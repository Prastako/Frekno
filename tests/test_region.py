"""Tests for pipeline.region."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import box

from pipeline.region import (
    TILE_COLUMNS,
    load_receptors,
    prep_buildings,
    prep_dem_index,
    prep_receptors,
    prep_region,
    read_region_geojson,
    read_tiles_csv,
    tile_rows,
    write_region_geojson,
    write_tiles_csv,
)
from pipeline.receptors import write_receptors_csv

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


# -- GeoJSON round-trip ---------------------------------------------------

class TestRegionGeojsonRoundTrip:
    """write_region_geojson + read_region_geojson form a round-trip."""

    def test_round_trip(self, tmp_path: Path):
        geom = box(-760000, -1060000, -720000, -1020000)
        p = tmp_path / "region.geojson"
        write_region_geojson(geom, p)
        restored = read_region_geojson(p)
        assert restored.equals(geom)

    def test_parent_dir_created(self, tmp_path: Path):
        geom = box(0, 0, 100, 100)
        p = tmp_path / "sub" / "dir" / "region.geojson"
        write_region_geojson(geom, p)
        assert p.exists()


# -- Tile rows ------------------------------------------------------------

class TestTileRows:
    """tile_rows builds dicts for tiles overlapping a region."""

    def test_two_by_two(self):
        """A 40km x 40km region aligned to 20km tiles gives 4 full tiles."""
        region = box(-760000, -1060000, -720000, -1020000)
        rows = tile_rows(region, 20000)
        assert len(rows) == 4
        for r in rows:
            assert r["region_km2"] == pytest.approx(400.0, abs=1e-6)
            assert r["full"] is True

    def test_partial_tile(self):
        """A small region inside a single tile is not full."""
        region = box(-759000, -1059000, -758000, -1058000)
        rows = tile_rows(region, 20000)
        assert len(rows) == 1
        r = rows[0]
        assert r["tile_id"] == "20k_-38_-53"
        assert r["ix"] == -38
        assert r["iy"] == -53
        assert r["xmin"] == -760000
        assert r["ymin"] == -1060000
        assert r["region_km2"] == pytest.approx(1.0, abs=1e-6)
        assert r["full"] is False

    def test_total_area(self):
        """Sum of region_km2 across tiles equals region area in km²."""
        region = box(-760000, -1060000, -720000, -1020000)
        rows = tile_rows(region, 20000)
        total = sum(r["region_km2"] for r in rows)
        assert total == pytest.approx(1600.0, abs=1e-6)


# -- Tile CSV round-trip --------------------------------------------------

class TestTilesCsvRoundTrip:
    """write_tiles_csv + read_tiles_csv form a round-trip."""

    def test_round_trip(self, tmp_path: Path):
        region = box(-760000, -1060000, -720000, -1020000)
        rows = tile_rows(region, 20000)
        p = tmp_path / "tiles.csv"
        write_tiles_csv(rows, p)
        restored = read_tiles_csv(p)
        assert len(restored) == len(rows)
        for orig, rest in zip(rows, restored):
            assert rest["tile_id"] == orig["tile_id"]
            assert rest["ix"] == orig["ix"]
            assert rest["iy"] == orig["iy"]
            assert rest["xmin"] == pytest.approx(orig["xmin"], abs=1e-6)
            assert rest["ymin"] == pytest.approx(orig["ymin"], abs=1e-6)
            assert rest["xmax"] == pytest.approx(orig["xmax"], abs=1e-6)
            assert rest["ymax"] == pytest.approx(orig["ymax"], abs=1e-6)
            assert rest["region_km2"] == pytest.approx(
                orig["region_km2"], abs=1e-6
            )
            assert rest["full"] == orig["full"]

    def test_columns(self, tmp_path: Path):
        """CSV header matches TILE_COLUMNS."""
        region = box(-760000, -1060000, -720000, -1020000)
        rows = tile_rows(region, 20000)
        p = tmp_path / "tiles.csv"
        write_tiles_csv(rows, p)
        with open(p, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert list(reader.fieldnames) == TILE_COLUMNS  # type: ignore[union-attr]

    def test_full_written_as_true_false(self, tmp_path: Path):
        """full column uses lowercase true/false strings."""
        region = box(-759000, -1059000, -758000, -1058000)
        rows = tile_rows(region, 20000)
        p = tmp_path / "tiles.csv"
        write_tiles_csv(rows, p)
        with open(p, encoding="utf-8") as f:
            text = f.read()
        assert "false" in text

    def test_parent_dir_created(self, tmp_path: Path):
        p = tmp_path / "sub" / "tiles.csv"
        write_tiles_csv([], p)
        assert p.exists()


# -- prep_region ----------------------------------------------------------

class TestPrepRegion:
    """prep_region orchestrates region and tile preparation."""

    def test_vusc_27(self, tmp_path: Path):
        stat_zip = FIXTURES / "ruian_stat_mini.zip"
        out_dir = tmp_path / "output"
        result = prep_region(stat_zip, "27", 20000, out_dir)
        assert out_dir.exists()
        assert (out_dir / "region.geojson").exists()
        assert (out_dir / "tiles.csv").exists()
        assert result["region_km2"] > 0
        assert result["tiles"] > 0
        assert result["full_tiles"] <= result["tiles"]

    def test_full_tiles_matches_csv(self, tmp_path: Path):
        """full_tiles count in result matches CSV full column."""
        stat_zip = FIXTURES / "ruian_stat_mini.zip"
        out_dir = tmp_path / "output"
        result = prep_region(stat_zip, "27", 20000, out_dir)
        tiles = read_tiles_csv(out_dir / "tiles.csv")
        actual_full = sum(1 for t in tiles if t["full"])
        assert result["full_tiles"] == actual_full


# -- prep_buildings -------------------------------------------------------

class TestPrepBuildings:
    """prep_buildings combines municipality building ZIPs."""

    def test_single_zip(self, tmp_path: Path):
        out_csv = tmp_path / "buildings.csv"
        result = prep_buildings(
            [FIXTURES / "ruian_obec_539139_mini.zip"], out_csv
        )
        assert result["files"] == 1
        assert result["rows"] == 25
        assert result["failed"] == []
        assert out_csv.exists()

    def test_duplicate_zip(self, tmp_path: Path):
        """Two copies of the same ZIP double the row count."""
        out_csv = tmp_path / "buildings.csv"
        result = prep_buildings(
            [
                FIXTURES / "ruian_obec_539139_mini.zip",
                FIXTURES / "ruian_obec_539139_mini.zip",
            ],
            out_csv,
        )
        assert result["files"] == 2
        assert result["rows"] == 50

    def test_csv_content(self, tmp_path: Path):
        """CSV has expected row count."""
        out_csv = tmp_path / "buildings.csv"
        prep_buildings([FIXTURES / "ruian_obec_539139_mini.zip"], out_csv)
        with open(out_csv, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 25


# -- prep_receptors -------------------------------------------------------

class TestPrepReceptors:
    """prep_receptors classifies buildings into receptors."""

    def test_stats_keys(self, tmp_path: Path):
        buildings_csv = tmp_path / "buildings.csv"
        prep_buildings([FIXTURES / "ruian_obec_539139_mini.zip"], buildings_csv)
        receptors_csv = tmp_path / "receptors.csv"
        stats = prep_receptors(buildings_csv, receptors_csv)
        expected_keys = {
            "rows", "home", "cottage", "unclear",
            "ignored", "ignored_unclear", "duplicates", "no_position",
        }
        assert set(stats.keys()) == expected_keys

    def test_receptors_csv_written(self, tmp_path: Path):
        buildings_csv = tmp_path / "buildings.csv"
        prep_buildings([FIXTURES / "ruian_obec_539139_mini.zip"], buildings_csv)
        receptors_csv = tmp_path / "receptors.csv"
        stats = prep_receptors(buildings_csv, receptors_csv)
        assert receptors_csv.exists()
        assert stats["rows"] == 25
        assert stats["home"] + stats["cottage"] <= stats["rows"]


# -- load_receptors -------------------------------------------------------

class TestLoadReceptors:
    """load_receptors loads receptor CSV into numpy arrays."""

    def test_load(self, tmp_path: Path):
        buildings_csv = tmp_path / "buildings.csv"
        prep_buildings([FIXTURES / "ruian_obec_539139_mini.zip"], buildings_csv)
        receptors_csv = tmp_path / "receptors.csv"
        prep_receptors(buildings_csv, receptors_csv)
        receptors = load_receptors(receptors_csv)
        assert "x" in receptors
        assert "y" in receptors
        assert "type" in receptors
        assert "id" in receptors
        assert receptors["x"].dtype == np.float64
        assert receptors["y"].dtype == np.float64
        assert len(receptors["x"]) == len(receptors["y"])


# -- prep_dem_index -------------------------------------------------------

class TestPrepDemIndex:
    """prep_dem_index builds terrain sheet index."""

    def test_empty_dir(self, tmp_path: Path):
        dmr_dir = tmp_path / "dmr"
        dmr_dir.mkdir()
        out_csv = tmp_path / "index.csv"
        result = prep_dem_index(dmr_dir, out_csv)
        assert result["sheets"] == 0
        assert out_csv.exists()


# -- load_receptors with facilities.csv -----------------------------------

class TestLoadReceptorsWithFacilities:
    """load_receptors also reads facilities.csv when present."""

    def test_with_facilities(self, tmp_path: Path):
        """receptors.csv + facilities.csv yields combined rows."""
        receptors_csv = tmp_path / "receptors.csv"
        write_receptors_csv(
            [
                {"building_id": "a1", "x": -750000, "y": -1050000,
                 "use_code": 1, "number_type": "1", "receptor_type": "home",
                 "unclear": False},
                {"building_id": "a2", "x": -750100, "y": -1050100,
                 "use_code": 1, "number_type": "1", "receptor_type": "home",
                 "unclear": False},
            ],
            receptors_csv,
        )
        fac_csv = tmp_path / "facilities.csv"
        write_receptors_csv(
            [
                {"building_id": "zbg5_0", "x": -750200, "y": -1050200,
                 "use_code": 0, "number_type": "0", "receptor_type": "facility",
                 "unclear": False},
            ],
            fac_csv,
        )
        receptors = load_receptors(receptors_csv)
        assert len(receptors["x"]) == 3
        assert receptors["type"][2] == "facility"
        assert receptors["id"][2] == "zbg5_0"

    def test_without_facilities(self, tmp_path: Path):
        """receptors.csv alone yields only receptor rows."""
        receptors_csv = tmp_path / "receptors.csv"
        write_receptors_csv(
            [
                {"building_id": "b1", "x": -760000, "y": -1060000,
                 "use_code": 1, "number_type": "1", "receptor_type": "home",
                 "unclear": False},
                {"building_id": "b2", "x": -760100, "y": -1060100,
                 "use_code": 1, "number_type": "1", "receptor_type": "home",
                 "unclear": False},
            ],
            receptors_csv,
        )
        receptors = load_receptors(receptors_csv)
        assert len(receptors["x"]) == 2