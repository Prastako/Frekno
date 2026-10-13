"""Region preparation: outline, tiles, buildings, receptors, terrain index."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from shapely.geometry import box, mapping, shape

from pipeline.dem import build_index, write_index_csv
from pipeline.fetch.ruian_shp import read_obec_buildings, read_region, write_buildings_csv
from pipeline.receptors import (
    build_receptors,
    load_type_map,
    read_buildings_csv,
    write_receptors_csv,
)
from pipeline.tiles import parse_tile_id, tile_bounds, tiles_for_geometry

logger = logging.getLogger(__name__)

TILE_COLUMNS = [
    "tile_id", "ix", "iy", "xmin", "ymin", "xmax", "ymax", "region_km2", "full",
]


# -- Region outline (GeoJSON) ---------------------------------------------

def write_region_geojson(geom: Any, path: str | Path) -> None:
    """Write *geom* as a single-feature GeoJSON file.

    Creates parent directories if needed; writes UTF-8.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": mapping(geom),
            }
        ],
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False)


def read_region_geojson(path: str | Path) -> Any:
    """Return the geometry of the first feature in a GeoJSON file."""
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return shape(data["features"][0]["geometry"])


# -- Tile rows ------------------------------------------------------------

def tile_rows(region: Any, size_m: int) -> list[dict]:
    """Build tile dictionaries for every tile that overlaps *region*."""
    rows: list[dict] = []
    for tid in tiles_for_geometry(region, size_m):
        ix, iy, _ = parse_tile_id(tid)
        xmin, ymin, xmax, ymax = tile_bounds(ix, iy, size_m)
        area_km2 = region.intersection(box(xmin, ymin, xmax, ymax)).area / 1e6
        full = area_km2 >= (size_m * size_m) / 1e6 - 1e-6
        rows.append({
            "tile_id": tid,
            "ix": ix,
            "iy": iy,
            "xmin": xmin,
            "ymin": ymin,
            "xmax": xmax,
            "ymax": ymax,
            "region_km2": area_km2,
            "full": full,
        })
    return rows


# -- Tile CSV -------------------------------------------------------------

def write_tiles_csv(rows: list[dict], path: str | Path) -> None:
    """Write tile rows to CSV.

    Floats are written with repr(); *full* is written as "true"/"false".
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TILE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            adapted = dict(row)
            for col in ("xmin", "ymin", "xmax", "ymax", "region_km2"):
                adapted[col] = repr(float(row[col]))
            adapted["full"] = "true" if row["full"] else "false"
            writer.writerow(adapted)


def read_tiles_csv(path: str | Path) -> list[dict]:
    """Read tile rows from CSV, restoring int ix/iy, float bounds, bool full."""
    path = Path(path)
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "tile_id": row["tile_id"],
                "ix": int(row["ix"]),
                "iy": int(row["iy"]),
                "xmin": float(row["xmin"]),
                "ymin": float(row["ymin"]),
                "xmax": float(row["xmax"]),
                "ymax": float(row["ymax"]),
                "region_km2": float(row["region_km2"]),
                "full": row["full"] == "true",
            })
    return rows


# -- High-level preparation -----------------------------------------------

def prep_region(
    stat_zip: str | Path,
    vusc_code: int | str,
    size_m: int,
    out_dir: str | Path,
) -> dict:
    """Prepare region outline and tile grid.

    Returns a summary dict with keys: region_km2, tiles, full_tiles.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    region = read_region(stat_zip, vusc_code)
    write_region_geojson(region, out_dir / "region.geojson")

    rows = tile_rows(region, size_m)
    write_tiles_csv(rows, out_dir / "tiles.csv")

    return {
        "region_km2": region.area / 1e6,
        "tiles": len(rows),
        "full_tiles": sum(1 for r in rows if r["full"]),
    }


def prep_buildings(obec_zips: list[str | Path], out_csv: str | Path) -> dict:
    """Read building data from municipality ZIPs and write a combined CSV.

    ZIPs are processed in sorted path order. Failed files are logged to the
    returned *failed* list. Returns a summary dict.
    """
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    sorted_zips = sorted(obec_zips, key=lambda p: str(Path(p)))
    files: list[str] = []
    total_rows: int = 0
    failed: list[str] = []
    first_success = True

    for zp in sorted_zips:
        try:
            rows = read_obec_buildings(zp)
            if first_success:
                write_buildings_csv(rows, out_csv, append=False)
                first_success = False
            else:
                write_buildings_csv(rows, out_csv, append=True)
            files.append(str(zp))
            total_rows += len(rows)
        except Exception as exc:
            failed.append(f"{Path(zp).name}: {exc}")

    if first_success:
        # No files succeeded — write empty file with header
        write_buildings_csv([], out_csv)

    return {
        "files": len(files),
        "rows": total_rows,
        "failed": failed,
    }


def prep_receptors(
    buildings_csv: str | Path,
    out_csv: str | Path,
    type_map: dict | None = None,
) -> dict:
    """Classify buildings into receptors and write a receptor CSV.

    Returns a stats dict from build_receptors.
    """
    if type_map is None:
        type_map = load_type_map()

    rows = read_buildings_csv(buildings_csv)
    receptors, stats = build_receptors(rows, type_map)
    write_receptors_csv(receptors, out_csv)
    return stats


def load_receptors(receptors_csv: str | Path) -> dict[str, np.ndarray]:
    """Load receptor CSV into numpy arrays.

    If facilities.csv exists in the same folder, its rows (receptor type
    "facility", from pipeline/facilities.py) are appended after the rows of
    *receptors_csv*.

    Returns dict with keys: x, y, type, id.
    """
    dtypes = {"building_id": str, "receptor_type": str}
    df = pd.read_csv(receptors_csv, dtype=dtypes)
    fac_csv = Path(receptors_csv).with_name("facilities.csv")
    if fac_csv.exists():
        fac = pd.read_csv(fac_csv, dtype=dtypes)
        if len(fac):
            df = pd.concat([df, fac], ignore_index=True)
    return {
        "x": df["x"].values.astype(np.float64),
        "y": df["y"].values.astype(np.float64),
        "type": df["receptor_type"].values.astype(str),
        "id": df["building_id"].values.astype(str),
    }


def prep_dem_index(dmr_dir: str | Path, out_csv: str | Path) -> dict:
    """Build a terrain sheet index from a directory of DMR 4G ZIPs.

    Returns a summary dict with the number of indexed sheets.
    """
    dmr_dir = Path(dmr_dir)
    zips = sorted(dmr_dir.glob("*.zip")) + sorted(dmr_dir.glob("*.tif"))
    rows = build_index(zips)
    write_index_csv(rows, out_csv)
    return {"sheets": len(rows)}
