"""Place names ("Moab, UT") to coordinates, from OpenStreetMap's Nominatim (free, no key).

Of the top five matches, the best-known (Nominatim's importance score) wins.
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
    """The best match for `name` in the US, keeping the traveler's wording as its name.

    A bare name that only matches as a county ("Yellowstone" is also Yellowstone County, MT)
    is tried as a national park first, since that is where RVers mean.
    """
    found = _search(name, http)
    if _only_a_county(name, found):
        found = _search(f"{name} National Park", http) or found
    if not found:
        raise PlaceNotFound(f"Couldn't find {name!r} on the map; try a city and state.")
    best = max(found, key=lambda f: float(f.get("importance") or 0))
    return Place(
        name=name,
        lat=float(best["lat"]),
        lon=float(best["lon"]),
        address=best.get("display_name"),
    )


def _search(query: str, http: CachedClient) -> list[dict]:
    response = http.get(
        NOMINATIM_URL,
        params={"q": query, "countrycodes": "us", "format": "jsonv2", "limit": 5},
    )
    if not response.is_success:
        raise SourceError(f"Nominatim returned {response.status_code} for {query!r}")
    return response.json()


def _only_a_county(name: str, found: list[dict]) -> bool:
    """The top match is a county the traveler didn't ask for by name."""
    if not found or "," in name or "county" in name.lower():
        return False
    top = max(found, key=lambda f: float(f.get("importance") or 0))
    return (top.get("display_name") or "").lower().startswith(f"{name.lower()} county")
