import json
import random
from datetime import date, timedelta

from dave import dataset
from dave.parser import Extracted, to_result


def _rows(name: str) -> list[dict]:
    return [json.loads(line) for line in (dataset.OUT / f"{name}.jsonl").read_text().splitlines()]


def test_committed_dataset_matches_the_generator(tmp_path):
    counts = dataset.write(tmp_path)
    assert counts == {"train": 2000, "test": 100}
    for name in counts:
        assert (tmp_path / f"{name}.jsonl").read_text() == (
            dataset.OUT / f"{name}.jsonl"
        ).read_text()


def test_every_label_is_a_spec_or_a_question():
    for row in _rows("train") + _rows("test"):
        result = to_result(Extracted.model_validate(row["extracted"]))
        assert result.spec is not None or result.question


def test_some_requests_leave_out_what_the_planner_needs():
    missing = [r for r in _rows("train") if to_result(Extracted(**r["extracted"])).spec is None]
    assert 100 < len(missing) < 400


def test_test_set_uses_places_training_never_mentions():
    train_text = " ".join(r["request"].lower() for r in _rows("train"))
    for city, _ in dataset.TEST_ORIGINS:
        assert city.lower() not in train_text
    for place, _, _ in dataset.TEST_DESTINATIONS:
        assert place.lower() not in train_text
    assert not {r["request"] for r in _rows("train")} & {r["request"] for r in _rows("test")}


def test_relative_start_dates_resolve_against_today():
    rng = random.Random(0)
    today = date(2026, 10, 8)  # a Thursday
    for _ in range(200):
        text, start = dataset._start(rng, today)
        if text == "leaving tomorrow":
            assert start == today + timedelta(days=1)
        elif text and text.startswith("leaving this coming"):
            assert today < start <= today + timedelta(days=7)
            assert text.endswith(dataset.WEEKDAYS[start.weekday()])
        elif text and text.startswith("sometime in"):
            assert start is None
        elif text:
            assert start > today


def test_labels_follow_the_text():
    for row in _rows("test"):
        text, label = row["request"].lower(), row["extracted"]
        if label["origin"]:
            assert label["origin"].split(",")[0].lower() in text
        if label["destination"]:
            assert label["destination"].split(",")[0].lower() in text
        if label["rv_year"]:
            assert str(label["rv_year"]) in text
        if label["round_trip"]:
            assert "loop" in text or "and back" in text
