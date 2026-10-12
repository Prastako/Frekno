"""Tests for pipeline.spike_report."""

import json
from pathlib import Path

import pytest

from pipeline.spike_report import (
    compare_rows,
    compare_stats,
    dist_class,
    extrapolate,
    nm_run_rows,
    tile_report_rows,
    write_csv,
    write_report_tables,
)


class TestDistClass:
    def test_boundaries(self):
        assert dist_class(999.9) == "0-1000"
        assert dist_class(1000.0) == "1000-2000"
        assert dist_class(10000.0) == ">=10000"


class TestExtrapolate:
    def test_empty(self):
        result = extrapolate([], 1.0, 1, {"job_hours": 6})
        assert result == {"tiles_done": 0}

    def test_single_full_tile(self):
        rows = [
            {
                "tile_id": "a",
                "full": True,
                "region_km2": 400.0,
                "wall_s": 3600.0,
                "peak_rss_mb": 2048.0,
                "peak_disk_mb": 1024.0,
            }
        ]
        limits = {
            "job_hours": 6,
            "ram_gb": 16,
            "disk_gb": 14,
            "concurrent_jobs": 20,
            "jobs_per_run": 256,
        }
        result = extrapolate(rows, 78871.0, 247, limits)
        assert result["s_per_km2"] == pytest.approx(9.0, abs=1e-4)
        assert result["cz_wall_h"] == pytest.approx(197.1775, abs=1e-3)
        assert result["runs_needed"] == 1
        assert result["max_rss_gb"] == pytest.approx(2.0, abs=1e-4)
        assert result["fits_job_hours"] is True


class TestCompareStats:
    def test_groups(self):
        rows = [
            {
                "variant": "hard",
                "res_m": 25.0,
                "dist_m": 500.0,
                "s63": 0.0,
                "n63": -3.0,
                "s125": 0.0,
                "n125": 0.0,
                "s250": 0.0,
                "n250": 0.0,
                "s500": 0.0,
                "n500": 0.0,
                "s1k": 0.0,
                "n1k": 0.0,
                "s2k": 0.0,
                "n2k": 0.0,
                "s4k": 0.0,
                "n4k": 0.0,
                "s8k": 0.0,
                "n8k": 0.0,
            },
            {
                "variant": "hard",
                "res_m": 25.0,
                "dist_m": 1500.0,
                "s63": 0.0,
                "n63": -6.0,
                "s125": 0.0,
                "n125": 0.0,
                "s250": 0.0,
                "n250": 0.0,
                "s500": 0.0,
                "n500": 0.0,
                "s1k": 0.0,
                "n1k": 0.0,
                "s2k": 0.0,
                "n2k": 0.0,
                "s4k": 0.0,
                "n4k": 0.0,
                "s8k": 0.0,
                "n8k": 0.0,
            },
            {
                "variant": "hard",
                "res_m": 25.0,
                "dist_m": 3000.0,
                "s63": 0.0,
                "n63": -9.0,
                "s125": 0.0,
                "n125": 0.0,
                "s250": 0.0,
                "n250": 0.0,
                "s500": 0.0,
                "n500": 0.0,
                "s1k": 0.0,
                "n1k": 0.0,
                "s2k": 0.0,
                "n2k": 0.0,
                "s4k": 0.0,
                "n4k": 0.0,
                "s8k": 0.0,
                "n8k": 0.0,
            },
        ]
        stats = compare_stats(rows)

        # Group (hard, 25.0, "63", "all"): n=3, mean=-6.0, p50=-6.0
        all_63 = [s for s in stats if s["variant"] == "hard" and s["band"] == "63" and s["dist_class"] == "all"][0]
        assert all_63["n"] == 3
        assert all_63["mean"] == pytest.approx(-6.0, abs=1e-4)
        assert all_63["p50"] == pytest.approx(-6.0, abs=1e-4)

        # Group (hard, 25.0, "63", "0-1000"): n=1, mean=-3.0
        lo_63 = [s for s in stats if s["variant"] == "hard" and s["band"] == "63" and s["dist_class"] == "0-1000"][0]
        assert lo_63["n"] == 1
        assert lo_63["mean"] == pytest.approx(-3.0, abs=1e-4)


class TestWriteReportTables:
    def test_one_tile_no_nm(self, tmp_path: Path):
        # tiles.csv
        (tmp_path / "region").mkdir()
        write_csv(
            [{"tile_id": "t1", "ix": "0", "iy": "0", "xmin": "0.0", "ymin": "0.0", "xmax": "20000.0", "ymax": "20000.0", "region_km2": "400.0", "full": "true"}],
            ["tile_id", "ix", "iy", "xmin", "ymin", "xmax", "ymax", "region_km2", "full"],
            tmp_path / "region" / "tiles.csv",
        )
        # summary.json
        (tmp_path / "tiles" / "t1").mkdir(parents=True)
        (tmp_path / "tiles" / "t1" / "summary.json").write_text(
            json.dumps({
                "grid": 100,
                "kept": 50,
                "receptors_home": 30,
                "receptors_cottage": 10,
                "dem_min": 200.0,
                "dem_max": 350.0,
                "dem_std": 25.0,
                "dem_s": 1.0,
                "landcover_s": 0.5,
                "candidates_s": 2.0,
                "screening_s": 10.0,
            })
        )
        # metrics_all.csv
        write_csv(
            [
                {
                    "step": "screen_t1",
                    "wall_s": "120.0",
                    "peak_rss_mb": "512.0",
                    "peak_disk_mb": "2048.0",
                }
            ],
            ["step", "wall_s", "peak_rss_mb", "peak_disk_mb"],
            tmp_path / "metrics_all.csv",
        )

        result = write_report_tables(tmp_path, 78871.0, 247, {
            "job_hours": 6,
            "ram_gb": 16,
            "disk_gb": 14,
            "concurrent_jobs": 20,
            "jobs_per_run": 256,
        })

        assert result["tiles"] == 1
        assert result["compare_groups"] == 0
        assert result["nm_runs"] == 0

        report = tmp_path / "report"
        assert (report / "tiles.csv").exists()
        assert (report / "extrapolation.json").exists()
        assert (report / "compare_stats.csv").exists()
        assert (report / "nm_runs.csv").exists()
