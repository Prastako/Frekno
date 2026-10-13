"""Cheap screening of candidate spots against nearby homes and cottages."""

import math

import numpy as np

from pipeline.acoustics import A_WEIGHTING_DB, air_absorption_db_per_km, exact_centre_hz
from pipeline.cnossos_path import boundary_f
from pipeline.freefield import levels_for
from pipeline.profile import barrier_db, line_points, sample_dem, single_edge
from pipeline.select import TYPES, bearing_deg, select_receptors

BAND_KEYS = ["a31", "a63", "a125", "a250", "a500", "a1k", "a2k", "a4k", "a8k"]
PAIR_COLUMNS = (
    ["candidate_id", "receptor_type", "rank", "receptor_id",
     "rx", "ry", "dist_m", "bearing_deg"]
    + BAND_KEYS
    + ["ref_level_dba"]
)
CANDIDATE_COLUMNS = (
    ["candidate_id", "x", "y"]
    + [f"n_{t}" for t in TYPES]
    + [f"worst_{t}_dba" for t in TYPES]
    + [f"worst_{t}_63" for t in TYPES]
)


def prepare_dem(dem, nodata=-9999.0) -> np.ndarray:
    """Return float64 copy of dem with NaN where the value equals nodata.

    The input array is not changed.
    """
    arr = np.asarray(dem, dtype=np.float64)
    arr[arr == nodata] = np.nan
    return arr


def _ground_factor(hard, transform, xs, ys, g_hard, g_soft):
    """Ground factor at points: g_hard on hard cells, g_soft elsewhere (nearest cell; outside the grid = g_soft)."""
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    out = np.full(xs.shape, float(g_soft))
    if hard is None:
        return out
    col = np.floor((xs - transform.c) / transform.a).astype(np.int64)
    row = np.floor((ys - transform.f) / transform.e).astype(np.int64)
    ok = (row >= 0) & (row < hard.shape[0]) & (col >= 0) & (col < hard.shape[1])
    out[ok] = np.where(hard[row[ok], col[ok]], float(g_hard), float(g_soft))
    return out


def pair_attenuation(dem, transform, cx, cy, rx, ry,
                     source_h, receptor_h, n_points, alpha,
                     method="iso", hard=None, g_hard=0.0, g_soft=1.0,
                     ground_credit=False, return_blocked=False):
    """Attenuation in dB from 1 m to each receptor.

    Parameters
    ----------
    dem : np.ndarray
        Already prepared DEM (NaN for missing cells).
    transform : rasterio transform
        Affine transform of the DEM.
    cx, cy : float
        Candidate coordinates.
    rx, ry : array-like
        Receptor coordinates, length P.
    source_h, receptor_h : float
        Absolute heights are terrain + these values.
    n_points : int
        Number of intermediate profile points.
    alpha : array-like
        Air-absorption dB/km per band (length 9).

    Returns
    -------
    np.ndarray
        Attenuation in dB, shape (P, 9).
    """
    rx = np.asarray(rx, dtype=np.float64)
    ry = np.asarray(ry, dtype=np.float64)
    P = rx.shape[0]

    if P == 0:
        return np.zeros((0, 9))

    alpha = np.asarray(alpha, dtype=np.float64)

    # Horizontal distance candidate -> receptor
    d = np.hypot(rx - cx, ry - cy)

    # Source height (same value for every row)
    zs = np.full(P,
        float(sample_dem(dem, transform, [cx], [cy], nodata=None)[0]) + source_h,
        dtype=np.float64,
    )

    # Receptor heights
    zr = sample_dem(dem, transform, rx, ry, nodata=None) + receptor_h

    # Intermediate line points (cx, cy repeated to length P)
    cx_arr = np.full(P, cx, dtype=np.float64)
    cy_arr = np.full(P, cy, dtype=np.float64)
    xs, ys, t = line_points(cx_arr, cy_arr, rx, ry, n_points)

    # Terrain heights along each profile
    z = sample_dem(dem, transform, xs.flatten(), ys.flatten(), nodata=None)
    z = z.reshape(t.shape)

    if method == "cnossos":
        g_pts = _ground_factor(hard, transform, xs, ys, g_hard, g_soft)
        g_s = np.full(P, _ground_factor(hard, transform, [cx], [cy], g_hard, g_soft)[0])
        g_r = _ground_factor(hard, transform, rx, ry, g_hard, g_soft)
        A, blocked, a_ground = boundary_f(t, z, g_pts, d, zs - source_h, zr - receptor_h,
                                          source_h, receptor_h, g_s, g_r, exact_centre_hz(),
                                          ground_credit=ground_credit)
        A[:, 0] = np.minimum(a_ground[:, 0], 0.0)  # no terrain credit at 31.5 Hz
        d3 = np.maximum(np.hypot(d, zr - zs), 1.0)[:, np.newaxis]
        result = 20.0 * np.log10(d3) + alpha * (d3 - 1.0) / 1000.0 + A
        return (result, blocked) if return_blocked else result

    # Single-edge diffraction
    delta, d_ss, d_sr = single_edge(t, z, np.maximum(d, 1e-9), zs, zr)

    # Barrier attenuation
    bar = barrier_db(delta, d_ss, d_sr, d, exact_centre_hz())
    bar[:, 0] = 0  # No terrain credit at 31.5 Hz

    # Free-field attenuation
    dd = np.maximum(d, 1.0)[:, np.newaxis]  # (P, 1) for (P, 9) output
    free = 20.0 * np.log10(dd) + alpha * (dd - 1.0) / 1000.0

    result = free + bar
    return (result, delta > 0) if return_blocked else result


def screen_candidates(dem, transform, cand_x, cand_y,
                      rec_x, rec_y, rec_type, rec_id, cfg, hard=None):
    """Screen candidate spots against nearby receptors.

    Parameters
    ----------
    dem : array-like
        Digital elevation model.
    transform : rasterio transform
    cand_x, cand_y : sequence of float
        Candidate coordinates.
    rec_x, rec_y : array-like
        Receptor coordinates.
    rec_type : array-like of str
        Receptor type labels.
    rec_id : array-like of str
        Receptor identifiers.
    cfg : dict
        Configuration with keys: temp_c, humidity_percent, pressure_kpa,
        ref_class, ref_character, radius_m, sector_deg, rings_m,
        source_h, receptor_h, n_points, keep_per_type.

    Returns
    -------
    (list[dict], list[dict])
        Candidate rows and pair rows.
    """
    dem = prepare_dem(dem)
    alpha = air_absorption_db_per_km(
        cfg["temp_c"], cfg["humidity_percent"], cfg["pressure_kpa"]
    )
    l1m = levels_for(cfg["ref_class"], cfg["ref_character"], 1.0)
    a_weighting = np.asarray(A_WEIGHTING_DB, dtype=np.float64)

    cand_x = np.asarray(cand_x, dtype=np.float64)
    cand_y = np.asarray(cand_y, dtype=np.float64)
    rec_x = np.asarray(rec_x, dtype=np.float64)
    rec_y = np.asarray(rec_y, dtype=np.float64)
    rec_type = np.asarray(rec_type)
    rec_id = np.asarray(rec_id)

    candidates = []
    pairs = []

    for i in range(len(cand_x)):
        cx = float(cand_x[i])
        cy = float(cand_y[i])

        sel = select_receptors(cx, cy, rec_x, rec_y, rec_type,
                               cfg["radius_m"], cfg["sector_deg"], cfg["rings_m"],
                               int(cfg.get("per_bin", 1)))

        cand_row = {"candidate_id": int(i), "x": cx, "y": cy}

        for t in TYPES:
            indices = sel[t]
            n = len(indices)
            cand_row[f"n_{t}"] = n

            if n == 0:
                cand_row[f"worst_{t}_dba"] = None
                cand_row[f"worst_{t}_63"] = None
                continue

            # Coordinates of selected receptors of type t
            t_rx = rec_x[indices]
            t_ry = rec_y[indices]
            t_rid = rec_id[indices]

            att = pair_attenuation(
                dem, transform, cx, cy, t_rx, t_ry,
                cfg["source_h"], cfg["receptor_h"], cfg["n_points"], alpha,
                method=cfg.get("method", "iso"), hard=hard,
                g_hard=cfg.get("g_hard", 0.0), g_soft=cfg.get("g_soft", 1.0),
                ground_credit=cfg.get("ground_credit", False),
            )

            # Band levels at each receptor
            levels = np.asarray(l1m, dtype=np.float64) - att

            # dB(A) per receptor
            dba = 10.0 * np.log10(
                np.sum(10.0 ** ((levels + a_weighting) / 10.0), axis=1)
            )

            # Sort by dba descending (stable sort preserves selection order for ties)
            order = np.argsort(-dba, kind="stable")

            # Worst dB(A) over ALL selected receptors of this type
            worst_dba = float(np.max(dba))
            cand_row[f"worst_{t}_dba"] = worst_dba

            # Worst 63 Hz level (band index 1) over ALL selected receptors
            worst_63 = float(np.max(levels[:, 1]))
            cand_row[f"worst_{t}_63"] = worst_63

            # Keep only top receptors
            kept = order[: cfg["keep_per_type"]]

            # Distances and bearings for kept receptors
            k_rx = t_rx[kept]
            k_ry = t_ry[kept]
            k_att = att[kept]
            k_dba = dba[kept]
            k_dist = np.hypot(k_rx - cx, k_ry - cy)
            k_bearing = bearing_deg(cx, cy, k_rx, k_ry)

            for j, k_idx in enumerate(kept):
                pair_row = {
                    "candidate_id": int(i),
                    "receptor_type": t,
                    "rank": j + 1,
                    "receptor_id": str(t_rid[k_idx]),
                    "rx": float(k_rx[j]),
                    "ry": float(k_ry[j]),
                    "dist_m": float(k_dist[j]),
                    "bearing_deg": float(k_bearing[j]),
                }
                for b, bk in enumerate(BAND_KEYS):
                    pair_row[bk] = float(k_att[j, b])
                pair_row["ref_level_dba"] = float(k_dba[j])
                pairs.append(pair_row)

        candidates.append(cand_row)

    return candidates, pairs
