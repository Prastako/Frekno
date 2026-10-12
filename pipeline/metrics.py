"""Record run time, memory, and disk use of a single pipeline step."""

import csv
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

MB = 1048576

CSV_COLUMNS = [
    "step",
    "started_utc",
    "wall_s",
    "peak_rss_mb",
    "start_disk_mb",
    "peak_disk_mb",
    "end_disk_mb",
    "exit_code",
    "timed_out",
]


def folder_size_bytes(path: Path | str) -> int:
    """Total size of all files below *path*, recursively."""
    path = Path(path)
    if not path.exists():
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for fname in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fname))
            except (FileNotFoundError, PermissionError):
                continue
    return total


def run_step(
    step: str,
    cmd: list[str],
    watch_dir: Path,
    csv_path: Path,
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout_s: float | None = None,
    sample_s: float = 0.25,
    log_path: Path | str | None = None,
) -> dict:
    """Run *cmd* as a subprocess and record metrics to *csv_path*.

    log_path: when given, stdout and stderr of the command go to this file.

    Returns a dict keyed by :data:`CSV_COLUMNS`.
    """
    # -- pre-start measurements ----------------------------------------
    start_disk = folder_size_bytes(watch_dir)
    started_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    t0 = time.monotonic()

    peak_rss = 0
    peak_disk_sampled = 0

    # -- launch --------------------------------------------------------
    log_file = None
    if log_path is not None:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "w", encoding="utf-8")
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log_file,
                                stderr=subprocess.STDOUT if log_file else None)
        ps_proc = psutil.Process(proc.pid)
    except OSError:
        # Program not found or similar – record failure, no exception.
        wall_s = time.monotonic() - t0
        end_disk = folder_size_bytes(watch_dir)
        peak_disk = max(peak_disk_sampled, start_disk, end_disk)
        result = {
            "step": step,
            "started_utc": started_utc,
            "wall_s": wall_s,
            "peak_rss_mb": peak_rss / MB,
            "start_disk_mb": start_disk / MB,
            "peak_disk_mb": peak_disk / MB,
            "end_disk_mb": end_disk / MB,
            "exit_code": -1,
            "timed_out": False,
        }
        if log_file is not None:
            log_file.close()
        _write_row(csv_path, result)
        return result

    timed_out = False
    exit_code: int | None = None

    try:
        # -- sampling loop ---------------------------------------------
        while True:
            elapsed = time.monotonic() - t0

            # Check timeout before sampling
            if timeout_s is not None and elapsed >= timeout_s:
                timed_out = True
                # Kill descendants first, then parent
                try:
                    for child in ps_proc.children(recursive=True):
                        try:
                            child.kill()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                try:
                    ps_proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                proc.wait()
                exit_code = -2
                break

            # Take a sample
            try:
                rss = ps_proc.memory_info().rss
                for child in ps_proc.children(recursive=True):
                    try:
                        rss += child.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            else:
                peak_rss = max(peak_rss, rss)

            disk = folder_size_bytes(watch_dir)
            peak_disk_sampled = max(peak_disk_sampled, disk)

            # Check if process is still running
            if proc.poll() is not None:
                exit_code = proc.returncode
                break

            time.sleep(sample_s)

        # If we exited the loop without a timeout break, get exit code
        if exit_code is None:
            exit_code = proc.returncode if proc.returncode is not None else 0

    finally:
        wall_s = time.monotonic() - t0
        end_disk = folder_size_bytes(watch_dir)
        peak_disk = max(peak_disk_sampled, start_disk, end_disk)

    result = {
        "step": step,
        "started_utc": started_utc,
        "wall_s": wall_s,
        "peak_rss_mb": peak_rss / MB,
        "start_disk_mb": start_disk / MB,
        "peak_disk_mb": peak_disk / MB,
        "end_disk_mb": end_disk / MB,
        "exit_code": exit_code,
        "timed_out": timed_out,
    }

    if log_file is not None:
        log_file.close()
    _write_row(csv_path, result)
    return result


def _write_row(csv_path: Path, result: dict) -> None:
    """Append a single CSV row for *result* to *csv_path*."""
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    # Write header if file does not exist or is empty
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        if write_header:
            writer.writerow(CSV_COLUMNS)
        writer.writerow(
            [
                result["step"],
                result["started_utc"],
                f'{result["wall_s"]:.3f}',
                f'{result["peak_rss_mb"]:.1f}',
                f'{result["start_disk_mb"]:.1f}',
                f'{result["peak_disk_mb"]:.1f}',
                f'{result["end_disk_mb"]:.1f}',
                str(int(result["exit_code"])),
                "true" if result["timed_out"] else "false",
            ]
        )
