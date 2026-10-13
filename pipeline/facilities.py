"""Facility receptors: campsites, hospitals and care homes from ZABAGED purpose-built areas.

Each area becomes points along its outer boundary, at most SPACING_M apart, so the
receptor nearest to a spot lies within SPACING_M / 2 of the area's true nearest edge.
"""

from pathlib import Path

import numpy as np
import pyogrio
import shapely

from pipeline.receptors import write_receptors_csv

# ZABAGED ArealUceloveZastavby.typzast_k: 310 camping, 412 nemocnice,
# 413 dalsi zdravotni a socialni zarizeni (care homes and other health or social facilities)
FACILITY_CODES = {"310": "campsite", "412": "hospital", "413": "care"}
SPACING_M = 50.0


def boundary_points(geom, spacing_m: float = SPACING_M) -> tuple[np.ndarray, np.ndarray]:
    """Return x and y arrays of points along the outer ring of each polygon in *geom*.

    Ring vertices are kept and points are added so that neighbours are at most
    *spacing_m* apart. The closing vertex is not repeated; holes are ignored.
    None or an empty geometry gives two empty arrays.
    """
    xs, ys = [], []
    if geom is not None and not geom.is_empty:
        for part in shapely.get_parts(geom):
            ring = shapely.segmentize(part.exterior, spacing_m)
            xy = shapely.get_coordinates(ring)[:-1]
            xs.append(xy[:, 0])
            ys.append(xy[:, 1])
    if not xs:
        return np.empty(0), np.empty(0)
    return np.concatenate(xs), np.concatenate(ys)


def read_facility_areas(gpkg: Path | str, bounds: tuple):
    """Read areas of layer ArealUceloveZastavby with a FACILITY_CODES code that touch *bounds*.

    *bounds* is (xmin, ymin, xmax, ymax). Returns a GeoDataFrame with columns
    fid_zbg, typzast_k (as str) and geometry.
    """
    gdf = pyogrio.read_dataframe(
        gpkg, layer="ArealUceloveZastavby", bbox=tuple(bounds),
        columns=["fid_zbg", "typzast_k"],
    )
    gdf["typzast_k"] = gdf["typzast_k"].astype(str)
    return gdf[gdf["typzast_k"].isin(list(FACILITY_CODES))].reset_index(drop=True)


def facility_rows(areas, spacing_m: float = SPACING_M) -> list[dict]:
    """Return one receptor row per boundary point, area by area.

    building_id is "zbg<fid_zbg>_<k>" with k = 0, 1, ... within each area,
    use_code the ZABAGED code as int, number_type "none",
    receptor_type "facility", unclear False.
    """
    rows = []
    for fid, code, geom in zip(areas["fid_zbg"], areas["typzast_k"], areas.geometry):
        xs, ys = boundary_points(geom, spacing_m)
        for k in range(len(xs)):
            rows.append({
                "building_id": f"zbg{int(fid)}_{k}",
                "x": float(xs[k]),
                "y": float(ys[k]),
                "use_code": int(code),
                "number_type": "none",
                "receptor_type": "facility",
                "unclear": False,
            })
    return rows


def prep_facilities(gpkg: Path | str, region, buffer_m: float, out_csv: Path | str,
                    spacing_m: float = SPACING_M) -> dict:
    """Write receptor rows of all facility areas within *buffer_m* of the bounding box of *region*.

    Returns {"areas": ..., "points": ..., "campsite": ..., "hospital": ..., "care": ...};
    the last three count areas.
    """
    xmin, ymin, xmax, ymax = region.bounds
    areas = read_facility_areas(
        gpkg, (xmin - buffer_m, ymin - buffer_m, xmax + buffer_m, ymax + buffer_m)
    )
    rows = facility_rows(areas, spacing_m)
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    write_receptors_csv(rows, out_csv)
    stats = {"areas": len(areas), "points": len(rows)}
    for code, name in FACILITY_CODES.items():
        stats[name] = int((areas["typzast_k"] == code).sum())
    return stats
