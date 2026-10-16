# Walkthrough: one request in, one plan out

This follows demo trip 1 through `dave plan`: what you type, what Dave does, and what you get
back. The plan below was built by the real pipeline from the test fixtures
(`tests/test_planner.py`), so its numbers are illustrative; run it yourself for live ones.

## 1. Set up once

```
uv sync
cp .env.example .env        # then fill in the keys
```

| Key | What it adds | Without it |
|---|---|---|
| `ANTHROPIC_API_KEY` | Reads the request | Nothing works (the parser needs it) |
| `RIDB_API_KEY` | Federal campgrounds with hookups, site lengths and prices | No campgrounds; the plan is marked "Not final" |
| `FOURSQUARE_API_KEY` | Stops, food, gas stations, private RV parks | Plan has drives, campgrounds and costs only |
| `EIA_API_KEY` | Gas prices (`uv run dave gas-snapshot`, weekly) | Fuel is left out of the costs, with a note, unless Google prices it |
| `GOOGLE_PLACES_API_KEY` | Gas stations on the route with their posted prices (paid beyond Google's free allowance, capped per plan) | Stations from Foursquare, priced at EIA averages |

Routing, bridge heights and place lookup use OpenStreetMap and need no key.

## 2. Request in

```
uv run dave plan 'We have a 2023 Winnebago Minnie Winnie 31K. Denver to Moab, 4 nights in November, $1,500, love hiking and big views.' --out demo/plans/trip-1-denver-moab.md
```

If something essential is missing (where from, where to, how many nights, which RV), Dave asks
for it instead of guessing, and exits with code 2.

## 3. What Dave does

1. **Understands the request.** Claude extracts origin, destination, nights, budget and
   interests; code fills in the defaults (5 h a day, electric and water hookups).
2. **Sizes the RV.** The Minnie Winnie 31K's length and height come from Winnebago's spec page.
   Other makes use class averages, and the plan says so.
3. **Routes it.** OSRM drives Denver to Moab; Overpass checks every bridge and tunnel against
   the RV's height plus 6 inches, and reroutes around any that are too low.
4. **Splits the days.** No day drives more than 5 hours. The nights left over are spent at the
   destination; on a round trip, the drive home starts after them.
5. **Picks campgrounds.** For each night, campgrounds near the day's end are filtered for a site
   the RV fits with the hookups it needs, then ranked by scenery, price and detour.
6. **Adds stops and food** that match the interests (with a Foursquare key).
7. **Prices it.** Fuel from regional gas averages, campgrounds per night, park tickets. If the
   plan is over budget, Dave swaps in cheaper campgrounds first, then drops paid stops, and
   says what each change saves and gives up.
8. **Checks it.** `validate_itinerary` re-checks every hard rule in code. A plan that breaks one
   is printed with a "Not final" banner listing what to fix, and `dave plan` exits with 1.

## 4. Plan out

```
# Denver, CO to Moab, UT

4 nights in a 2023 Winnebago Minnie Winnie 31K (32.75 ft long, 11 ft tall).

## Day 1 · Mon Nov 02: Denver, CO to Rifle Falls

177 miles, about 2 h 56 min of driving. [Directions](...)

**Tonight**
- Rifle Falls, $28 a night, electric + water hookups

## Day 2 · Tue Nov 03: Rifle Falls to Devils Garden Campground (Arches)

177 miles, about 2 h 56 min of driving. [Directions](...)

**Tonight and the next 2**
- Devils Garden Campground (Arches), $25 a night, electric + water hookups
```

Each day links to Google Maps directions from last night's campground to tonight's.

## 5. Costs

```
| | Fuel | Campground | Tickets | Total |
|---|---:|---:|---:|---:|
| Day 1 | $44.84 | $28.00 | $0.00 | $72.84 |
| Day 2 | $45.28 | $75.00 | $0.00 | $120.28 |
| **Trip** | $90.12 | $103.00 | $0.00 | **$193.12** |

Budget $1,500.00: $1,306.88 to spare.
```

Day 2's campground line covers all three nights in Moab.

## 6. Approvals

```
## Bookings to approve

- Campground: Rifle Falls, Nov 02 to Nov 03, $28.00 (proposed)
- Campground: Devils Garden Campground (Arches), Nov 03 to Nov 06, $75.00 (proposed)

Nothing is booked or paid until you approve each one.
```

Every booking is a proposal: the site, dates, price and a Recreation.gov link set to the site
that fits and the stay's dates. Dave never pays. A person approves each proposal
(`dave.booking.approve`), and only then does the booking hand-off give the steps to reserve it.
Park entrance passes and timed-entry reservations appear here too when a stop needs them.
