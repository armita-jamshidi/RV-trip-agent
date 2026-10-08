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
