"""Select receptors around a candidate spot for acoustic evaluation."""

import numpy as np

TYPES = ("home", "cottage")


def bearing_deg(cx, cy, rx, ry):
    """Return direction from candidate to each receptor in degrees clockwise from north."""
    return np.degrees(np.arctan2(rx - cx, ry - cy)) % 360


def select_receptors(cx, cy, rx, ry, rtype, radius_m, sector_deg, rings_m):
    """Pick one nearest receptor per type per (sector, ring) bin.

    Parameters
    ----------
    cx, cy : float
        Candidate spot coordinates (S-JTSK metres).
    rx, ry : array-like
        Receptor coordinates.
    rtype : array-like of str
        Receptor type labels (e.g. "home", "cottage").
    radius_m : float
        Maximum evaluation radius.
    sector_deg : float
        Azimuth sector width in degrees (must divide 360 without remainder).
    rings_m : sequence of float
        Ring boundaries starting at 0, strictly increasing, ending at radius_m.

    Returns
    -------
    dict[str, np.ndarray]
        Maps each type in TYPES to a sorted array of selected receptor indices.
    """
    rings_m = np.asarray(rings_m)

    # --- validation ---
    if rings_m[0] != 0:
        raise ValueError("rings_m must start at 0")
    if not np.all(np.diff(rings_m) > 0):
        raise ValueError("rings_m must be strictly increasing")
    if rings_m[-1] != radius_m:
        raise ValueError("last element of rings_m must equal radius_m")
    if sector_deg <= 0 or 360 % sector_deg != 0:
        raise ValueError("sector_deg must be positive and divide 360")

    nsectors = int(360 / sector_deg)
    nrings = len(rings_m) - 1

    rx = np.asarray(rx, dtype=float)
    ry = np.asarray(ry, dtype=float)
    rtype = np.asarray(rtype)

    # distances from candidate to each receptor
    distances = np.hypot(rx - cx, ry - cy)

    # within-radius mask
    within = distances <= radius_m

    # bearing (degrees clockwise from north) for included receptors
    brng = bearing_deg(cx, cy, rx, ry)

    # sector indices: floor(bearing / sector_deg)
    sectors = (brng / sector_deg).astype(int)

    # ring indices: i such that rings_m[i] <= distance < rings_m[i+1]
    # distance == last edge belongs to the last ring
    rings = np.searchsorted(rings_m, distances, side="right") - 1

    # flat bin = sector * nrings + ring
    bins = sectors * nrings + rings
    max_bins = nsectors * nrings

    # per-type selected indices (one per type per bin, nearest wins, ties: smaller index)
    selected = {}
    for t in TYPES:
        mask = within & (rtype == t)
        idx = np.flatnonzero(mask)
        if idx.size == 0:
            selected[t] = np.array([], dtype=int)
            continue

        dist = distances[idx]
        b = bins[idx]

        # initialise: -1 means no receptor placed in this bin
        best = np.full(max_bins, -1, dtype=int)
        best_dist = np.full(max_bins, np.inf)

        # vectorised placement: scan positions 0..len(idx)-1 so argmin prefers smaller array index
        for i in range(len(idx)):
            bi = b[i]
            if bi < max_bins and dist[i] < best_dist[bi]:
                best[bi] = i
                best_dist[bi] = dist[i]

        # collect placed indices
        placed = best[best >= 0]
        indices = idx[placed]

        # sort by distance (ties: smaller original index)
        order = np.lexsort((indices, distances[indices]))
        selected[t] = indices[order]

    return selected
