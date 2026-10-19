"""Gas stations along the route with their posted prices, from Google Places API (New) (T37).

A paid source (decision 2026-10-16-t37): Nearby Search with `fuelOptions` is billed per call
beyond Google's monthly free allowance, so a plan makes at most MAX_SEARCHES calls. Google's
terms don't allow storing prices, so these calls skip the on-disk cache; tests use recorded
fixtures served by a mock transport.

Not every station reports prices, and a price older than MAX_PRICE_AGE_DAYS is ignored. Station
prices also give each state on the route an average (`area_prices`), which prices the driving
where no station was found and wherever EIA has no snapshot.
"""

from datetime import date, datetime

from dave.corridor import query_radius_miles, search_points
from dave.fillups import BUFFER_MILES, big_rig
from dave.fuel_cost import nearest_state
from dave.geo import Point, cumulative_miles
from dave.http import CachedClient, SourceError
from dave.models import FuelType, GasPrice, GasStation, Place

URL = "https://places.googleapis.com/v1/places:searchNearby"
FIELDS = (
    ",".join(f"places.{f}" for f in ("id", "displayName", "formattedAddress", "location", "types"))
    + ",places.fuelOptions"
)
MAX_SEARCHES = 40  # per plan; at most a few dollars even with no free allowance left
MAX_RADIUS_M = 50_000  # Google's limit for a search circle
MAX_RESULTS = 20
MAX_PRICE_AGE_DAYS = 14
FUEL = {FuelType.GAS: "REGULAR_UNLEADED", FuelType.DIESEL: "DIESEL"}
METERS_PER_MILE = 1609.344


def search(center: Point, radius_miles: float, http: CachedClient, api_key: str) -> list[dict]:
    """Raw place records for gas stations around `center`, nearest first."""
    body = {
        "includedTypes": ["gas_station"],
        "maxResultCount": MAX_RESULTS,
        "rankPreference": "DISTANCE",
        "locationRestriction": {
            "circle": {
                "center": {"latitude": center[0], "longitude": center[1]},
                "radius": min(MAX_RADIUS_M, round(radius_miles * METERS_PER_MILE)),
            }
        },
    }
    response = http.post(
        URL,
        json_body=body,
        headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELDS},
        cache=False,
    )
    if not response.is_success:
        raise SourceError(f"Google Places answered {response.status_code}")
    return response.json().get("places", [])


def google_station(place: dict, fuel_type: FuelType, *, today: date) -> GasStation:
    name = place["displayName"]["text"]
    types = " ".join(place.get("types") or []).replace("_", " ")
    return GasStation(
        name=name,
        location=Place(
            name=name,
            lat=place["location"]["latitude"],
            lon=place["location"]["longitude"],
            address=place.get("formattedAddress"),
        ),
        fuel_type=fuel_type,
        price_per_gal=_price(place, fuel_type, today),
        rv_accessible=True if big_rig(name, types) else None,
    )


def stations_along(
    line: list[Point], http: CachedClient, api_key: str, fuel_type: FuelType, *, today: date
) -> list[GasStation]:
    """Stations near the whole route, searched every few miles (spaced out on long trips so
    a plan never makes more than MAX_SEARCHES calls)."""
    spacing = max(BUFFER_MILES * 5, cumulative_miles(line)[-1] / (MAX_SEARCHES - 1))
    places: dict[str, dict] = {}
    for center in search_points(line, spacing)[:MAX_SEARCHES]:
        for p in search(center, query_radius_miles(spacing), http, api_key):
            places.setdefault(p["id"], p)
    return [google_station(p, fuel_type, today=today) for p in places.values()]


def area_prices(stations: list[GasStation], *, today: date) -> list[GasPrice]:
    """Each state's average of the station prices found in it, and the route's average as the
    fallback for states with none. Dated today, so they win over older EIA weeks."""
    priced = [s for s in stations if s.price_per_gal]
    if not priced:
        return []
    by_state: dict[str, list[float]] = {}
    for s in priced:
        by_state.setdefault(nearest_state((s.location.lat, s.location.lon)), []).append(
            s.price_per_gal
        )
    fuel_type = priced[0].fuel_type
    rows = [(f"S{state}", f"{state} stations", p) for state, p in sorted(by_state.items())]
    rows.append(("NUS", "stations on the route", [s.price_per_gal for s in priced]))
    return [
        GasPrice(
            period=today,
            area=area,
            area_name=f"{name} (Google)",
            fuel_type=fuel_type,
            usd_per_gal=round(sum(p) / len(p), 3),
        )
        for area, name, p in rows
    ]


def with_station_prices(eia: list[GasPrice], stations: list[GasPrice]) -> list[GasPrice]:
    """EIA weeks, except where stations priced the same area: station prices are newer."""
    covered = {(p.area, p.fuel_type) for p in stations}
    return [p for p in eia if (p.area, p.fuel_type) not in covered] + stations


def _price(place: dict, fuel_type: FuelType, today: date) -> float | None:
    for fp in (place.get("fuelOptions") or {}).get("fuelPrices", []):
        if fp.get("type") != FUEL[fuel_type] or "price" not in fp:
            continue
        updated = datetime.fromisoformat(fp["updateTime"].replace("Z", "+00:00")).date()
        if (today - updated).days > MAX_PRICE_AGE_DAYS:
            return None
        price = fp["price"]
        if price.get("currencyCode", "USD") != "USD":
            return None
        value = int(price.get("units", 0)) + price.get("nanos", 0) / 1e9
        return round(value, 3) if value > 0 else None
    return None
