"""Tests for pipeline.settings."""

from pathlib import Path

from pipeline.settings import data_paths, load_settings, screening_cfg


def test_load_settings_ruian_code():
    assert load_settings()["region"]["ruian_vusc_code"] == 27


def test_load_settings_forest_radius():
    assert load_settings()["candidates"]["forest_radius_m"] == 300


def test_screening_cfg():
    cfg = screening_cfg(load_settings())
    assert cfg == {
        "temp_c": 10.0,
        "humidity_percent": 70.0,
        "pressure_kpa": 101.325,
        "ref_class": "medium",
        "ref_character": "very_bass_heavy",
        "radius_m": 10000.0,
        "sector_deg": 5.0,
        "rings_m": [0.0, 1000.0, 2000.0, 4000.0, 7000.0, 10000.0],
        "source_h": 2.0,
        "receptor_h": 4.0,
        "n_points": 200,
        "keep_per_type": 20,
        "method": "iso",
        "g_hard": 0.0,
        "g_soft": 1.0,
        "ground_credit": False,
    }


def test_data_paths_defaults(tmp_path):
    settings = load_settings()
    paths = data_paths(settings, env={})
    assert paths["stat_zip"] == Path(r"C:\AI-Workspace\data\frekno") / "raw" / "ruian" / "stat" / "1.zip"
    assert paths["out_dir"] == Path(r"C:\AI-Workspace\work\frekno-out\spike")


def test_data_paths_env_override(tmp_path):
    settings = load_settings()
    paths = data_paths(settings, env={"FREKNO_DATA": str(tmp_path), "FREKNO_OUT": str(tmp_path / "o")})
    assert paths["dmr_dir"] == tmp_path / "raw" / "dmr4g"
    assert paths["out_dir"] == tmp_path / "o"
