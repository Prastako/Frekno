"""The German area around Leipzig: region outline, state outlines and tiles in S-JTSK (BKG VG250, dl-de/by-2-0).

The region is the circle of DATA_RADIUS_M around CENTRE cut to the states in STATES. The tile run drops every spot
closer than the receptor radius (10 km) to the region edge, so the website shows the circle of SHOW_RADIUS_M,
minus 10 km along the Czech and Bavarian borders, as on the Czech side.
"""

import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pyogrio
import shapely
from pyproj import Transformer

from pipeline.region import tile_rows, write_region_geojson, write_tiles_csv

AREA = "de-leipzig"
CENTRE = (12.3747, 51.3406)  # lon, lat: Leipzig, Markt
SHOW_RADIUS_M = 100_000
DATA_RADIUS_M = 110_000  # SHOW_RADIUS_M plus the 10 km receptor radius
STATES = {"12": "BB", "14": "SN", "15": "ST", "16": "TH"}  # VG250 SN_L -> state code
SJTSK = "EPSG:5514"
WGS84 = "EPSG:4326"
# All conversions to and from S-JTSK go through WGS84 with the transformers pipeline/pack.py also uses: a direct
# conversion from ETRS89 (EPSG:25832, 25833) picks other datum shifts in PROJ, up to 110 m apart around Leipzig.
_TO_SJTSK = Transformer.from_crs(WGS84, SJTSK, always_xy=True)
_FROM_SJTSK = Transformer.from_crs(SJTSK, WGS84, always_xy=True)


def sjtsk_xy(x, y, crs: str) -> tuple:
    """S-JTSK coordinates of points given in *crs*, through WGS84."""
    if crs != WGS84:
        x, y = Transformer.from_crs(crs, WGS84, always_xy=True).transform(x, y)
    return _TO_SJTSK.transform(x, y)


def crs_xy(x, y, crs: str) -> tuple:
    """Coordinates in *crs* of S-JTSK points, through WGS84."""
    lon, lat = _FROM_SJTSK.transform(x, y)
    return (lon, lat) if crs == WGS84 else Transformer.from_crs(WGS84, crs, always_xy=True).transform(lon, lat)


def to_sjtsk(geom, crs: str):
    """*geom* (a shapely geometry or an array of them) from *crs* to S-JTSK, made valid."""
    return shapely.make_valid(shapely.transform(geom, lambda xy: np.column_stack(sjtsk_xy(xy[:, 0], xy[:, 1], crs))))


def circle(lon: float, lat: float, radius_m: float, n: int = 720):
    """Polygon in S-JTSK through n points radius_m from (lon, lat) (WGS84) on the ellipsoid."""
    ang = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
    aeqd = f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m"
    x, y = sjtsk_xy(radius_m * np.cos(ang), radius_m * np.sin(ang), aeqd)
    return shapely.Polygon(np.column_stack([x, y]))


def read_states(vg250_gpkg) -> dict:
    """{state code: land area of the state in S-JTSK} for STATES, from the VG250 layer vg250_lan (GF 4 = land)."""
    lan = pyogrio.read_dataframe(vg250_gpkg, layer="vg250_lan", columns=["SN_L", "GF"])
    lan = lan[(lan["GF"].astype(int) == 4) & lan["SN_L"].isin(list(STATES))]
    crs = lan.crs.to_string()
    return {STATES[k]: to_sjtsk(shapely.union_all(g.geometry.to_numpy()), crs) for k, g in lan.groupby("SN_L")}


def area_region(states: dict, centre: tuple = CENTRE, radius_m: float = DATA_RADIUS_M):
    """The region: the circle around *centre* cut to the union of *states* (polygons only)."""
    cut = circle(centre[0], centre[1], radius_m).intersection(shapely.union_all(list(states.values())))
    polys = [p for p in shapely.get_parts(cut) if p.geom_type == "Polygon"]
    return shapely.MultiPolygon(polys) if len(polys) > 1 else polys[0]


def write_states(states: dict, region, path) -> None:
    """Write the parts of the states inside *region* to a GeoPackage layer 'states' (columns state, geometry)."""
    rows = [{"state": k, "geometry": g.intersection(region)} for k, g in sorted(states.items())]
    gdf = gpd.GeoDataFrame(rows, columns=["state", "geometry"], geometry="geometry", crs=SJTSK)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, layer="states", driver="GPKG")


def read_area_states(path) -> dict:
    """{state code: its part of the region} from the GeoPackage written by write_states."""
    gdf = pyogrio.read_dataframe(path, layer="states")
    return {s: g for s, g in zip(gdf["state"], gdf.geometry) if g is not None and not g.is_empty}


def wgs84_bbox(geom) -> tuple:
    """(lon_min, lat_min, lon_max, lat_max) of an S-JTSK geometry, rounded outwards to 0.01 degree."""
    lon, lat = _FROM_SJTSK.transform(*shapely.get_coordinates(shapely.segmentize(geom.envelope.exterior, 1000.0)).T)
    return (math.floor(min(lon) * 100) / 100, math.floor(min(lat) * 100) / 100,
            math.ceil(max(lon) * 100) / 100, math.ceil(max(lat) * 100) / 100)


def prep_area(vg250_gpkg, out_dir, size_m: int) -> dict:
    """Write region.geojson, tiles.csv and states.gpkg for the area into *out_dir*; return areas and tile counts."""
    states = read_states(vg250_gpkg)
    region = area_region(states)
    out_dir = Path(out_dir)
    write_region_geojson(region, out_dir / "region.geojson")
    write_states(states, region, out_dir / "states.gpkg")
    rows = tile_rows(region, size_m)
    write_tiles_csv(rows, out_dir / "tiles.csv")
    return {"region_km2": round(region.area / 1e6), "tiles": len(rows), "full_tiles": sum(1 for r in rows if r["full"]),
            **{f"{k}_km2": round(region.intersection(g).area / 1e6) for k, g in sorted(states.items())}}