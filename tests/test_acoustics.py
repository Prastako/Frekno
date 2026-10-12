"""Tests for pipeline.acoustics."""

import csv
import math

import pytest

from pipeline.acoustics import (
    air_absorption_db_per_km,
    energy_sum_db,
    load_acoustics,
    weighted_level_db,
)


def test_air_absorption_known_values():
    """Air absorption at 10 C, 70% humidity matches known answers CSV."""
    csv_path = pytest.importorskip("pathlib").Path(__file__).resolve().parents[1] / "tests" / "known_answers" / "air_absorption.csv"
    result = air_absorption_db_per_km(10, 70)
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            expected = float(row["alpha_db_per_km"])
            assert result[i] == pytest.approx(expected, abs=1e-6)


def test_weighted_level_balanced_a():
    config = load_acoustics()
    bands = config["characters"]["balanced"]["bands_db"]
    dba = weighted_level_db(bands, "A")
    assert dba == pytest.approx(97.9999187998575, abs=1e-6)


def test_weighted_level_balanced_c():
    config = load_acoustics()
    bands = config["characters"]["balanced"]["bands_db"]
    dbc = weighted_level_db(bands, "C")
    assert dbc == pytest.approx(109.640336638205, abs=1e-6)


def test_weighted_level_bass_heavy_a():
    config = load_acoustics()
    bands = config["characters"]["bass_heavy"]["bands_db"]
    dba = weighted_level_db(bands, "A")
    assert dba == pytest.approx(98.4015328908062, abs=1e-6)


def test_weighted_level_bass_heavy_c():
    config = load_acoustics()
    bands = config["characters"]["bass_heavy"]["bands_db"]
    dbc = weighted_level_db(bands, "C")
    assert dbc == pytest.approx(113.467672433509, abs=1e-6)


def test_weighted_level_very_bass_heavy_a():
    config = load_acoustics()
    bands = config["characters"]["very_bass_heavy"]["bands_db"]
    dba = weighted_level_db(bands, "A")
    assert dba == pytest.approx(98.2122924636509, abs=1e-6)


def test_weighted_level_very_bass_heavy_c():
    config = load_acoustics()
    bands = config["characters"]["very_bass_heavy"]["bands_db"]
    dbc = weighted_level_db(bands, "C")
    assert dbc == pytest.approx(116.18946444416, abs=1e-6)


def test_energy_sum_db_two_zeros():
    assert energy_sum_db([0, 0]) == pytest.approx(3.0103, abs=1e-4)


def test_energy_sum_db_single():
    assert energy_sum_db([60]) == pytest.approx(60, abs=1e-9)


def test_weighted_level_z():
    assert weighted_level_db([0.0] * 9, "Z") == pytest.approx(10 * math.log10(9), abs=1e-9)


def test_air_absorption_humidity_too_high():
    with pytest.raises(ValueError):
        air_absorption_db_per_km(10, 101)


def test_air_absorption_humidity_negative():
    with pytest.raises(ValueError):
        air_absorption_db_per_km(10, -1)


def test_air_absorption_zero_pressure():
    with pytest.raises(ValueError):
        air_absorption_db_per_km(10, 70, 0)


def test_energy_sum_empty():
    with pytest.raises(ValueError):
        energy_sum_db([])


def test_weighted_level_wrong_length():
    with pytest.raises(ValueError):
        weighted_level_db([0.0] * 8, "A")


def test_weighted_level_unknown():
    with pytest.raises(ValueError):
        weighted_level_db([0.0] * 9, "B")
