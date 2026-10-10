# Real-world references (T34)

One JSON file per demo trip (`trip-1-denver-moab.json`, ...), in the `TripReference` format from
`src/dave/evaluate.py`. Every fact names its `source` (a URL or service) and the date it was
`checked`. Only facts observed outside Dave belong here; never copy Dave's own output in.

- `drive`: each day's drive time from an independent routing service.
- `campgrounds`: hookups, longest RV site and nightly price from the campground's official page.
- `gas`: the current state average for the RV's fuel (EIA, or AAA's state averages).
- `low_clearances`: known low bridges and tunnels near the route (OpenStreetMap `maxheight`,
  state DOT lists).

No files are here yet: the sources are blocked from the environment Dave is built in. Once they
are collected, score the demo trips with `dave.evaluate.score_trip` and save the result of
`render_scorecards` as `evals/scorecard.md`. Each gap it lists is a candidate Notion task.
