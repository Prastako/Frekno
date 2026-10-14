"""Tests for pipeline.de_area (region, states and tiles of the German area)."""

import geopandas as gpd
import numpy as np
import pytest
import shapely
from pyproj import Geod, Transformer

from pipeline import de_area
from pipeline.region import read_region_geojson, read_tiles_csv, tile_rows

TO_WGS = Transformer.from_crs("EPSG:5514", "EPSG:4326", always_xy=True)
TO_SJTSK = Transformer.from_crs("EPSG:4326", "EPSG:5514", always_xy=True)
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)


def utm_box(lon0, lat0, lon1, lat1):
    (x0, x1), (y0, y1) = TO_UTM.transform([lon0, lon1], [lat0, lat1])
    return shapely.box(x0, y0, x1, y1)


def vg250(path):
    """VG250 stand-in: Saxony (14) east and Thuringia (16) west of 12.3 E, Bavaria (09) south of 50.5 N, a Saxon lake (GF 2)."""
    rows = [("14", 4, utm_box(12.3, 50.5, 14.5, 52.6)), ("16", 4, utm_box(10.0, 50.5, 12.3, 52.6)),
            ("09", 4, utm_box(10.0, 49.5, 14.5, 50.5)), ("14", 2, utm_box(12.3, 52.6, 14.5, 53.0))]
    gdf = gpd.GeoDataFrame({"SN_L": [r[0] for r in rows], "GF": [r[1] for r in rows]}, geometry=[r[2] for r in rows],
                           crs="EPSG:25832")
    gdf.to_file(path, layer="vg250_lan", driver="GPKG")
    return path


def inside(geom, lon, lat):
    return geom.contains(shapely.Point(TO_SJTSK.transform(lon, lat)))


def test_circle_points_lie_at_the_radius():
    c = de_area.circle(12.3747, 51.3406, 10_000.0, n=36)
    lon, lat = TO_WGS.transform(*shapely.get_coordinates(c.exterior)[:-1].T)
    _, _, d = Geod(ellps="WGS84").inv(np.full(36, 12.3747), np.full(36, 51.3406), lon, lat)
    assert d == pytest.approx(np.full(36, 10_000.0), abs=1.0)


def test_read_states_keeps_the_land_of_the_area_states(tmp_path):
    states = de_area.read_states(vg250(tmp_path / "vg.gpkg"))
    assert sorted(states) == ["SN", "TH"]
    assert inside(states["SN"], 13.0, 51.0) and not inside(states["SN"], 11.0, 51.0)
    assert not inside(states["SN"], 13.0, 52.8)


def test_prep_area_writes_region_states_and_tiles(tmp_path):
    stats = de_area.prep_area(vg250(tmp_path / "vg.gpkg"), tmp_path / "out", 20000)
    region = read_region_geojson(tmp_path / "out" / "region.geojson")
    assert inside(region, 12.3747, 51.3406) and inside(region, 12.37, 50.6)
    assert not inside(region, 12.37, 50.4)  # Bavaria
    assert not inside(region, 12.3747, 52.4)  # beyond 110 km
    rows = read_tiles_csv(tmp_path / "out" / "tiles.csv")
    assert len(rows) == stats["tiles"] == len(tile_rows(region, 20000))
    assert stats["full_tiles"] == sum(1 for r in rows if r["full"])
    parts = de_area.read_area_states(tmp_path / "out" / "states.gpkg")
    assert sorted(parts) == ["SN", "TH"]
    assert sum(g.area for g in parts.values()) == pytest.approx(region.area, rel=1e-6)
    assert stats["region_km2"] == round(region.area / 1e6)
    assert stats["SN_km2"] + stats["TH_km2"] == pytest.approx(stats["region_km2"], abs=1)


def test_wgs84_bbox_rounds_outwards():
    x, y = TO_SJTSK.transform(12.3747, 51.3406)
    lon0, lat0, lon1, lat1 = de_area.wgs84_bbox(shapely.box(x - 5000, y - 5000, x + 5000, y + 5000))
    assert lon0 < 12.3747 < lon1 and lat0 < 51.3406 < lat1
    assert all(round(v * 100) == pytest.approx(v * 100, abs=1e-9) for v in (lon0, lat0, lon1, lat1))
    assert lon1 - lon0 < 0.3 and lat1 - lat0 < 0.2


def test_to_sjtsk_matches_pyproj():
    x, y = TO_UTM.transform(12.3747, 51.3406)
    p = de_area.to_sjtsk(shapely.Point(x, y), "EPSG:25832")
    assert (p.x, p.y) == pytest.approx(TO_SJTSK.transform(12.3747, 51.3406), abs=0.5)