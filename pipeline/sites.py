"""Merge the website data of another area (the site data of its own tile run) into the Czech website data.

Every tile entry gets "area" ("cz" for the base data). Tiles of the added area get the id "<area>/<tile id>" and the
file tiles/<area>/<tile id>.bin.gz. Its protected sites are appended to the base list, so their indices in its tile
files move by the length of the base list; those files are written anew with the moved indices.

Run as `python -m pipeline.sites <base dir> <extra dir> --area <area>`; the base folder is changed in place.
"""

import argparse
import json
import sys
from pathlib import Path

from pipeline.de_sources import ATTRIBUTION as DE_ATTRIBUTION
from pipeline.pack import NO_SITE, read_tile, write_tile

BASE_AREA = "cz"
ATTRIBUTIONS = {"de-leipzig": DE_ATTRIBUTION}


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _save(obj, path: Path, **kw) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, **kw), encoding="utf-8")


def merge_sites(base_dir, extra_dir, area: str, attribution: str) -> dict:
    """Add the tiles and protected sites of *extra_dir* to the site data in *base_dir*; return the new totals."""
    base_dir, extra_dir = Path(base_dir), Path(extra_dir)
    index, extra = _load(base_dir / "index.json"), _load(extra_dir / "index.json")
    prot, extra_prot = _load(base_dir / index["protected_file"]), _load(extra_dir / extra["protected_file"])
    offset = len(prot["sites"])
    if offset + len(extra_prot["sites"]) >= NO_SITE:
        raise ValueError("too many protected sites for the tile format")
    tiles = [{**t, "area": t.get("area", BASE_AREA)} for t in index["tiles"]]
    for t in extra["tiles"]:
        entry = {**t, "id": f"{area}/{t['id']}", "area": area}
        if t["file"]:
            _, rec = read_tile(extra_dir / t["file"])
            rec = rec.copy()
            has = rec["sites"] != NO_SITE
            rec["sites"][has] += offset
            entry["file"] = f"tiles/{area}/{t['id']}.bin.gz"
            entry["bytes"] = write_tile(rec, base_dir / entry["file"])
        tiles.append(entry)
    index["tiles"] = sorted(tiles, key=lambda t: t["id"])
    index["attribution"] = f"{index['attribution']}; {attribution}"
    prot["sites"] = prot["sites"] + extra_prot["sites"]
    _save(prot, base_dir / index["protected_file"], separators=(",", ":"))
    _save(index, base_dir / "index.json", indent=1)
    added = [t for t in tiles if t["area"] == area]
    return {"tiles": len(tiles), "added_tiles": len(added), "added_spots": sum(t["spots"] for t in added),
            "sites": len(prot["sites"])}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.sites")
    parser.add_argument("base", help="site data folder to extend (index.json, protected.json, tiles/)")
    parser.add_argument("extra", help="site data folder of the added area")
    parser.add_argument("--area", required=True, choices=sorted(ATTRIBUTIONS))
    args = parser.parse_args(argv)
    print(json.dumps(merge_sites(args.base, args.extra, args.area, ATTRIBUTIONS[args.area])))
    return 0


if __name__ == "__main__":
    sys.exit(main())