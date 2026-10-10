"""Score a plan against reality: what a trip's real-world references say, check by check.

A `TripReference` holds what was observed outside Dave, each fact with its source and the
date it was checked: drive times from an independent routing service, campground hookups,
site lengths and prices from official pages, current gas prices, and known low bridges
near the route. `score_trip` compares an itinerary (and the gas prices it was planned with)
with those facts and returns a `Scorecard` of passed and failed checks; the failures are the
gaps to turn into tasks.

References are data files under `evals/reality/`, one per demo trip, collected where the
sources can be reached. Nothing here makes a network call.
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pydantic import Field

from dave.corridor import locate
from dave.models import GasPrice, Hookup, Itinerary, Model

REALITY = Path(__file__).resolve().parents[2] / "evals" / "reality"

DRIVE_TIME_TOLERANCE = 0.15  # Dave's hours within 15% of the reference
PRICE_TOLERANCE_USD = 5.0  # a nightly price this close counts as right
GAS_TOLERANCE = 0.05  # a gas price within 5%
ON_ROUTE_MILES = 0.05  # a low bridge this close to the route line is on it


class Reference(Model):
    source: str = Field(description="URL or service the fact came from")
    checked: date


class DriveReference(Reference):
    day: int
    drive_hours: float = Field(gt=0)


class CampgroundReference(Reference):
    name: str
    hookups: set[Hookup] | None = None  # None: the page doesn't say
    max_rv_length_ft: float | None = Field(default=None, gt=0)
    nightly_price_usd: float | None = Field(default=None, ge=0)


class GasReference(Reference):
    state: str  # two-letter code
    usd_per_gal: float = Field(gt=0)


class LowClearance(Reference):
    name: str
    lat: float
    lon: float
    clearance_ft: float = Field(gt=0)


class TripReference(Model):
    trip: str
    note: str | None = None  # how it was collected
    drive: list[DriveReference] = Field(default_factory=list)
    campgrounds: list[CampgroundReference] = Field(default_factory=list)
    gas: list[GasReference] = Field(default_factory=list)
    low_clearances: list[LowClearance] = Field(default_factory=list)


@dataclass(frozen=True)
class Check:
    kind: str  # drive time, hookups, site length, price, gas price, clearance
    subject: str
    passed: bool
    detail: str


@dataclass
class Scorecard:
    trip: str
    checks: list[Check] = field(default_factory=list)

    @property
    def score(self) -> float | None:
        return sum(c.passed for c in self.checks) / len(self.checks) if self.checks else None

    @property
    def gaps(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]


def load_reference(trip: str, folder: Path = REALITY) -> TripReference:
    return TripReference.model_validate_json((folder / f"{trip}.json").read_text())


def score_trip(
    itinerary: Itinerary, reference: TripReference, gas_prices: list[GasPrice] = ()
) -> Scorecard:
    card = Scorecard(reference.trip)
    card.checks += _drive_times(itinerary, reference)
    card.checks += _campgrounds(itinerary, reference)
    card.checks += _gas(itinerary, reference, gas_prices)
    card.checks += _clearances(itinerary, reference)
    return card


def _drive_times(itinerary: Itinerary, ref: TripReference) -> list[Check]:
    days = {d.day: d for d in itinerary.days}
    out = []
    for r in ref.drive:
        day = days.get(r.day)
        if day is None:
            continue
        off = abs(day.drive_hours - r.drive_hours) / r.drive_hours
        out.append(
            Check(
                "drive time",
                f"Day {r.day}",
                off <= DRIVE_TIME_TOLERANCE,
                f"Dave {day.drive_hours:.1f} h, {r.source} {r.drive_hours:.1f} h ({off:.0%} off)",
            )
        )
    return out


def _campgrounds(itinerary: Itinerary, ref: TripReference) -> list[Check]:
    by_name = {r.name: r for r in ref.campgrounds}
    out = []
    for day in itinerary.days:
        camp = day.campground
        r = by_name.get(camp.name) if camp else None
        if r is None:
            continue
        subject = f"Day {day.day}: {camp.name}"
        need = itinerary.spec.hookups_required
        if r.hookups is not None:
            missing = need - r.hookups
            out.append(
                Check(
                    "hookups",
                    subject,
                    not missing,
                    f"{r.source} lists {', '.join(sorted(r.hookups)) or 'none'}"
                    + (f"; missing {', '.join(sorted(missing))}" if missing else ""),
                )
            )
        if r.max_rv_length_ft is not None:
            length = itinerary.rv.total_length_ft
            out.append(
                Check(
                    "site length",
                    subject,
                    r.max_rv_length_ft >= length,
                    f"{r.source} allows {r.max_rv_length_ft:g} ft; the RV is {length:g} ft",
                )
            )
        if r.nightly_price_usd is not None:
            planned = camp.nightly_price_usd
            ok = planned is not None and abs(planned - r.nightly_price_usd) <= PRICE_TOLERANCE_USD
            shown = "no price" if planned is None else f"${planned:g}"
            out.append(
                Check(
                    "price",
                    subject,
                    ok,
                    f"Dave {shown}, {r.source} ${r.nightly_price_usd:g} a night",
                )
            )
    return out


def _gas(itinerary: Itinerary, ref: TripReference, prices: list[GasPrice]) -> list[Check]:
    fuel = itinerary.rv.fuel_type
    out = []
    for r in ref.gas:
        planned = [p for p in prices if p.area == f"S{r.state}" and p.fuel_type is fuel]
        if not planned:
            continue
        used = max(planned, key=lambda p: p.period)
        off = abs(used.usd_per_gal - r.usd_per_gal) / r.usd_per_gal
        out.append(
            Check(
                "gas price",
                r.state,
                off <= GAS_TOLERANCE,
                f"Dave ${used.usd_per_gal:.2f} (week of {used.period}), "
                f"{r.source} ${r.usd_per_gal:.2f} ({off:.0%} off)",
            )
        )
    return out


def _clearances(itinerary: Itinerary, ref: TripReference) -> list[Check]:
    """Every known low bridge the RV can't pass must be off the route or warned about."""
    height = itinerary.rv.height_ft
    out = []
    for bridge in ref.low_clearances:
        if bridge.clearance_ft >= height:
            continue
        point = (bridge.lat, bridge.lon)
        on = [
            d
            for d in itinerary.days
            if d.geometry and locate(point, d.geometry)[1] <= ON_ROUTE_MILES
        ]
        warned = [d for d in on if any(bridge.name in w for w in d.clearance_warnings)]
        passed = not on or len(warned) == len(on)
        where = ", ".join(f"Day {d.day}" for d in on) or "not on the route"
        out.append(
            Check(
                "clearance",
                bridge.name,
                passed,
                f"{bridge.clearance_ft:g} ft, the RV is {height:g} ft; {where}"
                + ("" if passed else ", and Dave didn't warn"),
            )
        )
    return out


def render_scorecards(cards: list[Scorecard]) -> str:
    """Per-trip and overall results, then the gaps, as Markdown."""
    lines = ["# Dave vs. reality", "", "| Trip | Checks | Passed | Score |", "|---|---:|---:|---:|"]
    for c in cards:
        score = "n/a" if c.score is None else f"{c.score:.0%}"
        passed = len(c.checks) - len(c.gaps)
        lines.append(f"| {c.trip} | {len(c.checks)} | {passed} | {score} |")
    total = sum(len(c.checks) for c in cards)
    passed = total - sum(len(c.gaps) for c in cards)
    if total:
        lines.append(f"| **All** | {total} | {passed} | {passed / total:.0%} |")
    gaps = [(c.trip, g) for c in cards for g in c.gaps]
    lines += ["", "## Gaps", ""]
    lines += [f"- {trip}, {g.kind}, {g.subject}: {g.detail}" for trip, g in gaps] or ["None."]
    return "\n".join(lines) + "\n"
