"""Find places "along the way": one corridor helper shared by stops, food, gas and campgrounds.

A corridor is the band within `buffer_miles` of the route. `search_points` gives the centers
to query a places API from, spaced so their circles cover the band. `along_route` then keeps
the candidates inside the band, sorted by how far along the trip they are, with the detour
each one costs.

Detours are estimated, not routed: straight-line distance off the route times a road
circuity factor, there and back, at a slow local-road RV speed. That is cheap enough to run
on every candidate; the planner can route the few it picks.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise

from dave.geo import EARTH_RADIUS_MILES, Point, cumulative_miles, interpolate

DEFAULT_BUFFER_MILES = 15.0
ROAD_CIRCUITY = 1.3  # roads run about 30% longer than the straight line
DETOUR_MPH = 35.0  # an RV on local roads, towns and parking included


@dataclass(frozen=True)
class CorridorHit[T]:
    item: T
    along_miles: float  # how far into the trip the closest point of the route is
    off_route_miles: float  # straight-line distance from the route
    detour_minutes: float  # estimated extra driving to visit and come back


def search_points(line: list[Point], buffer_miles: float = DEFAULT_BUFFER_MILES) -> list[Point]:
    """Query centers along the line, one per `buffer_miles`, ends included.

    A circle of radius `buffer_miles * sqrt(2)` around each center covers the whole band
    between it and the next center, so that is the radius to query with.
    """
    if len(line) < 2:
        return list(line)
    cum = cumulative_miles(line)
    total = cum[-1]
    count = max(1, math.ceil(total / buffer_miles))
    points, i = [], 0
    for k in range(count + 1):
        target = total * k / count
        while i + 1 < len(line) - 1 and cum[i + 1] < target:
            i += 1
        span = cum[i + 1] - cum[i]
        points.append(interpolate(line[i], line[i + 1], (target - cum[i]) / span if span else 0))
    return points


def query_radius_miles(buffer_miles: float = DEFAULT_BUFFER_MILES) -> float:
    return buffer_miles * math.sqrt(2)


def locate(point: Point, line: list[Point]) -> tuple[float, float]:
    """(miles along the line to the nearest point, miles off the line)."""
    if len(line) == 1:
        return 0.0, _flat_miles(point, line[0], point[0])
    cum = cumulative_miles(line)
    best_off, best_along = math.inf, 0.0
    for i, (a, b) in enumerate(pairwise(line)):
        t, off = _project(point, a, b)
        if off < best_off:
            best_off, best_along = off, cum[i] + t * (cum[i + 1] - cum[i])
    return best_along, best_off


def detour_minutes(off_route_miles: float, mph: float = DETOUR_MPH) -> float:
    return 2 * off_route_miles * ROAD_CIRCUITY / mph * 60


def along_route[T](
    items: list[T],
    line: list[Point],
    where: Callable[[T], Point],
    *,
    buffer_miles: float = DEFAULT_BUFFER_MILES,
) -> list[CorridorHit[T]]:
    """The items within `buffer_miles` of the line, in trip order."""
    hits = []
    for item in items:
        along, off = locate(where(item), line)
        if off <= buffer_miles:
            hits.append(CorridorHit(item, along, off, detour_minutes(off)))
    return sorted(hits, key=lambda h: h.along_miles)


def _flat_miles(a: Point, b: Point, ref_lat: float) -> float:
    """Distance on a local flat projection; accurate to well under 1% over corridor widths."""
    dy = math.radians(b[0] - a[0]) * EARTH_RADIUS_MILES
    dx = math.radians(b[1] - a[1]) * EARTH_RADIUS_MILES * math.cos(math.radians(ref_lat))
    return math.hypot(dx, dy)


def _project(p: Point, a: Point, b: Point) -> tuple[float, float]:
    """Fraction along segment a-b of the point nearest p, and p's distance from it in miles."""
    k = math.cos(math.radians(p[0]))
    ax, ay, bx, by, px, py = a[1] * k, a[0], b[1] * k, b[0], p[1] * k, p[0]
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else min(1.0, max(0.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    nearest = interpolate(a, b, t)
    return t, _flat_miles(p, nearest, p[0])
