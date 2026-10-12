"""Free-field levels at a receptor for a rig class and sound character."""

import math

from pipeline.acoustics import (
    HEARING_THRESHOLD_DB,
    air_absorption_db_per_km,
    load_acoustics,
    weighted_level_db,
)


def attenuation_db(d_m: float, ref_m: float, alpha_db_per_km: list[float]) -> list[float]:
    """Geometric spreading plus air-absorption from *ref_m* to *d_m*.

    Per band: ``20 * log10(d_m / ref_m) + alpha[i] * (d_m - ref_m) / 1000``.
    """
    if d_m <= 0:
        raise ValueError("d_m must be positive")
    if ref_m <= 0:
        raise ValueError("ref_m must be positive")
    if len(alpha_db_per_km) != 9:
        raise ValueError("alpha_db_per_km must have 9 values")

    spreading = 20.0 * math.log10(d_m / ref_m)
    return [
        spreading + alpha_db_per_km[i] * (d_m - ref_m) / 1000.0
        for i in range(9)
    ]


def class_spectrum(level_dba: float, character_bands_db: list[float]) -> list[float]:
    """Shift a character spectrum so its A-weighted sum equals *level_dba*."""
    shift = level_dba - weighted_level_db(character_bands_db, "A")
    return [band + shift for band in character_bands_db]


def receptor_levels(
    level_dba: float,
    class_distance_m: float,
    character_bands_db: list[float],
    d_m: float,
    temp_c: float = 10.0,
    humidity_percent: float = 70.0,
    pressure_kpa: float = 101.325,
) -> list[float]:
    """Band levels at a receptor *d_m* away from a rig.

    Source spectrum is the character bands shifted to the class level,
    attenuated by geometric spreading and air absorption.
    """
    spectrum = class_spectrum(level_dba, character_bands_db)
    alpha = air_absorption_db_per_km(temp_c, humidity_percent, pressure_kpa)
    att = attenuation_db(d_m, class_distance_m, alpha)
    return [spectrum[i] - att[i] for i in range(9)]


def night_margin_db(band_levels: list[float], target_dba: float) -> float:
    """Margin to the night reference level.

    Positive means the receptor level is *below* the target.
    """
    return target_dba - weighted_level_db(band_levels, "A")


def worst_band_margin_db(
    band_levels: list[float],
    threshold_db: tuple[float, ...] = HEARING_THRESHOLD_DB,
) -> float:
    """Minimum per-band margin to the hearing threshold.

    Positive means every band is below the threshold.
    """
    return min(threshold_db[i] - band_levels[i] for i in range(9))


def levels_for(class_key: str, character_key: str, d_m: float) -> list[float]:
    """Convenience wrapper: receptor levels for a named class and character.

    Class keys: ``small``, ``medium``, ``large``.
    Character keys: ``balanced``, ``bass_heavy``, ``very_bass_heavy``.
    """
    ac = load_acoustics()

    if class_key not in ac["classes"]:
        raise ValueError(f"unknown class key: {class_key!r}")
    if character_key not in ac["characters"]:
        raise ValueError(f"unknown character key: {character_key!r}")

    cls = ac["classes"][class_key]
    ch = ac["characters"][character_key]
    w = ac["weather"]

    return receptor_levels(
        cls["level_dba"],
        cls["distance_m"],
        ch["bands_db"],
        d_m,
        temp_c=w["temperature_c"],
        humidity_percent=w["humidity_percent"],
        pressure_kpa=w["pressure_kpa"],
    )
