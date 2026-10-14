"""Tests for pipeline.de_landscape (Basis-DLM land cover, roads, facilities and military areas)."""

import geopandas as gpd
import pandas as pd
import pyogrio
import pytest
import shapely
from pyproj import Transformer

from pipeline import de_landscape as dl
from pipeline.de_area import SJTSK, circle
from pipeline.region import read_region_geojson

TO_SJTSK = Transformer.from_crs("EPSG:4326", SJTSK, always_xy=True)


def frame(rows, lines=False):
    """GeoDataFrame in S-JTSK with columns objektart and klasse, one 100 m square (or line) per row."""
    geoms = [shapely.LineString([(k * 200, 0), (k * 200 + 100, 0)]) if lines else shapely.box(k * 200, 0, k * 200 + 100, 100)
             for k in range(len(rows))]
    return gpd.GeoDataFrame({"objektart": [r[0] for r in rows], "klasse": [r[1] for r in rows]}, geometry=geoms, crs=SJTSK)


SIEDLUNG = [("IndustrieUndGewerbeflaeche", "Industrie und Gewerbe"), ("SportFreizeitUndErholungsflaeche", "Park"),
            ("SportFreizeitUndErholungsflaeche", "Sportanlage"), ("Wohnbauflaeche", "Wohnbaufläche"),
            ("Friedhof", "Friedhof"), ("TagebauGrubeSteinbruch", "Tagebau, Grube, Steinbruch"), ("Halde", "Halde"),
            ("SportFreizeitUndErholungsflaeche", "Campingplatz"), ("FlaecheBesondererFunktionalerPraegung", "Soziales"),
            ("SportFreizeitUndErholungsflaeche", "Wochenend- und Ferienhausfläche")]
TRAFFIC = [("Strassenachse", "Bundesautobahn"), ("Strassenachse", "Bundesstraße"), ("Fahrbahnachse", "Kreisstraße"),
           ("Strassenachse", "Gemeindestraße"), ("Fahrwegachse", "Wirtschaftsweg"), ("WegPfadSteig", "Fußweg"),
           ("Bahnstrecke", "Eisenbahn")]


def layers():
    return dl.landscape_layers(frame(SIEDLUNG), frame([("Wald", "Laubholz"), ("Gehoelz", "Gehölz"), ("Landwirtschaft", "Ackerland")]),
                               frame([("StehendesGewaesser", "See"), ("Gewaessermerkmal", "Quelle")]), frame(TRAFFIC, lines=True))


def test_pick():
    df = frame(SIEDLUNG)
    assert len(dl.pick(df, objektart=["SportFreizeitUndErholungsflaeche"])) == 4
    assert len(dl.pick(df, objektart=["SportFreizeitUndErholungsflaeche"], not_klasse=["Park"])) == 3
    assert list(dl.pick(df, klasse=["Halde", "Friedhof"])["objektart"]) == ["Friedhof", "Halde"]


def test_landscape_layers():
    got = layers()
    counts = {k: len(v) for k, v in got.items()}
    assert counts == {"VodniPlocha": 1, "ArealUceloveZastavby": 5, "OstatniPlochaVSidlech": 1, "Hrbitov": 1,
                      "PovrchovaTezbaLom": 2, "LesniPudaSeStromy": 1, "LesniPudaSKrovinatymPorostem": 1, "SilniceDalnice": 2,
                      "SilniceNeevidovana": 1, "Cesta": 1}
    assert list(got["SilniceDalnice"]["typsil_k"]) == ["S1", "S3"]
    assert list(got["Cesta"]["typcesty_k"]) == ["026"]
    assert all(v.crs.to_string() == SJTSK for v in got.values())


def test_write_layers(tmp_path):
    gpkg = tmp_path / "slim.gpkg"
    counts = dl.write_layers(layers(), gpkg)
    names = dict(pyogrio.list_layers(gpkg).tolist())
    assert set(names) == {*layers(), "KulnaSklenikFoliovnikPristresek", "ParkovisteOdpocivka", "Ulice"}
    assert counts["Ulice"] == 0 and counts["SilniceDalnice"] == 2
    assert "typulice_k" in pyogrio.read_info(gpkg, layer="Ulice")["fields"]
    assert pyogrio.read_dataframe(gpkg, layer="SilniceDalnice")["typsil_k"].tolist() == ["S1", "S3"]
    assert pyogrio.read_info(gpkg, layer="VodniPlocha")["crs"] == SJTSK


def test_write_facilities(tmp_path):
    out = tmp_path / "facilities.csv"
    stats = dl.write_facilities(frame(SIEDLUNG), out)
    assert stats == {"areas": 3, "points": 24, "Campingplatz": 1, "Gesundheit, Kur": 0, "Soziales": 1,
                     "Wochenend- und Ferienhausfläche": 1}
    rows = pd.read_csv(out, dtype={"building_id": str})
    assert rows["receptor_type"].value_counts().to_dict() == {"campsite": 8, "care": 8, "recreation": 8}
    assert rows["building_id"].iloc[0] == "dezbg1_0"
    assert sorted(rows["use_code"].unique()) == [310, 313, 413]


def test_write_military(tmp_path):
    borders = frame([("SonstigesRecht", dl.MILITARY), ("NaturUmweltOderBodenschutzrecht", "Naturschutzgebiet"),
                     ("SonstigesRecht", dl.MILITARY)])
    assert dl.write_military(borders, tmp_path / "military.geojson") == 2
    assert read_region_geojson(tmp_path / "military.geojson").area == pytest.approx(2 * 100 * 100)


def test_read_bdlm_keeps_the_region_in_sjtsk(tmp_path):
    rows = [("Wald", "Laubholz", shapely.box(12.37, 51.33, 12.38, 51.34)), ("Wald", "Laubholz", shapely.box(11.0, 48.0, 11.01, 48.01))]
    gdf = gpd.GeoDataFrame({"objektart": [r[0] for r in rows], "klasse": [r[1] for r in rows]}, geometry=[r[2] for r in rows],
                           crs="EPSG:4326")
    gpkg = tmp_path / "TH.gpkg"
    gdf.to_file(gpkg, layer="vegetationsflaeche_bdlm", driver="GPKG")
    got = dl.read_bdlm([gpkg], "vegetationsflaeche_bdlm", ["objektart", "klasse"], circle(12.3747, 51.3406, 5000.0))
    assert len(got) == 1 and got.crs.to_string() == SJTSK
    x, y = TO_SJTSK.transform(12.375, 51.335)
    assert got.geometry.iloc[0].contains(shapely.Point(x, y))
    assert dl.read_bdlm([gpkg], "vegetationsflaeche_bdlm", ["objektart", "klasse"], circle(15.0, 50.0, 1000.0)).empty