"""Tests for pipeline.details."""

import numpy as np
import pandas as pd
import pytest
import shapely

from pipeline.details import nearest_distance, protected_flags, slope_percent


def test_slope_percent_plane():
    """A plane rising 0.5 m per 10 m cell along x has 5% slope in the interior."""
    dem = np.arange(10, dtype=np.float64) * 0.5
    dem = np.broadcast_to(dem, (10, 10))
    slope = slope_percent(dem, 10.0)
    # Interior cells (not the edges where gradient is different)
    interior = slope[1:-1, 1:-1]
    assert np.all(interior == pytest.approx(5.0, abs=0.01))


def test_nearest_distance_to_line():
    """Distance from point (50, 30) to a horizontal line at y=0 is 30."""
    dist = nearest_distance([50.0], [30.0], [shapely.LineString([(0, 0), (100, 0)])])
    assert dist[0] == pytest.approx(30.0, abs=0.1)


def test_nearest_distance_no_geoms():
    """With no geometries, distance returns the cap."""
    dist = nearest_distance([50.0], [30.0], [])
    assert dist[0] == pytest.approx(5000.0)


def test_protected_flags():
    """A point inside a protected site gets the right bit mask and site id."""
    sites = pd.DataFrame({
        "category": ["chko"],
        "site_id": ["NS-1"],
        "geometry": [shapely.box(-10, -10, 10, 10)],
    })
    bits, ids = protected_flags([0.0], [0.0], sites)
    assert bits[0] == 2  # chko = bit 2
    assert ids[0] == "NS-1"


def test_border_flags():
    from pipeline.details import border_flags

    region = shapely.box(0, 0, 100000, 100000)
    assert list(border_flags([5000.0, 50000.0], [50000.0, 50000.0], region, (0, 0, 100000, 100000), 10000.0)) == [1, 0]
    assert list(border_flags([5000.0], [50000.0], None, (0, 0, 1, 1), 10000.0)) == [0]
