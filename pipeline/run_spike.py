"""Run spike stages as subprocesses with metrics and logging."""

import argparse
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pipeline.metrics import CSV_COLUMNS, run_step
from pipeline.region import read_tiles_csv
from pipeline.settings import ROOT, data_paths, load_settings

PREP_COMMANDS = ["prep-region", "prep-buildings", "prep-receptors", "prep-dem-index"]
STAGES = ("prep", "screen", "nm", "ruian", "merge")


def cli_cmd(args, settings_path=None, out=None):
    """Build a pipeline.cli command list."""
    cmd = [sys.executable, "-m", "pipeline.cli"]
    if settings_path is not None:
        cmd.extend(["--settings", str(settings_path)])
    if out is not None:
        cmd.extend(["--out", str(out)])
    cmd.extend(str(a) for a in args)
    return cmd


def step(name, args, out, watch_dir, timeout_s=None, settings_path=None):
    """Run a single pipeline step and record metrics."""
    watch_dir.mkdir(parents=True, exist_ok=True)
    return run_step(
        name,
        cli_cmd(args, settings_path, out),
        watch_dir,
        out / "metrics" / f"{name}.csv",
        cwd=ROOT,
        timeout_s=timeout_s,
        log_path=out / "logs" / f"{name}.log",
    )


def run_prep(out, settings_path=None, timeout_s=None):
    """Run preparation commands sequentially, stopping on first failure."""
    results = []
    for cmd in PREP_COMMANDS:
        name = cmd.replace("-", "_")
        row = step(name, [cmd], out, out / "region", timeout_s, settings_path)
        results.append(row)
        if row["exit_code"] != 0:
            break
    return results


def select_tiles(out, spec):
    """Return a list of tile IDs based on the selection spec."""
    if spec == "all":
        tiles = read_tiles_csv(out / "region" / "tiles.csv")
        return [t["tile_id"] for t in tiles]
    if spec == "full":
        tiles = read_tiles_csv(out / "region" / "tiles.csv")
        return [t["tile_id"] for t in tiles if t["full"]]
    return [t.strip() for t in spec.split(",") if t.strip()]


def run_screen(out, tiles, workers=1, pairs=False, settings_path=None, timeout_s=None):
    """Run screen-tile for each tile using a thread pool."""
    def _screen(tile):
        return step(
            f"screen_{tile}",
            ["screen-tile", tile] + (["--pairs"] if pairs else []),
            out,
            out / "tiles" / tile,
            timeout_s,
            settings_path,
        )
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(_screen, tiles))


def parse_nm_jobs(spec):
    """Parse nm job spec into list of (tile, variant, res, n) tuples."""
    jobs = []
    for part in spec.split(";"):
        part = part.strip()
        if not part:
            continue
        tile, variant, res, n = part.split(":")
        jobs.append((tile.strip(), variant.strip(), int(res), int(n)))
    return jobs


def run_nm(out, jobs, java_opts="", settings_path=None, timeout_s=None):
    """Run nm-tile jobs sequentially."""
    results = []
    for tile, variant, res, n in jobs:
        args = [
            "nm-tile", tile,
            "--variant", variant,
            "--res", res,
            "--n", n,
            f"--java-opts={java_opts}",
        ]
        if timeout_s is not None:
            args.append("--timeout")
            args.append(str(timeout_s))
        name = f"nm_{tile}_{variant}_{res}m"
        row = step(name, args, out, out / "nm", timeout_s, settings_path)
        results.append(row)
    return results


def merge_metrics(out):
    """Merge all per-step metric CSV files into a single file with source column."""
    files = sorted((out / "metrics").glob("*.csv")) + sorted((out / "nm").glob("*/metrics.csv"))
    target = out / "metrics_all.csv"
    row_count = 0
    with open(target, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["source"] + CSV_COLUMNS)
        for fp in files:
            with open(fp, newline="") as src:
                reader = csv.DictReader(src)
                for row in reader:
                    writer.writerow([fp.relative_to(out).as_posix()] + [row[c] for c in CSV_COLUMNS])
                    row_count += 1
    return {"files": len(files), "rows": row_count, "path": str(target)}


def build_parser():
    """Build the CLI argument parser."""
    p = argparse.ArgumentParser()
    p.add_argument("--stage", required=True, choices=STAGES)
    p.add_argument("--settings")
    p.add_argument("--out")
    p.add_argument("--tiles", default="all")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--pairs", action="store_true")
    p.add_argument("--nm-jobs", default="")
    p.add_argument("--java-opts", default="")
    p.add_argument("--timeout", type=float, default=None)
    return p


def main(argv=None):
    """Parse arguments, run the requested stage, return exit code."""
    args = build_parser().parse_args(argv)
    out = Path(args.out) if args.out else data_paths(load_settings(args.settings))["out_dir"]
    out.mkdir(parents=True, exist_ok=True)

    if args.stage == "prep":
        results = run_prep(out, args.settings, args.timeout)
    elif args.stage == "screen":
        results = run_screen(
            out,
            select_tiles(out, args.tiles),
            args.workers,
            args.pairs,
            args.settings,
            args.timeout,
        )
    elif args.stage == "nm":
        results = run_nm(out, parse_nm_jobs(args.nm_jobs), args.java_opts, args.settings, args.timeout)
    elif args.stage == "ruian":
        results = [step("ruian_check", ["ruian-check"], out, out / "ruian", args.timeout, args.settings)]
    elif args.stage == "merge":
        print(json.dumps(merge_metrics(out)))
        return 0

    for r in results:
        print(json.dumps({
            "step": r["step"],
            "exit_code": r["exit_code"],
            "wall_s": round(r["wall_s"], 1),
            "peak_rss_mb": round(r["peak_rss_mb"], 1),
        }))
    return 0 if all(r["exit_code"] == 0 for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
