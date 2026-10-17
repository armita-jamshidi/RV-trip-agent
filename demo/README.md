# Demo trips

Real-world scenarios used for demos and for the evaluation harness (T34).

1. "We have a 2023 Winnebago Minnie Winnie 31K. Denver to Moab, 4 nights in November, $1,500, love hiking and big views."
2. "Thor Four Winds 28A, family of four, Chicago to Washington DC over a week, museums and kid-friendly food, budget $2,500."
3. "Class B Winnebago Revel. Austin to Nashville, 5 nights, we love weird roadside attractions and BBQ, $1,200."
4. "Tiffin Allegro Red 38 KA towing a Jeep. Seattle to Yellowstone and back, 10 nights, national parks, $4,000."

For each, the evaluation compares Dave's plan with reality: real drive times, real campground hookups and prices, real gas prices, and known low clearances.

Rendered itineraries (T33): [`itinerary-1-denver-moab.md`](itinerary-1-denver-moab.md). It is built from hand-written fixtures until the routing and campground services are reachable; trips 2–4 need those live sources and are not rendered yet. After changing the planner or renderer, refresh it with `DAVE_UPDATE_DEMO=1 uv run pytest tests/test_render.py`.

## Running them (T35)

`dave plan` builds a complete, validated plan; [WALKTHROUGH.md](WALKTHROUGH.md) explains each step and which keys add what. Save each run's plan in `demo/plans/`:

```
uv run dave plan 'We have a 2023 Winnebago Minnie Winnie 31K. Denver to Moab, 4 nights in November, $1,500, love hiking and big views.' --out demo/plans/trip-1-denver-moab.md
uv run dave plan 'Thor Four Winds 28A, family of four, Chicago to Washington DC over a week, museums and kid-friendly food, budget $2,500.' --out demo/plans/trip-2-chicago-dc.md
uv run dave plan 'Class B Winnebago Revel. Austin to Nashville, 5 nights, we love weird roadside attractions and BBQ, $1,200.' --out demo/plans/trip-3-austin-nashville.md
uv run dave plan 'Tiffin Allegro Red 38 KA towing a Jeep. Seattle to Yellowstone and back, 10 nights, national parks, $4,000.' --out demo/plans/trip-4-seattle-yellowstone.md
```
