"""Tests for pipeline.pack (tile format FRK1 version 2)."""

import gzip
import json

import numpy as np
import pandas as pd
import pytest

from pipeline import pack

SITE_IDS = np.array(["CP-000001", "N2-000002", "NS-000003"])


def make_tile(true_brgs, levels, list_len=None):
    """One spot at a fixed point; one home receptor per (true bearing, ref level)."""
    cands = pd.DataFrame({"candidate_id": [7], "x": [-740000.0], "y": [-1050000.0],
                          "site_type": ["clearing"], "forest_frac": [0.4]})
    north = pack.grid_north(cands["x"], cands["y"])[2][0]
    rows = []
    for rank, (brg, lev) in enumerate(zip(true_brgs, levels), start=1):
        att = {k: 40.0 + rank for k in pack.BAND_KEYS}
        rows.append({"candidate_id": 7, "receptor_type": "home", "rank": rank, "receptor_id": f"r{rank}",
                     "dist_m": 1000.0 + rank, "bearing_deg": (brg - north) % 360.0, **att, "ref_level_dba": lev})
    details = pd.DataFrame({"candidate_id": [7], "slope_pct": [3.4], "flat_m2": [12300], "forest_m": [0.0],
                            "road_m": [512.0], "track_m": [97.0], "prot": [18], "prot_sites": ["N2-000002;NS-000003"]})
    return cands, pd.DataFrame(rows), details


def test_record_size():
    assert pack.SPOT.itemsize == 406


def test_details_and_position():
    cands, pairs, details = make_tile([20.0], [50.0])
    rec = pack.pack_records(cands, pairs, details, SITE_IDS)
    assert rec["x"][0] == -740000 and rec["y"][0] == -1050000
    assert (rec["site"][0], rec["forest"][0], rec["slope"][0], rec["prot"][0]) == (1, 40, 3, 18)
    assert (rec["flat"][0], rec["forest_m"][0], rec["road_m"][0], rec["track_m"][0]) == (12300, 0, 512, 97)
    assert list(rec["sites"][0]) == [1, 2, pack.NO_SITE, pack.NO_SITE]


def test_one_slot_per_sector_loudest_first():
    cands, pairs, details = make_tile([20.0, 25.0, 110.0, 200.0], [60.0, 59.0, 55.0, 50.0])
    rec = pack.pack_records(cands, pairs, details, SITE_IDS)
    home = rec["layers"][0, 0]
    assert home["n"] == 3
    assert list(home["r"]["dist"][:3]) == [1001, 1003, 1004]
    assert list(home["r"]["brg"][:3] >> 5) == [0, 2, 4]
    assert home["r"]["att"][0][0] == 82  # 41 dB in 0.5 dB steps
    assert home["floor"] == pack.NO_FLOOR


def test_floor_when_list_full():
    cands, pairs, details = make_tile([20.0, 25.0], [60.0, 52.3])
    rec = pack.pack_records(cands, pairs, details, SITE_IDS, list_cap=2)
    assert rec["layers"][0, 0]["floor"] == 30  # (60.0 - 52.3) / 0.25 rounded down


def test_unknown_site_id_raises():
    cands, pairs, details = make_tile([20.0], [50.0])
    details["prot_sites"] = ["XX-999999"]
    with pytest.raises(ValueError):
        pack.pack_records(cands, pairs, details, SITE_IDS)


def test_pack_region(tmp_path):
    import geopandas as gpd
    from shapely.geometry import Point
    sites = gpd.GeoDataFrame({"site_id": ["NS-000003", "CP-000001", "N2-000002"], "category": ["chko", "contract", "evl"],
                              "name": ["C", "A", "B"]}, geometry=[Point(0, 0)] * 3, crs="EPSG:5514")
    gpkg = tmp_path / "protected.gpkg"
    sites.to_file(gpkg, layer="protected", driver="GPKG")
    cands, pairs, details = make_tile([20.0, 110.0], [60.0, 55.0])
    for t in ("home", "cottage", "campsite", "care", "recreation"):
        cands[f"worst_{t}_dba"] = 60.0 if t == "home" else np.nan
    tile = tmp_path / "screen" / "20k_-37_-53"
    tile.mkdir(parents=True)
    cands.to_csv(tile / "candidates.csv", index=False)
    pairs.to_csv(tile / "pairs.csv", index=False)
    details.to_csv(tile / "details.csv", index=False)
    out = pack.pack_region(tmp_path / "screen", tmp_path / "site", gpkg)
    assert out == {"tiles": 1, "spots": 1, "bytes": (tmp_path / "site" / "tiles" / "20k_-37_-53.bin.gz").stat().st_size}
    raw = (tmp_path / "site" / "tiles" / "20k_-37_-53.bin.gz").read_bytes()
    assert gzip.decompress(raw)[:4] == b"FRK1"
    head, rec = pack.read_tile(tmp_path / "site" / "tiles" / "20k_-37_-53.bin.gz")
    assert head["version"] == 2 and head["spots"] == 1 and rec["layers"][0, 0]["n"] == 2
    index = json.loads((tmp_path / "site" / "index.json").read_text(encoding="utf-8"))
    assert index["version"] == 2 and index["tiles"][0]["ref_min_dba"] == 60.0
    assert set(index["model"]["source_1m_db"]) == {"small", "medium", "large"}
    prot = json.loads((tmp_path / "site" / "protected.json").read_text(encoding="utf-8"))
    assert [s[0] for s in prot["sites"]] == ["CP-000001", "N2-000002", "NS-000003"]


def test_border_bit():
    cands, pairs, details = make_tile([20.0], [50.0])
    details["border"] = [1]
    rec = pack.pack_records(cands, pairs, details, SITE_IDS)
    assert rec["prot"][0] == 18 | pack.BORDER_BIT


def test_pack_tile_and_write_index(tmp_path):
    cands, pairs, details = make_tile([20.0, 110.0], [60.0, 55.0])
    for t in pack.LAYERS:
        cands[f"worst_{t}_dba"] = 60.0 if t == "home" else np.nan
    d = tmp_path / "scr" / "20k_-37_-53"
    d.mkdir(parents=True)
    cands.to_csv(d / "candidates.csv", index=False)
    pairs.to_csv(d / "pairs.csv", index=False)
    details.to_csv(d / "details.csv", index=False)
    meta = pack.pack_tile(d, tmp_path / "site", SITE_IDS)
    assert (meta["id"], meta["spots"], meta["ref_min_dba"]) == ("20k_-37_-53", 1, 60.0)
    sites = pd.DataFrame({"site_id": list(SITE_IDS), "category": ["contract", "evl", "chko"], "name": ["A", "B", "C"]})
    assert pack.write_index(tmp_path / "site", [meta], sites) == {"tiles": 1, "spots": 1, "bytes": meta["bytes"]}
    index = json.loads((tmp_path / "site" / "index.json").read_text(encoding="utf-8"))
    assert index["border_bit"] == 128 and index["tiles"] == [meta]
