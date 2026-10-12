"""Terrain profiles and terrain-barrier attenuation for screening."""

import math

import numpy as np
from scipy.ndimage import map_coordinates


SOUND_SPEED = 340.0
C2 = 20.0
MAX_BARRIER_DB = 20.0
GRAZING_DB = 10 * math.log10(3)


def sample_dem(dem, transform, xs, ys, nodata=-9999.0) -> np.ndarray:
    """Bilinear terrain height at points.

    Cell values are taken at cell centres.
    Cells equal to *nodata* count as NaN.
    nodata=None: dem already has NaN for missing cells; it is used as is, without a copy.
    """
    arr = np.asarray(dem)
    if nodata is not None:
        arr = arr.astype(np.float64)
        arr[arr == nodata] = np.nan

    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)

    col = (xs - transform.c) / transform.a - 0.5
    row = (ys - transform.f) / transform.e - 0.5

    result = map_coordinates(arr, [row, col], order=1, mode="nearest")
    return result.reshape(xs.shape)


def line_points(x0, y0, x1, y1, n):
    """n points strictly between start and end.

    Returns xs, ys, t each with shape (P, n) where P is the number of profiles.
    t is the horizontal distance from the start.
    """
    x0 = np.atleast_1d(np.asarray(x0, dtype=np.float64))
    y0 = np.atleast_1d(np.asarray(y0, dtype=np.float64))
    x1 = np.atleast_1d(np.asarray(x1, dtype=np.float64))
    y1 = np.atleast_1d(np.asarray(y1, dtype=np.float64))

    # Fractions i / (n + 1) for i = 1..n, shape (n,)
    fractions = np.arange(1, n + 1) / (n + 1)

    dx = x1 - x0  # (P,)
    dy = y1 - y0  # (P,)
    dist = np.sqrt(dx**2 + dy**2)  # (P,)

    # Outer products: (P, n)
    frac = fractions[np.newaxis, :]  # (1, n)

    xs = x0[:, np.newaxis] + dx[:, np.newaxis] * frac
    ys = y0[:, np.newaxis] + dy[:, np.newaxis] * frac
    t = dist[:, np.newaxis] * frac

    return xs, ys, t


def single_edge(t, z, d, zs, zr):
    """Single-edge diffraction: find the worst (largest delta) point per profile.

    t, z have shape (P, n).  d, zs, zr have shape (P,).
    Returns delta, d_ss, d_sr each with shape (P,).
    """
    t = np.asarray(t, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    d = np.asarray(d, dtype=np.float64)
    zs = np.asarray(zs, dtype=np.float64)
    zr = np.asarray(zr, dtype=np.float64)

    P, n = t.shape

    # Line-of-sight height at each t
    los = zs[:, np.newaxis] + (zr[:, np.newaxis] - zs[:, np.newaxis]) * t / d[:, np.newaxis]

    # Only points above LOS and with valid (non-NaN) height count
    above = (z > los) & ~np.isnan(z)

    # Delta for each point
    dt = d[:, np.newaxis] - t
    d_ss_pt = np.sqrt(t**2 + (z - zs[:, np.newaxis])**2)
    d_sr_pt = np.sqrt(dt**2 + (zr[:, np.newaxis] - z)**2)
    direct = np.sqrt(d**2 + (zr - zs)**2)
    delta_pt = d_ss_pt + d_sr_pt - direct[:, np.newaxis]

    # Mask invalid points with a sentinel so argmax picks a valid one
    # We need the max delta among valid points; if none, output 0
    delta_masked = np.where(above, delta_pt, -np.inf)

    # Track whether any point above LOS exists
    any_above = np.any(above, axis=1)

    # Index of max delta per profile
    max_idx = np.argmax(delta_masked, axis=1)

    delta = np.where(
        any_above,
        delta_pt[np.arange(P), max_idx],
        0.0,
    )
    d_ss = np.where(
        any_above,
        d_ss_pt[np.arange(P), max_idx],
        0.0,
    )
    d_sr = np.where(
        any_above,
        d_sr_pt[np.arange(P), max_idx],
        0.0,
    )

    return delta, d_ss, d_sr


def barrier_db(delta, d_ss, d_sr, d, freqs_hz) -> np.ndarray:
    """ISO 9613-2 barrier attenuation without its grazing term.

    delta, d_ss, d_sr, d have shape (P,).
    freqs_hz has shape (F,).
    Returns shape (P, F).
    """
    delta = np.asarray(delta, dtype=np.float64)
    d_ss = np.asarray(d_ss, dtype=np.float64)
    d_sr = np.asarray(d_sr, dtype=np.float64)
    d = np.asarray(d, dtype=np.float64)
    freqs_hz = np.asarray(freqs_hz, dtype=np.float64)

    P = delta.shape[0]
    F = freqs_hz.shape[0]

    # Column vectors for (P, 1) broadcasting against (F,) → (P, F)
    delta_col = delta[:, np.newaxis]
    d_ss_col = d_ss[:, np.newaxis]
    d_sr_col = d_sr[:, np.newaxis]
    d_col = d[:, np.newaxis]
    lam = SOUND_SPEED / freqs_hz  # (F,)

    mask = delta_col > 0

    # Guard against division by zero where delta = 0
    sqrt_arg = d_ss_col * d_sr_col * d_col / (2 * np.where(mask, delta_col, 1.0))
    kmet = np.exp(-np.sqrt(sqrt_arg) / 2000)
    value = 10 * np.log10(3 + (C2 / lam) * delta_col * kmet) - GRAZING_DB
    value = np.minimum(value, MAX_BARRIER_DB)

    return np.where(mask, value, 0.0)
