"""Stage 1: enumerate OSM `addr:interpolation` ways across the Toronto bbox.

The bbox is swept as a grid of tiles so no single Overpass request has to
return the whole city. For each way we keep its geometry plus the
housenumber/street that live on its member nodes (the way itself only carries
`addr:interpolation` and usually `source`). Result is cached to
data/interpolation_ways.json.
"""
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from .config import Config

_HN_RE = re.compile(r"\d+")


def _parse_housenumber(value: str | None) -> int | None:
    if not value:
        return None
    m = _HN_RE.search(value)
    return int(m.group()) if m else None


def _tiles(bbox: tuple[float, float, float, float], step: float):
    min_lat, min_lon, max_lat, max_lon = bbox
    lat = min_lat
    while lat < max_lat:
        lon = min_lon
        nlat = min(lat + step, max_lat)
        while lon < max_lon:
            nlon = min(lon + step, max_lon)
            yield (lat, lon, nlat, nlon)
            lon = nlon
        lat = nlat


def _query(tile: tuple[float, float, float, float]) -> str:
    s, w, n, e = tile
    return (
        "[out:json][timeout:180];"
        f'way["addr:interpolation"]({s},{w},{n},{e});'
        "(._;>;);"
        "out body;"
    )


def _normalize_way(way: dict, nodes: dict[int, dict]) -> dict | None:
    """Turn a raw Overpass way + its member nodes into our flat record, or None
    if the way has no usable geometry."""
    member_ids = way.get("nodes", [])
    geom: list[tuple[float, float]] = []
    anchors: list[dict] = []  # member nodes carrying a housenumber
    streets: list[str] = []
    for nid in member_ids:
        node = nodes.get(nid)
        if node is None or node.get("lat") is None:
            continue
        latlon = (node["lat"], node["lon"])
        geom.append(latlon)
        ntags = node.get("tags") or {}
        hn = _parse_housenumber(ntags.get("addr:housenumber"))
        if hn is not None:
            anchors.append({"id": nid, "lat": node["lat"], "lon": node["lon"], "num": hn})
            if ntags.get("addr:street"):
                streets.append(ntags["addr:street"])
    if len(geom) < 1:
        return None

    wtags = way.get("tags") or {}
    if not streets and wtags.get("addr:street"):
        streets.append(wtags["addr:street"])
    street = streets[0] if streets else None

    nums = [a["num"] for a in anchors]
    return {
        "way_id": way["id"],
        "parity": wtags.get("addr:interpolation"),
        "source": wtags.get("source"),
        "street": street,
        "geometry": geom,  # [[lat, lon], ...]
        "anchors": anchors,
        "lo": min(nums) if nums else None,
        "hi": max(nums) if nums else None,
    }


def fetch(cfg: Config, force: bool = False) -> list[dict]:
    """Fetch + cache all interpolation ways in the configured bbox."""
    out_path = cfg.data_dir / "interpolation_ways.json"
    if out_path.exists() and not force:
        return load_cached(cfg)

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    headers = {"User-Agent": cfg.user_agent}

    by_id: dict[int, dict] = {}
    tiles = list(_tiles(cfg.toronto_bbox, cfg.tile_deg))
    for i, tile in enumerate(tiles, 1):
        # Overpass throttles with 429 (and sheds load with 504); one busy
        # moment shouldn't kill a 66-tile sweep. Back off and retry the tile.
        for attempt in range(5):
            resp = session.post(
                cfg.overpass_url,
                data={"data": _query(tile)},
                headers=headers,
                timeout=200,
            )
            if resp.status_code in (429, 504) and attempt < 4:
                wait = int(resp.headers.get("Retry-After") or 0) or 30 * (attempt + 1)
                print(f"  tile {i}/{len(tiles)}: Overpass busy "
                      f"({resp.status_code}); retrying in {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        elements = resp.json().get("elements", [])
        nodes = {
            el["id"]: el for el in elements if el.get("type") == "node"
        }
        new = 0
        for el in elements:
            if el.get("type") != "way" or el["id"] in by_id:
                continue
            rec = _normalize_way(el, nodes)
            if rec is not None:
                by_id[el["id"]] = rec
                new += 1
        print(f"  tile {i}/{len(tiles)} {tile}: +{new} ways (total {len(by_id)})")
        if i < len(tiles):
            time.sleep(cfg.request_delay_s)

    ways = list(by_id.values())
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bbox": list(cfg.toronto_bbox),
        "ways": ways,
    }
    out_path.write_text(json.dumps(payload), encoding="utf-8")
    print(f"Wrote {len(ways)} interpolation ways to {out_path}")
    return ways


def _read_cache(cfg: Config) -> dict:
    path = cfg.data_dir / "interpolation_ways.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python run.py fetch` first."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):  # pre-timestamp cache format
        return {"fetched_at": None, "bbox": None, "ways": data}
    return data


def load_cached(cfg: Config) -> list[dict]:
    return _read_cache(cfg)["ways"]


def fetched_at(cfg: Config) -> str | None:
    """ISO timestamp of the cached fetch, or None for a pre-timestamp cache."""
    return _read_cache(cfg)["fetched_at"]
