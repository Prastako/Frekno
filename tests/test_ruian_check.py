"""Tests for pipeline.ruian_check."""

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely.geometry import box

from pipeline.fetch.ruian_shp import read_obec_buildings, write_buildings_csv
from pipeline.ruian_check import (
    AREA_CODES,
    CAMP_COLUMNS,
    CODE_COUNT_COLUMNS,
    area_check,
    buildings_in_region,
    campsites,
    code_counts,
    load_use_names,
    read_areas,
    ruian_check,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REGION = box(-760000, -1065000, -745000, -1050000)


def _make_zbgaged(tmp_path: Path) -> Path:
    """Create a minimal GeoPackage with ZABAGED purpose-area data."""
    gpkg = tmp_path / "z.gpkg"
    gdf = gpd.GeoDataFrame(
        {
            "fid_zbg": [1, 2, 3],
            "jmeno": ["Kemp A", None, "X"],
            "typzast_k": ["310", "312", "999"],
        },
        geometry=[
            box(-751400, -1057100, -751200, -1056900),
            box(-753000, -1057200, -752800, -1057000),
            box(-752000, -1056000, -751000, -1055000),
        ],
        crs="EPSG:5514",
    )
    gdf.to_file(gpkg, layer="ArealUceloveZastavby")
    return gpkg


def test_load_use_names():
    names = load_use_names()
    assert 3 in names
    assert names[3] == "objekt k bydlení"
    assert names[8] == "stavba pro rodinnou rekreaci"


def test_buildings_in_region(tmp_path):
    zip_path = FIXTURES / "ruian_obec_539139_mini.zip"
    bcsv = tmp_path / "b.csv"
    write_buildings_csv(read_obec_buildings(zip_path), bcsv)

    df = buildings_in_region(bcsv, REGION)
    assert len(df) == 25
    assert "receptor_type" in df.columns
    assert "unclear" in df.columns
    assert df["receptor_type"].isin(["home", "cottage", "ignore"]).all()
    assert (df["use_code"].isna().sum()) == 9


def test_code_counts(tmp_path):
    zip_path = FIXTURES / "ruian_obec_539139_mini.zip"
    bcsv = tmp_path / "b.csv"
    write_buildings_csv(read_obec_buildings(zip_path), bcsv)

    df = buildings_in_region(bcsv, REGION)
    names = load_use_names()
    rows = code_counts(df, names)

    assert len(rows) == 9
    # First row: use_code 3
    assert rows[0]["use_code"] == 3
    assert rows[0]["use_name"] == "objekt k bydlení"
    assert rows[0]["number_type"] == "cp"
    assert rows[0]["receptor_type"] == "home"
    assert rows[0]["unclear"] is False
    assert rows[0]["count"] == 1

    # Rows with missing use_code (sorted last)
    missing = [r for r in rows if r["use_code"] is None]
    assert len(missing) == 3  # cp, ce, none
    nt_counts = {r["number_type"]: r["count"] for r in missing}
    assert nt_counts["cp"] == 3
    assert nt_counts["ce"] == 2
    assert nt_counts["none"] == 4


def test_area_check(tmp_path):
    zip_path = FIXTURES / "ruian_obec_539139_mini.zip"
    bcsv = tmp_path / "b.csv"
    write_buildings_csv(read_obec_buildings(zip_path), bcsv)
    gpkg = _make_zbgaged(tmp_path)

    df = buildings_in_region(bcsv, REGION)
    areas = read_areas(gpkg, REGION)
    rows = area_check(df, areas)

    assert len(rows) == 9

    r310 = rows[0]  # 310 is first in AREA_CODES
    assert r310["area_code"] == 310
    assert r310["areas"] == 1
    assert r310["buildings"] == 1
    assert r310["home"] == 1

    r312 = rows[1]
    assert r312["area_code"] == 312
    assert r312["areas"] == 1
    assert r312["buildings"] == 1
    assert r312["home"] == 1

    r313 = rows[2]
    assert r313["area_code"] == 313
    assert r313["areas"] == 0


def test_campsites(tmp_path):
    zip_path = FIXTURES / "ruian_obec_539139_mini.zip"
    bcsv = tmp_path / "b.csv"
    write_buildings_csv(read_obec_buildings(zip_path), bcsv)
    gpkg = _make_zbgaged(tmp_path)

    df = buildings_in_region(bcsv, REGION)
    areas = read_areas(gpkg, REGION)
    rows = campsites(df, areas)

    assert len(rows) == 1
    r = rows[0]
    assert r["fid_zbg"] == 1
    assert r["name"] == "Kemp A"
    assert r["area_ha"] == 4.0
    assert r["buildings_inside"] == 1
    assert r["receptors_inside"] == 1


def test_ruian_check_summary(tmp_path):
    zip_path = FIXTURES / "ruian_obec_539139_mini.zip"
    bcsv = tmp_path / "b.csv"
    write_buildings_csv(read_obec_buildings(zip_path), bcsv)
    gpkg = _make_zbgaged(tmp_path)
    out_dir = tmp_path / "out"

    summary = ruian_check(bcsv, REGION, gpkg, out_dir)

    assert summary["buildings"] == 25
    assert summary["home"] == 11
    assert summary["cottage"] == 7
    assert summary["ignore"] == 7
    assert summary["unclear"] == 11
    assert summary["no_code"] == 9
    assert summary["campsites"] == 1
    assert summary["campsites_without_receptor_within_200m"] == 0

    # summary.json was written
    assert (out_dir / "summary.json").exists()
    with open(out_dir / "summary.json") as f:
        saved = json.load(f)
    assert saved == summary


def test_ruian_check_outputs(tmp_path):
    zip_path = FIXTURES / "ruian_obec_539139_mini.zip"
    bcsv = tmp_path / "b.csv"
    write_buildings_csv(read_obec_buildings(zip_path), bcsv)
    gpkg = _make_zbgaged(tmp_path)
    out_dir = tmp_path / "out"

    ruian_check(bcsv, REGION, gpkg, out_dir)

    # code_counts.csv
    cc = pd.read_csv(out_dir / "code_counts.csv")
    assert len(cc) == 9
    assert list(cc.columns) == CODE_COUNT_COLUMNS

    # area_check.csv
    ac = pd.read_csv(out_dir / "area_check.csv")
    assert len(ac) == 9

    # campsites.csv
    cs = pd.read_csv(out_dir / "campsites.csv")
    assert len(cs) == 1
    assert cs["fid_zbg"].iloc[0] == 1
    assert cs["name"].iloc[0] == "Kemp A"
