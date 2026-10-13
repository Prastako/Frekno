"""Tests for pipeline.protected."""

import xml.etree.ElementTree as ET

from pipeline.protected import CATEGORIES, NS, site_category


def test_categories_mapping():
    assert CATEGORIES["protectedLandscapeArea"] == "chko"
    assert CATEGORIES["natureReserve"] == "zchu"


def test_site_category_nature_reserve():
    xml_str = (
        '<ps:ProtectedSite xmlns:ps="http://inspire.ec.europa.eu/schemas/ps/4.0" '
        'xmlns:xlink="http://www.w3.org/1999/xlink">'
        '  <ps:siteDesignation>'
        '    <ps:DesignationType>'
        '      <ps:designationScheme xlink:href="http://example/nationalProtectionCategory"/>'
        '      <ps:designation xlink:href="http://example/natureReserve"/>'
        '    </ps:DesignationType>'
        '  </ps:siteDesignation>'
        '</ps:ProtectedSite>'
    )
    site = ET.fromstring(xml_str)
    assert site_category(site) == "zchu"
