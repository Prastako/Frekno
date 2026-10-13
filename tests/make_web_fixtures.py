"""Write the website test fixtures: a synthetic FRK1 tile and what the site model must compute for it.

Run from the repo root: python tests/make_web_fixtures.py
Writes web/tests/fixtures/tile.bin.gz, index.json and expected.json. The reference model below
defines the site model (web/js/model.js):
- source at 1 m: preset classes from index.model.source_1m_db; custom = character shifted to the
  level in dB(A), spread back from its distance (20 log10 d + alpha * (d - 1) / 1000);
- slot level = A-weighted sum of (source - attenuation); layer level = loudest slot, at least the
  floor level (slot 0 level minus floor steps); spot margin = lowest (target - layer level) over
  the layers that are on; score = 6 + floor(margin / 2.5), limited to 1..10 (10 with no receptor);
- cardioid: facings 0, 15, ..., 345 degrees; bands in model.cardioid.bands_hz get the gain
  max(20 log10((1 + cos d) / 2), -rear_rejection_db), d = angle from the facing to the nearest
  point of the slot's 45 degree sector; the floor gets no gain; the facing with the highest
  margin wins (first one within 1e-9 dB).
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import pack  # noqa: E402

OUT = ROOT / "web" / "tests" / "fixtures"
FACINGS = [15.0 * j for j in range(24)]
SITES = [["CP-000001", "contract", "Rybník"], ["N2-000002", "evl", "Údolí"], ["NS-000003", "chko", "Křivoklátsko"]]
CASES = [
    {"rig": {"cls": "medium", "character": "very_bass_heavy"}, "cardioid": False, "layers": [1, 1, 1, 1, 1], "targets": [35] * 5},
    {"rig": {"cls": "large", "character": "balanced"}, "cardioid": True, "layers": [1, 1, 1, 1, 1], "targets": [45] * 5},
    {"rig": {"cls": "small", "character": "bass_heavy"}, "cardioid": True, "layers": [1, 0, 1, 0, 1], "targets": [35, 40, 45, 50, 27]},
    {"rig": {"cls": "custom", "character": "very_bass_heavy", "level": 103.0, "distance": 30.0}, "cardioid": False,
     "layers": [0, 1, 0, 0, 0], "targets": [27] * 5},
    {"rig": {"cls": "medium", "character": "very_bass_heavy"}, "cardioid": True, "layers": [1, 1, 1, 1, 1], "targets": [35] * 5},
]
FILTERS = [
    {"sites": [0, 1, 2], "minFlat": 0, "access": None, "excludeProt": 0, "forestLaw": False, "bbox": None},
    {"sites": [0, 2], "minFlat": 5000, "access": {"kind": "track", "max": 3000}, "excludeProt": 4, "forestLaw": True, "bbox": None},
    {"sites": [0, 1, 2], "minFlat": 0, "access": {"kind": "road", "max": 2500}, "excludeProt": 0, "forestLaw": False,
     "bbox": [14.2, 49.6, 14.8, 50.3]},
]


def make_records(n=14, seed=7):
    rng = np.random.default_rng(seed)
    rec = np.zeros(n, dtype=pack.SPOT)
    rec["lon"], rec["lat"] = 14.0 + rng.random(n), 49.5 + rng.random(n)
    rec["x"], rec["y"] = rng.integers(-800000, -500000, n), rng.integers(-1200000, -950000, n)
    rec["site"], rec["forest"], rec["slope"] = rng.integers(0, 3, n), rng.integers(0, 101, n), rng.integers(0, 256, n)
    rec["prot"], rec["flat"] = rng.integers(0, 128, n), rng.integers(0, 31701, n)
    for col in ("forest_m", "road_m", "track_m"):
        rec[col] = rng.integers(0, 5001, n)
    rec["sites"] = pack.NO_SITE
    rec["sites"][1, :2] = [2, 0]
    rec["sites"][4, :1] = [1]
    lay = rec["layers"]
    lay["floor"] = pack.NO_FLOOR
    shape = np.array([0, 0, 1, 2, 4, 8, 15, 35, 90], float)
    for i in range(n):
        for li in range(len(pack.LAYERS)):
            m = 0 if (i == 0 or (i + li) % 7 == 3) else int(rng.integers(1, pack.K + 1))
            secs = rng.permutation(pack.SECTORS)[:m]
            base = rng.uniform(72.0, 100.0)
            for k in range(m):
                att = base + 2.5 * k + shape + rng.uniform(-3.0, 3.0, 9)
                lay["r"]["att"][i, li, k] = np.clip(np.rint(att / pack.ATT_STEP_DB), 0, 255)
                lay["r"]["dist"][i, li, k] = rng.integers(150, 9000)
                lay["r"]["brg"][i, li, k] = secs[k] * 32 + rng.integers(0, 32)
            lay["n"][i, li] = m
            if m and rng.random() < 0.6:
                lay["floor"][i, li] = rng.integers(0, 40)
    return rec


def source_1m(model, rig):
    if rig["cls"] != "custom":
        return np.array(model["source_1m_db"][rig["cls"]][rig["character"]], float)
    shape = np.array(model["characters"][rig["character"]]["bands_db"], float)
    a, alpha, d = np.array(model["a_weighting_db"]), np.array(model["alpha_db_per_km"]), rig["distance"]
    shift = rig["level"] - 10 * math.log10(np.sum(10 ** ((shape + a) / 10)))
    return shape + shift + 20 * math.log10(d) + alpha * (d - 1) / 1000


def angdist(u, v):
    return abs((u - v + 180.0) % 360.0 - 180.0)


def gain_db(facing, sector, rear):
    a0, a1 = 45.0 * sector, 45.0 * sector + 45.0
    d = 0.0 if a0 <= facing <= a1 else min(angdist(facing, a0), angdist(facing, a1))
    g = (1 + math.cos(math.radians(d))) / 2
    return max(20 * math.log10(g), -rear) if g > 1e-12 else -rear


def evaluate(r, index, src, case):
    m = index["model"]
    a = np.array(m["a_weighting_db"])
    sub = np.isin(index["bands_hz"], m["cardioid"]["bands_hz"])
    rear = m["cardioid"]["rear_rejection_db"]
    best = None
    for f in (FACINGS if case["cardioid"] else [None]):
        margin, level, layer = math.inf, -math.inf, -1
        for li in range(len(pack.LAYERS)):
            n, floor = int(r["layers"]["n"][li]), int(r["layers"]["floor"][li])
            if not case["layers"][li] or n == 0:
                continue
            lev = -math.inf
            for k in range(n):
                e = 10 ** ((src - r["layers"]["r"]["att"][li, k] * pack.ATT_STEP_DB + a) / 10)
                if f is not None:
                    e = np.where(sub, e * 10 ** (gain_db(f, int(r["layers"]["r"]["brg"][li, k]) >> 5, rear) / 10), e)
                lev = max(lev, 10 * math.log10(e.sum()))
            if floor != pack.NO_FLOOR:
                e0 = 10 ** ((src - r["layers"]["r"]["att"][li, 0] * pack.ATT_STEP_DB + a) / 10)
                lev = max(lev, 10 * math.log10(e0.sum()) - floor * pack.FLOOR_STEP_DB)
            if case["targets"][li] - lev < margin:
                margin, level, layer = case["targets"][li] - lev, lev, li
        if best is None or margin > best[0] + 1e-9:
            best = (margin, level, layer, f)
    margin, level, layer, f = best
    if layer < 0:
        f = None
    sc = 10 if math.isinf(margin) else min(10, max(1, 6 + math.floor(margin / 2.5)))
    fin = math.isfinite(margin)
    return {"margin": margin if fin else None, "level": level if fin else None, "layer": layer, "facing": f, "score": sc}


def passes(r, flt):
    if int(r["site"]) not in flt["sites"] or int(r["flat"]) < flt["minFlat"]:
        return False
    if flt["access"] and int(r["track_m" if flt["access"]["kind"] == "track" else "road_m"]) > flt["access"]["max"]:
        return False
    if int(r["prot"]) & flt["excludeProt"] or (flt["forestLaw"] and int(r["forest_m"]) <= 50):
        return False
    b = flt["bbox"]
    return b is None or (b[0] <= float(r["lon"]) <= b[2] and b[1] <= float(r["lat"]) <= b[3])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rec = make_records()
    size = pack.write_tile(rec, OUT / "tile.bin.gz")
    index = {"format": "FRK1", "version": pack.VERSION, "layers": list(pack.LAYERS), "bands_hz": pack.BANDS_HZ, "k": pack.K,
             "sectors": pack.SECTORS, "att_step_db": pack.ATT_STEP_DB, "floor_step_db": pack.FLOOR_STEP_DB,
             "max_sites": pack.MAX_SITES, "site_codes": pack.SITE_CODES, "protected_bits": pack.PROTECTED_BITS,
             "protected_file": "protected.json", "model": pack.model_block(),
             "tiles": [{"id": "fixture", "file": "tile.bin.gz", "spots": len(rec), "bytes": size, "bbox": [14, 49.5, 15, 50.5]}]}
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    (OUT / "protected.json").write_text(json.dumps({"bits": pack.PROTECTED_BITS, "sites": SITES}, ensure_ascii=False), encoding="utf-8", newline="\n")
    spots = []
    for r in rec:
        spots.append({"lon": float(r["lon"]), "lat": float(r["lat"]), "x": int(r["x"]), "y": int(r["y"]), "site": int(r["site"]),
                      "forest": int(r["forest"]), "slope": int(r["slope"]), "prot": int(r["prot"]), "flat": int(r["flat"]),
                      "forestM": int(r["forest_m"]), "roadM": int(r["road_m"]), "trackM": int(r["track_m"]),
                      "sites": [int(v) for v in r["sites"] if v != pack.NO_SITE],
                      "n": [int(v) for v in r["layers"]["n"]], "floor": [int(v) for v in r["layers"]["floor"]],
                      "att00": [int(v) for v in r["layers"]["r"]["att"][1, 0]], "dist00": int(r["layers"]["r"]["dist"][1, 0]),
                      "brg00": int(r["layers"]["r"]["brg"][1, 0])})
    cases = []
    for case in CASES:
        src = source_1m(index["model"], case["rig"])
        res = [evaluate(r, index, src, case) for r in rec]
        order = sorted(range(len(rec)), key=lambda i: (-(res[i]["margin"] if res[i]["margin"] is not None else math.inf), i))
        reverse = {c: evaluate(rec[3], index, source_1m(index["model"], {**case["rig"], "cls": c}), case)["margin"]
                   for c in ("small", "medium", "large")}
        cases.append({**case, "source": [float(v) for v in src], "results": res, "order": order, "reverse_spot3": reverse})
    filters = [{**f, "pass": [i for i, r in enumerate(rec) if passes(r, f)]} for f in FILTERS]
    (OUT / "expected.json").write_text(json.dumps({"spots": spots, "cases": cases, "filters": filters}, indent=1), encoding="utf-8", newline="\n")
    print(f"wrote {len(rec)} spots, {len(cases)} cases, {len(filters)} filters to {OUT}")


if __name__ == "__main__":
    main()
