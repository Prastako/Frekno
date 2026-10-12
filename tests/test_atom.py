"""Tests for pipeline.fetch.atom."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.fetch.atom import parse_service_feed, parse_dataset_feed, sheets_in_bbox, zip_url

FIXTURES = Path(__file__).resolve().parent / "fixtures"

SERVICE_EXCERPT = FIXTURES / "atom_dmr4g_service_excerpt.xml"
DATASET_BENE09 = FIXTURES / "atom_dmr4g_dataset_BENE09.xml"


class TestParseServiceFeed:
    def test_sheet_count(self):
        sheets, problems = parse_service_feed(SERVICE_EXCERPT)
        assert len(sheets) == 10
        assert len(problems) == 0

    def test_first_sheet(self):
        sheets, _ = parse_service_feed(SERVICE_EXCERPT)
        first = sheets[0]
        assert first["code"] == "BENE09"
        assert first["lat_min"] == pytest.approx(49.7764, abs=1e-4)
        assert first["lat_max"] == pytest.approx(49.7972, abs=1e-4)
        assert first["lon_min"] == pytest.approx(14.6982, abs=1e-4)
        assert first["lon_max"] == pytest.approx(14.7363, abs=1e-4)
        assert first["dataset_feed_url"] == (
            "https://atom.cuzk.gov.cz/DMR4G-SJTSK-TIFF/datasetFeeds/"
            "CZ-00025712-CUZK_DMR4G-SJTSK-TIFF_BENE09.xml"
        )

    def test_missing_polygon_skipped(self, tmp_path):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:georss="http://www.georss.org/georss" '
            'xmlns:inspire_dls="http://inspire.ec.europa.eu/schemas/inspire_dls/1.0">\n'
            '  <entry>\n'
            '    <id>http://example.org/entry1</id>\n'
            '    <title>Test Entry</title>\n'
            '    <link rel="alternate" href="http://example.org/feed.xml"/>\n'
            '    <inspire_dls:spatial_dataset_identifier_code>'
            'CZ-00025712-CUZK_DMR4G-SJTSK-TIFF_TEST01'
            '</inspire_dls:spatial_dataset_identifier_code>\n'
            '  </entry>\n'
            '</feed>'
        )
        test_file = tmp_path / "no_polygon.xml"
        test_file.write_text(xml, encoding="utf-8")
        sheets, problems = parse_service_feed(test_file)
        assert len(sheets) == 0
        assert len(problems) == 1


class TestSheetsInBBox:
    def test_berou_bbox(self):
        sheets, _ = parse_service_feed(SERVICE_EXCERPT)
        result = sheets_in_bbox(sheets, 14.30, 49.95, 14.34, 49.97)
        codes = [s["code"] for s in result]
        assert codes == ["BERO07", "BERO08", "BERO17", "BERO18"]


class TestParseDatasetFeed:
    def test_bene09(self):
        results = parse_dataset_feed(DATASET_BENE09)
        assert len(results) == 1
        assert results[0]["url"] == (
            "https://openzu.cuzk.gov.cz/opendata/DMR4G-TIFF/epsg-5514/BENE09.zip"
        )
        assert results[0]["length"] == 768908
        assert results[0]["type"] == "image/tiff"


class TestZipUrl:
    def test_default_template(self):
        url = zip_url("BENE09")
        assert url == "https://openzu.cuzk.gov.cz/opendata/DMR4G-TIFF/epsg-5514/BENE09.zip"
