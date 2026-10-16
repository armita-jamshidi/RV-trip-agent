# RV-trip-agent

Dave is an AI travel agent for RVers: tell it your RV, budget and interests, and it plans a low-cost, fun road trip that your rig actually fits. See `CLAUDE.md` for how the project is built and `ROADMAP.md` for what's next.

## Develop

```
uv sync
uv run pytest
uv run ruff check
uv run dave --help
```

Copy `.env.example` to `.env` and add API keys when a feature needs them.

## Run the dashboard

```
uv run dave dashboard
```

This opens Dave's page in your browser at http://localhost:8765/ (the same on Windows PowerShell and Mac/Linux). Fill in your RV, route, dates, budget and interests, or pick one of the demo trips, and Dave plans it with the same planner as `dave plan`. Itineraries already saved in `demo/` open from the "Demo trips" list without planning. Planning needs `ANTHROPIC_API_KEY` in `.env`. Use `--port` to pick another port and `--no-browser` to skip opening a tab. Nothing is booked or paid from the dashboard.
