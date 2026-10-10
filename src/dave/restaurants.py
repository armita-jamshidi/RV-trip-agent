"""A lunch and a dinner suggestion for each driving day.

Lunch is searched around the halfway point of the day's drive, dinner around that night's
campground (or the day's end when no campground is picked yet). Candidates are ranked on
quality, the detour they cost, a cuisine the trip hasn't had yet, and price.

Rating and price are paid ("Premium") Foursquare fields, so only free fields are requested
for now: an unrated place gets a neutral quality prior and says "not rated". When a rating
is present, places below `MIN_RATING` are dropped.

Big rigs get the same dense-area parking warning as stops.
"""

from dave import foursquare
from dave.corridor import detour_minutes, locate
from dave.geo import Point, cumulative_miles, haversine_miles, interpolate
from dave.http import CachedClient
from dave.models import DayLeg, Place, Restaurant
from dave.pitstops import BIG_RIG_FT, CROWD_RADIUS_MILES, CROWD_SIZE, CROWDED_NOTE

FOOD = ("4d4b7105d754a06374d81259",)  # Foursquare "Food"
FIELDS = "fsq_place_id,name,latitude,longitude,categories,location"
SEARCH_MILES = 15.0
MIN_RATING = 7.5  # out of 10
UNRATED_PRIOR = 0.6
LONG_DETOUR_MINUTES = 30.0  # this much extra driving for a meal scores zero
WEIGHTS = {"quality": 0.45, "detour": 0.25, "variety": 0.2, "price": 0.1}
NOT_A_MEAL = {
    "coffee shop", "café", "cafe", "bakery", "dessert shop", "ice cream parlor", "donut shop",
    "juice bar", "tea room", "bar", "cocktail bar", "liquor store", "candy store",
}  # fmt: skip


def foursquare_restaurant(place: dict) -> Restaurant:
    categories = [c["name"] for c in place.get("categories") or []]
    return Restaurant(
        name=place["name"],
        location=Place(
            name=place["name"],
            lat=place["latitude"],
            lon=place["longitude"],
            address=(place.get("location") or {}).get("formatted_address"),
        ),
        cuisine=categories[0] if categories else None,
        rating=place.get("rating"),
        price_level=place.get("price"),
    )


def candidate_restaurants(
    center: Point, http: CachedClient, api_key: str, radius_miles: float = SEARCH_MILES
) -> list[Restaurant]:
    """Sit-down meal places within `radius_miles` of `center`."""
    places = foursquare.search(center, radius_miles, http, api_key, categories=FOOD, fields=FIELDS)
    found = [foursquare_restaurant(p) for p in places]
    return [
        r
        for r in found
        if r.cuisine
        and r.cuisine.lower() not in NOT_A_MEAL
        and haversine_miles(center, _where(r)) <= radius_miles
    ]


def lunch_point(day: DayLeg) -> Point:
    """Halfway along the day's drive."""
    line = day.geometry or [(day.start.lat, day.start.lon), (day.end.lat, day.end.lon)]
    cum = cumulative_miles(line)
    half = cum[-1] / 2
    for i in range(len(line) - 1):
        if cum[i + 1] >= half:
            span = cum[i + 1] - cum[i]
            return interpolate(line[i], line[i + 1], (half - cum[i]) / span if span else 0)
    return line[-1]


def dinner_point(day: DayLeg) -> Point:
    place = day.campground.location if day.campground else day.end
    return place.lat, place.lon


def pick_meal(
    meal: str,
    candidates: list[Restaurant],
    detours: dict[str, float],
    had: set[str],
    *,
    big_rig: bool = False,
) -> Restaurant | None:
    """The best candidate, or None. `detours` maps names to extra minutes of driving and
    `had` holds cuisines (and names) already used on the trip."""
    best, best_score = None, -1.0
    for r in candidates:
        if r.name in had or (r.rating is not None and r.rating < MIN_RATING):
            continue
        minutes = detours[r.name]
        parts = {
            "quality": r.rating / 10 if r.rating is not None else UNRATED_PRIOR,
            "detour": max(0.0, 1 - minutes / LONG_DETOUR_MINUTES),
            "variety": 0.0 if r.cuisine in had else 1.0,
            "price": (4 - r.price_level) / 3 if r.price_level else 0.5,
        }
        score = sum(WEIGHTS[k] * v for k, v in parts.items())
        if score > best_score:
            best, best_score = r, score
    if best is None:
        return None
    note = CROWDED_NOTE if big_rig and _crowded(best, candidates) else None
    return best.model_copy(
        update={
            "meal": meal,
            "detour_minutes": round(detours[best.name], 1),
            "rv_parking_note": note,
        }
    )


def plan_meals(
    days: list[DayLeg],
    http: CachedClient,
    api_key: str,
    *,
    rv_length_ft: float | None = None,
) -> list[DayLeg]:
    """The days with `restaurants` set to [lunch, dinner] (either may be missing)."""
    big_rig = rv_length_ft is not None and rv_length_ft > BIG_RIG_FT
    had: set[str] = set()
    planned = []
    for day in days:
        meals = []
        lunch_at = lunch_point(day)
        lunch = candidate_restaurants(lunch_at, http, api_key)
        line = day.geometry or [lunch_at]
        off = {r.name: detour_minutes(locate(_where(r), line)[1]) for r in lunch}
        if pick := pick_meal("lunch", lunch, off, had, big_rig=big_rig):
            meals.append(pick)
            had |= {pick.name, pick.cuisine}

        dinner_at = dinner_point(day)
        dinner = candidate_restaurants(dinner_at, http, api_key)
        off = {r.name: detour_minutes(haversine_miles(dinner_at, _where(r))) for r in dinner}
        if pick := pick_meal("dinner", dinner, off, had, big_rig=big_rig):
            meals.append(pick)
            had |= {pick.name, pick.cuisine}
        planned.append(day.model_copy(update={"restaurants": meals}))
    return planned


def _where(r: Restaurant) -> Point:
    return r.location.lat, r.location.lon


def _crowded(r: Restaurant, places: list[Restaurant]) -> bool:
    near = sum(
        1
        for p in places
        if p.name != r.name and haversine_miles(_where(r), _where(p)) <= CROWD_RADIUS_MILES
    )
    return near >= CROWD_SIZE
