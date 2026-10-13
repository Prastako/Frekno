"""Tests for pipeline.cli."""

import json
from io import StringIO

import pytest

import pipeline.cli


def test_nm_tile_parse():
    """Parsing nm-tile with all flags."""
    parser = pipeline.cli.build_parser()
    args = parser.parse_args(
        [
            "--out", "x",
            "nm-tile", "20k_1_2",
            "--variant", "soft",
            "--res", "50",
            "--n", "3",
            "--java-opts=-Xmx2g",
        ]
    )
    assert args.command == "nm-tile"
    assert args.tile == "20k_1_2"
    assert args.variant == "soft"
    assert args.res == 50.0
    assert args.n == 3
    assert args.out == "x"
    assert args.java_opts == "-Xmx2g"


def test_nm_tile_bad_variant():
    """Invalid variant causes SystemExit."""
    parser = pipeline.cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["nm-tile", "t", "--variant", "wet"])


def test_nm_dir_name():
    """nm_dir_name formats tile, variant, and resolution."""
    assert pipeline.cli.nm_dir_name("20k_1_2", "hard", 25.0) == "20k_1_2_hard_25m"


def test_main_prep_dem_index(tmp_path, monkeypatch):
    """main() for prep-dem-index delegates correctly and returns 0."""

    def fake_prep_dem_index(dmr_dir, out_csv):
        fake_prep_dem_index._dmr_dir = dmr_dir
        fake_prep_dem_index._out_csv = out_csv
        return {"sheets": 3}

    monkeypatch.setattr(pipeline.cli, "prep_dem_index", fake_prep_dem_index)
    captured = StringIO()
    monkeypatch.setattr("sys.stdout", captured)

    ret = pipeline.cli.main(["--out", str(tmp_path), "prep-dem-index"])
    assert ret == 0

    out = json.loads(captured.getvalue().strip())
    assert out == {"sheets": 3}
    assert fake_prep_dem_index._out_csv == tmp_path / "region" / "dem_index.csv"


def test_main_prep_facilities(tmp_path, monkeypatch):
    """main() for prep-facilities delegates correctly and returns 0."""

    def fake_prep_facilities(zabaged, region, radius_m, out_csv):
        fake_prep_facilities._region = region
        fake_prep_facilities._out_csv = out_csv
        return {"areas": 1}

    monkeypatch.setattr(pipeline.cli, "prep_facilities", fake_prep_facilities)
    monkeypatch.setattr(pipeline.cli, "read_region_geojson", lambda path: "R")
    captured = StringIO()
    monkeypatch.setattr("sys.stdout", captured)

    ret = pipeline.cli.main(["--out", str(tmp_path), "prep-facilities"])
    assert ret == 0

    out = json.loads(captured.getvalue().strip())
    assert out == {"areas": 1}
    assert fake_prep_facilities._region == "R"
    assert fake_prep_facilities._out_csv == tmp_path / "region" / "facilities.csv"


def test_main_nm_tile_fail(tmp_path, monkeypatch):
    """main() returns 1 when nm_tile reports ok=False."""

    def fake_nm_tile(
        tile,
        settings,
        dem_index,
        gpkg,
        screen_dir,
        work_dir,
        nm_home,
        java,
        variant=None,
        res_m=None,
        n_cand=None,
        java_opts=None,
        timeout_s=None,
    ):
        fake_nm_tile._work_dir = work_dir
        fake_nm_tile._res_m = res_m
        return {"ok": False}

    monkeypatch.setattr(pipeline.cli, "nm_tile", fake_nm_tile)
    monkeypatch.setattr(pipeline.cli, "read_index_csv", lambda path: [])
    captured = StringIO()
    monkeypatch.setattr("sys.stdout", captured)

    ret = pipeline.cli.main(["--out", str(tmp_path), "nm-tile", "20k_1_2", "--res", "50"])
    assert ret == 1
    assert fake_nm_tile._work_dir == tmp_path / "nm" / "20k_1_2_zabaged_50m"
    assert fake_nm_tile._res_m == 50.0
