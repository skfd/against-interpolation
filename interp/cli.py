"""Command-line entry point: fetch -> build -> create."""
import argparse
import json
from collections import Counter
from pathlib import Path

from . import coverage, hoods, osm, tasks
from .config import Config, load

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
    from .t2bridge import source_db

    ways = osm.load_cached(cfg)
    snap = source_db.latest_snapshot_id()
    print(f"Building coverage against source snapshot {snap} for {len(ways)} ways...")
    index = coverage.build_index(snap)
    print(f"Indexed {sum(len(v) for v in index.values())} city points on "
          f"{len(index)} streets.")
    hood_polys = hoods.load(cfg.data_dir)
    print(f"Loaded {len(hood_polys)} neighbourhood polygons.")

    # Three-way split:
    #   outside  -- midpoint in no neighbourhood polygon: not Toronto, no task
    #   excluded -- Toronto, but uncovered/unknown: nothing to verify against
    #   tasks    -- full/partial coverage, tagged with its neighbourhood
    cats = Counter()
    by_hood = Counter()
    lines: list[str] = []
    excluded: list[str] = []
    outside: list[str] = []
    for way in ways:
        mid_lat, mid_lon = hoods.midpoint(way["geometry"])
        hood = hoods.locate(mid_lat, mid_lon, hood_polys)
        cov = coverage.coverage_for_way(way, index, cfg.match_radius_m)
        task_line = tasks.to_line(
            tasks.build_feature_collection(way, cov, neighbourhood=hood)
        )
        if hood is None:
            outside.append(task_line)
            continue
        cats[cov["category"]] += 1
        if cov["category"] in ("uncovered", "unknown"):
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
        "total_ways": len(ways),
        "task_count": len(lines),
        "excluded_count": len(excluded),
        "outside_count": len(outside),
        "by_category": dict(cats),
        "by_neighbourhood": dict(by_hood.most_common()),
        "match_radius_m": cfg.match_radius_m,
    }
    (cfg.data_dir / _SUMMARY_FILE).write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(f"\nWrote {len(lines)} tasks to {out}")
    print(f"Excluded {len(excluded)} uncovered/unknown Toronto ways -> "
          f"{cfg.data_dir / _EXCLUDED_FILE}")
    print(f"Cropped {len(outside)} ways outside Toronto -> "
          f"{cfg.data_dir / _OUTSIDE_FILE}")
    _print_summary(summary)


def cmd_stats(args, cfg: Config) -> None:
    path = cfg.data_dir / _SUMMARY_FILE
    if not path.exists():
        raise SystemExit("No summary.json — run `build` first.")
    _print_summary(json.loads(path.read_text(encoding="utf-8")))


def _print_summary(summary: dict) -> None:
    print("\nCoverage breakdown (Toronto ways):")
    by = summary["by_category"]
    total = sum(by.values()) or 1
    for cat in ("full", "partial", "uncovered", "unknown"):
        n = by.get(cat, 0)
        print(f"  {cat:<10} {n:>7}  ({100 * n / total:4.1f}%)")
    print(f"  {'TOTAL':<10} {total:>7}")
    if summary.get("outside_count"):
        print(f"  (+{summary['outside_count']} ways outside Toronto, cropped)")
    by_hood = summary.get("by_neighbourhood") or {}
    if by_hood:
        print(f"\nTasks span {len(by_hood)} neighbourhoods; largest:")
        for hood, n in list(by_hood.items())[:10]:
            print(f"  {n:>5}  {hood}")


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

    instruction = Path("instructions/interpolation.md").read_text(encoding="utf-8")

    if args.by_neighbourhood:
        # One challenge per neighbourhood, named "<base> - <neighbourhood>".
        groups: dict[str, list[str]] = {}
        for ln in task_lines:
            props = json.loads(ln.lstrip(chr(0x1e)))["features"][0]["properties"]
            hood = props.get("neighbourhood") or "(unassigned)"
            groups.setdefault(hood, []).append(ln)
        print(f"Plan: {len(groups)} neighbourhood challenges under project "
              f"{project_id} ({len(task_lines)} tasks total):")
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
            cfg.mr_api_base, project_id, full_name, instruction
        )
        print(f"Created challenge {challenge_id} '{full_name}'. Uploading "
              f"{len(lines)} tasks...")
        maproulette.add_tasks(cfg.mr_api_base, challenge_id, lines)
    print(
        f"Done. View: https://maproulette.org/admin/project/{project_id}"
    )


def main(argv=None) -> None:
    cfg = load()
    p = argparse.ArgumentParser(prog="against-interpolation")
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
    c.add_argument("--dry-run", action="store_true", help="validate, don't create")
    c.set_defaults(func=cmd_create)

    args = p.parse_args(argv)
    args.func(args, cfg)


if __name__ == "__main__":
    main()
