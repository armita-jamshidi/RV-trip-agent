"""Pick a campground for each night: one that fits the RV, looks great and keeps costs down.

For each day's end, the candidates within `radius_miles` are filtered by T14 (site length,
hookups, amps), ranked for scenery by T16, then weighed against the nightly price and the
drive off the route. A campground known to fit always beats one that needs a call to
confirm; within each group the weighted score decides. Campgrounds over the nightly price
cap are dropped. Each night gets the pick plus up to two alternatives.
"""

from dataclasses import dataclass, field

from dave.corridor import detour_minutes
from dave.geo import haversine_miles
from dave.models import Campground, DayLeg, Hookup, RVProfile
from dave.scenic import rank_scenic
from dave.site_fit import Fit, SiteFit, filter_campgrounds
from dave.store.vectors import Embedder

RADIUS_MILES = 25.0
ALTERNATIVES = 2
PRICE_CAP_USD = 80.0  # a night at or above this scores zero on price
UNKNOWN_PRICE = 0.3  # an unknown price could break the budget, so it scores below average
LONG_DETOUR_MINUTES = 120.0  # this much extra driving (there and back) scores zero
WEIGHTS = {"scenic": 0.45, "price": 0.3, "detour": 0.25}


@dataclass(frozen=True)
class Choice:
    campground: Campground
    fit: SiteFit
    score: float  # 0 to 1
    detour_minutes: float  # extra driving, there and back, from the day's end point
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NightPick:
    day: int
    pick: Choice | None
    alternatives: list[Choice]
    note: str  # why this one, or why there is none


def overnight_centers(days: list[DayLeg]) -> list[tuple[float, float]]:
    """Where to search: each day's end. Pass these to `campgrounds.ingest`."""
    return [(d.end.lat, d.end.lon) for d in days]


def pick_night(
    day: DayLeg,
    campgrounds: list[Campground],
    rv: RVProfile,
    required: set[Hookup],
    embedder: Embedder,
    *,
    radius_miles: float = RADIUS_MILES,
    max_nightly_usd: float | None = None,
) -> NightPick:
    end = (day.end.lat, day.end.lon)
    off = {id(c): haversine_miles(end, (c.location.lat, c.location.lon)) for c in campgrounds}
    nearby = [c for c in campgrounds if off[id(c)] <= radius_miles]
    if max_nightly_usd is not None:
        nearby = [
            c
            for c in nearby
            if c.nightly_price_usd is None or c.nightly_price_usd <= max_nightly_usd
        ]
    fits = {id(f.campground): f for f in filter_campgrounds(nearby, rv, required)}
    if not fits:
        why = f"No campground within {radius_miles:g} miles of {day.end.name} fits the RV"
        why += f" with {', '.join(sorted(required))} hookups." if required else "."
        return NightPick(day.day, None, [], why)

    cap = max_nightly_usd or PRICE_CAP_USD
    choices = []
    for camp, scenic in rank_scenic([fits[k].campground for k in fits], embedder):
        minutes = detour_minutes(off[id(camp)])
        price = camp.nightly_price_usd
        parts = {
            "scenic": scenic.score,
            "price": UNKNOWN_PRICE if price is None else max(0.0, 1 - price / cap),
            "detour": max(0.0, 1 - minutes / LONG_DETOUR_MINUTES),
        }
        fit = fits[id(camp)]
        reasons = [fit.reason, *scenic.reasons]
        reasons.append(f"${price:g} a night" if price is not None else "price unknown")
        reasons.append(f"{minutes:.0f} min of extra driving")
        score = sum(WEIGHTS[k] * v for k, v in parts.items())
        choices.append(Choice(camp, fit, score, minutes, reasons))

    choices.sort(key=lambda c: (c.fit.fit is not Fit.YES, -c.score))
    best, rest = choices[0], choices[1 : 1 + ALTERNATIVES]
    note = f"{best.campground.name}: " + "; ".join(best.reasons) + "."
    if best.fit.fit is Fit.CONFIRM:
        note = f"Call to confirm {best.campground.name}: {best.fit.reason}."
    return NightPick(day.day, best, rest, note)


def pick_campgrounds(
    days: list[DayLeg],
    campgrounds: list[Campground],
    rv: RVProfile,
    required: set[Hookup],
    embedder: Embedder,
    *,
    round_trip: bool = False,
    radius_miles: float = RADIUS_MILES,
    max_nightly_usd: float | None = None,
) -> list[NightPick]:
    """One pick per night. On a round trip the last day ends at home and needs none."""
    nights = days[:-1] if round_trip else days
    return [
        pick_night(
            d,
            campgrounds,
            rv,
            required,
            embedder,
            radius_miles=radius_miles,
            max_nightly_usd=max_nightly_usd,
        )
        for d in nights
    ]


def with_campgrounds(days: list[DayLeg], picks: list[NightPick]) -> list[DayLeg]:
    """The days with each night's pick filled in. Nights without a pick stay empty."""
    chosen = {p.day: p.pick.campground for p in picks if p.pick}
    return [d.model_copy(update={"campground": chosen.get(d.day, d.campground)}) for d in days]


def campground_costs(picks: list[NightPick]) -> float:
    """Known nightly prices of the picks; unknown prices are left for the booking step."""
    return sum(p.pick.campground.nightly_price_usd or 0 for p in picks if p.pick is not None)
