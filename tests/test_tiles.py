"""Tests for pipeline/tiles.py."""

import pytest
from shapely.geometry import box

from pipeline.tiles import (
    bbox_to_wgs84,
    parse_tile_id,
    tile_bounds,
    tile_id,
    tile_index,
    tiles_for_geometry,
)


class TestTileIndex:
    def test_negative_coords(self):
        assert tile_index(-743000, -1043000, 20000) == (-38, -53)

    def test_exact_boundary(self):
        assert tile_index(-740000, -1040000, 20000) == (-37, -52)

    def test_half_past_boundary(self):
        assert tile_index(-740000.5, -1040000, 20000) == (-38, -52)

    def test_invalid_size_m_float(self):
        with pytest.raises(ValueError):
            tile_index(0, 0, 2500)


class TestTileId:
    def test_format(self):
        assert tile_id(-38, -53, 20000) == "20k_-38_-53"


class TestParseTileId:
    def test_roundtrip(self):
        assert parse_tile_id("20k_-38_-53") == (-38, -53, 20000)

    def test_invalid_string(self):
        with pytest.raises(ValueError):
            parse_tile_id("x")


class TestTileBounds:
    def test_with_buffer(self):
        assert tile_bounds(-38, -53, 20000, 10000) == (
            -770000, -1070000, -730000, -1030000,
        )

    def test_negative_buffer(self):
        with pytest.raises(ValueError):
            tile_bounds(0, 0, 20000, -1)


class TestTilesForGeometry:
    def test_two_by_two(self):
        assert tiles_for_geometry(
            box(-760000, -1060000, -720000, -1020000), 20000,
        ) == [
            "20k_-38_-53",
            "20k_-38_-52",
            "20k_-37_-53",
            "20k_-37_-52",
        ]

    def test_single_tile(self):
        assert tiles_for_geometry(
            box(-759000, -1059000, -758000, -1058000), 20000,
        ) == ["20k_-38_-53"]


class TestBboxToWgs84:
    def test_rounding(self):
        lon_min, lat_min, lon_max, lat_max = bbox_to_wgs84(
            -743000, -1044000, -741000, -1042000,
        )
        assert lon_min == pytest.approx(14.4167, abs=1e-3)
        assert lat_min == pytest.approx(50.0784, abs=1e-3)
        assert lon_max == pytest.approx(14.4482, abs=1e-3)
        assert lat_max == pytest.approx(50.0987, abs=1e-3)

    def test_invalid_bbox(self):
        with pytest.raises(ValueError):
            bbox_to_wgs84(0, 0, 0, 10)
