"""Field accuracy of the trip request parser on `evals/parser/cases.jsonl`.

A case either expects a spec (scored field by field against every ConstraintSpec field, with
defaults filled in) or expects a follow-up question (scored once: right missing fields or not).
Free text is compared loosely, since "Moab, UT" and "Moab, Utah" are the same answer.
"""

import json
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

from dave.models import ConstraintSpec
from dave.parser import ParseResult

TODAY = date(2026, 10, 8)  # the cases' relative dates were written against this day
TARGET = 0.9
CASES = Path(__file__).resolve().parents[2] / "evals" / "parser" / "cases.jsonl"
INTEREST_TOLERANCE = 0.3
FILLER = {"the", "national", "park", "np", "world", "worlds"}


def norm(text: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", text.lower().split(",")[0]).split()
    return " ".join(w.removesuffix("s") for w in words if w not in FILLER)


def same_text(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return a == b
    a, b = norm(a), norm(b)
    return a in b or b in a


def same_list(expected: list[str], got: list[str]) -> bool:
    return all(any(same_text(e, g) for g in got) for e in expected) and all(
        any(same_text(g, e) for e in expected) for g in got
    )


def field_matches(name: str, expected: ConstraintSpec, got: ConstraintSpec) -> bool:
    e, g = getattr(expected, name), getattr(got, name)
    match name:
        case "origin" | "destination":
            return same_text(e, g)
        case "must_visit" | "avoid":
            # Repeating the destination in must_visit is neither right nor wrong.
            dest = expected.destination
            return same_list(
                [x for x in e if not same_text(x, dest)], [x for x in g if not same_text(x, dest)]
            )
        case "rv":
            return same_text(e.make, g.make) and same_text(e.model, g.model) and e.year == g.year
        case "interests":
            ed, gd = e.model_dump(), g.model_dump()
            return all(abs(ed[k] - gd[k]) <= INTEREST_TOLERANCE for k in ed)
        case "budget_usd":
            return e == g if e is None or g is None else abs(e - g) < 1
        case _:
            return e == g


def score_case(case: dict, result: ParseResult) -> dict[str, bool]:
    if "missing" in case:
        return {"missing": result.spec is None and set(result.missing) == set(case["missing"])}
    expected = ConstraintSpec(**case["expected"])
    if result.spec is None:
        return {name: False for name in ConstraintSpec.model_fields}
    return {
        name: field_matches(name, expected, result.spec) for name in ConstraintSpec.model_fields
    }


def load_cases(path: Path = CASES) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def evaluate(parse: Callable[[str], ParseResult], cases: list[dict]) -> dict:
    """Run `parse` on every case. Returns overall accuracy, per-field accuracy and misses."""
    totals: dict[str, list[bool]] = {}
    misses = []
    for case in cases:
        scores = score_case(case, parse(case["request"]))
        for name, ok in scores.items():
            totals.setdefault(name, []).append(ok)
        if wrong := [name for name, ok in scores.items() if not ok]:
            misses.append({"id": case["id"], "fields": wrong})
    flat = [ok for oks in totals.values() for ok in oks]
    return {
        "accuracy": sum(flat) / len(flat),
        "fields": {name: sum(oks) / len(oks) for name, oks in totals.items()},
        "misses": misses,
    }
