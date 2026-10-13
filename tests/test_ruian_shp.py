"""Tests for pipeline.fetch.ruian_shp."""

import pathlib
import csv

import pytest

from pipeline.fetch.ruian_shp import (
    BUILDING_COLUMNS,
    read_obec_buildings,
    read_region,
    write_buildings_csv,
    so_b_member,
)

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
OBEC_ZIP = FIXTURES / "ruian_obec_539139_mini.zip"
STAT_ZIP = FIXTURES / "ruian_stat_mini.zip"


class TestReadObecBuildings:
    def test_row_count(self):
        rows = read_obec_buildings(OBEC_ZIP)
        assert len(rows) == 25

    def test_first_row(self):
        rows = read_obec_buildings(OBEC_ZIP)
        first = rows[0]
        assert first["building_id"] == "147980607"
        assert first["use_code"] == 7
        assert first["number_type"] == "cp"
        assert first["x"] == pytest.approx(-751293.9, abs=1e-6)
        assert first["y"] == pytest.approx(-1056954.16, abs=1e-6)
        assert first["obec"] == 539139

    def test_use_code_none_count(self):
        rows = read_obec_buildings(OBEC_ZIP)
        none_count = sum(1 for r in rows if r["use_code"] is None)
        assert none_count == 9


class TestReadRegion:
    def test_area_region_27(self):
        geom = read_region(STAT_ZIP, 27)
        area_per_mio = geom.area / 1e6
        assert area_per_mio == pytest.approx(10931.536, abs=0.01)

    def test_area_region_27_str_kod(self):
        geom = read_region(STAT_ZIP, "27")
        area_per_mio = geom.area / 1e6
        assert area_per_mio == pytest.approx(10931.536, abs=0.01)

    def test_missing_region_raises(self):
        with pytest.raises(ValueError):
            read_region(STAT_ZIP, 35)


class TestSoBMember:
    def test_returns_correct_member(self):
        member = so_b_member(OBEC_ZIP)
        assert member == "539139/SO_B.shp"


class TestWriteBuildingsCsv:
    def test_write_then_append(self, tmp_path: pathlib.Path):
        rows = read_obec_buildings(OBEC_ZIP)
        out = tmp_path / "buildings.csv"

        write_buildings_csv(rows[:10], out)
        write_buildings_csv(rows[10:25], out, append=True)

        with open(out, encoding="utf-8") as f:
            lines = f.readlines()

        # 1 header + 25 data lines
        assert len(lines) == 26
        assert lines[0].strip() == ",".join(BUILDING_COLUMNS)

    def test_use_code_none_written_empty(self, tmp_path: pathlib.Path):
        rows = read_obec_buildings(OBEC_ZIP)
        out = tmp_path / "buildings.csv"
        write_buildings_csv(rows, out)

        with open(out, encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            for row in reader:
                if row[0] == "39578399":  # first row with NaN ZPVY_KOD
                    assert row[1] == ""

    def test_creates_parent_dirs(self, tmp_path: pathlib.Path):
        rows = read_obec_buildings(OBEC_ZIP)
        out = tmp_path / "nested" / "dir" / "buildings.csv"
        write_buildings_csv(rows[:1], out)
        assert out.exists()


def test_read_region_whole_state(tmp_path):
    import zipfile

    import geopandas as gpd
    from shapely.geometry import box

    from pipeline.fetch.ruian_shp import read_region

    d = tmp_path / "1"
    d.mkdir()
    gpd.GeoDataFrame({"KOD": [1]}, geometry=[box(0, 0, 10, 10)], crs="EPSG:5514").to_file(d / "STATY_P.shp")
    with zipfile.ZipFile(tmp_path / "1.zip", "w") as z:
        for f in d.iterdir():
            z.write(f, f"1/{f.name}")
    assert read_region(tmp_path / "1.zip", 0).area == 100
