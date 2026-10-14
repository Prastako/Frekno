"""Tests for pipeline.de_buildings (receptors from the German building outlines)."""

import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import pytest
import shapely
from pyproj import Transformer

from pipeline import de_buildings as db
from pipeline.de_area import SJTSK, circle, to_sjtsk

TO_UTM33 = Transformer.from_crs("EPSG:4326", "EPSG:25833", always_xy=True)
TO_SJTSK = Transformer.from_crs("EPSG:4326", SJTSK, always_xy=True)
CX, CY = TO_UTM33.transform(12.3747, 51.3406)  # Leipzig in UTM 33


def square(dx, dy, area):
    s = area ** 0.5
    return shapely.box(CX + dx, CY + dy, CX + dx + s, CY + dy + s)


def shapefile_zip(path, member, fields, rows, extra=()):
    """Zip a shapefile named *member* (rows: (values..., geometry), EPSG:25833) plus empty *extra* files."""
    gdf = gpd.GeoDataFrame({f: [r[k] for r in rows] for k, f in enumerate(fields)}, geometry=[r[-1] for r in rows],
                           crs="EPSG:25833")
    shp = path.parent / "tmp_shp" / member
    shp.parent.mkdir(parents=True, exist_ok=True)
    pyogrio.write_dataframe(gdf, shp, driver="ESRI Shapefile")
    with zipfile.ZipFile(path, "w") as z:
        for p in sorted(shp.parent.glob(shp.stem + ".*")):
            z.write(p, p.name)
        for name in extra:
            z.writestr(name, "")
    return path


ROWS = [  # GFK, area m2, in a leisure area, expected type
    ("31001_1000", 80, False, "home"), ("31001_1000", 29, False, "ignore"), ("31001_1000", 20, True, "cottage"),
    ("31001_1000", 9, True, "ignore"), ("31001_1010", 30, False, "home"), ("31001_1312", 12, False, "cottage"),
    ("31001_1313", 8, False, "ignore"), ("31001_9998", 49, False, "ignore"), ("31001_9998", 50, False, "home"),
    ("31001_9998", 20, True, "cottage"), ("31001_2071", 400, False, "home"), ("31001_2071", 400, True, "home"),
    ("31001_3051", 3000, False, "home"), ("31001_2463", 40, True, "ignore"), ("31001_2000", 500, False, "ignore"),
    ("51009_1610", 100, False, "ignore"), ("", 100, False, "ignore"), ("31001_12", 100, False, "ignore"),
    ("31001_1220", 120, True, "cottage"), ("31001_3100", 300, False, "ignore"),
]


def test_building_types():
    got = db.building_types([r[0] for r in ROWS], [r[1] for r in ROWS], [r[2] for r in ROWS])
    assert list(got) == [r[3] for r in ROWS]
    assert len(db.building_types([], [], [])) == 0


def test_in_areas():
    pts = shapely.points([0.5, 5.0, 2.5], [0.5, 5.0, 0.5])
    got = db.in_areas(pts, [shapely.box(0, 0, 1, 1), None, shapely.box(2, 0, 3, 1)])
    assert got.tolist() == [True, False, True]
    assert db.in_areas(pts, []).tolist() == [False, False, False]


def test_shapefiles(tmp_path):
    shapefile_zip(tmp_path / "SN.zip", "hu_sn_gebaeude_20260924.shp", ["GFK", "OI"], [("31001_1000", "a", square(0, 0, 100))])
    shapefile_zip(tmp_path / "BB_ee.zip", "GebauedeBauwerk.shp", ["gfkzshh", "oid"], [("31001_1010", "b", square(0, 0, 100))],
                  extra=["Flurstueck.shp"])
    got = db.shapefiles(tmp_path)
    assert [(p.rsplit("/", 1)[1], g, i) for p, g, i in got] == [("hu_sn_gebaeude_20260924.shp", "GFK", "OI"),
                                                                ("GebauedeBauwerk.shp", "gfkzshh", "oid")]
    assert got[0][0].startswith("/vsizip/")
    with zipfile.ZipFile(tmp_path / "BB_x.zip", "w") as z:
        z.writestr("Nutzung.shp", "")
    with pytest.raises(ValueError, match="no shapefile"):
        db.shapefiles(tmp_path)


def run_prep(tmp_path):
    raw = tmp_path / "hu"
    raw.mkdir()
    sn = [("31001_1000", "home1", square(0, 0, 100)), ("31001_1000", "shed", square(100, 0, 20)),
          ("31001_1000", "hut", square(200, 0, 15)), ("31001_1000", "far", square(30000, 0, 100))]
    shapefile_zip(raw / "SN.zip", "hu_sn.shp", ["GFK", "OI"], sn)
    shapefile_zip(raw / "BB_ee.zip", "GebauedeBauwerk.shp", ["gfkzshh", "oid"],
                  [("31001_1010", "home2", square(0, 300, 50)), ("51009_1610", "roof", square(100, 300, 60))])
    leisure = [to_sjtsk(square(190, -10, 1600), "EPSG:25833")]
    stats = db.prep_buildings(raw, leisure, circle(12.3747, 51.3406, 5000.0), tmp_path / "receptors.csv", tmp_path / "slim.gpkg")
    return stats, pd.read_csv(tmp_path / "receptors.csv", dtype={"building_id": str})


def test_prep_buildings(tmp_path):
    stats, rec = run_prep(tmp_path)
    assert stats == {"buildings": 5, "home": 2, "cottage": 1}
    assert rec[["building_id", "receptor_type", "use_code"]].values.tolist() == [
        ["dehome1", "home", 1000], ["dehut", "cottage", 1000], ["dehome2", "home", 1010]]
    assert set(rec["number_type"]) == {"none"} and not rec["unclear"].any()
    x, y = TO_SJTSK.transform(12.3747, 51.3406)
    assert np.hypot(rec["x"].iloc[0] - x, rec["y"].iloc[0] - y) < 20
    assert pyogrio.read_info(tmp_path / "slim.gpkg", layer=db.BUILDING_LAYER)["features"] == 5


def test_prep_buildings_in_small_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "BATCH", 2)
    stats, rec = run_prep(tmp_path)
    assert stats == {"buildings": 5, "home": 2, "cottage": 1}
    assert rec["building_id"].tolist() == ["dehome1", "dehut", "dehome2"]
    assert pyogrio.read_info(tmp_path / "slim.gpkg", layer=db.BUILDING_LAYER)["features"] == 5
