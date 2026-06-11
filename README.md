# against-interpolation

Generates MapRoulette tasks to retire redundant `addr:interpolation` lines in
Toronto. This is the cleanup phase that the sibling
[`toronto-2-address-import`](../toronto-2-address-import) project deferred as
out of scope: now that the City's per-address points are in OSM, the old
StatCan/CanVec interpolation lines that span the same blocks can be removed.

One MapRoulette task is created **per interpolation line**. Each task shows the
house numbers the City actually has for the block (the ground truth — the
interpolation's in-between numbers are only estimates and many never existed)
and walks a mapper through three steps:

1. **Align buildings / address points** to the Bing imagery layer.
2. **Verify the addresses** — every City house number present as an individual
   node, or as an address on a building when that building has only the one
   address. The [Toronto Address Layer](https://skfd.github.io/toronto-addresses-layer/)
   helps spot misaligned or missing ones.
3. **Remove the interpolation line** — delete the endpoint nodes (the editor
   takes the way with them); keep an endpoint that is part of a building or
   carries other tags.

Lines whose range can't be read (`unknown`) or with **zero** matching City
points (`uncovered` — often just outside Toronto's open-data coverage) are
**excluded from upload** and parked in `data/excluded.geojson` for manual
review: a task with an empty house-number list gives a mapper nothing to verify
against.

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
python run.py create --name "..."    # override the challenge name (test runs)
```

Set the API key (PowerShell):

```powershell
$env:MAPROULETTE_API_KEY = "<your key>"
```

## Outputs (under `data/`, gitignored)

| File | Contents |
|---|---|
| `interpolation_ways.json` | raw enumerated ways (geometry + endpoint housenumbers/street) |
| `tasks.geojson` | RS-delimited MapRoulette tasks (`full`/`partial` coverage only) |
| `excluded.geojson` | `uncovered`/`unknown` ways held back from upload, for review |
| `summary.json` | coverage breakdown for the last `build` |

## Notes

- **Coverage matching** keys on the normalized street name **and** a distance
  guard (`coverage.match_radius_m`, default 150 m) from the interpolation line,
  so the same street name in different GTA municipalities doesn't cross-match.
- The coverage category (`full`/`partial`) is kept as a hidden task property
  and in the `build` stats; it is **not** shown to mappers. An interpolation
  range enumerates estimates, not real addresses, so "missing" intermediate
  numbers are expected and not warned about.
- `create` is the only outward-facing step. It validates the project before
  creating anything, then PUTs **one FeatureCollection per task** (MapRoulette's
  `addTasks` parses a single JSON value per request — the `U+001E` prefix is
  stripped before upload). Challenges are created as difficulty 3 (expert) with
  `requiresLocal` set.
