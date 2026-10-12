"""Tests for pipeline.freefield using known-answer CSV files."""

import csv
import pathlib

import pytest

from pipeline.acoustics import air_absorption_db_per_km, weighted_level_db
from pipeline.freefield import (
    attenuation_db,
    class_spectrum,
    levels_for,
    night_margin_db,
    receptor_levels,
    worst_band_margin_db,
)

KA = pathlib.Path(__file__).resolve().parent / "known_answers"


def _read(path: pathlib.Path) -> list[dict[str, str]]:
    with open(path) as f:
        return list(csv.DictReader(f))


# --- attenuation_from_1m.csv (54 rows) ---

_att_rows = _read(KA / "attenuation_from_1m.csv")


@pytest.mark.parametrize("row", _att_rows, ids=lambda r: f"{r['distance_km']}km-{r['band_hz']}Hz")
def test_attenuation_from_1m(row):
    distance_m = float(row["distance_km"]) * 1000
    alpha = air_absorption_db_per_km(10, 70)
    att = attenuation_db(distance_m, 1.0, alpha)
    expected = float(row["attenuation_db"])
    # Find the correct band index by frequency
    bands_hz = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000]
    idx = bands_hz.index(float(row["band_hz"]))
    assert att[idx] == pytest.approx(expected, abs=0.01)


# --- receptor_levels.csv (486 rows) ---

_rec_rows = _read(KA / "receptor_levels.csv")


@pytest.mark.parametrize("row", _rec_rows, ids=lambda r: f"{r['class']}-{r['character']}-{r['distance_km']}km-{r['band_hz']}Hz")
def test_receptor_levels(row):
    cls = row["class"]
    ch = row["character"]
    distance_m = float(row["distance_km"]) * 1000
    bands = levels_for(cls, ch, distance_m)
    expected = float(row["level_db"])
    bands_hz = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000]
    idx = bands_hz.index(float(row["band_hz"]))
    assert bands[idx] == pytest.approx(expected, abs=0.01)


# --- margins.csv (54 rows) ---

_mar_rows = _read(KA / "margins.csv")


@pytest.mark.parametrize("row", _mar_rows, ids=lambda r: f"{r['class']}-{r['character']}-{r['distance_km']}km")
def test_margins(row):
    cls = row["class"]
    ch = row["character"]
    distance_m = float(row["distance_km"]) * 1000
    bands = levels_for(cls, ch, distance_m)

    assert weighted_level_db(bands, "A") == pytest.approx(float(row["dba"]), abs=0.01)
    assert weighted_level_db(bands, "C") == pytest.approx(float(row["dbc"]), abs=0.01)
    assert night_margin_db(bands, 35) == pytest.approx(float(row["margin_night_target_db"]), abs=0.01)
    assert worst_band_margin_db(bands) == pytest.approx(
        float(row["worst_band_margin_threshold_db"]), abs=0.01
    )


# --- receptor_levels at class distance equals class_spectrum ---

def test_receptor_at_class_distance():
    """At the class reference distance (40 m), receptor_levels == class_spectrum."""
    balanced_bands = [99, 109, 100, 97, 97, 92, 88, 84, 78]
    levels = receptor_levels(99, 40, balanced_bands, 40)
    expected = class_spectrum(99, balanced_bands)
    for i in range(9):
        assert levels[i] == pytest.approx(expected[i], abs=1e-9)


# --- ValueError cases ---

def test_attenuation_zero_distance():
    alpha = air_absorption_db_per_km(10, 70)
    with pytest.raises(ValueError):
        attenuation_db(0, 1.0, alpha)


def test_levels_for_bad_class():
    with pytest.raises(ValueError):
        levels_for("huge", "balanced", 1000)
