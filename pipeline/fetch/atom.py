"""Read ČÚZK ATOM download feeds and pick map sheets for an area."""

from __future__ import annotations

from pathlib import Path

import xml.etree.ElementTree as ET

ATOM = "{http://www.w3.org/2005/Atom}"
GEORSS = "{http://www.georss.org/georss}"
INSPIRE_DLS = "{http://inspire.ec.europa.eu/schemas/inspire_dls/1.0}"


def parse_service_feed(path: Path | str) -> tuple[list[dict], list[str]]:
    """Parse a ČÚZK ATOM service feed and return map sheets with problems.

    Uses iterparse with both start and end events so child elements are
    preserved until the parent entry is fully processed, then cleared.
    """
    sheets: list[dict] = []
    problems: list[str] = []
    in_entry = False

    for event, element in ET.iterparse(path, events=("start", "end")):
        # Enter an entry → mark flag, skip to next event
        if event == "start" and element.tag == f"{ATOM}entry":
            in_entry = True
            continue

        # Inside an entry: only act on the entry's own "end" event
        if in_entry:
            if event == "end" and element.tag == f"{ATOM}entry":
                _process_service_entry(element, sheets, problems)
                element.clear()
                in_entry = False
            continue

        # Outside any entry → clear to save memory
        element.clear()

    return sheets, problems


def _process_service_entry(
    element: ET.Element,
    sheets: list,
    problems: list,
) -> None:
    """Extract one entry's data and append to sheets or problems."""
    entry_id = element.findtext(f"{ATOM}id", "")

    # Code
    code_elem = element.find(f"{INSPIRE_DLS}spatial_dataset_identifier_code")
    if code_elem is None or code_elem.text is None:
        problems.append(f"{entry_id}: missing spatial_dataset_identifier_code")
        return

    code = code_elem.text.rsplit("_", 1)[-1]

    # Title
    title_elem = element.find(f"{ATOM}title")
    title = title_elem.text if title_elem is not None and title_elem.text is not None else ""

    # Alternate link
    dataset_feed_url = None
    for link in element.iter(f"{ATOM}link"):
        if link.get("rel") == "alternate":
            dataset_feed_url = link.get("href")
            break

    if dataset_feed_url is None:
        problems.append(f"{entry_id}: missing alternate link")
        return

    # GeoRSS polygon
    polygon_elem = element.find(f"{GEORSS}polygon")
    if polygon_elem is None or polygon_elem.text is None:
        problems.append(f"{entry_id}: missing georss polygon")
        return

    try:
        values = [float(v) for v in polygon_elem.text.split()]
    except ValueError:
        problems.append(f"{entry_id}: polygon contains non-numeric value")
        return

    if len(values) % 2 != 0:
        problems.append(f"{entry_id}: polygon has odd number of values")
        return

    latitudes = values[0::2]
    longitudes = values[1::2]

    sheets.append({
        "code": code,
        "title": title,
        "dataset_feed_url": dataset_feed_url,
        "lat_min": min(latitudes),
        "lat_max": max(latitudes),
        "lon_min": min(longitudes),
        "lon_max": max(longitudes),
    })


def parse_dataset_feed(path: Path | str) -> list[dict]:
    """Parse a ČÚZK ATOM dataset feed and return download link info."""
    results: list[dict] = []
    in_entry = False

    for event, element in ET.iterparse(path, events=("start", "end")):
        if event == "start" and element.tag == f"{ATOM}entry":
            in_entry = True
            continue

        if in_entry:
            if event == "end" and element.tag == f"{ATOM}entry":
                _process_dataset_entry(element, results)
                element.clear()
                in_entry = False
            continue

        element.clear()

    return results


def _process_dataset_entry(
    element: ET.Element,
    results: list,
) -> None:
    """Extract alternate links from one dataset entry."""
    for link in element.iter(f"{ATOM}link"):
        if link.get("rel") == "alternate":
            length_attr = link.get("length")
            results.append({
                "url": link.get("href", ""),
                "length": int(length_attr) if length_attr is not None else None,
                "type": link.get("type") or "",
            })


def sheets_in_bbox(
    sheets: list[dict],
    lon_min: float,
    lat_min: float,
    lon_max: float,
    lat_max: float,
) -> list[dict]:
    """Return sheets whose bounding box overlaps the query box with positive area, sorted by code."""
    matching = [
        s
        for s in sheets
        if s["lon_min"] < lon_max
        and s["lon_max"] > lon_min
        and s["lat_min"] < lat_max
        and s["lat_max"] > lat_min
    ]
    return sorted(matching, key=lambda s: s["code"])


def zip_url(
    code: str,
    template: str = (
        "https://openzu.cuzk.gov.cz/opendata/DMR4G-TIFF/epsg-5514/{code}.zip"
    ),
) -> str:
    """Format the download URL for a given map sheet code."""
    return template.format(code=code)