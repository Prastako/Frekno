"""Inputs of the German area around Leipzig for a tile run, with the same file names as the Czech national inputs.

Run as `python -m pipeline.germany <command>`; paths come from pipeline.settings (FREKNO_* variables):
fetch (downloads, region and tiles), prep (receptors, facilities, protected and military areas, slim GeoPackage),
terrain <tiles> --dest <dir> (terrain chunks), inputs <dest> (the release files without terrain).
"""

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

from pipeline.de_area import prep_area, read_area_states, wgs84_bbox
from pipeline.de_buildings import prep_buildings
from pipeline.de_landscape import (LEISURE_AREAS, landscape_layers, pick, read_bdlm, write_facilities, write_layers,
                                   write_military)
from pipeline.de_protected import prep_protected
from pipeline.de_sources import BDLM_STATES, VG250_URL, fetch_vectors
from pipeline.de_terrain import tile_chunk
from pipeline.fetch.download import download
from pipeline.region import read_region_geojson
from pipeline.settings import data_paths, load_settings

RELEASE_FILES = ["region.geojson", "tiles.csv", "receptors.csv", "facilities.csv", "protected.gpkg",
                 "military.geojson", "states.gpkg"]
COLS = ["objektart", "klasse"]


def fetch(raw: Path, region_dir: Path, size_m: int) -> dict:
    """Download VG250 and write the area files, then download the other sources for the area's bounding box."""
    download(VG250_URL, raw / "vg250.zip", timeout=600)
    gpkg = raw / "vg250.gpkg"
    if not gpkg.exists():
        with zipfile.ZipFile(raw / "vg250.zip") as z:
            gpkg.write_bytes(z.read(next(n for n in z.namelist() if n.endswith(".gpkg"))))
    area = prep_area(gpkg, region_dir, size_m)
    return {"area": area, **fetch_vectors(raw, wgs84_bbox(read_region_geojson(region_dir / "region.geojson")))}


def prep(raw: Path, region_dir: Path, gpkg: Path) -> dict:
    """Write receptors.csv, facilities.csv, protected.gpkg, military.geojson and the slim GeoPackage *gpkg*."""
    region = read_region_geojson(region_dir / "region.geojson")
    bdlm = [raw / "bdlm" / f"{s}.gpkg" for s in BDLM_STATES]
    sied = read_bdlm(bdlm, "siedlungsflaeche_bdlm", COLS, region)
    gpkg.unlink(missing_ok=True)
    leisure = pick(sied, klasse=LEISURE_AREAS).geometry.to_numpy()
    stats = {"buildings": prep_buildings(raw / "hu", leisure, region, region_dir / "receptors.csv", gpkg)}
    layers = landscape_layers(sied, read_bdlm(bdlm, "vegetationsflaeche_bdlm", COLS, region),
                              read_bdlm(bdlm, "gewaesserflaeche_bdlm", COLS, region),
                              read_bdlm(bdlm, "verkehrslinie_bdlm", COLS, region))
    stats["layers"] = write_layers(layers, gpkg)
    stats["facilities"] = write_facilities(sied, region_dir / "facilities.csv")
    borders = read_bdlm(bdlm, "grenze_flaeche_bdlm", ["id", *COLS, "zone_name", "name"], region)
    stats["military"] = write_military(borders, region_dir / "military.geojson")
    thuringia = read_area_states(region_dir / "states.gpkg")["TH"]
    stats["protected"] = prep_protected(borders, raw / "eea", region, thuringia, region_dir / "protected.gpkg")
    return stats


def inputs(region_dir: Path, gpkg: Path, dest: Path) -> dict:
    """Copy the release files and the slim GeoPackage (as zabaged_slim.gpkg) into *dest*; return their sizes."""
    dest.mkdir(parents=True, exist_ok=True)
    for name in RELEASE_FILES:
        shutil.copy2(region_dir / name, dest / name)
    shutil.copy2(gpkg, dest / "zabaged_slim.gpkg")
    return {p.name: p.stat().st_size for p in sorted(dest.iterdir()) if p.is_file()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.germany")
    parser.add_argument("--settings", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch")
    sub.add_parser("prep")
    ter = sub.add_parser("terrain")
    ter.add_argument("tiles", nargs="+")
    ter.add_argument("--dest", required=True)
    sub.add_parser("inputs").add_argument("dest")
    args = parser.parse_args(argv)
    settings = load_settings(args.settings)
    paths = data_paths(settings)
    raw = paths["data_dir"] / "raw" / "de"
    reg = paths["out_dir"] / "region"
    if args.command == "fetch":
        res = fetch(raw, reg, settings["tiles"]["size_m"])
    elif args.command == "prep":
        res = prep(raw, reg, paths["zabaged"])
    elif args.command == "terrain":
        states = read_area_states(reg / "states.gpkg")
        res = {t: tile_chunk(t, states, Path(args.dest)) for t in args.tiles}
    else:
        res = inputs(reg, paths["zabaged"], Path(args.dest))
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
