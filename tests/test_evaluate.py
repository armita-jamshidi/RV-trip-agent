from datetime import date
from pathlib import Path

from test_fuel_cost import EIA, client
from test_render import demo_1

from dave.evaluate import load_reference, render_scorecards, score_trip
from dave.gas_prices import fetch

FIXTURES = Path(__file__).parent / "fixtures" / "evals"


def scorecard(tmp_path):
    itinerary, _ = demo_1(tmp_path)
    prices = fetch(client(tmp_path / "eia", EIA()), "key", date(2026, 7, 1))
    reference = load_reference("trip-1-denver-moab_synthetic", FIXTURES)
    return score_trip(itinerary, reference, prices)


def test_each_fact_becomes_a_check(tmp_path):
    card = scorecard(tmp_path)
    assert card.trip == "trip-1-denver-moab"
    assert [(c.kind, c.subject, c.passed) for c in card.checks] == [
        ("drive time", "Day 1", True),  # 2.9 h vs 3.1 h
        ("drive time", "Day 2", False),  # 2.9 h vs 4.0 h
        ("price", "Day 1: Rifle Falls", False),  # $28 planned, $36 listed
        ("hookups", "Day 2: Devils Garden Campground (Arches)", False),
        ("site length", "Day 2: Devils Garden Campground (Arches)", True),
        ("price", "Day 2: Devils Garden Campground (Arches)", True),
        ("gas price", "CO", True),
        ("clearance", "Old rail bridge", False),  # 10.5 ft on day 1, no warning
        ("clearance", "Low bridge elsewhere", True),  # 9 ft but off the route
    ]
    assert card.score == 5 / 9


def test_details_say_what_reality_says(tmp_path):
    gaps = {(g.kind, g.subject): g.detail for g in scorecard(tmp_path).gaps}
    assert gaps[("drive time", "Day 2")] == "Dave 2.9 h, routing service 4.0 h (27% off)"
    assert gaps[("hookups", "Day 2: Devils Garden Campground (Arches)")] == (
        "recreation.gov lists none; missing electric, water"
    )
    assert gaps[("clearance", "Old rail bridge")] == (
        "10.5 ft, the RV is 11 ft; Day 1, and Dave didn't warn"
    )


def test_a_warned_low_bridge_passes(tmp_path):
    itinerary, _ = demo_1(tmp_path)
    warned = itinerary.days[0].model_copy(
        update={"clearance_warnings": ["Old rail bridge: 10.5 ft clearance"]}
    )
    itinerary = itinerary.model_copy(update={"days": [warned, *itinerary.days[1:]]})
    reference = load_reference("trip-1-denver-moab_synthetic", FIXTURES)
    checks = {c.subject: c for c in score_trip(itinerary, reference).checks}
    assert checks["Old rail bridge"].passed
    assert "CO" not in checks  # no planning prices given, so no gas check


def test_scorecard_markdown_lists_scores_and_gaps(tmp_path):
    text = render_scorecards([scorecard(tmp_path)])
    assert "| trip-1-denver-moab | 9 | 5 | 56% |" in text
    assert "| **All** | 9 | 5 | 56% |" in text
    assert "- trip-1-denver-moab, price, Day 1: Rifle Falls: Dave $28, state park page $36" in text
