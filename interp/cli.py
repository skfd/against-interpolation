"""Command-line entry point: fetch -> build -> create."""
import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import coverage, hoods, osm, tasks
from .config import CITY_ENV, Config, load

_TASKS_FILE = "tasks.geojson"
_EXCLUDED_FILE = "excluded.geojson"
_OUTSIDE_FILE = "outside.geojson"
_SUMMARY_FILE = "summary.json"


def _parse_bbox(s: str | None, cfg: Config) -> tuple[float, float, float, float]:
    if not s:
        return cfg.toronto_bbox
    parts = [float(x) for x in s.split(",")]
    if len(parts) != 4:
        raise SystemExit("--bbox must be 'min_lat,min_lon,max_lat,max_lon'")
    return tuple(parts)  # type: ignore[return-value]


def cmd_fetch(args, cfg: Config) -> None:
    if args.bbox:
        cfg.toronto_bbox = _parse_bbox(args.bbox, cfg)
    ways = osm.fetch(cfg, force=args.force)
    print(f"Fetched {len(ways)} interpolation ways.")


def cmd_build(args, cfg: Config) -> None:
    from .t2bridge import BOUND_CITY, BOUND_CITY_DIR, source_db

    if BOUND_CITY != cfg.city:
        raise SystemExit(
            f"The t2 engine is bound to {BOUND_CITY!r} ({BOUND_CITY_DIR}), not "
            f"{cfg.city!r}. Run through run.py, which sets the city before "
            f"the engine is imported.")
    ways = osm.load_cached(cfg)
    snap = source_db.latest_snapshot_id()
    print(f"Building coverage against source snapshot {snap} for {len(ways)} ways...")
    index = coverage.build_index(snap)
    print(f"Indexed {sum(len(v) for v in index.values())} city points on "
          f"{len(index)} streets.")
    hood_polys = hoods.load(cfg.data_dir, cfg.hoods_url, cfg.hood_name_field,
                            cfg.city_name)
    print(f"Loaded {len(hood_polys)} neighbourhood polygons.")
    neighbours = {}
    for db in cfg.neighbour_dbs:
        for street, pts in coverage.neighbour_index(db).items():
            neighbours.setdefault(street, []).extend(pts)
    if cfg.neighbour_dbs:
        print(f"Indexed {sum(len(v) for v in neighbours.values())} neighbour "
              f"points from {len(cfg.neighbour_dbs)} source(s).")

    # Three-way split:
    #   outside  -- midpoint in no neighbourhood polygon: not Toronto, no task
    #   excluded -- Toronto, but uncovered/unknown: nothing to verify against
    #   tasks    -- full/partial coverage, tagged with its neighbourhood
    cats = Counter()
    kinds = Counter()
    held_by = Counter()
    by_hood = Counter()
    lines: list[str] = []
    excluded: list[str] = []
    outside: list[str] = []
    for way in ways:
        mid_lat, mid_lon = hoods.midpoint(way["geometry"])
        hood = hoods.locate(mid_lat, mid_lon, hood_polys)
        cov = coverage.coverage_for_way(way, index, cfg.match_radius_m)
        kind = _task_kind(way, cov, index)
        held = None
        if hood is not None:
            if cfg.require_all_nodes_inside and any(
                    hoods.locate(lat, lon, hood_polys) is None
                    for lat, lon in way["geometry"]):
                held = "outside-city"
            elif neighbours and (hits := coverage.neighbour_hits(
                    way, neighbours, cfg.match_radius_m)):
                held = "neighbour-addresses: " + ", ".join(map(str, hits))
        task_line = tasks.to_line(
            tasks.build_feature_collection(
                way, cov, neighbourhood=hood,
                guidance=cfg.guidance.get(kind) if cfg.guidance else None,
                held=held,
            )
        )
        if hood is None:
            outside.append(task_line)
            continue
        cats[cov["category"]] += 1
        kinds[kind] += 1
        if held:
            held_by[held.split(":")[0]] += 1
        if held or kind not in cfg.task_categories:
            excluded.append(task_line)
        else:
            lines.append(task_line)
            by_hood[hood] += 1

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.data_dir / _TASKS_FILE
    out.write_text("\n".join(lines), encoding="utf-8")
    (cfg.data_dir / _EXCLUDED_FILE).write_text(
        "\n".join(excluded), encoding="utf-8"
    )
    (cfg.data_dir / _OUTSIDE_FILE).write_text(
        "\n".join(outside), encoding="utf-8"
    )

    summary = {
        "source_snapshot": snap,
        "fetched_at": osm.fetched_at(cfg),
        "total_ways": len(ways),
        "task_count": len(lines),
        "excluded_count": len(excluded),
        "outside_count": len(outside),
        "by_category": dict(cats),
        **({"by_kind": dict(kinds), "held": dict(held_by)}
           if cfg.guidance or cfg.neighbour_dbs or cfg.require_all_nodes_inside
           else {}),
        "by_neighbourhood": dict(by_hood.most_common()),
        "match_radius_m": cfg.match_radius_m,
    }
    (cfg.data_dir / _SUMMARY_FILE).write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(f"\nWrote {len(lines)} tasks to {out}")
    print(f"Excluded {len(excluded)} {cfg.city_name} ways held back -> "
          f"{cfg.data_dir / _EXCLUDED_FILE}")
    print(f"Cropped {len(outside)} ways outside {cfg.city_name} -> "
          f"{cfg.data_dir / _OUTSIDE_FILE}")
    _print_summary(summary, cfg.city_name)


def _task_kind(way: dict, cov: dict, index: dict) -> str:
    """The coverage category, refined where the category hides the reason:

    same_number       an `unknown` line whose two numbered nodes carry the same
                      number. N to N interpolates nothing, which is a reason to
                      delete it, not a reason it can't be read.
    unmatched_street  an `uncovered` line on a street the source has no points
                      on at all (Glenholme for Glenholm Drive). "No address in
                      range" means nothing there; the end nodes want fixing.
    """
    from .t2bridge import normalize_street

    if (cov["category"] == "unknown" and len(way.get("anchors") or []) >= 2
            and way.get("lo") is not None and way.get("lo") == way.get("hi")):
        return "same_number"
    if (cov["category"] == "uncovered" and way.get("street")
            and normalize_street(way["street"]) not in index):
        return "unmatched_street"
    return cov["category"]


def cmd_stats(args, cfg: Config) -> None:
    path = cfg.data_dir / _SUMMARY_FILE
    if not path.exists():
        raise SystemExit("No summary.json — run `build` first.")
    _print_summary(json.loads(path.read_text(encoding="utf-8")), cfg.city_name)


def _print_summary(summary: dict, city_name: str = "Toronto") -> None:
    print(f"\nCoverage breakdown ({city_name} ways):")
    by = summary["by_category"]
    total = sum(by.values()) or 1
    for cat in ("full", "partial", "uncovered", "unknown"):
        n = by.get(cat, 0)
        print(f"  {cat:<10} {n:>7}  ({100 * n / total:4.1f}%)")
    print(f"  {'TOTAL':<10} {total:>7}")
    if summary.get("outside_count"):
        print(f"  (+{summary['outside_count']} ways outside {city_name}, cropped)")
    by_hood = summary.get("by_neighbourhood") or {}
    if by_hood:
        print(f"\nTasks span {len(by_hood)} neighbourhoods; largest:")
        for hood, n in list(by_hood.items())[:10]:
            print(f"  {n:>5}  {hood}")


def _summary_fetched_at(cfg: Config) -> str | None:
    path = cfg.data_dir / _SUMMARY_FILE
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("fetched_at")


def _warn_if_stale(fetched: str | None) -> None:
    if not fetched:
        print("Note: fetch timestamp unknown (old cache format).")
        return
    age = datetime.now(timezone.utc) - datetime.fromisoformat(fetched)
    print(f"OSM data fetched {age.days} day(s) ago ({fetched}).")
    if age.days > 7:
        print("WARNING: the fetch is over a week old. OSM has moved since; "
              "consider `fetch --force` + `build` before uploading.")


def _record_in_manifest(
    path, project_id: int, challenge_id: int, name: str, hood: str | None,
    lines: list[str], fetched: str | None,
) -> None:
    """Append a created challenge (and the way ids it covers) to the committed
    manifest, so `refresh` can diff live tasks against current OSM."""
    manifest = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {"project_id": project_id, "challenges": {}}
    )
    way_ids = [
        int(json.loads(ln.lstrip(chr(0x1e)))["features"][0]["properties"]
            ["osm_way"].split("/")[1])
        for ln in lines
    ]
    manifest["challenges"][str(challenge_id)] = {
        "name": name,
        "neighbourhood": hood,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fetched_at": fetched,
        "task_count": len(way_ids),
        "way_ids": way_ids,
    }
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def cmd_create(args, cfg: Config) -> None:
    from . import maproulette

    project_id = args.project_id or cfg.mr_project_id
    challenge_name = args.name or cfg.mr_challenge_name
    if not project_id:
        raise SystemExit(
            "No project id. Set maproulette.project_id in config.toml or pass "
            "--project-id."
        )

    tasks_path = cfg.data_dir / _TASKS_FILE
    if not tasks_path.exists():
        raise SystemExit("No tasks.geojson — run `build` first.")
    # Split on "\n" only — NOT splitlines(): the  record-separator prefix
    # on each line is itself a line boundary to str.splitlines().
    task_lines = [
        ln for ln in tasks_path.read_text(encoding="utf-8").split("\n") if ln.strip()
    ]
    if args.limit:
        task_lines = task_lines[: args.limit]

    instruction = cfg.instructions_path.read_text(encoding="utf-8")

    fetched = _summary_fetched_at(cfg)
    _warn_if_stale(fetched)

    if args.by_neighbourhood:
        # One challenge per neighbourhood, named "<base> - <neighbourhood>".
        groups: dict[str, list[str]] = {}
        for ln in task_lines:
            props = json.loads(ln.lstrip(chr(0x1e)))["features"][0]["properties"]
            hood = props.get("neighbourhood") or "(unassigned)"
            groups.setdefault(hood, []).append(ln)
        if args.hoods:
            wanted = {h.strip().lower() for h in args.hoods.split(",")}
            missing = wanted - {k.lower() for k in groups}
            if missing:
                raise SystemExit(
                    f"No tasks for requested neighbourhood(s): {', '.join(sorted(missing))}"
                )
            groups = {k: v for k, v in groups.items() if k.lower() in wanted}
        print(f"Plan: {len(groups)} neighbourhood challenges under project "
              f"{project_id} ({sum(len(v) for v in groups.values())} tasks total):")
        for hood in sorted(groups):
            print(f"  {len(groups[hood]):>5}  {challenge_name} - {hood}")
    else:
        groups = {None: task_lines}
        print(f"Plan: create challenge '{challenge_name}' under project "
              f"{project_id} with {len(task_lines)} tasks.")

    if args.dry_run:
        # Offline-friendly preview: validate if a key is present, else just warn.
        try:
            name = maproulette.validate_project(cfg.mr_api_base, project_id)
            print(f"  project OK: {name}")
        except maproulette.MaprouletteError as e:
            print(f"  (skipped project validation: {e})")
        print("--dry-run: stopping before creating the challenge.")
        return

    print(f"Validating project {project_id}...")
    name = maproulette.validate_project(cfg.mr_api_base, project_id)
    print(f"  project OK: {name}")

    for hood, lines in sorted(groups.items(), key=lambda kv: kv[0] or ""):
        full_name = f"{challenge_name} - {hood}" if hood else challenge_name
        challenge_id = maproulette.create_challenge(
            cfg.mr_api_base, project_id, full_name, instruction,
            blurb=cfg.mr_blurb, checkin_comment=cfg.mr_checkin_comment,
        )
        print(f"Created challenge {challenge_id} '{full_name}'. Uploading "
              f"{len(lines)} tasks...")
        maproulette.add_tasks(cfg.mr_api_base, challenge_id, lines)
        _record_in_manifest(
            cfg.manifest_path, project_id, challenge_id, full_name, hood,
            lines, fetched,
        )
    print(
        f"Done. View: https://maproulette.org/admin/project/{project_id}"
    )


def cmd_refresh(args, cfg: Config) -> None:
    from . import maproulette, refresh

    manifest_path = cfg.manifest_path
    if not manifest_path.exists():
        raise SystemExit(f"No {manifest_path.name} — nothing to refresh "
                         f"(run `create` first).")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    ways = osm.load_cached(cfg)
    live_ids = {w["way_id"] for w in ways}
    cache_fetched = osm.fetched_at(cfg)
    built_from = _summary_fetched_at(cfg)
    if cache_fetched and built_from and cache_fetched != built_from:
        raise SystemExit(
            f"tasks.geojson was built from a different fetch ({built_from}) "
            f"than the cache ({cache_fetched}). Run `build` first."
        )
    _warn_if_stale(cache_fetched)

    tasks_path = cfg.data_dir / _TASKS_FILE
    if not tasks_path.exists():
        raise SystemExit("No tasks.geojson — run `build` first.")
    task_lines = [
        ln for ln in tasks_path.read_text(encoding="utf-8").split("\n") if ln.strip()
    ]
    hood_lines = refresh.lines_by_hood(task_lines)

    entries, orphan_hoods = refresh.plan(manifest, live_ids, hood_lines)
    if args.hoods:
        wanted = {h.strip().lower() for h in args.hoods.split(",")}
        missing = wanted - {(e["neighbourhood"] or "").lower() for e in entries}
        if missing:
            raise SystemExit(
                f"No challenge for requested neighbourhood(s): "
                f"{', '.join(sorted(missing))}"
            )
        entries = [
            e for e in entries if (e["neighbourhood"] or "").lower() in wanted
        ]

    todo = [e for e in entries if e["gone"] or e["new"]]
    total_gone = sum(len(e["gone"]) for e in todo)
    total_new = sum(len(e["new"]) for e in todo)
    print(f"\nPlan: {len(todo)}/{len(entries)} challenges need changes "
          f"({total_gone} ways gone from OSM, {total_new} new tasks):")
    for e in todo:
        print(f"  -{len(e['gone']):>4} +{len(e['new']):>4}  {e['name']}")
    if orphan_hoods:
        print(f"\n{len(orphan_hoods)} neighbourhood(s) in the build have no "
              f"challenge (use `create --by-neighbourhood --hoods ...`):")
        for hood in orphan_hoods:
            print(f"  {len(hood_lines[hood]):>5}  {hood}")

    if args.dry_run:
        print("--dry-run: stopping before touching MapRoulette.")
        return
    if not todo:
        print("Nothing to do.")
        return

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for e in todo:
        cid = e["challenge_id"]
        ch = manifest["challenges"][str(cid)]
        print(f"\n{e['name']} (challenge {cid}):")
        # Live task list (name "way/<id>" -> id/status), used both to skip
        # tasks a mapper already closed and to make re-runs idempotent.
        by_way: dict[int, dict] = {}
        for t in maproulette.get_tasks(cfg.mr_api_base, cid):
            if t["name"].startswith("way/"):
                by_way[int(t["name"].split("/")[1])] = t
        if e["gone"]:
            to_mark, closed, not_found = [], 0, 0
            for way_id in e["gone"]:
                t = by_way.get(way_id)
                if t is None:
                    not_found += 1
                elif t["status"] in maproulette.REFRESHABLE_STATUSES:
                    to_mark.append(t["id"])
                else:
                    closed += 1
            print(f"  {len(e['gone'])} ways gone from OSM: marking "
                  f"{len(to_mark)} alreadyFixed ({closed} already closed by "
                  f"mappers, {not_found} not found in MR)")
            maproulette.set_task_statuses(
                cfg.mr_api_base, to_mark, maproulette.STATUS_ALREADY_FIXED
            )
        if e["new"]:
            # Skip ways MR already has a task for (interrupted earlier run).
            to_upload = [w for w in e["new"] if w not in by_way]
            if len(to_upload) < len(e["new"]):
                print(f"  {len(e['new']) - len(to_upload)} new task(s) already "
                      f"in MR (resumed run); skipping those")
            if to_upload:
                lines = [hood_lines[e["neighbourhood"]][w] for w in to_upload]
                print(f"  uploading {len(lines)} new tasks...")
                maproulette.add_tasks(cfg.mr_api_base, cid, lines)
            # Record all of e["new"]: after this block they all exist in MR.
            ch["way_ids"].extend(e["new"])
            ch["task_count"] = len(ch["way_ids"])
        ch["refreshed_at"] = now
        # Write after every challenge so an interrupted run can resume.
        manifest_path.write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
    print("\nDone.")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="against-interpolation")
    p.add_argument("--city", default="toronto",
                   help="toronto (config.toml, the default) or <city> "
                        "(config.<city>.toml, data/<city>/, manifest.<city>.json)")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="enumerate interpolation ways from OSM")
    f.add_argument("--bbox", help="min_lat,min_lon,max_lat,max_lon (default: config)")
    f.add_argument("--force", action="store_true", help="ignore cache")
    f.set_defaults(func=cmd_fetch)

    b = sub.add_parser("build", help="compute coverage + write MapRoulette tasks")
    b.set_defaults(func=cmd_build)

    s = sub.add_parser("stats", help="print the last build's coverage breakdown")
    s.set_defaults(func=cmd_stats)

    c = sub.add_parser("create", help="create the MapRoulette challenge + upload")
    c.add_argument("--project-id", type=int, help="override config project id")
    c.add_argument("--name", help="override config challenge name")
    c.add_argument("--limit", type=int, help="upload only the first N tasks")
    c.add_argument("--by-neighbourhood", action="store_true",
                   help="one challenge per neighbourhood instead of one big one")
    c.add_argument("--hoods",
                   help="comma-separated neighbourhood filter (with --by-neighbourhood)")
    c.add_argument("--dry-run", action="store_true", help="validate, don't create")
    c.set_defaults(func=cmd_create)

    r = sub.add_parser(
        "refresh",
        help="sync live challenges with a fresh fetch+build: close tasks for "
             "ways gone from OSM, upload tasks for new ways",
    )
    r.add_argument("--hoods", help="comma-separated neighbourhood filter")
    r.add_argument("--dry-run", action="store_true",
                   help="print the diff, change nothing")
    r.set_defaults(func=cmd_refresh)

    args = p.parse_args(argv)
    # Before load() and before anything imports t2bridge, which reads the
    # config at import time to point the engine at the city checkout.
    os.environ[CITY_ENV] = args.city
    cfg = load()
    args.func(args, cfg)


if __name__ == "__main__":
    main()
