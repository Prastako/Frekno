"""Parallel file downloads with retries, for the national inputs."""

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

CHUNK = 1 << 20


def download(url: str, dest, session=None, retries: int = 4, timeout: float = 120.0) -> int:
    """Download *url* to *dest* through a .part file; an existing *dest* is kept. Return the bytes written (0 if kept)."""
    dest = Path(dest)
    if dest.exists():
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    get = (session or requests).get
    for attempt in range(retries):
        try:
            with get(url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                n = 0
                with open(part, "wb") as f:
                    for block in r.iter_content(CHUNK):
                        f.write(block)
                        n += len(block)
            part.replace(dest)
            return n
        except (requests.RequestException, OSError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return 0


def download_many(items: list, workers: int = 24, retries: int = 4) -> dict:
    """Download (url, dest) pairs in parallel; return counts and the URLs that still failed."""
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=workers, pool_maxsize=workers)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    stats = {"files": 0, "bytes": 0, "kept": 0, "failed": []}

    def one(item):
        url, dest = item
        try:
            return url, download(url, dest, session, retries), None
        except Exception as err:  # noqa: BLE001 - count every failure and go on
            return url, 0, err

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for url, n, err in ex.map(one, items):
            if err is not None:
                stats["failed"].append(url)
            elif n == 0:
                stats["kept"] += 1
            else:
                stats["files"] += 1
                stats["bytes"] += n
    return stats
