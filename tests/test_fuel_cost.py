import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from test_gas_prices import EIA, client

from dave.days import split_days
from dave.fuel_cost import estimate_fuel, mpg, nearest_state
from dave.gas_prices import fetch
from dave.http import CachedClient
from dave.models import DayLeg, FuelType, Place, RVClass, RVProfile
from dave.routing import route

OSRM = json.loads((Path(__file__).parent / "fixtures/osrm_denver_moab_synthetic.json").read_text())
DENVER = Place(name="Denver, CO", lat=39.7392, lon=-104.9903)
MOAB = Place(name="Moab, UT", lat=38.5733, lon=-109.5498)
TODAY = date(2026, 10, 9)


def rv(**changes) -> RVProfile:
    fields = dict(
        make="Winnebago", model="Minnie Winnie 31K", rv_class=RVClass.C, length_ft=32.75,
        height_ft=11, fuel_type=FuelType.GAS,
    )  # fmt: skip
    return RVProfile(**{**fields, **changes})


@pytest.fixture
def prices(tmp_path):
    return fetch(client(tmp_path, EIA()), "key", date(2026, 7, 1))


@pytest.fixture
def days(tmp_path):
    http = CachedClient(
        tmp_path / "osrm", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=OSRM))
    )
    return split_days(route([DENVER, MOAB], http), DENVER, MOAB, start_date=date(2026, 11, 2))


def test_demo_trip_1_fuel_cost_with_source_and_date(days, prices):
    """Denver to Moab in a Minnie Winnie: 354 mi at the Class C average of 12 mpg."""
    estimate = estimate_fuel(days, rv(), prices, today=TODAY)
    assert estimate.mpg == 12 and estimate.mpg_source == "class average"
    assert estimate.gallons == 29.5
    # Day 1 stays in Colorado; day 2 crosses into Utah, priced at the PADD 4 average.
    assert [d.areas for d in estimate.days] == [["Colorado"], ["Colorado", "PADD 4"]]
    assert estimate.days[0].usd_per_gal == 3.04  # Colorado, mean of the weeks within 60 days
    assert estimate.total_usd == 90.12
    assert estimate.summary() == [
        "Day 1: 177 mi, 14.8 gal at about $3.04/gal (Colorado): $44.84",
        "Day 2: 177 mi, 14.8 gal at about $3.07/gal (Colorado, PADD 4): $45.28",
        "Fuel total: about $90.12 for 29.5 gal of gas at 12 mpg (class average).",
        "Estimate from U.S. EIA weekly retail average prices, week of 2026-10-05.",
    ]


def test_diesel_rv_uses_diesel_prices_and_its_own_mpg(days, prices):
    gas = estimate_fuel(days, rv(), prices, today=TODAY)
    diesel = estimate_fuel(days, rv(fuel_type=FuelType.DIESEL, mpg=15), prices, today=TODAY)
    assert diesel.mpg_source == "RV specs" and diesel.gallons == pytest.approx(354 / 15, abs=0.1)
    assert diesel.days[0].usd_per_gal != gas.days[0].usd_per_gal


def test_class_averages_follow_the_domain_rules():
    assert mpg(rv(rv_class=RVClass.A)) == (8, "class average")
    assert mpg(rv(rv_class=RVClass.B)) == (18, "class average")
    assert mpg(rv(rv_class=RVClass.TRAVEL_TRAILER)) == (10, "class average")


def test_trip_dates_pick_the_price_window(days, prices):
    early = [d.model_copy(update={"travel_date": date(2026, 8, 10)}) for d in days]
    estimate = estimate_fuel(early, rv(), prices, today=TODAY)
    assert estimate.days[0].price_week == date(2026, 8, 3)
    assert estimate.days[0].usd_per_gal == 3.0


def test_unlisted_state_falls_back_to_region_then_us(prices):
    # Nashville, TN: no Tennessee series in the fixture, so its region (PADD 2) is used.
    a, b = Place(name="a", lat=36.16, lon=-86.78), Place(name="b", lat=36.2, lon=-86.6)
    leg = DayLeg(day=1, start=a, end=b, drive_hours=1, miles=12)
    assert estimate_fuel([leg], rv(), prices, today=TODAY).days[0].areas == ["PADD 2"]


def test_no_prices_says_how_to_get_them(days):
    with pytest.raises(ValueError, match="gas-snapshot"):
        estimate_fuel(days, rv(), [], today=TODAY)


@pytest.mark.parametrize(
    ("point", "state"),
    [((39.74, -104.99), "CO"), ((38.57, -109.55), "UT"), ((36.16, -86.78), "TN"),
     ((30.27, -97.74), "TX"), ((39.96, -83.0), "OH"), ((47.61, -122.33), "WA")],
)  # fmt: skip
def test_nearest_state_for_demo_trip_cities(point, state):
    assert nearest_state(point) == state


def test_cli_prints_the_estimate(days, prices, tmp_path, monkeypatch, capsys):
    from dave import cli, gas_prices, routing
    from dave.gas_prices import _rows

    store = tmp_path / "gas"
    store.mkdir()
    (store / "all.json").write_bytes(_rows.dump_json(prices))
    monkeypatch.setattr(gas_prices, "STORE", store)
    monkeypatch.setattr(routing, "route", lambda places, http: _route_for(days))
    monkeypatch.setenv("DAVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("DAVE_OFFLINE", "1")
    args = ["fuel", "Thor Four Winds 28A", "39.7392,-104.9903", "38.5733,-109.5498"]
    assert cli.main([*args, "--on", "2026-11-02"]) == 0
    out = capsys.readouterr().out
    assert "Fuel total: about $" in out and "at 12 mpg (class average)" in out
    assert "Estimate from U.S. EIA weekly retail average prices, week of 2026-10-05." in out

    monkeypatch.setattr(gas_prices, "STORE", tmp_path / "empty")
    assert cli.main(args) == 1


def _route_for(days):
    from dave.models import Route, RouteLeg

    miles = sum(d.miles for d in days)
    hours = sum(d.drive_hours for d in days)
    line = [p for d in days for p in d.geometry]
    return Route(
        miles=miles,
        car_hours=hours,
        drive_hours=hours,
        legs=[RouteLeg(miles=miles, drive_hours=hours)],
        geometry=line,
    )
