"""Scaffold checks: config and known-answer files exist and parse."""
import csv
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_acoustics_config_has_nine_bands():
    cfg = json.loads((ROOT / "config" / "acoustics.json").read_text(encoding="utf-8"))
    assert cfg["bands_hz"] == [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000]
    for key in ("a_weighting_db", "c_weighting_db", "hearing_threshold_db", "band_index"):
        assert len(cfg[key]) == 9
    for ch in cfg["characters"].values():
        assert len(ch["bands_db"]) == 9


def test_spike_config_parses():
    cfg = tomllib.loads((ROOT / "config" / "spike.toml").read_text(encoding="utf-8"))
    assert cfg["tiles"]["size_m"] == 20000
    assert cfg["receptors"]["radius_m"] == 10000


def test_receptor_types_cover_codes_1_to_30():
    with open(ROOT / "config" / "receptor_types.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [int(r["code"]) for r in rows] == list(range(1, 31))
    assert {r["receptor_type"] for r in rows} <= {"home", "cottage", "unclear", "ignore"}


def test_known_answer_row_counts():
    expected = {"air_absorption.csv": 9, "attenuation_from_1m.csv": 54, "character_levels.csv": 3,
                "receptor_levels.csv": 486, "margins.csv": 54}
    for name, n in expected.items():
        with open(ROOT / "tests" / "known_answers" / name, encoding="utf-8", newline="") as f:
            assert len(list(csv.DictReader(f))) == n, name
