"""Details per candidate spot: flat ground, distances to forest, roads and tracks, protected areas."""

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import rasterio
import shapely
from shapely import STRtree

from pipeline.dem import mosaic
from pipeline.tiles import parse_tile_id, tile_bounds

FLAT_SLOPE_PCT = 5.0       # a cell is flat when its slope is at most this
FLAT_RADIUS_M = 100.0      # flat area is counted within this radius of the spot
DIST_CAP_M = 5000.0        # distances are capped here; also the search margin around a tile
FOREST_LAYERS = {"LesniPudaSeStromy": None, "LesniPudaSKrovinatymPorostem": None}
ROAD_LAYERS = {"SilniceDalnice": ("typsil_k", ["S1", "S1p", "S1v", "S2", "S2p", "S2v", "S3", "S3p", "S3v"]),
               "SilniceNeevidovana": None,
               "Ulice": ("typulice_k", ["026", "926"])}
TRACK_LAYERS = {"Cesta": ("typcesty_k", ["026"])}
PROTECTED_BITS = {"np": 1, "chko": 2, "zchu": 4, "buffer": 8, "evl": 16, "po": 32, "contract": 64}
DETAIL_COLUMNS = ["candidate_id", "slope_pct", "flat_m2", "forest_m", "road_m", "track_m", "prot", "prot_sites", "border"]


def slope_percent(dem: np.ndarray, res_m: float, nodata: float = -9999.0) -> np.ndarray:
    """Slope in percent per cell (NaN where the cell or a neighbour has no data)."""
    z = np.where(dem == nodata, np.nan, dem.astype(np.float64))
    gy, gx = np.gradient(z, res_m)
    slope = 100.0 * np.hypot(gx, gy)
    slope[np.isnan(z)] = np.nan
    return slope


def flat_area_m2(slope: np.ndarray, transform, xs, ys, radius_m: float = FLAT_RADIUS_M,
                 max_slope: float = FLAT_SLOPE_PCT) -> tuple[np.ndarray, np.ndarray]:
    """Return (flat area in m2 within radius_m of each point, slope at the point's cell)."""
    res = transform.a
    n = int(radius_m // res)
    dr, dc = np.mgrid[-n:n + 1, -n:n + 1]
    disk = (dr * res) ** 2 + (dc * res) ** 2 <= radius_m ** 2
    dr, dc = dr[disk], dc[disk]
    rows, cols = rasterio.transform.rowcol(transform, np.asarray(xs, float), np.asarray(ys, float))
    rows, cols = np.asarray(rows), np.asarray(cols)
    rr, cc = rows[:, None] + dr[None, :], cols[:, None] + dc[None, :]
    inside = (rr >= 0) & (rr < slope.shape[0]) & (cc >= 0) & (cc < slope.shape[1])
    vals = slope[np.clip(rr, 0, slope.shape[0] - 1), np.clip(cc, 0, slope.shape[1] - 1)]
    flat = inside & (vals <= max_slope)
    here = slope[np.clip(rows, 0, slope.shape[0] - 1), np.clip(cols, 0, slope.shape[1] - 1)]
    return flat.sum(axis=1) * res * res, here


def nearest_distance(xs, ys, geoms, cap_m: float = DIST_CAP_M) -> np.ndarray:
    """Distance from each point to the nearest geometry (0 inside a polygon), capped at cap_m."""
    out = np.full(len(xs), float(cap_m))
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    if not geoms or len(xs) == 0:
        return out
    pts = shapely.points(np.asarray(xs, float), np.asarray(ys, float))
    (ip, _), dist = STRtree(geoms).query_nearest(pts, max_distance=cap_m, return_distance=True, all_matches=False)
    np.minimum.at(out, ip, dist)
    return out


def protected_flags(xs, ys, sites) -> tuple[np.ndarray, list[str]]:
    """Bit mask (PROTECTED_BITS) and ';'-joined site ids (in PROTECTED_BITS order) for each point."""
    n = len(xs)
    bits = np.zeros(n, dtype=np.int64)
    ids = [[] for _ in range(n)]
    if n == 0 or len(sites) == 0:
        return bits, ["" for _ in range(n)]
    pts = shapely.points(np.asarray(xs, float), np.asarray(ys, float))
    ip, isite = STRtree(list(sites.geometry)).query(pts, predicate="intersects")
    order = {c: k for k, c in enumerate(PROTECTED_BITS)}
    cats, sids = sites["category"].to_numpy(), sites["site_id"].to_numpy()
    for p, s in sorted(zip(ip, isite), key=lambda t: (t[0], order[cats[t[1]]], sids[t[1]])):
        bits[p] |= PROTECTED_BITS[cats[s]]
        ids[p].append(str(sids[s]))
    return bits, [";".join(v) for v in ids]


def border_flags(xs, ys, region, bounds, radius_m: float) -> np.ndarray:
    """1 where the edge of *region* (inside *bounds*) is closer than radius_m, else 0; all 0 without a region."""
    out = np.zeros(len(xs), dtype=np.int64)
    if region is None or len(xs) == 0:
        return out
    edge = shapely.intersection(region.boundary, shapely.box(*bounds))
    if edge.is_empty:
        return out
    d = shapely.distance(shapely.points(np.asarray(xs, float), np.asarray(ys, float)), edge)
    return (d < radius_m).astype(np.int64)


def read_layers(gpkg, layers: dict, bounds: tuple) -> list:
    """Geometries of *layers* inside *bounds*; a layer maps to None or (column, allowed values)."""
    out = []
    for name, rule in layers.items():
        cols = [] if rule is None else [rule[0]]
        df = pyogrio.read_dataframe(gpkg, layer=name, bbox=tuple(bounds), columns=cols)
        if rule is not None:
            df = df[df[rule[0]].astype(str).isin(rule[1])]
        out.extend(g for g in df.geometry if g is not None and not g.is_empty)
    return out


def tile_details(tile_id: str, dem_index: list, gpkg, protected_gpkg, screen_dir, res_m: float = 10.0,
                 region=None, radius_m: float = 10000.0) -> dict:
    """Write screen_dir/details.csv for the spots in screen_dir/candidates.csv; return counts."""
    screen_dir = Path(screen_dir)
    cands = pd.read_csv(screen_dir / "candidates.csv")
    xs, ys = cands["x"].to_numpy(float), cands["y"].to_numpy(float)
    ix, iy, size = parse_tile_id(tile_id)
    margin = 2 * FLAT_RADIUS_M
    dem_bounds = tile_bounds(ix, iy, size, margin)
    with tempfile.TemporaryDirectory() as tmp:
        mosaic(dem_index, dem_bounds, res_m, Path(tmp) / "dem.tif")
        with rasterio.open(Path(tmp) / "dem.tif") as ds:
            dem, transform = ds.read(1), ds.transform
    flat, slope_here = flat_area_m2(slope_percent(dem, res_m), transform, xs, ys)
    search = tile_bounds(ix, iy, size, DIST_CAP_M)
    sites = pyogrio.read_dataframe(protected_gpkg, layer="protected", bbox=tuple(search))
    bits, site_ids = protected_flags(xs, ys, sites)
    out = pd.DataFrame({
        "candidate_id": cands["candidate_id"],
        "slope_pct": np.round(slope_here, 1),
        "flat_m2": flat.astype(int),
        "forest_m": np.round(nearest_distance(xs, ys, read_layers(gpkg, FOREST_LAYERS, search))),
        "road_m": np.round(nearest_distance(xs, ys, read_layers(gpkg, ROAD_LAYERS, search))),
        "track_m": np.round(nearest_distance(xs, ys, read_layers(gpkg, {**ROAD_LAYERS, **TRACK_LAYERS}, search))),
        "prot": bits,
        "prot_sites": site_ids,
        "border": border_flags(xs, ys, region, tile_bounds(ix, iy, size, radius_m), radius_m),
    }, columns=DETAIL_COLUMNS)
    out.to_csv(screen_dir / "details.csv", index=False)
    return {"tile_id": tile_id, "spots": len(out), "protected": int((bits > 0).sum())}
