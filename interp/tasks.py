"""Stage 2 output: turn each interpolation way + its coverage into one
MapRoulette task (a GeoJSON FeatureCollection). Tasks are written
record-separator-delimited (one FeatureCollection per line, each prefixed with
\\u001e) — the line-by-line GeoJSON format MapRoulette ingests.

Each task's single feature is the interpolation LineString, so the task locates
on the line and an editor can load the way directly. The City house numbers
that replace the line are rendered into the `housenumbers` property, which the
challenge instruction embeds via mustache `{{housenumbers}}`.
"""
import json

RS = ""


def _range_label(way: dict) -> str:
    lo, hi, parity = way.get("lo"), way.get("hi"), way.get("parity") or "all"
    if lo is None or hi is None:
        return f"unknown ({parity})"
    return f"{lo}-{hi} ({parity})"


def _housenumbers(cov: dict) -> str:
    """Plain comma-separated list of the house numbers the City has points for.

    The City data is the ground truth for which addresses are real; the
    interpolation's in-between numbers are only estimates, so we list what the
    City actually has rather than enumerating the parity range.
    """
    nums = [str(it["num"]) for it in cov["items"] if it["present"]]
    if not nums:
        return "_(no City points found in this range)_"
    return ", ".join(nums)


def build_feature_collection(
    way: dict, cov: dict, neighbourhood: str | None = None
) -> dict:
    osm_way = f"way/{way['way_id']}"
    coords = [[lon, lat] for lat, lon in way["geometry"]]  # GeoJSON is lon,lat
    properties = {
        "@id": osm_way,
        "osm_way": osm_way,
        "street": way.get("street") or "(unknown street)",
        "range": _range_label(way),
        "coverage_category": cov["category"],  # kept for build stats / filtering
        "source": way.get("source") or "(none)",
        "housenumbers": _housenumbers(cov),
        "neighbourhood": neighbourhood or "",
    }
    geometry = (
        {"type": "LineString", "coordinates": coords}
        if len(coords) >= 2
        else {"type": "Point", "coordinates": coords[0]}
    )
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": geometry, "properties": properties}
        ],
    }


def to_line(fc: dict) -> str:
    """One RS-prefixed, newline-free JSON line for the tasks file."""
    return RS + json.dumps(fc, ensure_ascii=False, separators=(",", ":"))
