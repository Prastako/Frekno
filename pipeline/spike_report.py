"""Spike report: tables derived from pipeline spike outputs."""

import csv
import json
import math
from pathlib import Path

import numpy as np

from pipeline.region import read_tiles_csv

BANDS = ["63", "125", "250", "500", "1k", "2k", "4k", "8k"]
DIST_EDGES = [0, 1000, 2000, 4000, 7000, 10000]
TILE_REPORT_COLUMNS = [
    "tile_id", "full", "region_km2", "grid", "kept",
    "receptors_home", "receptors_cottage", "dem_relief_m", "dem_std_m",
    "wall_s", "peak_rss_mb", "peak_disk_mb",
    "dem_s", "landcover_s", "candidates_s", "screening_s",
]
STAT_COLUMNS = ["variant", "res_m", "band", "dist_class", "n", "mean", "std", "p10", "p50", "p90"]
NM_RUN_COLUMNS = [
    "run", "tile_id", "variant", "res_m", "ok", "sources", "receivers",
    "pairs_of_interest", "compared", "steps_wall_s", "propagate_wall_s", "max_rss_mb",
]


def read_csv(path: Path) -> list[dict]:
    """Read a CSV file into a list of dicts."""
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def last_metrics(out: Path) -> dict[str, dict]:
    """Return step -> its last row dict from metrics_all.csv."""
    metrics_path = out / "metrics_all.csv"
    if not metrics_path.exists():
        return {}
    result: dict[str, dict] = {}
    for row in read_csv(metrics_path):
        result[row["step"]] = row
    return result


def tile_report_rows(out: Path) -> list[dict]:
    """Build one report row per tile that has both summary.json and screening metrics."""
    tiles = read_tiles_csv(out / "region" / "tiles.csv")
    metrics = last_metrics(out)
    rows: list[dict] = []
    for tile in tiles:
        tile_id = tile["tile_id"]
        summary_path = out / "tiles" / tile_id / "summary.json"
        if not summary_path.exists():
            continue
        screen_step = f"screen_{tile_id}"
        if screen_step not in metrics:
            continue
        summary = json.loads(summary_path.read_text())
        m = metrics[screen_step]
        dem_max = summary.get("dem_max")
        row = {
            "tile_id": tile_id,
            "full": tile["full"],
            "region_km2": float(tile["region_km2"]),
            "grid": summary["grid"],
            "kept": summary["kept"],
            "receptors_home": summary["receptors_home"],
            "receptors_cottage": summary["receptors_cottage"],
            "dem_relief_m": dem_max - summary["dem_min"] if dem_max is not None else None,
            "dem_std_m": summary.get("dem_std"),
            "wall_s": float(m["wall_s"]),
            "peak_rss_mb": float(m["peak_rss_mb"]),
            "peak_disk_mb": float(m["peak_disk_mb"]),
            "dem_s": summary.get("dem_s"),
            "landcover_s": summary.get("landcover_s"),
            "candidates_s": summary.get("candidates_s"),
            "screening_s": summary.get("screening_s"),
        }
        rows.append(row)
    return rows


def extrapolate(
    rows: list[dict],
    cz_area_km2: float,
    cz_tiles: int,
    limits: dict,
) -> dict:
    """Estimate cost of processing all of Czechia from the spike sample."""
    if not rows:
        return {"tiles_done": 0}

    km2 = sum(r["region_km2"] for r in rows)
    wall = sum(r["wall_s"] for r in rows)

    full = [r for r in rows if r["full"]]
    if not full:
        full = rows

    return {
        "tiles_done": len(rows),
        "region_km2_done": km2,
        "total_wall_h": wall / 3600,
        "s_per_km2": wall / km2,
        "full_tiles_done": sum(1 for r in rows if r["full"]),
        "full_tile_wall_min_mean": sum(r["wall_s"] for r in full) / len(full) / 60,
        "full_tile_wall_min_max": max(r["wall_s"] for r in full) / 60,
        "max_tile_wall_h": max(r["wall_s"] for r in rows) / 3600,
        "max_rss_gb": max(r["peak_rss_mb"] for r in rows) / 1024,
        "max_disk_gb": max(r["peak_disk_mb"] for r in rows) / 1024,
        "cz_wall_h": (wall / km2) * cz_area_km2 / 3600,
        "cz_tiles": cz_tiles,
        "cz_wall_h_with_concurrency": ((wall / km2) * cz_area_km2 / 3600) / limits["concurrent_jobs"],
        "runs_needed": math.ceil(cz_tiles / limits["jobs_per_run"]),
        "fits_job_hours": max(r["wall_s"] for r in rows) / 3600 <= limits["job_hours"],
        "fits_ram": max(r["peak_rss_mb"] for r in rows) / 1024 <= limits["ram_gb"],
        "fits_disk": max(r["peak_disk_mb"] for r in rows) / 1024 <= limits["disk_gb"],
    }


def compare_rows(out: Path) -> list[dict]:
    """Collect every row from every compare.csv under out/nm/."""
    nm_dir = out / "nm"
    if not nm_dir.exists():
        return []
    rows: list[dict] = []
    for run_dir in sorted(nm_dir.iterdir()):
        csv_path = run_dir / "compare.csv"
        if not csv_path.exists():
            continue
        for row in read_csv(csv_path):
            rows.append({
                "variant": row["variant"],
                "res_m": float(row["res_m"]),
                "dist_m": float(row["dist_m"]),
                **{f"s{b}": float(row[f"a{b}"]) for b in BANDS},
                **{f"n{b}": float(row[f"nm{b}"]) for b in BANDS},
            })
    return rows


def dist_class(d: float) -> str:
    """Return the distance bucket label for a distance in metres."""
    for i in range(len(DIST_EDGES) - 1):
        if d < DIST_EDGES[i + 1]:
            return f"{DIST_EDGES[i]}-{DIST_EDGES[i + 1]}"
    return f">={DIST_EDGES[-1]}"


def compare_stats(rows: list[dict]) -> list[dict]:
    """Compute screening-vs-noise diff statistics grouped by variant/res/band/distance."""
    groups: dict[tuple, list[float]] = {}

    for row in rows:
        for b in BANDS:
            diff = row[f"n{b}"] - row[f"s{b}"]
            vc = (row["variant"], row["res_m"], b, "all")
            groups.setdefault(vc, []).append(diff)
            dc = dist_class(row["dist_m"])
            vd = (row["variant"], row["res_m"], b, dc)
            groups.setdefault(vd, []).append(diff)

    sorted_keys = sorted(groups.keys(), key=lambda k: (k[0], k[1], BANDS.index(k[2]), k[3]))

    result: list[dict] = []
    for key in sorted_keys:
        values = groups[key]
        arr = np.array(values)
        result.append({
            "variant": key[0],
            "res_m": key[1],
            "band": key[2],
            "dist_class": key[3],
            "n": len(values),
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr, ddof=0)),
            "p10": float(np.percentile(arr, 10)),
            "p50": float(np.percentile(arr, 50)),
            "p90": float(np.percentile(arr, 90)),
        })
    return result


def nm_run_rows(out: Path) -> list[dict]:
    """One row per summary.json found under out/nm/*/."""
    nm_dir = out / "nm"
    if not nm_dir.exists():
        return []
    rows: list[dict] = []
    for run_dir in sorted(nm_dir.iterdir()):
        summary_path = run_dir / "summary.json"
        if not summary_path.exists():
            continue
        summary = json.loads(summary_path.read_text())
        steps = summary.get("steps", [])
        steps_wall_s = sum(s["wall_s"] for s in steps)
        propagate_wall_s = None
        for s in steps:
            if s["step"].endswith("propagate"):
                propagate_wall_s = s["wall_s"]
                break
        max_rss_mb = max((s["peak_rss_mb"] for s in steps), default=None)
        rows.append({
            "run": run_dir.name,
            "tile_id": summary["tile_id"],
            "variant": summary["variant"],
            "res_m": summary["res_m"],
            "ok": summary["ok"],
            "sources": summary["sources"],
            "receivers": summary["receivers"],
            "pairs_of_interest": summary["pairs_of_interest"],
            "compared": summary["compared"],
            "steps_wall_s": steps_wall_s,
            "propagate_wall_s": propagate_wall_s,
            "max_rss_mb": max_rss_mb,
        })
    return rows


def write_csv(rows: list[dict], columns: list[str], path: Path, float_as_repr: bool = True) -> None:
    """Write rows to CSV; None becomes empty string, floats use repr when float_as_repr is True."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            formatted = {}
            for col in columns:
                v = row.get(col, "")
                if v is None:
                    formatted[col] = ""
                elif isinstance(v, float) and float_as_repr:
                    formatted[col] = repr(v)
                else:
                    formatted[col] = v
            writer.writerow(formatted)


def write_report_tables(
    out: Path,
    cz_area_km2: float,
    cz_tiles: int,
    limits: dict,
) -> dict:
    """Generate all report artefacts under out/report/."""
    report_dir = out / "report"
    report_dir.mkdir(parents=True, exist_ok=True)

    tile_rows = tile_report_rows(out)
    write_csv(tile_rows, TILE_REPORT_COLUMNS, report_dir / "tiles.csv")

    ext = extrapolate(tile_rows, cz_area_km2, cz_tiles, limits)
    (report_dir / "extrapolation.json").write_text(json.dumps(ext, indent=1) + "\n")

    comp_rows = compare_rows(out)
    stats = compare_stats(comp_rows) if comp_rows else []
    write_csv(stats, STAT_COLUMNS, report_dir / "compare_stats.csv")

    runs = nm_run_rows(out)
    write_csv(runs, NM_RUN_COLUMNS, report_dir / "nm_runs.csv")

    return {
        "tiles": len(tile_rows),
        "compare_groups": len(stats),
        "nm_runs": len(runs),
    }
