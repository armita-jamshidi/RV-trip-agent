# Data sources

Free sources first (decision 2026-10-08).

| Need | Source | Access | Notes |
|---|---|---|---|
| Places, restaurants, attractions | Foursquare OS Places | Open dataset / API key | Ratings and categories for stops and food. |
| Campgrounds | Recreation.gov RIDB | Free API key | Federal campgrounds, site attributes (hookups, max length). |
| Routing | OSRM (OpenStreetMap) | Free, public demo server or self-host | Drive time and geometry. |
| Bridge heights | OpenStreetMap via Overpass | Free | `maxheight` tags along the route. |
| Gas prices (regional) | U.S. EIA API | Free key | Weekly regional averages for cost estimates. |
| Gas prices (station level) | Our own daily snapshots | Built in T22 | No free API has 2-month station history; we collect it ourselves. |
| RV dimensions | Manufacturer spec pages | Web fetch | Cached; manual override when a page can't be parsed. |
| LLM | Anthropic API (Claude Agent SDK) | API key | Planner and baseline for fine-tuned models. |

Keys go in environment variables: `ANTHROPIC_API_KEY`, `FOURSQUARE_API_KEY`, `RIDB_API_KEY`, `EIA_API_KEY`.
