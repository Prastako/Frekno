"""Tests for pipeline.run_spike."""

import csv
import json
from pathlib import Path

import pytest

from pipeline.metrics import CSV_COLUMNS
from pipeline.run_spike import (
    cli_cmd,
    main,
    merge_metrics,
    parse_nm_jobs,
    select_tiles,
)


# ── helpers ──

def _make_fake(rs):
    """Return (fake_fn, call_list) pair.

    The fake records every invocation as a dict and returns the row
    from *rs* matched by the ``step`` argument (falls back to the
    first entry in *rs*).
    """
    calls = []

    def fake(step, cmd, watch_dir, csv_path, *, cwd=None, timeout_s=None, log_path=None, **extra):
        calls.append({
            "step": step, "cmd": cmd, "watch_dir": watch_dir, "csv_path": csv_path,
            "cwd": cwd, "timeout_s": timeout_s, "log_path": log_path,
        })
        for entry in rs:
            if entry.get("step") == step:
                return entry
        return rs[0]

    return fake, calls


# ── cli_cmd ──

def test_cli_cmd():
    assert cli_cmd(["screen-tile", "x"], settings_path="s.toml", out="o")[1:] == [
        "-m", "pipeline.cli", "--settings", "s.toml", "--out", "o",
        "screen-tile", "x",
    ]


# ── parse_nm_jobs ──

def test_parse_nm_jobs():
    assert parse_nm_jobs("20k_1_2:hard:25:50; 20k_1_3:zabaged:10:5") == [
        ("20k_1_2", "hard", 25, 50),
        ("20k_1_3", "zabaged", 10, 5),
    ]


# ── select_tiles ──

def test_select_tiles(tmp_path):
    assert select_tiles(tmp_path, "a, b ,") == ["a", "b"]


# ── main: screen stage ──

def test_main_screen(tmp_path, monkeypatch):
    fake, calls = _make_fake([
        {"step": "screen_t1", "exit_code": 0, "wall_s": 1.0, "peak_rss_mb": 2.0},
        {"step": "screen_t2", "exit_code": 0, "wall_s": 1.0, "peak_rss_mb": 2.0},
    ])
    monkeypatch.setattr("pipeline.run_spike.run_step", fake)

    ret = main([
        "--stage", "screen",
        "--out", str(tmp_path),
        "--tiles", "t1,t2",
        "--workers", "2",
        "--pairs",
    ])
    assert ret == 0
    assert len(calls) == 2
    by_step = {c["step"]: c for c in calls}
    assert "screen_t1" in by_step
    assert "screen_t2" in by_step
    assert by_step["screen_t1"]["cmd"][-3:] == ["screen-tile", "t1", "--pairs"]
    assert by_step["screen_t2"]["cmd"][-3:] == ["screen-tile", "t2", "--pairs"]
    assert by_step["screen_t1"]["csv_path"] == tmp_path / "metrics" / "screen_t1.csv"
    assert by_step["screen_t1"]["log_path"] == tmp_path / "logs" / "screen_t1.log"


# ── main: prep stage (stop on failure) ──

def test_main_prep_failure(tmp_path, monkeypatch):
    fake, calls = _make_fake([
        {"step": "prep_region", "exit_code": 0, "wall_s": 1.0, "peak_rss_mb": 2.0},
        {"step": "prep_buildings", "exit_code": 1, "wall_s": 0.5, "peak_rss_mb": 1.0},
    ])
    monkeypatch.setattr("pipeline.run_spike.run_step", fake)

    ret = main(["--stage", "prep", "--out", str(tmp_path)])
    assert ret == 1
    assert len(calls) == 2
    assert calls[0]["step"] == "prep_region"
    assert calls[1]["step"] == "prep_buildings"


# ── merge_metrics ──

def test_merge_metrics(tmp_path):
    (tmp_path / "metrics").mkdir()
    (tmp_path / "nm" / "x").mkdir(parents=True)

    for fp in [tmp_path / "metrics" / "a.csv", tmp_path / "nm" / "x" / "metrics.csv"]:
        with open(fp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(CSV_COLUMNS)
            n_rows = 2 if "a.csv" in str(fp) else 1
            for _ in range(n_rows):
                w.writerow(["0"] * len(CSV_COLUMNS))

    info = merge_metrics(tmp_path)
    assert info["files"] == 2
    assert info["rows"] == 3
    assert info["path"].endswith("metrics_all.csv")

    with open(tmp_path / "metrics_all.csv", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    assert rows[1][0] == "metrics/a.csv"
    assert rows[2][0] == "metrics/a.csv"
    assert rows[3][0] == "nm/x/metrics.csv"
