"""NoiseModelling for chosen candidates of a screened tile, compared with the screening."""

import csv
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from scipy.ndimage import distance_transform_edt
from shapely.geometry import box

from pipeline.dem import NODATA, mosaic, sheets_for_bounds
from pipeline.landcover import (
    grid_shape,
    hard_mask,
    landcover_masks,
    ground_polygons,
    write_ground_geojson,
)
from pipeline.nm_io import (
    attenuation_from_1m,
    read_receivers_level,
    write_asc,
    write_dummy_building_geojson,
    write_points_geojson,
)
from pipeline.nm_run import build_steps, run_steps
from pipeline.tile_screen import tile_parts

VARIANTS = ("zabaged", "hard", "soft")

SCREEN_KEYS = ["a63", "a125", "a250", "a500", "a1k", "a2k", "a4k", "a8k"]

NM_KEYS = ["nm63", "nm125", "nm250", "nm500", "nm1k", "nm2k", "nm4k", "nm8k"]

COMPARE_COLUMNS = (
    ["variant", "res_m", "candidate_id", "receptor_id", "receptor_type", "rank", "dist_m"]
    + SCREEN_KEYS
    + NM_KEYS
)


def pick_spread(values, n):
    """Return indices of finite values sorted by value (stable), evenly spread to n."""
    arr = np.asarray(values, dtype=float)
    finite_indices = np.where(np.isfinite(arr))[0]
    order = finite_indices[np.argsort(arr[finite_indices], kind="stable")]
    finite_count = len(order)
    if finite_count <= n:
        return order
    indices = np.round(np.linspace(0, finite_count - 1, n)).astype(int)
    unique_indices = np.unique(indices)
    return order[unique_indices]


def fill_nodata(dem, nodata=NODATA):
    """Fill nodata/NaN cells with the value of the nearest valid cell."""
    out = np.asarray(dem, dtype=np.float64)
    bad = (out == nodata) | np.isnan(out)
    if not np.any(bad):
        return out
    if not np.any(~bad):
        raise ValueError("no valid cell")
    distances, indices = distance_transform_edt(bad, return_distances=True, return_indices=True)
    out[bad] = out[indices[0][bad], indices[1][bad]]
    return out


def nm_inputs(tile_id, settings, dem_index, gpkg, cands_csv, pairs_csv, work_dir, variant, res_m, n_cand):
    """Prepare all NoiseModelling input files for a single variant and resolution."""
    if variant not in VARIANTS:
        raise ValueError(f"variant {variant!r} not in {VARIANTS}")

    work_dir.mkdir(parents=True, exist_ok=True)

    buf = tile_parts(tile_id, settings["tiles"]["buffer_m"])[1]
    keep = settings["receptors"]["worst_per_type_for_nm"]

    # Select candidates
    cands = pd.read_csv(cands_csv)
    worst = np.fmax(cands["worst_home_dba"].values.astype(np.float64),
                    cands["worst_cottage_dba"].values.astype(np.float64))
    chosen = cands.iloc[pick_spread(worst, n_cand)]

    # Filter pairs
    pairs = pd.read_csv(pairs_csv, dtype={"receptor_id": str})
    kept = pairs[pairs["candidate_id"].isin(chosen["candidate_id"]) & (pairs["rank"] <= keep)]
    rcv = kept.drop_duplicates(subset="receptor_id", keep="first")

    # Source/receiver maps
    sources_map = pd.DataFrame({
        "pk": np.arange(1, len(chosen) + 1),
        "candidate_id": chosen["candidate_id"].values,
        "x": chosen["x"].values,
        "y": chosen["y"].values,
    })
    sources_map.to_csv(work_dir / "sources_map.csv", index=False)

    receivers_map = pd.DataFrame({
        "pk": np.arange(1, len(rcv) + 1),
        "receptor_id": rcv["receptor_id"].values,
        "x": rcv["rx"].values,
        "y": rcv["ry"].values,
    })
    receivers_map.to_csv(work_dir / "receivers_map.csv", index=False)

    kept.to_csv(work_dir / "pairs_of_interest.csv", index=False)

    # GeoJSON for sources and receivers
    write_points_geojson(
        work_dir / "sources.geojson",
        sources_map["pk"].values,
        sources_map["x"].values,
        sources_map["y"].values,
        [float(settings["source"]["height_m"])] * len(sources_map),
    )
    write_points_geojson(
        work_dir / "receivers.geojson",
        receivers_map["pk"].values,
        receivers_map["x"].values,
        receivers_map["y"].values,
        [float(settings["receptors"]["height_m"])] * len(receivers_map),
    )

    # DEM
    dem_info = mosaic(sheets_for_bounds(dem_index, buf), buf, res_m, work_dir / "dem.tif")
    with rasterio.open(work_dir / "dem.tif") as src:
        dem = src.read(1)
        transform = src.transform
    write_asc(fill_nodata(dem), transform, work_dir / "dem.asc")

    # Ground
    if variant == "zabaged":
        polys = ground_polygons(
            hard_mask(landcover_masks(gpkg, buf, res_m)),
            grid_shape(buf, res_m)[2],
        )
    elif variant == "hard":
        polys = [(box(*buf), 0.0)]
    else:  # soft
        polys = [(box(*buf), 1.0)]
    write_ground_geojson(polys, work_dir / "ground.geojson")

    # Buildings (dummy)
    write_dummy_building_geojson(work_dir / "buildings.geojson", buf[0] + 10.0, buf[1] + 10.0)

    return {
        "sources": len(chosen),
        "receivers": len(rcv),
        "pairs_of_interest": len(kept),
        "ground_polygons": len(polys),
        "dem_cells": dem.size,
        "dem_nodata_cells": dem_info["nodata_cells"],
    }


def nm_compare(work_dir, variant, res_m):
    """Compare NoiseModelling results with screening attenuations."""
    src_map = pd.read_csv(work_dir / "sources_map.csv")
    rcv_map = pd.read_csv(work_dir / "receivers_map.csv", dtype={"receptor_id": str})

    pk_to_cand = dict(zip(src_map["pk"], src_map["candidate_id"]))
    pk_to_rcpt = dict(zip(rcv_map["pk"], rcv_map["receptor_id"]))

    levels = read_receivers_level(work_dir / "out" / "receivers_level.csv")
    attenuations = {}
    for entry in levels:
        cand_id = pk_to_cand[entry["source_id"]]
        rcpt_id = pk_to_rcpt[entry["receiver_id"]]
        attenuations[(cand_id, rcpt_id)] = attenuation_from_1m(entry["levels"])

    pairs = pd.read_csv(work_dir / "pairs_of_interest.csv", dtype={"receptor_id": str})
    rows = []
    missing = 0
    for _, row in pairs.iterrows():
        key = (int(row["candidate_id"]), str(row["receptor_id"]))
        if key not in attenuations:
            missing += 1
            continue
        att = attenuations[key]
        rows.append({
            "variant": variant,
            "res_m": float(res_m),
            "candidate_id": int(row["candidate_id"]),
            "receptor_id": str(row["receptor_id"]),
            "receptor_type": row["receptor_type"],
            "rank": int(row["rank"]),
            "dist_m": float(row["dist_m"]),
            **{k: float(row[k]) for k in SCREEN_KEYS},
            **{k: float(v) for k, v in zip(NM_KEYS, att)},
        })
    return rows, missing


def nm_tile(tile_id, settings, dem_index, gpkg, screen_dir, work_dir, nm_home, java,
            variant="zabaged", res_m=None, n_cand=None, java_opts="", timeout_s=None,
            metrics_csv=None):
    """Run NoiseModelling for a screened tile and compare results."""
    res = float(res_m or settings["terrain"]["nm_resolution_m"])
    n = int(n_cand or settings["noisemodelling"]["candidates_per_sample_tile"])

    # Prepare inputs
    t0 = time.monotonic()
    info = nm_inputs(
        tile_id, settings, dem_index, gpkg,
        screen_dir / "candidates.csv", screen_dir / "pairs.csv",
        work_dir, variant, res, n,
    )
    inputs_s = time.monotonic() - t0

    # Run NoiseModelling
    (work_dir / "out").mkdir(exist_ok=True)

    inputs = {
        "dem": work_dir / "dem.asc",
        "ground": work_dir / "ground.geojson",
        "buildings": work_dir / "buildings.geojson",
        "sources": work_dir / "sources.geojson",
        "receivers": work_dir / "receivers.geojson",
        "result_csv": work_dir / "out" / "receivers_level.csv",
    }
    params = {
        "max_distance_m": settings["noisemodelling"]["max_source_distance_m"],
        "humidity_percent": settings["weather"]["humidity_percent"],
        "temperature_c": settings["weather"]["temperature_c"],
        "favourable": settings["weather"]["favourable_occurrence"],
        "threads": settings["noisemodelling"]["threads"],
    }
    steps = build_steps(nm_home, work_dir / "ws", inputs, params)
    run_rows = run_steps(
        steps, java,
        metrics_csv or work_dir / "metrics.csv",
        work_dir,
        java_opts,
        timeout_s,
        prefix=f"{tile_id}_{variant}_{int(res)}m_",
    )

    ok = len(run_rows) == 7 and all(r["exit_code"] == 0 for r in run_rows)

    if ok:
        compare_rows, missing = nm_compare(work_dir, variant, res)
        with open(work_dir / "compare.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COMPARE_COLUMNS)
            w.writeheader()
            for row in compare_rows:
                formatted = dict(row)
                for k in ["res_m", "dist_m"] + SCREEN_KEYS + NM_KEYS:
                    if k in formatted and isinstance(formatted[k], float):
                        formatted[k] = repr(formatted[k])
                w.writerow(formatted)
    else:
        compare_rows = []
        missing = None

    summary = {
        "tile_id": tile_id,
        "variant": variant,
        "res_m": res,
        "ok": ok,
        **info,
        "inputs_s": inputs_s,
        "steps": [{"step": r["step"], "wall_s": r["wall_s"],
                    "peak_rss_mb": r["peak_rss_mb"], "exit_code": r["exit_code"]}
                  for r in run_rows],
        "compared": len(compare_rows),
        "missing": missing,
    }
    with open(work_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=1)
    return summary
