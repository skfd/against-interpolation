This task retires one OpenStreetMap `addr:interpolation` line on **{{street}}**, range **{{range}}** (source `{{source}}`). The City of Guelph's own address points are now all in OSM, so the line has nothing left to stand in for.

**City data house numbers in this range:**
{{housenumbers}}

**For this line:** {{guidance}}

### 1. Verify the addresses
Where numbers are listed above, each should be present, as an individual node or as the address on a building that carries only that one address.

- Split comma- or semicolon-separated addresses into individual nodes.
- If a building carries one address and also has address nodes inside it, move its address onto a node of its own.

The [Guelph Address Layer](https://guelph-maps.github.io/guelph-address-layer/) shows the City's points and helps spot an address that is missing or misplaced.

### 2. Remove the interpolation line
Select the line's two **end nodes** and delete them; the editor then takes the rest of the line with them. If you delete only the way, the end nodes are left behind as stray address nodes.

Keep an end node if it is part of a building or another way, or if it carries tags other than `addr:*` and `source` (`addr:city` and `source` alone do **not** count). Also keep it if its address is mapped nowhere else.

Mark **Fixed** when done, **Already Fixed** if someone beat you to it, or **Not an Issue** / **Skip** if you judge that the line should stay.

Report problems on the [Guelph address import thread](https://community.openstreetmap.org/t/import-addresses-from-city-of-guelph-data/135103).
