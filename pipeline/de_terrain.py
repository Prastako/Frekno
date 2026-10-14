"""Terrain chunks for the German area: the states' terrain models averaged to 10 m and warped to S-JTSK tiles.

Sources (dl-de/by-2-0): Saxony DGM1 in 2 km GeoTIFF tiles and Brandenburg DGM1 in 1 km GeoTIFF tiles (UTM 33);
Saxony-Anhalt DGM5 in 2 km GeoTIFF tiles inside one ZIP, read with HTTP ranges, and Thuringia DGM2 (2010 to 2013) in
1 km XYZ tiles (UTM 32). Each source tile is averaged to RES_M in its own grid; the pieces of one UTM zone are put
together and sampled bilinearly at the cell centres of the RES_M S-JTSK grid of the tile, whose UTM positions come
through WGS84 like every German input (pipeline/de_area.py). Missing source tiles are skipped.
"""

import io
import math
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import requests
import shapely
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from scipy.ndimage import map_coordinates

from pipeline.de_area import SJTSK, crs_xy
from pipeline.dem import NODATA
from pipeline.tiles import parse_tile_id, tile_bounds

RES_M = 10
SN_URL = "https://geocloud.landesvermessung.sachsen.de/public.php/dav/files/JCcXyifaNdLDnxZ/dgm1_33{e}_{n}_2_sn_tiff.zip"
BB_URL = "https://data.geobasis-bb.de/geobasis/daten/dgm/tif/dgm_33{e}-{n}.zip"
ST_URL = ("https://www.geodatenportal.sachsen-anhalt.de/gfds_webshare/download/LVermGeo/Geodatenportal/"
          "Online-Bereitstellung-LVermGeo/DGM/DGM5.zip")
ST_MEMBER = "DGM5/dgm5_32_{e}_{n}_2_st.tif"
TH_URL = "https://geoportal.geoportal-th.de/hoehendaten/DGM/dgm_2010-2013/dgm2_{e}_{n}_1_th_2010-2013.zip"
SOURCES = {"SN": ("EPSG:25833", 2), "BB": ("EPSG:25833", 1), "ST": ("EPSG:25832", 2), "TH": ("EPSG:25832", 1)}


class HttpFile:
    """Read-only file over HTTP range requests (enough for zipfile)."""

    def __init__(self, url: str, session=None):
        self.url, self.pos, self.s = url, 0, session or requests.Session()
        head = retry(lambda: self.s.head(url, timeout=120, allow_redirects=True))
        self.size = int(head.headers["Content-Length"])

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, off: int, whence: int = 0) -> int:
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.size - self.pos
        if n == 0 or self.pos >= self.size:
            return b""
        rng = {"Range": f"bytes={self.pos}-{min(self.pos + n, self.size) - 1}"}
        for attempt in range(4):
            try:
                r = self.s.get(self.url, headers=rng, timeout=300)
                r.raise_for_status()
                break
            except requests.RequestException:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        self.pos += len(r.content)
        return r.content


def retry(call, attempts: int = 4):
    """call() with up to *attempts* tries on network errors, waiting 1, 2, 4 s in between."""
    for attempt in range(attempts):
        try:
            return call()
        except requests.RequestException:
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)


def block_mean(a: np.ndarray, k: int) -> np.ndarray:
    """Mean of each k x k block of *a* without NODATA cells (NODATA where a block has none); size must divide by k."""
    h, w = a.shape
    v = a.reshape(h // k, k, w // k, k).astype(np.float64)
    ok = v != NODATA
    n = ok.sum(axis=(1, 3))
    s = np.where(ok, v, 0.0).sum(axis=(1, 3))
    return np.where(n > 0, s / np.maximum(n, 1), NODATA).astype(np.float32)


def tif_piece(data: bytes) -> tuple:
    """(10 m array, west, north) from GeoTIFF bytes whose pixel size divides RES_M."""
    with MemoryFile(data) as mf, mf.open() as ds:
        a = ds.read(1).astype(np.float32)
        nod = ds.nodata
        if nod is not None and nod != NODATA:
            a[a == nod] = NODATA
        return block_mean(a, int(round(RES_M / ds.res[0]))), ds.bounds.left, ds.bounds.top


def xyz_piece(text: bytes, west: float, south: float, size_m: float) -> tuple:
    """(10 m array, west, north) from XYZ grid points of one tile (a point counts for the cell it starts)."""
    df = pd.read_csv(io.BytesIO(text), sep=r"\s+", header=None, names=["x", "y", "z"], dtype=np.float64)
    n = int(size_m / RES_M)
    col = np.floor((df["x"].to_numpy() - west) / RES_M).astype(int)
    row = np.clip(n - 1 - np.floor((df["y"].to_numpy() - south) / RES_M).astype(int), 0, n - 1)
    ok = (col >= 0) & (col < n)
    s, c = np.zeros((n, n)), np.zeros((n, n))
    np.add.at(s, (row[ok], col[ok]), df["z"].to_numpy()[ok])
    np.add.at(c, (row[ok], col[ok]), 1)
    return np.where(c > 0, s / np.maximum(c, 1), NODATA).astype(np.float32), west, south + size_m


def zip_member(data: bytes, suffix: str) -> bytes:
    """The first member of the ZIP *data* whose name ends with *suffix*."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read(next(n for n in z.namelist() if n.lower().endswith(suffix)))


def source_cells(part, crs: str, km: int) -> list[tuple[int, int]]:
    """(east, north) in km of the source tiles (km x km, aligned to km) that touch *part* (S-JTSK) in *crs*."""
    poly = shapely.transform(shapely.segmentize(part, 500.0), lambda xy: np.column_stack(crs_xy(xy[:, 0], xy[:, 1], crs)))
    x0, y0, x1, y1 = poly.bounds
    cells = []
    for e in range(math.floor(x0 / 1000 / km) * km, math.floor(x1 / 1000) + 1, km):
        for n in range(math.floor(y0 / 1000 / km) * km, math.floor(y1 / 1000) + 1, km):
            if poly.intersects(shapely.box(e * 1000, n * 1000, (e + km) * 1000, (n + km) * 1000)):
                cells.append((e, n))
    return cells


def fetch_piece(state: str, e: int, n: int, session, st_zip=None):
    """One source tile as (10 m array, west, north), or None when the state has no such tile."""
    if state == "ST":
        name = ST_MEMBER.format(e=e, n=n)
        if name not in st_zip.namelist():
            return None
        return tif_piece(st_zip.read(name))
    url = {"SN": SN_URL, "BB": BB_URL, "TH": TH_URL}[state].format(e=e, n=n)
    for attempt in range(4):
        try:
            r = session.get(url, timeout=300)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            break
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    if state == "TH":
        return xyz_piece(zip_member(r.content, ".xyz"), e * 1000.0, n * 1000.0, 1000.0)
    return tif_piece(zip_member(r.content, ".tif"))


def st_pieces(cells: list, session) -> list:
    """Saxony-Anhalt pieces for *cells* through one ZIP reader (an empty list for no cells)."""
    if not cells:
        return []
    z = zipfile.ZipFile(HttpFile(ST_URL, session))
    return [fetch_piece("ST", e, n, session, z) for e, n in cells]


def warp_pieces(pieces: list, crs: str, dst: np.ndarray, dst_transform) -> None:
    """Put the 10 m *pieces* of one UTM zone together and sample them bilinearly into *dst* where it is still NODATA
    (a cell next to a missing source cell stays NODATA)."""
    if not pieces:
        return
    west = min(p[1] for p in pieces)
    north = max(p[2] for p in pieces)
    east = max(p[1] + p[0].shape[1] * RES_M for p in pieces)
    south = min(p[2] - p[0].shape[0] * RES_M for p in pieces)
    src = np.full((int(round((north - south) / RES_M)), int(round((east - west) / RES_M))), NODATA, dtype=np.float32)
    for a, w, nth in pieces:
        r0, c0 = int(round((north - nth) / RES_M)), int(round((w - west) / RES_M))
        view = src[r0:r0 + a.shape[0], c0:c0 + a.shape[1]]
        np.copyto(view, a, where=(a != NODATA))
    rows, cols = np.mgrid[0:dst.shape[0], 0:dst.shape[1]]
    ux, uy = crs_xy(dst_transform.c + (cols.ravel() + 0.5) * dst_transform.a,
                    dst_transform.f + (rows.ravel() + 0.5) * dst_transform.e, crs)
    grid = np.where(src == NODATA, np.nan, src).astype(np.float64)
    pos = [(north - np.asarray(uy)) / RES_M - 0.5, (np.asarray(ux) - west) / RES_M - 0.5]
    out = map_coordinates(grid, pos, order=1, mode="constant", cval=np.nan).reshape(dst.shape)
    np.copyto(dst, out.astype(np.float32), where=(dst == NODATA) & np.isfinite(out))


def tile_chunk(tile_id: str, states: dict, dest_dir, workers: int = 8) -> dict:
    """Write dest_dir/<tile_id>.tif (RES_M, S-JTSK) from the sources of the states (*states*: {code: part of the
    region}) that touch the tile; return the number of source tiles used per state. Nothing is written without data."""
    ix, iy, size = parse_tile_id(tile_id)
    bounds = tile_bounds(ix, iy, size)
    box = shapely.box(*bounds).buffer(100.0)
    dst = np.full((int(size / RES_M), int(size / RES_M)), NODATA, dtype=np.float32)
    transform = from_origin(bounds[0], bounds[3], RES_M, RES_M)
    session = requests.Session()
    used = {}
    for zone in ("EPSG:25833", "EPSG:25832"):
        pieces = []
        for st, (crs, km) in SOURCES.items():
            part = states.get(st)
            if crs != zone or part is None or not part.intersects(box):
                continue
            cells = source_cells(part.intersection(box), crs, km)
            if st == "ST":  # one ZIP reader per thread: a reader keeps a file position
                groups = [cells[j::workers] for j in range(workers)]
                with ThreadPoolExecutor(workers) as ex:
                    parts = list(ex.map(lambda g: st_pieces(g, session), groups))
                got = [p for part in parts for p in part]
            else:
                with ThreadPoolExecutor(workers) as ex:
                    got = list(ex.map(lambda c: fetch_piece(st, c[0], c[1], session), cells))
            used[st] = sum(g is not None for g in got)
            pieces += [g for g in got if g is not None]
        warp_pieces(pieces, zone, dst, transform)
    if not (dst != NODATA).any():
        return used
    dest = Path(dest_dir) / f"{tile_id}.tif"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(dest, "w", driver="GTiff", height=dst.shape[0], width=dst.shape[1], count=1, dtype="float32",
                       crs=SJTSK, transform=transform, nodata=NODATA, compress="deflate", predictor=3, tiled=True,
                       blockxsize=256, blockysize=256) as ds:
        ds.write(dst, 1)
    return used