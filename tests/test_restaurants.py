import json
from pathlib import Path

import httpx
from conftest import ConceptEmbedder
from test_campgrounds import Sources as CampSources
from test_overnight import COLORADO, DENVER, MINNIE, MOAB, NEED, OSRM

from dave.campgrounds import ingest
from dave.days import split_days
from dave.http import CachedClient
from dave.models import DayLeg, Place, Restaurant
from dave.overnight import overnight_centers, pick_campgrounds, with_campgrounds
from dave.pitstops import CROWDED_NOTE
from dave.restaurants import candidate_restaurants, lunch_point, pick_meal, plan_meals
from dave.routing import route

PLACES = json.loads(
    (
        Path(__file__).parent / "fixtures/restaurants/foursquare_denver_moab_synthetic.json"
    ).read_text()
)


class Foursquare:
    def __init__(self, places=PLACES):
        self.places, self.requests = places, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=self.places)


def client(tmp_path, server) -> CachedClient:
    return CachedClient(tmp_path, transport=httpx.MockTransport(server), sleep=lambda s: None)


def trip_days(tmp_path) -> list[DayLeg]:
    """Demo trip 1 routed, split into days and given T17's campgrounds."""
    days = split_days(
        route([DENVER, MOAB], client(tmp_path / "osrm", lambda r: httpx.Response(200, json=OSRM))),
        DENVER,
        MOAB,
    )
    camps = client(tmp_path / "camps", CampSources())
    moab = ingest(overnight_centers(days)[1:], 30, camps, ridb_key="r", foursquare_key="f")
    picks = pick_campgrounds(days, COLORADO + moab, MINNIE, NEED, ConceptEmbedder())
    return with_campgrounds(days, picks)


def meal(name, cuisine, rating=None, price=None, lat=39.64, lon=-106.37) -> Restaurant:
    return Restaurant(
        name=name,
        location=Place(name=name, lat=lat, lon=lon),
        cuisine=cuisine,
        rating=rating,
        price_level=price,
    )


def test_demo_trip_1_gets_lunch_and_dinner_every_day(tmp_path):
    server = Foursquare()
    days = plan_meals(trip_days(tmp_path), client(tmp_path / "fsq", server), "key")
    meals = [[(r.meal, r.name) for r in d.restaurants] for d in days]
    assert meals == [
        [("lunch", "Gore Creek Grill"), ("dinner", "Rifle Creek Diner")],
        [("lunch", "Loma Junction BBQ"), ("dinner", "Slickrock Burgers")],
    ]
    # Dinner is searched around the night's campground, not the overnight area.
    centers = [r.url.params["ll"] for r in server.requests]
    assert centers[1] == "39.675,-107.7" and centers[3] == "38.7783,-109.5874"
    assert all(
        r.url.params["fsq_category_ids"] == "4d4b7105d754a06374d81259" for r in server.requests
    )
    assert "rating" not in server.requests[0].url.params["fields"]  # paid field, not requested


def test_coffee_shops_and_far_places_are_not_meals(tmp_path):
    found = candidate_restaurants((39.64, -106.37), client(tmp_path, Foursquare()), "key")
    assert sorted(r.name for r in found) == ["Gore Creek Grill", "Vail Taqueria"]


def test_rated_below_threshold_is_dropped_and_rating_wins():
    options = [
        meal("Low", "Diner", rating=6.9),
        meal("High", "Diner", rating=9.1),
        meal("None", "Diner"),
    ]
    pick = pick_meal("lunch", options, {"Low": 0, "High": 5, "None": 0}, set())
    assert pick.name == "High" and pick.meal == "lunch" and pick.detour_minutes == 5
    assert pick_meal("lunch", options[:1], {"Low": 0}, set()) is None


def test_a_new_cuisine_beats_a_repeat():
    options = [meal("Taco Two", "Mexican Restaurant"), meal("Noodle Bar", "Ramen Restaurant")]
    pick = pick_meal("dinner", options, {"Taco Two": 0, "Noodle Bar": 6}, {"Mexican Restaurant"})
    assert pick.name == "Noodle Bar"


def test_cheaper_wins_when_all_else_is_equal():
    options = [meal("Steakhouse", "Steakhouse", price=4), meal("Diner", "Diner", price=1)]
    assert pick_meal("dinner", options, {"Steakhouse": 0, "Diner": 0}, set()).name == "Diner"


def test_big_rig_gets_parking_warning_in_dense_areas():
    downtown = [meal(f"Place {i}", f"Cuisine {i}", lat=39.64 + i * 0.0005) for i in range(8)]
    detours = {r.name: 0 for r in downtown}
    assert (
        pick_meal("lunch", downtown, detours, set(), big_rig=True).rv_parking_note == CROWDED_NOTE
    )
    assert pick_meal("lunch", downtown, detours, set()).rv_parking_note is None


def test_lunch_is_halfway_along_the_day():
    day = DayLeg(
        day=1, start=DENVER, end=MOAB, drive_hours=4, miles=200,
        geometry=[(39.0, -105.0), (39.0, -106.0), (39.0, -107.0)],
    )  # fmt: skip
    lat, lon = lunch_point(day)
    assert round(lat, 3) == 39.0 and round(lon, 3) == -106.0


def test_nothing_nearby_leaves_the_meal_out(tmp_path):
    days = plan_meals(
        trip_days(tmp_path), client(tmp_path / "fsq", Foursquare({"results": []})), "k"
    )
    assert all(d.restaurants == [] for d in days)
