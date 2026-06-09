"""Small geodesy helpers. Equirectangular projection local to a reference
latitude is accurate to a fraction of a percent over the few-hundred-metre
distances we deal with, and avoids a numpy/shapely dependency."""
import math

_M_PER_DEG_LAT = 111_320.0


def _to_xy(lat: float, lon: float, ref_lat: float) -> tuple[float, float]:
    x = lon * _M_PER_DEG_LAT * math.cos(math.radians(ref_lat))
    y = lat * _M_PER_DEG_LAT
    return x, y


def point_to_polyline_m(
    lat: float, lon: float, line: list[tuple[float, float]]
) -> float:
    """Shortest distance in metres from a point to a polyline given as
    [(lat, lon), ...]. A 1-point line degrades to point-to-point."""
    if not line:
        return float("inf")
    ref_lat = line[0][0]
    px, py = _to_xy(lat, lon, ref_lat)
    if len(line) == 1:
        ax, ay = _to_xy(line[0][0], line[0][1], ref_lat)
        return math.hypot(px - ax, py - ay)
    best = float("inf")
    for (alat, alon), (blat, blon) in zip(line, line[1:]):
        ax, ay = _to_xy(alat, alon, ref_lat)
        bx, by = _to_xy(blat, blon, ref_lat)
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        if seg2 == 0:
            d = math.hypot(px - ax, py - ay)
        else:
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
            cx, cy = ax + t * dx, ay + t * dy
            d = math.hypot(px - cx, py - cy)
        best = min(best, d)
    return best


def bbox_of(line: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    """(min_lat, min_lon, max_lat, max_lon) of a list of (lat, lon)."""
    lats = [p[0] for p in line]
    lons = [p[1] for p in line]
    return min(lats), min(lons), max(lats), max(lons)
