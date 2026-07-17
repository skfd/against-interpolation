"""Refresh planning: diff the committed manifest against a fresh OSM fetch and
the current build, one entry per live challenge. Pure logic — no network.

The rules (mapper statuses always win; only ever act on still-open tasks):
  * a way in the manifest but gone from the fresh OSM fetch -> its task should
    be closed (someone removed the way outside MapRoulette). Which statuses may
    be overwritten is the caller's concern (see maproulette.REFRESHABLE_STATUSES).
  * a way in the current build but in no manifest challenge -> a new task for
    its neighbourhood's challenge.
  * a way in both -> leave alone. Note "gone" means gone from the raw fetch,
    NOT from tasks.geojson: a way can drop out of the build (e.g. coverage
    shifted to uncovered) while still existing in OSM.
"""
import json

from .tasks import RS


def lines_by_hood(task_lines: list[str]) -> dict[str, dict[int, str]]:
    """Group tasks.geojson lines as {neighbourhood: {way_id: line}}."""
    out: dict[str, dict[int, str]] = {}
    for ln in task_lines:
        props = json.loads(ln.lstrip(RS))["features"][0]["properties"]
        way_id = int(props["osm_way"].split("/")[1])
        hood = props.get("neighbourhood") or "(unassigned)"
        out.setdefault(hood, {})[way_id] = ln
    return out


def plan(
    manifest: dict,
    live_way_ids: set[int],
    hood_lines: dict[str, dict[int, str]],
) -> tuple[list[dict], list[str]]:
    """Return (entries, orphan_hoods).

    entries: one dict per manifest challenge (sorted by neighbourhood) with
      challenge_id, name, neighbourhood, gone (way ids to close) and new
      (way ids to upload).
    orphan_hoods: neighbourhoods present in the build but with no challenge
      in the manifest (needs `create --by-neighbourhood --hoods ...`).
    """
    challenges = manifest["challenges"]
    # A way already tracked by ANY challenge is never "new" — guards against
    # double-uploading a way whose neighbourhood assignment shifted.
    claimed = {w for ch in challenges.values() for w in ch["way_ids"]}

    entries = []
    for cid, ch in challenges.items():
        hood = ch["neighbourhood"]
        manifest_ways = set(ch["way_ids"])
        entries.append({
            "challenge_id": int(cid),
            "name": ch["name"],
            "neighbourhood": hood,
            "gone": sorted(manifest_ways - live_way_ids),
            "new": sorted(
                w for w in hood_lines.get(hood, {}) if w not in claimed
            ),
        })
    entries.sort(key=lambda e: e["neighbourhood"] or "")

    covered = {ch["neighbourhood"] for ch in challenges.values()}
    orphan_hoods = sorted(set(hood_lines) - covered)
    return entries, orphan_hoods
