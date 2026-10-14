"""Tests for pipeline.de_terrain (terrain chunks of the German area); no network."""

import io
import math
import zipfile

import numpy as np
import pytest
import rasterio
import shapely
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from pipeline import de_terrain as dt
from pipeline.de_area import crs_xy, sjtsk_xy
from pipeline.dem import NODATA
from pipeline.tiles import tile_bounds

UTM33 = "EPSG:25833"


def tif_bytes(a, west, north, res, nodata):
    with MemoryFile() as mf:
        with mf.open(driver="GTiff", height=a.shape[0], width=a.shape[1], count=1, dtype="float32", crs=UTM33,
                     transform=from_origin(west, north, res, res), nodata=nodata) as ds:
            ds.write(a.astype(np.float32), 1)
        return mf.read()


def utm_part(x0, y0, x1, y1, crs=UTM33):
    """The UTM box as a polygon in S-JTSK (through WGS84, like the module)."""
    ring = shapely.get_coordinates(shapely.segmentize(shapely.box(x0, y0, x1, y1).exterior, 100.0))
    return shapely.Polygon(np.column_stack(sjtsk_xy(ring[:, 0], ring[:, 1], crs)))


def test_block_mean():
    a = np.array([[1, 3, NODATA, NODATA], [5, 7, NODATA, NODATA], [2, 2, 2, NODATA], [2, 2, 2, 6]], dtype=np.float32)
    got = dt.block_mean(a, 2)
    assert got.tolist() == [[4.0, NODATA], [2.0, pytest.approx(10 / 3)]]
    assert got.dtype == np.float32


def test_tif_piece_averages_and_keeps_nodata():
    a = np.full((20, 20), 100.0)
    a[:10, :10] = -32767.0
    a[10:, 10:] = 50.0
    got, west, north = dt.tif_piece(tif_bytes(a, 316000.0, 5692000.0, 1.0, -32767.0))
    assert (west, north) == (316000.0, 5692000.0)
    assert got.tolist() == [[NODATA, 100.0], [100.0, 50.0]]


def test_xyz_piece():
    xs, ys = np.meshgrid(np.arange(0.0, 20.0, 2.0), np.arange(0.0, 20.0, 2.0))
    lines = [f"{700000 + x:.2f} {5640000 + y:.2f} {x + 100 * (y >= 10):.2f}" for x, y in zip(xs.ravel(), ys.ravel())]
    got, west, north = dt.xyz_piece("\n".join(lines).encode(), 700000.0, 5640000.0, 20.0)
    assert (west, north) == (700000.0, 5640020.0)
    assert got.tolist() == [[104.0, 114.0], [4.0, 14.0]]


def test_zip_member():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.tif.aux.xml", b"x")
        z.writestr("a.tif", b"tif")
    assert dt.zip_member(buf.getvalue(), ".tif") == b"tif"


def test_source_cells():
    part = utm_part(316100.0, 5690100.0, 317900.0, 5691900.0)
    assert dt.source_cells(part, UTM33, 2) == [(316, 5690)]
    assert dt.source_cells(part, UTM33, 1) == [(316, 5690), (316, 5691), (317, 5690), (317, 5691)]


def test_warp_pieces_samples_through_wgs84():
    piece = (np.full((200, 200), 100.0, dtype=np.float32), 316000.0, 5692000.0)
    cx, cy = sjtsk_xy(317000.0, 5691000.0, UTM33)
    x0, y0 = math.floor(cx / 10) * 10 - 50, math.floor(cy / 10) * 10 - 50
    dst = np.full((10, 10), NODATA, dtype=np.float32)
    dst[0, 0] = 7.0
    dt.warp_pieces([piece], UTM33, dst, from_origin(x0, y0 + 100, 10, 10))
    assert dst[0, 0] == 7.0 and (dst.ravel()[1:] == 100.0).all()
    far = np.full((4, 4), NODATA, dtype=np.float32)
    dt.warp_pieces([piece], UTM33, far, from_origin(x0 + 5000, y0, 10, 10))
    assert (far == NODATA).all()


def test_tile_chunk_with_fake_sources(tmp_path, monkeypatch):
    calls = []

    def fake(state, e, n, session, st_zip=None):
        calls.append((state, e, n))
        return np.full((200, 200), 50.0, dtype=np.float32), e * 1000.0, (n + 2) * 1000.0

    monkeypatch.setattr(dt, "fetch_piece", fake)
    part = utm_part(316200.0, 5690200.0, 317800.0, 5691800.0)
    cx, cy = part.centroid.x, part.centroid.y
    tid = f"20k_{math.floor(cx / 20000)}_{math.floor(cy / 20000)}"
    used = dt.tile_chunk(tid, {"SN": part}, tmp_path)
    assert used == {"SN": len(calls)} and ("SN", 316, 5690) in calls
    with rasterio.open(tmp_path / f"{tid}.tif") as ds:
        assert ds.crs.to_string() == "EPSG:5514" and ds.res == (10.0, 10.0)
        assert tuple(ds.bounds) == tile_bounds(*[int(v) for v in tid[4:].split("_")], 20000)
        a = ds.read(1)
        r, c = ds.index(cx, cy)
        assert a[r, c] == 50.0 and (a == NODATA).any()
    assert dt.tile_chunk(tid, {}, tmp_path / "none") == {}
    assert not (tmp_path / "none").exists()


class FakeSession:
    """Serves *data* to HEAD and ranged GET requests."""

    def __init__(self, data):
        self.data = data

    def head(self, url, timeout=None, allow_redirects=None):
        return type("R", (), {"headers": {"Content-Length": str(len(self.data))}})()

    def get(self, url, headers=None, timeout=None):
        a, b = (int(v) for v in headers["Range"][6:].split("-"))
        return type("R", (), {"content": self.data[a:b + 1], "raise_for_status": lambda self: None})()


def test_http_file_reads_a_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("DGM5/a.tif", b"0123456789" * 1000)
    z = zipfile.ZipFile(dt.HttpFile("https://example.org/x.zip", FakeSession(buf.getvalue())))
    assert z.namelist() == ["DGM5/a.tif"] and z.read("DGM5/a.tif") == b"0123456789" * 1000


def test_crs_xy_round_trip():
    x, y = sjtsk_xy(317000.0, 5691000.0, UTM33)
    assert crs_xy(x, y, UTM33) == pytest.approx((317000.0, 5691000.0), abs=0.01)
