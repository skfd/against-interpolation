"""Load the city config from the project root.

Toronto is the default city and keeps the original layout: `config.toml`,
`data/`, `manifest.json`. Any other city is `config.<city>.toml`,
`data/<city>/`, `manifest.<city>.json`, selected with `run.py --city <city>`
(which sets AGAINST_INTERPOLATION_CITY before anything loads the config, so
the `t2` bridge points the engine at the right city checkout too).

Every key added for the second city falls back to Toronto's original value,
so `config.toml` needs no edits and Toronto's runs are unchanged.
"""
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CITY_ENV = "AGAINST_INTERPOLATION_CITY"

_TORONTO_HOODS_URL = (
    "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/"
    "package_show?id=neighbourhoods"
)


@dataclass
class Config:
    t2_root: str
    t2_city_dir: str
    toronto_bbox: tuple[float, float, float, float]  # the city's fetch bbox
    overpass_url: str
    tile_deg: float
    request_delay_s: float
    match_radius_m: float
    mr_api_base: str
    mr_project_id: int
    mr_challenge_name: str
    mr_upload_batch_size: int

    city: str = "toronto"
    city_name: str = "Toronto"
    data_dir: Path = ROOT / "data"
    manifest_path: Path = ROOT / "manifest.json"
    instructions_path: Path = ROOT / "instructions" / "interpolation.md"
    # Overpass: extra endpoints tried in turn when the main one keeps
    # shedding load, and how many tries each tile gets in all.
    overpass_fallback_urls: list[str] = field(default_factory=list)
    overpass_attempts: int = 5
    user_agent: str = "against-interpolation (Toronto OSM cleanup)"
    # Neighbourhoods: either a CKAN package_show URL (Toronto) or a URL that
    # serves GeoJSON directly (ArcGIS ...&f=geojson).
    hoods_url: str = _TORONTO_HOODS_URL
    hood_name_field: str = "AREA_NAME"
    # Which coverage categories become tasks. Toronto tasks only lines with a
    # City point to verify against; a city may also task the rest, with the
    # per-task `guidance` property saying what to do instead.
    task_categories: tuple[str, ...] = ("full", "partial")
    # A line with any node outside the neighbourhood polygons is held back:
    # the city's roster does not speak there.
    require_all_nodes_inside: bool = False
    # A neighbouring authority's address DB (same tracker schema). Any of its
    # points on the line's street, in its range and parity, within
    # match_radius_m, holds the line back: deleting it could lose them.
    neighbour_dbs: list[str] = field(default_factory=list)
    # Per-task `guidance` text by task kind (full, partial, uncovered,
    # same_number), embedded by the instruction as {{guidance}}. Toronto has
    # none, and its tasks carry no such property.
    guidance: dict[str, str] = field(default_factory=dict)
    mr_blurb: str = "Retire redundant addr:interpolation lines in Toronto."
    mr_checkin_comment: str = (
        "Removed redundant addr:interpolation line (Toronto Open Data points) "
        "#maproulette #toronto-interpolation-cleanup"
    )


def current_city() -> str | None:
    city = (os.environ.get(CITY_ENV) or "").strip().lower()
    return None if city in ("", "toronto") else city


def load(city: str | None = None) -> Config:
    city = city if city is not None else current_city()
    if city in ("", "toronto"):
        city = None
    path = ROOT / (f"config.{city}.toml" if city else "config.toml")
    if not path.exists():
        raise SystemExit(f"No {path.name} for city {city!r}.")
    with open(path, "rb") as f:
        cfg = tomllib.load(f)

    osm = cfg["osm"]
    bbox = tuple(osm.get("bbox") or osm["toronto_bbox"])
    assert len(bbox) == 4, "osm.bbox must have 4 numbers"
    c = cfg.get("city", {})
    cov = cfg["coverage"]
    mr = cfg["maproulette"]

    out = Config(
        t2_root=str((ROOT / cfg["t2"]["root"]).resolve()),
        t2_city_dir=str((ROOT / cfg["t2"].get("city_dir", cfg["t2"]["root"])).resolve()),
        toronto_bbox=bbox,  # type: ignore[arg-type]
        overpass_url=str(osm["overpass_url"]),
        tile_deg=float(osm["tile_deg"]),
        request_delay_s=float(osm.get("request_delay_s", 1.0)),
        match_radius_m=float(cov["match_radius_m"]),
        mr_api_base=str(mr["api_base"]),
        mr_project_id=int(mr["project_id"]),
        mr_challenge_name=str(mr["challenge_name"]),
        mr_upload_batch_size=int(mr.get("upload_batch_size", 1000)),
    )
    if city:
        out.city = city
        out.data_dir = ROOT / "data" / city
        out.manifest_path = ROOT / f"manifest.{city}.json"
    out.city_name = str(c.get("name", out.city_name))
    if "instructions" in mr:
        out.instructions_path = ROOT / mr["instructions"]
    out.overpass_fallback_urls = list(osm.get("fallback_urls", []))
    out.overpass_attempts = int(osm.get("attempts", out.overpass_attempts))
    out.user_agent = str(osm.get("user_agent", out.user_agent))
    out.hoods_url = str(c.get("neighbourhoods_url", out.hoods_url))
    out.hood_name_field = str(c.get("neighbourhood_name_field", out.hood_name_field))
    out.task_categories = tuple(cov.get("task_categories", out.task_categories))
    out.require_all_nodes_inside = bool(
        cov.get("require_all_nodes_inside", out.require_all_nodes_inside))
    out.neighbour_dbs = [str((ROOT / p).resolve()) for p in cov.get("neighbour_dbs", [])]
    out.guidance = {str(k): str(v) for k, v in cfg.get("guidance", {}).items()}
    out.mr_blurb = str(mr.get("blurb", out.mr_blurb))
    out.mr_checkin_comment = str(mr.get("checkin_comment", out.mr_checkin_comment))
    return out
