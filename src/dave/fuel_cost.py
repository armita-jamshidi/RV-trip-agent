"""What fuel will cost for the trip, per day and in total, from EIA's weekly averages (T22).

Gallons = miles / MPG, using the RV's own MPG when known, else the class average from
context/domain.md. Each day's route is cut into short pieces and each piece is priced in the
state it falls in, so a day that crosses from Colorado into Utah pays some of each. The state
is the one whose center is nearest, which can be wrong within a few miles of a border; prices
are regional averages anyway, so every number here is an estimate and says so.
"""

from dataclasses import dataclass
from datetime import date

from dave.gas_prices import price_for
from dave.geo import Point, cumulative_miles, haversine_miles, interpolate
from dave.models import DayLeg, FuelType, GasPrice, RVClass, RVProfile

SOURCE = "U.S. EIA weekly retail average"
CLASS_MPG = {
    RVClass.A: 8.0,
    RVClass.B: 18.0,
    RVClass.C: 12.0,
    RVClass.TRAVEL_TRAILER: 10.0,  # the tow vehicle's mileage while towing
    RVClass.FIFTH_WHEEL: 10.0,
}
PIECES_PER_DAY = 10

# Approximate geographic center of each state (lat, lon), for nearest-state lookup.
STATE_CENTERS = {
    "AL": (32.8, -86.8), "AK": (64.7, -152.0), "AZ": (34.3, -111.7), "AR": (34.9, -92.4),
    "CA": (37.2, -119.5), "CO": (39.0, -105.5), "CT": (41.6, -72.7), "DE": (39.0, -75.5),
    "DC": (38.9, -77.0), "FL": (28.6, -82.4), "GA": (32.7, -83.4), "HI": (20.3, -156.4),
    "ID": (44.4, -114.6), "IL": (40.0, -89.2), "IN": (39.9, -86.3), "IA": (42.1, -93.5),
    "KS": (38.5, -98.4), "KY": (37.5, -85.3), "LA": (31.1, -92.0), "ME": (45.4, -69.2),
    "MD": (39.0, -76.8), "MA": (42.3, -71.8), "MI": (44.3, -85.4), "MN": (46.3, -94.3),
    "MS": (32.7, -89.7), "MO": (38.4, -92.5), "MT": (47.0, -109.6), "NE": (41.5, -99.8),
    "NV": (39.3, -116.6), "NH": (43.7, -71.6), "NJ": (40.2, -74.7), "NM": (34.4, -106.1),
    "NY": (42.9, -75.5), "NC": (35.6, -79.4), "ND": (47.5, -100.5), "OH": (40.3, -82.8),
    "OK": (35.6, -97.5), "OR": (43.9, -120.6), "PA": (40.9, -77.8), "RI": (41.7, -71.5),
    "SC": (33.9, -80.9), "SD": (44.4, -100.2), "TN": (35.9, -86.4), "TX": (31.5, -99.3),
    "UT": (39.3, -111.7), "VT": (44.1, -72.7), "VA": (37.5, -78.9), "WA": (47.4, -120.5),
    "WV": (38.6, -80.6), "WI": (44.6, -89.9), "WY": (43.0, -107.6),
}  # fmt: skip


@dataclass(frozen=True)
class DayFuel:
    day: int
    miles: float
    gallons: float
    usd: float
    usd_per_gal: float  # mileage-weighted across the areas the day crosses
    areas: list[str]  # EIA area names the prices came from
    price_week: date  # the latest EIA week used

    def line(self) -> str:
        return (
            f"Day {self.day}: {self.miles:.0f} mi, {self.gallons:.1f} gal at about "
            f"${self.usd_per_gal:.2f}/gal ({', '.join(self.areas)}): ${self.usd:,.2f}"
        )


@dataclass(frozen=True)
class FuelEstimate:
    days: list[DayFuel]
    mpg: float
    mpg_source: str  # "RV specs" or "class average"
    fuel_type: FuelType

    @property
    def total_usd(self) -> float:
        return round(sum(d.usd for d in self.days), 2)

    @property
    def gallons(self) -> float:
        return round(sum(d.gallons for d in self.days), 1)

    def summary(self) -> list[str]:
        weeks = sorted({d.price_week for d in self.days})
        return [
            *(d.line() for d in self.days),
            f"Fuel total: about ${self.total_usd:,.2f} for {self.gallons:.1f} gal of "
            f"{self.fuel_type.value} at {self.mpg:g} mpg ({self.mpg_source}).",
            f"Estimate from {SOURCE} prices, week of {weeks[-1].isoformat()}.",
        ]


def mpg(rv: RVProfile) -> tuple[float, str]:
    if rv.mpg:
        return rv.mpg, "RV specs"
    return CLASS_MPG[rv.rv_class], "class average"


def nearest_state(point: Point) -> str:
    return min(STATE_CENTERS, key=lambda s: haversine_miles(point, STATE_CENTERS[s]))


def estimate_fuel(
    days: list[DayLeg], rv: RVProfile, prices: list[GasPrice], *, today: date
) -> FuelEstimate:
    """Fuel cost per day. Raises ValueError when there are no stored prices to use."""
    miles_per_gal, mpg_source = mpg(rv)
    out = []
    for day in days:
        gallons = day.miles / miles_per_gal
        when = day.travel_date or today
        used: list[tuple[float, GasPrice]] = []
        for share, point in _pieces(day):
            price = price_for(prices, nearest_state(point), rv.fuel_type, when)
            if price is None:
                raise ValueError(f"No {rv.fuel_type.value} prices stored; run `dave gas-snapshot`.")
            used.append((share, price))
        per_gal = sum(share * p.usd_per_gal for share, p in used)
        out.append(
            DayFuel(
                day=day.day,
                miles=day.miles,
                gallons=round(gallons, 2),
                usd=round(gallons * per_gal, 2),
                usd_per_gal=round(per_gal, 3),
                areas=list(dict.fromkeys(_tidy(p.area_name) for _, p in used)),
                price_week=max(p.period for _, p in used),
            )
        )
    return FuelEstimate(out, miles_per_gal, mpg_source, rv.fuel_type)


def _tidy(name: str) -> str:
    """EIA writes states in capitals ("COLORADO"); regions read fine as they are ("PADD 4")."""
    return name.title() if name.isupper() and not name.startswith("PADD") else name


def _pieces(day: DayLeg) -> list[tuple[float, Point]]:
    """(share of the day's miles, midpoint) for equal-length pieces of the day's route."""
    line = day.geometry or [(day.start.lat, day.start.lon), (day.end.lat, day.end.lon)]
    cum = cumulative_miles(line)
    if cum[-1] == 0:
        return [(1.0, line[0])]
    points, i = [], 0
    for k in range(PIECES_PER_DAY):
        target = cum[-1] * (k + 0.5) / PIECES_PER_DAY
        while i + 1 < len(line) - 1 and cum[i + 1] < target:
            i += 1
        span = cum[i + 1] - cum[i]
        points.append(interpolate(line[i], line[i + 1], (target - cum[i]) / span if span else 0))
    return [(1 / PIECES_PER_DAY, p) for p in points]
