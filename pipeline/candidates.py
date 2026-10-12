"""Candidate party spots on a grid, filtered by land cover and distance to homes."""

import math

import numpy as np
from scipy.signal import fftconvolve
from scipy.spatial import cKDTree
from shapely import contains_xy


SITE_TYPES = ("open", "clearing", "forest")


def grid_points(region, bounds, spacing_m):
    """Return (xs, ys) of grid centres inside *region*."""
    xmin, ymin, xmax, ymax = bounds
    nx = int(math.floor((xmax - xmin) / spacing_m))
    ny = int(math.floor((ymax - ymin) / spacing_m))

    x = xmin + spacing_m / 2 + np.arange(nx) * spacing_m
    y = ymin + spacing_m / 2 + np.arange(ny) * spacing_m

    X, Y = np.meshgrid(x, y)
    xs = X.ravel()
    ys = Y.ravel()

    mask = contains_xy(region, xs, ys)
    return xs[mask], ys[mask]


def mask_at(mask, transform, xs, ys):
    """True where the raster cell at each point is non-zero and in-bounds."""
    col = np.floor((np.asarray(xs, dtype=float) - transform.c) / transform.a).astype(int)
    row = np.floor((np.asarray(ys, dtype=float) - transform.f) / transform.e).astype(int)

    height, width = mask.shape
    in_bounds = (row >= 0) & (row < height) & (col >= 0) & (col < width)
    value = np.zeros(len(xs), dtype=bool)
    if in_bounds.any():
        value[in_bounds] = mask[row[in_bounds], col[in_bounds]] != 0
    return value


def value_at(grid, transform, xs, ys, outside=np.nan):
    """Return the grid value at each point, or *outside* when out-of-bounds."""
    col = np.floor((np.asarray(xs, dtype=float) - transform.c) / transform.a).astype(int)
    row = np.floor((np.asarray(ys, dtype=float) - transform.f) / transform.e).astype(int)

    height, width = grid.shape
    in_bounds = (row >= 0) & (row < height) & (col >= 0) & (col < width)

    result = np.full(len(xs), outside, dtype=np.float64)
    if in_bounds.any():
        result[in_bounds] = grid[row[in_bounds], col[in_bounds]].astype(np.float64)
    return result


def forest_fraction(forest_mask, res_m, radius_m):
    """Smoothed forest fraction using a circular kernel."""
    r = int(math.floor(radius_m / res_m))
    indices = np.arange(-r, r + 1)
    ii, jj = np.meshgrid(indices, indices)
    dist_sq = (ii * res_m) ** 2 + (jj * res_m) ** 2
    kernel = (dist_sq <= radius_m ** 2).astype(np.float64)

    arr = (forest_mask != 0).astype(np.float64)
    # FFT convolution (zero padding); rounding removes FFT noise such as 1e-13
    frac = fftconvolve(arr, kernel, mode="same") / kernel.sum()
    return np.clip(np.round(frac, 9), 0.0, 1.0)


def build_candidates(region, bounds, spacing_m, masks, transform,
                    home_x, home_y, min_home_m, forest_radius_m):
    """Build candidate spots, filter by land-cover and proximity to homes."""
    xs, ys = grid_points(region, bounds, spacing_m)
    n_grid = len(xs)

    # Land-cover filter: water, building, or compound
    landcover = (
        mask_at(masks["water"], transform, xs, ys)
        | mask_at(masks["building"], transform, xs, ys)
        | mask_at(masks["compound"], transform, xs, ys)
    )
    n_landcover = int(np.sum(landcover))

    # Distance to nearest home
    if len(home_x) > 0:
        tree = cKDTree(np.column_stack((home_x, home_y)))
        dists, _ = tree.query(np.column_stack((xs, ys)), k=1)
        near_home = dists < min_home_m
    else:
        near_home = np.zeros(n_grid, dtype=bool)

    n_near_home = int(np.sum(near_home & ~landcover))

    # Keep mask
    keep = ~landcover & ~near_home
    n_kept = int(np.sum(keep))

    if n_kept == 0:
        return {
            "x": np.array([], dtype=np.float64),
            "y": np.array([], dtype=np.float64),
            "in_forest": np.array([], dtype=bool),
            "forest_frac": np.array([], dtype=np.float64),
            "site_type": np.array([], dtype=object),
            "stats": {
                "grid": n_grid,
                "landcover": n_landcover,
                "near_home": n_near_home,
                "kept": n_kept,
            },
        }

    kx = xs[keep]
    ky = ys[keep]

    in_forest = mask_at(masks["forest"], transform, kx, ky)

    ff = forest_fraction(masks["forest"], abs(transform.a), forest_radius_m)
    f_frac = value_at(ff, transform, kx, ky, outside=0.0)

    site_type = np.empty(n_kept, dtype=object)
    site_type[in_forest] = "forest"
    site_type[~in_forest] = np.where(
        f_frac[~in_forest] >= 0.5, "clearing", "open"
    )

    return {
        "x": kx,
        "y": ky,
        "in_forest": in_forest,
        "forest_frac": f_frac,
        "site_type": site_type,
        "stats": {
            "grid": n_grid,
            "landcover": n_landcover,
            "near_home": n_near_home,
            "kept": n_kept,
        },
    }
