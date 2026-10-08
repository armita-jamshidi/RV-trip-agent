# Decisions

- 2026-10-08: Python + Claude Agent SDK.
- 2026-10-08: Bookings need human approval per booking; no stored payment details.
- 2026-10-08: Free data sources first (see data-sources.md).
- 2026-10-08: LanceDB for vectors, behind an interface so pgvector can replace it.
- 2026-10-08: Fine-tuning via QLoRA on Google Colab (Kaggle as backup); start with Qwen2.5-3B, move to 7B only if needed. Claude is the baseline.
- 2026-10-08: One Notion task per branch and PR; hourly routine works one task per run.
- 2026-10-08: The agent runs with built-in Claude Code tools disabled (`tools=[]`); Dave can only call its own tools in `src/dave/tools/`, so it can't touch files or run shell commands.
