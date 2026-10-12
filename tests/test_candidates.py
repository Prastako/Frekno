"""Tests for pipeline.candidates."""

import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import box, Polygon

from pipeline.candidates import (
    grid_points,
    mask_at,
    value_at,
    forest_fraction,
    build_candidates,
)


# ── grid_points ──────────────────────────────────────────────────────────


def test_grid_points_box():
    xs, ys = grid_points(box(0, 0, 1000, 1000), (0, 0, 1000, 1000), 250)
    assert len(xs) == 16
    assert list(xs[:4]) == [125, 375, 625, 875]
    assert list(ys[:4]) == [125, 125, 125, 125]
    assert ys[-1] == 875


def test_grid_points_triangle():
    poly = Polygon([(0, 0), (1000, 0), (0, 1000)])
    xs, ys = grid_points(poly, (0, 0, 1000, 1000), 250)
    assert len(xs) == 6


# ── mask_at ──────────────────────────────────────────────────────────────


def test_mask_at():
    m = np.zeros((10, 10), dtype=np.uint8)
    m[0, 0] = 1
    tr = from_origin(0, 100, 10, 10)
    result = mask_at(m, tr, [5, 50, -5], [95, 50, 95])
    assert list(result) == [True, False, False]


# ── forest_fraction ──────────────────────────────────────────────────────


def test_forest_fraction():
    arr = np.ones((11, 11), dtype=np.uint8)
    ff = forest_fraction(arr, 10, 30)
    assert ff[5, 5] == 1.0
    assert ff[0, 0] == pytest.approx(0.3793103, abs=1e-6)


# ── build_candidates helpers ─────────────────────────────────────────────

_BOUNDS = (0, 0, 1000, 1000)
_REGION = box(0, 0, 1000, 1000)
_SPACING = 250
_MIN_HOME = 500
_FOREST_RADIUS = 300


def _make_masks(all_forest=False):
    zero = np.zeros((100, 100), dtype=np.uint8)
    water = np.zeros((100, 100), dtype=np.uint8)
    water[75:100, 0:25] = 1
    forest = np.ones((100, 100), dtype=np.uint8) if all_forest else zero.copy()
    return {
        "water": water,
        "building": zero.copy(),
        "compound": zero.copy(),
        "forest": forest,
        "quarry": zero.copy(),
    }


# ── build_candidates: no homes ───────────────────────────────────────────


def test_build_candidates_no_homes():
    masks = _make_masks()
    tr = from_origin(0, 1000, 10, 10)
    result = build_candidates(
        _REGION, _BOUNDS, _SPACING, masks, tr,
        np.array([], dtype=float), np.array([], dtype=float),
        _MIN_HOME, _FOREST_RADIUS,
    )
    assert result["stats"] == {"grid": 16, "landcover": 1, "near_home": 0, "kept": 15}
    assert all(st == "open" for st in result["site_type"])


# ── build_candidates: one home ───────────────────────────────────────────


def test_build_candidates_one_home():
    masks = _make_masks()
    tr = from_origin(0, 1000, 10, 10)
    result = build_candidates(
        _REGION, _BOUNDS, _SPACING, masks, tr,
        np.array([500.0]), np.array([500.0]),
        _MIN_HOME, _FOREST_RADIUS,
    )
    assert result["stats"] == {"grid": 16, "landcover": 1, "near_home": 12, "kept": 3}
    kept = list(zip(result["x"], result["y"]))
    assert set(kept) == {(875.0, 125.0), (125.0, 875.0), (875.0, 875.0)}


# ── build_candidates: all forest ─────────────────────────────────────────


def test_build_candidates_all_forest():
    masks = _make_masks(all_forest=True)
    tr = from_origin(0, 1000, 10, 10)
    result = build_candidates(
        _REGION, _BOUNDS, _SPACING, masks, tr,
        np.array([], dtype=float), np.array([], dtype=float),
        _MIN_HOME, _FOREST_RADIUS,
    )
    assert result["stats"]["kept"] == 15
    assert all(st == "forest" for st in result["site_type"])
