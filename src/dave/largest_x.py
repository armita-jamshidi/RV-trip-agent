"""Quirky "largest X" roadside attractions: the world's largest caterpillar, the tallest Athena.

Two sources, both turned into ordinary `Stop`s for the pitstop ranking (T18):
- a curated seed list (`largest_x.json`), each entry with its claim and where it was checked;
- a Foursquare name search for "largest" and "biggest" along the route, keeping only places
  whose name actually makes the claim (the search is fuzzy).

Every stop gets the "Roadside Attraction" category, which the interest scoring maps to the
traveler's `largest_x` interest.
"""

import json
import re
from pathlib import Path

from dave import foursquare
from dave.corridor import DEFAULT_BUFFER_MILES, query_radius_miles, search_points
from dave.geo import Point, haversine_miles
from dave.http import CachedClient
from dave.models import Place, Stop

SEEDS = Path(__file__).with_name("largest_x.json")
CATEGORY = "Roadside Attraction"
QUERIES = ("largest", "biggest")
FIELDS = "fsq_place_id,name,latitude,longitude,location"
# Not "world's" alone: World's Fair Park makes no claim.
CLAIM = re.compile(r"\b(?:largest|biggest|tallest)\b", re.IGNORECASE)
SAME_SPOT_MILES = 0.2


def seed_stops() -> list[Stop]:
    return [
        Stop(
            name=s["name"],
            location=Place(name=s["name"], lat=s["lat"], lon=s["lon"], address=s["address"]),
            category=CATEGORY,
            description=s["claim"],
        )
        for s in json.loads(SEEDS.read_text())
    ]


def searched_stops(
    line: list[Point],
    http: CachedClient,
    api_key: str,
    *,
    buffer_miles: float = DEFAULT_BUFFER_MILES,
) -> list[Stop]:
    """Places along the route whose names claim to be the largest or biggest of something."""
    places: dict[str, dict] = {}
    radius = query_radius_miles(buffer_miles)
    for center in search_points(line, buffer_miles):
        for query in QUERIES:
            for place in foursquare.search(
                center, radius, http, api_key, fields=FIELDS, query=query
            ):
                if CLAIM.search(place["name"]):
                    places.setdefault(place["fsq_place_id"], place)
    return [
        Stop(
            name=p["name"],
            location=Place(
                name=p["name"],
                lat=p["latitude"],
                lon=p["longitude"],
                address=(p.get("location") or {}).get("formatted_address"),
            ),
            category=CATEGORY,
        )
        for p in places.values()
    ]


def largest_x_stops(line: list[Point], http: CachedClient, api_key: str) -> list[Stop]:
    """Seeds first; a searched place at the same spot as a seed is the same attraction."""
    return merge(seed_stops(), searched_stops(line, http, api_key))


def merge(preferred: list[Stop], others: list[Stop]) -> list[Stop]:
    """`preferred` plus the `others` that aren't at the same spot as one already kept."""
    kept = list(preferred)
    for stop in others:
        if not any(_same_spot(stop, k) for k in kept):
            kept.append(stop)
    return kept


def _same_spot(a: Stop, b: Stop) -> bool:
    return (
        haversine_miles((a.location.lat, a.location.lon), (b.location.lat, b.location.lon))
        <= SAME_SPOT_MILES
    )
