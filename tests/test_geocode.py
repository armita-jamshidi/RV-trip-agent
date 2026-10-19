import httpx
import pytest

from dave.geocode import PlaceNotFound, geocode
from dave.http import USER_AGENT, CachedClient


def client(tmp_path, body, seen=None):
    def serve(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=body)

    return CachedClient(tmp_path, transport=httpx.MockTransport(serve))


def test_place_keeps_the_travelers_name_and_asks_politely(tmp_path):
    seen = []
    found = [{"lat": "38.5733", "lon": "-109.5498", "display_name": "Moab, Grand County, Utah"}]
    place = geocode("Moab, UT", client(tmp_path, found, seen))
    assert (place.name, place.lat, place.lon) == ("Moab, UT", 38.5733, -109.5498)
    assert seen[0].headers["User-Agent"] == USER_AGENT
    assert seen[0].url.params["countrycodes"] == "us"


def test_unknown_place_says_what_to_give(tmp_path):
    with pytest.raises(PlaceNotFound, match="try a city and state"):
        geocode("Nowhereville", client(tmp_path, []))


def test_a_bare_name_is_the_best_known_place_not_the_first_match(tmp_path):
    found = [
        {"lat": "45.96", "lon": "-108.28", "display_name": "Yellowstone County", "importance": 0.5},
        {"lat": "44.60", "lon": "-110.55", "display_name": "Yellowstone National Park",
         "importance": 0.8},
    ]  # fmt: skip
    place = geocode("Yellowstone", client(tmp_path, found))
    assert (place.lat, place.lon) == (44.60, -110.55)


def test_a_bare_name_that_is_only_a_county_is_tried_as_a_national_park(tmp_path):
    county = [
        {
            "lat": "45.96",
            "lon": "-108.28",
            "importance": 0.6,
            "display_name": "Yellowstone County, Montana, United States",
        }
    ]
    park = [{"lat": "44.60", "lon": "-110.55", "importance": 0.7,
             "display_name": "Yellowstone National Park, Wyoming, United States"}]  # fmt: skip
    seen = []

    def serve(request):
        seen.append(request.url.params["q"])
        return httpx.Response(200, json=park if "National Park" in seen[-1] else county)

    http = CachedClient(tmp_path, transport=httpx.MockTransport(serve))
    place = geocode("Yellowstone", http)
    assert (place.name, place.lat, place.lon) == ("Yellowstone", 44.60, -110.55)
    assert seen == ["Yellowstone", "Yellowstone National Park"]
    # Asked for by county, or with a state, it stays as found.
    assert geocode("Yellowstone County", client(tmp_path / "c", county)).lat == 45.96
