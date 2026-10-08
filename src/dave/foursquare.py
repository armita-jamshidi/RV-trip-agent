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
    fields: str,
    categories: tuple[str, ...] = (),
    query: str | None = None,
) -> list[dict]:
    """Raw place records around `center`, by category, by name or description words, or both."""
    params = {
        "ll": f"{center[0]},{center[1]}",
        "radius": min(MAX_RADIUS_M, round(radius_miles * METERS_PER_MILE)),
        "fields": fields,
        "limit": MAX_RESULTS,
    }
    if categories:
        params["fsq_category_ids"] = ",".join(categories)
    if query:
        params["query"] = query
    response = http.get(
        URL,
        params=params,
        headers={"Authorization": f"Bearer {api_key}", "X-Places-Api-Version": VERSION},
    )
    if not response.is_success:
        raise SourceError(f"Foursquare returned {response.status_code}")
    return response.json().get("results", [])
