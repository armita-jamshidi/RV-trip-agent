import copy
from datetime import date
from pathlib import Path

import httpx
from conftest import ConceptEmbedder
from test_campgrounds import Sources as Campgrounds
from test_gas_prices import EIA
from test_gas_prices import client as eia_client
from test_google_places import Google
from test_overnight import OSRM

from dave import cli, planner
from dave.gas_prices import fetch
from dave.http import CachedClient
from dave.models import ConstraintSpec
from dave.parser import ParseResult
from dave.planner import Sources, plan_trip

FIXTURES = Path(__file__).parent / "fixtures"
MINNIE_PAGE = (FIXTURES / "rv_specs" / "winnebago_minnie_winnie.html").read_text()
REQUEST = (
    "We have a 2023 Winnebago Minnie Winnie 31K. Denver to Moab, 4 nights in November, "
    "$1,500, love hiking and big views."
)
SPEC = ConstraintSpec(
    origin="Denver, CO",
    destination="Moab, UT",
    start_date=date(2026, 11, 2),
    nights=4,
    budget_usd=1500,
)
PLACES = {"Denver, CO": (39.7392, -104.9903), "Moab, UT": (38.5733, -109.5498)}

# Synthetic RIDB records (documented v1 format) for the Colorado night of the Denver-Moab drive.
RIFLE = {
    "RECDATA": [
        {
            "FacilityID": "300001",
            "FacilityName": "Rifle Falls",
            "FacilityTypeDescription": "Campground",
            "FacilityLatitude": 39.675,
            "FacilityLongitude": -107.70,
            "FacilityUseFeeDescription": "$28 per night",
            "Reservable": True,
            "FacilityDescription": "<p>Forest campground by the waterfall and creek.</p>",
        }
    ],
    "METADATA": {"RESULTS": {"CURRENT_COUNT": 1, "TOTAL_COUNT": 1}},
}
RIFLE_SITES = {
    "RECDATA": [
        {
            "CampsiteID": "31",
            "CampsiteName": "R1",
            "CampsiteType": "RV ELECTRIC",
            "ATTRIBUTES": [
                {"AttributeName": "Electricity Hookup", "AttributeValue": "30"},
                {"AttributeName": "Water Hookup", "AttributeValue": "Y"},
            ],
            "PERMITTEDEQUIPMENT": [{"EquipmentName": "RV", "MaxLength": 40}],
        }
    ],
    "METADATA": {"RESULTS": {"CURRENT_COUNT": 1, "TOTAL_COUNT": 1}},
}


class World:
    """Every source the planner calls, by host, served from synthetic fixtures."""

    def __init__(self):
        self.camps = Campgrounds()
        self.google = Google()
        self.hosts: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host, params = request.url.host, request.url.params
        self.hosts.append(host)
        if host == "nominatim.openstreetmap.org":
            lat, lon = PLACES[params["q"]]
            return httpx.Response(200, json=[{"lat": str(lat), "lon": str(lon)}])
        if host == "router.project-osrm.org":
            body = copy.deepcopy(OSRM)
            if request.url.path.split("/")[-1].startswith(f"{PLACES['Moab, UT'][1]}"):
                line = body["routes"][0]["geometry"]["coordinates"]
                body["routes"][0]["geometry"]["coordinates"] = line[::-1]
            return httpx.Response(200, json=body)
        if host == "overpass-api.de":
            return httpx.Response(200, json={"elements": []})
        if host == "places.googleapis.com":
            return self.google(request)
        if host == "www.winnebago.com":
            return httpx.Response(200, text=MINNIE_PAGE)
        if request.url.path == "/api/v1/facilities" and float(params["latitude"]) > 39.2:
            return httpx.Response(200, json=RIFLE)
        if request.url.path == "/api/v1/facilities/300001/campsites":
            return httpx.Response(200, json=RIFLE_SITES)
        return self.camps(request)


def sources(tmp_path, world=None, *, ridb_key="r", eia=True, google=None) -> Sources:
    http = CachedClient(tmp_path / "http", transport=httpx.MockTransport(world or World()))
    prices = fetch(eia_client(tmp_path / "eia", EIA()), "key", date(2026, 7, 1)) if eia else []
    return Sources(http, ConceptEmbedder(), prices, ridb_key=ridb_key, google_places_key=google)


def test_demo_trip_1_is_planned_end_to_end_and_valid(tmp_path):
    world = World()
    trip = plan_trip(REQUEST, SPEC, sources(tmp_path, world), today=date(2026, 10, 16))
    text = trip.markdown()

    assert trip.errors == [] and "Not final" not in text
    assert "4 nights in a 2023 Winnebago Minnie Winnie 31K" in text
    assert "## Day 1 · Mon Nov 02: Denver, CO to Rifle Falls" in text
    assert "## Day 2 · Tue Nov 03: Rifle Falls to Devils Garden Campground (Arches)" in text
    assert "**Tonight and the next 2**" in text
    # Campgrounds are proposed for approval, the Moab one for all three nights.
    bookings = {b.name: b for b in trip.itinerary.bookings}
    devils = bookings["Devils Garden Campground (Arches)"]
    assert (devils.start_date, devils.end_date, devils.price_usd) == (
        date(2026, 11, 3),
        date(2026, 11, 6),
        75,
    )
    assert bookings["Rifle Falls"].price_usd == 28
    assert "## Bookings to approve" in text and "Nothing is booked or paid" in text
    assert trip.itinerary.costs.campgrounds_usd == 103
    assert "Budget $1,500.00:" in text and "to spare" in text
    assert "- No stops, food or gas stations: they need a FOURSQUARE_API_KEY." in text
    assert {"nominatim.openstreetmap.org", "overpass-api.de", "www.winnebago.com"} <= set(
        world.hosts
    )


def test_round_trip_spends_extra_nights_at_the_destination_then_drives_home(tmp_path):
    spec = SPEC.model_copy(update={"round_trip": True, "nights": 5})
    trip = plan_trip(REQUEST, spec, sources(tmp_path), today=date(2026, 10, 16))
    days = trip.itinerary.days

    assert trip.errors == []
    assert [d.travel_date.day for d in days] == [2, 3, 6, 7]  # 3 nights in Moab, then home
    assert days[-1].campground is None and days[-1].end.name == "Denver, CO"
    devils = next(b for b in trip.itinerary.bookings if b.name.startswith("Devils"))
    assert (devils.start_date, devils.end_date) == (date(2026, 11, 3), date(2026, 11, 6))
    assert "**Tonight and the next 2**" in trip.markdown()


def test_too_few_nights_are_raised_and_said(tmp_path):
    spec = SPEC.model_copy(update={"nights": 1})
    trip = plan_trip(REQUEST, spec, sources(tmp_path), today=date(2026, 10, 16))
    assert trip.itinerary.spec.nights == 2
    assert "takes 2 nights, not 1; planned with 2." in trip.markdown()


def test_no_start_date_plans_two_weeks_out_and_says_so(tmp_path):
    spec = SPEC.model_copy(update={"start_date": None})
    trip = plan_trip(REQUEST, spec, sources(tmp_path), today=date(2026, 10, 16))
    assert trip.itinerary.days[0].travel_date == date(2026, 10, 30)
    assert "No start date given; planned from Fri Oct 30." in trip.markdown()


def test_without_a_campground_key_the_plan_is_not_final(tmp_path):
    trip = plan_trip(REQUEST, SPEC, sources(tmp_path, ridb_key=None), today=date(2026, 10, 16))
    text = trip.markdown()
    assert "> **Not final: this plan breaks a rule.**" in text
    assert "> - Day 1: no campground for the night." in text
    assert "- No campgrounds: they need a RIDB_API_KEY." in text


def test_an_unknown_rv_gets_a_question(tmp_path):
    trip = plan_trip("Denver to Moab, 4 nights", SPEC, sources(tmp_path), today=date(2026, 10, 16))
    assert trip.itinerary is None
    assert trip.markdown().startswith("Which RV is it?")


def test_cli_plan_prints_and_saves_the_itinerary(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DAVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(planner, "plan_trip", lambda *a, **k: _fake_trip(tmp_path))
    monkeypatch.setattr("dave.parser.parse_request", lambda *a, **k: ParseResult(spec=SPEC))
    monkeypatch.setattr("dave.store.vectors.FastEmbedder", lambda *a, **k: ConceptEmbedder())
    out = tmp_path / "trip.md"

    assert cli.main(["plan", REQUEST, "--out", str(out)]) == 0
    assert "## Day 1 · Mon Nov 02" in capsys.readouterr().out
    assert out.read_text(encoding="utf-8").startswith("# Denver, CO to Moab, UT")


def test_cli_plan_asks_for_what_is_missing(monkeypatch, capsys):
    question = ParseResult(missing=["rv"], question="To plan your trip I need your RV.")
    monkeypatch.setattr("dave.parser.parse_request", lambda *a, **k: question)
    assert cli.main(["plan", "somewhere nice"]) == 2
    assert "I need your RV" in capsys.readouterr().out


def _fake_trip(tmp_path):
    return plan_trip(REQUEST, SPEC, sources(tmp_path / "fake"), today=date(2026, 10, 16))


class OverpassDown(World):
    def __call__(self, request):
        if request.url.host == "overpass-api.de":
            return httpx.Response(406, text="Not Acceptable")
        return super().__call__(request)


def test_unchecked_bridges_mark_the_plan_not_final_instead_of_crashing(tmp_path):
    trip = plan_trip(REQUEST, SPEC, sources(tmp_path, OverpassDown()), today=date(2026, 10, 16))
    text = trip.markdown()
    assert "> **Not final: this plan breaks a rule.**" in text
    assert "> - Day 1: bridge heights weren't checked (Overpass answered 406)" in text
    assert "## Costs" in text and "## Bookings to approve" in text


def test_dashboard_plans_with_the_same_pipeline(monkeypatch):
    from dave.dashboard import agent_planner

    monkeypatch.setattr("dave.parser.parse_request", lambda *a, **k: ParseResult(question="Q?"))
    assert agent_planner("somewhere nice") == "Q?\n"


def test_google_station_prices_price_the_fuel_and_the_fill_ups_without_eia(tmp_path):
    world = World()
    src = sources(tmp_path, world, eia=False, google="g")
    trip = plan_trip(REQUEST, SPEC, src, today=date(2026, 10, 16))
    text = trip.markdown()

    assert trip.errors == [] and world.google.requests
    assert trip.itinerary.costs.fuel_usd > 0
    assert "No gas prices stored" not in text
    assert "- No stops or food: they need a FOURSQUARE_API_KEY." in text
    assert "**Gas**\n- Love's Travel Stop, about $" in text and "/gal (area average)" in text


def test_a_google_error_is_a_note_not_a_crash(tmp_path):
    world = World()
    world.google = Google(403)
    trip = plan_trip(REQUEST, SPEC, sources(tmp_path, world, google="g"), today=date(2026, 10, 16))
    assert "No station prices (Google Places answered 403); fuel uses EIA averages." in (
        trip.markdown()
    )
    assert trip.itinerary.costs.fuel_usd > 0
