"""Tests for pipeline.landcover."""

import json
from pathlib import Path

import geopandas
import numpy as np
import pyogrio
from rasterio.transform import from_origin
from shapely.geometry import box

from pipeline.landcover import (
    grid_shape,
    ground_grid,
    ground_polygons,
    hard_mask,
    landcover_masks,
    read_geometries,
    write_ground_geojson,
)


def _make_gpkg(tmp_path: Path) -> Path:
    """Create a small GeoPackage with test layers."""
    gpkg = tmp_path / "test.gpkg"
    pyogrio.write_dataframe(
        geopandas.GeoDataFrame(
            {"fid_zbg": [1]},
            geometry=[box(0, 0, 50, 100)],
            crs="EPSG:5514",
        ),
        gpkg,
        layer="VodniPlocha",
        driver="GPKG",
        append=False,
    )
    pyogrio.write_dataframe(
        geopandas.GeoDataFrame(
            {"fid_zbg": [2]},
            geometry=[box(100, 0, 200, 200)],
            crs="EPSG:5514",
        ),
        gpkg,
        layer="LesniPudaSeStromy",
        driver="GPKG",
        append=True,
    )
    pyogrio.write_dataframe(
        geopandas.GeoDataFrame(
            {"fid_zbg": [3]},
            geometry=[box(60, 60, 80, 80)],
            crs="EPSG:5514",
        ),
        gpkg,
        layer="BudovaJednotlivaNeboBlokBudov",
        driver="GPKG",
        append=True,
    )
    return gpkg


def test_grid_shape():
    h, w, tr = grid_shape((0, 0, 300, 200), 10)
    assert (h, w) == (20, 30)
    assert tr == from_origin(0, 200, 10, 10)


def test_grid_shape_value_error():
    try:
        grid_shape((0, 0, 305, 200), 10)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_read_geometries(tmp_path):
    gpkg = _make_gpkg(tmp_path)
    geoms = read_geometries(gpkg, ["VodniPlocha", "NoSuchLayer"], (0, 0, 300, 300))
    assert len(geoms) == 1
    assert geoms[0].area == 5000


def test_landcover_masks_shapes_and_sums(tmp_path):
    gpkg = _make_gpkg(tmp_path)
    bounds = (0, 0, 300, 300)
    masks = landcover_masks(gpkg, bounds, 10)
    for m in masks.values():
        assert m.shape == (30, 30)
        assert m.dtype == np.uint8
    assert masks["water"].sum() == 50
    assert masks["building"].sum() == 4
    assert masks["compound"].sum() == 0
    assert masks["forest"].sum() == 200
    assert masks["quarry"].sum() == 0


def test_landcover_masks_water_cell(tmp_path):
    gpkg = _make_gpkg(tmp_path)
    bounds = (0, 0, 300, 300)
    masks = landcover_masks(gpkg, bounds, 10)
    assert masks["water"][29, 0] == 1
    assert masks["water"][19, 0] == 0


def test_hard_mask(tmp_path):
    gpkg = _make_gpkg(tmp_path)
    bounds = (0, 0, 300, 300)
    masks = landcover_masks(gpkg, bounds, 10)
    hm = hard_mask(masks)
    assert hm.sum() == 50


def test_ground_polygons(tmp_path):
    gpkg = _make_gpkg(tmp_path)
    bounds = (0, 0, 300, 300)
    masks = landcover_masks(gpkg, bounds, 10)
    hm = hard_mask(masks)
    tr = from_origin(0, 300, 10, 10)
    polys = ground_polygons(hm, tr)
    hard_area = sum(g.area for g, gv in polys if gv == 0.0)
    soft_area = sum(g.area for g, gv in polys if gv == 1.0)
    assert hard_area == 5000
    assert soft_area == 85000


def test_write_ground_geojson(tmp_path):
    gpkg = _make_gpkg(tmp_path)
    bounds = (0, 0, 300, 300)
    masks = landcover_masks(gpkg, bounds, 10)
    hm = hard_mask(masks)
    tr = from_origin(0, 300, 10, 10)
    polys = ground_polygons(hm, tr)
    out = tmp_path / "a" / "g.geojson"
    write_ground_geojson(polys, out)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["type"] == "FeatureCollection"
    g_values = {f["properties"]["G"] for f in data["features"]}
    assert g_values == {0.0, 1.0}


def test_ground_grid():
    hard = np.zeros((16, 16), dtype=np.uint8)
    hard[0:8, 0:8] = 1
    hard[8:12, 8:16] = 1
    cells = ground_grid(hard, from_origin(-10000, -20000, 25, 25), 200.0)
    assert len(cells) == 4
    for g, _ in cells:
        assert g.area == 40000.0
    # Cell with bounds (-10000, -20200, -9800, -20000) has G 0.0
    cell_00 = [(g, gv) for g, gv in cells if g.bounds == (-10000.0, -20200.0, -9800.0, -20000.0)]
    assert len(cell_00) == 1
    assert cell_00[0][1] == 0.0
    # Cell (-9800, -20400, -9600, -20200) has G 0.5
    cell_01 = [(g, gv) for g, gv in cells if g.bounds == (-9800.0, -20400.0, -9600.0, -20200.0)]
    assert len(cell_01) == 1
    assert cell_01[0][1] == 0.5
    # Invalid cell_m raises ValueError
    try:
        ground_grid(hard, from_origin(0, 400, 25, 25), 210.0)
        assert False, "expected ValueError"
    except ValueError:
        pass
