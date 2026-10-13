# Real-world references (T34)

One JSON file per demo trip (`trip-1-denver-moab.json`, ...), in the `TripReference` format from
`src/dave/evaluate.py`. Every fact names its `source` (a URL or service) and the date it was
`checked`. Only facts observed outside Dave belong here; never copy Dave's own output in.

- `drive`: each day's drive time from an independent routing service.
- `campgrounds`: hookups, longest RV site and nightly price from the campground's official page.
- `gas`: the current state average for the RV's fuel (EIA, or AAA's state averages).
- `low_clearances`: known low bridges and tunnels near the route (OpenStreetMap `maxheight`,
  state DOT lists).

Collected so far: `trip-1-denver-moab.json` (OSRM drive times, Devils Garden from Recreation.gov,
low clearances from Overpass). Trips 2 to 4 have no rendered itinerary to score yet: planning them
needs RIDB (it answers 401, no key reaches the session) and Foursquare (refused). Also still
unreachable: Colorado Parks and Wildlife, and EIA and AAA gas averages.

Two quirks of the sources, as of 2026-10-13. The proxy refuses OSRM URLs with `;` between
coordinates, so routes were queried with OSRM's `polyline(...)` form instead. Overpass answers 406
to requests without a descriptive `User-Agent` (httpx's default is refused), and 502 or 504 to
large queries when it is busy, so clearances were collected with small bounding boxes and retries.

`evals/scorecard.md` is the scored result. Refresh it after changing a reference or the planner
with `DAVE_UPDATE_EVAL=1 uv run pytest tests/test_evaluate.py`. Each gap it lists is a candidate
Notion task.
