"""Tests for pipeline.profile – terrain profiles and barrier attenuation."""

import numpy as np
import pytest
from rasterio.transform import from_origin

from pipeline.profile import (
    GRAZING_DB,
    MAX_BARRIER_DB,
    SOUND_SPEED,
    barrier_db,
    line_points,
    sample_dem,
    single_edge,
)


class TestSampleDem:
    def test_values(self):
        """2x + 3y + 10 at cell centres on a 20x20 grid."""
        dem = np.zeros((20, 20), dtype=np.float64)
        for row in range(20):
            for col in range(20):
                x = 1005 + 10 * col
                y = 1995 - 10 * row
                dem[row, col] = 2 * x + 3 * y + 10

        tr = from_origin(1000, 2000, 10, 10)

        xs = np.array([1050.0, 1123.4])
        ys = np.array([1950.0, 1876.6])

        heights = sample_dem(dem, tr, xs, ys)

        # (1050, 1950): x=1050, y=1950 -> 2*1050 + 3*1950 + 10 = 7960
        # (1123.4, 1876.6): 2*1123.4 + 3*1876.6 + 10 = 7886.6
        assert heights[0] == pytest.approx(7960.0, abs=1e-3)
        assert heights[1] == pytest.approx(7886.6, abs=1e-3)


class TestLinePoints:
    def test_basic(self):
        """4 points between (0,0) and (300,400)."""
        xs, ys, t = line_points(0, 0, 300, 400, 4)

        assert t[0].tolist() == [100, 200, 300, 400]
        assert xs[0].tolist() == [60, 120, 180, 240]
        assert ys[0].tolist() == [80, 160, 240, 320]


class TestSingleEdge:
    def test_barrier_present(self):
        """Peak delta when a barrier point is above the line-of-sight."""
        t = np.array([[100.0, 400.0, 700.0]])
        z = np.array([[0.0, 30.0, 0.0]])
        d = np.array([1000.0])
        zs = np.array([2.0])
        zr = np.array([4.0])

        delta, d_ss, d_sr = single_edge(t, z, d, zs, zr)

        # sqrt(400^2+28^2) + sqrt(600^2+26^2) - sqrt(1000^2+2^2) = 1.539872
        expected_delta = (
            np.sqrt(400**2 + 28**2) + np.sqrt(600**2 + 26**2) - np.sqrt(1000**2 + 2**2)
        )
        assert delta[0] == pytest.approx(expected_delta, abs=1e-6)
        assert d_ss[0] == pytest.approx(np.sqrt(400**2 + 28**2), abs=1e-6)
        assert d_sr[0] == pytest.approx(np.sqrt(600**2 + 26**2), abs=1e-6)

    def test_no_barrier(self):
        """No points above LOS → all zeros."""
        t = np.array([[100.0, 400.0, 700.0]])
        z = np.array([[0.0, 0.0, 0.0]])
        d = np.array([1000.0])
        zs = np.array([2.0])
        zr = np.array([4.0])

        delta, d_ss, d_sr = single_edge(t, z, d, zs, zr)

        assert delta[0] == 0
        assert d_ss[0] == 0
        assert d_sr[0] == 0


class TestBarrierDb:
    def test_values(self):
        """Row 0: delta=0 → all zeros. Row 1: positive delta → computed values."""
        delta = np.array([0.0, 1.539872])
        d_ss = np.array([0.0, 400.9788])
        d_sr = np.array([0.0, 600.5631])
        d = np.array([1000.0, 1000.0])
        freqs = np.array([63.0957, 1000.0, 7943.28])

        result = barrier_db(delta, d_ss, d_sr, d, freqs)

        # Row 0: all zeros
        assert result[0, 0] == pytest.approx(0, abs=1e-3)
        assert result[0, 1] == pytest.approx(0, abs=1e-3)
        assert result[0, 2] == pytest.approx(0, abs=1e-3)

        # Row 1: ~[0.0983, 1.3446, 5.8910]
        assert result[1, 0] == pytest.approx(0.0983, abs=1e-3)
        assert result[1, 1] == pytest.approx(1.3446, abs=1e-3)
        assert result[1, 2] == pytest.approx(5.8910, abs=1e-3)


class TestSingleEdgeFourProfiles:
    def test_single_edge_four_profiles(self):
        """Four profiles: flat (delta=0), barrier, varying heights (max of 3 pts), NaN barrier."""
        t = np.array([[250.0, 500.0, 750.0],
                      [100.0, 400.0, 700.0],
                      [100.0, 400.0, 700.0],
                      [100.0, 400.0, 700.0]])
        z = np.array([[0.0, 0.0, 0.0],
                      [0.0, 30.0, 0.0],
                      [12.0, 30.0, 25.0],
                      [np.nan, 30.0, np.nan]])
        d = np.array([1000.0] * 4)
        zs = np.array([2.0] * 4)
        zr = np.array([4.0] * 4)

        delta, d_ss, d_sr = single_edge(t, z, d, zs, zr)

        # Profile 0: flat terrain → delta = 0
        assert delta[0] == pytest.approx(0, abs=1e-9)

        # Profile 1: barrier at centre → expected formula
        expected_barrier = (
            np.sqrt(400**2 + 28**2) + np.sqrt(600**2 + 26**2) - np.sqrt(1000**2 + 2**2)
        )
        assert delta[1] == pytest.approx(expected_barrier, abs=1e-9)

        # Profile 2: varying heights → largest of the three point values
        pt_values = [
            np.sqrt(100**2 + (12 - 2)**2) + np.sqrt((1000 - 100)**2 + (4 - 12)**2) - np.sqrt(1000**2 + 2**2),
            np.sqrt(400**2 + (30 - 2)**2) + np.sqrt((1000 - 400)**2 + (4 - 30)**2) - np.sqrt(1000**2 + 2**2),
            np.sqrt(700**2 + (25 - 2)**2) + np.sqrt((1000 - 700)**2 + (4 - 25)**2) - np.sqrt(1000**2 + 2**2),
        ]
        assert delta[2] == pytest.approx(max(pt_values), abs=1e-9)

        # Profile 3: NaN at ends, valid barrier → same as profile 1
        assert delta[3] == pytest.approx(expected_barrier, abs=1e-9)


class TestSampleDemNoCopy:
    def test_sample_dem_does_not_change_input(self):
        dem = np.full((4, 4), 100.0, dtype=np.float64)
        dem[0, 0] = -9999.0
        tr = from_origin(0, 40, 10, 10)
        result = sample_dem(dem, tr, [25.0], [15.0])
        assert dem[0, 0] == -9999.0
        assert result[0] == pytest.approx(100.0, abs=1e-6)

    def test_sample_dem_nodata_none(self):
        dem = np.full((4, 4), 100.0, dtype=np.float64)
        dem[0, 0] = np.nan
        tr = from_origin(0, 40, 10, 10)
        result = sample_dem(dem, tr, [25.0, 5.0], [15.0, 35.0], nodata=None)
        assert result[0] == pytest.approx(100.0, abs=1e-6)
        assert np.isnan(result[1])
