"""Tests for pipeline.cnossos_path — boundary_f (ground + terrain diffraction)."""
import numpy as np

from pipeline.cnossos_path import boundary_f

# Standard octave bands
bands = np.array([31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000])


def test_flat_terrain_hard_ground():
    """Flat terrain with hard ground (g=0): A = -7.92 in every band, not blocked."""
    n = 200
    t = np.linspace(0.5, 999.5, n)[np.newaxis, :]
    z = np.full((1, n), 250.0)
    g = np.zeros((1, n))
    d = np.array([1000.0])
    A, blocked, a_ground = boundary_f(
        t, z, g, d, 250.0, 250.0, 2.0, 4.0, 0.0, 0.0, bands,
    )
    assert blocked[0] == False
    np.testing.assert_allclose(A[0], -7.92, atol=1e-6)


def test_boundary_f_array_params():
    """boundary_f accepts (P,) arrays for zg_s, zg_r, h_s, h_r, g_s, g_r."""
    P = 3
    n = 200
    t = np.linspace(0.5, 999.5, n)[np.newaxis, :].repeat(P, axis=0)
    z = np.full((P, n), 250.0)
    g = np.zeros((P, n))
    d = np.full(P, 1000.0)
    zg_s = np.full(P, 250.0)
    zg_r = np.full(P, 250.0)
    h_s = np.full(P, 2.0)
    h_r = np.full(P, 4.0)
    g_s = np.zeros(P)
    g_r = np.zeros(P)
    A, blocked, a_ground = boundary_f(
        t, z, g, d, zg_s, zg_r, h_s, h_r, g_s, g_r, bands,
    )
    for i in range(P):
        assert blocked[i] == False
        np.testing.assert_allclose(A[i], -7.92, atol=1e-6)


def test_flat_terrain_soft_ground():
    """Flat terrain with soft ground (g=1): A = 0.0."""
    n = 200
    t = np.linspace(0.5, 999.5, n)[np.newaxis, :]
    z = np.full((1, n), 250.0)
    g = np.ones((1, n))
    d = np.array([1000.0])
    A, blocked, a_ground = boundary_f(
        t, z, g, d, 250.0, 250.0, 2.0, 4.0, 1.0, 1.0, bands,
    )
    assert blocked[0] == False
    np.testing.assert_allclose(A[0], 0.0, atol=1e-6)


def test_ridge_blocking():
    """Single ridge at 330 m in middle of 2 km profile: blocked, >15 dB at 1 kHz."""
    n = 199
    t = np.linspace(1.0, 1999.0, n)[np.newaxis, :]
    z = np.full((1, n), 250.0)
    z[0, 99] = 330.0  # ridge in the middle
    g = np.zeros((1, n))
    d = np.array([2000.0])
    A, blocked, a_ground = boundary_f(
        t, z, g, d, 250.0, 250.0, 2.0, 4.0, 0.0, 0.0, bands,
    )
    assert blocked[0] == True
    # 1 kHz is index 5
    assert A[0, 5] > 15.0
