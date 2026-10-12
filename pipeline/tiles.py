"""Square map tiles in S-JTSK coordinates (EPSG:5514)."""

import math
import re

from pyproj import Transformer
from shapely.geometry import box


def _validate_size_m(size_m: int) -> None:
    """Raise ValueError unless size_m is a positive int multiple of 1000."""
    if not isinstance(size_m, int) or isinstance(size_m, bool):
        raise ValueError("size_m must be an integer")
    if size_m <= 0:
        raise ValueError("size_m must be greater than 0")
    if size_m % 1000 != 0:
        raise ValueError("size_m must be a multiple of 1000")


def tile_index(x: float, y: float, size_m: int) -> tuple[int, int]:
    """Return tile indices (ix, iy) for the given S-JTSK coordinates."""
    _validate_size_m(size_m)
    return (math.floor(x / size_m), math.floor(y / size_m))


def tile_id(ix: int, iy: int, size_m: int) -> str:
    """Return a human-readable tile identifier."""
    _validate_size_m(size_m)
    return f"{size_m // 1000}k_{ix}_{iy}"


def parse_tile_id(tid: str) -> tuple[int, int, int]:
    """Parse a tile identifier, returning (ix, iy, size_m)."""
    match = re.fullmatch(r"(\d+)k_(-?\d+)_(-?\d+)", tid)
    if not match:
        raise ValueError(f"invalid tile id: {tid!r}")
    size_m = int(match.group(1)) * 1000
    if size_m == 0:
        raise ValueError("size_m must not be 0")
    return (int(match.group(2)), int(match.group(3)), size_m)


def tile_bounds(
    ix: int, iy: int, size_m: int, buffer_m: float = 0.0
) -> tuple[float, float, float, float]:
    """Return (xmin, ymin, xmax, ymax) for the tile, expanded by buffer_m."""
    _validate_size_m(size_m)
    if buffer_m < 0:
        raise ValueError("buffer_m must not be negative")
    xmin = ix * size_m - buffer_m
    ymin = iy * size_m - buffer_m
    xmax = (ix + 1) * size_m + buffer_m
    ymax = (iy + 1) * size_m + buffer_m
    return (xmin, ymin, xmax, ymax)


def tiles_for_geometry(geom, size_m: int) -> list[str]:
    """Return sorted tile ids whose squares overlap *geom* with area > 0."""
    _validate_size_m(size_m)
    if geom.is_empty:
        return []

    gminx, gminy, gmaxx, gmaxy = geom.bounds
    ix_start = math.floor(gminx / size_m)
    ix_end = math.floor(gmaxx / size_m)
    iy_start = math.floor(gminy / size_m)
    iy_end = math.floor(gmaxy / size_m)

    ids: list[str] = []
    for ix in range(ix_start, ix_end + 1):
        for iy in range(iy_start, iy_end + 1):
            tile_rect = box(
                ix * size_m,
                iy * size_m,
                (ix + 1) * size_m,
                (iy + 1) * size_m,
            )
            if tile_rect.intersection(geom).area > 0:
                ids.append(tile_id(ix, iy, size_m))

    return sorted(ids, key=lambda t: (parse_tile_id(t)[0], parse_tile_id(t)[1]))


def bbox_to_wgs84(
    xmin: float, ymin: float, xmax: float, ymax: float
) -> tuple[float, float, float, float]:
    """Transform S-JTSK bounding box to WGS84, returning (lon_min, lat_min, lon_max, lat_max)."""
    if xmin >= xmax:
        raise ValueError("xmin must be less than xmax")
    if ymin >= ymax:
        raise ValueError("ymin must be less than ymax")

    transformer = Transformer.from_crs("EPSG:5514", "EPSG:4326", always_xy=True)
    n = 21

    xs = [xmin + i * (xmax - xmin) / (n - 1) for i in range(n)]
    ys = [ymin + i * (ymax - ymin) / (n - 1) for i in range(n)]

    # Bottom edge (y = ymin) and top edge (y = ymax)
    all_lons: list[float] = []
    all_lats: list[float] = []

    for edge_y in (ymin, ymax):
        lons, lats = transformer.transform(xs, [edge_y] * n)
        all_lons.extend(lons)
        all_lats.extend(lats)

    # Left edge (x = xmin) and right edge (x = xmax)
    for edge_x in (xmin, xmax):
        lons, lats = transformer.transform([edge_x] * n, ys)
        all_lons.extend(lons)
        all_lats.extend(lats)

    return (min(all_lons), min(all_lats), max(all_lons), max(all_lats))
