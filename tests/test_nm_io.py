"""Tests for pipeline.nm_io."""

import json
import math
from pathlib import Path

import pytest
from rasterio.transform import Affine, from_origin

from pipeline.nm_io import (
    attenuation_from_1m,
    read_receivers_level,
    write_asc,
    write_dummy_building_geojson,
    write_points_geojson,
)


def test_write_asc(tmp_path):
    dem = [[1.0, 2.5], [4.0, -9999.0]]
    tr = from_origin(-760000.0, -1050000.0, 25.0, 25.0)
    path = tmp_path / "s" / "d.asc"
    write_asc(dem, tr, path)

    content = path.read_text()
    assert "\r" not in content

    lines = content.split("\n")
    assert "ncols 2" in lines[0]
    assert "nrows 2" in lines[1]
    assert "xllcorner -760000.0" in lines[2]
    assert "yllcorner -1050050.0" in lines[3]
    assert "cellsize 25.0" in lines[4]
    assert "NODATA_value -9999.0" in lines[5]

    row1 = [float(v) for v in lines[6].split()]
    assert row1 == [1.0, 2.5]
    row2 = [float(v) for v in lines[7].split()]
    assert row2 == [4.0, -9999.0]


def test_write_asc_nan(tmp_path):
    dem = [[math.nan, 5.0]]
    tr = from_origin(0, 10, 10, 10)
    path = tmp_path / "nan.asc"
    write_asc(dem, tr, path)

    content = path.read_text()
    lines = content.split("\n")
    row = [float(v) for v in lines[6].split()]
    assert row == [-9999.0, 5.0]


def test_write_asc_bad_transform():
    tr = Affine(10, 0, 0, 0, -5, 10)
    with pytest.raises(ValueError):
        write_asc([[1.0]], tr, Path("/tmp/dummy.asc"))


def test_write_points_geojson(tmp_path):
    path = tmp_path / "points.geojson"
    write_points_geojson(path, [7], [-750000.5], [-1050000.0], [2.0])

    with open(path) as f:
        data = json.load(f)

    feat = data["features"][0]
    assert feat["properties"] == {"PK": 7}
    assert feat["geometry"]["coordinates"] == [-750000.5, -1050000.0, 2.0]


def test_write_dummy_building_geojson(tmp_path):
    path = tmp_path / "buildings.geojson"
    write_dummy_building_geojson(path, 100.0, 200.0)

    with open(path) as f:
        data = json.load(f)

    feat = data["features"][0]
    assert feat["properties"] == {"HEIGHT": 3.0}
    ring = feat["geometry"]["coordinates"][0]
    assert ring[0] == ring[4]
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    assert min(xs) == 100.0
    assert max(ys) == 210.0


def test_read_receivers_level(tmp_path):
    csv_path = tmp_path / "receivers.csv"
    csv_path.write_text(
        '"IDRECEIVER","IDSOURCE","THE_GEOM","HZ63","HZ125","HZ250","HZ500",'
        '"HZ1000","HZ2000","HZ4000","HZ8000","LAEQ","LEQ"\n'
        '"6","1","SRID=5514;POINT Z (-750000 -1050000 4)",'
        '"-83.3","-86.2","-92.5","-101.4","-118.7","-178.7","-409.8","-1250.9",'
        '"-97.4","-81.2"\n'
    )

    result = read_receivers_level(csv_path)
    assert len(result) == 1
    assert result[0]["receiver_id"] == 6
    assert result[0]["source_id"] == 1
    assert result[0]["levels"] == [
        -83.3, -86.2, -92.5, -101.4, -118.7, -178.7, -409.8, -1250.9
    ]


def test_attenuation_from_1m():
    result = attenuation_from_1m([-58.2, -100.0])
    assert result[0] == pytest.approx(47.2, abs=0.01)
    assert result[1] == pytest.approx(89.0, abs=0.01)
