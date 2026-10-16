import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from test_fuel_cost import DENVER, MOAB, OSRM, TODAY, rv
from test_gas_prices import EIA, client

from dave.days import split_days
from dave.fillups import FillUpPlan, foursquare_station, plan_fillups, stations_along
from dave.gas_prices import fetch
from dave.http import CachedClient
from dave.models import FuelType, RVClass
from dave.routing import route

PLACES = json.loads(
    (Path(__file__).parent / "fixtures/fillups/foursquare_denver_moab_synthetic.json").read_text()
)


@pytest.fixture
def prices(tmp_path):
    return fetch(client(tmp_path, EIA()), "key", date(2026, 7, 1))


def trip(tmp_path, a=DENVER, b=MOAB):
    http = CachedClient(
        tmp_path / "osrm", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=OSRM))
    )
    r = route([a, b], http)
    if a is MOAB:  # the fixture is Denver to Moab; drive it backwards
        r = r.model_copy(update={"geometry": r.geometry[::-1]})
    return split_days(r, a, b, start_date=date(2026, 11, 2))


@pytest.fixture
def stations():
    return [foursquare_station(p, FuelType.GAS) for p in PLACES["results"]]


def show(plan: FillUpPlan) -> list[tuple[int, str, float]]:
    return [(s.day, s.station.name, s.gallons) for s in plan.stops]


def test_demo_trip_1_big_rig_fills_once_at_a_truck_stop(tmp_path, stations, prices):
    plan = plan_fillups(trip(tmp_path), rv(), stations, prices, today=TODAY)
    assert show(plan) == [(1, "Love's Travel Stop", 29.5)]  # not the Costco: too tight for 33 ft
    assert (plan.tank_gal, plan.tank_source) == (55, "class estimate")
    assert plan.stops[0].station.avg_price_60d == 3.04  # Colorado's average, not a station price
    assert plan.saving_usd == 0.44 and plan.baseline_usd == 90.12
    assert plan.summary() == [
        "Day 1: fill 30 gal at Love's Travel Stop (mile 5), about $3.04/gal area average: $89.68",
        "No real saving on this route: average prices are about the same all along ($89.68 "
        "either way).",
        "Only truck stops and travel centers are planned: the RV is too big for most pumps.",
    ]


def test_buys_only_enough_to_reach_a_cheaper_area(tmp_path, stations, prices):
    """Moab to Denver: Utah is dearer than Colorado, so buy little in Utah."""
    plan = plan_fillups(trip(tmp_path, MOAB, DENVER), rv(), stations, prices, today=TODAY)
    assert show(plan) == [(1, "Flying J Travel Center", 10.5), (1, "Love's Travel Stop", 19.0)]
    assert [s.station.avg_price_60d for s in plan.stops] == [3.09, 3.04]


def test_small_tank_stops_again_and_never_runs_low(tmp_path, stations, prices):
    van = rv(rv_class=RVClass.B, length_ft=19.6)  # 25 gal at 18 mpg: 337 mi to a quarter tank
    plan = plan_fillups(trip(tmp_path), van, stations, prices, today=TODAY)
    assert [s.station.name for s in plan.stops] == ["Costco Gasoline", "Love's Travel Stop"]
    assert sum(s.gallons for s in plan.stops) == pytest.approx(354 / 18, abs=0.2)
    assert not plan.warnings  # a van can use any pump


def test_spec_tank_size_wins(tmp_path, stations, prices):
    plan = plan_fillups(trip(tmp_path), rv(fuel_tank_gal=40), stations, prices, today=TODAY)
    assert (plan.tank_gal, plan.tank_source) == (40, "RV specs")


def test_warns_when_no_station_is_in_range(tmp_path, stations, prices):
    van = rv(rv_class=RVClass.B, length_ft=19.6)
    near_start = [s for s in stations if s.name == "Costco Gasoline"]
    plan = plan_fillups(trip(tmp_path), van, near_start, prices, today=TODAY)
    assert "No suitable station within 338 mi after mile 2" in plan.warnings[0]
    assert plan_fillups(trip(tmp_path), van, [], prices, today=TODAY).warnings == [
        "No station found near the start; leave with a full tank."
    ]


def test_truck_stops_are_known_by_category_or_chain():
    def station(name, category="Gas Station"):
        place = {
            "name": name,
            "latitude": 39,
            "longitude": -105,
            "categories": [{"name": category}],
        }
        return foursquare_station(place, FuelType.DIESEL).rv_accessible

    assert station("Love's Travel Stop") and station("Pilot Travel Center")
    assert station("Big Bob's Fuel", "Truck Stop")
    assert station("Shell") is None and station("TAqueria Gas") is None


def test_stations_are_searched_along_the_route(tmp_path):
    requests = []

    def foursquare(request):
        requests.append(request)
        return httpx.Response(200, json=PLACES)

    http = CachedClient(tmp_path / "fsq", transport=httpx.MockTransport(foursquare))
    found = stations_along(trip(tmp_path)[0].geometry, http, "key", FuelType.GAS)
    assert len(found) == len(PLACES["results"])  # each station once, however many searches
    assert len(requests) > 1
    assert requests[0].url.params["fsq_category_ids"] == "4bf58dd8d48988d113951735"
