"""Tests for pipeline.sites (merging another area's website data into the Czech data)."""

import json

import numpy as np
import pytest

from pipeline import sites
from pipeline.pack import NO_SITE, SPOT, read_tile, write_tile


def site_dir(path, tiles, site_rows, attribution):
    """A site data folder: tiles = (id, [site index lists per spot] or None for a tile without a file)."""
    entries = []
    for tid, spots in tiles:
        e = {"id": tid, "file": None, "spots": 0, "bytes": 0, "bbox": [12.0, 51.0, 12.3, 51.2], "ref_min_dba": 30.0}
        if spots is not None:
            rec = np.zeros(len(spots), dtype=SPOT)
            for i, ids in enumerate(spots):
                rec["sites"][i] = ids + [NO_SITE] * (4 - len(ids))
                rec["lon"][i] = 12.0 + i
            e.update(file=f"tiles/{tid}.bin.gz", spots=len(spots), bytes=write_tile(rec, path / "tiles" / f"{tid}.bin.gz"))
        entries.append(e)
    (path / "index.json").write_text(json.dumps({"format": "FRK1", "protected_file": "protected.json", "tiles": entries,
                                                 "attribution": attribution}), encoding="utf-8")
    (path / "protected.json").write_text(json.dumps({"bits": {"np": 1}, "sites": site_rows}), encoding="utf-8")
    return path


def make(tmp_path, base_sites=2):
    base = site_dir(tmp_path / "base", [("20k_-38_-47", [[0], [1, 0]])],
                    [[f"BZ-{k}", "buffer", f"B{k}"] for k in range(base_sites)], "ČÚZK")
    extra = site_dir(tmp_path / "extra", [("20k_-44_-45", [[0, 1], []]), ("20k_-44_-46", None)],
                     [["DE-a", "chko", "LSG A"], ["DE-b", "evl", "FFH B"]], "Germany")
    return base, extra


def test_merge_sites(tmp_path):
    base, extra = make(tmp_path)
    before = (base / "tiles" / "20k_-38_-47.bin.gz").read_bytes()
    stats = sites.merge_sites(base, extra, "de-leipzig", "DE data")
    assert stats == {"tiles": 3, "added_tiles": 2, "added_spots": 2, "sites": 4}
    index = json.loads((base / "index.json").read_text(encoding="utf-8"))
    assert [(t["id"], t["area"], t["file"]) for t in index["tiles"]] == [
        ("20k_-38_-47", "cz", "tiles/20k_-38_-47.bin.gz"),
        ("de-leipzig/20k_-44_-45", "de-leipzig", "tiles/de-leipzig/20k_-44_-45.bin.gz"),
        ("de-leipzig/20k_-44_-46", "de-leipzig", None)]
    assert index["attribution"] == "ČÚZK; DE data"
    head, rec = read_tile(base / "tiles" / "de-leipzig" / "20k_-44_-45.bin.gz")
    assert head["spots"] == 2
    assert rec["sites"].tolist() == [[2, 3, NO_SITE, NO_SITE], [NO_SITE] * 4]
    assert rec["lon"].tolist() == [12.0, 13.0]
    assert index["tiles"][1]["bytes"] == (base / "tiles" / "de-leipzig" / "20k_-44_-45.bin.gz").stat().st_size
    assert (base / "tiles" / "20k_-38_-47.bin.gz").read_bytes() == before
    prot = json.loads((base / "protected.json").read_text(encoding="utf-8"))
    assert [s[0] for s in prot["sites"]] == ["BZ-0", "BZ-1", "DE-a", "DE-b"]


def test_merge_sites_refuses_too_many_sites(tmp_path):
    base, extra = make(tmp_path, base_sites=NO_SITE - 2)
    with pytest.raises(ValueError, match="too many"):
        sites.merge_sites(base, extra, "de-leipzig", "DE data")


def test_main(tmp_path, capsys):
    base, extra = make(tmp_path)
    assert sites.main([str(base), str(extra), "--area", "de-leipzig"]) == 0
    assert json.loads(capsys.readouterr().out)["added_tiles"] == 2
    index = json.loads((base / "index.json").read_text(encoding="utf-8"))
    assert index["attribution"].startswith("ČÚZK; Germany: © GeoBasis-DE / BKG")