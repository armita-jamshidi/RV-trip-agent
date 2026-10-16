import os
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from test_budget import demo_trip
from test_overnight import DENVER, MINNIE

from dave.budget import fit_budget
from dave.models import ConstraintSpec, DayLeg, Itinerary, Place, Restaurant, Stop
from dave.render import directions_link, render_markdown

DEMO_1 = Path(__file__).parents[1] / "demo" / "itinerary-1-denver-moab.md"
SPEC_1 = ConstraintSpec(
    origin="Denver, CO",
    destination="Moab, UT",
    start_date=date(2026, 11, 2),
    nights=4,
    budget_usd=1500,
)
DEMO_NOTE = (
    "Built from hand-written test data, not live sources: routing, campground and gas price "
    "services are blocked where this was generated. Rerun once they are reachable."
)


def demo_1(tmp_path) -> tuple[Itinerary, list]:
    """Demo trip 1: two driving days, then two more nights at the Moab campground."""
    days, picks, fuel = demo_trip(tmp_path)
    plan = fit_budget(days, picks, fuel, SPEC_1.budget_usd, extra_nights=2)
    itinerary = Itinerary(
        spec=SPEC_1, rv=MINNIE, days=plan.days, costs=plan.costs, bookings=plan.tickets
    )
    return itinerary, plan.per_day


def test_demo_trip_1_matches_the_saved_itinerary(tmp_path):
    """demo/ holds the rendered demo trip; DAVE_UPDATE_DEMO=1 rewrites it after a change."""
    itinerary, per_day = demo_1(tmp_path)
    text = render_markdown(itinerary, per_day=per_day, notes=[DEMO_NOTE])
    if os.environ.get("DAVE_UPDATE_DEMO"):
        DEMO_1.write_text(text)
    assert text == DEMO_1.read_text()


def test_itinerary_reads_day_by_day_with_costs_and_bookings(tmp_path):
    itinerary, per_day = demo_1(tmp_path)
    text = render_markdown(itinerary, per_day=per_day)
    assert "4 nights in a Winnebago Minnie Winnie 31K (32.75 ft long, 11 ft tall)." in text
    assert "## Day 1 · Mon Nov 02: Denver, CO to Rifle Falls" in text
    assert "## Day 2 · Tue Nov 03: Rifle Falls to Devils Garden Campground (Arches)" in text
    assert "**Tonight and the next 2**" in text
    assert "- Rifle Falls, $28 a night, electric + water hookups" in text
    assert "- Arches National Park\n" in text
    assert "[Devils Garden Campground (Arches), $25 a night, electric + water hookups](" in text
    # Day 2's campground is booked for three nights: $75.
    assert "| Day 2 | $45.28 | $75.00 | $30.00 | $150.28 |" in text
    assert "| **Trip** | $90.12 | $103.00 | $30.00 | **$223.12** |" in text
    assert "Budget $1,500.00: $1,276.88 to spare." in text
    assert "## Bookings to approve" in text and "(proposed)" in text
    assert "Not final" not in text


def test_a_plan_that_breaks_a_rule_is_marked_not_final(tmp_path):
    itinerary, _ = demo_1(tmp_path)
    long_day = itinerary.days[0].model_copy(update={"drive_hours": 6.5})
    text = render_markdown(itinerary.model_copy(update={"days": [long_day, *itinerary.days[1:]]}))
    assert "> **Not final: this plan breaks a rule.**" in text
    assert "> - Day 1: 6.5 h of driving is over the 5 h limit; split it or stop sooner." in text


def test_directions_go_through_the_stops_to_the_campground():
    stop = Stop(name="Lookout", location=Place(name="x", lat=39.5, lon=-106.0), category="View")
    day = DayLeg(
        day=1,
        start=DENVER,
        end=Place(name="Glenwood Springs", lat=39.55, lon=-107.32),
        drive_hours=3,
        miles=160,
        stops=[stop],
    )
    query = parse_qs(urlparse(directions_link(day)).query)
    assert query["origin"] == ["39.73920,-104.99030"]
    assert query["waypoints"] == ["39.50000,-106.00000"]
    assert query["destination"] == ["39.55000,-107.32000"]
    assert query["travelmode"] == ["driving"]


def test_food_and_unpriced_campground_lines():
    day = DayLeg(
        day=1,
        start=DENVER,
        end=Place(name="Glenwood Springs", lat=39.55, lon=-107.32),
        drive_hours=3,
        miles=160,
        restaurants=[
            Restaurant(
                name="Slope & Hatch", location=DENVER, cuisine="Tacos", rating=8.6, price_level=1
            )
        ],
    )
    itinerary = Itinerary(spec=SPEC_1, rv=MINNIE, days=[day])
    text = render_markdown(itinerary)
    assert "**Food**\n- Slope & Hatch (Tacos, rated 8.6/10, $)" in text
    assert "> - Day 1: no campground for the night." in text
