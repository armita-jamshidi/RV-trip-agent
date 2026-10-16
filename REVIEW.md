# Review checklist

Used by Dave before opening a PR and by Armita when reviewing one.

## Does it do the task?
- [ ] The PR matches one Notion task and its "Done when" line.
- [ ] The Notion task has a plain-language summary: what changed, how to try it, what is left.

## Safety
- [ ] No code path pays or books without an explicit human approval for that booking.
- [ ] No API keys, tokens or personal data committed.
- [ ] RV constraints (height, length, hookups, 5 h/day, budget) are enforced in code, not only in a prompt.

## Quality
- [ ] `uv run ruff check` and `uv run pytest` pass; CI is green.
- [ ] New tools have tests with recorded fixtures, no live network.
- [ ] External calls go through the cached client.
- [ ] Code is small and readable; no dead code or unused options.
- [ ] Any new data source or paid service is recorded as a new file in `context/decisions/` (not appended to `context/decisions.md`).

## Results
- [ ] If the task affects plans, a demo trip from `demo/` was rerun and the output still makes sense.
