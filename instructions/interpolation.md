This task retires one OpenStreetMap `addr:interpolation` line on **{{street}}** — range **{{range}}** (source `{{source}}`). It became redundant after the City of Toronto per-address import.

**City data house numbers:**
{{housenumbers}}

### 1. Align buildings / address points
Align the OSM building footprints and address nodes to the Bing imagery layer.

### 2. Verify the addresses
Verify that every house number above is present — as an individual node, or as an address on a building when that building has only the one address.

- Split comma/semicolon-separated addresses into individual nodes.
- Extract the address off a building into its own node if the building already carries another address node.

Use the [Toronto Address Layer](https://skfd.github.io/toronto-addresses-layer/) for reference if any address looks misaligned or missing.

### 3. Remove the interpolation line
Once every number above is present as a real point/building, delete the `addr:interpolation` way. Select the endpoint **nodes** and delete them — the editor then selects the rest of the way; if you delete the way directly, the endpoint nodes are left behind.

**IMPORTANT:** double-check that you deleted the beginning and ending nodes, not only the way. Keep an endpoint node if it is part of a building or carries other tags.

Mark **Fixed** when done, **Already Fixed** if someone beat you to it, or **Not an Issue** / **Skip** if you judged that the line should stay.

Report any problems or suggestions to the [Interpolation Elimination Mapping Party forum post](https://community.openstreetmap.org/t/toronto-address-interpolation-elimination-maproullete/144535).
