"""Pick 1 to 3 stops per driving day that match what this traveler loves.

Candidates come from Foursquare (landmarks, outdoors, arts and museums; food is T20's job)
along the whole route, then each day keeps the best-ranked ones within its own corridor
whose detours still fit under the daily driving limit. Detours are driving, so they count
against the limit; time spent at a stop does not.

Without ratings (a paid Foursquare field), generic neighborhood places such as a plain "Park"
or "Playground" would crowd out the real sights just by being close, so they are skipped.

Big rigs get a parking warning, not a veto, for stops in dense clusters of places
(usually a downtown), where street parking won't fit them.
"""

from dave import foursquare
from dave.corridor import DEFAULT_BUFFER_MILES, along_route, query_radius_miles, search_points
from dave.days import DEFAULT_MAX_HOURS
from dave.geo import Point, haversine_miles
from dave.http import CachedClient
from dave.interests import rank_stops
from dave.models import DayLeg, Interests, Place, Stop

STOP_CATEGORIES = (
    "4d4b7105d754a06377d81259",  # Landmarks and Outdoors
    "4d4b7104d754a06370d81259",  # Arts and Entertainment
)
FIELDS = "fsq_place_id,name,latitude,longitude,categories,location"
MAX_STOPS_PER_DAY = 3
MINOR_CATEGORIES = {
    "park", "playground", "plaza", "picnic area", "fountain", "field", "dog park", "skate park",
    "athletics and sports", "pool", "bridge",
}  # fmt: skip

BIG_RIG_FT = 25  # longer than a Class B or a small Class C
CROWD_RADIUS_MILES = 0.25
CROWD_SIZE = 6  # this many other places that close means a dense, downtown-like block
CROWDED_NOTE = "Dense area; street parking unlikely to fit this RV. Park outside and walk in."


def foursquare_stop(place: dict) -> Stop:
    location = place.get("location") or {}
    return Stop(
        name=place["name"],
        location=Place(
            name=place["name"],
            lat=place["latitude"],
            lon=place["longitude"],
            address=location.get("formatted_address"),
        ),
        category=", ".join(c["name"] for c in place.get("categories") or []),
    )


def candidate_stops(
    line: list[Point],
    http: CachedClient,
    api_key: str,
    *,
    buffer_miles: float = DEFAULT_BUFFER_MILES,
) -> list[Stop]:
    """Every landmark, outdoor and arts place near the route worth a detour, each once."""
    places: dict[str, dict] = {}
    radius = query_radius_miles(buffer_miles)
    for center in search_points(line, buffer_miles):
        for place in foursquare.search(
            center, radius, http, api_key, categories=STOP_CATEGORIES, fields=FIELDS
        ):
            places.setdefault(place["fsq_place_id"], place)
    return [foursquare_stop(p) for p in places.values() if not _minor(p)]


def plan_stops(
    days: list[DayLeg],
    candidates: list[Stop],
    interests: Interests,
    *,
    rv_length_ft: float | None = None,
    max_hours: float = DEFAULT_MAX_HOURS,
    buffer_miles: float = DEFAULT_BUFFER_MILES,
) -> list[DayLeg]:
    """The days with their `stops` filled in trip order. A stop is used on one day only."""
    big_rig = rv_length_ft is not None and rv_length_ft > BIG_RIG_FT
    used: set[tuple[str, float, float]] = set()
    planned = []
    for day in days:
        hits = along_route(candidates, day.geometry, _where, buffer_miles=buffer_miles)
        along = {}
        on_route = []
        for h in hits:
            if _key(h.item) in used:
                continue
            stop = h.item.model_copy(update={"detour_minutes": round(h.detour_minutes, 1)})
            along[_key(stop)] = h.along_miles
            on_route.append(stop)

        spare_minutes = (max_hours - day.drive_hours) * 60
        picked = []
        for stop in rank_stops(on_route, interests):
            if len(picked) == MAX_STOPS_PER_DAY:
                break
            if stop.detour_minutes > spare_minutes:
                continue
            spare_minutes -= stop.detour_minutes
            if big_rig and _crowded(stop, candidates):
                stop = stop.model_copy(update={"rv_parking_note": CROWDED_NOTE})
            picked.append(stop)
        used |= {_key(s) for s in picked}
        picked.sort(key=lambda s: along[_key(s)])
        planned.append(day.model_copy(update={"stops": picked}))
    return planned


def find_pitstops(
    days: list[DayLeg],
    interests: Interests,
    http: CachedClient,
    api_key: str,
    *,
    rv_length_ft: float | None = None,
    max_hours: float = DEFAULT_MAX_HOURS,
) -> list[DayLeg]:
    line = [p for day in days for p in day.geometry]
    candidates = candidate_stops(line, http, api_key)
    return plan_stops(days, candidates, interests, rv_length_ft=rv_length_ft, max_hours=max_hours)


def _minor(place: dict) -> bool:
    names = {c["name"].lower() for c in place.get("categories") or []}
    return not names or names <= MINOR_CATEGORIES


def _where(stop: Stop) -> Point:
    return stop.location.lat, stop.location.lon


def _key(stop: Stop) -> tuple[str, float, float]:
    return stop.name, stop.location.lat, stop.location.lon


def _crowded(stop: Stop, places: list[Stop]) -> bool:
    near = sum(
        1
        for p in places
        if _key(p) != _key(stop) and haversine_miles(_where(stop), _where(p)) <= CROWD_RADIUS_MILES
    )
    return near >= CROWD_SIZE
