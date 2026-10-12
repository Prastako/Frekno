"""Tests for pipeline.select."""

import numpy as np
from pipeline.select import bearing_deg, select_receptors


def test_select_full():
    """Main selection test with multiple receptors, types, sectors, and rings."""
    rx = np.array([0, 0, 10, 2000, 0, 0, 300, 0, -300], dtype=float)
    ry = np.array([500, 300, 1500, 0, -10000, -10001, 0, 300, 0], dtype=float)
    rtype = np.array(
        ["home", "home", "home", "home", "home", "home",
         "cottage", "cottage", "home"]
    )

    result = select_receptors(0, 0, rx, ry, rtype, 10000, 5, [0, 1000, 2000, 4000, 7000, 10000])

    np.testing.assert_array_equal(result["home"], [1, 8, 2, 3, 4])
    np.testing.assert_array_equal(result["cottage"], [6, 7])


def test_bearing_deg():
    """Bearing to four cardinal-direction points from origin."""
    rx = np.array([0, 1, 0, -1], dtype=float)
    ry = np.array([1, 0, -1, 0], dtype=float)
    brng = bearing_deg(0, 0, rx, ry)
    np.testing.assert_array_almost_equal(brng, [0, 90, 180, 270])


def test_invalid_rings():
    """rings_m must end exactly at radius_m."""
    rx = np.array([0.0])
    ry = np.array([500.0])
    rtype = np.array(["home"])

    try:
        select_receptors(0, 0, rx, ry, rtype, 10000, 7, [0, 1000, 9000])
        assert False, "expected ValueError"
    except ValueError:
        pass
