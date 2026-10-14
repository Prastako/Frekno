"""Land cover, roads, facilities and military areas of the German area from the Basis-DLM (basemap.de basisviews).

The tile run reads ZABAGED layer names (pipeline/landcover.py CLASSES, pipeline/details.py ROAD_LAYERS and
TRACK_LAYERS), so Basis-DLM features are written to the slim GeoPackage under those names, with the codes the
pipeline filters on. Facilities use the ZABAGED codes of pipeline/facilities.py.
"""

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import shapely

from pipeline.de_area import SJTSK, to_sjtsk, wgs84_bbox
from pipeline.facilities import facility_rows
from pipeline.receptors import write_receptors_csv
from pipeline.region import write_region_geojson

GREEN = ("Park", "Grünanlage", "Garten", "Kleingarten")  # sport and leisure areas that stay soft ground
COMPOUND = ("IndustrieUndGewerbeflaeche", "FlaecheBesondererFunktionalerPraegung", "SportFreizeitUndErholungsflaeche")
SETTLEMENT = ("Wohnbauflaeche", "FlaecheGemischterNutzung")
QUARRY = ("TagebauGrubeSteinbruch", "Halde", "Bergbaubetrieb")
WATER = ("StehendesGewaesser", "Fliessgewaesser", "Hafenbecken", "Meer")
ROAD_CLASSES = {"Bundesstraße": "S1", "Landesstraße, Staatsstraße": "S2", "Kreisstraße": "S3"}
LOCAL_ROADS = ("Gemeindestraße", "Sonstige öffentliche Straße", "Nicht öffentliche Straße")
TRACKS = ("Hauptwirtschaftsweg", "Wirtschaftsweg")
AXES = ("Strassenachse", "Fahrbahnachse")
FACILITY_CODES = {"Campingplatz": "310", "Gesundheit, Kur": "412", "Soziales": "413", "Wochenend- und Ferienhausfläche": "313"}
LEISURE_AREAS = ("Wochenend- und Ferienhausfläche", "Kleingarten")
MILITARY = "Truppenübungsplatz, Standortübungsplatz"
EMPTY_LAYERS = {"KulnaSklenikFoliovnikPristresek": ("Polygon", []), "ParkovisteOdpocivka": ("Polygon", []),
                "Ulice": ("LineString", ["typulice_k"])}


def read_bdlm(paths: list, layer: str, columns: list, region) -> gpd.GeoDataFrame:
    """Features of *layer* from the Basis-DLM GeoPackages *paths* that touch *region*, in S-JTSK."""
    bbox = wgs84_bbox(region)
    parts = []
    for p in paths:
        df = pyogrio.read_dataframe(p, layer=layer, columns=columns, bbox=bbox)
        if len(df):
            df = df.set_geometry(to_sjtsk(df.geometry.to_numpy(), "EPSG:4326"), crs=SJTSK)
            parts.append(df[df.intersects(region)])
    if not parts:
        return gpd.GeoDataFrame({c: [] for c in columns}, geometry=[], crs=SJTSK)
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs=SJTSK)


def pick(df, objektart=None, klasse=None, not_klasse=()) -> gpd.GeoDataFrame:
    """Rows of *df* whose objektart is in *objektart* and klasse in *klasse* (None = any), klasse not in *not_klasse*."""
    keep = ~df["klasse"].isin(list(not_klasse))
    if objektart is not None:
        keep &= df["objektart"].isin(list(objektart))
    if klasse is not None:
        keep &= df["klasse"].isin(list(klasse))
    return df[keep]


def geoms(df, **cols) -> gpd.GeoDataFrame:
    """Only the geometry of *df*, plus constant columns given as name=value."""
    out = gpd.GeoDataFrame(geometry=df.geometry.reset_index(drop=True), crs=SJTSK)
    for k, v in cols.items():
        out[k] = v
    return out


def landscape_layers(siedlung, vegetation, water, traffic) -> dict:
    """{ZABAGED layer name: GeoDataFrame} from the Basis-DLM layers (each with columns objektart and klasse)."""
    roads = pick(traffic, objektart=AXES, klasse=list(ROAD_CLASSES))
    return {
        "VodniPlocha": geoms(pick(water, objektart=WATER)),
        "ArealUceloveZastavby": geoms(pick(siedlung, objektart=COMPOUND, not_klasse=GREEN)),
        "OstatniPlochaVSidlech": geoms(pick(siedlung, objektart=SETTLEMENT)),
        "Hrbitov": geoms(pick(siedlung, objektart=["Friedhof"])),
        "PovrchovaTezbaLom": geoms(pick(siedlung, objektart=QUARRY)),
        "LesniPudaSeStromy": geoms(pick(vegetation, objektart=["Wald"])),
        "LesniPudaSKrovinatymPorostem": geoms(pick(vegetation, objektart=["Gehoelz"])),
        "SilniceDalnice": gpd.GeoDataFrame({"typsil_k": roads["klasse"].map(ROAD_CLASSES).to_numpy()},
                                           geometry=roads.geometry.reset_index(drop=True), crs=SJTSK),
        "SilniceNeevidovana": geoms(pick(traffic, objektart=AXES, klasse=LOCAL_ROADS)),
        "Cesta": geoms(pick(traffic, objektart=["Fahrwegachse"], klasse=TRACKS), typcesty_k="026"),
    }


def write_layers(layers: dict, gpkg) -> dict:
    """Write *layers* and the EMPTY_LAYERS to the GeoPackage *gpkg* (EPSG:5514); return feature counts."""
    gpkg = Path(gpkg)
    gpkg.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, gdf in layers.items():
        pyogrio.write_dataframe(gdf, gpkg, layer=name, driver="GPKG", promote_to_multi=True)
        counts[name] = len(gdf)
    for name, (gtype, cols) in EMPTY_LAYERS.items():
        empty = gpd.GeoDataFrame({c: pd.Series(dtype=str) for c in cols}, geometry=gpd.GeoSeries([], crs=SJTSK))
        pyogrio.write_dataframe(empty, gpkg, layer=name, driver="GPKG", geometry_type=gtype)
        counts[name] = 0
    return counts


def write_facilities(siedlung, out_csv) -> dict:
    """Receptor rows along the edges of campsites, health and social areas and weekend-house areas (FACILITY_CODES)."""
    areas = pick(siedlung, klasse=list(FACILITY_CODES)).reset_index(drop=True)
    areas = gpd.GeoDataFrame({"fid_zbg": range(1, len(areas) + 1), "typzast_k": areas["klasse"].map(FACILITY_CODES)},
                             geometry=areas.geometry, crs=SJTSK)
    rows = facility_rows(areas)
    for r in rows:
        r["building_id"] = "de" + r["building_id"]
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    write_receptors_csv(rows, out_csv)
    return {"areas": len(areas), "points": len(rows), **{k: int((areas["typzast_k"] == c).sum()) for k, c in FACILITY_CODES.items()}}


def write_military(borders, path) -> int:
    """Write the military training areas among the Basis-DLM borders as one GeoJSON feature; return how many."""
    mil = pick(borders, objektart=["SonstigesRecht"], klasse=[MILITARY])
    write_region_geojson(shapely.union_all(mil.geometry.to_numpy()), path)
    return len(mil)