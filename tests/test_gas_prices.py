import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from dave import cli, gas_prices
from dave.gas_prices import collect, coverage, fetch, load, price_for
from dave.http import CachedClient, SourceError
from dave.models import FuelType

FIXTURE = Path(__file__).parent / "fixtures" / "gas_prices" / "eia_weekly_synthetic.json"
TODAY = date(2026, 10, 9)


class EIA:
    """Serves the synthetic EIA response a page at a time, like the real API."""

    def __init__(self, status: int = 200):
        self.body = json.loads(FIXTURE.read_text())
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, text="API_KEY_INVALID")
        offset, length = int(request.url.params["offset"]), int(request.url.params["length"])
        rows = self.body["response"]["data"][offset : offset + length]
        return httpx.Response(200, json={"response": {**self.body["response"], "data": rows}})


def client(tmp_path, server) -> CachedClient:
    return CachedClient(tmp_path / "http", transport=httpx.MockTransport(server))


def test_fetch_keeps_us_region_and_state_rows_with_prices(tmp_path):
    prices = fetch(client(tmp_path, EIA()), "key", date(2026, 7, 1))
    areas = {p.area for p in prices}
    assert areas == {"NUS", "R10", "R1Z", "R20", "R40", "SCO"}  # city series dropped
    assert len(prices) == 4 * 2 * 6 - 1  # one week has no Colorado diesel price
    assert {p.fuel_type for p in prices} == {FuelType.GAS, FuelType.DIESEL}


def test_fetch_follows_pages_and_keeps_the_key_out_of_the_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(gas_prices, "PAGE", 20)
    server = EIA()
    assert len(fetch(client(tmp_path, server), "secret-key", date(2026, 7, 1))) == 47
    assert [r.url.params["offset"] for r in server.requests] == ["0", "20", "40"]
    assert all(r.url.params["api_key"] == "secret-key" for r in server.requests)
    assert server.requests[0].url.params.get_list("facets[product][]") == ["EPMR", "EPD2D"]
    cached = "".join(p.read_text() for p in (tmp_path / "http").glob("*.json"))
    assert "secret-key" not in cached
    # A rerun with a different key is served from the cache.
    fetch(client(tmp_path, server), "other-key", date(2026, 7, 1))
    assert len(server.requests) == 3


def test_fetch_reports_eia_errors(tmp_path):
    with pytest.raises(SourceError, match="403"):
        fetch(client(tmp_path, EIA(status=403)), "bad", date(2026, 7, 1))


def test_collect_saves_each_week_once(tmp_path):
    store = tmp_path / "gas"
    saved = collect(client(tmp_path, EIA()), "key", store, today=TODAY)
    assert saved == [date(2026, 8, 3), date(2026, 9, 21), date(2026, 9, 28), date(2026, 10, 5)]
    assert sorted(f.name for f in store.iterdir())[-1] == "2026-10-05.json"
    assert collect(client(tmp_path, EIA()), "key", store, today=TODAY) == []
    assert len(load(store)) == 47


def test_collect_rewrites_a_week_eia_revised(tmp_path):
    store = tmp_path / "gas"
    collect(client(tmp_path, EIA()), "key", store, today=TODAY)
    revised = EIA()
    revised.body["response"]["data"][0]["value"] = "3.333"
    saved = collect(client(tmp_path / "rerun", revised), "key", store, today=TODAY)
    assert saved == [date(2026, 10, 5)]


@pytest.fixture
def prices(tmp_path):
    store = tmp_path / "gas"
    collect(client(tmp_path, EIA()), "key", store, today=TODAY)
    return load(store)


def test_a_state_with_its_own_series_uses_it(prices):
    p = price_for(prices, "co", FuelType.GAS, TODAY)
    assert (p.area, p.period) == ("SCO", date(2026, 10, 5))
    assert p.usd_per_gal == pytest.approx((3.06 + 3.04 + 3.02) / 3, abs=1e-3)  # Aug 3 is too old


def test_other_states_use_their_region_then_the_us(prices):
    assert price_for(prices, "UT", FuelType.GAS, TODAY).area == "R40"
    assert price_for(prices, "GA", FuelType.GAS, TODAY).area == "R1Z"
    assert price_for(prices, "NJ", FuelType.GAS, TODAY).area == "R10"  # R1Y not in the snapshot
    assert price_for(prices, "AZ", FuelType.GAS, TODAY).area == "NUS"  # no West Coast rows


def test_missing_weeks_are_skipped_not_zero(prices):
    p = price_for(prices, "CO", FuelType.DIESEL, TODAY)
    assert p.usd_per_gal == pytest.approx((3.81 + 3.77) / 2, abs=1e-3)


def test_a_future_trip_uses_the_newest_two_months(prices):
    later = price_for(prices, "CO", FuelType.GAS, date(2027, 5, 1))
    assert later == price_for(prices, "CO", FuelType.GAS, TODAY)


def test_a_past_date_uses_the_weeks_before_it(prices):
    p = price_for(prices, "CO", FuelType.GAS, date(2026, 9, 1))
    assert (p.period, p.usd_per_gal) == (date(2026, 8, 3), 3.0)


def test_no_snapshots_means_no_price():
    assert price_for([], "CO", FuelType.GAS, TODAY) is None


def test_coverage_names_states_with_and_without_their_own_series(prices):
    report = coverage(prices)
    assert (report["weeks"], report["first"], report["last"]) == (4, "2026-08-03", "2026-10-05")
    assert report["states_with_own_series"] == ["CO"]
    assert "UT" in report["states_using_region"] and "CO" not in report["states_using_region"]


def test_cli_gas_price_reads_snapshots(prices, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gas_prices, "STORE", tmp_path / "gas")
    assert cli.main(["gas-price", "ut", "--on", "2026-10-09"]) == 0
    assert "$3.090/gal gas in UT, estimated from the EIA PADD 4 average" in capsys.readouterr().out
    monkeypatch.setattr(gas_prices, "STORE", tmp_path / "empty")
    assert cli.main(["gas-price", "UT"]) == 1
