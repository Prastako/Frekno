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


def test_select_with_facility():
    """Select with campsite receptors returns keys for home, cottage, and campsite;
    campsite key holds campsite indices; home result is unchanged."""
    rx = np.array([-100, 100, 50, -100], dtype=float)
    ry = np.array([500, 500, -200, -600], dtype=float)
    rtype = np.array(["home", "home", "campsite", "campsite"])

    result = select_receptors(0, 0, rx, ry, rtype, 10000, 5,
                             [0, 1000, 2000, 4000, 7000, 10000])

    assert "home" in result
    assert "cottage" in result
    assert "campsite" in result
    np.testing.assert_array_equal(result["campsite"], [2, 3])
    np.testing.assert_array_equal(result["home"], [0, 1])

    # Compare with result when campsite receptors are removed
    rx_no_fac = np.array([-100, 100], dtype=float)
    ry_no_fac = np.array([500, 500], dtype=float)
    rtype_no_fac = np.array(["home", "home"])
    result_no_fac = select_receptors(0, 0, rx_no_fac, ry_no_fac, rtype_no_fac,
                                     10000, 5, [0, 1000, 2000, 4000, 7000, 10000])
    np.testing.assert_array_equal(result["home"], result_no_fac["home"])


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


def test_per_bin_selection():
    """Four homes due north at 300, 100, 200, 100 m (idx 0-3) and one at 1500 m (idx 4).

    Rings [0, 1500, 2000] put the two 100 m homes in ring 0,
    the 200 m and 300 m homes in ring 1, and the 1500 m home in ring 2.
    """
    rx = np.array([0.0, 0.0, 0.0, 0.0, 0.0])
    ry = np.array([300.0, 100.0, 200.0, 100.0, 1500.0])
    rtype = np.array(["home", "home", "home", "home", "home"])

    result1 = select_receptors(0, 0, rx, ry, rtype, 2000, 90, [0, 1500, 2000], per_bin=1)
    np.testing.assert_array_equal(result1["home"], [1, 4])

    result2 = select_receptors(0, 0, rx, ry, rtype, 2000, 90, [0, 1500, 2000], per_bin=2)
    np.testing.assert_array_equal(result2["home"], [1, 3, 4])

    result3 = select_receptors(0, 0, rx, ry, rtype, 2000, 90, [0, 1500, 2000], per_bin=3)
    np.testing.assert_array_equal(result3["home"], [1, 3, 2, 4])


def test_per_bin_zero_raises():
    """per_bin = 0 raises ValueError."""
    rx = np.array([0.0])
    ry = np.array([500.0])
    rtype = np.array(["home"])

    try:
        select_receptors(0, 0, rx, ry, rtype, 1000, 90, [0, 1000], per_bin=0)
        assert False, "expected ValueError"
    except ValueError:
        pass
