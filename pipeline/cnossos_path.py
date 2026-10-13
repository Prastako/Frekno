"""CNOSSOS-EU favourable-condition boundary attenuation (ground + terrain diffraction) for screening profiles."""
import numpy as np

from pipeline.cnossos import (GAMMA_MIN, aground_f, arc, circle_center, dif_db, g_prime, heights,
                              mean_plane, mean_plane_split, mirror)


def _dground(a_side, d_img, dd):
    arg = 1 + (10 ** (-a_side / 20) - 1) * 10 ** (-(d_img - dd) / 20)
    return -20 * np.log10(np.maximum(arg, 1e-6))


def boundary_f(t, z, g, d, zg_s, zg_r, h_s, h_r, g_s, g_r, freqs_hz, ground_credit=True):
    t = np.asarray(t, float); z = np.asarray(z, float); g = np.asarray(g, float)
    P = t.shape[0]
    d = np.broadcast_to(np.asarray(d, float), (P,))
    zg_s = np.broadcast_to(np.asarray(zg_s, float), (P,))
    zg_r = np.broadcast_to(np.asarray(zg_r, float), (P,))
    hs = np.broadcast_to(np.asarray(h_s, float), (P,)); hr = np.broadcast_to(np.asarray(h_r, float), (P,))
    gs = np.broadcast_to(np.asarray(g_s, float), (P,)); gr = np.broadcast_to(np.asarray(g_r, float), (P,))
    T = np.concatenate([np.zeros((P, 1)), t, d[:, None]], axis=1)
    Z = np.concatenate([zg_s[:, None], z, zg_r[:, None]], axis=1)
    G = np.concatenate([gs[:, None], g, gr[:, None]], axis=1)
    W = np.isfinite(Z).astype(float)
    Z = np.where(W > 0, Z, 0.0)
    sz, rz = zg_s + hs, zg_r + hr
    zero = np.zeros(P)
    dsr = np.hypot(d, rz - sz)
    gam = np.maximum(GAMMA_MIN, 8 * dsr)
    # whole path
    a, b = mean_plane(T, Z, W)
    hS, hR, dp = heights(a, b, zero, sz, d, rz)
    gp = (W * G).sum(axis=1) / np.maximum(W.sum(axis=1), 1)
    a_ground = aground_f(hS, hR, dp, gp, g_prime(gp, gs, hS, hR, dp), freqs_hz)
    # blocking by the curved ray
    ct, cz = circle_center(zero, sz, d, rz, gam)
    Ti, Zi, Wi = T[:, 1:-1], Z[:, 1:-1], W[:, 1:-1]
    blk = (Wi > 0) & (np.hypot(Ti - ct[:, None], Zi - cz[:, None]) > gam[:, None])
    blocked = blk.any(axis=1)
    with np.errstate(all="ignore"):
        di = (arc(np.hypot(Ti, Zi - sz[:, None]), gam[:, None])
              + arc(np.hypot(d[:, None] - Ti, rz[:, None] - Zi), gam[:, None])
              - arc(dsr, gam)[:, None])
        rows = np.arange(P)
        k = np.argmax(np.where(blk, di, -np.inf), axis=1) + 1  # column in T, Z
        ot, oz = T[rows, k], Z[rows, k]
        dd = dif_db(np.where(blocked, di[rows, k - 1], 0.0), freqs_hz)
        (a1, b1), (a2, b2) = mean_plane_split(T, Z, W, k)
        cw, cg = np.cumsum(W, axis=1), np.cumsum(W * G, axis=1)
        # source side
        hS1, hO1, dp1 = heights(a1, b1, zero, sz, ot, oz)
        g1 = cg[rows, k] / np.maximum(cw[rows, k], 1)
        A1 = aground_f(hS1, hO1, dp1, g1, g_prime(g1, gs, hS1, hO1, dp1), freqs_hz)
        st, sz_i = mirror(a1, b1, zero, sz)
        d1 = dif_db(arc(np.hypot(ot - st, oz - sz_i), gam) + arc(np.hypot(d - ot, rz - oz), gam)
                    - arc(np.hypot(d - st, rz - sz_i), gam), freqs_hz)
        dg1 = _dground(A1, d1, dd)
        # receptor side
        hO2, hR2, dp2 = heights(a2, b2, ot, oz, d, rz)
        n2 = cw[:, -1] - cw[rows, k] + W[rows, k]
        g2 = (cg[:, -1] - cg[rows, k] + (W * G)[rows, k]) / np.maximum(n2, 1)
        A2 = aground_f(hO2, hR2, dp2, g2, g2, freqs_hz)
        rt, rz_i = mirror(a2, b2, d, rz)
        d2 = dif_db(arc(np.hypot(ot, oz - sz), gam) + arc(np.hypot(rt - ot, rz_i - oz), gam)
                    - arc(np.hypot(rt, rz_i - sz), gam), freqs_hz)
        dg2 = _dground(A2, d2, dd)
    if not ground_credit:
        a_ground = np.minimum(a_ground, 0.0)
        dg1 = np.minimum(dg1, 0.0)
        dg2 = np.minimum(dg2, 0.0)
    A = np.where(blocked[:, None], dd + dg1 + dg2, a_ground)
    return A, blocked, a_ground
