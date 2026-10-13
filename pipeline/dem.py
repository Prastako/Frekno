"""Index DMR 4G terrain sheets and mosaic them for a tile."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.transform import from_origin

NODATA = -9999.0
SJTSK = "EPSG:5514"
INDEX_COLUMNS = ["code", "path", "xmin", "ymin", "xmax", "ymax"]


def sheet_path(zip_path: str | Path) -> str:
    """Return the rasterio path of a terrain file: /vsizip/ for a DMR 4G ZIP, the file itself for a GeoTIFF."""
    p = Path(zip_path).resolve()
    if p.suffix.lower() in (".tif", ".tiff"):
        return p.as_posix()
    return "/vsizip/" + p.as_posix() + "/" + p.stem + ".tif"


def build_index(zip_paths: list[str | Path]) -> list[dict[str, Any]]:
    """Build an index of DMR 4G sheets from ZIP file paths, sorted by code."""
    rows: list[dict[str, Any]] = []
    for zp in zip_paths:
        sp = sheet_path(zp)
        with rasterio.open(sp) as ds:
            b = ds.bounds
            rows.append({
                "code": Path(zp).stem,
                "path": sp,
                "xmin": float(b.left),
                "ymin": float(b.bottom),
                "xmax": float(b.right),
                "ymax": float(b.top),
            })
    return sorted(rows, key=lambda r: r["code"])


def write_index_csv(rows: list[dict[str, Any]], path: str | Path) -> None:
    """Write index rows to a CSV file."""
    path = Path(path)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INDEX_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            adapted = dict(row)
            for col in ("xmin", "ymin", "xmax", "ymax"):
                adapted[col] = repr(row[col])
            writer.writerow(adapted)


def read_index_csv(path: str | Path) -> list[dict[str, Any]]:
    """Read index rows from a CSV file, restoring float coordinates."""
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows: list[dict[str, Any]] = []
        for row in reader:
            rows.append({
                "code": row["code"],
                "path": row["path"],
                "xmin": float(row["xmin"]),
                "ymin": float(row["ymin"]),
                "xmax": float(row["xmax"]),
                "ymax": float(row["ymax"]),
            })
    return rows


def sheets_for_bounds(
    rows: list[dict[str, Any]],
    bounds: tuple[float, float, float, float],
) -> list[dict[str, Any]]:
    """Return rows whose box overlaps *bounds* with positive area, in index order."""
    xmin, ymin, xmax, ymax = bounds
    result: list[dict[str, Any]] = []
    for row in rows:
        if (row["xmin"] < xmax
                and row["xmax"] > xmin
                and row["ymin"] < ymax
                and row["ymax"] > ymin):
            result.append(row)
    return result


def mosaic(
    rows: list[dict[str, Any]],
    bounds: tuple[float, float, float, float],
    res_m: float,
    out_path: str | Path,
) -> dict[str, Any]:
    """Mosaic terrain sheets into a GeoTIFF covering *bounds* at resolution *res_m*."""
    xmin, ymin, xmax, ymax = bounds

    width = (xmax - xmin) / res_m
    height = (ymax - ymin) / res_m

    if not (width == int(width) and height == int(height) and width > 0 and height > 0):
        raise ValueError(
            f"bounds / res_m must yield positive whole numbers "
            f"(got width={width}, height={height})"
        )

    width = int(width)
    height = int(height)

    overlapping = sheets_for_bounds(rows, bounds)

    if overlapping:
        paths = [r["path"] for r in overlapping]
        arr, transform = merge(
            paths,
            bounds=(xmin, ymin, xmax, ymax),
            res=res_m,
            nodata=NODATA,
            dtype="float32",
            resampling=Resampling.average,
        )
        mosaic_data = arr[0]
    else:
        mosaic_data = np.full((height, width), NODATA, dtype="float32")
        transform = from_origin(xmin, ymax, res_m, res_m)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(
        out_path, "w", driver="GTiff",
        height=height, width=width, count=1,
        dtype="float32",
        crs=CRS.from_string(SJTSK),
        transform=transform,
        nodata=NODATA,
        compress="lzw",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        dst.write(mosaic_data, 1)

    mask = mosaic_data != NODATA
    nodata_cells = int(np.sum(~mask))

    if mask.any():
        min_val: float | None = float(np.min(mosaic_data[mask]))
        max_val: float | None = float(np.max(mosaic_data[mask]))
    else:
        min_val = None
        max_val = None

    return {
        "width": width,
        "height": height,
        "sheets": len(overlapping),
        "nodata_cells": nodata_cells,
        "min": min_val,
        "max": max_val,
    }
