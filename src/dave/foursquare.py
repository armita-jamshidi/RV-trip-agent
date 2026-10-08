"""Foursquare OS Places search, shared by campgrounds, stops and (later) restaurants.

Only free ("Pro") fields are requested. Rating, popularity, hours and photos are paid
("Premium") fields and need their own decision in context/decisions.md.
"""

from dave.geo import Point
from dave.http import CachedClient, SourceError

URL = "https://places-api.foursquare.com/places/search"
VERSION = "2025-06-17"
MAX_RADIUS_M = 100_000
MAX_RESULTS = 50
METERS_PER_MILE = 1609.344


def search(
    center: Point,
    radius_miles: float,
    http: CachedClient,
    api_key: str,
    *,
    categories: tuple[str, ...],
    fields: str,
) -> list[dict]:
    """Raw place records in these categories around `center`."""
    response = http.get(
        URL,
        params={
            "ll": f"{center[0]},{center[1]}",
            "radius": min(MAX_RADIUS_M, round(radius_miles * METERS_PER_MILE)),
            "fsq_category_ids": ",".join(categories),
            "fields": fields,
            "limit": MAX_RESULTS,
        },
        headers={"Authorization": f"Bearer {api_key}", "X-Places-Api-Version": VERSION},
    )
    if not response.is_success:
        raise SourceError(f"Foursquare returned {response.status_code}")
    return response.json().get("results", [])
