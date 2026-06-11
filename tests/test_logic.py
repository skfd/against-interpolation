"""Unit tests for the pure logic: parity ranges, coverage categorization,
point-to-line distance, task rendering. No network or DB."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from interp import geo  # noqa: E402
from interp.coverage import _parity_sequence, coverage_for_way  # noqa: E402
from interp import tasks  # noqa: E402


def test_parity_sequence():
    assert _parity_sequence(637, 655, "odd") == list(range(637, 656, 2))
    assert _parity_sequence(10, 28, "even") == list(range(10, 29, 2))
    assert _parity_sequence(1, 5, "all") == [1, 2, 3, 4, 5]
    # missing/odd parity tag falls back to every integer
    assert _parity_sequence(1, 4, None) == [1, 2, 3, 4]
    # reversed endpoints are normalized
    assert _parity_sequence(655, 637, "odd") == list(range(637, 656, 2))
    # an even start requested as odd skips to the first odd
    assert _parity_sequence(10, 16, "odd") == [11, 13, 15]


def test_point_to_polyline():
    # 1 deg lon at the equator-ish ref; use a short E-W segment.
    line = [(43.65, -79.40), (43.65, -79.39)]
    # a point right on the segment
    assert geo.point_to_polyline_m(43.65, -79.395, line) < 1.0
    # a point ~111 m north of the line (0.001 deg lat)
    d = geo.point_to_polyline_m(43.651, -79.395, line)
    assert 100 < d < 125
    # single-point line degrades to point distance
    assert geo.point_to_polyline_m(43.65, -79.40, [(43.65, -79.40)]) < 1.0


def _way(lo, hi, parity, street, geom):
    return {"way_id": 1, "lo": lo, "hi": hi, "parity": parity,
            "street": street, "geometry": geom, "source": "test"}


def test_coverage_full_partial_uncovered_unknown():
    geom = [(43.650, -79.400), (43.650, -79.399)]
    # index keyed by normalized street name
    pts = {
        "MAIN ST": [
            {"num": 1, "lat": 43.650, "lon": -79.3995, "apid": 11, "full": "1 Main St"},
            {"num": 3, "lat": 43.650, "lon": -79.3994, "apid": 13, "full": "3 Main St"},
        ]
    }
    full = coverage_for_way(_way(1, 3, "odd", "Main St", geom), pts, 150)
    assert full["category"] == "full" and full["present_count"] == 2

    partial = coverage_for_way(_way(1, 5, "odd", "Main St", geom), pts, 150)
    assert partial["category"] == "partial"
    assert [it["num"] for it in partial["items"] if not it["present"]] == [5]

    uncovered = coverage_for_way(_way(1, 3, "odd", "Elsewhere Rd", geom), pts, 150)
    assert uncovered["category"] == "uncovered" and uncovered["present_count"] == 0

    unknown = coverage_for_way(_way(4, 4, "even", "Main St", geom), pts, 150)
    assert unknown["category"] == "unknown"


def test_coverage_respects_radius():
    geom = [(43.650, -79.400), (43.650, -79.399)]
    # point on the right street + number but ~330 m away (0.003 deg lat)
    pts = {"MAIN ST": [
        {"num": 1, "lat": 43.653, "lon": -79.3995, "apid": 11, "full": "1 Main St"},
    ]}
    far = coverage_for_way(_way(1, 1, "all", "Main St", geom), pts, 150)
    # lo==hi -> unknown regardless; use a 2-number range to exercise the radius
    rng = coverage_for_way(_way(1, 3, "odd", "Main St", geom), pts, 150)
    assert rng["present_count"] == 0  # the only candidate is out of radius


def test_task_rendering():
    geom = [(43.650, -79.400), (43.650, -79.399)]
    way = _way(1, 3, "odd", "Main St", geom)
    cov = coverage_for_way(way, {"MAIN ST": [
        {"num": 1, "lat": 43.650, "lon": -79.3995, "apid": 11, "full": "1 Main St"},
        {"num": 3, "lat": 43.650, "lon": -79.3994, "apid": 13, "full": "3 Main St"},
    ]}, 150)
    fc = tasks.build_feature_collection(way, cov)
    props = fc["features"][0]["properties"]
    assert props["osm_way"] == "way/1"
    assert props["coverage_category"] == "full"
    assert props["range"] == "1-3 (odd)"
    assert props["housenumbers"] == "1, 3"
    assert fc["features"][0]["geometry"]["type"] == "LineString"
    # GeoJSON coordinates are lon,lat
    assert fc["features"][0]["geometry"]["coordinates"][0] == [-79.400, 43.650]

    line = tasks.to_line(fc)
    assert line.startswith(chr(0x1e))
    assert "\n" not in line
