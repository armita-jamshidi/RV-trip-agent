import json
from pathlib import Path

import httpx
import pytest

from dave.days import split_days
from dave.http import CachedClient
from dave.interests import interest_matches
from dave.largest_x import searched_stops, seed_stops
from dave.models import Interests, Place
from dave.pitstops import find_pitstops
from dave.routing import route

FIXTURES = Path(__file__).parent / "fixtures"
OSRM = json.loads((FIXTURES / "osrm_austin_nashville_synthetic.json").read_text())
BY_CATEGORY = json.loads((FIXTURES / "largest_x/foursquare_categories_synthetic.json").read_text())
BY_NAME = json.loads((FIXTURES / "largest_x/foursquare_names_synthetic.json").read_text())
AUSTIN = Place(name="Austin, TX", lat=30.2672, lon=-97.7431)
NASHVILLE = Place(name="Nashville, TN", lat=36.1627, lon=-86.7816)

# Demo trip 3: "we love weird roadside attractions and BBQ", in a Class B Revel.
ROADSIDE_FAN = Interests(nature=0.3, museums=0.3, largest_x=0.9, food=0.8)
NO_QUIRKS = Interests(nature=0.8, museums=0.5, largest_x=0.0, food=0.5)
REVEL_FT = 19.8
SEEDED = {"World's Largest Caterpillar", "Pioneer Plaza Cattle Drive", "Athena at the Parthenon"}


class Sources:
    def __init__(self):
        self.searches: list[httpx.URL] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path != "/places/search":
            return httpx.Response(200, json=OSRM)
        self.searches.append(request.url)
        return httpx.Response(200, json=BY_NAME if "query" in request.url.params else BY_CATEGORY)


def client(tmp_path, server) -> CachedClient:
    return CachedClient(tmp_path, transport=httpx.MockTransport(server), sleep=lambda s: None)


@pytest.fixture
def days(tmp_path):
    http = client(tmp_path / "osrm", Sources())
    return split_days(route([AUSTIN, NASHVILLE], http), AUSTIN, NASHVILLE)


def test_seeds_say_what_they_claim_and_count_as_largest_x():
    seeds = seed_stops()
    assert {s.name for s in seeds} == SEEDED
    for s in seeds:
        assert s.description and s.location.address
        assert interest_matches(s) == {"largest_x"}


def test_name_search_keeps_only_places_that_make_the_claim(tmp_path):
    server = Sources()
    found = searched_stops([(30.2672, -97.7431), (30.5, -97.6)], client(tmp_path, server), "k")
    assert {s.name for s in found} == {
        "World's Largest Caterpillar",
        "Arkansas's Biggest Peanut (synthetic)",
    }
    assert {u.params["query"] for u in server.searches} == {"largest", "biggest"}
    assert all("fsq_category_ids" not in u.params for u in server.searches)


def test_austin_to_nashville_surfaces_at_least_two_largest_x_stops(tmp_path, days):
    planned = find_pitstops(
        days, ROADSIDE_FAN, client(tmp_path, Sources()), "k", rv_length_ft=REVEL_FT
    )
    stops = [s for d in planned for s in d.stops]
    quirky = [s for s in stops if "largest_x" in interest_matches(s)]
    assert len(quirky) >= 2
    assert SEEDED <= {s.name for s in stops}
    # The seed and Foursquare's copy of the caterpillar are one stop.
    assert [s.name for s in stops].count("World's Largest Caterpillar") == 1
    caterpillar = next(s for s in stops if s.name == "World's Largest Caterpillar")
    assert "I-35E" in caterpillar.description


def test_no_name_searches_when_the_traveler_does_not_care(tmp_path, days):
    server = Sources()
    planned = find_pitstops(days, NO_QUIRKS, client(tmp_path, server), "k")
    assert all("query" not in u.params for u in server.searches)
    assert not SEEDED & {s.name for d in planned for s in d.stops}
