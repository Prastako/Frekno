"""CNOSSOS-EU favourable ground and terrain attenuation for screening profiles.

Pure numpy, vectorised over P profiles and F bands.
Formulas follow Directive (EU) 2015/996, Annex II, 2.5.6 and 2.5.7.
"""

import math

import numpy as np
from numpy import (
    arcsin, exp, log10, maximum, minimum, newaxis, pi, sqrt,
    take_along_axis, where,
)
from numpy.linalg import norm

# --- Constants ---
C = 340.0
A0 = 2e-4
GAMMA_MIN = 1000.0
DIF_CAP = 25.0
EPS_H = 0.01
DP_MIN = 1.0


def arc(c, gamma):
    """Arc-length on a circle of radius *gamma* with chord *c*.

    Both inputs are (P,); returns (P,).
    """
    c = np.asarray(c, dtype=np.float64)
    gamma = np.asarray(gamma, dtype=np.float64)
    ratio = minimum(c / (2.0 * gamma), 1.0)
    return 2.0 * gamma * arcsin(ratio)


def dif_db(delta, freqs_hz):
    """Diffraction attenuation in dB.

    delta: (P,).  freqs_hz: (F,).  Returns (P, F).
    """
    delta = np.asarray(delta, dtype=np.float64)
    freqs_hz = np.asarray(freqs_hz, dtype=np.float64)
    lam = C / freqs_hz  # (F,)
    x = 40.0 * delta[:, newaxis] / lam  # (P, F)
    value = 10.0 * log10(3.0 + x)
    value = where(x >= -2.0, value, 0.0)
    return minimum(value, DIF_CAP)


def mean_plane(t, z, w):
    """Weighted least-squares line z = a*t + b per row.

    t, z, w each have shape (P, m).  Returns a, b each (P,).
    """
    t = np.asarray(t, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    w = np.asarray(w, dtype=np.float64)

    S0 = np.sum(w, axis=1)
    St = np.sum(w * t, axis=1)
    Sz = np.sum(w * z, axis=1)
    Stt = np.sum(w * t * t, axis=1)
    Stz = np.sum(w * t * z, axis=1)

    den = S0 * Stt - St ** 2
    safe_den = 1e-12 * maximum(S0 * Stt, 1.0)
    fallback = (S0 < 2) | (den <= safe_den)

    a = where(fallback, 0.0, (S0 * Stz - St * Sz) / den)
    b = where(fallback, where(S0 == 0, 0.0, Sz / S0), (Sz - a * St) / S0)
    return a, b


def mean_plane_split(t, z, w, k):
    """Two planes split at column *k* (inclusive in both).

    t, z, w: (P, m).  k: (P,) column indices.
    Returns ((a1, b1), (a2, b2)).
    """
    t = np.asarray(t, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    w = np.asarray(w, dtype=np.float64)
    k = np.asarray(k, dtype=np.intp)

    P, m = t.shape
    kw = w * t
    kz = w * z
    ktt = w * t * t
    ktz = w * t * z

    cs0 = np.cumsum(w, axis=1)
    cst = np.cumsum(kw, axis=1)
    csz = np.cumsum(kz, axis=1)
    cstt = np.cumsum(ktt, axis=1)
    cstz = np.cumsum(ktz, axis=1)

    S0_1 = cs0[np.arange(P), k]
    St_1 = cst[np.arange(P), k]
    Sz_1 = csz[np.arange(P), k]
    Stt_1 = cstt[np.arange(P), k]
    Stz_1 = cstz[np.arange(P), k]

    total_S0 = cs0[..., -1]
    total_St = cst[..., -1]
    total_Sz = csz[..., -1]
    total_Stt = cstt[..., -1]
    total_Stz = cstz[..., -1]

    k_prev = np.clip(k - 1, 0, m - 1)
    mask_k = k > 0
    prefix_S0 = cs0[np.arange(P), k_prev]
    prefix_St = cst[np.arange(P), k_prev]
    prefix_Sz = csz[np.arange(P), k_prev]
    prefix_Stt = cstt[np.arange(P), k_prev]
    prefix_Stz = cstz[np.arange(P), k_prev]

    S0_2 = total_S0 - where(mask_k, prefix_S0, 0.0)
    St_2 = total_St - where(mask_k, prefix_St, 0.0)
    Sz_2 = total_Sz - where(mask_k, prefix_Sz, 0.0)
    Stt_2 = total_Stt - where(mask_k, prefix_Stt, 0.0)
    Stz_2 = total_Stz - where(mask_k, prefix_Stz, 0.0)

    def _plane(S0, St, Sz, Stt, Stz):
        den = S0 * Stt - St ** 2
        safe_den = 1e-12 * maximum(S0 * Stt, 1.0)
        fallback = (S0 < 2) | (den <= safe_den)
        a = where(fallback, 0.0, (S0 * Stz - St * Sz) / den)
        b = where(fallback, where(S0 == 0, 0.0, Sz / S0), (Sz - a * St) / S0)
        return a, b

    return _plane(S0_1, St_1, Sz_1, Stt_1, Stz_1), _plane(S0_2, St_2, Sz_2, Stt_2, Stz_2)


def heights(a, b, t1, z1, t2, z2):
    """Heights above plane z = a*t + b and distance along plane.

    All inputs (P,).  Returns h1, h2, dp each (P,).
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    t1 = np.asarray(t1, dtype=np.float64)
    z1 = np.asarray(z1, dtype=np.float64)
    t2 = np.asarray(t2, dtype=np.float64)
    z2 = np.asarray(z2, dtype=np.float64)

    n = sqrt(1.0 + a * a)
    h1 = maximum((z1 - a * t1 - b) / n, 0.0)
    h2 = maximum((z2 - a * t2 - b) / n, 0.0)
    dp = maximum(abs((t2 - t1) + a * (z2 - z1)) / n, DP_MIN)
    return h1, h2, dp


def mirror(a, b, t, z):
    """Mirror point (t, z) across plane z = a*t + b.

    All inputs (P,).  Returns ti, zi each (P,).
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    t = np.asarray(t, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)

    n = sqrt(1.0 + a * a)
    s = maximum((z - a * t - b) / n, 0.0)
    ti = t + 2.0 * s * a / n
    zi = z - 2.0 * s / n
    return ti, zi


def g_prime(g_path, g_s, zs, zr, dp):
    """Interpolated ground factor.

    All inputs (P,).  Returns (P,).
    """
    g_path = np.asarray(g_path, dtype=np.float64)
    g_s = np.asarray(g_s, dtype=np.float64)
    zs = np.asarray(zs, dtype=np.float64)
    zr = np.asarray(zr, dtype=np.float64)
    dp = np.asarray(dp, dtype=np.float64)

    q = 30.0 * (zs + zr)
    return where(
        dp <= q,
        g_path * dp / q + g_s * (1.0 - dp / q),
        g_path,
    )


def aground_f(zs, zr, dp, g_path, g_m, freqs_hz):
    """Favourable ground attenuation.

    zs, zr, dp, g_path, g_m: (P,).  freqs_hz: (F,).
    Returns (P, F).
    """
    zs = np.asarray(zs, dtype=np.float64)
    zr = np.asarray(zr, dtype=np.float64)
    dp = np.asarray(dp, dtype=np.float64)
    g_path = np.asarray(g_path, dtype=np.float64)
    g_m = np.asarray(g_m, dtype=np.float64)
    freqs_hz = np.asarray(freqs_hz, dtype=np.float64)

    hs = maximum(zs + zr, EPS_H)

    zs2 = zs + A0 * (zs / hs) ** 2 * dp ** 2 / 2.0 + 6e-3 * dp / hs
    zr2 = zr + A0 * (zr / hs) ** 2 * dp ** 2 / 2.0 + 6e-3 * dp / hs

    k = 2.0 * pi * freqs_hz / C  # (F,)
    g = g_path[:, newaxis]  # (P, 1)
    f = freqs_hz  # (F,)

    w = 0.0185 * f ** 2.5 * g ** 2.6 / (
        f ** 1.5 * g ** 2.6 + 1.3e3 * f ** 0.75 * g ** 1.3 + 1.16e6
    )  # (P, F)

    dp_col = dp[:, newaxis]  # (P, 1)
    cf = dp_col * (1.0 + 3.0 * w * dp_col * exp(-sqrt(w * dp_col))) / (1.0 + w * dp_col)
    q = cf / k[None, :]  # (P, F)
    r = sqrt(2.0 * q)  # (P, F)

    val = -10.0 * log10(
        4.0 * k[None, :] ** 2 / dp_col ** 2
        * (zs2[:, newaxis] ** 2 - r * zs2[:, newaxis] + q)
        * (zr2[:, newaxis] ** 2 - r * zr2[:, newaxis] + q)
    )

    q_amin = 30.0 * (zs + zr)  # (P,)
    amin = where(
        dp <= q_amin,
        -3.0 * (1.0 - g_m),
        -3.0 * (1.0 - g_m) * (1.0 + 2.0 * (1.0 - 30.0 * (zs + zr) / dp)),
    )[:, newaxis]  # (P, 1)

    return where(g_path[:, newaxis] > 0, maximum(val, amin), amin)


def circle_center(ts, zs, tr, zr, gamma):
    """Circle of radius *gamma* through S and R, centre below chord.

    All inputs (P,).  Returns ct, cz each (P,).
    """
    ts = np.asarray(ts, dtype=np.float64)
    zs = np.asarray(zs, dtype=np.float64)
    tr = np.asarray(tr, dtype=np.float64)
    zr = np.asarray(zr, dtype=np.float64)
    gamma = np.asarray(gamma, dtype=np.float64)

    c = np.hypot(tr - ts, zr - zs)
    ut = (tr - ts) / c
    uz = (zr - zs) / c
    nt = -uz
    nz = ut
    mt = (ts + tr) / 2.0
    mz = (zs + zr) / 2.0
    e = sqrt(gamma ** 2 - (c / 2.0) ** 2)
    ct = mt - nt * e
    cz = mz - nz * e
    return ct, cz


