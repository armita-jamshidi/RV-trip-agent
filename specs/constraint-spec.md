# Constraint spec

The contract between the trip request parser (Claude baseline or fine-tuned model) and the planner. Every field is validated with pydantic.

```json
{
  "origin": "Denver, CO",
  "destination": "Moab, UT",
  "round_trip": false,
  "start_date": "2026-11-02",
  "nights": 4,
  "travelers": 2,
  "rv": {"make": "Winnebago", "model": "Minnie Winnie 31K", "year": 2023},
  "budget_usd": 1500,
  "max_drive_hours_per_day": 5,
  "hookups_required": ["electric", "water"],
  "interests": {"nature": 0.7, "museums": 0.1, "largest_x": 0.2, "food": 0.5},
  "must_visit": ["Arches National Park"],
  "avoid": ["interstate"]
}
```

Rules: missing values fall back to `context/domain.md` defaults; unknown fields are rejected; `interests` weights are 0 to 1.
