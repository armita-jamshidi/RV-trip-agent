# Decisions, one file each

Record each non-obvious choice as its own file here, named
`YYYY-MM-DD-t<task id>-<short-slug>.md` (for example `2026-10-11-t34-eval-tolerances.md`).
The file holds one dated line, the same style as `../decisions.md`:

```
- 2026-10-11: Eval tolerances (T34): drive time within 15%, nightly price within $5, gas within 5%.
```

Why: parallel task branches each appended a line to the end of `decisions.md`, so every
merge conflicted. New files never conflict. `decisions.md` keeps the entries made before
2026-10-10 and is no longer appended to; read both to see every decision.
