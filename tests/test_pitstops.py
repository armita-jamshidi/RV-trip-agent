import json
from pathlib import Path

import httpx
import pytest

from dave import cli
from dave.days import split_days
from dave.http import CachedClient
from dave.models import DayLeg, Interests, Place, Stop
from dave.pitstops import (
    CROWDED_NOTE,
    MAX_STOPS_PER_DAY,
    candidate_stops,
    find_pitstops,
    plan_stops,
)
from dave.routing import route

FIXTURES = Path(__file__).parent / "fixtures"
OSRM = json.loads((FIXTURES / "osrm_denver_moab_synthetic.json").read_text())
PLACES = json.loads((FIXTURES / "pitstops/foursquare_denver_moab_synthetic.json").read_text())
DENVER = Place(name="Denver, CO", lat=39.7392, lon=-104.9903)
MOAB = Place(name="Moab, UT", lat=38.5733, lon=-109.5498)

# Demo trip 1 loves hiking and big views; demo trip 2 loves museums.
HIKER = Interests(nature=0.9, museums=0.1, largest_x=0.0, food=0.5)
MUSEUM_GOER = Interests(nature=0.1, museums=0.9, largest_x=0.0, food=0.5)
MINNIE_WINNIE_FT = 31.5
REVEL_FT = 19.8


class Sources:
    def __init__(self):
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/places/search":
            return httpx.Response(200, json=PLACES)
        return httpx.Response(200, json=OSRM)


def client(tmp_path, server) -> CachedClient:
    return CachedClient(tmp_path, transport=httpx.MockTransport(server), sleep=lambda s: None)


@pytest.fixture
def days(tmp_path):
    http = client(tmp_path / "osrm", Sources())
    return split_days(route([DENVER, MOAB], http), DENVER, MOAB)


def names(day: DayLeg) -> list[str]:
    return [s.name for s in day.stops]


def test_candidates_are_deduplicated_and_skip_generic_places(tmp_path, days):
    server = Sources()
    line = [p for d in days for p in d.geometry]
    found = candidate_stops(line, client(tmp_path, server), "fsq-key")
    assert len(server.requests) > 1  # one search per stretch of the corridor
    assert len(found) == len({s.name for s in found}) == 16
    assert not {"Cheesman Park", "Washington Park Playground"} & {s.name for s in found}

    hanging_lake = next(s for s in found if s.name == "Hanging Lake Trail")
    assert hanging_lake.category == "Hiking Trail"
    red_rocks = next(s for s in found if s.name.startswith("Red Rocks"))
    assert red_rocks.category == "Park, Music Venue"  # kept: not only a generic park

    request = server.requests[0]
    assert request.headers["Authorization"] == "Bearer fsq-key"
    assert "rating" not in request.url.params["fields"]  # paid field
    assert "popularity" not in request.url.params["fields"]


def test_hikers_and_museum_goers_get_different_stops(tmp_path, days):
    hiker = find_pitstops(days, HIKER, client(tmp_path, Sources()), "k")
    museums = find_pitstops(days, MUSEUM_GOER, client(tmp_path, Sources()), "k")

    assert names(hiker[0]) == [
        "Red Rocks Park and Amphitheatre",
        "Hanging Lake Trail",
        "Glenwood Hot Springs",
    ]
    assert {"Colorado National Monument", "Arches National Park"} <= set(names(hiker[1]))
    assert all("Museum" not in n for d in hiker for n in names(d))
    assert names(museums[0])[0] == "Denver Firefighters Museum"
    assert all("Museum" in n for n in names(museums[0]))
    assert names(museums[1])[0] == "Museum of the West"


def test_every_day_gets_one_to_three_stops_in_trip_order(tmp_path, days):
    for day in find_pitstops(days, HIKER, client(tmp_path, Sources()), "k"):
        assert 1 <= len(day.stops) <= MAX_STOPS_PER_DAY
    planned = find_pitstops(days, HIKER, client(tmp_path, Sources()), "k")
    # Red Rocks is near Denver, Glenwood Hot Springs 160 miles on.
    assert names(planned[0])[0].startswith("Red Rocks")
    assert names(planned[0])[-1] == "Glenwood Hot Springs"


def test_far_away_places_are_never_picked(tmp_path, days):
    planned = find_pitstops(days, HIKER, client(tmp_path, Sources()), "k")
    assert "Mesa Verde National Park" not in {n for d in planned for n in names(d)}


def test_detours_fit_under_the_daily_driving_limit():
    long_day = DayLeg(
        day=1,
        start=DENVER,
        end=MOAB,
        drive_hours=4.9,  # six minutes to spare
        miles=300,
        geometry=[(39.0, -108.0), (39.0, -109.0)],
    )
    near = Stop(
        name="Roadside Overlook",
        location=Place(name="o", lat=39.01, lon=-108.5),
        category="Scenic Lookout",
    )
    far = Stop(
        name="Canyon Trail",
        location=Place(name="c", lat=39.1, lon=-108.6),
        category="Hiking Trail",
    )
    [day] = plan_stops([long_day], [near, far], HIKER)
    assert names(day) == ["Roadside Overlook"]
    assert day.stops[0].detour_minutes <= 6
    [roomy] = plan_stops([long_day.model_copy(update={"drive_hours": 3})], [near, far], HIKER)
    assert set(names(roomy)) == {"Roadside Overlook", "Canyon Trail"}


def test_a_stop_is_used_on_one_day_only():
    leg = dict(start=DENVER, end=MOAB, drive_hours=2, miles=100)
    day1 = DayLeg(day=1, geometry=[(39.0, -108.0), (39.0, -108.5)], **leg)
    day2 = DayLeg(day=2, geometry=[(39.0, -108.5), (39.0, -109.0)], **leg)
    at_boundary = Stop(
        name="Boundary Arch",
        location=Place(name="b", lat=39.02, lon=-108.5),
        category="National Park",
    )
    planned = plan_stops([day1, day2], [at_boundary], HIKER)
    assert [names(d) for d in planned] == [["Boundary Arch"], []]


def test_big_rigs_are_warned_about_downtown_parking(tmp_path, days):
    big = find_pitstops(
        days, MUSEUM_GOER, client(tmp_path, Sources()), "k", rv_length_ft=MINNIE_WINNIE_FT
    )
    small = find_pitstops(
        days, MUSEUM_GOER, client(tmp_path, Sources()), "k", rv_length_ft=REVEL_FT
    )
    assert all(s.rv_parking_note == CROWDED_NOTE for s in big[0].stops)
    assert not any(s.rv_parking_note for s in big[1].stops)  # Grand Junction, Moab: room to park
    assert not any(s.rv_parking_note for d in small for s in d.stops)


def test_cli_prints_stops_per_day(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FOURSQUARE_API_KEY", "f")
    monkeypatch.setenv("DAVE_CACHE_DIR", str(tmp_path / "cache"))
    original = CachedClient.__init__

    def mocked(self, cache_dir, **kwargs):
        original(self, cache_dir, transport=httpx.MockTransport(Sources()), sleep=lambda s: None)

    monkeypatch.setattr(CachedClient, "__init__", mocked)
    argv = ["pitstops", "39.7392,-104.9903", "38.5733,-109.5498"]
    assert cli.main([*argv, "--interests", "nature=0.1,museums=0.9", "--rv-length", "31"]) == 0
    out = capsys.readouterr().out
    assert "Day 1: 2.9 h driving" in out and "Day 2: 2.9 h driving" in out
    assert "Denver Art Museum (Art Museum), +1 min detour" in out
    assert CROWDED_NOTE in out
