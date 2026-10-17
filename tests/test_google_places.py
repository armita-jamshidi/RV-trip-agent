import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from test_fillups import trip
from test_fuel_cost import rv
from test_gas_prices import EIA, client

from dave import google_places
from dave.fillups import plan_fillups
from dave.fuel_cost import estimate_fuel
from dave.gas_prices import fetch
from dave.geo import haversine_miles
from dave.http import CachedClient, SourceError
from dave.models import FuelType

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/google_places/denver_moab_synthetic.json").read_text()
)
TODAY = date(2026, 10, 16)


class Google:
    """Places API (New) Nearby Search: every station in the fixture inside the circle."""

    def __init__(self, status: int = 200):
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"status": "PERMISSION_DENIED"}})
        circle = json.loads(request.content)["locationRestriction"]["circle"]
        c, r = circle["center"], circle["radius"] / 1609.344
        inside = [
            p
            for p in FIXTURE["places"]
            if haversine_miles(
                (c["latitude"], c["longitude"]),
                (p["location"]["latitude"], p["location"]["longitude"]),
            )
            <= r
        ]
        return httpx.Response(200, json={"places": inside} if inside else {})


def http(tmp_path, server) -> CachedClient:
    return CachedClient(tmp_path / "http", transport=httpx.MockTransport(server))


def stations(tmp_path, server=None, fuel_type=FuelType.GAS):
    line = [p for d in trip(tmp_path) for p in d.geometry]
    return google_places.stations_along(
        line, http(tmp_path, server or Google()), "g-key", fuel_type, today=TODAY
    )


def test_stations_carry_their_posted_price_when_recent(tmp_path):
    found = {s.name + f"@{s.location.lon}": s for s in stations(tmp_path)}
    assert len(found) == 8
    shell = found["Shell@-105.9435"]
    assert shell.price_per_gal == 3.29 and shell.rv_accessible is None
    assert found["Pilot Travel Center@-107.4476"].rv_accessible is True  # Google's truck_stop
    assert found["Love's Travel Stop@-105.0687"].price_per_gal is None  # no fuelOptions
    assert found["Love's Travel Stop@-108.4284"].price_per_gal is None  # price is from August


def test_diesel_reads_the_diesel_price(tmp_path):
    shell = next(s for s in stations(tmp_path, fuel_type=FuelType.DIESEL) if s.name == "Shell")
    assert shell.price_per_gal == 3.79


def test_searches_are_capped_sent_with_the_key_in_a_header_and_never_cached(tmp_path):
    server = Google()
    stations(tmp_path, server)
    assert 1 < len(server.requests) <= google_places.MAX_SEARCHES
    sent = server.requests[0]
    assert sent.headers["X-Goog-Api-Key"] == "g-key"
    assert "places.fuelOptions" in sent.headers["X-Goog-FieldMask"]
    assert "g-key" not in str(sent.url)
    assert not (tmp_path / "http").exists()  # prices are not stored (Google's terms)


def test_an_error_is_raised_for_the_planner_to_note(tmp_path):
    with pytest.raises(SourceError, match="Google Places answered 403"):
        stations(tmp_path, Google(403))


def test_station_prices_price_each_state_and_the_rest_of_the_route(tmp_path):
    rows = {p.area: p for p in google_places.area_prices(stations(tmp_path), today=TODAY)}
    assert set(rows) == {"SCO", "SUT", "NUS"}
    assert rows["SCO"].usd_per_gal == pytest.approx((2.89 + 3.29 + 3.15) / 3, abs=0.001)
    assert rows["SUT"].area_name == "UT stations (Google)" and rows["SUT"].period == TODAY


def test_station_prices_replace_eia_only_where_they_exist(tmp_path):
    eia = fetch(client(tmp_path / "eia", EIA()), "key", date(2026, 7, 1))
    found = google_places.area_prices(stations(tmp_path), today=TODAY)
    merged = google_places.with_station_prices(eia, found)
    gas_co = [p for p in merged if p.area == "SCO" and p.fuel_type == FuelType.GAS]
    assert [p.area_name for p in gas_co] == ["CO stations (Google)"]
    assert [p for p in merged if p.area == "SCO" and p.fuel_type == FuelType.DIESEL]  # not priced
    assert [p for p in merged if p.area == "R40"]  # EIA's Rocky Mountain region stays


def test_fuel_cost_and_fill_ups_work_from_station_prices_alone(tmp_path):
    days = trip(tmp_path)
    found = stations(tmp_path)
    prices = google_places.area_prices(found, today=TODAY)

    fuel = estimate_fuel(days, rv(), prices, today=TODAY)
    assert fuel.total_usd > 0 and "CO stations (Google)" in fuel.days[0].areas

    plan = plan_fillups(days, rv(length_ft=24), found, prices, today=TODAY)
    assert plan.stops[0].station.name == "Costco Gasoline"  # $2.89 posted, the cheapest
    assert plan.summary()[0].endswith("$2.89/gal posted: " + f"${plan.stops[0].usd:,.2f}")
