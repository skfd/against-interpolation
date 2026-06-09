"""Stage 2 output: turn each interpolation way + its coverage into one
MapRoulette task (a GeoJSON FeatureCollection). Tasks are written
record-separator-delimited (one FeatureCollection per line, each prefixed with
\\u001e) — the line-by-line GeoJSON format MapRoulette ingests.

Each task's single feature is the interpolation LineString, so the task locates
on the line and an editor can load the way directly. The City point positions
(the answer to "what replaces this line") are rendered into the
`addresses_block` property, which the challenge instruction embeds via
mustache `{{addresses_block}}`.
"""
import json

RS = ""


def _range_label(way: dict) -> str:
    lo, hi, parity = way.get("lo"), way.get("hi"), way.get("parity") or "all"
    if lo is None or hi is None:
        return f"unknown ({parity})"
    return f"{lo}-{hi} ({parity})"


def _coverage_label(cov: dict) -> str:
    cat, p, t = cov["category"], cov["present_count"], cov["total"]
    if cat == "full":
        return f"full ({p}/{t} present)"
    if cat == "partial":
        return f"partial ({p}/{t} present)"
    if cat == "uncovered":
        return f"none (0/{t} present)"
    return "unknown (could not determine range)"


def _addresses_block(cov: dict) -> str:
    if cov["category"] == "unknown" or not cov["items"]:
        return "_Range could not be determined from the way's endpoints._"
    lines = []
    for it in cov["items"]:
        n = it["num"]
        if it["present"]:
            lat, lon = it["lat"], it["lon"]
            edit = f"https://www.openstreetmap.org/edit#map=21/{lat:.6f}/{lon:.6f}"
            lines.append(
                f"- **{n}** - {it['full']}  "
                f"({lat:.6f}, {lon:.6f}) [edit]({edit})  "
                f"`city_id={it['apid']}`"
            )
        else:
            lines.append(f"- **{n}** - NO CITY POINT")
    return "\n".join(lines)


def build_feature_collection(way: dict, cov: dict) -> dict:
    osm_way = f"way/{way['way_id']}"
    coords = [[lon, lat] for lat, lon in way["geometry"]]  # GeoJSON is lon,lat
    properties = {
        "@id": osm_way,
        "osm_way": osm_way,
        "street": way.get("street") or "(unknown street)",
        "range": _range_label(way),
        "coverage": _coverage_label(cov),
        "coverage_category": cov["category"],
        "source": way.get("source") or "(none)",
        "count_present": cov["present_count"],
        "count_total": cov["total"],
        "addresses_block": _addresses_block(cov),
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
