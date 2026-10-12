"""Tests for pipeline.metrics."""

import csv
import sys
from pathlib import Path

import pytest

from pipeline.metrics import CSV_COLUMNS, run_step


class TestMemory:
    """peak_rss_mb tracking."""

    def test_peak_rss(self, tmp_path: Path):
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        csv_path = tmp_path / "metrics.csv"

        cmd = [
            sys.executable,
            "-c",
            'x = b"x" * (150 * 1048576); import time; time.sleep(1)',
        ]
        result = run_step("mem_test", cmd, watch_dir, csv_path)

        assert result["peak_rss_mb"] >= 120
        assert result["exit_code"] == 0
        assert result["timed_out"] is False


class TestDisk:
    """peak_disk_mb tracking."""

    def test_peak_disk(self, tmp_path: Path):
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        csv_path = tmp_path / "metrics.csv"

        cmd = [
            sys.executable,
            "-c",
            f"""
import time, os
fp = r"{watch_dir / 'data.bin'}"
with open(fp, "wb") as f:
    f.write(b"\\x00" * (20 * 1048576))
time.sleep(1)
os.remove(fp)
time.sleep(0.5)
""",
        ]
        result = run_step("disk_test", cmd, watch_dir, csv_path)

        assert result["peak_disk_mb"] >= 15
        assert result["end_disk_mb"] < 1


class TestExitCode:
    """Non-zero exit code capture."""

    def test_exit_3(self, tmp_path: Path):
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        csv_path = tmp_path / "metrics.csv"

        cmd = [sys.executable, "-c", "import sys; sys.exit(3)"]
        result = run_step("exit3", cmd, watch_dir, csv_path)

        assert result["exit_code"] == 3


class TestMissingProgram:
    """OSError on launch returns exit_code -1 without raising."""

    def test_no_such_program(self, tmp_path: Path):
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        csv_path = tmp_path / "metrics.csv"

        cmd = ["no-such-program-frekno"]
        result = run_step("missing", cmd, watch_dir, csv_path)

        assert result["exit_code"] == -1
        assert csv_path.exists()


class TestTimeout:
    """Process killed after timeout."""

    def test_kills_on_timeout(self, tmp_path: Path):
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        csv_path = tmp_path / "metrics.csv"

        cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
        result = run_step("slow", cmd, watch_dir, csv_path, timeout_s=1)

        assert result["timed_out"] is True
        assert result["exit_code"] == -2
        assert result["wall_s"] < 10


class TestCSVAppend:
    """Two calls append rows; first line is the header."""

    def test_two_calls_three_lines(self, tmp_path: Path):
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        csv_path = tmp_path / "metrics.csv"

        cmd = [sys.executable, "-c", "pass"]
        run_step("first", cmd, watch_dir, csv_path)
        run_step("second", cmd, watch_dir, csv_path)

        with open(csv_path, encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == 3
        assert lines[0].strip() == ",".join(CSV_COLUMNS)


def test_str_paths(tmp_path: Path):
    from pipeline.metrics import folder_size_bytes

    w = tmp_path / "w"
    w.mkdir()
    (w / "file.dat").write_bytes(b"\x00" * 2048)

    assert folder_size_bytes(str(w)) == 2048

    result = run_step(
        "str",
        [sys.executable, "-c", "pass"],
        str(tmp_path / "w"),
        str(tmp_path / "s.csv"),
    )
    assert result["exit_code"] == 0
    assert (tmp_path / "s.csv").exists()
