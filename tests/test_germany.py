"""Tests for pipeline.germany (command line of the German area inputs)."""

import json

from pipeline import germany


def test_inputs_copies_the_release_files(tmp_path):
    reg = tmp_path / "region"
    reg.mkdir()
    for k, name in enumerate(germany.RELEASE_FILES):
        (reg / name).write_text("x" * (k + 1), encoding="utf-8")
    (tmp_path / "slim.gpkg").write_text("gpkg", encoding="utf-8")
    sizes = germany.inputs(reg, tmp_path / "slim.gpkg", tmp_path / "dest")
    assert sorted(sizes) == sorted([*germany.RELEASE_FILES, "zabaged_slim.gpkg"])
    assert sizes["zabaged_slim.gpkg"] == 4 and sizes["tiles.csv"] == 2


def test_main_terrain(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FREKNO_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("FREKNO_OUT", str(tmp_path / "out"))
    seen = {}
    monkeypatch.setattr(germany, "read_area_states", lambda path: seen.setdefault("states", path) and {"SN": None})
    monkeypatch.setattr(germany, "tile_chunk", lambda tid, states, dest: {"SN": len(tid)})
    assert germany.main(["terrain", "20k_-44_-45", "20k_-44_-46", "--dest", str(tmp_path / "dem")]) == 0
    assert json.loads(capsys.readouterr().out) == {"20k_-44_-45": {"SN": 11}, "20k_-44_-46": {"SN": 11}}
    assert seen["states"] == tmp_path / "out" / "region" / "states.gpkg"