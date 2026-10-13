"""Tests for pipeline.national."""

import json
import zipfile

import geopandas as gpd
import numpy as np
import pyogrio
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point, box

from pipeline import national
from pipeline.dem import build_index, mosaic
from pipeline.region import read_region_geojson, write_tiles_csv


def tiles_csv(path, n):
    rows = [{"tile_id": f"20k_{i}_0", "ix": i, "iy": 0, "xmin": 0, "ymin": 0, "xmax": 1, "ymax": 1, "region_km2": 1.0, "full": True}
            for i in range(n)]
    write_tiles_csv(rows, path)


def test_zabaged_zip_url():
    text = '<link href="https://x.cz/a/ZABAGED-3045-gpkg-20261004.zip"/><link href="https://x.cz/a/ZABAGED-5514-gpkg-20261004.zip"/>'
    assert national.zabaged_zip_url(text) == "https://x.cz/a/ZABAGED-5514-gpkg-20261004.zip"


def test_neighbours_and_groups(tmp_path):
    assert national.neighbours("20k_-1_-1") == ["20k_-2_-2", "20k_-1_-2", "20k_0_-2", "20k_-2_-1", "20k_-1_-1",
                                                "20k_0_-1", "20k_-2_0", "20k_-1_0", "20k_0_0"]
    tiles_csv(tmp_path / "tiles.csv", 5)
    assert national.tile_groups(tmp_path / "tiles.csv", 2) == ["20k_0_0 20k_1_0", "20k_2_0 20k_3_0", "20k_4_0"]


def test_obec_codes(tmp_path):
    shp = tmp_path / "1"
    shp.mkdir()
    gpd.GeoDataFrame({"KOD": [500020, 500011]}, geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:5514").to_file(shp / "OBCE_P.shp")
    with zipfile.ZipFile(tmp_path / "1.zip", "w") as z:
        for f in shp.iterdir():
            z.write(f, f"1/{f.name}")
    assert national.obec_codes(tmp_path / "1.zip") == ["500011", "500020"]


def test_military_areas(tmp_path):
    shp = tmp_path / "shp"
    shp.mkdir()
    gpd.GeoDataFrame({"KOD": [503941, 500011, 545422], "STATUS_KOD": ["1", "2", "1"]},
                     geometry=[box(0, 0, 10, 10), box(20, 0, 30, 10), box(40, 0, 50, 10)], crs="EPSG:5514").to_file(shp / "OBCE_P.shp")
    with zipfile.ZipFile(tmp_path / "1.zip", "w") as z:
        for f in shp.iterdir():
            z.write(f, f"1/{f.name}")
    assert national.military_areas(tmp_path / "1.zip", tmp_path / "military.geojson") == 2
    geom = read_region_geojson(tmp_path / "military.geojson")
    assert geom.area == pytest.approx(200.0)
    assert geom.contains(Point(5, 5)) and geom.contains(Point(45, 5)) and not geom.contains(Point(25, 5))


def test_slim_zabaged(tmp_path):
    src = tmp_path / "full.gpkg"
    for name, n in (("VodniPlocha", 2), ("Cesta", 1), ("Other", 3)):
        gdf = gpd.GeoDataFrame({"a": list(range(n))}, geometry=[box(i, 0, i + 1, 1) for i in range(n)], crs="EPSG:5514")
        gdf.to_file(src, layer=name, driver="GPKG")
    assert national.slim_zabaged(src, tmp_path / "slim.gpkg", layers=["Cesta", "VodniPlocha"]) == {"Cesta": 1, "VodniPlocha": 2}
    assert sorted(row[0] for row in pyogrio.list_layers(tmp_path / "slim.gpkg")) == ["Cesta", "VodniPlocha"]


def test_dem_chunks_match_mosaic(tmp_path):
    sheets = []
    for i, x0 in enumerate((-40000.0, -38000.0)):
        p = tmp_path / f"s{i}.tif"
        with rasterio.open(p, "w", driver="GTiff", width=400, height=400, count=1, dtype="float32", crs="EPSG:5514",
                           transform=from_origin(x0, -38000.0, 5, 5), nodata=-9999.0) as d:
            d.write(np.full((400, 400), 100.0 + i, dtype="float32") + np.arange(400, dtype="float32")[None, :] * 0.01, 1)
        sheets.append(p)
    idx = build_index(sheets)
    assert national.dem_chunks(idx, ["20k_-2_-2", "20k_5_5"], 10.0, tmp_path / "dem") == 1
    assert [p.name for p in (tmp_path / "dem").iterdir()] == ["20k_-2_-2.tif"]
    mosaic(idx, (-40000.0, -40000.0, -20000.0, -20000.0), 10.0, tmp_path / "ref.tif")
    with rasterio.open(tmp_path / "dem" / "20k_-2_-2.tif") as a, rasterio.open(tmp_path / "ref.tif") as b:
        assert a.profile["compress"] == "deflate" and np.array_equal(a.read(1), b.read(1))


def test_main_groups_and_neighbours(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FREKNO_OUT", str(tmp_path))
    (tmp_path / "region").mkdir()
    tiles_csv(tmp_path / "region" / "tiles.csv", 2)
    assert national.main(["groups", "--size", "1"]) == 0
    assert json.loads(capsys.readouterr().out) == ["20k_0_0", "20k_1_0"]
    assert national.main(["neighbours", "20k_0_0", "20k_1_0"]) == 0
    out = capsys.readouterr().out.split()
    assert len(out) == 12 and out[0] == "20k_-1_-1"
