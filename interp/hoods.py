"""Neighbourhood boundaries: download once from the city's open data, then
assign each interpolation way to a neighbourhood by point-in-polygon on the
way's midpoint. Toronto's 158 come through CKAN; another city's URL may serve
GeoJSON directly (Guelph's 23 Areas, an ArcGIS `f=geojson` query).

The 158 neighbourhood polygons union to exactly the city boundary, so this
doubles as the Toronto crop: a way whose midpoint falls in no polygon is
outside the city and gets no task.
"""
import json
import re
from pathlib import Path

import requests

_CKAN_PACKAGE = (
    "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/"
    "package_show?id=neighbourhoods"
)
_FILE = "neighbourhoods.geojson"


def _download(path: Path, url: str = _CKAN_PACKAGE) -> None:
    if "package_show" not in url:  # serves the GeoJSON itself
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        path.write_bytes(resp.content)
        return
    meta = requests.get(url, timeout=60).json()
    resources = meta["result"]["resources"]
    # The bare "Neighbourhoods" GeoJSON resource is a datastore dump that
    # actually serves CSV; we want the real file export of the current
    # (158-neighbourhood) layer in WGS84.
    geojson = [
        r for r in resources
        if r.get("format", "").lower() == "geojson"
        and "datastore/dump" not in r.get("url", "")
        and "historical" not in r.get("name", "").lower()
    ]
    if not geojson:
        raise RuntimeError("No GeoJSON resource in the neighbourhoods package.")
    resp = requests.get(geojson[0]["url"], timeout=120)
    resp.raise_for_status()
    path.write_bytes(resp.content)


def load(data_dir: Path, url: str = _CKAN_PACKAGE, name_field: str = "AREA_NAME",
         city_name: str = "Toronto") -> list[tuple]:
    """[(name, rings, bbox), ...] where rings = [[(lon, lat), ...], ...]
    (outer rings and holes together; containment is even-odd across them all)
    and bbox = (min_lon, min_lat, max_lon, max_lat) for prefiltering."""
    path = data_dir / _FILE
    if not path.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {city_name} neighbourhood boundaries...")
        _download(path, url)
    fc = json.loads(path.read_text(encoding="utf-8"))

    hoods = []
    for feat in fc["features"]:
        props = feat.get("properties", {})
        name = props.get(name_field) or next(
            (v for k, v in props.items() if "NAME" in k.upper()), "?"
        )
        # Older releases embed the area code in the name: "Casa Loma (96)".
        name = re.sub(r"\s*\(\d+\)$", "", str(name))
        geom = feat.get("geometry") or {}
        if geom.get("type") == "Polygon":
            polys = [geom["coordinates"]]
        elif geom.get("type") == "MultiPolygon":
            polys = geom["coordinates"]
        else:
            continue
        rings = [ring for poly in polys for ring in poly]
        lons = [pt[0] for ring in rings for pt in ring]
        lats = [pt[1] for ring in rings for pt in ring]
        hoods.append((name, rings, (min(lons), min(lats), max(lons), max(lats))))
    return hoods


def _in_ring(lon: float, lat: float, ring: list) -> bool:
    """Ray-casting test against one ring."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[j][0], ring[j][1]
        if (y1 > lat) != (y2 > lat):
            x_cross = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def locate(lat: float, lon: float, hoods: list[tuple]) -> str | None:
    """Neighbourhood name containing the point, or None (outside Toronto).
    Even-odd over a feature's rings handles holes; the bbox check keeps the
    pure-Python scan fast across ~69k ways x 158 polygons."""
    for name, rings, (min_lon, min_lat, max_lon, max_lat) in hoods:
        if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
            continue
        crossings = sum(1 for ring in rings if _in_ring(lon, lat, ring))
        if crossings % 2 == 1:
            return name
    return None


def midpoint(geometry: list) -> tuple[float, float]:
    """(lat, lon) vertex centroid of a way's [[lat, lon], ...] geometry."""
    lats = [p[0] for p in geometry]
    lons = [p[1] for p in geometry]
    return sum(lats) / len(lats), sum(lons) / len(lons)
