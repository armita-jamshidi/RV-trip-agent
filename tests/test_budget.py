from datetime import date

import httpx
from conftest import ConceptEmbedder
from test_campgrounds import Sources
from test_fuel_cost import EIA, client
from test_overnight import COLORADO, DENVER, MINNIE, MOAB, NEED, OSRM

from dave.budget import day_costs, fit_budget
from dave.campgrounds import ingest
from dave.days import split_days
from dave.fuel_cost import estimate_fuel
from dave.gas_prices import fetch
from dave.http import CachedClient
from dave.models import Place, Stop
from dave.overnight import overnight_centers, pick_campgrounds, with_campgrounds
from dave.routing import route

ARCHES = Stop(
    name="Arches National Park",
    location=Place(name="Arches", lat=38.73, lon=-109.59),
    category="Landmarks and Outdoors > National Park",
)


def demo_trip(tmp_path):
    """Demo trip 1 with T17's campgrounds, an Arches stop on day 2 and T21's fuel estimate."""
    osrm = CachedClient(
        tmp_path / "osrm", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=OSRM))
    )
    days = split_days(route([DENVER, MOAB], osrm), DENVER, MOAB, start_date=date(2026, 11, 2))
    days[1] = days[1].model_copy(update={"stops": [ARCHES]})
    camps = CachedClient(tmp_path / "camps", transport=httpx.MockTransport(Sources()))
    moab = ingest(overnight_centers(days)[1:], 30, camps, ridb_key="r", foursquare_key="f")
    picks = pick_campgrounds(days, COLORADO + moab, MINNIE, NEED, ConceptEmbedder())
    prices = fetch(client(tmp_path, EIA()), "key", date(2026, 7, 1))
    fuel = estimate_fuel(days, MINNIE, prices, today=date(2026, 10, 9))
    return days, picks, fuel


def test_rollup_per_day_and_total(tmp_path):
    days, picks, fuel = demo_trip(tmp_path)
    plan = fit_budget(days, picks, fuel, 500)
    assert [(d.fuel_usd, d.campground_usd, d.tickets_usd) for d in plan.per_day] == [
        (44.84, 28, 0),
        (45.28, 25, 30),  # Devils Garden, and the Arches entrance pass
    ]
    assert plan.costs.total_usd == 173.12 and plan.costs.remaining_usd == 326.88
    assert plan.changes == [] and plan.summary()[2] == (
        "Total: $173.12, $326.88 under the $500.00 budget"
    )


def test_over_budget_trip_is_brought_under_with_an_explanation(tmp_path):
    days, picks, fuel = demo_trip(tmp_path)
    plan = fit_budget(days, picks, fuel, 150)
    assert plan.changes == [
        "Night 2: Devils Garden Campground (Arches) ($25) swapped for Ken's Lake Campground "
        "($20), saving $5.00; gives up: mentions arches, scenic, views.",
        "Day 2: dropped Arches National Park, saving $30.00 in tickets.",
    ]
    assert plan.costs.total_usd == 138.12 and not plan.over_by_usd
    assert [d.campground.name for d in plan.days] == ["Rifle Falls", "Ken's Lake Campground"]
    assert plan.picks[1].alternatives[0].campground.name == "Devils Garden Campground (Arches)"
    assert plan.tickets == [] and plan.days[1].stops == []


def test_cheapest_first_swaps_before_dropping_stops(tmp_path):
    days, picks, fuel = demo_trip(tmp_path)
    plan = fit_budget(days, picks, fuel, 170)  # $3.12 over: the $5 swap is enough
    assert len(plan.changes) == 1 and plan.changes[0].startswith("Night 2:")
    assert plan.days[1].stops == [ARCHES]


def test_still_over_says_by_how_much_and_what_to_do(tmp_path):
    days, picks, fuel = demo_trip(tmp_path)
    plan = fit_budget(days, picks, fuel, 100)
    assert plan.over_by_usd == 38.12
    assert plan.summary()[-1] == (
        "Still $38.12 over budget: shorten the trip by a night or pick a closer destination."
    )


def test_extra_nights_are_spent_at_the_last_campground(tmp_path):
    days, picks, fuel = demo_trip(tmp_path)
    plan = fit_budget(days, picks, fuel, None, extra_nights=2)  # 4 nights, 2 driving days
    assert [d.campground_usd for d in plan.per_day] == [28, 75]
    assert plan.costs.budget_usd is None and plan.summary()[2] == "Total: $223.12"


def test_unpriced_campgrounds_are_named(tmp_path):
    days, picks, fuel = demo_trip(tmp_path)
    days = with_campgrounds(days, picks)
    free = days[0].campground.model_copy(update={"nightly_price_usd": None})
    days = [days[0].model_copy(update={"campground": free}), days[1]]
    plan = fit_budget(days, [], fuel, None)
    assert plan.unpriced == ["Rifle Falls"]
    assert plan.summary()[-1] == "No listed price for Rifle Falls; the total may be low."
    assert day_costs(days, fuel, [])[0].campground_usd == 0
