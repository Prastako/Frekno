"""Land-cover masks from ZABAGED and ground polygons for NoiseModelling."""

import json
from pathlib import Path

import numpy as np
import pyogrio
from rasterio.features import rasterize, shapes
from rasterio.transform import from_origin
from shapely.geometry import mapping, shape

CLASSES = {
    "water": ["VodniPlocha"],
    "building": ["BudovaJednotlivaNeboBlokBudov", "KulnaSklenikFoliovnikPristresek"],
    "compound": [
        "ArealUceloveZastavby",
        "OstatniPlochaVSidlech",
        "ParkovisteOdpocivka",
        "Hrbitov",
    ],
    "forest": ["LesniPudaSeStromy", "LesniPudaSKrovinatymPorostem"],
    "quarry": ["PovrchovaTezbaLom"],
}

HARD_CLASSES = ("water", "compound", "quarry")


def grid_shape(bounds: tuple, res_m: float) -> tuple:
    """Return (h, w, transform) for the given bounds and resolution.

    Raises ValueError when h or w are not positive whole numbers.
    """
    xmin, ymin, xmax, ymax = bounds
    w = (xmax - xmin) / res_m
    h = (ymax - ymin) / res_m
    if w <= 0 or h <= 0 or w % 1 != 0 or h % 1 != 0:
        raise ValueError(f"grid dimensions not positive whole numbers: h={h}, w={w}")
    transform = from_origin(xmin, ymax, res_m, res_m)
    return (int(h), int(w), transform)


def read_geometries(gpkg: Path, layers: list, bounds: tuple) -> list:
    """Read non-None, non-empty geometries from the given layers."""
    available = [row[0] for row in pyogrio.list_layers(gpkg)]
    geoms: list = []
    for name in layers:
        if name not in available:
            continue
        gdf = pyogrio.read_dataframe(gpkg, layer=name, bbox=tuple(bounds), columns=[])
        for g in gdf.geometry:
            if g is not None and not g.is_empty:
                geoms.append(g)
    return geoms


def rasterize_class(gpkg: Path, cls: str, bounds: tuple, res_m: float) -> np.ndarray:
    """Return a uint8 mask: 1 where geometries of the class cover the cell centre."""
    geoms = read_geometries(gpkg, CLASSES[cls], bounds)
    h, w, tr = grid_shape(bounds, res_m)
    if not geoms:
        return np.zeros((h, w), dtype="uint8")
    return rasterize(geoms, out_shape=(h, w), transform=tr, fill=0, default_value=1, dtype="uint8")


def landcover_masks(gpkg: Path, bounds: tuple, res_m: float) -> dict:
    """Return {class: mask} for every class in CLASSES."""
    return {cls: rasterize_class(gpkg, cls, bounds, res_m) for cls in CLASSES}


def hard_mask(masks: dict) -> np.ndarray:
    """Return uint8 OR of masks for the hard classes."""
    h = np.zeros_like(next(iter(masks.values())))
    for c in HARD_CLASSES:
        h = h | masks[c]
    return h


def ground_polygons(hard: np.ndarray, transform) -> list:
    """Return list of (shapely geometry, G) per connected area.

    G = 0.0 for hard-ground areas, 1.0 otherwise.
    """
    polys: list = []
    for geom_dict, value in shapes(hard.astype("uint8"), transform=transform):
        g = 0.0 if value == 1 else 1.0
        polys.append((shape(geom_dict), g))
    return polys


def write_ground_geojson(polys: list, path: Path) -> None:
    """Write ground polygons as a GeoJSON FeatureCollection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"G": g}, "geometry": mapping(geom)}
            for geom, g in polys
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fc, f)
