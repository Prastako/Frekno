"""Tests for pipeline.de_protected (protected areas of the German area)."""

import json
import math

import geopandas as gpd
import pyogrio
import pytest
import shapely

from pipeline import de_protected as dp
from pipeline.de_area import SJTSK, circle


def borders():
    rows = [("A1", "Nationalpark", "Zone I", "Hainich"), ("A2", "Naturschutzgebiet", None, "Hohe Warte"),
            ("A3", "Landschaftsschutzgebiet", None, "LSG Loberaue"), ("A4", "Biosphärenreservat", "Kernzone", "Mittelelbe"),
            ("A5", "Biosphärenreservat", "Pflegezone", "Mittelelbe"), ("A6", "Naturpark", None, "Dübener Heide"),
            ("A7", "Truppenübungsplatz, Standortübungsplatz", None, "Altengrabow"), ("A8", "Naturdenkmal", None, None),
            ("A9", "Geschützter Landschaftsbestandteil", None, "GLB Hahnberg")]
    return gpd.GeoDataFrame({"id": [r[0] for r in rows], "klasse": [r[1] for r in rows], "zone_name": [r[2] for r in rows],
                             "name": [r[3] for r in rows]},
                            geometry=[shapely.box(k, 0, k + 1, 1) for k in range(len(rows))], crs=SJTSK)


def geojson(path, features):
    """Write an EEA-like GeoJSON answer: features = (properties, lon0, lat0, lon1, lat1)."""
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": p, "geometry": shapely.geometry.mapping(shapely.box(a, b, c, d))}
        for p, a, b, c, d in features]}
    path.write_text(json.dumps(fc), encoding="utf-8")
    return path


def test_label():
    assert dp.label("LSG", "LSG Loberaue") == "LSG Loberaue"
    assert dp.label("LSG", "Saaletal") == "LSG Saaletal"
    assert dp.label("LSG", "LSGfeld") == "LSG LSGfeld"
    assert dp.label("ND", None) == "ND"
    assert dp.label("ND", "  ") == "ND"
    assert dp.label("NSG", math.nan) == "NSG"


def test_bdlm_sites():
    got = dp.bdlm_sites(borders())
    assert got[["site_id", "category", "name"]].values.tolist() == [
        ["DE-A1", "np", "NLP Hainich"], ["DE-A2", "zchu", "NSG Hohe Warte"], ["DE-A3", "chko", "LSG Loberaue"],
        ["DE-A4", "zchu", "BR Mittelelbe (Kernzone)"], ["DE-A5", "chko", "BR Mittelelbe"], ["DE-A8", "zchu", "ND"],
        ["DE-A9", "zchu", "GLB Hahnberg"]]
    assert got.crs.to_string() == SJTSK


def test_eea_sites_keep_and_cut(tmp_path):
    path = geojson(tmp_path / "ffh.geojson", [({"SITECODE": "DE4639301", "SITENAME": "Leipziger Auensystem"}, 12.30, 51.30, 12.45, 51.38),
                                              ({"SITECODE": "DE8034371", "SITENAME": "Ammersee"}, 11.1, 47.9, 11.2, 48.0)])
    within = circle(12.3747, 51.3406, 3000.0)
    got = dp.eea_sites(path, "evl", "FFH", "SITECODE", "SITENAME", within)
    assert got[["site_id", "category", "name"]].values.tolist() == [["DE-DE4639301", "evl", "FFH Leipziger Auensystem"]]
    assert got.geometry.iloc[0].area > within.area
    cut = dp.eea_sites(path, "evl", "FFH", "SITECODE", "SITENAME", within, clip=True)
    assert cut.geometry.iloc[0].area == pytest.approx(within.area, rel=1e-6)


def test_prep_protected(tmp_path):
    eea = tmp_path / "eea"
    eea.mkdir()
    near = (12.30, 51.30, 12.45, 51.38)
    geojson(eea / "ffh.geojson", [({"SITECODE": "DE4639301", "SITENAME": "Auensystem"}, *near)])
    geojson(eea / "spa.geojson", [({"SITECODE": "DE4639451", "SITENAME": "Leipziger Auwald"}, *near),
                                  ({"SITECODE": "DE4639451", "SITENAME": "Leipziger Auwald"}, *near)])
    geojson(eea / "lsg.geojson", [({"natDAId": 555774777, "siteName": "Chemnitzaue"}, *near), ({"natDAId": 1, "siteName": "Weit"}, 11.0, 48.0, 11.1, 48.1)])
    region = circle(12.3747, 51.3406, 3000.0)
    b = borders()
    b["geometry"] = [region.centroid.buffer(100.0)] * len(b)
    stats = dp.prep_protected(b, eea, region, region.buffer(-1000.0), tmp_path / "protected.gpkg")
    got = pyogrio.read_dataframe(tmp_path / "protected.gpkg", layer="protected")
    assert got["site_id"].tolist() == sorted(got["site_id"]) and got["site_id"].is_unique
    assert stats == {"sites": 10, "np": 1, "chko": 3, "zchu": 4, "evl": 1, "po": 1}
    lsg = got[got["site_id"] == "DE-555774777"]
    assert lsg["name"].iloc[0] == "LSG Chemnitzaue"
    assert lsg.geometry.iloc[0].area == pytest.approx(region.buffer(-1000.0).area, rel=1e-3)