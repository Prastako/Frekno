"""Tests for pipeline/facilities.py."""

import pandas as pd
import pyogrio
import geopandas
import numpy as np
import pytest
import shapely

from pipeline.facilities import boundary_points, prep_facilities


def box(xmin, ymin, xmax, ymax):
    """Create a box polygon."""
    return shapely.box(xmin, ymin, xmax, ymax)


class TestBoundaryPoints:
    """Tests for boundary_points."""

    def test_box_8_points(self):
        """boundary_points(box(0, 0, 100, 100), 50.0) gives 8 points."""
        geom = box(0, 0, 100, 100)
        xs, ys = boundary_points(geom, 50.0)
        assert len(xs) == 8
        assert len(ys) == 8

    def test_box_points_on_edges(self):
        """Each point lies on an edge of the square."""
        geom = box(0, 0, 100, 100)
        xs, ys = boundary_points(geom, 50.0)
        for x, y in zip(xs, ys):
            # Point must be on one of the four edges
            on_bottom = abs(y) < 1e-9 and 0 <= x <= 100
            on_top = abs(y - 100) < 1e-9 and 0 <= x <= 100
            on_left = abs(x) < 1e-9 and 0 <= y <= 100
            on_right = abs(x - 100) < 1e-9 and 0 <= y <= 100
            assert on_bottom or on_top or on_left or on_right

    def test_box_no_duplicates(self):
        """No point appears twice."""
        geom = box(0, 0, 100, 100)
        xs, ys = boundary_points(geom, 50.0)
        points = list(zip(xs, ys))
        assert len(points) == len(set(points))

    def test_none(self):
        """boundary_points(None) gives two empty arrays."""
        xs, ys = boundary_points(None)
        assert len(xs) == 0
        assert len(ys) == 0


class TestPrepFacilities:
    """Tests for prep_facilities."""

    @pytest.fixture
    def gpkg(self, tmp_path):
        """Create a test GeoPackage with two areas."""
        path = tmp_path / "test.gpkg"
        gdf = geopandas.GeoDataFrame(
            {"fid_zbg": [1, 2], "typzast_k": ["310", "311"]},
            geometry=[box(0, 0, 100, 100), box(500, 0, 600, 100)],
            crs="EPSG:5514",
        )
        pyogrio.write_dataframe(gdf, path, layer="ArealUceloveZastavby", driver="GPKG")
        return path

    def test_prep_returns_stats(self, gpkg, tmp_path):
        """prep_facilities returns correct area/point counts."""
        region = box(0, 0, 1000, 1000)
        out = tmp_path / "region" / "facilities.csv"
        stats = prep_facilities(gpkg, region, 100.0, out)
        assert stats["areas"] == 1
        assert stats["points"] == 8
        assert stats["campsite"] == 1
        assert stats["recreation"] == 0
        assert stats["care"] == 0

    def test_csv_header(self, gpkg, tmp_path):
        """CSV has the expected header columns."""
        region = box(0, 0, 1000, 1000)
        out = tmp_path / "region" / "facilities.csv"
        prep_facilities(gpkg, region, 100.0, out)
        df = pd.read_csv(out)
        expected = ["building_id", "x", "y", "use_code", "number_type",
                    "receptor_type", "unclear"]
        assert list(df.columns) == expected

    def test_csv_first_row(self, gpkg, tmp_path):
        """First data row starts with zbg1_0."""
        region = box(0, 0, 1000, 1000)
        out = tmp_path / "region" / "facilities.csv"
        prep_facilities(gpkg, region, 100.0, out)
        df = pd.read_csv(out)
        assert df.iloc[0]["building_id"] == "zbg1_0"

    def test_csv_receptor_type(self, gpkg, tmp_path):
        """Every row has receptor_type 'campsite'."""
        region = box(0, 0, 1000, 1000)
        out = tmp_path / "region" / "facilities.csv"
        prep_facilities(gpkg, region, 100.0, out)
        df = pd.read_csv(out)
        assert (df["receptor_type"] == "campsite").all()

    def test_multi_receptor_types(self, tmp_path):
        """Areas with codes 313, 412, 413 yield receptor_types recreation, care, care."""
        path = tmp_path / "test.gpkg"
        gdf = geopandas.GeoDataFrame(
            {"fid_zbg": [10, 20, 30], "typzast_k": ["313", "412", "413"]},
            geometry=[box(0, 0, 100, 100), box(200, 0, 300, 100), box(400, 0, 500, 100)],
            crs="EPSG:5514",
        )
        pyogrio.write_dataframe(gdf, path, layer="ArealUceloveZastavby", driver="GPKG")
        region = box(0, 0, 1000, 1000)
        out = tmp_path / "region" / "facilities.csv"
        stats = prep_facilities(path, region, 100.0, out)
        df = pd.read_csv(out)
        types = df["receptor_type"].tolist()
        assert "recreation" in types
        assert "care" in types
        assert stats["campsite"] == 0
        assert stats["care"] == 2
        assert stats["recreation"] == 1
