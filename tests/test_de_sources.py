"""Tests for pipeline.de_sources (download links and downloads of the German area)."""

import json

import pytest

from pipeline import de_sources

LISTING = """<a href="basisviews_bdlm_BB_EPSG4326_2026-10-13.gpkg">a</a>
<a href="basisviews_bdlm_BB_EPSG4326_2026-10-14.gpkg">b</a>
<a href="basisviews_bdlm_SN_EPSG4326_2026-10-14.gpkg">c</a>
<a href="basisviews_bdlm_ST_EPSG4326_2026-10-12.gpkg">d</a>
<a href="basisviews_bdlm_TH_EPSG4326_2026-10-14.gpkg">e</a>
<a href="basisviews_bdlm_BY_EPSG4326_2026-10-14.gpkg">f</a>"""


class Answer:
    """Stand-in for a requests response."""

    def __init__(self, data=None, text=""):
        self.data, self.text = data, text
        self.content = json.dumps(data).encode() if data is not None else text.encode()

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def test_bdlm_urls_newest_file_per_state():
    urls = de_sources.bdlm_urls(LISTING)
    assert list(urls) == ["BB", "SN", "ST", "TH"]
    assert urls["BB"] == de_sources.BDLM_LIST_URL + "basisviews_bdlm_BB_EPSG4326_2026-10-14.gpkg"
    assert urls["ST"].endswith("/basisviews_bdlm_ST_EPSG4326_2026-10-12.gpkg")


def test_bdlm_urls_missing_state():
    with pytest.raises(ValueError, match="TH"):
        de_sources.bdlm_urls(LISTING.replace("_TH_", "_XX_"))


def test_query_params():
    p = de_sources.query_params("MS='DE'", (10.5, 50.2, 14.2, 52.5), "SITECODE,SITENAME")
    assert p["geometry"] == "10.5,50.2,14.2,52.5"
    assert (p["where"], p["outFields"], p["f"], p["inSR"], p["outSR"]) == ("MS='DE'", "SITECODE,SITENAME", "geojson", "4326", "4326")
    assert (p["geometryType"], p["spatialRel"], p["returnGeometry"]) == ("esriGeometryEnvelope", "esriSpatialRelIntersects", "true")


def test_query_geojson_saves_the_answer(tmp_path, monkeypatch):
    data = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"a": k}, "geometry": None} for k in range(3)]}
    monkeypatch.setattr(de_sources.requests, "get", lambda url, params=None, timeout=None: Answer(data))
    dest = tmp_path / "eea" / "x.geojson"
    assert de_sources.query_geojson("https://example.org/q", {}, dest) == 3
    assert json.loads(dest.read_text(encoding="utf-8")) == data


def test_query_geojson_refuses_an_error_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(de_sources.requests, "get", lambda url, params=None, timeout=None: Answer({"error": {"code": 400}}))
    with pytest.raises(ValueError, match="no features"):
        de_sources.query_geojson("https://example.org/q", {}, tmp_path / "y.geojson")
    assert not (tmp_path / "y.geojson").exists()


def test_fetch_vectors_downloads_every_source(tmp_path, monkeypatch):
    got, asked = [], []
    monkeypatch.setattr(de_sources, "download", lambda url, dest, timeout=None: got.append((url, dest.relative_to(tmp_path).as_posix())))

    def fake_get(url, params=None, timeout=None):
        if params is None:
            return Answer(text=LISTING)
        asked.append((url, params["where"]))
        return Answer({"features": [{}, {}]})

    monkeypatch.setattr(de_sources.requests, "get", fake_get)
    stats = de_sources.fetch_vectors(tmp_path, (10.5, 50.2, 14.2, 52.5))
    dests = [d for _, d in got]
    assert dests == ["vg250.zip", "bdlm/BB.gpkg", "bdlm/SN.gpkg", "bdlm/ST.gpkg", "bdlm/TH.gpkg", "hu/SN.zip", "hu/ST.zip",
                     "hu/TH.zip", "hu/BB_brb.zip", "hu/BB_ee.zip", "hu/BB_lds.zip", "hu/BB_osl.zip", "hu/BB_pm.zip", "hu/BB_tf.zip"]
    assert got[0][0] == de_sources.VG250_URL
    assert got[8][0] == de_sources.BB_ALKIS_URL.format("brb")
    assert [w for _, w in asked] == ["MS='DE'", "MS='DE'", "countryCode='DE' AND designationTypeCode='DE07'"]
    assert asked[1][0] == de_sources.N2K_URL.format(layer=1)
    assert (stats["ffh"], stats["spa"], stats["lsg"]) == (2, 2, 2)
    assert stats["bdlm"]["SN"] == "basisviews_bdlm_SN_EPSG4326_2026-10-14.gpkg"