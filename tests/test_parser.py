from datetime import date
from types import SimpleNamespace

import pytest

from dave import parser_eval
from dave.cli import main
from dave.models import ConstraintSpec, Hookup
from dave.parser import Extracted, ExtractedInterests, ParseResult, extract, to_result

CASES = parser_eval.load_cases()
BLANK = dict.fromkeys(Extracted.model_fields) | {"must_visit": [], "avoid": []}


def oracle(case: dict) -> Extracted:
    """What a perfect extractor would return for a case: only the fields the case states."""
    if "missing" in case:
        given = {"origin": "Denver", "destination": "Moab", "nights": 3, "rv_make": "Jayco"}
        return Extracted(
            **BLANK | {k: v for k, v in given.items() if k.split("_")[0] not in case["missing"]}
        )
    e = dict(case["expected"])
    rv = e.pop("rv")
    interests = e.pop("interests", None)
    return Extracted(
        **BLANK
        | e
        | {"rv_make": rv.get("make"), "rv_model": rv.get("model"), "rv_year": rv.get("year")}
        | {"interests": ExtractedInterests(**interests) if interests else None}
    )


def test_twenty_cases():
    assert len(CASES) == 20
    assert [c["id"] for c in CASES] == list(range(1, 21))


def test_perfect_extraction_scores_100_percent():
    by_request = {c["request"]: oracle(c) for c in CASES}
    report = parser_eval.evaluate(lambda text: to_result(by_request[text]), CASES)
    assert report["misses"] == []
    assert report["accuracy"] == 1.0


def test_defaults_fill_unstated_fields():
    result = to_result(oracle(CASES[0]))
    spec = result.spec
    assert spec.max_drive_hours_per_day == 5
    assert spec.hookups_required == {Hookup.ELECTRIC, Hookup.WATER}
    assert spec.travelers == 2
    assert spec.interests.nature == 0.9 and spec.interests.largest_x == 0.0


def test_partial_interests_keep_defaults_and_clamp():
    x = Extracted(
        **BLANK
        | {"origin": "Austin", "destination": "Waco", "nights": 1, "rv_model": "Revel"}
        | {"interests": ExtractedInterests(nature=1.4, museums=None, largest_x=None, food=None)}
    )
    interests = to_result(x).spec.interests
    assert interests.nature == 1 and interests.museums == 0.5


def test_loop_trip_ends_at_origin():
    x = Extracted(
        **BLANK | {"origin": "Phoenix", "round_trip": True, "nights": 7, "rv_make": "Newmar"}
    )
    spec = to_result(x).spec
    assert spec.destination == "Phoenix" and spec.round_trip


def test_missing_essentials_ask_a_question():
    result = to_result(Extracted(**BLANK | {"nights": 3}))
    assert result.spec is None
    assert result.missing == ["origin", "destination", "rv"]
    assert result.question == (
        "To plan your trip I need where you're starting from, "
        "where you're headed (or that it's a loop) and your RV's make and model."
    )


def test_loose_text_matching():
    assert parser_eval.same_text("Moab, UT", "Moab, Utah")
    assert parser_eval.same_text("Bryce Canyon National Park, UT", "Bryce Canyon")
    assert parser_eval.same_list(["interstates"], ["Interstate"])
    assert not parser_eval.same_text("Denver, CO", "Dallas, TX")


def test_wrong_fields_are_counted():
    case = CASES[0]
    spec = ConstraintSpec(**case["expected"]).model_copy(update={"nights": 9, "origin": "Reno"})
    scores = parser_eval.score_case(case, ParseResult(spec=spec))
    assert [name for name, ok in scores.items() if not ok] == ["origin", "nights"]


def test_question_case_needs_the_right_missing_fields():
    case = next(c for c in CASES if c.get("missing") == ["origin"])
    assert parser_eval.score_case(case, ParseResult(missing=["origin"], question="?")) == {
        "missing": True
    }
    assert parser_eval.score_case(case, ParseResult(missing=["rv"], question="?")) == {
        "missing": False
    }


class FakeClient:
    def __init__(self, output: Extracted):
        self.calls = []
        self.messages = SimpleNamespace(parse=self.parse)
        self.output = output

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=self.output)


def test_extract_calls_claude_once_then_uses_cache(tmp_path):
    client = FakeClient(oracle(CASES[0]))
    today = date(2026, 10, 8)
    first = extract(CASES[0]["request"], today=today, client=client, cache_dir=tmp_path)
    again = extract(CASES[0]["request"], today=today, client=client, cache_dir=tmp_path)
    assert first == again == client.output
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["output_format"] is Extracted
    assert "Today is 2026-10-08" in call["messages"][0]["content"]


def test_cli_parse_prints_question(monkeypatch, capsys):
    import dave.parser

    monkeypatch.setattr(dave.parser, "extract", lambda text, **kw: Extracted(**BLANK))
    assert main(["parse", "somewhere warm"]) == 0
    assert capsys.readouterr().out.startswith("To plan your trip I need")


@pytest.mark.parametrize("accuracy, code", [(0.95, 0), (0.5, 1)])
def test_cli_eval_exit_code(monkeypatch, capsys, accuracy, code):
    monkeypatch.setattr(parser_eval, "evaluate", lambda parse, cases: {"accuracy": accuracy})
    assert main(["eval-parser"]) == code
