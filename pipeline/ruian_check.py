"""RUIAN use-code analysis and ZABAGED purpose-area cross-check."""

import csv
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from shapely import contains_xy
from shapely.geometry import box

from pipeline.receptors import ROOT, classify, load_type_map

# ZABAGED purpose-area codes of interest
AREA_CODES = {
    "310": "camping",
    "312": "cottage colony",
    "313": "recreation area",
    "316": "allotment colony",
    "210": "school",
    "412": "hospital",
    "413": "health or social facility",
    "111": "livestock farm",
    "112": "farm, other",
}

CODE_COUNT_COLUMNS = [
    "use_code",
    "use_name",
    "number_type",
    "receptor_type",
    "unclear",
    "count",
]

AREA_COLUMNS = [
    "area_code",
    "area_name",
    "areas",
    "buildings",
    "home",
    "cottage",
    "ignore",
    "unclear",
]

CAMP_COLUMNS = [
    "fid_zbg",
    "name",
    "x",
    "y",
    "area_ha",
    "buildings_inside",
    "receptors_inside",
    "receptors_within_200m",
]

_NUMBER_TYPE_ORDER = {"cp": 0, "ce": 1, "none": 2}


def load_use_names(path=None) -> dict[int, str]:
    """Load use-code -> name mapping from *path* (default: ``config/receptor_types.csv``)."""
    target = path or ROOT / "config" / "receptor_types.csv"
    df = pd.read_csv(target)
    return dict(zip(df["code"], df["name"]))


def buildings_in_region(
    buildings_csv: Path,
    region,
    type_map: dict | None = None,
) -> pd.DataFrame:
    """Read *buildings_csv*, keep rows inside *region*, add receptor classification."""
    df = pd.read_csv(
        buildings_csv,
        dtype={"building_id": str, "number_type": str},
    )
    # Drop duplicate building_ids (keep first)
    df = df.drop_duplicates(subset="building_id", keep="first")

    # Drop rows with non-finite coordinates
    df = df[
        np.isfinite(df["x"]) & np.isfinite(df["y"])
    ].copy()

    # Keep only buildings inside the region
    inside = contains_xy(region, df["x"].values, df["y"].values)
    df = df[inside].copy()

    # use_code as nullable Int64; missing stays missing
    df["use_code"] = pd.array(df["use_code"], dtype="Int64")

    # Classify receptors
    tm = type_map if type_map is not None else load_type_map()
    results = [
        classify(int(uc) if pd.notnull(uc) else None, nt, tm)
        for uc, nt in zip(df["use_code"], df["number_type"])
    ]
    df["receptor_type"] = [r[0] for r in results]
    df["unclear"] = [r[1] for r in results]

    return df.reset_index(drop=True)


def code_counts(df: pd.DataFrame, names: dict[int, str]) -> list[dict]:
    """Count buildings grouped by (use_code, number_type, receptor_type, unclear)."""
    groups = df.groupby(
        ["use_code", "number_type", "receptor_type", "unclear"],
        dropna=False,
    ).size().reset_index(name="count")

    rows: list[dict] = []
    for _, row in groups.iterrows():
        uc = row["use_code"]
        use_name = names.get(int(uc), "") if pd.notnull(uc) else ""
        rows.append({
            "use_code": int(uc) if pd.notnull(uc) else None,
            "use_name": use_name,
            "number_type": row["number_type"],
            "receptor_type": row["receptor_type"],
            "unclear": bool(row["unclear"]),
            "count": int(row["count"]),
        })

    # Sort: use_code ascending (None last), then number_type in cp/ce/none order
    rows.sort(
        key=lambda r: (
            (0, r["use_code"]) if r["use_code"] is not None else (1, 0),
            _NUMBER_TYPE_ORDER.get(r["number_type"], 9),
        )
    )
    return rows


def read_areas(gpkg: Path, region) -> gpd.GeoDataFrame:
    """Read ZABAGED purpose areas from *gpkg*, filtered to *region*."""
    gdf = pyogrio.read_dataframe(
        gpkg,
        layer="ArealUceloveZastavby",
        bbox=tuple(region.bounds),
        columns=["fid_zbg", "jmeno", "typzast_k"],
    )
    gdf["typzast_k"] = gdf["typzast_k"].astype(str)
    # Keep only codes of interest
    gdf = gdf[gdf["typzast_k"].isin(AREA_CODES)].copy()
    # Keep only areas whose representative point is inside region
    reps = gdf.geometry.representative_point()
    inside = contains_xy(region, reps.x.values, reps.y.values)
    gdf = gdf[inside].copy()
    return gdf.reset_index(drop=True)


def area_check(df: pd.DataFrame, areas: gpd.GeoDataFrame) -> list[dict]:
    """Join building points to purpose areas and summarize by area code."""
    points_gdf = gpd.GeoDataFrame(
        df[["receptor_type", "unclear"]],
        geometry=gpd.points_from_xy(df["x"], df["y"], crs=areas.crs),
    )

    joined = gpd.sjoin(
        points_gdf,
        areas[["typzast_k", "geometry"]],
        predicate="within",
        how="inner",
    )

    rows: list[dict] = []
    for code, label in AREA_CODES.items():
        subset = joined[joined["typzast_k"] == code]
        rows.append({
            "area_code": int(code),
            "area_name": label,
            "areas": len(areas[areas["typzast_k"] == code]),
            "buildings": len(subset),
            "home": int((subset["receptor_type"] == "home").sum()),
            "cottage": int((subset["receptor_type"] == "cottage").sum()),
            "ignore": int((subset["receptor_type"] == "ignore").sum()),
            "unclear": int(subset["unclear"].sum()),
        })

    return rows


def campsites(
    df: pd.DataFrame,
    areas: gpd.GeoDataFrame,
    near_m: float = 200.0,
) -> list[dict]:
    """Analyse camping areas (code 310) for nearby receptors."""
    camp_areas = areas[areas["typzast_k"] == "310"].copy()

    all_home_cottage = df[df["receptor_type"].isin(["home", "cottage"])].copy()
    all_points = gpd.GeoDataFrame(
        all_home_cottage,
        geometry=gpd.points_from_xy(
            all_home_cottage["x"], all_home_cottage["y"], crs=areas.crs
        ),
    )

    rows: list[dict] = []
    for _, area in camp_areas.iterrows():
        fp = area.geometry.representative_point()
        buffer_geom = area.geometry.buffer(near_m)
        buildings_inside = int(contains_xy(
            area.geometry, df["x"].values, df["y"].values
        ).sum())
        receptors_inside = int(
            contains_xy(
                area.geometry, all_points["x"].values, all_points["y"].values
            ).sum()
        )
        receptors_within_200m = int(
            contains_xy(
                buffer_geom, all_points["x"].values, all_points["y"].values
            ).sum()
        )
        rows.append({
            "fid_zbg": int(area["fid_zbg"]),
            "name": area["jmeno"] if pd.notna(area["jmeno"]) else "",
            "x": fp.x,
            "y": fp.y,
            "area_ha": area.geometry.area / 1e4,
            "buildings_inside": buildings_inside,
            "receptors_inside": receptors_inside,
            "receptors_within_200m": receptors_within_200m,
        })

    return rows


def write_csv(rows: list[dict], columns: list[str], path: Path) -> None:
    """Write *rows* to CSV at *path* using *columns* as the header."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            out = {}
            for col in columns:
                val = row[col]
                if val is None:
                    out[col] = ""
                elif isinstance(val, float):
                    out[col] = repr(val)
                else:
                    out[col] = val
            writer.writerow(out)


def ruian_check(
    buildings_csv: Path,
    region,
    gpkg: Path,
    out_dir: Path,
) -> dict:
    """Run the full RUIAN check pipeline and write results to *out_dir*."""
    out_dir.mkdir(parents=True, exist_ok=True)

    type_map = load_type_map()
    use_names = load_use_names()

    df = buildings_in_region(buildings_csv, region, type_map)
    cc_rows = code_counts(df, use_names)
    areas = read_areas(gpkg, region)
    ac_rows = area_check(df, areas)
    cs_rows = campsites(df, areas)

    write_csv(cc_rows, CODE_COUNT_COLUMNS, out_dir / "code_counts.csv")
    write_csv(ac_rows, AREA_COLUMNS, out_dir / "area_check.csv")
    write_csv(cs_rows, CAMP_COLUMNS, out_dir / "campsites.csv")

    summary = {
        "buildings": len(df),
        "home": int((df["receptor_type"] == "home").sum()),
        "cottage": int((df["receptor_type"] == "cottage").sum()),
        "ignore": int((df["receptor_type"] == "ignore").sum()),
        "unclear": int(df["unclear"].sum()),
        "no_code": int(df["use_code"].isna().sum()),
        "campsites": len(cs_rows),
        "campsites_without_receptor_within_200m": sum(
            1 for r in cs_rows if r["receptors_within_200m"] == 0
        ),
    }

    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)

    return summary
