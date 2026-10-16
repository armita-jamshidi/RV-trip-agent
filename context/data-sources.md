# Data sources

Free sources first (decision 2026-10-08).

| Need | Source | Access | Notes |
|---|---|---|---|
| Places, restaurants, attractions | Foursquare OS Places | Open dataset / API key | Ratings and categories for stops and food. |
| Campgrounds | Recreation.gov RIDB | Free API key | Federal campgrounds, site attributes (hookups, max length). |
| Routing | OSRM (OpenStreetMap) | Free, public demo server or self-host | Drive time and geometry. |
| Place names to coordinates | OpenStreetMap Nominatim | Free, no key | Two lookups per plan (origin, destination), cached; sent with a descriptive User-Agent as its usage policy asks. |
| Bridge heights | OpenStreetMap via Overpass | Free | `maxheight` tags along the route. |
| Gas prices | U.S. EIA API, saved weekly by `dave gas-snapshot` | Free key | Weekly regular and diesel averages for the U.S., 10 regions and 9 states (CA, CO, FL, MA, MN, NY, OH, TX, WA); other states use their region. Station-level prices come from Google Places when its key is set (row below). |
| Gas station prices | Google Places API (New), Nearby Search with `fuelOptions` | Paid key (monthly free allowance), optional | Posted regular and diesel prices at stations along the route, at most 40 searches a plan. Never cached on disk (Google's terms); decision 2026-10-16-t37. |
| RV dimensions | Manufacturer spec pages | Web fetch | Cached; manual override when a page can't be parsed. |
| LLM | Anthropic API (Claude Agent SDK) | API key | Planner and baseline for fine-tuned models. |

Keys go in environment variables: `ANTHROPIC_API_KEY`, `FOURSQUARE_API_KEY`, `RIDB_API_KEY`, `EIA_API_KEY`, and optionally `GOOGLE_PLACES_API_KEY`.
