"""Select receptors around a candidate spot for acoustic evaluation."""

import numpy as np

TYPES = ("home", "cottage", "campsite", "care", "recreation")


def bearing_deg(cx, cy, rx, ry):
    """Return direction from candidate to each receptor in degrees clockwise from north."""
    return np.degrees(np.arctan2(rx - cx, ry - cy)) % 360


def select_receptors(cx, cy, rx, ry, rtype, radius_m, sector_deg, rings_m, per_bin=1):
    """Pick the per_bin nearest receptors per type per (sector, ring) bin.

    Parameters
    ----------
    cx, cy : float
        Candidate spot coordinates (S-JTSK metres).
    rx, ry : array-like
        Receptor coordinates.
    rtype : array-like of str
        Receptor type labels (values of TYPES).
    radius_m : float
        Maximum evaluation radius.
    sector_deg : float
        Azimuth sector width in degrees (must divide 360 without remainder).
    rings_m : sequence of float
        Ring boundaries starting at 0, strictly increasing, ending at radius_m.
    per_bin : int
        Receptors kept per type and bin, nearest first (ties: smaller index).

    Returns
    -------
    dict[str, np.ndarray]
        Maps each type in TYPES to an array of selected receptor indices,
        sorted by distance (ties: smaller index).
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
    if int(per_bin) != per_bin or per_bin < 1:
        raise ValueError("per_bin must be a whole number of at least 1")

    nsectors = int(360 / sector_deg)
    nrings = len(rings_m) - 1

    rx = np.asarray(rx, dtype=float)
    ry = np.asarray(ry, dtype=float)
    rtype = np.asarray(rtype)

    distances = np.hypot(rx - cx, ry - cy)
    sectors = (bearing_deg(cx, cy, rx, ry) / sector_deg).astype(int)
    rings = np.searchsorted(rings_m, distances, side="right") - 1
    bins = sectors * nrings + rings
    usable = (distances <= radius_m) & (bins < nsectors * nrings)

    selected = {}
    for t in TYPES:
        idx = np.flatnonzero(usable & (rtype == t))
        # order by bin, then distance, then index; keep the first per_bin of each bin
        order = idx[np.lexsort((idx, distances[idx], bins[idx]))]
        b = bins[order]
        start = np.flatnonzero(np.r_[True, b[1:] != b[:-1]])
        rank = np.arange(b.size) - np.repeat(start, np.diff(np.r_[start, b.size]))
        chosen = order[rank < per_bin]
        selected[t] = chosen[np.lexsort((chosen, distances[chosen]))]

    return selected
