# Decisions

- 2026-10-08: Python + Claude Agent SDK.
- 2026-10-08: Bookings need human approval per booking; no stored payment details.
- 2026-10-08: Free data sources first (see data-sources.md).
- 2026-10-08: LanceDB for vectors, behind an interface so pgvector can replace it.
- 2026-10-08: Fine-tuning via QLoRA on Google Colab (Kaggle as backup); start with Qwen2.5-3B, move to 7B only if needed. Claude is the baseline.
- 2026-10-08: One Notion task per branch and PR; hourly routine works one task per run.
- 2026-10-08: The agent runs with built-in Claude Code tools disabled (`tools=[]`); Dave can only call its own tools in `src/dave/tools/`, so it can't touch files or run shell commands.
- 2026-10-08: The request parser is one Claude call with structured outputs (`anthropic` SDK, `messages.parse`), not an agent loop. Claude returns only what the traveler stated (null otherwise), and code applies the domain defaults.
- 2026-10-08: The parser asks a follow-up only for origin, destination (unless it's a loop), nights and RV. A start date is optional; prices fall back to estimates without one.
- 2026-10-08: Parser accuracy compares free text loosely ("Moab, UT" = "Moab, Utah") and interest weights within ±0.3, since the weights are a judgment call.
- 2026-10-08: RV identification is an offline catalog match (9 manufacturers, their main model lines), not an LLM call. Model names that are everyday words ("View", "Classic", "Interstate") only match when the manufacturer is named.
- 2026-10-08: The catalog stores each manufacturer's site, not spec-page URL patterns. Manufacturer sites are blocked by this environment's network policy, so URL patterns can't be verified yet; T07 finds the spec page.
- 2026-10-08: Interests map to words in Foursquare category labels rather than category IDs, so the mapping survives taxonomy changes. Stop score = best matching interest weight × quality (60% rating, 40% popularity) × 0.5^(detour / 30 min). Unrated stops get a 6/10 prior.
- 2026-10-08: Routing uses the public OSRM demo server (car profile) with RV drive time = car time × 1.10, configurable. OSRM has no RV or truck profile; bridge heights are handled separately (T10).
- 2026-10-08: Driving days are split into equal parts (fewest days that keep each at or under 5 h), cutting the route geometry by distance. This avoids short last-day stubs. Campground choice (T17) may pull an overnight earlier, never later.
- 2026-10-08: Corridor search estimates detours from straight-line distance off the route (x1.3 road circuity, there and back, 35 mph) instead of routing every candidate; the planner routes only the few it picks. Default corridor is 15 mi each side.
