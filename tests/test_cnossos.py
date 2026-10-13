"""Tests for pipeline.cnossos — CNOSSOS-EU favourable ground and terrain attenuation."""

import numpy as np
import pytest

from pipeline.cnossos import (
    C,
    arc,
    aground_f,
    circle_center,
    dif_db,
    g_prime,
    heights,
    mean_plane,
    mean_plane_split,
    mirror,
)

# Standard octave bands
bands = np.array([31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000])


def test_arc():
    """Arc length on a circle of radius gamma with chord c."""
    gamma = 1000.0
    chords = np.array([100.0, 500.0, 1000.0])
    result = arc(chords, gamma)
    # Arc length > chord length
    assert np.all(result > chords)
    # For small chords, arc ≈ chord
    assert arc(np.array([10.0]), gamma)[0] == pytest.approx(10.0, abs=1e-4)


def test_dif_db():
    """Diffraction attenuation in dB."""
    freqs = bands
    # delta = 0 -> 10*log10(3) for all bands
    result = dif_db(np.array([0.0]), freqs)
    expected = 10.0 * np.log10(3.0)
    np.testing.assert_allclose(result, expected, atol=1e-6)

    # Large delta -> capped at DIF_CAP (25)
    result = dif_db(np.array([100.0]), freqs)
    np.testing.assert_allclose(result, 25.0, atol=1e-6)

    # Negative delta below threshold -> 0
    result = dif_db(np.array([-1.0]), freqs)
    np.testing.assert_allclose(result, 0.0, atol=1e-6)


def test_mean_plane():
    """Weighted least-squares plane fits a line exactly for collinear points."""
    P, m = 3, 100
    t = np.linspace(0, 100, m)[np.newaxis, :].repeat(P, axis=0)
    slope = 0.5
    intercept = 100.0
    z = slope * t + intercept
    w = np.ones((P, m))
    a, b = mean_plane(t, z, w)
    np.testing.assert_allclose(a, slope, atol=1e-10)
    np.testing.assert_allclose(b, intercept, atol=1e-10)


def test_mean_plane_split():
    """Plane split gives correct results for known data."""
    P, m = 1, 5
    t = np.arange(m, dtype=np.float64)[np.newaxis, :]
    z = np.array([[0, 1, 3, 4, 5]])
    w = np.ones((P, m))
    k = np.array([2], dtype=np.intp)
    (a1, b1), (a2, b2) = mean_plane_split(t, z, w, k)
    assert a1[0] > 0
    assert a2[0] > 0
    # Plane 1 covers cols 0-2, plane 2 covers cols 2-4


def test_mirror():
    """Mirror point (0, 10) across plane z=0."""
    a = np.array([0.0])
    b = np.array([0.0])
    t = np.array([0.0])
    z = np.array([10.0])
    ti, zi = mirror(a, b, t, z)
    np.testing.assert_allclose(ti, [0.0], atol=1e-10)
    np.testing.assert_allclose(zi, [-10.0], atol=1e-10)


def test_mirror_on_plane():
    """Point on plane mirrors to itself."""
    a = np.array([1.0])
    b = np.array([0.0])
    t = np.array([1.0])
    z = np.array([1.0])  # on plane z = 1*t + 0
    ti, zi = mirror(a, b, t, z)
    np.testing.assert_allclose(ti, [1.0], atol=1e-10)
    np.testing.assert_allclose(zi, [1.0], atol=1e-10)


def test_circle_center():
    """Circle center is equidistant from S and R."""
    ts = np.array([0.0])
    zs = np.array([252.0])
    tr = np.array([1000.0])
    zr = np.array([254.0])
    gamma = 1000.0
    ct, cz = circle_center(ts, zs, tr, zr, gamma)
    d_s = np.hypot(ct - ts, cz - zs)
    d_r = np.hypot(ct - tr, cz - zr)
    np.testing.assert_allclose(d_s, gamma, atol=1e-6)
    np.testing.assert_allclose(d_r, gamma, atol=1e-6)


def test_heights():
    """Heights above a horizontal plane with known values."""
    a = np.array([0.0])
    b = np.array([0.0])
    t1 = np.array([0.0])
    z1 = np.array([2.0])
    t2 = np.array([10.0])
    z2 = np.array([4.0])
    h1, h2, dp = heights(a, b, t1, z1, t2, z2)
    assert h1[0] == pytest.approx(2.0, abs=1e-10)
    assert h2[0] == pytest.approx(4.0, abs=1e-10)
    assert dp[0] == pytest.approx(10.0, abs=1e-10)


def test_g_prime_interpolation():
    """g_prime interpolates between g_s and g_path for short distances."""
    g_path = np.array([0.0])
    g_s = np.array([1.0])
    zs = np.array([1.0])
    zr = np.array([1.0])
    dp = np.array([1.0])  # Short distance, well below 30*(zs+zr)=60
    result = g_prime(g_path, g_s, zs, zr, dp)
    # dp/q = 1/60 -> gp * 1/60 + gs * (1 - 1/60) = 0 + 59/60
    assert result[0] == pytest.approx(59.0 / 60.0, abs=1e-10)


def test_g_prime_long_distance():
    """g_prime returns g_path for long distances."""
    g_path = np.array([0.5])
    g_s = np.array([1.0])
    zs = np.array([1.0])
    zr = np.array([1.0])
    dp = np.array([100.0])  # > 30*(1+1) = 60
    result = g_prime(g_path, g_s, zs, zr, dp)
    assert result[0] == pytest.approx(g_path[0], abs=1e-10)


def test_aground_f_harsh_ground():
    """a_ground_f with g=0 returns amin = -3*(1-gm)."""
    P = 3
    zs = np.full(P, 2.0)
    zr = np.full(P, 4.0)
    dp = np.full(P, 1000.0)
    g_path = np.zeros(P)
    g_m = np.zeros(P)
    result = aground_f(zs, zr, dp, g_path, g_m, bands)
    # amin = -3 * (1 - 0) = -3 for dp <= 30*(2+4)=180; else -3*(1 + 2*(1-180/1000))
    # dp=1000 > 180 -> amin = -3*(1 + 2*(1 - 0.18)) = -3*(1 + 1.64) = -3*2.64 = -7.92
    expected = -7.92
    np.testing.assert_allclose(result, expected, atol=1e-6)


def test_aground_f_soft_ground():
    """a_ground_f with g=1 returns 0 when capped."""
    P = 3
    zs = np.full(P, 2.0)
    zr = np.full(P, 4.0)
    dp = np.full(P, 1000.0)
    g_path = np.ones(P)
    g_m = np.ones(P)
    result = aground_f(zs, zr, dp, g_path, g_m, bands)
    np.testing.assert_allclose(result, 0.0, atol=1e-6)
