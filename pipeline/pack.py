"""Pack the screening results and spot details of a tile into the gzip file the website reads.

Tile file = gzip of a 16-byte header and one fixed-size record per spot (little-endian, no padding).
Record: lon, lat (float32, WGS84); x, y (int32, S-JTSK metres, for the cadastre link); site type,
forest percent, slope percent (255 = unknown), protected bits (uint8; BORDER_BIT = receptors beyond
the region edge may be missing); flat area in m2 and the
distances in metres to forest, road and track (uint16); MAX_SITES indices into protected.json
(uint16, NO_SITE = none); then for each layer in LAYERS a slot count, a floor and K slots.
A slot is the loudest receptor (reference rig) of one sector of true bearing: nine band
attenuations from 1 m (uint8, ATT_STEP_DB steps), distance (uint16, metres), true bearing (uint8,
360/256 degree steps; sector = bearing >> 5). Slots are sorted loudest first. The floor says how far
below slot 0 (reference rig, FLOOR_STEP_DB steps, rounded down) receptors outside the slots'
sectors can be: the last screened receptor when the screened list was full, and the sectors after
the K loudest. NO_FLOOR = no such receptors.
"""

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
from pyproj import Geod, Transformer

from pipeline.acoustics import A_WEIGHTING_DB, air_absorption_db_per_km, load_acoustics
from pipeline.details import DIST_CAP_M, FLAT_RADIUS_M, FLAT_SLOPE_PCT, PROTECTED_BITS
from pipeline.freefield import levels_for
from pipeline.select import TYPES as LAYERS
from pipeline.tiles import parse_tile_id, tile_bounds

MAGIC = b"FRK1"
VERSION = 2
K = 6
SECTORS = 8
MAX_SITES = 4
NO_SITE = 65535
NO_FLOOR = 255
BORDER_BIT = 128  # in the protected-bits byte: receptors beyond the region edge may be missing
ATT_STEP_DB = 0.5
FLOOR_STEP_DB = 0.25
BAND_KEYS = ["a31", "a63", "a125", "a250", "a500", "a1k", "a2k", "a4k", "a8k"]
BANDS_HZ = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000]
SITE_CODES = {"open": 0, "clearing": 1, "forest": 2}
HEADER = np.dtype([("magic", "S4"), ("version", "<u2"), ("layers", "u1"), ("k", "u1"),
                   ("bands", "u1"), ("pad", "u1"), ("spots", "<u4"), ("pad2", "<u2")])
SLOT = np.dtype([("att", "u1", (len(BAND_KEYS),)), ("dist", "<u2"), ("brg", "u1")])
LAYER = np.dtype([("n", "u1"), ("floor", "u1"), ("r", SLOT, (K,))])
SPOT = np.dtype([("lon", "<f4"), ("lat", "<f4"), ("x", "<i4"), ("y", "<i4"),
                 ("site", "u1"), ("forest", "u1"), ("slope", "u1"), ("prot", "u1"),
                 ("flat", "<u2"), ("forest_m", "<u2"), ("road_m", "<u2"), ("track_m", "<u2"),
                 ("sites", "<u2", (MAX_SITES,)), ("layers", LAYER, (len(LAYERS),))])

_TO_WGS = Transformer.from_crs("EPSG:5514", "EPSG:4326", always_xy=True)
_GEOD = Geod(ellps="WGS84")


def grid_north(x, y):
    """Return (lon, lat, azimuth): WGS84 position and true azimuth of the S-JTSK +y direction."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    lon, lat = _TO_WGS.transform(x, y)
    lon1, lat1 = _TO_WGS.transform(x, y + 100.0)
    az, _, _ = _GEOD.inv(lon, lat, lon1, lat1)
    return np.asarray(lon), np.asarray(lat), np.asarray(az) % 360.0


def site_indices(prot_sites: pd.Series, site_ids: np.ndarray) -> np.ndarray:
    """MAX_SITES indices per spot into the sorted *site_ids* for ';'-joined ids (NO_SITE = none)."""
    out = np.full((len(prot_sites), MAX_SITES), NO_SITE, dtype=np.uint16)
    for i, text in enumerate(prot_sites.fillna("").astype(str)):
        ids = [v for v in text.split(";") if v][:MAX_SITES]
        if not ids:
            continue
        idx = np.searchsorted(site_ids, ids)
        if np.any(idx >= len(site_ids)) or np.any(site_ids[np.minimum(idx, len(site_ids) - 1)] != ids):
            raise ValueError(f"unknown protected site id in {text!r}")
        out[i, :len(ids)] = idx
    return out


def pack_records(cands: pd.DataFrame, pairs: pd.DataFrame, details: pd.DataFrame,
                 site_ids: np.ndarray, list_cap: int = 20) -> np.ndarray:
    """Build the SPOT records for one tile from candidates.csv, pairs.csv and details.csv rows."""
    n = len(cands)
    rec = np.zeros(n, dtype=SPOT)
    if n == 0:
        return rec
    lon, lat, north = grid_north(cands["x"], cands["y"])
    rec["lon"], rec["lat"] = lon, lat
    rec["x"], rec["y"] = np.rint(cands["x"].to_numpy(float)), np.rint(cands["y"].to_numpy(float))
    rec["site"] = cands["site_type"].map(SITE_CODES).to_numpy()
    rec["forest"] = np.clip(np.rint(cands["forest_frac"].to_numpy(float) * 100), 0, 100)
    det = details.set_index("candidate_id").loc[cands["candidate_id"].to_numpy()]
    slope = det["slope_pct"].to_numpy(float)
    rec["slope"] = np.where(np.isnan(slope), 255, np.clip(np.rint(np.nan_to_num(slope)), 0, 254))
    border = det["border"].fillna(0).to_numpy(int) if "border" in det.columns else np.zeros(n, dtype=int)
    rec["prot"] = det["prot"].to_numpy(int) | np.where(border > 0, BORDER_BIT, 0)
    for col, key in (("flat", "flat_m2"), ("forest_m", "forest_m"), ("road_m", "road_m"), ("track_m", "track_m")):
        rec[col] = np.clip(np.rint(det[key].to_numpy(float)), 0, 65535)
    rec["sites"] = site_indices(det["prot_sites"], site_ids)
    lay = rec["layers"]
    lay["floor"] = NO_FLOOR
    row_of = pd.Series(np.arange(n), index=cands["candidate_id"].to_numpy())
    p = pairs.sort_values(["candidate_id", "receptor_type", "rank"], kind="stable")
    rows = row_of.loc[p["candidate_id"].to_numpy()].to_numpy()
    true_brg = (p["bearing_deg"].to_numpy(float) + north[rows]) % 360.0
    brg = np.rint(true_brg * 256.0 / 360.0).astype(int) % 256
    p = p.assign(row=rows, brg=brg, sec=brg // (256 // SECTORS))
    for li, layer in enumerate(LAYERS):
        s = p[p["receptor_type"] == layer]
        if len(s) == 0:
            continue
        top = s.drop_duplicates(["row", "sec"])
        top = top.assign(slot=top.groupby("row").cumcount())
        kept, dropped = top[top["slot"] < K], top[top["slot"] >= K]
        r, k = kept["row"].to_numpy(), kept["slot"].to_numpy()
        view = lay["r"][:, li]
        view["att"][r, k] = np.clip(np.rint(kept[BAND_KEYS].to_numpy(float) / ATT_STEP_DB), 0, 255)
        view["dist"][r, k] = np.clip(np.rint(kept["dist_m"].to_numpy(float)), 0, 65535)
        view["brg"][r, k] = kept["brg"].to_numpy()
        lay["n"][:, li] = np.bincount(r, minlength=n)
        g = s.groupby("row")["ref_level_dba"]
        lead, last, count = g.first(), g.last(), g.size()
        floor = pd.Series(np.where(count.to_numpy() >= list_cap, last.to_numpy(), -np.inf), index=lead.index)
        if len(dropped):
            dmax = dropped.groupby("row")["ref_level_dba"].max()
            floor.loc[dmax.index] = np.maximum(floor.loc[dmax.index].to_numpy(), dmax.to_numpy())
        has = np.isfinite(floor.to_numpy())
        steps = np.floor((lead.to_numpy() - np.where(has, floor.to_numpy(), 0.0)) / FLOOR_STEP_DB)
        lay["floor"][lead.index.to_numpy(), li] = np.where(has, np.clip(steps, 0, NO_FLOOR - 1), NO_FLOOR)
    return rec


def write_tile(rec: np.ndarray, path) -> int:
    """Write header and records gzip-compressed to *path*; return the file size in bytes."""
    hdr = np.zeros(1, dtype=HEADER)
    hdr["magic"], hdr["version"], hdr["spots"] = MAGIC, VERSION, len(rec)
    hdr["layers"], hdr["k"], hdr["bands"] = len(LAYERS), K, len(BAND_KEYS)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = gzip.compress(hdr.tobytes() + rec.tobytes(), compresslevel=9, mtime=0)
    path.write_bytes(data)
    return len(data)


def read_tile(path) -> tuple[dict, np.ndarray]:
    """Read a tile file back (gzip or plain): (header as dict, SPOT records)."""
    data = Path(path).read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    hdr = np.frombuffer(data[:HEADER.itemsize], dtype=HEADER)[0]
    if hdr["magic"] != MAGIC or hdr["version"] != VERSION:
        raise ValueError(f"not a version {VERSION} tile file: {path}")
    head = {k: (hdr[k].item() if k != "magic" else hdr[k].decode()) for k in ("magic", "version", "layers", "k", "bands", "spots")}
    return head, np.frombuffer(data[HEADER.itemsize:], dtype=SPOT, count=int(hdr["spots"]))


def model_block() -> dict:
    """Acoustic constants the website needs, from config/acoustics.json."""
    ac = load_acoustics()
    w = ac["weather"]
    alpha = air_absorption_db_per_km(w["temperature_c"], w["humidity_percent"], w["pressure_kpa"])
    return {"a_weighting_db": list(A_WEIGHTING_DB), "alpha_db_per_km": [round(float(a), 4) for a in alpha],
            "classes": ac["classes"], "characters": ac["characters"], "cardioid": ac["cardioid"],
            "source_1m_db": {c: {ch: [round(v, 4) for v in levels_for(c, ch, 1.0)] for ch in ac["characters"]}
                             for c in ac["classes"]}}


def read_sites(protected_gpkg) -> pd.DataFrame:
    """Protected sites (site_id, category, name) from the prepared GeoPackage, sorted by site_id."""
    sites = pyogrio.read_dataframe(protected_gpkg, layer="protected", read_geometry=False,
                                   columns=["site_id", "category", "name"])
    return sites.astype(str).sort_values("site_id", kind="stable").reset_index(drop=True)


def pack_tile(tile_dir, site_dir, site_ids: np.ndarray, list_cap: int = 20) -> dict | None:
    """Pack one screened tile folder into site_dir/tiles/<tile>.bin.gz; return its index entry (None without spots)."""
    d = Path(tile_dir)
    cands = pd.read_csv(d / "candidates.csv")
    if len(cands) == 0:
        return None
    if not (d / "details.csv").exists():
        raise FileNotFoundError(f"details.csv missing in {d}")
    details = pd.read_csv(d / "details.csv", dtype={"prot_sites": str})
    rec = pack_records(cands, pd.read_csv(d / "pairs.csv", dtype={"receptor_id": str}), details, site_ids, list_cap)
    size = write_tile(rec, Path(site_dir) / "tiles" / f"{d.name}.bin.gz")
    worst = cands[[f"worst_{t}_dba" for t in LAYERS]].max(axis=1).min()
    ix, iy, tile_m = parse_tile_id(d.name)
    x0, y0, x1, y1 = tile_bounds(ix, iy, tile_m)
    lon, lat = _TO_WGS.transform([x0, x1, x1, x0], [y0, y0, y1, y1])
    return {"id": d.name, "file": f"tiles/{d.name}.bin.gz", "spots": int(len(rec)), "bytes": size,
            "bbox": [round(float(v), 6) for v in (rec["lon"].min(), rec["lat"].min(), rec["lon"].max(), rec["lat"].max())],
            "outline": [[round(float(a), 5), round(float(b), 5)] for a, b in zip(lon, lat)],
            "ref_min_dba": None if pd.isna(worst) else round(float(worst), 1)}


def write_index(site_dir, tiles: list[dict], sites: pd.DataFrame) -> dict:
    """Write site_dir/index.json (tiles sorted by id) and protected.json; return totals."""
    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    tiles = sorted(tiles, key=lambda t: t["id"])
    prot = {"bits": PROTECTED_BITS, "sites": sites[["site_id", "category", "name"]].values.tolist()}
    (site_dir / "protected.json").write_text(json.dumps(prot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    index = {"format": MAGIC.decode(), "version": VERSION, "layers": list(LAYERS), "bands_hz": BANDS_HZ, "k": K,
             "sectors": SECTORS, "att_step_db": ATT_STEP_DB, "floor_step_db": FLOOR_STEP_DB, "max_sites": MAX_SITES,
             "site_codes": SITE_CODES, "protected_bits": PROTECTED_BITS, "border_bit": BORDER_BIT,
             "protected_file": "protected.json",
             "details": {"flat_radius_m": FLAT_RADIUS_M, "flat_slope_pct": FLAT_SLOPE_PCT, "dist_cap_m": DIST_CAP_M},
             "model": model_block(), "tiles": tiles,
             "attribution": "ČÚZK (RÚIAN, ZABAGED, DMR 4G), CC BY 4.0; AOPK ČR (chráněná území), CC BY 4.0"}
    (site_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"tiles": len(tiles), "spots": sum(t["spots"] for t in tiles), "bytes": sum(t["bytes"] for t in tiles)}


def pack_region(screen_dir, site_dir, protected_gpkg, list_cap: int = 20) -> dict:
    """Pack every tile folder of *screen_dir* into site_dir/tiles/<tile>.bin.gz; write index.json and protected.json."""
    sites = read_sites(protected_gpkg)
    ids = sites["site_id"].to_numpy()
    tiles = []
    for d in sorted(p for p in Path(screen_dir).iterdir() if (p / "candidates.csv").exists() and (p / "pairs.csv").exists()):
        meta = pack_tile(d, site_dir, ids, list_cap)
        if meta is not None:
            tiles.append(meta)
    return write_index(site_dir, tiles, sites)