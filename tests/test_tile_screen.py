"""Tests for pipeline.tile_screen."""

import csv
import zipfile
from pathlib import Path

import geopandas
import numpy as np
import pyogrio
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from pipeline.dem import build_index
from pipeline.tile_screen import (
    CANDIDATE_OUT_COLUMNS,
    receptors_in_bounds,
    screen_tile,
    tile_parts,
    write_rows,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    """Create terrain, GeoPackage, receptors, and settings for testing."""
    tmp = tmp_path_factory.mktemp("data")

    # DEM: flat 300 m terrain at 10 m resolution over (-1000, -1000, 3000, 3000)
    tr = from_origin(-1000, 3000, 10, 10)
    tif_path = tmp / "AAA01.tif"
    with rasterio.open(
        tif_path, "w",
        driver="GTiff", width=400, height=400,
        count=1, dtype="float32", crs=None, transform=tr,
        nodata=-9999.0,
    ) as ds:
        ds.write(np.full((400, 400), 300.0, dtype=np.float32), 1)

    # Zip containing the sheet
    zip_path = tmp / "AAA01.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(tif_path, "AAA01.tif")

    index = build_index([zip_path])

    # GeoPackage with landcover layers
    gpkg = tmp / "z.gpkg"
    crs = "EPSG:5514"

    pyogrio.write_dataframe(
        geopandas.GeoDataFrame(
            {"fid_zbg": [1]}, geometry=[box(0, 0, 300, 300)], crs=crs
        ), str(gpkg), layer="VodniPlocha"
    )
    pyogrio.write_dataframe(
        geopandas.GeoDataFrame(
            {"fid_zbg": [1]}, geometry=[box(1000, 1000, 2000, 2000)], crs=crs
        ), str(gpkg), layer="LesniPudaSeStromy", append=True
    )
    pyogrio.write_dataframe(
        geopandas.GeoDataFrame(
            {"fid_zbg": [1]}, geometry=[box(1700, 200, 1800, 300)], crs=crs
        ), str(gpkg), layer="BudovaJednotlivaNeboBlokBudov", append=True
    )

    # Receptors
    rec = {
        "x": np.array([1750.0, 250.0, -500.0, 5000.0]),
        "y": np.array([250.0, 1750.0, 1000.0, 1000.0]),
        "type": np.array(["home", "cottage", "home", "home"]),
        "id": np.array(["b1", "b2", "b3", "b4"]),
    }

    # Settings (mirrors spike.toml structure with overrides)
    settings = {
        "region": {"name": "test", "ruian_vusc_code": 27},
        "tiles": {"size_m": 20000, "buffer_m": 1000},
        "candidates": {
            "grid_m": 250,
            "min_distance_to_home_m": 300,
            "forest_radius_m": 300,
            "exclude": ["water", "buildings", "built_up"],
        },
        "receptors": {
            "radius_m": 1000,
            "height_m": 4.0,
            "unclear_rule": "house_number",
            "selection_sector_deg": 5,
            "selection_rings_m": [0, 500, 1000],
            "worst_per_type_for_nm": 20,
        },
        "source": {"height_m": 2.0},
        "terrain": {
            "dataset": "DMR4G",
            "screening_resolution_m": 10,
            "nm_resolution_m": 25,
            "nm_sensitivity_resolutions_m": [10, 50],
        },
        "weather": {
            "temperature_c": 10.0,
            "humidity_percent": 70.0,
            "pressure_kpa": 101.325,
            "favourable_occurrence": 1.0,
        },
        "screening": {
            "barrier_cap_single_db": 20.0,
            "barrier_cap_double_db": 25.0,
            "ground_credit": False,
            "band_31_5_terrain_credit": False,
            "n_points": 50,
            "ref_class": "medium",
            "ref_character": "very_bass_heavy",
        },
    }

    region = box(0, 0, 2000, 2000)

    return {
        "tmp": tmp,
        "index": index,
        "gpkg": gpkg,
        "rec": rec,
        "settings": settings,
        "region": region,
    }


# ── tile_parts ────────────────────────────────────────────────────────────


def test_tile_parts():
    bounds, buf = tile_parts("2k_0_0", 1000)
    assert bounds == (0, 0, 2000, 2000)
    assert buf == (-1000, -1000, 3000, 3000)


# ── receptors_in_bounds ──────────────────────────────────────────────────


def test_receptors_in_bounds(setup):
    sub = receptors_in_bounds(setup["rec"], (-1000, -1000, 3000, 3000))
    assert len(sub["x"]) == 3
    assert list(sub["id"]) == ["b1", "b2", "b3"]


# ── write_rows ───────────────────────────────────────────────────────────


def test_write_rows(tmp_path):
    rows = [{"a": "hello", "b": 1.5, "c": None}]
    write_rows(rows, ["a", "b", "c"], tmp_path / "out.csv")
    with open(tmp_path / "out.csv", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        row = next(reader)
    assert header == ["a", "b", "c"]
    assert row == ["hello", "1.5", ""]


# ── screen_tile: full integration ────────────────────────────────────────


def test_screen_tile(setup):
    out_dir = setup["tmp"] / "screen_out"

    summary = screen_tile(
        tile_id="2k_0_0",
        settings=setup["settings"],
        region=setup["region"],
        dem_index=setup["index"],
        gpkg=setup["gpkg"],
        rec=setup["rec"],
        out_dir=out_dir,
        write_pairs=False,
        keep_dem=False,
    )

    # ── Summary values ────────────────────────────────────────────────
    assert summary["tile_id"] == "2k_0_0"
    assert summary["bounds"] == [0, 0, 2000, 2000]
    assert summary["buffered_bounds"] == [-1000, -1000, 3000, 3000]
    assert summary["grid"] == 64
    assert summary["landcover"] == 1
    assert summary["near_home"] == 4
    assert summary["kept"] == 59
    assert summary["receptors_home"] == 2
    assert summary["receptors_cottage"] == 1
    assert summary["dem_sheets"] == 1
    assert summary["dem_nodata_cells"] == 0
    assert summary["dem_min"] == pytest.approx(300.0, abs=0.01)
    assert summary["dem_max"] == pytest.approx(300.0, abs=0.01)
    assert summary["dem_std"] == pytest.approx(0.0, abs=0.01)
    assert summary["pairs"] == 50

    # ── Timing keys present and non-negative ──────────────────────────
    for key in ("dem_s", "landcover_s", "candidates_s", "screening_s", "write_s"):
        assert summary[key] >= 0, f"{key} should be non-negative"

    # ── summary.json written to disk ──────────────────────────────────
    summary_path = out_dir / "summary.json"
    assert summary_path.exists()

    # ── candidates.csv ────────────────────────────────────────────────
    csv_path = out_dir / "candidates.csv"
    assert csv_path.exists()

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    assert len(rows) == 59  # 59 kept candidates

    # Find candidate at (375, 125)
    row_dict = dict(zip(header, rows))
    for row in rows:
        rd = dict(zip(header, row))
        if rd["x"] == "375.0" and rd["y"] == "125.0":
            break
    else:
        assert False, "No candidate at (375.0, 125.0) found"

    assert rd["n_home"] == "0"
    assert rd["worst_home_dba"] == ""
    assert rd["site_type"] == "open"

    # ── dem_screening.tif removed (keep_dem=False) ────────────────────
    assert not (out_dir / "dem_screening.tif").exists()

    # ── pairs.csv not written (write_pairs=False) ─────────────────────
    assert not (out_dir / "pairs.csv").exists()

    # ── Write pairs.csv with write_pairs=True ─────────────────────────
    out_dir2 = setup["tmp"] / "screen_out_pairs"
    screen_tile(
        tile_id="2k_0_0",
        settings=setup["settings"],
        region=setup["region"],
        dem_index=setup["index"],
        gpkg=setup["gpkg"],
        rec=setup["rec"],
        out_dir=out_dir2,
        write_pairs=True,
        keep_dem=True,
    )

    assert (out_dir2 / "pairs.csv").exists()
    assert (out_dir2 / "dem_screening.tif").exists()

    with open(out_dir2 / "pairs.csv", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    assert len(rows) == 50