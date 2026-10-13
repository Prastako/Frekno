"""Tests for pipeline.pack."""

import numpy as np
import pandas as pd
import pytest

from pipeline import pack


class TestSPOTSize:
    def test_itemsize(self):
        assert pack.SPOT.itemsize == 315


class TestPackRecords:
    @pytest.fixture
    def cands(self):
        return pd.DataFrame({
            "candidate_id": [0, 1],
            "x": [-740000.0, -740250.0],
            "y": [-1050000.0, -1050000.0],
            "site_type": ["open", "forest"],
            "forest_frac": [0.0, 0.5],
        })

    @pytest.fixture
    def pairs(self, cands):
        rows = []
        # Spot 0: seven "home" rows (ranks 1 to 7)
        for rank in range(1, 8):
            rows.append({
                "candidate_id": 0,
                "receptor_type": "home",
                "rank": rank,
                "receptor_id": f"h{rank}",
                "rx": -740100.0 + rank * 10,
                "ry": -1050100.0 + rank * 10,
                "dist_m": 100.0 + rank * 10,
                "bearing_deg": 45.0 + rank * 5,
                "ref_level_dba": 55.0 - rank,
                "a31": 20.0 + rank, "a63": 22.0 + rank, "a125": 24.0 + rank,
                "a250": 26.0 + rank, "a500": 28.0 + rank, "a1k": 30.0 + rank,
                "a2k": 32.0 + rank, "a4k": 34.0 + rank, "a8k": 36.0 + rank,
            })
        # Spot 0: two "campsite" rows sharing the same area key
        for rank, rid in [(1, "zbg10_0"), (2, "zbg10_1")]:
            rows.append({
                "candidate_id": 0,
                "receptor_type": "campsite",
                "rank": rank,
                "receptor_id": rid,
                "rx": -739800.0,
                "ry": -1049800.0,
                "dist_m": 200.0,
                "bearing_deg": 30.0,
                "ref_level_dba": 50.0,
                "a31": 10.0, "a63": 12.0, "a125": 14.0,
                "a250": 16.0, "a500": 18.0, "a1k": 20.0,
                "a2k": 22.0, "a4k": 24.0, "a8k": 26.0,
            })
        return pd.DataFrame(rows)

    def test_spot0_home_count(self, cands, pairs):
        rec = pack.pack_records(cands, pairs)
        # Spot 0 has 7 home rows, K=5 limit -> 5
        assert rec[0]["layers"]["n"][0] == 5  # home layer index 0

    def test_spot0_campsite_count(self, cands, pairs):
        rec = pack.pack_records(cands, pairs)
        # zbg10_0 and zbg10_1 share area_key "zbg10", deduplicated -> 1
        assert rec[0]["layers"]["n"][2] == 1  # campsite layer index 2

    def test_spot1_no_receptors(self, cands, pairs):
        rec = pack.pack_records(cands, pairs)
        # Spot 1 has no pairs at all
        for li in range(len(pack.LAYERS)):
            assert rec[1]["layers"]["n"][li] == 0


class TestWriteRead:
    @pytest.fixture
    def records(self):
        return pd.DataFrame({
            "candidate_id": [0, 1],
            "x": [-740000.0, -740250.0],
            "y": [-1050000.0, -1050000.0],
            "site_type": ["open", "forest"],
            "forest_frac": [0.0, 0.5],
        })

    @pytest.fixture
    def pairs(self):
        rows = []
        for rank in range(1, 6):
            rows.append({
                "candidate_id": 0,
                "receptor_type": "home",
                "rank": rank,
                "receptor_id": f"h{rank}",
                "rx": -740100.0,
                "ry": -1050100.0,
                "dist_m": 100.0,
                "bearing_deg": 45.0,
                "ref_level_dba": 55.0,
                "a31": 20.0, "a63": 22.0, "a125": 24.0,
                "a250": 26.0, "a500": 28.0, "a1k": 30.0,
                "a2k": 32.0, "a4k": 34.0, "a8k": 36.0,
            })
        return pd.DataFrame(rows)

    def test_roundtrip(self, records, pairs, tmp_path):
        rec = pack.pack_records(records, pairs)
        tile_path = tmp_path / "test.bin"
        size = pack.write_tile(rec, tile_path)
        assert size > 0
        head, rec2 = pack.read_tile(tile_path)
        assert head["spots"] == 2
        assert head["magic"] == "FRK1"
        assert len(rec2) == len(rec)
        assert rec2["lon"][0] == rec["lon"][0]
        assert rec2["lon"][1] == rec["lon"][1]
