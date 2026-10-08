"""Split a route into driving days of at most `max_hours` behind the wheel.

Days are balanced: a 5.9 h drive becomes two days of about 3 h, not 5 h plus a 54-minute stub.
Driving time is spread along the route in proportion to distance. Stop time is not driving
time and is planned separately, so it never counts against the daily limit.
"""

import math
from datetime import date, timedelta

from dave.geo import cumulative_miles, interpolate
from dave.models import DayLeg, Place, Route

DEFAULT_MAX_HOURS = 5.0


def driving_days_needed(route: Route, max_hours: float = DEFAULT_MAX_HOURS) -> int:
    return max(1, math.ceil(round(route.drive_hours / max_hours, 9)))


def split_days(
    route: Route,
    origin: Place,
    destination: Place,
    *,
    max_hours: float = DEFAULT_MAX_HOURS,
    start_date: date | None = None,
) -> list[DayLeg]:
    """Equal-length driving days, each ending at an overnight area on the route."""
    days = driving_days_needed(route, max_hours)
    line = route.geometry or [(origin.lat, origin.lon), (destination.lat, destination.lon)]
    cum = cumulative_miles(line)
    total = cum[-1]

    # Cut the line at 1/days, 2/days, ... of its length.
    pieces: list[list[tuple[float, float]]] = []
    current, i = [line[0]], 0
    for k in range(1, days):
        target = total * k / days
        while i + 1 < len(line) - 1 and cum[i + 1] <= target:
            i += 1
            current.append(line[i])
        span = cum[i + 1] - cum[i]
        cut = interpolate(line[i], line[i + 1], (target - cum[i]) / span if span else 0)
        pieces.append([*current, cut])
        current = [cut]
    pieces.append([*current, *line[i + 1 :]])

    stops = [origin]
    stops += [
        Place(name=f"Overnight area {n}", lat=p[-1][0], lon=p[-1][1])
        for n, p in enumerate(pieces[:-1], 1)
    ]
    stops.append(destination)
    return [
        DayLeg(
            day=n,
            travel_date=start_date + timedelta(days=n - 1) if start_date else None,
            start=stops[n - 1],
            end=stops[n],
            drive_hours=route.drive_hours / days,
            miles=route.miles / days,
            geometry=piece,
        )
        for n, piece in enumerate(pieces, 1)
    ]
