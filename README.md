# against-interpolation

Generates MapRoulette tasks to retire redundant `addr:interpolation` lines in
Toronto. This is the cleanup phase that the sibling
[`toronto-2-address-import`](https://github.com/skfd/toronto-2-address-import)
project deferred as out of scope: now that the City's per-address points are in
OSM, the old StatCan/CanVec interpolation lines that span the same blocks can be
removed.

One MapRoulette task is created **per interpolation line**. Each task shows the
house numbers the City actually has for the block (the ground truth — the
interpolation's in-between numbers are only estimates and many never existed)
and walks a mapper through two steps:

1. **Verify the addresses** — every City house number present as an individual
   node, or as an address on a building when that building has only the one
   address. The [Toronto Address Layer](https://skfd.github.io/toronto-addresses-layer/)
   helps spot misaligned or missing ones.
2. **Remove the interpolation line** — delete the endpoint nodes (the editor
   takes the way with them); keep an endpoint that is part of a building or
   carries other tags.

Each line is assigned to one of the City's 158 neighbourhoods by
point-in-polygon on its midpoint (boundaries auto-downloaded from Toronto Open
Data). Because the neighbourhood polygons union to exactly the city boundary,
this doubles as the Toronto crop: ways whose midpoint falls in no polygon (the
fetch bbox bleeds into Mississauga/Vaughan/Markham) go to `data/outside.geojson`
and get no task. Lines whose range can't be read (`unknown`) or with **zero**
matching City points (`uncovered`) are likewise held back in
`data/excluded.geojson` for manual review: a task with an empty house-number
list gives a mapper nothing to verify against.

## How it relates to the sibling projects

- **Data** comes from
  [`toronto-2-address-import`](https://github.com/skfd/toronto-2-address-import),
  which `build` requires. We import its `t2` package read-only for the Toronto
  address DB (`source_db`) and the street-name normalizer
  (`conflate.normalize_street`). Set its location in `config.toml` under
  `[t2] root` — the default `../toronto-2-address-import` works when both repos
  are cloned side by side. That project's own `config.toml` supplies the SQLite
  path, so we don't duplicate it.
- **MapRoulette task shape** mirrors `bikeshare-toronto-maproulette`:
  record-separator-delimited GeoJSON (one `FeatureCollection` per line, each
  prefixed with a `U+001E` record separator), with the challenge instruction in
  `instructions/interpolation.md` and `{{property}}` mustache substitution per
  task.

## Setup

Python 3.11+.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .            # installs `requests`
```

Then edit `config.toml`:

- `[t2] root` — path to the
  [`toronto-2-address-import`](https://github.com/skfd/toronto-2-address-import)
  checkout, relative to this project or absolute. `build` reads its address DB,
  so clone it too. Defaults to a sibling checkout.
- `[maproulette] project_id` — the MapRoulette project the challenge lands in
  (required before `create`).

## Run

```bash
# 1. Enumerate addr:interpolation ways from OSM (tiled Overpass, cached).
#    Use a small --bbox to test; omit it for the whole city (~69k ways, slow).
python run.py fetch --bbox "43.645,-79.42,43.665,-79.39"

# 2. Compute per-line coverage from the City DB and write the task GeoJSON.
python run.py build
python run.py stats          # coverage breakdown of the last build

# 3. Create the challenge and upload tasks. Needs MAPROULETTE_API_KEY set and
#    a real project_id. Preview first:
python run.py create --dry-run
python run.py create --limit 20      # upload a small first batch
python run.py create                 # full upload
python run.py create --name "..."    # override the challenge name (test runs)
python run.py create --by-neighbourhood   # one challenge per neighbourhood

# 4. Later: sync the live challenges with a fresh fetch+build. Closes tasks
#    whose ways are gone from OSM (marked alreadyFixed) and uploads tasks for
#    newly eligible ways. Mapper-set statuses are never overwritten.
python run.py fetch --force && python run.py build
python run.py refresh --dry-run      # preview the per-challenge diff
python run.py refresh                # apply it
```

Set the API key (PowerShell):

```powershell
$env:MAPROULETTE_API_KEY = "<your key>"
```

## Outputs (under `data/`, gitignored)

| File | Contents |
|---|---|
| `interpolation_ways.json` | raw enumerated ways (geometry + endpoint housenumbers/street) |
| `neighbourhoods.geojson` | City neighbourhood boundaries (auto-downloaded) |
| `tasks.geojson` | RS-delimited MapRoulette tasks (`full`/`partial`, Toronto only, tagged with neighbourhood) |
| `excluded.geojson` | `uncovered`/`unknown` Toronto ways held back from upload, for review |
| `outside.geojson` | ways whose midpoint falls outside the city boundary (no task) |
| `summary.json` | coverage + per-neighbourhood breakdown for the last `build` |

## Notes

- **Coverage matching** keys on the normalized street name **and** a distance
  guard (`coverage.match_radius_m`, default 150 m) from the interpolation line,
  so the same street name in different GTA municipalities doesn't cross-match.
- The coverage category (`full`/`partial`) is kept as a hidden task property
  and in the `build` stats; it is **not** shown to mappers. An interpolation
  range enumerates estimates, not real addresses, so "missing" intermediate
  numbers are expected and not warned about.
- **Staleness:** the fetch cache is timestamped and `create`/`refresh` warn
  when it is more than a week old (refetch + rebuild before uploading). Every
  created challenge is recorded in the committed `manifest.json` (challenge id,
  neighbourhood, way ids, fetch time), which is what `refresh` diffs against.
- **Refresh rules:** a task is closed (`alreadyFixed`) only when its way is
  gone from the raw OSM fetch — not merely absent from `tasks.geojson`, since
  a way can drop out of the build while still existing in OSM. Only tasks
  still in `created`/`skipped` status are ever touched; fixed, falsePositive
  and other mapper-set statuses always win. New tasks are `addTasks`-ed to the
  existing neighbourhood challenge; existing tasks are never re-uploaded.
- `create` is the only outward-facing step. It validates the project before
  creating anything, then PUTs **one FeatureCollection per task** (MapRoulette's
  `addTasks` parses a single JSON value per request — the `U+001E` prefix is
  stripped before upload). Challenges are created as difficulty 3 (expert) with
  `requiresLocal` set.
