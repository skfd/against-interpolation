This task retires one OpenStreetMap `addr:interpolation` line on **{{street}}** — range **{{range}}** (source `{{source}}`).

Toronto Open Data now has real address points for this block, so the interpolation line should be replaced by those points and removed. Coverage from the City repository: **{{coverage}}**.

**OSM line:** {{osm_way}}

### 1. Verify the addresses
The City has these points for the range (a real point already imported into OSM should sit at each listed position):

{{addresses_block}}

For any number marked `NO CITY POINT`, do **not** delete the line — the interpolation is still asserting a housenumber the City data does not cover. Skip the task (or add the point yourself if you can verify it) instead.

### 2. Align buildings & address points
For each address above, confirm the OSM building footprint / address node sits at the City position shown, and snap or nudge it there against imagery if needed. The interpolation endpoints are approximate StatCan geometry; the City points are the authoritative positions.

### 3. Remove the interpolation line
Once every number in the range is present as a real point/building, delete the `addr:interpolation` way {{osm_way}}. Delete an endpoint node too **only** if it carries nothing but `addr:housenumber`/`addr:street` (now redundant); keep any endpoint that is part of a building or has other tags.

Mark **Fixed** when done, **Already Fixed** if someone beat you to it, or **Not an Issue** / **Skip** if the line should stay (e.g. uncovered numbers).
