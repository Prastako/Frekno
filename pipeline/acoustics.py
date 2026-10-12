"""Acoustic constants, air absorption, and level sums."""

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# --- Module constants loaded once at import ---


def _load_config():
    path = ROOT / "config" / "acoustics.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_config = _load_config()

BANDS_HZ = tuple(_config["bands_hz"])
A_WEIGHTING_DB = tuple(_config["a_weighting_db"])
C_WEIGHTING_DB = tuple(_config["c_weighting_db"])
HEARING_THRESHOLD_DB = tuple(_config["hearing_threshold_db"])


def load_acoustics(path=None):
    """Parse acoustics.json and return the resulting dict."""
    if path is None:
        path = ROOT / "config" / "acoustics.json"
    else:
        path = Path(path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def exact_centre_hz():
    """Return the exact centre frequency for each octave band."""
    band_index = _config["band_index"]
    return [1000.0 * 10 ** (0.3 * k) for k in band_index]


def air_absorption_db_per_km(temp_c, humidity_percent, pressure_kpa=101.325):
    """ISO 9613-1 air absorption in dB per kilometre per octave band."""
    if humidity_percent < 0 or humidity_percent > 100:
        raise ValueError("humidity_percent must be between 0 and 100")
    if pressure_kpa <= 0:
        raise ValueError("pressure_kpa must be positive")
    if temp_c <= -273.15:
        raise ValueError("temp_c must be above absolute zero")

    T = temp_c + 273.15
    T0 = 293.15
    T01 = 273.16
    pr = pressure_kpa / 101.325

    C = -6.8346 * (T01 / T) ** 1.261 + 4.6151
    h = humidity_percent * 10 ** C / pr

    frequencies = exact_centre_hz()
    result = []
    for f in frequencies:
        frO = pr * (24 + 40400 * h * (0.02 + h) / (0.391 + h))
        frN = pr * (T / T0) ** -0.5 * (
            9 + 280 * h * math.exp(-4.170 * ((T / T0) ** (-1.0 / 3) - 1))
        )
        alpha = 8.686 * f ** 2 * (
            1.84e-11 / pr * (T / T0) ** 0.5
            + (T / T0) ** -2.5
            * (
                0.01275 * math.exp(-2239.1 / T) / (frO + f ** 2 / frO)
                + 0.1068 * math.exp(-3352.0 / T) / (frN + f ** 2 / frN)
            )
        )
        result.append(1000.0 * alpha)
    return result


def energy_sum_db(levels):
    """Energy sum of a list or tuple of dB levels."""
    if not levels:
        raise ValueError("levels must not be empty")
    return 10.0 * math.log10(sum(10.0 ** (L / 10.0) for L in levels))


def weighted_level_db(band_levels, weighting):
    """Weighted level using A, C, or Z weighting."""
    if len(band_levels) != 9:
        raise ValueError("band_levels must have exactly 9 values")
    if weighting == "A":
        weights = A_WEIGHTING_DB
    elif weighting == "C":
        weights = C_WEIGHTING_DB
    elif weighting == "Z":
        weights = (0.0,) * 9
    else:
        raise ValueError(f"Unknown weighting: {weighting}")
    return energy_sum_db([band_levels[i] + weights[i] for i in range(9)])
