# Geospatial — Data Dictionary

Source: **OpenStreetMap** via the Overpass API. Licence: **ODbL** — attribution to
OpenStreetMap contributors is required in any product or dashboard.

## Files

| File | Contents | Size |
|---|---|---|
| `raw/osm_boundaries.json` | 781 administrative relations (14 at `admin_level=4`, 767 at `admin_level=6`) with full geometry, over bbox S26.0 W73.5 N32.5 E80.5 | 41.5 MB |
| `raw/osm_roads.json` | 9,978 ways classified `motorway`/`trunk`/`primary` (+ links) over the NCR core S27.9 W76.7 N29.0 E77.6, **tags only** | 2.7 MB |
| `raw/osm_landuse.json` | 14,134 ways/relations with a `landuse` tag over the same NCR core, **tags only** | 1.5 MB |

## Why tags-only for roads and land use

`out geom` inflates responses enormously — the boundary extract was 41.5 MB for only 781
relations. Fetching the road network with geometry over the full source region would be
~84,000 ways and several GB. VayuSangam needs the road network's *existence and
classification* (station siting, transport-corridor features), not a renderable basemap, so
roads and land use are stored as tagged features without geometry.

**Consequence:** road and land-use features cannot be used for distance or point-in-polygon
computation in their current form. If station-scale road geometry is later needed (for
example distance-to-highway), re-fetch that geometry for a station-scale bbox rather than the
whole region. Only `osm_boundaries.json` currently carries usable geometry.

## Road classes retrieved

`motorway` 2,915 · `trunk` 2,862 · `primary` 1,626 · `trunk_link` 1,187 · `motorway_link` 677 ·
`primary_link` 711

`secondary` and residential streets are **not** included — they were the bulk of the 84k count.

## Land-use classes retrieved

`residential` 5,554 · `farmland` 2,745 · `grass` 1,392 · `industrial` 931 · `basin` 876 ·
`commercial` 834 · `construction` 295 · `retail` 272 (remainder in the raw file)

## District coverage — partial, and stated as such

The boundary extract covers the full source region and contains, among others:
**Gurgaon, Ghaziabad, Faridabad** (all `admin_level=6`) and **Gautam Buddha Nagar**
(the district containing Noida).

**Not present in this extract:**
- **Gurugram** — OSM tags the district as `Gurgaon`; a name-based join must map
  `Gurugram → Gurgaon` explicitly.
- **Delhi's districts and sub-districts** (South East, Shahdara, New Delhi, …) are absent.
  `Delhi` exists only as a single `admin_level=4` relation. A station-level point-in-polygon
  against the available boundaries will therefore **not** resolve a district for Delhi stations.

This is why `station_availability.csv` and `station_metadata.csv` still have an empty
`district` column for all 220 OpenAQ stations. A correct fix needs a dedicated Delhi
district-level extract (Delhi is administered as a union territory, so OSM's `admin_level=6`
layer does not cover it in the same way as the neighbouring states). **No district is inferred
from a station name.** See the district section of `data/air_quality/DATA_DICTIONARY.md` for
the Survey of India / LGD alternative.

## Geometry and coordinate reference

All coordinates are **WGS84 / EPSG:4326** as returned by Overpass. No reprojection is applied.

## Reproducing

```bash
.venv/bin/python scripts/data_collection/geospatial/download_osm.py --test          # boundaries only
.venv/bin/python scripts/data_collection/geospatial/download_osm.py --only roads
.venv/bin/python scripts/data_collection/geospatial/download_osm.py --only landuse
```

Overpass is rate-limited and may return HTTP 429; the collector backs off and falls back to a
second public endpoint.
