"""Place names ("Moab, UT") to coordinates, from OpenStreetMap's Nominatim (free, no key).

A bare name takes the best-known of the top five matches, by Nominatim's importance score.
Nominatim asks for a descriptive User-Agent (the cached client sends one on every request) and
at most one request a second. A plan looks up two places, and the cache keeps repeat lookups
off the network entirely.
"""

from dave.http import CachedClient, SourceError
from dave.models import Place

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


class PlaceNotFound(ValueError):
    pass


def geocode(name: str, http: CachedClient) -> Place:
    """The best match for `name` in the US, keeping the traveler's wording as its name."""
    response = http.get(
        NOMINATIM_URL,
        params={"q": name, "countrycodes": "us", "format": "jsonv2", "limit": 5},
    )
    if not response.is_success:
        raise SourceError(f"Nominatim returned {response.status_code} for {name!r}")
    found = response.json()
    if not found:
        raise PlaceNotFound(f"Couldn't find {name!r} on the map; try a city and state.")
    # The best-known match: "Yellowstone" is the national park, not Yellowstone County.
    best = max(found, key=lambda f: float(f.get("importance") or 0))
    return Place(
        name=name,
        lat=float(best["lat"]),
        lon=float(best["lon"]),
        address=best.get("display_name"),
    )
