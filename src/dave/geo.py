"""Small geometry helpers on (lat, lon) points."""

import math
from itertools import pairwise

EARTH_RADIUS_MILES = 3958.8

Point = tuple[float, float]


def haversine_miles(a: Point, b: Point) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def cumulative_miles(line: list[Point]) -> list[float]:
    """Distance from the start of the line to each of its points."""
    out = [0.0]
    for a, b in pairwise(line):
        out.append(out[-1] + haversine_miles(a, b))
    return out


def interpolate(a: Point, b: Point, t: float) -> Point:
    """The point a fraction `t` of the way from a to b (straight line; fine over short segments)."""
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
