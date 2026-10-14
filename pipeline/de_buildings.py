"""Receptors in the German area from the states' official building outlines (Hausumringe; ALKIS in Brandenburg).

GFK holds the object type and the building function code joined by "_", such as "31001_1000" (AdV code list
BuildingFunctionTypeAdV). Saxony, Saxony-Anhalt and Thuringia give most homes only the general code 1000, and
Thuringia many buildings 9998 (not known); small buildings among them are sheds and garages. So residential and
public buildings count as homes from HOME_MIN_M2 up and unknown ones from UNKNOWN_MIN_M2. Leisure buildings (1310 to
1313) and residential or unknown buildings inside weekend-house and allotment areas are cottages from COTTAGE_MIN_M2
up. Lodging and public buildings (2070 to 2074, 3000 to 3099) count as homes, as the Czech data count such buildings
with a house number.
"""

import csv
import re
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely
from shapely import STRtree

from pipeline.de_area import SJTSK, crs_xy, to_sjtsk

HOME_MIN_M2 = 30.0
UNKNOWN_MIN_M2 = 50.0
COTTAGE_MIN_M2 = 10.0
BATCH = 400_000  # buildings read at a time (keeps memory low)
BUILDING_LAYER = "BudovaJednotlivaNeboBlokBudov"
SOURCES = {  # file name pattern in the download folder -> (shapefile inside the ZIP, GFK field, id field)
    "SN.zip": (r"\.shp$", "GFK", "OI"),
    "ST.zip": (r"\.shp$", "GFK", "OI"),
    "TH.zip": (r"\.shp$", "GFK", "OI"),
    "BB_*.zip": (r"GebauedeBauwerk\.shp$", "gfkzshh", "oid"),
}


def building_types(gfk, area_m2, leisure) -> np.ndarray:
    """'home', 'cottage' or 'ignore' per building, from its GFK text, footprint area in m2 and whether its point lies
    in a weekend-house or allotment area."""
    g = pd.Series(list(gfk), dtype=str)
    code = pd.to_numeric(g.str.slice(6), errors="coerce").fillna(-1).to_numpy()
    building = ((g.str.slice(0, 6) == "31001_") & g.str.slice(6).str.fullmatch(r"\d{4}")).to_numpy()
    area = np.asarray(area_m2, dtype=float)
    leisure = np.asarray(leisure, dtype=bool)
    residential = building & (code >= 1000) & (code < 1300)
    public = building & (((code >= 2070) & (code <= 2074)) | ((code >= 3000) & (code < 3100)))
    unknown = building & (code == 9998)
    cottage = building & (((code >= 1310) & (code <= 1313)) | (leisure & (residential | unknown)))
    out = np.full(len(g), "ignore", dtype=object)
    out[(residential | public) & (area >= HOME_MIN_M2)] = "home"
    out[unknown & (area >= UNKNOWN_MIN_M2)] = "home"
    out[cottage] = np.where(area[cottage] >= COTTAGE_MIN_M2, "cottage", "ignore")
    return out


def shapefiles(raw_hu) -> list[tuple[str, str, str]]:
    """(/vsizip/ path of the shapefile, GFK field, id field) for every downloaded building file in *raw_hu*."""
    out = []
    for pattern, (member, gfk, oid) in SOURCES.items():
        for z in sorted(Path(raw_hu).glob(pattern)):
            names = [n for n in zipfile.ZipFile(z).namelist() if re.search(member, n)]
            if not names:
                raise ValueError(f"no shapefile matching {member} in {z}")
            out.append((f"/vsizip/{z.resolve().as_posix()}/{names[0]}", gfk, oid))
    return out


def in_areas(points, areas) -> np.ndarray:
    """True for each point that lies inside one of the polygons *areas*."""
    out = np.zeros(len(points), dtype=bool)
    geoms = [g for g in areas if g is not None and not g.is_empty]
    if len(points) and geoms:
        ip, _ = STRtree(geoms).query(points, predicate="within")
        out[ip] = True
    return out


def read_buildings(path: str, gfk_field: str, id_field: str, region, skip: int = 0, count: int | None = None) -> dict:
    """Buildings of one shapefile whose inner point lies in *region*: ids, GFK, area (m2), points and outlines in S-JTSK.

    Reads the features skip to skip + count of those near the region; "read" is how many that were.
    """
    crs = pyogrio.read_info(path)["crs"]
    ring = shapely.segmentize(region.envelope.buffer(1000.0).exterior, 1000.0)
    xs, ys = crs_xy(*shapely.get_coordinates(ring).T, crs)
    df = pyogrio.read_dataframe(path, columns=[gfk_field, id_field], bbox=(min(xs), min(ys), max(xs), max(ys)),
                                skip_features=skip, max_features=count)
    read = len(df)
    df = df[df.geometry.notna()]
    geom = df.geometry.to_numpy()
    pts = to_sjtsk(shapely.point_on_surface(geom), crs)
    shapely.prepare(region)
    inside = shapely.contains_xy(region, shapely.get_x(pts), shapely.get_y(pts))
    return {"id": df[id_field].astype(str).to_numpy()[inside], "gfk": df[gfk_field].astype(str).to_numpy()[inside],
            "area": shapely.area(geom)[inside], "points": pts[inside], "outlines": to_sjtsk(geom[inside], crs), "read": read}


def prep_buildings(raw_hu, leisure_areas, region, receptors_csv, gpkg) -> dict:
    """Write receptors.csv (homes and cottages, columns of pipeline/receptors.py) and append all building outlines to
    the GeoPackage *gpkg*, BATCH buildings at a time.

    *leisure_areas* are the weekend-house and allotment areas in S-JTSK. Returns counts per type.
    """
    stats, first = {"buildings": 0, "home": 0, "cottage": 0}, True
    Path(receptors_csv).parent.mkdir(parents=True, exist_ok=True)
    with open(receptors_csv, "w", encoding="utf-8", newline="") as f:
        out = csv.writer(f, lineterminator="\n")
        out.writerow(["building_id", "x", "y", "use_code", "number_type", "receptor_type", "unclear"])
        for path, gfk_field, id_field in shapefiles(raw_hu):
            skip = 0
            while True:
                b = read_buildings(path, gfk_field, id_field, region, skip, BATCH)
                types = building_types(b["gfk"], b["area"], in_areas(b["points"], leisure_areas))
                codes = pd.to_numeric(pd.Series(b["gfk"]).str.slice(6), errors="coerce").to_numpy()
                xs, ys = shapely.get_x(b["points"]), shapely.get_y(b["points"])
                for k in np.flatnonzero(types != "ignore"):
                    out.writerow([f"de{b['id'][k]}", repr(float(xs[k])), repr(float(ys[k])),
                                  "" if np.isnan(codes[k]) else int(codes[k]), "none", types[k], "false"])
                pyogrio.write_dataframe(gpd.GeoDataFrame(geometry=b["outlines"], crs=SJTSK), gpkg, layer=BUILDING_LAYER,
                                        driver="GPKG", append=not first, promote_to_multi=True)
                first = False
                stats["buildings"] += len(types)
                stats["home"] += int((types == "home").sum())
                stats["cottage"] += int((types == "cottage").sum())
                if b["read"] < BATCH:
                    break
                skip += BATCH
    return stats
