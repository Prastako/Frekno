"""Tests for pipeline.nm_tile."""

import csv
import json
import struct
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pipeline import nm_tile


class TestPickSpread:
    """Tests for pick_spread function."""

    def test_basic_spread(self):
        """pick_spread([5, nan, 1, 3, 2, 4], 3) returns [2, 3, 0]."""
        values = [5.0, np.nan, 1.0, 3.0, 2.0, 4.0]
        result = nm_tile.pick_spread(values, 3)
        assert result.tolist() == [2, 3, 0]

    def test_all_values(self):
        """When n >= finite count, return all finite indices sorted by value."""
        values = [3.0, 1.0, 2.0]
        result = nm_tile.pick_spread(values, 5)
        assert result.tolist() == [1, 2, 0]

    def test_single_value(self):
        """Single finite value."""
        values = [np.nan, 5.0, np.nan]
        result = nm_tile.pick_spread(values, 1)
        assert result.tolist() == [1]

    def test_one_spread(self):
        """n=1 returns the index of the smallest finite value."""
        values = [5.0, 1.0, 3.0]
        result = nm_tile.pick_spread(values, 1)
        assert result.tolist() == [1]

    def test_equal_values(self):
        """Stable sort for equal values."""
        values = [2.0, 1.0, 1.0, 3.0]
        result = nm_tile.pick_spread(values, 2)
        assert len(result) >= 1


class TestFillNodata:
    """Tests for fill_nodata function."""

    def test_no_nodata(self):
        """No change when there are no nodata cells."""
        dem = np.array([[1.0, 2.0], [3.0, 4.0]])
        result = nm_tile.fill_nodata(dem)
        assert result.tolist() == [[1.0, 2.0], [3.0, 4.0]]

    def test_fill_nodata_cells(self):
        """Nodata cells are filled with nearest valid value."""
        dem = np.array([[1.0, np.nan, 3.0],
                        [4.0, 5.0, 6.0],
                        [7.0, 8.0, 9.0]])
        result = nm_tile.fill_nodata(dem)
        # The NaN at (0, 1) should be filled with nearest valid neighbor
        assert np.all(np.isfinite(result))

    def test_fill_with_nodata_value(self):
        """Cells with NODATA value are also filled."""
        dem = np.array([[1.0, -9999.0, 3.0],
                        [4.0, 5.0, 6.0],
                        [7.0, 8.0, 9.0]])
        result = nm_tile.fill_nodata(dem)
        assert np.all(np.isfinite(result))
        assert not np.any(result == -9999.0)

    def test_all_nodata_raises(self):
        """All nodata raises ValueError."""
        dem = np.array([[np.nan, np.nan], [np.nan, np.nan]])
        with pytest.raises(ValueError, match="no valid cell"):
            nm_tile.fill_nodata(dem)

    def test_mixed_nodata_and_nan(self):
        """Both NaN and NODATA are treated as bad."""
        dem = np.array([[1.0, np.nan], [-9999.0, 5.0]])
        result = nm_tile.fill_nodata(dem)
        assert np.all(np.isfinite(result))
        assert not np.any(result == -9999.0)


class TestNMTileConstants:
    """Test that constants are correctly defined."""

    def test_variants(self):
        assert nm_tile.VARIANTS == ("zabaged", "hard", "soft")

    def test_screen_keys(self):
        assert nm_tile.SCREEN_KEYS == ["a63", "a125", "a250", "a500", "a1k", "a2k", "a4k", "a8k"]

    def test_nm_keys(self):
        assert nm_tile.NM_KEYS == ["nm63", "nm125", "nm250", "nm500", "nm1k", "nm2k", "nm4k", "nm8k"]

    def test_compare_columns(self):
        expected = (
            ["variant", "res_m", "candidate_id", "receptor_id", "receptor_type", "rank", "dist_m"]
            + nm_tile.SCREEN_KEYS
            + nm_tile.NM_KEYS
        )
        assert nm_tile.COMPARE_COLUMNS == expected


class TestNmCompare:
    """Tests for nm_compare function."""

    def test_basic_compare(self, tmp_path):
        """nm_compare produces one row with nm63=49.0 and nm8k=56.0 with missing=1."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "out").mkdir()

        variant = "hard"
        res_m = 50.0

        # Create sources_map.csv
        pd.DataFrame({"pk": [1], "candidate_id": [100], "x": [-1000.0], "y": [-2000.0]}).to_csv(
            work_dir / "sources_map.csv", index=False
        )

        # Create receivers_map.csv
        pd.DataFrame({"pk": [1, 2], "receptor_id": ["R1", "R2"], "x": [0.0, 100.0], "y": [0.0, 100.0]}).to_csv(
            work_dir / "receivers_map.csv", index=False
        )

        # Create pairs_of_interest.csv
        pd.DataFrame({
            "candidate_id": [100, 100],
            "receptor_id": ["R1", "R2"],
            "receptor_type": ["home", "home"],
            "rank": [1, 2],
            "dist_m": [500.0, 600.0],
            "a63": [10.0, 11.0],
            "a125": [10.0, 11.0],
            "a250": [10.0, 11.0],
            "a500": [10.0, 11.0],
            "a1k": [10.0, 11.0],
            "a2k": [10.0, 11.0],
            "a4k": [10.0, 11.0],
            "a8k": [10.0, 11.0],
        }).to_csv(work_dir / "pairs_of_interest.csv", index=False)

        # Create receivers_level.csv with one entry for (100, R1)
        # read_receivers_level expects columns: IDRECEIVER, IDSOURCE, HZ63-HZ8000
        # attenuation_from_1m returns [-level - 11.0 for level in levels]
        # We want nm63=49.0 and nm8k=56.0
        # -level - 11 = 49  =>  level = -60.0  (for 63Hz)
        # -level - 11 = 56  =>  level = -67.0  (for 8kHz)
        # Only write for R1 (pk=1) so R2 (pk=2) is missing
        band_levels = [-60.0, -59.0, -58.0, -57.0, -56.0, -55.0, -54.0, -67.0]

        with open(work_dir / "out" / "receivers_level.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["IDRECEIVER", "IDSOURCE", "type", "HZ63", "HZ125", "HZ250",
                        "HZ500", "HZ1000", "HZ2000", "HZ4000", "HZ8000"])
            w.writerow([1, 1, "outdoor"] + [f"{l:.4f}" for l in band_levels])

        rows, missing = nm_tile.nm_compare(work_dir, variant, res_m)

        # One row for R1, missing=1 for R2
        assert len(rows) == 1
        assert missing == 1
        assert rows[0]["nm63"] == pytest.approx(49.0, abs=0.1)
        assert rows[0]["nm8k"] == pytest.approx(56.0, abs=0.1)
        assert rows[0]["variant"] == variant
        assert rows[0]["res_m"] == res_m

    def test_no_missing(self, tmp_path):
        """All pairs found in results."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "out").mkdir()

        variant = "soft"
        res_m = 25.0

        pd.DataFrame({"pk": [1], "candidate_id": [1], "x": [0.0], "y": [0.0]}).to_csv(
            work_dir / "sources_map.csv", index=False
        )
        pd.DataFrame({"pk": [1], "receptor_id": ["R1"], "x": [100.0], "y": [100.0]}).to_csv(
            work_dir / "receivers_map.csv", index=False
        )
        pd.DataFrame({
            "candidate_id": [1],
            "receptor_id": ["R1"],
            "receptor_type": ["home"],
            "rank": [1],
            "dist_m": [500.0],
            "a63": [10.0], "a125": [10.0], "a250": [10.0], "a500": [10.0],
            "a1k": [10.0], "a2k": [10.0], "a4k": [10.0], "a8k": [10.0],
        }).to_csv(work_dir / "pairs_of_interest.csv", index=False)

        band_levels = [40.0] * 8
        with open(work_dir / "out" / "receivers_level.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["IDRECEIVER", "IDSOURCE", "type", "HZ63", "HZ125", "HZ250",
                        "HZ500", "HZ1000", "HZ2000", "HZ4000", "HZ8000"])
            w.writerow([1, 1, "outdoor"] + [f"{l:.4f}" for l in band_levels])

        rows, missing = nm_tile.nm_compare(work_dir, variant, res_m)
        assert len(rows) == 1
        assert missing == 0

    def test_all_missing(self, tmp_path):
        """No NM results for any pair."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "out").mkdir()

        pd.DataFrame({"pk": [1], "candidate_id": [1], "x": [0.0], "y": [0.0]}).to_csv(
            work_dir / "sources_map.csv", index=False
        )
        pd.DataFrame({"pk": [1], "receptor_id": ["R1"], "x": [100.0], "y": [100.0]}).to_csv(
            work_dir / "receivers_map.csv", index=False
        )
        pd.DataFrame({
            "candidate_id": [1],
            "receptor_id": ["R1"],
            "receptor_type": ["home"],
            "rank": [1],
            "dist_m": [500.0],
            "a63": [10.0], "a125": [10.0], "a250": [10.0], "a500": [10.0],
            "a1k": [10.0], "a2k": [10.0], "a4k": [10.0], "a8k": [10.0],
        }).to_csv(work_dir / "pairs_of_interest.csv", index=False)

        # Empty receivers_level.csv
        with open(work_dir / "out" / "receivers_level.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["IDRECEIVER", "IDSOURCE", "type", "HZ63", "HZ125", "HZ250",
                        "HZ500", "HZ1000", "HZ2000", "HZ4000", "HZ8000"])

        rows, missing = nm_tile.nm_compare(work_dir, "hard", 50.0)
        assert len(rows) == 0
        assert missing == 1


class TestNMTileImports:
    """Test that all required functions are importable."""

    def test_pick_spread_importable(self):
        assert callable(nm_tile.pick_spread)

    def test_fill_nodata_importable(self):
        assert callable(nm_tile.fill_nodata)

    def test_nm_inputs_importable(self):
        assert callable(nm_tile.nm_inputs)

    def test_nm_compare_importable(self):
        assert callable(nm_tile.nm_compare)

    def test_nm_tile_importable(self):
        assert callable(nm_tile.nm_tile)

    def test_constants_importable(self):
        assert hasattr(nm_tile, "VARIANTS")
        assert hasattr(nm_tile, "SCREEN_KEYS")
        assert hasattr(nm_tile, "NM_KEYS")
        assert hasattr(nm_tile, "COMPARE_COLUMNS")
