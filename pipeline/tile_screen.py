"""Screen all candidate spots of a single tile and write results."""

import json
import time
from pathlib import Path

import numpy as np
import rasterio

from pipeline.candidates import build_candidates
from pipeline.dem import mosaic, sheets_for_bounds
from pipeline.landcover import landcover_masks
from pipeline.screening import PAIR_COLUMNS, screen_candidates
from pipeline.settings import screening_cfg
from pipeline.tiles import parse_tile_id, tile_bounds

CANDIDATE_OUT_COLUMNS = [
    "candidate_id", "x", "y", "site_type", "forest_frac",
    "n_home", "n_cottage", "worst_home_dba", "worst_cottage_dba",
    "worst_home_63", "worst_cottage_63",
]


def tile_parts(tile_id: str, buffer_m: float) -> tuple:
    """Return (tile bounds, buffered bounds)."""
    ix, iy, size = parse_tile_id(tile_id)
    return (tile_bounds(ix, iy, size), tile_bounds(ix, iy, size, buffer_m))


def receptors_in_bounds(rec: dict, bounds: tuple) -> dict:
    """Keep receptors whose coordinates fall inside *bounds* (inclusive)."""
    xmin, ymin, xmax, ymax = bounds
    mask = (
        (rec["x"] >= xmin) & (rec["x"] <= xmax) &
        (rec["y"] >= ymin) & (rec["y"] <= ymax)
    )
    return {k: v[mask] for k, v in rec.items()}


def _format_field(value):
    """Format a single field for CSV output."""
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)
    return str(value)


def write_rows(rows: list, columns: list, path: Path):
    """Write *rows* as CSV with *columns* as header."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(columns)]
    for row in rows:
        lines.append(",".join(_format_field(row[c]) for c in columns))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def screen_tile(
    tile_id: str,
    settings: dict,
    region,
    dem_index: list,
    gpkg: Path,
    rec: dict,
    out_dir: Path,
    write_pairs: bool = False,
    keep_dem: bool = False,
) -> dict:
    """Screen all candidate spots of *tile_id* and write results to *out_dir*."""
    out_dir.mkdir(parents=True, exist_ok=True)

    bounds, buf = tile_parts(tile_id, settings["tiles"]["buffer_m"])
    res = settings["terrain"]["screening_resolution_m"]

    # ── DEM ──────────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    dem_path = out_dir / "dem_screening.tif"
    stats = mosaic(sheets_for_bounds(dem_index, buf), buf, res, dem_path)
    with rasterio.open(dem_path) as ds:
        dem = ds.read(1)
        transform = ds.transform
    if not keep_dem:
        dem_path.unlink()
    t_dem = time.perf_counter() - t0

    valid = dem != -9999.0
    if valid.any():
        dem_min = float(np.min(dem[valid]))
        dem_max = float(np.max(dem[valid]))
        dem_std = float(np.std(dem[valid]))
    else:
        dem_min = None
        dem_max = None
        dem_std = None

    # ── Land cover ───────────────────────────────────────────────────────
    t1 = time.perf_counter()
    masks = landcover_masks(gpkg, buf, res)
    t_landcover = time.perf_counter() - t1

    # ── Receptors in buffered bounds ─────────────────────────────────────
    sub = receptors_in_bounds(rec, buf)
    homes = sub["type"] == "home"

    # ── Candidates ───────────────────────────────────────────────────────
    t2 = time.perf_counter()
    c = build_candidates(
        region, bounds,
        settings["candidates"]["grid_m"],
        masks, transform,
        sub["x"][homes], sub["y"][homes],
        settings["candidates"]["min_distance_to_home_m"],
        settings["candidates"]["forest_radius_m"],
    )
    t_candidates = time.perf_counter() - t2

    # ── Screening ────────────────────────────────────────────────────────
    t3 = time.perf_counter()
    cands, pairs = screen_candidates(
        dem, transform,
        c["x"], c["y"],
        sub["x"], sub["y"], sub["type"], sub["id"],
        screening_cfg(settings),
    )
    t_screening = time.perf_counter() - t3

    # ── Write results ────────────────────────────────────────────────────
    t4 = time.perf_counter()

    for i, cand in enumerate(cands):
        cand["site_type"] = str(c["site_type"][i])
        cand["forest_frac"] = float(c["forest_frac"][i])

    write_rows(cands, CANDIDATE_OUT_COLUMNS, out_dir / "candidates.csv")
    if write_pairs:
        write_rows(pairs, PAIR_COLUMNS, out_dir / "pairs.csv")

    summary = {
        "tile_id": tile_id,
        "bounds": list(bounds),
        "buffered_bounds": list(buf),
        "grid": c["stats"]["grid"],
        "landcover": c["stats"]["landcover"],
        "near_home": c["stats"]["near_home"],
        "kept": c["stats"]["kept"],
        "receptors_home": int(np.sum(homes)),
        "receptors_cottage": int(np.sum(sub["type"] == "cottage")),
        "dem_sheets": stats["sheets"],
        "dem_nodata_cells": stats["nodata_cells"],
        "dem_min": dem_min,
        "dem_max": dem_max,
        "dem_std": dem_std,
        "pairs": len(pairs),
        "dem_s": t_dem,
        "landcover_s": t_landcover,
        "candidates_s": t_candidates,
        "screening_s": t_screening,
        "write_s": time.perf_counter() - t4,
    }

    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(summary, indent=1))

    return summary
