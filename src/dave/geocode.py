"""Place names ("Moab, UT") to coordinates, from OpenStreetMap's Nominatim (free, no key).

Nominatim asks for a descriptive User-Agent and at most one request a second. A plan looks up
two places, and the cached client keeps repeat lookups off the network entirely.
"""

from dave.http import CachedClient, SourceError
from dave.models import Place

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "dave-rv-trip-agent (https://github.com/armita-jamshidi/rv-trip-agent)"


class PlaceNotFound(ValueError):
    pass


def geocode(name: str, http: CachedClient) -> Place:
    """The best match for `name` in the US, keeping the traveler's wording as its name."""
    response = http.get(
        NOMINATIM_URL,
        params={"q": name, "countrycodes": "us", "format": "jsonv2", "limit": 1},
        headers={"User-Agent": USER_AGENT},
    )
    if not response.is_success:
        raise SourceError(f"Nominatim returned {response.status_code} for {name!r}")
    found = response.json()
    if not found:
        raise PlaceNotFound(f"Couldn't find {name!r} on the map; try a city and state.")
    return Place(
        name=name,
        lat=float(found[0]["lat"]),
        lon=float(found[0]["lon"]),
        address=found[0].get("display_name"),
    )
