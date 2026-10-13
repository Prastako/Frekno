"""Protected areas (AOPK ČR, INSPIRE Protected Sites, CC BY 4.0) as one GeoPackage layer in S-JTSK.

Each site keeps its id, a category (CATEGORIES) and its name. Sites of other national
categories (biosphere reserves, Ramsar sites) are skipped.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import geopandas as gpd
import shapely
from pyproj import Transformer

NS = {"gml": "http://www.opengis.net/gml/3.2", "ps": "http://inspire.ec.europa.eu/schemas/ps/4.0",
      "gn": "http://inspire.ec.europa.eu/schemas/gn/4.0", "xlink": "http://www.w3.org/1999/xlink"}
# nationalProtectionCategory designation value -> category used by the site
CATEGORIES = {
    "nationalPark": "np",
    "protectedLandscapeArea": "chko",
    "nationalNatureReserve": "zchu",
    "natureReserve": "zchu",
    "nationalNatureMonument": "zchu",
    "natureMonument": "zchu",
    "bufferZone": "buffer",
    "habitatsDirectiveSite": "evl",
    "birdsDirectiveSite": "po",
    "contractProtectedArea": "contract",
}
_TO_SJTSK = Transformer.from_crs("EPSG:3035", "EPSG:5514", always_xy=True)
_TAG_SITE = "{%s}ProtectedSite" % NS["ps"]


def _ring(pos_list: str):
    v = [float(t) for t in pos_list.split()]
    # EPSG:3035 in GML is northing first (lat, lon order): pairs are (y, x)
    ys, xs = v[0::2], v[1::2]
    x, y = _TO_SJTSK.transform(xs, ys)
    return list(zip(x, y))


def site_geometry(site: ET.Element):
    """MultiPolygon in EPSG:5514 from the gml:MultiSurface of a ps:ProtectedSite element."""
    polys = []
    for poly in site.iter("{%s}Polygon" % NS["gml"]):
        ext = poly.find("gml:exterior/gml:LinearRing/gml:posList", NS)
        holes = [_ring(h.text) for h in poly.findall("gml:interior/gml:LinearRing/gml:posList", NS)]
        polys.append(shapely.Polygon(_ring(ext.text), holes))
    return shapely.make_valid(shapely.MultiPolygon(polys)) if polys else None


def site_category(site: ET.Element) -> str | None:
    """Category from the nationalProtectionCategory designation, or None if not in CATEGORIES."""
    for d in site.iterfind("ps:siteDesignation/ps:DesignationType", NS):
        scheme = d.find("ps:designationScheme", NS).get("{%s}href" % NS["xlink"], "")
        if scheme.endswith("/nationalProtectionCategory"):
            value = d.find("ps:designation", NS).get("{%s}href" % NS["xlink"], "").rsplit("/", 1)[-1]
            return CATEGORIES.get(value)
    return None


def read_sites(gml_path) -> gpd.GeoDataFrame:
    """Parse the AOPK GML into a GeoDataFrame with columns site_id, category, name, geometry (EPSG:5514)."""
    rows = []
    for _, el in ET.iterparse(gml_path, events=("end",)):
        if el.tag != _TAG_SITE:
            continue
        cat = site_category(el)
        if cat is not None:
            name = el.find(".//gn:text", NS)
            rows.append({"site_id": el.get("{%s}id" % NS["gml"]), "category": cat,
                         "name": name.text if name is not None else "", "geometry": site_geometry(el)})
        el.clear()
    return gpd.GeoDataFrame(rows, columns=["site_id", "category", "name", "geometry"], geometry="geometry", crs="EPSG:5514")


def prep_protected(gml_path, out_gpkg) -> dict:
    """Write the protected sites to *out_gpkg* (layer 'protected'); return counts per category."""
    gdf = read_sites(gml_path)
    Path(out_gpkg).parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out_gpkg, layer="protected", driver="GPKG")
    return {"sites": len(gdf), **{c: int((gdf["category"] == c).sum()) for c in dict.fromkeys(CATEGORIES.values())}}
