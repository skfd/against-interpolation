# against-interpolation

Generates MapRoulette tasks to retire redundant `addr:interpolation` lines in
Toronto. This is the cleanup phase that the sibling
[`toronto-2-address-import`](../toronto-2-address-import) project deferred as
out of scope: now that the City's per-address points are in OSM, the old
StatCan/CanVec interpolation lines that span the same blocks can be removed.

One MapRoulette task is created **per interpolation line**. Each task walks a
mapper through three steps:

1. **Verify the addresses** — the task lists every housenumber in the line's
   range together with whether the City repository has a real point for it (and
   that point's exact position). A fully-covered range is safe to retire; a gap
   (`NO CITY POINT`) is a stop sign.
2. **Align buildings & address points** — confirm the OSM building/address node
   sits at the authoritative City position shown.
3. **Remove the interpolation line** — delete the way once every number is a
   real point.

The coverage status (`full` / `partial` / `none` / `unknown`) is shown on every
task so the mapper can judge, per the design decision to surface all lines
rather than pre-filter to only the safe ones.

## How it relates to the sibling projects

- **Data** comes from `toronto-2-address-import`. We import its `t2` package
  read-only for the Toronto address DB (`source_db`) and the street-name
  normalizer (`conflate.normalize_street`). Set its location in `config.toml`
  under `[t2] root`. That project's own `config.toml` supplies the SQLite path,
  so we don't duplicate it.
- **MapRoulette task shape** mirrors `bikeshare-toronto-maproulette`:
  record-separator-delimited GeoJSON (one `FeatureCollection` per line, each
  prefixed with a `U+001E` record separator), with the challenge instruction in
  `instructions/interpolation.md` and `{{property}}` mustache substitution per
  task.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .            # installs `requests`
```

Edit `config.toml`:

- `[t2] root` — path to the `toronto-2-address-import` checkout.
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
```

Set the API key (PowerShell):

```powershell
$env:MAPROULETTE_API_KEY = "<your key>"
```

## Outputs (under `data/`, gitignored)

| File | Contents |
|---|---|
| `interpolation_ways.json` | raw enumerated ways (geometry + endpoint housenumbers/street) |
| `tasks.geojson` | RS-delimited MapRoulette tasks, one line per interpolation way |
| `summary.json` | coverage breakdown for the last `build` |

## Notes

- **Coverage matching** keys on the normalized street name **and** a distance
  guard (`coverage.match_radius_m`, default 150 m) from the interpolation line,
  so the same street name in different GTA municipalities doesn't cross-match.
- **`unknown`** lines are those whose range can't be read from the way's
  endpoints (e.g. a single-housenumber endpoint, `lo == hi`). They still get a
  task, flagged accordingly.
- `create` is the only outward-facing step. It validates the project before
  creating anything and uploads tasks in batches
  (`maproulette.upload_batch_size`).
