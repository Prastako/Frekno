"""Protected areas of the German area as one GeoPackage layer in S-JTSK (columns as in pipeline/protected.py).

Sources: the Basis-DLM borders (national parks, nature reserves, natural monuments, protected landscape features,
Landschaftsschutzgebiete, biosphere reserves), the EEA's Natura 2000 sites (habitats directive sites and bird
areas) and, for Thuringia, whose Basis-DLM has no Landschaftsschutzgebiete, the EEA's nationally designated areas.
Site ids start with "DE-"; names start with the German type (the website shows them without a category word).
"""

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

from pipeline.de_area import SJTSK, to_sjtsk

BDLM_TYPES = {  # Basis-DLM klasse -> (category, type label)
    "Nationalpark": ("np", "NLP"),
    "Naturschutzgebiet": ("zchu", "NSG"),
    "Nationales Naturmonument": ("zchu", "NNM"),
    "Naturdenkmal": ("zchu", "ND"),
    "Geschützter Landschaftsbestandteil": ("zchu", "GLB"),
    "Landschaftsschutzgebiet": ("chko", "LSG"),
    "Biosphärenreservat": ("chko", "BR"),
}
CORE_ZONE = "Kernzone"  # a biosphere reserve's core zone counts as a reserve
COLUMNS = ["site_id", "category", "name", "geometry"]


def label(kind: str, name) -> str:
    """'<kind> <name>', without repeating a kind the name already starts with; the kind alone without a name."""
    name = "" if name is None or pd.isna(name) else str(name).strip()
    if not name:
        return kind
    return name if name.startswith(kind + " ") else f"{kind} {name}"


def bdlm_sites(borders: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Sites from the Basis-DLM layer grenze_flaeche_bdlm (columns id, klasse, zone_name, name; S-JTSK)."""
    rows = []
    for sid, kl, zone, name, geom in zip(borders["id"], borders["klasse"], borders["zone_name"], borders["name"], borders.geometry):
        if kl not in BDLM_TYPES:
            continue
        cat, kind = BDLM_TYPES[kl]
        text = label(kind, name)
        if kl == "Biosphärenreservat" and zone == CORE_ZONE:
            cat, text = "zchu", f"{text} ({CORE_ZONE})"
        rows.append({"site_id": f"DE-{sid}", "category": cat, "name": text, "geometry": geom})
    return gpd.GeoDataFrame(rows, columns=COLUMNS, geometry="geometry", crs=SJTSK)


def eea_sites(geojson, category: str, kind: str, id_field: str, name_field: str, within, clip: bool = False) -> gpd.GeoDataFrame:
    """Sites from an EEA GeoJSON answer (WGS84) that touch *within*, in S-JTSK; with *clip*, only their parts inside it."""
    df = pyogrio.read_dataframe(geojson)
    geom = to_sjtsk(df.geometry.to_numpy(), "EPSG:4326")
    out = gpd.GeoDataFrame({"site_id": [f"DE-{v}" for v in df[id_field]], "category": category,
                            "name": [label(kind, v) for v in df[name_field]]}, geometry=geom, crs=SJTSK)
    out = out[out.intersects(within)].copy()
    if clip:
        out["geometry"] = out.geometry.intersection(within)
    return out[COLUMNS].reset_index(drop=True)


def prep_protected(borders, eea_dir, region, thuringia, out_gpkg) -> dict:
    """Write all German sites that touch *region* to *out_gpkg* (layer 'protected'); return counts per category.

    *eea_dir* holds ffh.geojson, spa.geojson and lsg.geojson (pipeline/de_sources.py); *thuringia* is Thuringia's part
    of the region, where the EEA's Landschaftsschutzgebiete are used (cut to it).
    """
    eea_dir = Path(eea_dir)
    parts = [bdlm_sites(borders),
             eea_sites(eea_dir / "ffh.geojson", "evl", "FFH", "SITECODE", "SITENAME", region),
             eea_sites(eea_dir / "spa.geojson", "po", "SPA", "SITECODE", "SITENAME", region),
             eea_sites(eea_dir / "lsg.geojson", "chko", "LSG", "natDAId", "siteName", thuringia, clip=True)]
    gdf = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs=SJTSK)
    gdf = gdf.drop_duplicates("site_id").sort_values("site_id", kind="stable").reset_index(drop=True)
    Path(out_gpkg).parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out_gpkg, layer="protected", driver="GPKG")
    return {"sites": len(gdf), **{c: int((gdf["category"] == c).sum()) for c in ("np", "chko", "zchu", "evl", "po")}}