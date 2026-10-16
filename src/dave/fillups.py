"""Where to fill up so the RV never runs low and buys its fuel where it is cheapest.

There are no station prices (no free source allows collecting them, decision 2026-10-09), so a
station's price is the EIA average for its area (T22). Savings come from buying in the cheaper
state or region before crossing into a dearer one. Among stations in the same area, chains that
usually sell below the local average (warehouse clubs, supermarket stations) are preferred,
without claiming a price for them.

Big rigs only use stations that can take them: truck stops and travel centers, by category or
by chain. The plan keeps a quarter tank in reserve and starts with a fill-up near the origin.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from dave import foursquare
from dave.corridor import along_route, query_radius_miles, search_points
from dave.fuel_cost import estimate_fuel, mpg, nearest_state
from dave.gas_prices import price_for
from dave.geo import Point, cumulative_miles
from dave.http import CachedClient
from dave.models import DayLeg, FuelType, GasPrice, GasStation, Place, RVClass, RVProfile
from dave.pitstops import BIG_RIG_FT

GAS_STATION = ("4bf58dd8d48988d113951735",)  # Foursquare "Gas Station"
FIELDS = "fsq_place_id,name,latitude,longitude,categories,location"
BUFFER_MILES = 3.0  # stations this close to the route; a fill-up shouldn't be a side trip
RESERVE = 0.25  # never plan to drop below a quarter tank
FIRST_FILL_MILES = 15.0  # the opening fill-up happens this close to the start
# Tank sizes when the spec page doesn't give one (towables: the tow vehicle's tank).
CLASS_TANK_GAL = {
    RVClass.A: 80,
    RVClass.B: 25,
    RVClass.C: 55,
    RVClass.TRAVEL_TRAILER: 30,
    RVClass.FIFTH_WHEEL: 30,
}
BIG_RIG_CHAINS = ("love's", "pilot", "flying j", "petro", "ta", "travelcenters", "buc-ee's")
BIG_RIG_CATEGORIES = ("truck stop", "travel center", "rest area")
USUALLY_CHEAPER = ("costco", "sam's club", "bj's", "murphy usa", "kroger", "safeway")


@dataclass(frozen=True)
class FillUp:
    station: GasStation
    day: int
    trip_miles: float  # how far into the trip
    gallons: float
    usd: float


@dataclass(frozen=True)
class FillUpPlan:
    stops: list[FillUp]
    tank_gal: float
    tank_source: str  # "RV specs" or "class estimate"
    baseline_usd: float  # the same fuel bought at each area's average as you drive through it
    warnings: list[str] = field(default_factory=list)

    @property
    def total_usd(self) -> float:
        return round(sum(s.usd for s in self.stops), 2)

    @property
    def saving_usd(self) -> float:
        return round(self.baseline_usd - self.total_usd, 2)

    def summary(self) -> list[str]:
        lines = [
            f"Day {s.day}: fill {s.gallons:.0f} gal at {s.station.name} (mile {s.trip_miles:.0f}),"
            f" about ${s.station.avg_price_60d:.2f}/gal area average: ${s.usd:,.2f}"
            for s in self.stops
        ]
        if self.saving_usd >= 1:
            lines.append(
                f"Estimated saving vs. buying as you go: ${self.saving_usd:,.2f} "
                f"(${self.total_usd:,.2f} instead of ${self.baseline_usd:,.2f})."
            )
        else:
            lines.append(
                f"No real saving on this route: average prices are about the same all along "
                f"(${self.total_usd:,.2f} either way)."
            )
        return lines + self.warnings


def foursquare_station(place: dict, fuel_type: FuelType) -> GasStation:
    categories = " ".join(c["name"] for c in place.get("categories") or []).lower()
    name = place["name"].lower()
    big_rig = any(c in categories for c in BIG_RIG_CATEGORIES) or any(
        re.search(rf"(?<![\w']){re.escape(c)}(?![\w'])", name) for c in BIG_RIG_CHAINS
    )
    return GasStation(
        name=place["name"],
        location=Place(
            name=place["name"],
            lat=place["latitude"],
            lon=place["longitude"],
            address=(place.get("location") or {}).get("formatted_address"),
        ),
        fuel_type=fuel_type,
        rv_accessible=True if big_rig else None,
    )


def stations_along(
    line: list[Point], http: CachedClient, api_key: str, fuel_type: FuelType
) -> list[GasStation]:
    places: dict[str, dict] = {}
    for center in search_points(line, BUFFER_MILES * 5):
        for p in foursquare.search(
            center,
            query_radius_miles(BUFFER_MILES * 5),
            http,
            api_key,
            categories=GAS_STATION,
            fields=FIELDS,
        ):
            places.setdefault(p["fsq_place_id"], p)
    return [foursquare_station(p, fuel_type) for p in places.values()]


def plan_fillups(
    days: list[DayLeg],
    rv: RVProfile,
    stations: list[GasStation],
    prices: list[GasPrice],
    *,
    today: date,
) -> FillUpPlan:
    """Cheapest-ahead fill-ups: at each stop buy just enough to reach a cheaper station in
    range, else fill the tank (or buy just enough to finish the trip)."""
    miles_per_gal, _ = mpg(rv)
    tank, tank_source = (
        (rv.fuel_tank_gal, "RV specs")
        if rv.fuel_tank_gal
        else (CLASS_TANK_GAL[rv.rv_class], "class estimate")
    )
    reserve = tank * RESERVE
    full_range = (tank - reserve) * miles_per_gal
    baseline = estimate_fuel(days, rv, prices, today=today).total_usd

    line = [p for d in days for p in d.geometry] or [
        (days[0].start.lat, days[0].start.lon),
        (days[-1].end.lat, days[-1].end.lon),
    ]
    scale = sum(d.miles for d in days) / (cumulative_miles(line)[-1] or 1)
    total = sum(d.miles for d in days)
    day_ends = [sum(d.miles for d in days[: i + 1]) for i in range(len(days))]
    when = days[0].travel_date or today

    big_rig = rv.total_length_ft > BIG_RIG_FT
    usable = [s for s in stations if s.rv_accessible or not big_rig]
    hits = along_route(usable, line, _where, buffer_miles=BUFFER_MILES)
    priced: list[tuple[float, GasStation]] = []
    for h in hits:
        price = price_for(prices, nearest_state(_where(h.item)), rv.fuel_type, when)
        if price:
            station = h.item.model_copy(update={"avg_price_60d": price.usd_per_gal})
            priced.append((h.along_miles * scale, station))

    warnings = []
    if big_rig and len(usable) < len(stations):
        warnings.append(
            "Only truck stops and travel centers are planned: the RV is too big for most pumps."
        )
    first = [(m, s) for m, s in priced if m <= FIRST_FILL_MILES]
    if not first:
        warnings.append("No station found near the start; leave with a full tank.")
        return FillUpPlan([], tank, tank_source, baseline, warnings)

    stops: list[FillUp] = []
    at, station = min(first, key=lambda ms: _rank(ms[1], ms[0], 0))
    fuel = reserve - at / miles_per_gal  # the drive to the opening fill-up dips into the reserve
    while True:
        ahead = [(m, s) for m, s in priced if at < m <= at + full_range]
        cheaper = next(((m, s) for m, s in ahead if s.avg_price_60d < station.avg_price_60d), None)
        if cheaper:
            need = (cheaper[0] - at) / miles_per_gal + reserve
            target = cheaper
        elif total - at <= full_range:
            need, target = (total - at) / miles_per_gal + reserve, None
        else:
            need = tank
            target = min(ahead, key=lambda ms: _rank(ms[1], ms[0], at)) if ahead else None
        buy = max(0.0, min(tank, need) - fuel)
        if buy > 0:
            stops.append(
                FillUp(
                    station=station,
                    day=next(i + 1 for i, end in enumerate(day_ends) if at <= end + 1e-6),
                    trip_miles=round(at, 1),
                    gallons=round(buy, 1),
                    usd=round(buy * station.avg_price_60d, 2),
                )
            )
            fuel += buy
        if target is None:
            if not (total - at <= full_range):
                warnings.append(
                    f"No suitable station within {full_range:.0f} mi after mile {at:.0f}; "
                    "fill up wherever you can there."
                )
            break
        fuel -= (target[0] - at) / miles_per_gal
        at, station = target

    return FillUpPlan(stops, tank, tank_source, baseline, warnings)


def _rank(station: GasStation, miles: float, at: float) -> tuple:
    """Cheapest area first, then a usually-cheaper chain, then the farthest along."""
    chain = any(c in station.name.lower() for c in USUALLY_CHEAPER)
    return station.avg_price_60d, not chain, -(miles - at)


def _where(station: GasStation) -> Point:
    return station.location.lat, station.location.lon
