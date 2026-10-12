"""Files that NoiseModelling reads and writes."""

import csv
import json
from pathlib import Path

import numpy as np


NM_BANDS_HZ = (63, 125, 250, 500, 1000, 2000, 4000, 8000)


def write_asc(dem, transform, path, nodata=-9999.0):
    """Write ESRI ASCII grid (.asc)."""
    tr = transform
    if tr.b != 0 or tr.d != 0 or tr.a != -tr.e:
        raise ValueError("Transform must have zero rotation and square cells")

    dem_array = np.asarray(dem)
    nrows, ncols = dem_array.shape

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    xllcorner = float(tr.c)
    yllcorner = float(tr.f + tr.e * nrows)
    cellsize = float(tr.a)
    nodata_repr = repr(float(nodata))

    header_lines = [
        f"ncols {ncols}",
        f"nrows {nrows}",
        f"xllcorner {repr(xllcorner)}",
        f"yllcorner {repr(yllcorner)}",
        f"cellsize {repr(cellsize)}",
        f"NODATA_value {nodata_repr}",
    ]

    with open(path, "w", newline="\n") as f:
        for line in header_lines:
            f.write(line + "\n")
        for row in dem_array:
            parts = []
            for val in row.flat:
                fv = float(val)
                if np.isnan(fv) or fv == nodata:
                    parts.append(nodata_repr)
                else:
                    parts.append(f"{fv:.3f}")
            f.write(" ".join(parts) + "\n")


def write_points_geojson(path, ids, xs, ys, heights):
    """Write points as GeoJSON FeatureCollection."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    features = []
    for i in range(len(ids)):
        features.append(
            {
                "type": "Feature",
                "properties": {"PK": int(ids[i])},
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(xs[i]), float(ys[i]), float(heights[i])],
                },
            }
        )

    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)


def write_dummy_building_geojson(path, x, y):
    """Write a single 10x10 dummy building for NoiseModelling."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    ring = [[x, y], [x + 10, y], [x + 10, y + 10], [x, y + 10], [x, y]]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"HEIGHT": 3.0},
                        "geometry": {"type": "Polygon", "coordinates": [ring]},
                    }
                ],
            },
            f,
        )


def read_receivers_level(csv_path):
    """Read receiver-level CSV exported by NoiseModelling."""
    path = Path(csv_path)
    results = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            levels = [
                float(row["HZ63"]),
                float(row["HZ125"]),
                float(row["HZ250"]),
                float(row["HZ500"]),
                float(row["HZ1000"]),
                float(row["HZ2000"]),
                float(row["HZ4000"]),
                float(row["HZ8000"]),
            ]
            results.append(
                {
                    "receiver_id": int(row["IDRECEIVER"]),
                    "source_id": int(row["IDSOURCE"]),
                    "levels": levels,
                }
            )
    return results


def attenuation_from_1m(levels):
    """Convert 1 m levels to attenuations.

    NoiseModelling reports levels for a 0 dB sound-power source; a point
    source is 11 dB below its power at 1 m, so attenuation = -level - 11.
    """
    return [-float(v) - 11.0 for v in levels]
