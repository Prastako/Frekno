"""Pack the screening results of a tile into the binary file the website reads.

File = 16-byte header, then one fixed-size record per spot (little-endian, no padding):
lon, lat (float32, WGS84); site type and forest percent (uint8); then for each layer in
LAYERS a receptor count (uint8) and K receptor slots. A slot holds the nine band
attenuations from 1 m (uint8, ATT_STEP_DB steps, capped at 255 steps), the distance
(uint16, metres) and the true bearing from the spot (uint8, 360/256 degree steps).
Receptors are the loudest per layer for the reference rig; facility layers keep one
receptor per area.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Geod, Transformer

from pipeline.select import TYPES as LAYERS

MAGIC = b"FRK1"
VERSION = 1
K = 5
ATT_STEP_DB = 0.5
BAND_KEYS = ["a31", "a63", "a125", "a250", "a500", "a1k", "a2k", "a4k", "a8k"]
BANDS_HZ = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000]
SITE_CODES = {"open": 0, "clearing": 1, "forest": 2}
HEADER = np.dtype([("magic", "S4"), ("version", "<u2"), ("layers", "u1"), ("k", "u1"),
                   ("bands", "u1"), ("pad", "u1"), ("spots", "<u4"), ("pad2", "<u2")])
SLOT = np.dtype([("att", "u1", (len(BAND_KEYS),)), ("dist", "<u2"), ("brg", "u1")])
LAYER = np.dtype([("n", "u1"), ("r", SLOT, (K,))])
SPOT = np.dtype([("lon", "<f4"), ("lat", "<f4"), ("site", "u1"), ("forest", "u1"),
                 ("layers", LAYER, (len(LAYERS),))])

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


def area_key(receptor_id: str) -> str:
    """Facility points 'zbg<fid>_<k>' share the key 'zbg<fid>'; other ids are their own key."""
    return receptor_id.rsplit("_", 1)[0] if receptor_id.startswith("zbg") else receptor_id


def pack_records(cands: pd.DataFrame, pairs: pd.DataFrame) -> np.ndarray:
    """Build the SPOT records for one tile from candidates.csv and pairs.csv rows."""
    n = len(cands)
    rec = np.zeros(n, dtype=SPOT)
    if n == 0:
        return rec
    lon, lat, north = grid_north(cands["x"], cands["y"])
    rec["lon"], rec["lat"] = lon, lat
    rec["site"] = cands["site_type"].map(SITE_CODES).to_numpy()
    rec["forest"] = np.clip(np.rint(cands["forest_frac"].to_numpy(float) * 100), 0, 100)
    row_of = pd.Series(np.arange(n), index=cands["candidate_id"].to_numpy())
    p = pairs.sort_values(["candidate_id", "receptor_type", "rank"], kind="stable")
    p = p.assign(key=p["receptor_id"].astype(str).map(area_key))
    p = p.drop_duplicates(["candidate_id", "receptor_type", "key"])
    lay = rec["layers"]
    for li, layer in enumerate(LAYERS):
        s = p[p["receptor_type"] == layer]
        s = s.assign(slot=s.groupby("candidate_id").cumcount())
        s = s[s["slot"] < K]
        rows = row_of.loc[s["candidate_id"].to_numpy()].to_numpy()
        slots = s["slot"].to_numpy()
        slot_view = lay["r"][:, li]
        slot_view["att"][rows, slots] = np.clip(np.rint(s[BAND_KEYS].to_numpy(float) / ATT_STEP_DB), 0, 255)
        slot_view["dist"][rows, slots] = np.clip(np.rint(s["dist_m"].to_numpy(float)), 0, 65535)
        true_brg = (s["bearing_deg"].to_numpy(float) + north[rows]) % 360.0
        slot_view["brg"][rows, slots] = np.rint(true_brg * 256.0 / 360.0).astype(int) % 256
        lay["n"][:, li] = np.bincount(rows, minlength=n)
    return rec


def write_tile(rec: np.ndarray, path) -> int:
    """Write header and records to *path*; return the file size in bytes."""
    hdr = np.zeros(1, dtype=HEADER)
    hdr["magic"], hdr["version"], hdr["spots"] = MAGIC, VERSION, len(rec)
    hdr["layers"], hdr["k"], hdr["bands"] = len(LAYERS), K, len(BAND_KEYS)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = hdr.tobytes() + rec.tobytes()
    path.write_bytes(data)
    return len(data)


def read_tile(path) -> tuple[dict, np.ndarray]:
    """Read a tile file back: (header as dict, SPOT records)."""
    data = Path(path).read_bytes()
    hdr = np.frombuffer(data[:HEADER.itemsize], dtype=HEADER)[0]
    if hdr["magic"] != MAGIC or hdr["version"] != VERSION:
        raise ValueError(f"not a version {VERSION} tile file: {path}")
    head = {k: (hdr[k].item() if k != "magic" else hdr[k].decode()) for k in ("magic", "version", "layers", "k", "bands", "spots")}
    return head, np.frombuffer(data[HEADER.itemsize:], dtype=SPOT, count=int(hdr["spots"]))


def pack_region(screen_dir, site_dir) -> dict:
    """Pack every tile folder of *screen_dir* into site_dir/tiles/<tile>.bin and write site_dir/index.json."""
    screen_dir, site_dir = Path(screen_dir), Path(site_dir)
    tiles = []
    for d in sorted(p for p in screen_dir.iterdir() if (p / "candidates.csv").exists() and (p / "pairs.csv").exists()):
        cands = pd.read_csv(d / "candidates.csv")
        if len(cands) == 0:
            continue
        rec = pack_records(cands, pd.read_csv(d / "pairs.csv", dtype={"receptor_id": str}))
        size = write_tile(rec, site_dir / "tiles" / f"{d.name}.bin")
        tiles.append({"id": d.name, "file": f"tiles/{d.name}.bin", "spots": int(len(rec)), "bytes": size,
                      "bbox": [round(float(v), 6) for v in (rec["lon"].min(), rec["lat"].min(), rec["lon"].max(), rec["lat"].max())]})
    index = {"format": MAGIC.decode(), "version": VERSION, "layers": list(LAYERS), "bands_hz": BANDS_HZ, "k": K,
             "att_step_db": ATT_STEP_DB, "site_codes": SITE_CODES, "tiles": tiles,
             "attribution": "ČÚZK (RÚIAN, ZABAGED, DMR 4G), CC BY 4.0"}
    (site_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"tiles": len(tiles), "spots": sum(t["spots"] for t in tiles), "bytes": sum(t["bytes"] for t in tiles)}
