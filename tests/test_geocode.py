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
