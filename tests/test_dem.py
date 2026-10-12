"""Tests for pipeline.dem — DMR 4G sheet indexing and mosaicking."""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

from pipeline.dem import (
    NODATA,
    SJTSK,
    INDEX_COLUMNS,
    sheet_path,
    build_index,
    write_index_csv,
    read_index_csv,
    sheets_for_bounds,
    mosaic,
)


def _make_sheet(
    tmp_path: Path,
    code: str,
    nrows: int,
    ncols: int,
    data: np.ndarray,
    xmin: float,
    ymax: float,
    pixel_size: float = 5.0,
) -> Path:
    """Create a DMR 4G-style ZIP with CODE.tif and CODE.tfw in *tmp_path*."""
    tif_path = tmp_path / f"{code}.tif"
    tfw_path = tmp_path / f"{code}.tfw"

    transform = from_origin(xmin, ymax, pixel_size, pixel_size)

    with rasterio.open(
        tif_path, "w", driver="GTiff",
        height=nrows, width=ncols, count=1,
        dtype="float32",
        crs=CRS.from_string(SJTSK),
        transform=transform,
    ) as dst:
        dst.write(data.astype("float32"), 1)

    # World file (TFW) — GDAL reads this when accessing via /vsizip/
    with open(tfw_path, "w") as f:
        f.write(f"{pixel_size}\n0\n0\n{-pixel_size}\n{xmin}\n{ymax}\n")

    zip_path = tmp_path / f"{code}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(tif_path, f"{code}.tif")
        zf.write(tfw_path, f"{code}.tfw")

    return zip_path


@pytest.fixture
def sheets(tmp_path: Path) -> tuple[list[Path], list[dict]]:
    """Build two test sheets A and B and return (zip_paths, index_rows)."""
    # Sheet A: 10 rows x 20 cols, all 100.0, top-left (0, 100)
    a_data = np.full((10, 20), 100.0, dtype="float32")
    zip_a = _make_sheet(tmp_path, "A", 10, 20, a_data, 0.0, 100.0)

    # Sheet B: 10 rows x 20 cols, value = row + 10*col, top-left (0, 50)
    b_data = np.fromfunction(
        lambda r, c: r + 10.0 * c, (10, 20), dtype="float32"
    )
    zip_b = _make_sheet(tmp_path, "B", 10, 20, b_data, 0.0, 50.0)

    zip_paths = [zip_a, zip_b]
    rows = build_index(zip_paths)
    return zip_paths, rows


class TestSheetPath:
    def test_format(self, tmp_path: Path) -> None:
        z = tmp_path / "X123.zip"
        z.touch()
        result = sheet_path(z)
        assert result.startswith("/vsizip/")
        assert result.endswith("/X123.tif")


class TestBuildIndex:
    def test_bounds_and_order(self, sheets: tuple) -> None:
        _, rows = sheets
        assert len(rows) == 2

        # Sheet A: 10 rows x 20 cols at 5 m → height 50, width 100
        # top-left (0, 100) → (xmin=0, ymin=50, xmax=100, ymax=100)
        a = rows[0]
        assert a["code"] == "A"
        assert a["xmin"] == pytest.approx(0.0, abs=1e-6)
        assert a["ymin"] == pytest.approx(50.0, abs=1e-6)
        assert a["xmax"] == pytest.approx(100.0, abs=1e-6)
        assert a["ymax"] == pytest.approx(100.0, abs=1e-6)

        # Sheet B: top-left (0, 50) → (xmin=0, ymin=0, xmax=100, ymax=50)
        b = rows[1]
        assert b["code"] == "B"
        assert b["xmin"] == pytest.approx(0.0, abs=1e-6)
        assert b["ymin"] == pytest.approx(0.0, abs=1e-6)
        assert b["xmax"] == pytest.approx(100.0, abs=1e-6)
        assert b["ymax"] == pytest.approx(50.0, abs=1e-6)


class TestIndexCsvRoundTrip:
    def test_round_trip(self, sheets: tuple, tmp_path: Path) -> None:
        _, original = sheets
        csv_path = tmp_path / "index.csv"
        write_index_csv(original, csv_path)
        restored = read_index_csv(csv_path)

        assert len(restored) == len(original)
        for orig, rest in zip(original, restored):
            assert rest["code"] == orig["code"]
            assert rest["path"] == orig["path"]
            assert rest["xmin"] == pytest.approx(orig["xmin"], abs=1e-6)
            assert rest["ymin"] == pytest.approx(orig["ymin"], abs=1e-6)
            assert rest["xmax"] == pytest.approx(orig["xmax"], abs=1e-6)
            assert rest["ymax"] == pytest.approx(orig["ymax"], abs=1e-6)


class TestSheetsForBounds:
    def test_full_overlap(self, sheets: tuple) -> None:
        _, rows = sheets
        result = sheets_for_bounds(rows, (0, 0, 100, 100))
        assert len(result) == 2

    def test_partial_overlap(self, sheets: tuple) -> None:
        _, rows = sheets
        result = sheets_for_bounds(rows, (0, 50, 100, 100))
        assert len(result) == 1
        assert result[0]["code"] == "A"

    def test_no_overlap(self, sheets: tuple) -> None:
        _, rows = sheets
        result = sheets_for_bounds(rows, (1000, 1000, 1100, 1100))
        assert len(result) == 0


class TestMosaic:
    def test_basic(self, sheets: tuple, tmp_path: Path) -> None:
        _, rows = sheets
        out = tmp_path / "mosaic" / "out.tif"

        info = mosaic(rows, (0, 0, 100, 100), 10.0, out)

        assert info["width"] == 10
        assert info["height"] == 10
        assert info["sheets"] == 2
        assert info["nodata_cells"] == 0

        # Read back the mosaic
        with rasterio.open(out) as ds:
            arr = ds.read(1)

        # Top half (rows 0-4, y=50-100) is sheet A → all 100.0
        assert np.allclose(arr[:5, :], 100.0, atol=1e-4)

        # Cell [5, 1] = mean of B cells rows 0-1, cols 2-3
        # B[0,2]=20, B[0,3]=30, B[1,2]=21, B[1,3]=31 → mean = 25.5
        assert arr[5, 1] == pytest.approx(25.5, abs=1e-4)

    def test_no_overlap(self, sheets: tuple, tmp_path: Path) -> None:
        _, rows = sheets
        out = tmp_path / "empty" / "out.tif"

        info = mosaic(rows, (1000, 1000, 1100, 1100), 10.0, out)

        assert info["sheets"] == 0
        assert info["nodata_cells"] == 100  # 10 x 10
        assert info["min"] is None
        assert info["max"] is None

    def test_invalid_bounds(self, sheets: tuple, tmp_path: Path) -> None:
        _, rows = sheets
        out = tmp_path / "bad" / "out.tif"

        with pytest.raises(ValueError):
            mosaic(rows, (0, 0, 95, 100), 10.0, out)

    def test_file_properties(self, sheets: tuple, tmp_path: Path) -> None:
        _, rows = sheets
        out = tmp_path / "prop" / "out.tif"
        mosaic(rows, (0, 0, 100, 100), 10.0, out)

        with rasterio.open(out) as ds:
            assert ds.crs == CRS.from_string(SJTSK)
            assert ds.nodata == NODATA
            assert ds.dtypes[0] == "float32"
