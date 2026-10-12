"""Read RUIAN building points and region outlines from ČÚZK SHP downloads."""

import csv
import math
import pathlib
import zipfile
from typing import Any

import pyogrio
import shapely
from pipeline.receptors import number_type_from_text

BUILDING_COLUMNS = ["building_id", "use_code", "number_type", "x", "y", "obec"]


def vsizip(zip_path: pathlib.Path | str, inner: str) -> str:
    """Build a GDAL /vsizip/ path for reading a member inside a ZIP."""
    return "/vsizip/" + pathlib.Path(zip_path).resolve().as_posix() + "/" + inner


def read_region(stat_zip: pathlib.Path | str, vusc_kod: int | str) -> shapely.geometry.base.BaseGeometry:
    """Read region polygon from a state SHP ZIP.

    Returns the geometry of the row whose KOD equals *vusc_kod*.
    Raises ValueError if no row or more than one row matches.
    """
    member = vsizip(stat_zip, "1/VUSC_P.shp")
    gdf = pyogrio.read_dataframe(member, encoding="cp1250")

    target = str(int(vusc_kod))
    matches = []
    for _, row in gdf.iterrows():
        if str(row["KOD"]).strip() == target:
            matches.append(row["geometry"])

    if len(matches) == 0:
        raise ValueError(f"No region with KOD {vusc_kod!r}")
    if len(matches) > 1:
        raise ValueError(f"Multiple regions with KOD {vusc_kod!r}")
    return matches[0]


def so_b_member(zip_path: pathlib.Path | str) -> str:
    """Find the single SO_B.shp member in a municipality ZIP.

    Returns the member path like '<folder>/SO_B.shp'.
    Raises ValueError if none or more than one is found.
    """
    with zipfile.ZipFile(zip_path) as zf:
        candidates = [m for m in zf.namelist() if "/SO_B.shp" in m and m.count("/") == 1]

    if len(candidates) == 0:
        raise ValueError("No SO_B.shp member found in ZIP")
    if len(candidates) > 1:
        raise ValueError("Multiple SO_B.shp members found in ZIP")
    return candidates[0]


def read_obec_buildings(zip_path: pathlib.Path | str) -> list[dict[str, Any]]:
    """Read building points from a municipality ZIP.

    Returns one dict per row in file order with keys from BUILDING_COLUMNS.
    """
    member = so_b_member(zip_path)
    folder_name = member.split("/")[0]
    obec = int(folder_name)

    gdf = pyogrio.read_dataframe(vsizip(zip_path, member), encoding="cp1250")

    rows: list[dict[str, Any]] = []
    for _, row in gdf.iterrows():
        zpv = row.get("ZPVY_KOD")
        use_code: int | None = None
        if zpv is not None and not (isinstance(zpv, float) and math.isnan(zpv)):
            use_code = int(zpv)

        geom = row["geometry"]
        rows.append({
            "building_id": str(int(row["KOD"])),
            "use_code": use_code,
            "number_type": number_type_from_text(row.get("TEXT")),
            "x": float(geom.x),
            "y": float(geom.y),
            "obec": obec,
        })
    return rows


def write_buildings_csv(rows: list[dict[str, Any]], path: pathlib.Path | str, append: bool = False) -> None:
    """Write building rows to a CSV file.

    When *append* is False the file is overwritten.
    When *append* is True rows are added; the header is written only
    when the file is new or empty.
    """
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    file_exists = path.exists() and path.stat().st_size > 0

    mode = "a" if append else "w"
    with open(path, mode, encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        if not (append and file_exists):
            writer.writerow(BUILDING_COLUMNS)
        for r in rows:
            writer.writerow([
                r["building_id"],
                r["use_code"] if r["use_code"] is not None else "",
                r["number_type"],
                repr(r["x"]),
                repr(r["y"]),
                r["obec"],
            ])
