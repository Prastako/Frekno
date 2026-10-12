"""Tests for pipeline.nm_run — step lists and run with tiny Python commands."""

import sys
from pathlib import Path

import pytest

from pipeline import nm_run


class TestScriptRunner:
    def test_parent_is_bin(self, tmp_path: Path):
        assert nm_run.script_runner(tmp_path).parent == tmp_path / "bin"


class TestBuildSteps:
    def _inputs(self, tmp_path: Path) -> dict:
        return {
            key: tmp_path / (key + ".x")
            for key in ("dem", "ground", "buildings", "sources", "receivers", "result_csv")
        }

    def _params(self) -> dict:
        return {
            "max_distance_m": 11000,
            "humidity_percent": 70.0,
            "temperature_c": 10.0,
            "favourable": 1,
            "threads": 2,
        }

    def test_names(self, tmp_path: Path):
        steps = nm_run.build_steps(
            tmp_path / "nm", tmp_path / "ws", self._inputs(tmp_path), self._params()
        )
        names = [s[0] for s in steps]
        assert names == [
            "import_dem",
            "import_ground",
            "import_buildings",
            "import_sources",
            "import_receivers",
            "propagate",
            "export",
        ]

    def test_cwd(self, tmp_path: Path):
        steps = nm_run.build_steps(
            tmp_path / "nm", tmp_path / "ws", self._inputs(tmp_path), self._params()
        )
        expected_cwd = str(tmp_path / "nm")
        for step in steps:
            assert step[2] == expected_cwd

    def test_propagate_favourable(self, tmp_path: Path):
        steps = nm_run.build_steps(
            tmp_path / "nm", tmp_path / "ws", self._inputs(tmp_path), self._params()
        )
        propagate_argv = steps[5][1]
        idx = propagate_argv.index("--confFavourableOccurrencesDefault")
        assert propagate_argv[idx + 1] == "1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1"

    def test_propagate_max_src_dist(self, tmp_path: Path):
        steps = nm_run.build_steps(
            tmp_path / "nm", tmp_path / "ws", self._inputs(tmp_path), self._params()
        )
        propagate_argv = steps[5][1]
        idx = propagate_argv.index("--confMaxSrcDist")
        assert propagate_argv[idx + 1] == "11000"

    def test_propagate_table_dem(self, tmp_path: Path):
        steps = nm_run.build_steps(
            tmp_path / "nm", tmp_path / "ws", self._inputs(tmp_path), self._params()
        )
        propagate_argv = steps[5][1]
        idx = propagate_argv.index("--tableDEM")
        assert propagate_argv[idx + 1] == "DEM"

    def test_import_buildings_table(self, tmp_path: Path):
        steps = nm_run.build_steps(
            tmp_path / "nm", tmp_path / "ws", self._inputs(tmp_path), self._params()
        )
        buildings_argv = steps[2][1]
        idx = buildings_argv.index("--tableName")
        assert buildings_argv[idx + 1] == "BUILDINGS"


class TestRunSteps:
    def test_stops_on_first_failure(self, tmp_path: Path):
        metrics_csv = tmp_path / "m.csv"
        steps = [
            ("a", [sys.executable, "-c", "pass"], str(tmp_path)),
            ("b", [sys.executable, "-c", "import sys; sys.exit(3)"], str(tmp_path)),
            ("c", [sys.executable, "-c", "pass"], str(tmp_path)),
        ]
        rows = nm_run.run_steps(
            steps, "java", metrics_csv, tmp_path, prefix="t_"
        )
        assert len(rows) == 2
        assert rows[0]["exit_code"] == 0
        assert rows[1]["exit_code"] == 3

        # Check CSV content
        import csv
        with open(metrics_csv, newline="") as f:
            reader = csv.DictReader(f)
            csv_steps = [row["step"] for row in reader]
        assert "t_a" in csv_steps
        assert "t_b" in csv_steps
        assert len(csv_steps) == 2

    def test_java_env_vars(self, tmp_path: Path):
        metrics_csv = tmp_path / "m.csv"
        check_code = (
            "import os, sys; "
            "sys.exit(0 if os.environ['JAVACMD'] == 'X' and "
            "os.environ['JAVA_OPTS'] == '-Xmx1g' else 5)"
        )
        steps = [
            ("check", [sys.executable, "-c", check_code], str(tmp_path)),
        ]
        rows = nm_run.run_steps(
            steps, "X", metrics_csv, tmp_path, java_opts="-Xmx1g"
        )
        assert rows[0]["exit_code"] == 0
