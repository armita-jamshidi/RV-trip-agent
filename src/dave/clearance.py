"""Bridge and tunnel clearances along a route, from OpenStreetMap, with rerouting around low ones.

OSM tags height limits as `maxheight` on the road that passes under the bridge or through the
tunnel. A way counts as on the route when at least two of its nodes lie on the route line; a
road that merely crosses the route touches it at one node and doesn't count. Limits are
compared with RV height plus the 6 inch margin from `context/domain.md`.
"""

import math
import re
from dataclasses import dataclass, field

from dave.corridor import locate
from dave.geo import Point
from dave.http import CachedClient, SourceError
from dave.models import Place, Route
from dave.routing import RoutingError, routes

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
MARGIN_FT = 0.5
ON_ROUTE_MILES = 0.015  # about 25 m: a way's node this close is on the route
CHUNK_POINTS = 100  # route points per Overpass query, keeping URLs short
DETOUR_MILES = 1.0  # how far off a low bridge to put a detour waypoint
METERS_TO_FEET = 3.28084


@dataclass(frozen=True)
class Restriction:
    name: str
    at: Point
    clearance_ft: float | None  # None for a tunnel with no height limit tagged
    propane_banned: bool = False


@dataclass
class ClearanceCheck:
    route: Route
    too_low: list[Restriction] = field(default_factory=list)
    propane_tunnels: list[Restriction] = field(default_factory=list)
    rerouted: bool = False

    def warnings(self) -> list[str]:
        """Plain messages for the itinerary: low clearances block a plan, propane only warns."""
        return [
            f"{r.name} has {r.clearance_ft:.1f} ft clearance, too low for this RV."
            for r in self.too_low
        ]

    def notes(self) -> list[str]:
        return [
            f"{r.name} restricts propane; check its rules or go around."
            for r in self.propane_tunnels
        ]


def parse_height(value: str) -> float | None:
    """OSM maxheight in feet: `3.7`, `3.7 m`, `12'4"`, `12 ft`. None for `none`/`default`."""
    v = value.strip().lower().replace("’", "'").replace("”", '"')
    if m := re.fullmatch(r"(\d+)\s*'\s*(?:(\d+(?:\.\d+)?)\s*\")?", v):
        return int(m.group(1)) + float(m.group(2) or 0) / 12
    if m := re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ft|feet)", v):
        return float(m.group(1))
    if m := re.fullmatch(r"(\d+(?:\.\d+)?)\s*(m)?", v):
        return float(m.group(1)) * METERS_TO_FEET
    return None


def _query(points: list[Point]) -> str:
    line = ",".join(f"{lat:.5f},{lon:.5f}" for lat, lon in points)
    around = f"(around:25,{line})"
    return (
        "[out:json][timeout:60];("
        f'way{around}["maxheight"];'
        f'way{around}["tunnel"]["hazmat"];'
        f'way{around}["tunnel"]["hazmat:adr_tunnel_cat"];'
        ");out tags geom;"
    )


def restrictions(line: list[Point], http: CachedClient) -> list[Restriction]:
    """Height limits and propane bans on ways that run along `line`."""
    found: dict[int, Restriction] = {}
    step = CHUNK_POINTS - 1  # chunks overlap by one point so no segment is skipped
    for start in range(0, max(1, len(line) - 1), step):
        chunk = line[start : start + CHUNK_POINTS]
        response = http.get(OVERPASS_URL, params={"data": _query(chunk)})
        if not response.is_success:
            raise SourceError(f"Overpass answered {response.status_code}")
        for way in response.json().get("elements", []):
            nodes = [(n["lat"], n["lon"]) for n in way.get("geometry", [])]
            on_route = [p for p in nodes if locate(p, line)[1] <= ON_ROUTE_MILES]
            if way["id"] in found or len(on_route) < 2:
                continue
            tags = way.get("tags", {})
            found[way["id"]] = Restriction(
                name=tags.get("name") or tags.get("ref") or f"OSM way {way['id']}",
                at=on_route[len(on_route) // 2],
                clearance_ft=parse_height(tags["maxheight"]) if "maxheight" in tags else None,
                propane_banned=tags.get("tunnel") not in {None, "no"}
                and (tags.get("hazmat") == "no" or "hazmat:adr_tunnel_cat" in tags),
            )
    return list(found.values())


def check(route: Route, rv_height_ft: float, http: CachedClient) -> ClearanceCheck:
    found = restrictions(route.geometry, http)
    need = rv_height_ft + MARGIN_FT
    return ClearanceCheck(
        route=route,
        too_low=[r for r in found if r.clearance_ft is not None and r.clearance_ft < need],
        propane_tunnels=[r for r in found if r.propane_banned],
    )


def clear_route(
    start: Place, end: Place, rv_height_ft: float, http: CachedClient, **routing
) -> ClearanceCheck:
    """The fastest route from start to end that the RV fits under.

    Tries the normal route, then OSRM's alternatives, then detours through a waypoint a mile
    to each side of the first low bridge. When nothing fits, returns the normal route with its
    low clearances listed, so the validator refuses the plan instead of hiding the problem.
    """
    candidates = routes([start, end], http, alternatives=True, **routing)
    first = check(candidates[0], rv_height_ft, http)
    if not first.too_low:
        return first

    checked = [first] + [check(r, rv_height_ft, http) for r in candidates[1:]]
    if all(c.too_low for c in checked):
        low = first.too_low[0].at
        for via in _around(low):
            waypoint = Place(name="Detour", lat=via[0], lon=via[1])
            try:
                detour = routes([start, waypoint, end], http, **routing)[0]
            except RoutingError:
                continue
            checked.append(check(detour, rv_height_ft, http))

    fits = [c for c in checked if not c.too_low]
    if not fits:
        return first
    best = min(fits, key=lambda c: c.route.drive_hours)
    best.rerouted = True
    return best


def _around(p: Point) -> list[Point]:
    """Points DETOUR_MILES north, east, south and west of p."""
    dlat = DETOUR_MILES / 69.0
    dlon = dlat / max(0.1, math.cos(math.radians(p[0])))
    return [(p[0] + dlat, p[1]), (p[0], p[1] + dlon), (p[0] - dlat, p[1]), (p[0], p[1] - dlon)]
