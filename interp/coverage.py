"""Stage 2: for each interpolation way, which housenumbers in its range does
the Toronto source repository actually have a real address point for?

This is the evidence a mapper needs before deleting the line: a fully-covered
range is redundant with real points; a partially-covered one is not yet safe.

We load every single-point Toronto address once, bucketed by normalized
street, then answer each way in memory (one pass, no per-way SQL).
"""
import sqlite3
from collections import defaultdict

from . import geo
from .config import Config
from .t2bridge import normalize_street, source_db


def _parity_sequence(lo: int, hi: int, parity: str | None) -> list[int]:
    lo, hi = (lo, hi) if lo <= hi else (hi, lo)
    p = (parity or "").strip().lower()
    if p == "odd":
        start = lo if lo % 2 == 1 else lo + 1
        return list(range(start, hi + 1, 2))
    if p == "even":
        start = lo if lo % 2 == 0 else lo + 1
        return list(range(start, hi + 1, 2))
    # "all", a numeric step, "alphabetic", or missing -> every integer.
    return list(range(lo, hi + 1))


def build_index(snap_id: int) -> dict[str, list[dict]]:
    """{normalized_street: [{num, lat, lon, apid, full}, ...]} over all active
    single-point (hi_num IS NULL) Toronto addresses."""
    # The engine's tracker schema is city-generic; expr() projects the logical
    # fields (lo_num, street, ...) through Toronto's [source_fields] recipe.
    lo = source_db.expr("lo_num", "")
    hi = source_db.expr("hi_num", "")
    if lo == "NULL":
        # A source with no range fields (Guelph publishes one number per
        # point): the point's own number is its lo_num, and hi_num is NULL
        # for every row. Without this every point was filtered out and every
        # line read `uncovered`.
        lo = f"CAST({source_db.expr('number', '')} AS INTEGER)"
    conn = source_db.connect_readonly()
    try:
        rows = conn.execute(
            f"SELECT {lo} AS lo_num, "
            f"       {source_db.expr('street', '')} AS linear_name_full, "
            "       latitude, longitude, "
            "       identity_key AS address_point_id, "
            f"       {source_db.expr('full', '')} AS address_full "
            "FROM addresses "
            f"WHERE max_snapshot_id=? AND {hi} IS NULL AND {lo} IS NOT NULL",
            (snap_id,),
        ).fetchall()
    finally:
        conn.close()

    index: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["latitude"] is None or r["longitude"] is None:
            continue
        index[normalize_street(r["linear_name_full"])].append(
            {
                "num": int(r["lo_num"]),
                "lat": r["latitude"],
                "lon": r["longitude"],
                "apid": r["address_point_id"],
                "full": r["address_full"],
            }
        )
    return index


def neighbour_index(db_path: str) -> dict[str, list[dict]]:
    """{normalized_street: [{num, lat, lon}]} from a neighbouring authority's
    tracker DB (same `addresses` schema, plain `number`/`street` columns),
    latest snapshot. Guelph's is Wellington County: past the city limit the
    City's roster says nothing, and the County's points are what a deleted
    line could lose."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        latest = conn.execute(
            "SELECT max(max_snapshot_id) FROM addresses").fetchone()[0]
        rows = conn.execute(
            "SELECT number, street, latitude, longitude FROM addresses "
            "WHERE max_snapshot_id=?", (latest,)).fetchall()
    finally:
        conn.close()
    index: dict[str, list[dict]] = defaultdict(list)
    for number, street, lat, lon in rows:
        if lat is None or lon is None or not str(number or "").isdigit():
            continue
        index[normalize_street(street)].append(
            {"num": int(number), "lat": lat, "lon": lon})
    return index


def neighbour_hits(way: dict, index: dict[str, list[dict]],
                   radius_m: float) -> list[int]:
    """Neighbour-source numbers on the line's street, in its range (ends
    included) and parity, within radius_m of the line."""
    lo, hi, street = way.get("lo"), way.get("hi"), way.get("street")
    geom = [tuple(p) for p in way.get("geometry", [])]
    if lo is None or hi is None or lo == hi or not street or not geom:
        return []
    wanted = set(_parity_sequence(lo, hi, way.get("parity")))
    return sorted({
        p["num"] for p in index.get(normalize_street(street), [])
        if p["num"] in wanted
        and geo.point_to_polyline_m(p["lat"], p["lon"], geom) <= radius_m
    })


def coverage_for_way(
    way: dict, index: dict[str, list[dict]], radius_m: float
) -> dict:
    """Return a coverage record:
        {category, present_count, total, items: [{num, present, full, lat, lon, apid}]}
    category in {full, partial, uncovered, unknown}."""
    lo, hi, street = way.get("lo"), way.get("hi"), way.get("street")
    geom = [tuple(p) for p in way.get("geometry", [])]
    if lo is None or hi is None or lo == hi or not street or not geom:
        return {"category": "unknown", "present_count": 0, "total": 0, "items": []}

    seq = _parity_sequence(lo, hi, way.get("parity"))
    bucket = index.get(normalize_street(street), [])
    line_bbox = geo.bbox_of(geom)
    # Pad the line bbox by ~radius (deg) so a nearby point isn't pre-filtered out.
    pad = radius_m / 111_320.0
    nums_wanted = set(seq)
    candidates = [
        p
        for p in bucket
        if p["num"] in nums_wanted
        and line_bbox[0] - pad <= p["lat"] <= line_bbox[2] + pad
        and line_bbox[1] - pad <= p["lon"] <= line_bbox[3] + pad
    ]
    # Nearest in-radius point per number.
    best: dict[int, dict] = {}
    for p in candidates:
        d = geo.point_to_polyline_m(p["lat"], p["lon"], geom)
        if d > radius_m:
            continue
        cur = best.get(p["num"])
        if cur is None or d < cur["_dist"]:
            best[p["num"]] = {**p, "_dist": d}

    items = []
    present_count = 0
    for n in seq:
        hit = best.get(n)
        if hit is not None:
            present_count += 1
            items.append(
                {
                    "num": n,
                    "present": True,
                    "full": hit["full"],
                    "lat": hit["lat"],
                    "lon": hit["lon"],
                    "apid": hit["apid"],
                }
            )
        else:
            items.append({"num": n, "present": False})

    total = len(seq)
    if present_count == 0:
        category = "uncovered"
    elif present_count == total:
        category = "full"
    else:
        category = "partial"
    return {
        "category": category,
        "present_count": present_count,
        "total": total,
        "items": items,
    }
