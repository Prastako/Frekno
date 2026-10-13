"""National run: download the inputs, write the release files, and pack tiles and the index.

Run as `python -m pipeline.national <command>`; paths come from pipeline.settings (FREKNO_* variables).
"""

import argparse
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

import pyogrio
import rasterio
import requests
import shapely

from pipeline.details import FOREST_LAYERS, ROAD_LAYERS, TRACK_LAYERS
from pipeline.dem import mosaic, read_index_csv, sheets_for_bounds
from pipeline.fetch.atom import parse_service_feed, zip_url
from pipeline.fetch.download import download, download_many
from pipeline.landcover import CLASSES
from pipeline.pack import pack_tile, read_sites, write_index
from pipeline.region import read_region_geojson, read_tiles_csv, write_region_geojson
from pipeline.settings import data_paths, load_settings
from pipeline.tiles import parse_tile_id, tile_bounds, tile_id

STAT_URL = "https://services.cuzk.gov.cz/shp/stat/epsg-5514/1.zip"
OBEC_URL = "https://services.cuzk.gov.cz/shp/obec/epsg-5514/{code}.zip"
DMR_FEED_URL = "https://atom.cuzk.gov.cz/DMR4G-SJTSK-TIFF/DMR4G-SJTSK-TIFF.xml"
ZABAGED_FEED_URL = "https://atom.cuzk.gov.cz/ZABAGED-GPKG/datasetFeeds/CZ-00025712-CUZK_ZABAGED-GPKG_1.xml"
AOPK_URL = "https://gis.nature.cz/inspire/gml/INSPIRE-PS_All.gml"
SLIM_LAYERS = sorted({*(n for names in CLASSES.values() for n in names), *FOREST_LAYERS, *ROAD_LAYERS, *TRACK_LAYERS})
REGION_FILES = ["region.geojson", "tiles.csv", "receptors.csv", "facilities.csv", "protected.gpkg"]


def obec_codes(stat_zip) -> list[str]:
    """Municipality codes (OBCE_P KOD) from the RÚIAN state file, sorted."""
    path = f"/vsizip/{Path(stat_zip).resolve().as_posix()}/1/OBCE_P.shp"
    df = pyogrio.read_dataframe(path, read_geometry=False, columns=["KOD"])
    return sorted({str(int(v)) for v in df["KOD"]})


def military_areas(stat_zip, dest) -> int:
    """Write the military training areas (OBCE_P rows with STATUS_KOD 1) of the RÚIAN state file to *dest* as one
    GeoJSON feature in EPSG:5514; return how many there are."""
    path = f"/vsizip/{Path(stat_zip).resolve().as_posix()}/1/OBCE_P.shp"
    df = pyogrio.read_dataframe(path, columns=["STATUS_KOD"])
    areas = df[df["STATUS_KOD"].astype(int) == 1]
    write_region_geojson(shapely.union_all(areas.geometry.to_numpy()), dest)
    return len(areas)


def zabaged_zip_url(feed_text: str) -> str:
    """The EPSG:5514 GeoPackage ZIP link in the ZABAGED dataset feed."""
    m = re.search(r'https://[^"<\s]*-5514-gpkg-\d+\.zip', feed_text)
    if not m:
        raise ValueError("no EPSG:5514 GeoPackage link in the ZABAGED feed")
    return m.group(0)


def fetch_national(data_dir, zabaged_gpkg, workers: int = 24) -> dict:
    """Download every national input into data_dir/raw and unpack the ZABAGED GeoPackage to *zabaged_gpkg*."""
    raw = Path(data_dir) / "raw"
    stat_zip = raw / "ruian" / "stat" / "1.zip"
    download(STAT_URL, stat_zip, timeout=300)
    feed = raw / "feeds" / "DMR4G-SJTSK-TIFF.xml"
    download(DMR_FEED_URL, feed, timeout=300)
    sheets, _ = parse_service_feed(feed)
    items = [(OBEC_URL.format(code=c), raw / "ruian" / "obce" / f"{c}.zip") for c in obec_codes(stat_zip)]
    items += [(zip_url(s["code"]), raw / "dmr4g" / f"{s['code']}.zip") for s in sheets]
    items.append((AOPK_URL, raw / "aopk" / "INSPIRE-PS_All.gml"))
    stats = download_many(items, workers)
    url = zabaged_zip_url(requests.get(ZABAGED_FEED_URL, timeout=60).text)
    zpath = raw / "zabaged" / url.rsplit("/", 1)[-1]
    download(url, zpath, timeout=600)
    gpkg = Path(zabaged_gpkg)
    if not gpkg.exists():
        gpkg.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zpath) as z:
            member = next(n for n in z.namelist() if n.endswith(".gpkg"))
            with z.open(member) as src, open(gpkg, "wb") as dst:
                shutil.copyfileobj(src, dst, 16 << 20)
    stats["dmr_sheets"] = len(sheets)
    stats["zabaged"] = zpath.name
    return stats


def slim_zabaged(src_gpkg, dest_gpkg, layers=SLIM_LAYERS) -> dict:
    """Copy the ZABAGED layers the pipeline reads into a new GeoPackage; return feature counts per layer."""
    dest_gpkg = Path(dest_gpkg)
    dest_gpkg.unlink(missing_ok=True)
    counts = {}
    for name in layers:
        gdf = pyogrio.read_dataframe(src_gpkg, layer=name)
        pyogrio.write_dataframe(gdf, dest_gpkg, layer=name, driver="GPKG")
        counts[name] = len(gdf)
    return counts


def compact_tif(path) -> None:
    """Rewrite a GeoTIFF losslessly with DEFLATE and the floating-point predictor (about half the size of LZW)."""
    with rasterio.open(path) as src:
        data, profile = src.read(), src.profile
    profile.update(compress="deflate", predictor=3, tiled=True, blockxsize=256, blockysize=256)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data)


def dem_chunks(dem_index: list, tiles: list[str], res_m: float, dest_dir) -> int:
    """Write one terrain GeoTIFF per tile (tile bounds, res_m) from the sheet index; return how many were written."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for tid in tiles:
        ix, iy, size = parse_tile_id(tid)
        bounds = tile_bounds(ix, iy, size)
        rows = sheets_for_bounds(dem_index, bounds)
        if rows:
            mosaic(rows, bounds, res_m, dest_dir / f"{tid}.tif")
            compact_tif(dest_dir / f"{tid}.tif")
            written += 1
    return written


def prep_inputs(settings: dict, dest) -> dict:
    """Write the release files of a national run into *dest*: terrain chunks, slim ZABAGED and the region files."""
    paths = data_paths(settings)
    reg = paths["out_dir"] / "region"
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    tiles = [r["tile_id"] for r in read_tiles_csv(reg / "tiles.csv")]
    chunks = dem_chunks(read_index_csv(reg / "dem_index.csv"), tiles, settings["terrain"]["screening_resolution_m"], dest / "dem")
    layers = slim_zabaged(paths["zabaged"], dest / "zabaged_slim.gpkg")
    military = military_areas(paths["data_dir"] / "raw" / "ruian" / "stat" / "1.zip", dest / "military.geojson")
    for name in REGION_FILES:
        shutil.copy2(reg / name, dest / name)
    return {"tiles": len(tiles), "dem_chunks": chunks, "zabaged_layers": layers, "military_areas": military}


def tile_groups(tiles_csv, size: int) -> list[str]:
    """Tile ids from tiles.csv in groups of *size*, each group one space-separated string."""
    ids = [r["tile_id"] for r in read_tiles_csv(tiles_csv)]
    return [" ".join(ids[i:i + size]) for i in range(0, len(ids), size)]


def neighbours(tid: str) -> list[str]:
    """The tile and its eight neighbours."""
    ix, iy, size = parse_tile_id(tid)
    return [tile_id(ix + dx, iy + dy, size) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.national")
    parser.add_argument("--settings", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch").add_argument("--workers", type=int, default=24)
    sub.add_parser("inputs").add_argument("dest")
    sub.add_parser("groups").add_argument("--size", type=int, default=8)
    sub.add_parser("neighbours").add_argument("tiles", nargs="+")
    pt = sub.add_parser("pack-tile")
    pt.add_argument("tile")
    pt.add_argument("--site-dir", required=True)
    sub.add_parser("pack-index").add_argument("--site-dir", required=True)
    args = parser.parse_args(argv)
    settings = load_settings(args.settings)
    paths = data_paths(settings)
    reg = paths["out_dir"] / "region"
    if args.command == "fetch":
        res = fetch_national(paths["data_dir"], paths["zabaged"], args.workers)
    elif args.command == "inputs":
        res = prep_inputs(settings, args.dest)
    elif args.command == "groups":
        res = tile_groups(reg / "tiles.csv", args.size)
    elif args.command == "neighbours":
        res = " ".join(sorted({n for t in args.tiles for n in neighbours(t)}))
    elif args.command == "pack-tile":
        ids = read_sites(reg / "protected.gpkg")["site_id"].to_numpy()
        mil = reg / "military.geojson"
        res = pack_tile(paths["out_dir"] / "tiles" / args.tile, args.site_dir, ids, settings["receptors"]["worst_per_type_for_nm"],
                        read_region_geojson(mil) if mil.exists() else None)
        if res is not None:
            meta = Path(args.site_dir) / "meta" / f"{args.tile}.json"
            meta.parent.mkdir(parents=True, exist_ok=True)
            meta.write_text(json.dumps(res), encoding="utf-8")
    else:
        metas = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((Path(args.site_dir) / "meta").glob("*.json"))]
        res = write_index(args.site_dir, metas, read_sites(reg / "protected.gpkg"))
    print(res if isinstance(res, str) else json.dumps(res, ensure_ascii=False))
    return 1 if isinstance(res, dict) and res.get("failed") else 0


if __name__ == "__main__":
    sys.exit(main())
