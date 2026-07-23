"""Load config.toml from the project root."""
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    t2_root: str
    toronto_bbox: tuple[float, float, float, float]
    overpass_url: str
    tile_deg: float
    request_delay_s: float
    match_radius_m: float
    mr_api_base: str
    mr_project_id: int
    mr_challenge_name: str
    mr_upload_batch_size: int

    data_dir: Path = ROOT / "data"


def load() -> Config:
    with open(ROOT / "config.toml", "rb") as f:
        cfg = tomllib.load(f)

    bbox = tuple(cfg["osm"]["toronto_bbox"])
    assert len(bbox) == 4, "osm.toronto_bbox must have 4 numbers"

    return Config(
        t2_root=str((ROOT / cfg["t2"]["root"]).resolve()),
        toronto_bbox=bbox,  # type: ignore[arg-type]
        overpass_url=str(cfg["osm"]["overpass_url"]),
        tile_deg=float(cfg["osm"]["tile_deg"]),
        request_delay_s=float(cfg["osm"].get("request_delay_s", 1.0)),
        match_radius_m=float(cfg["coverage"]["match_radius_m"]),
        mr_api_base=str(cfg["maproulette"]["api_base"]),
        mr_project_id=int(cfg["maproulette"]["project_id"]),
        mr_challenge_name=str(cfg["maproulette"]["challenge_name"]),
        mr_upload_batch_size=int(cfg["maproulette"].get("upload_batch_size", 1000)),
    )
