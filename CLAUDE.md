# Dave: RV trip agent

Dave is an AI travel agent for RVers. Given a user's RV, budget and interests, Dave plans a low-cost, fun road trip: a route the RV physically fits, days of 5 hours of driving or less, campgrounds with hookups each night, worthwhile stops, good food, cheap gas, and a full cost breakdown. Bookings are prepared by Dave and confirmed by a human.

Read `context/product.md` first, then `ROADMAP.md` for what to build next.

## Stack
- Python 3.12, managed with `uv`. Package lives in `src/dave/`.
- Agent: Claude Agent SDK (`claude-agent-sdk`). Each capability is a tool in `src/dave/tools/`.
- Places: Foursquare OS Places. Campgrounds: Recreation.gov RIDB. Routing and bridge heights: OpenStreetMap (OSRM / Overpass). Gas: EIA regional prices plus our own station snapshots.
- Vector store: LanceDB, behind `src/dave/store/vectors.py` so it can be swapped.
- Fine-tuning: QLoRA notebooks in `training/`, run on Google Colab (Kaggle as backup).
- Tests: `pytest`. Lint/format: `ruff`.

## Layout
```
CLAUDE.md, ROADMAP.md, REVIEW.md
context/     product, domain rules, data sources, decisions log
customers/   personas Dave is built for
specs/       contracts between components (constraint spec, itinerary)
demo/        sample trip requests and expected-quality notes
routines/    prompts for scheduled work (hourly Notion worker)
src/dave/    the agent (created by the first build task)
training/    fine-tuning notebooks and datasets
evals/       real-world comparison harness
```

## Hard rules
1. **Never spend money without approval.** Booking code produces a proposal (site, dates, price, link) and stops. Payment only runs after a human approves that specific booking.
2. **No secrets in git.** Keys come from environment variables; `.env.example` lists them.
3. **Constraints are checked in code, not trusted from the model.** RV height vs. bridge clearance, RV length vs. site length, hookups, 5 h/day driving and budget are validated by `validate_itinerary()` before any plan is shown.
4. **Free data sources first.** A paid API needs a decision recorded in `context/decisions/`.
5. **Cache every external call** on disk so tests and reruns are cheap and deterministic.

## Conventions
- Small modules, typed with pydantic models from `src/dave/models.py`. No speculative abstractions.
- Every tool has a unit test with recorded fixtures (no live network in tests).
- One Notion task = one branch (`task/<id>-<slug>`) = one PR. Keep PRs small.
- Record non-obvious choices as a new file in `context/decisions/` (one dated line per file, named `YYYY-MM-DD-t<id>-<slug>.md`). Never append to `context/decisions.md`: parallel branches all editing one file made every merge conflict.

## Working a task
See `routines/hourly-notion-worker.md`. In short: take the top "Not started" task from the Notion board "RV Travel Agent", move it to "In progress", build it with tests, open a PR, then move it to "Ready for Review" with a plain-language summary and the PR link on the task page. Before opening the PR, check it against `REVIEW.md`.
