"""Tests for pipeline.receptors."""

import csv
from pathlib import Path

import pytest

from pipeline.receptors import (
    classify,
    counts_by_code,
    load_type_map,
    build_receptors,
    number_type_from_text,
    read_buildings_csv,
    write_receptors_csv,
)


@pytest.fixture
def type_map():
    return load_type_map()


# -- number_type_from_text ------------------------------------------------

def test_number_type_from_text():
    assert number_type_from_text("č.p. 1731") == "cp"
    assert number_type_from_text("č.e. 12") == "ce"
    assert number_type_from_text("bez čp/če") == "none"
    assert number_type_from_text(None) == "none"  # type: ignore[arg-type]


# -- classify ------------------------------------------------------------

def test_classify_known_home(type_map):
    assert classify(7, "none", type_map) == ("home", False)


def test_classify_known_cottage(type_map):
    assert classify(8, "cp", type_map) == ("cottage", False)


def test_classify_none_code_cp(type_map):
    assert classify(None, "cp", type_map) == ("home", True)


def test_classify_none_code_ce(type_map):
    assert classify(None, "ce", type_map) == ("cottage", True)


def test_classify_none_code_none(type_map):
    assert classify(None, "none", type_map) == ("ignore", True)


def test_classify_unclear_code_cp(type_map):
    """Code 11 is 'unclear' in the type map, so cp falls back to home."""
    assert classify(11, "cp", type_map) == ("home", True)


# -- build_receptors ------------------------------------------------------

def _make_rows(codes_numtypes, bid_prefix="b", x=-1_500_000.0, y=-2_800_000.0):
    """Helper: create building dicts from a list of (use_code, number_type)."""
    return [
        {
            "building_id": f"{bid_prefix}{i}",
            "use_code": code,
            "number_type": nt,
            "x": x,
            "y": y,
        }
        for i, (code, nt) in enumerate(codes_numtypes)
    ]


def test_build_receptors_main(type_map):
    data = [
        (7, "cp"),
        (8, "ce"),
        (18, "none"),
        (None, "cp"),
        (None, "ce"),
        (None, "none"),
        (99, "cp"),
        (11, "none"),
        (8, "cp"),
    ]
    rows = _make_rows(data)
    receptors, stats = build_receptors(rows, type_map)

    assert len(receptors) == 6
    assert [r["receptor_type"] for r in receptors] == [
        "home", "cottage", "home", "cottage", "home", "cottage"
    ]
    assert stats["rows"] == 9
    assert stats["home"] == 3
    assert stats["cottage"] == 3
    assert stats["unclear"] == 3
    assert stats["ignored"] == 3
    assert stats["ignored_unclear"] == 2
    assert stats["duplicates"] == 0
    assert stats["no_position"] == 0


def test_build_receptors_duplicate(type_map):
    rows = [
        {"building_id": "a", "use_code": 7, "number_type": "cp",
         "x": -1.0, "y": -2.0},
        {"building_id": "a", "use_code": 8, "number_type": "ce",
         "x": -3.0, "y": -4.0},
    ]
    receptors, stats = build_receptors(rows, type_map)
    assert len(receptors) == 1
    assert stats["duplicates"] == 1


def test_build_receptors_no_position(type_map):
    rows = [
        {"building_id": "a", "use_code": 7, "number_type": "cp",
         "x": None, "y": -2.0},
    ]
    receptors, stats = build_receptors(rows, type_map)
    assert len(receptors) == 0
    assert stats["no_position"] == 1


# -- load_type_map --------------------------------------------------------

def test_load_type_map():
    tm = load_type_map()
    assert len(tm) == 30
    assert tm[7] == "home"
    assert tm[8] == "cottage"
    assert tm[18] == "ignore"
    assert tm[11] == "unclear"


def test_load_type_map_custom_path(tmp_path, type_map):
    csv_path = tmp_path / "types.csv"
    csv_path.write_text(
        "code,name,receptor_type,note\n"
        "7,house,home,test\n"
        "8,cottage,cottage,test\n",
        encoding="utf-8",
    )
    tm = load_type_map(path=csv_path)
    assert len(tm) == 2
    assert tm[7] == "home"
    assert tm[8] == "cottage"


# -- read_buildings_csv ---------------------------------------------------

def test_read_buildings_csv(tmp_path):
    csv_path = tmp_path / "buildings.csv"
    csv_path.write_text(
        "building_id,use_code,number_type,x,y\n"
        " 1 ,7,cp,-1500000,-2800000\n"
        "2,,ce,-1500001,-2800001\n"
        "3,8,bad_type,-1500002,-2800002\n"
        "4,7,cp,,\n"
        "5,7,cp,abc,def\n"
        "6,7,cp,nan,100\n",
        encoding="utf-8",
    )
    rows = read_buildings_csv(csv_path)
    assert len(rows) == 6
    assert rows[0]["building_id"] == "1"
    assert rows[0]["use_code"] == 7
    assert rows[1]["use_code"] is None
    assert rows[2]["number_type"] == "none"  # bad_type -> "none"
    assert rows[3]["x"] is None
    assert rows[4]["x"] is None
    assert rows[5]["x"] is None  # NaN -> None


# -- write_receptors_csv --------------------------------------------------

def test_write_receptors_csv(tmp_path):
    receptors = [
        {"building_id": "a", "x": -1500000.0, "y": -2800000.0,
         "use_code": 7, "number_type": "cp",
         "receptor_type": "home", "unclear": False},
        {"building_id": "b", "x": -1500001.0, "y": -2800001.0,
         "use_code": None, "number_type": "ce",
         "receptor_type": "cottage", "unclear": True},
    ]
    out = tmp_path / "out.csv"
    write_receptors_csv(receptors, out)

    with open(out, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        recs = list(reader)
    assert len(recs) == 2
    assert recs[0]["use_code"] == "7"
    assert recs[0]["unclear"] == "false"
    assert recs[1]["use_code"] == ""
    assert recs[1]["unclear"] == "true"


# -- counts_by_code -------------------------------------------------------

def test_counts_by_code(type_map):
    rows = [
        {"building_id": "a", "use_code": 7, "number_type": "cp", "x": 0.0, "y": 0.0},
        {"building_id": "b", "use_code": 7, "number_type": "cp", "x": 0.0, "y": 0.0},
        {"building_id": "c", "use_code": None, "number_type": "ce", "x": 0.0, "y": 0.0},
    ]
    result = counts_by_code(rows, type_map)
    assert len(result) == 2
    assert result[0]["use_code"] == 7
    assert result[0]["number_type"] == "cp"
    assert result[0]["count"] == 2
    assert result[0]["unclear"] is False
    assert result[1]["use_code"] is None
    assert result[1]["unclear"] is True


# -- nan position ---------------------------------------------------------

def test_nan_position_skipped(type_map):
    rows = [
        {"building_id": "a", "use_code": 7, "number_type": "cp",
         "x": -740000.0, "y": float("nan")},
        {"building_id": "b", "use_code": 7, "number_type": "cp",
         "x": float("nan"), "y": -1040000.0},
    ]
    receptors, stats = build_receptors(rows, type_map)
    assert len(receptors) == 0
    assert stats["no_position"] == 2
