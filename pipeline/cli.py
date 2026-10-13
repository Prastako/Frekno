"""Command-line interface for the Frekno pipeline."""

import argparse
import json
import sys
from pathlib import Path

from pipeline.settings import load_settings, data_paths
from pipeline.region import prep_region, prep_buildings, prep_receptors, prep_dem_index, read_region_geojson, load_receptors
from pipeline.dem import read_index_csv
from pipeline.facilities import prep_facilities
from pipeline.pack import pack_region
from pipeline.protected import prep_protected
from pipeline.details import tile_details
from pipeline.tile_screen import screen_tile
from pipeline.nm_tile import VARIANTS, nm_tile
from pipeline.ruian_check import ruian_check

COMMANDS = (
    "prep-region",
    "prep-buildings",
    "prep-receptors",
    "prep-facilities",
    "prep-protected",
    "prep-dem-index",
    "screen-tile",
    "nm-tile",
    "ruian-check",
    "pack",
    "tile-details",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline.cli")
    parser.add_argument("--settings", default=None)
    parser.add_argument("--out", default=None)

    subparsers = parser.add_subparsers(dest="command", required=True)

    # No-argument commands
    subparsers.add_parser("prep-region")
    subparsers.add_parser("prep-buildings")
    subparsers.add_parser("prep-receptors")
    subparsers.add_parser("prep-facilities")
    subparsers.add_parser("prep-protected")
    subparsers.add_parser("prep-dem-index")
    subparsers.add_parser("ruian-check")

    # screen-tile
    st = subparsers.add_parser("screen-tile")
    st.add_argument("tile")
    st.add_argument("--pairs", action="store_true")
    st.add_argument("--keep-dem", action="store_true")

    # nm-tile
    nt = subparsers.add_parser("nm-tile")
    nt.add_argument("tile")
    nt.add_argument("--variant", default="zabaged", choices=VARIANTS)
    nt.add_argument("--res", type=float, default=None)
    nt.add_argument("--n", type=int, default=None)
    nt.add_argument("--java-opts", default="")
    nt.add_argument("--timeout", type=float, default=None)

    # pack
    pk = subparsers.add_parser("pack")
    pk.add_argument("--screen-dir", default=None)
    pk.add_argument("--site-dir", default=None)

    # tile-details
    td = subparsers.add_parser("tile-details")
    td.add_argument("tile")
    td.add_argument("--screen-dir", default=None)

    return parser


def nm_dir_name(tile: str, variant: str, res_m: float) -> str:
    return f"{tile}_{variant}_{int(res_m)}m"


def run(args: argparse.Namespace) -> dict:
    settings = load_settings(args.settings)
    paths = data_paths(settings)
    out = Path(args.out) if args.out else paths["out_dir"]
    reg = out / "region"

    cmd = args.command

    if cmd == "prep-region":
        return prep_region(
            paths["stat_zip"],
            settings["region"]["ruian_vusc_code"],
            settings["tiles"]["size_m"],
            reg,
        )

    if cmd == "prep-buildings":
        return prep_buildings(
            sorted(paths["obce_dir"].glob("*.zip")),
            reg / "buildings.csv",
        )

    if cmd == "prep-receptors":
        return prep_receptors(
            reg / "buildings.csv",
            reg / "receptors.csv",
        )

    if cmd == "prep-facilities":
        return prep_facilities(
            paths["zabaged"],
            read_region_geojson(reg / "region.geojson"),
            settings["receptors"]["radius_m"],
            reg / "facilities.csv",
        )

    if cmd == "prep-dem-index":
        return prep_dem_index(
            paths["dmr_dir"],
            reg / "dem_index.csv",
        )

    if cmd == "screen-tile":
        return screen_tile(
            args.tile,
            settings,
            read_region_geojson(reg / "region.geojson"),
            read_index_csv(reg / "dem_index.csv"),
            paths["zabaged"],
            load_receptors(reg / "receptors.csv"),
            out / "tiles" / args.tile,
            write_pairs=args.pairs,
            keep_dem=args.keep_dem,
        )

    if cmd == "nm-tile":
        res = args.res if args.res is not None else settings["terrain"]["nm_resolution_m"]
        return nm_tile(
            args.tile,
            settings,
            read_index_csv(reg / "dem_index.csv"),
            paths["zabaged"],
            out / "tiles" / args.tile,
            out / "nm" / nm_dir_name(args.tile, args.variant, res),
            paths["nm_home"],
            paths["java"],
            variant=args.variant,
            res_m=res,
            n_cand=args.n,
            java_opts=args.java_opts,
            timeout_s=args.timeout,
        )

    if cmd == "ruian-check":
        return ruian_check(
            reg / "buildings.csv",
            read_region_geojson(reg / "region.geojson"),
            paths["zabaged"],
            out / "ruian",
        )

    if cmd == "prep-protected":
        return prep_protected(
            paths["data_dir"] / "raw" / "aopk" / "INSPIRE-PS_All.gml",
            reg / "protected.gpkg",
        )

    if cmd == "tile-details":
        return tile_details(
            args.tile,
            read_index_csv(reg / "dem_index.csv"),
            paths["zabaged"],
            reg / "protected.gpkg",
            Path(args.screen_dir) if args.screen_dir else out / "tiles" / args.tile,
        )

    if cmd == "pack":
        return pack_region(
            Path(args.screen_dir) if args.screen_dir else out / "tiles",
            Path(args.site_dir) if args.site_dir else out / "site",
            reg / "protected.gpkg",
            settings["receptors"]["worst_per_type_for_nm"],
        )

    raise ValueError(f"Unknown command: {cmd}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = run(args)
    print(json.dumps(result, default=str))
    return 1 if isinstance(result, dict) and result.get("ok") is False else 0


if __name__ == "__main__":
    sys.exit(main())
