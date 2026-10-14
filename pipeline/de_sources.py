"""Open data for the German area around Leipzig: download links and the downloads themselves.

Licences: BKG VG250, basemap.de Basis-DLM and the states' building outlines and terrain models are under
dl-de/by-2-0 (Thuringia's building outlines CC BY 4.0); the EEA's Natura 2000 sites and nationally designated
areas and DELFI's timetables (gtfs.de) are under CC BY 4.0.
"""

import re
from pathlib import Path

import requests

from pipeline.fetch.download import download

VG250_URL = "https://daten.gdz.bkg.bund.de/produkte/vg/vg250_ebenen_0101/aktuell/vg250_01-01.utm32s.gpkg.ebenen.zip"
BDLM_LIST_URL = "https://basemap.de/dienste/opendata/basisviews/"
BDLM_STATES = ("BB", "SN", "ST", "TH")
HU_URLS = {
    "SN": "https://geocloud.landesvermessung.sachsen.de/public.php/dav/files/AcAqRn4k9Sz8ZZx/hu_sn_shape.zip",
    "ST": "https://www.geodatenportal.sachsen-anhalt.de/gfds_webshare/download/LVermGeo/Geodatenportal/content/Hausumringe.zip",
    "TH": "https://geoportal.geoportal-th.de/hausko_umr/HU-TH.zip",
}
BB_ALKIS_URL = "https://data.geobasis-bb.de/geobasis/daten/alkis/Vektordaten/shape/alkis_shape_{}.zip"
BB_DISTRICTS = ("brb", "ee", "lds", "osl", "pm", "tf")  # Brandenburg districts that reach into the area
EEA = "https://bio.discomap.eea.europa.eu/arcgis/rest/services/ProtectedSites/"
N2K_URL = EEA + "Natura2000Sites/MapServer/{layer}/query"  # layer 0: habitats directive sites, 1: bird areas
NATDA_URL = EEA + "NatDAv24_Dyna_WM/MapServer/4/query"  # nationally designated areas, large scale polygons
LSG_CODE = "DE07"  # NatDA designation code of the Landschaftsschutzgebiete
ATTRIBUTION = ("Germany: © GeoBasis-DE / BKG (VG250, basemap.de with the Basis-DLM of the states), © GeoSN, "
               "© GeoBasis-DE / LVermGeo ST, © GDI-Th, © GeoBasis-DE/LGB (building outlines, terrain models), "
               "dl-de/by-2-0 (www.govdata.de/dl-de/by-2-0), Thuringia's building outlines CC BY 4.0; "
               "EEA (Natura 2000, nationally designated areas), CC BY 4.0")


def bdlm_urls(listing: str) -> dict[str, str]:
    """The newest Basis-DLM GeoPackage link per state in BDLM_STATES from the basemap.de folder listing."""
    found = {}
    for st, day in re.findall(r"basisviews_bdlm_([A-Z]{2})_EPSG4326_(\d{4}-\d{2}-\d{2})\.gpkg", listing):
        if st in BDLM_STATES and day > found.get(st, ""):
            found[st] = day
    missing = [s for s in BDLM_STATES if s not in found]
    if missing:
        raise ValueError(f"no Basis-DLM file for {missing} in the listing")
    return {st: f"{BDLM_LIST_URL}basisviews_bdlm_{st}_EPSG4326_{day}.gpkg" for st, day in sorted(found.items())}


def query_params(where: str, bbox: tuple, fields: str) -> dict:
    """Query parameters for an EEA map service layer: features matching *where* that touch the lon/lat *bbox*,
    as GeoJSON in WGS84."""
    return {"where": where, "geometry": ",".join(str(v) for v in bbox), "geometryType": "esriGeometryEnvelope",
            "inSR": "4326", "spatialRel": "esriSpatialRelIntersects", "outFields": fields, "outSR": "4326",
            "returnGeometry": "true", "f": "geojson"}


def query_geojson(url: str, params: dict, dest) -> int:
    """Save the GeoJSON answer of an EEA query to *dest*; return the number of features."""
    r = requests.get(url, params=params, timeout=600)
    r.raise_for_status()
    data = r.json()
    if "features" not in data:
        raise ValueError(f"no features in the answer from {url}: {str(data)[:200]}")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return len(data["features"])


def fetch_vectors(raw: Path, bbox: tuple) -> dict:
    """Download VG250, the Basis-DLM GeoPackages, the building outlines and the protected areas into *raw*.

    *bbox* is (lon_min, lat_min, lon_max, lat_max) of the area. Returns the counts and file names.
    """
    raw = Path(raw)
    download(VG250_URL, raw / "vg250.zip", timeout=600)
    listing = requests.get(BDLM_LIST_URL, timeout=60).text
    stats = {"bdlm": {}}
    for st, url in bdlm_urls(listing).items():
        download(url, raw / "bdlm" / f"{st}.gpkg", timeout=1800)
        stats["bdlm"][st] = url.rsplit("/", 1)[-1]
    for st, url in HU_URLS.items():
        download(url, raw / "hu" / f"{st}.zip", timeout=1800)
    for d in BB_DISTRICTS:
        download(BB_ALKIS_URL.format(d), raw / "hu" / f"BB_{d}.zip", timeout=1800)
    fields = "SITECODE,SITENAME,MS"
    stats["ffh"] = query_geojson(N2K_URL.format(layer=0), query_params("MS='DE'", bbox, fields), raw / "eea" / "ffh.geojson")
    stats["spa"] = query_geojson(N2K_URL.format(layer=1), query_params("MS='DE'", bbox, fields), raw / "eea" / "spa.geojson")
    where = f"countryCode='DE' AND designationTypeCode='{LSG_CODE}'"
    stats["lsg"] = query_geojson(NATDA_URL, query_params(where, bbox, "natDAId,siteName,designationTypeCode"),
                                 raw / "eea" / "lsg.geojson")
    return stats