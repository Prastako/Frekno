"""Classify RUIAN buildings into receptor points by use code and house number."""

import csv
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TYPES = ("home", "cottage", "unclear", "ignore")
NUMBER_TYPES = ("cp", "ce", "none")
STAT_KEYS = ("rows", "home", "cottage", "unclear", "ignored", "ignored_unclear", "duplicates", "no_position")


def load_type_map(path=None) -> dict[int, str]:
    """Read receptor type mapping from the CSV file.

    Returns a dict mapping integer use-code to receptor type string.
    Raises ValueError on unknown receptor_type or duplicate codes.
    """
    if path is None:
        path = ROOT / "config" / "receptor_types.csv"
    type_map: dict[int, str] = {}
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = int(row["code"])
            receptor_type = row["receptor_type"]
            if receptor_type not in TYPES:
                raise ValueError(f"Unknown receptor_type {receptor_type!r} for code {code}")
            if code in type_map:
                raise ValueError(f"Duplicate code {code}")
            type_map[code] = receptor_type
    return type_map


def number_type_from_text(text: str | None) -> str:
    """Determine house-number type from a text label.

    Returns 'cp' (house number), 'ce' (evidenční/recreational), or 'none'.
    """
    if text is None:
        return "none"
    text = text.strip()
    if not text:
        return "none"
    if text.startswith("č.p.") or text.startswith("c.p."):
        return "cp"
    if text.startswith("č.e.") or text.startswith("c.e."):
        return "ce"
    return "none"


def classify(
    use_code: int | None,
    number_type: str,
    type_map: dict[int, str],
) -> tuple[str, bool]:
    """Classify a building into receptor type and an unclear flag.

    Returns (receptor_type, unclear) where *unclear* is True when the
    decision relied on the house-number type rather than a known use code.
    """
    if use_code is not None:
        mapped = type_map.get(use_code)
        if mapped in ("home", "cottage", "ignore"):
            return (mapped, False)
    # Fallback: code missing, not in map, or mapped to "unclear"
    if number_type == "cp":
        return ("home", True)
    if number_type == "ce":
        return ("cottage", True)
    return ("ignore", True)


def read_buildings_csv(path: Path | str) -> list[dict]:
    """Read building rows from a CSV file.

    Expected columns: building_id, use_code, number_type, x, y.
    Extra columns are silently ignored.
    """
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            building_id = row["building_id"].strip()

            uc_raw = row["use_code"].strip()
            use_code = None if uc_raw == "" else int(uc_raw)

            nt = row["number_type"].strip()
            number_type = nt if nt in NUMBER_TYPES else "none"

            x_raw = row["x"].strip()
            try:
                x: float | None = float(x_raw) if x_raw else None
                if x is not None and math.isnan(x):
                    x = None
            except ValueError:
                x = None

            y_raw = row["y"].strip()
            try:
                y: float | None = float(y_raw) if y_raw else None
                if y is not None and math.isnan(y):
                    y = None
            except ValueError:
                y = None

            rows.append({
                "building_id": building_id,
                "use_code": use_code,
                "number_type": number_type,
                "x": x,
                "y": y,
            })
    return rows


def build_receptors(
    rows: list[dict],
    type_map: dict[int, str],
) -> tuple[list[dict], dict]:
    """Build receptor points from building rows.

    Returns (receptors, stats).  *receptors* is a list of kept dicts;
    *stats* tracks counts for every key in STAT_KEYS.
    """
    stats = {key: 0 for key in STAT_KEYS}
    stats["rows"] = len(rows)
    seen: set[str] = set()
    receptors: list[dict] = []

    for row in rows:
        bid = row["building_id"]
        if bid in seen:
            stats["duplicates"] += 1
            continue
        seen.add(bid)

        receptor_type, unclear = classify(row["use_code"], row["number_type"], type_map)

        if receptor_type == "ignore":
            stats["ignored"] += 1
            if unclear:
                stats["ignored_unclear"] += 1
            continue

        if row["x"] is None or row["y"] is None or math.isnan(row["x"]) or math.isnan(row["y"]):
            stats["no_position"] += 1
            continue

        receptors.append({
            "building_id": bid,
            "x": row["x"],
            "y": row["y"],
            "use_code": row["use_code"],
            "number_type": row["number_type"],
            "receptor_type": receptor_type,
            "unclear": unclear,
        })
        stats[receptor_type] += 1
        if unclear:
            stats["unclear"] += 1

    return receptors, stats


def counts_by_code(
    rows: list[dict],
    type_map: dict[int, str],
) -> list[dict]:
    """Count rows per (use_code, number_type) combination.

    Each building_id is counted at most once (first row wins).
    Rows without a valid position are still counted.
    """
    seen: set[str] = set()
    counts: dict[tuple[int | None, str], int] = {}
    info: dict[tuple[int | None, str], tuple[str, bool]] = {}

    for row in rows:
        bid = row["building_id"]
        if bid in seen:
            continue
        seen.add(bid)

        use_code = row["use_code"]
        number_type = row["number_type"]
        receptor_type, unclear = classify(use_code, number_type, type_map)

        key = (use_code, number_type)
        counts[key] = counts.get(key, 0) + 1
        info[key] = (receptor_type, unclear)

    nt_order = {"cp": 0, "ce": 1, "none": 2}
    sorted_keys = sorted(
        counts.keys(),
        key=lambda k: (k[0] is None, k[0] if k[0] is not None else 0, nt_order.get(k[1], 3)),
    )

    result: list[dict] = []
    for key in sorted_keys:
        use_code, number_type = key
        receptor_type, unclear = info[key]
        result.append({
            "use_code": use_code,
            "number_type": number_type,
            "receptor_type": receptor_type,
            "unclear": unclear,
            "count": counts[key],
        })

    return result


def write_receptors_csv(receptors: list[dict], path: Path | str) -> None:
    """Write receptor points to a CSV file."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["building_id", "x", "y", "use_code", "number_type",
                         "receptor_type", "unclear"])
        for r in receptors:
            writer.writerow([
                r["building_id"],
                repr(r["x"]),
                repr(r["y"]),
                "" if r["use_code"] is None else r["use_code"],
                r["number_type"],
                r["receptor_type"],
                "true" if r["unclear"] else "false",
            ])
