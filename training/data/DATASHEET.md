# Trip request → constraint dataset

Training data for the small trip request parser (T29). Each row pairs a traveler's request with what they actually said, in the shape of `dave.parser.Extracted`. The planner applies defaults afterward (`dave.parser.to_result`), so labels use `null` for anything not stated.

| Split | Rows | File |
|---|---|---|
| train | 2,000 | `train.jsonl` |
| test | 100 | `test.jsonl` |

Regenerate with `uv run python -m dave.dataset`. The output is deterministic (seed 28 for train, 29 for test), and a test checks the committed files match the generator.

## Row format

```json
{"id": 1, "today": "2026-02-27", "request": "Salt Lake City to Bryce Canyon, leaving tomorrow, ...",
 "extracted": {"origin": "Salt Lake City, UT", "destination": "Bryce Canyon, UT", "start_date": "2026-02-28", "nights": 7, ...},
 "persona": "weekend van-lifer"}
```

`today` is the date the request is read against: "leaving tomorrow" and "starting Nov 2" resolve from it. The prompt for the fine-tuned model should include it, the same way `dave.parser.extract` does.

## How it was made

- **Composed, not sampled from a model.** `src/dave/dataset.py` builds each request from clauses (route, RV, nights, dates, budget, people, interests, hookups, must-visit, avoid) and builds the label at the same time, so labels are right by construction. There is no API cost and no labeling noise.
- **Personas** from `customers/personas.md` (retired explorers, young family, weekend van-lifer) set the RV classes, party size, budget range and leaning interests.
- **RVs** come from the catalog in `src/dave/rv_catalog.py`, sometimes with a floorplan code and year, sometimes without the make (`rv_make` is then null).
- **Voices:** a casual sentence, a terse list, and a formal "Please help me plan an RV trip:" request in the style of TravelPlanner queries. About 10% are lowercased.
- **Missing information:** about 10% leave out the origin, the number of nights or the RV, so the model learns to answer null and the agent asks a follow-up question.
- **Interest weights** follow the parser's rule: 0.9 for love or focus, 0.5 for a passing mention, 0.1 for dislike, null when not mentioned.

## Source datasets

TravelPlanner (Xie et al., 2024), NL4Opt (Ramamonjison et al., 2022) and OR-Instruct/ORLM (Tang et al., 2024) were reviewed for style. No rows were copied: this environment cannot reach Hugging Face, and none of them is about RVs. What was adapted: TravelPlanner's formal request phrasing, and NL4Opt's habit of labeling only the stated constraints, not assumed ones.

## Test set

The test set uses origins and destinations that never appear in training (Bozeman, Rapid City, El Paso, Little Rock, Raleigh, Jacksonville, Buffalo and Tulsa; Crater Lake, Olympic National Park, Taos, Mammoth Cave, Marfa and the Outer Banks). It measures whether the model generalizes to new places rather than memorizing them. All 100 test rows were read and checked by hand on 2026-10-08. Two problems found in that review were fixed in the generator: a kids' phrase appearing in a request from a couple, and "a Airstream".

## Limits

- Phrasing comes from a fixed set of templates, so real requests will be messier. Score the fine-tuned model on `evals/parser/cases.jsonl` (hand-written) as well as this test set.
- Places are labeled as written plus the state ("Zion, UT"), with no resolution to official names.
- All dates fall in 2026–2027.
