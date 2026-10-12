"""Load spike settings and derive data paths."""

import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_settings(path=None) -> dict:
    """Parse spike.toml (or *path*) and return the resulting dict."""
    target = path if path is not None else ROOT / "config" / "spike.toml"
    with open(target, "rb") as f:
        return tomllib.load(f)


def data_paths(settings: dict, env=None) -> dict[str, Path]:
    """Build a dict of data-file paths from *settings* and optional *env*."""
    if env is None:
        env = os.environ
    w = settings["paths"]["windows"]
    data_dir = Path(env["FREKNO_DATA"]) if "FREKNO_DATA" in env else Path(w["data_dir"])
    return {
        "data_dir": data_dir,
        "stat_zip": data_dir / "raw" / "ruian" / "stat" / "1.zip",
        "obce_dir": data_dir / "raw" / "ruian" / "obce",
        "dmr_dir": data_dir / "raw" / "dmr4g",
        "zabaged": Path(env["FREKNO_ZABAGED"]) if "FREKNO_ZABAGED" in env else Path(w["zabaged_gpkg"]),
        "out_dir": Path(env["FREKNO_OUT"]) if "FREKNO_OUT" in env else Path(w["out_dir"]),
        "nm_home": Path(env["FREKNO_NM_HOME"]) if "FREKNO_NM_HOME" in env else Path(w["noisemodelling_home"]),
        "java": Path(env["FREKNO_JAVA"]) if "FREKNO_JAVA" in env else Path(w["java"]),
    }


def screening_cfg(settings: dict) -> dict:
    """Return the screening configuration subset as a plain dict."""
    weather = settings["weather"]
    screening = settings["screening"]
    receptors = settings["receptors"]
    source = settings["source"]
    return {
        "temp_c": float(weather["temperature_c"]),
        "humidity_percent": float(weather["humidity_percent"]),
        "pressure_kpa": float(weather["pressure_kpa"]),
        "ref_class": screening["ref_class"],
        "ref_character": screening["ref_character"],
        "radius_m": float(receptors["radius_m"]),
        "sector_deg": float(receptors["selection_sector_deg"]),
        "rings_m": [float(r) for r in receptors["selection_rings_m"]],
        "source_h": float(source["height_m"]),
        "receptor_h": float(receptors["height_m"]),
        "n_points": int(screening["n_points"]),
        "keep_per_type": int(receptors["worst_per_type_for_nm"]),
    }
