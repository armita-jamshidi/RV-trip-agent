"""Trip request -> ConstraintSpec. Claude extracts what the traveler said; code applies defaults.

This is the baseline the fine-tuned parser (T29) must beat on `evals/parser/cases.jsonl`.
"""

import hashlib
import json
from datetime import date
from pathlib import Path

import anthropic
from pydantic import BaseModel

from dave.models import ConstraintSpec, Hookup, Interests, Model, RVRequest

MODEL = "claude-opus-5-5"

INSTRUCTIONS = """Extract the RV trip constraints the traveler stated. Use null (or an empty list) \
for anything they did not say; never fill in defaults or guess. Resolve relative dates against \
today's date. Places stay as written, with the state when it's clear ("Moab, UT"). A "loop" or \
"there and back" trip is round_trip=true. Interest weights run 0 to 1: 0.9 for something they \
love or focus on, 0.5 for a passing mention, 0.1 for something they dislike; null when they \
mention no interests at all. "Largest X" means roadside superlatives such as the world's \
largest ball of twine. Put places they insist on in must_visit and things they want to steer \
clear of (interstates, cities, toll roads) in avoid."""

# What the planner can't work without. Dates are optional: prices and availability fall back
# to estimates until the traveler picks a start date.
ESSENTIAL = {
    "origin": "where you're starting from",
    "destination": "where you're headed (or that it's a loop)",
    "nights": "how many nights",
    "rv": "your RV's make and model",
}


class ExtractedInterests(BaseModel):
    nature: float | None
    museums: float | None
    largest_x: float | None
    food: float | None


class Extracted(BaseModel):
    """What the traveler said, with null for anything unstated."""

    origin: str | None
    destination: str | None
    round_trip: bool | None
    start_date: date | None
    nights: int | None
    travelers: int | None
    rv_make: str | None
    rv_model: str | None
    rv_year: int | None
    budget_usd: float | None
    max_drive_hours_per_day: float | None
    hookups_required: list[Hookup] | None
    interests: ExtractedInterests | None
    must_visit: list[str]
    avoid: list[str]


class ParseResult(Model):
    """Either a spec the planner can use, or the question to ask the traveler."""

    spec: ConstraintSpec | None = None
    missing: list[str] = []
    question: str | None = None


def missing_fields(x: Extracted) -> list[str]:
    missing = []
    if not x.origin:
        missing.append("origin")
    if not x.destination and not x.round_trip:
        missing.append("destination")
    if not x.nights:
        missing.append("nights")
    if not (x.rv_make or x.rv_model):
        missing.append("rv")
    return missing


def to_result(x: Extracted) -> ParseResult:
    """Apply domain defaults (via ConstraintSpec) or ask for what's missing."""
    if missing := missing_fields(x):
        needs = [ESSENTIAL[f] for f in missing]
        listed = needs[0] if len(needs) == 1 else ", ".join(needs[:-1]) + " and " + needs[-1]
        return ParseResult(missing=missing, question=f"To plan your trip I need {listed}.")

    given = {
        "round_trip": x.round_trip,
        "start_date": x.start_date,
        "travelers": x.travelers,
        "budget_usd": x.budget_usd,
        "max_drive_hours_per_day": x.max_drive_hours_per_day,
        "hookups_required": set(x.hookups_required) if x.hookups_required else None,
    }
    if x.interests:
        weights = {k: v for k, v in x.interests.model_dump().items() if v is not None}
        given["interests"] = Interests(**{k: min(max(v, 0), 1) for k, v in weights.items()})
    spec = ConstraintSpec(
        origin=x.origin,
        destination=x.destination or x.origin,
        nights=x.nights,
        rv=RVRequest(make=x.rv_make, model=x.rv_model, year=x.rv_year),
        must_visit=x.must_visit,
        avoid=x.avoid,
        **{k: v for k, v in given.items() if v is not None},
    )
    return ParseResult(spec=spec)


def extract(
    text: str,
    *,
    today: date,
    client: anthropic.Anthropic | None = None,
    cache_dir: Path | None = None,
) -> Extracted:
    """Ask Claude for the stated constraints. Responses are cached on disk by request."""
    prompt = f"Today is {today.isoformat()}.\n\nTrip request:\n{text}"
    key = hashlib.sha256(json.dumps([MODEL, INSTRUCTIONS, prompt]).encode()).hexdigest()
    path = cache_dir / "parser" / f"{key}.json" if cache_dir else None
    if path and path.exists():
        return Extracted.model_validate_json(path.read_text())

    client = client or anthropic.Anthropic()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=4096,
        system=INSTRUCTIONS,
        messages=[{"role": "user", "content": prompt}],
        output_format=Extracted,
        output_config={"effort": "low"},
    )
    extracted = response.parsed_output
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(extracted.model_dump_json())
    return extracted


def parse_request(text: str, *, today: date | None = None, **kwargs) -> ParseResult:
    return to_result(extract(text, today=today or date.today(), **kwargs))
