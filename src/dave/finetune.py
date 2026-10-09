"""Shared pieces for the fine-tuned request parser (T29): its prompt, reading its output, scoring.

The Colab notebook `training/qlora_parser.ipynb` trains on `training/data/train.jsonl` with
`messages()` and scores on the test set with `score()`. The Claude baseline is scored the same
way by `python -m dave.finetune baseline`, so the two numbers compare like for like.
"""

import json
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from dave import parser_eval
from dave.dataset import OUT
from dave.parser import INSTRUCTIONS, Extracted, ParseResult, to_result

TARGET = 0.95  # the fine-tuned model must reach 95% of the baseline's field accuracy
RESULTS = OUT.parent / "results"
SYSTEM = (
    INSTRUCTIONS
    + "\n\nReply with one JSON object and nothing else, with exactly these keys: "
    + ", ".join(Extracted.model_fields)
    + ". interests is null or an object with nature, museums, largest_x and food."
)


def load(split: str) -> list[dict]:
    return [json.loads(line) for line in (OUT / f"{split}.jsonl").read_text().splitlines()]


def user_prompt(today: str, request: str) -> str:
    """The same user turn `dave.parser.extract` sends Claude."""
    return f"Today is {today}.\n\nTrip request:\n{request}"


def messages(row: dict) -> dict:
    """A training example in prompt/completion chat form."""
    return {
        "prompt": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_prompt(row["today"], row["request"])},
        ],
        "completion": [{"role": "assistant", "content": json.dumps(row["extracted"])}],
    }


def read_output(text: str) -> Extracted | None:
    """The model's reply as `Extracted`, or None if it isn't valid JSON for the schema."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return Extracted.model_validate_json(text[start : end + 1])
    except ValidationError:
        return None


def case(row: dict) -> dict:
    """A dataset row as a `parser_eval` case: an expected spec, or the fields to ask for."""
    result = to_result(Extracted.model_validate(row["extracted"]))
    if result.spec is None:
        return {"id": row["id"], "missing": result.missing}
    return {"id": row["id"], "expected": result.spec.model_dump(mode="json")}


def score(outputs: list[Extracted | None], rows: list[dict]) -> dict:
    """Valid-JSON rate and `parser_eval` field accuracy for outputs aligned with rows."""
    results = {
        row["request"]: to_result(out) if out else ParseResult()
        for out, row in zip(outputs, rows, strict=True)
    }
    report = parser_eval.evaluate(lambda text: results[text], [case(r) | r for r in rows])
    return {"valid_json": sum(o is not None for o in outputs) / len(outputs)} | report


def baseline(extract: Callable[[str, date], Extracted], rows: list[dict]) -> dict:
    """Score an extractor (the Claude parser by default) on rows, reading each against its day."""
    outputs = [extract(r["request"], date.fromisoformat(r["today"])) for r in rows]
    return score(outputs, rows)


def meets_target(model: dict, base: dict) -> bool:
    return model["accuracy"] >= TARGET * base["accuracy"]


def main(argv: list[str]) -> int:
    if argv != ["baseline"]:
        print("usage: python -m dave.finetune baseline")
        return 2
    from dave.config import load_settings
    from dave.parser import extract

    cache_dir = load_settings().cache_dir
    report = baseline(lambda text, today: extract(text, today=today, cache_dir=cache_dir),
                      load("test"))  # fmt: skip
    RESULTS.mkdir(parents=True, exist_ok=True)
    Path(RESULTS / "baseline.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("valid_json", "accuracy")}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
