"""The plan as a Markdown itinerary an RVer can read on the road.

Day by day: the drive (with a Google Maps directions link), stops, food, gas and the night's
campground; then a daily and total cost table and the bookings waiting for approval. The
itinerary is validated here too (CLAUDE.md rule 3): a plan that breaks a rule is rendered
with a "not final" banner listing what to fix, never as a finished plan.
"""

from urllib.parse import urlencode

from dave.budget import DayCost
from dave.models import BookingProposal, Campground, DayLeg, Itinerary, Place
from dave.validator import validate_itinerary

MAPS_URL = "https://www.google.com/maps/dir/"
MAPS_WAYPOINTS = 9  # Google Maps directions links take at most 9 waypoints


def render_markdown(
    itinerary: Itinerary, *, per_day: list[DayCost] | None = None, notes: list[str] = ()
) -> str:
    spec, rv = itinerary.spec, itinerary.rv
    nights = f"{spec.nights} night" + ("s" if spec.nights != 1 else "")
    name = " ".join(str(x) for x in (rv.year, rv.make, rv.model) if x)
    lines = [
        f"# {spec.origin} to {spec.destination}",
        "",
        f"{nights} in a {name} ({rv.total_length_ft:g} ft long, {rv.height_ft:g} ft tall).",
    ]
    if errors := validate_itinerary(itinerary):
        lines += ["", "> **Not final: this plan breaks a rule.** Fix these before using it:"]
        lines += [f"> - {e}" for e in errors]
    if notes:
        lines += ["", *(f"- {n}" for n in notes)]

    last_nights = spec.nights - len(itinerary.days) + 1
    previous = None
    for i, day in enumerate(itinerary.days):
        stay = last_nights if i == len(itinerary.days) - 1 else 1
        lines += ["", *_day(day, previous, stay)]
        previous = day.campground

    lines += ["", "## Costs", "", *_costs(itinerary, per_day)]
    if itinerary.bookings:
        lines += ["", "## Bookings to approve", "", *_bookings(itinerary.bookings)]
    return "\n".join(lines) + "\n"


def directions_link(day: DayLeg, start: Place | None = None) -> str:
    """Google Maps driving directions from `start` (else the day's start) through its stops."""
    params = {
        "api": "1",
        "origin": _ll(start or day.start),
        "destination": _ll(day.campground.location if day.campground else day.end),
        "travelmode": "driving",
    }
    if day.stops:
        params["waypoints"] = "|".join(_ll(s.location) for s in day.stops[:MAPS_WAYPOINTS])
    return f"{MAPS_URL}?{urlencode(params)}"


def _day(day: DayLeg, previous: Campground | None, nights: int) -> list[str]:
    """One day. It starts at last night's campground, if there was one, and ends at tonight's."""
    when = f" · {day.travel_date:%a %b %d}" if day.travel_date else ""
    start = previous.location if previous else day.start
    end = day.campground.name if day.campground else day.end.name
    out = [
        f"## Day {day.day}{when}: {previous.name if previous else day.start.name} to {end}",
        "",
        f"{day.miles:.0f} miles, about {_hours(day.drive_hours)} of driving. "
        f"[Directions]({directions_link(day, start)}) (Google Maps doesn't know the RV's "
        "height; where it differs, follow Dave's route.)",
    ]
    out += [f"- ⚠️ {w}" for w in day.clearance_warnings]
    if day.stops:
        out += ["", "**Stops**"]
        for s in day.stops:
            extra = [f"{s.detour_minutes:.0f} min detour"] if s.detour_minutes else []
            if s.ticket_price_usd:
                extra.append(f"${s.ticket_price_usd:,.2f} entry")
            if s.rv_parking_note:
                extra.append(s.rv_parking_note)
            out.append(f"- {s.name}" + (f" ({'; '.join(extra)})" if extra else ""))
    if day.restaurants:
        out += ["", "**Food**"]
        for r in day.restaurants:
            extra = [r.cuisine] if r.cuisine else []
            if r.rating is not None:
                extra.append(f"rated {r.rating:g}/10")
            if r.price_level:
                extra.append("$" * r.price_level)
            out.append(f"- {r.name}" + (f" ({', '.join(extra)})" if extra else ""))
    if day.gas_stations:
        out += ["", "**Gas**"]
        for g in day.gas_stations:
            price = f" at ${g.price_per_gal:.2f}/gal" if g.price_per_gal else ""
            out.append(f"- {g.name}{price}")
    tonight = "Tonight" if nights == 1 else f"Tonight and the next {nights - 1}"
    out += ["", f"**{tonight}**", f"- {_campground(day)}"]
    return out


def _campground(day: DayLeg) -> str:
    camp = day.campground
    if camp is None:
        return "Home."
    hookups = camp.hookups or set().union(*(s.hookups for s in camp.sites))
    parts = [camp.name]
    if camp.nightly_price_usd is not None:
        parts.append(f"${camp.nightly_price_usd:g} a night")
    else:
        parts.append("price to confirm")
    if hookups:
        parts.append(" + ".join(sorted(hookups)) + " hookups")
    text = ", ".join(parts)
    return f"[{text}]({camp.booking_url})" if camp.booking_url else text


def _costs(itinerary: Itinerary, per_day: list[DayCost] | None) -> list[str]:
    c = itinerary.costs
    out = ["| | Fuel | Campground | Tickets | Total |", "|---|---:|---:|---:|---:|"]
    for d in per_day or []:
        out.append(
            f"| Day {d.day} | {_usd(d.fuel_usd)} | {_usd(d.campground_usd)} | "
            f"{_usd(d.tickets_usd)} | {_usd(d.total_usd)} |"
        )
    out.append(
        f"| **Trip** | {_usd(c.fuel_usd)} | {_usd(c.campgrounds_usd)} | {_usd(c.tickets_usd)} | "
        f"**{_usd(c.total_usd)}** |"
    )
    if c.budget_usd is not None:
        left = c.remaining_usd
        verdict = f"{_usd(left)} to spare" if left >= 0 else f"{_usd(-left)} over"
        out += ["", f"Budget {_usd(c.budget_usd)}: {verdict}."]
    out += ["", "Fuel is an estimate from regional average prices."]
    return out


def _bookings(bookings: list[BookingProposal]) -> list[str]:
    out = []
    for b in bookings:
        dates = f"{b.start_date:%b %d}" + (f" to {b.end_date:%b %d}" if b.end_date else "")
        name = f"[{b.name}]({b.url})" if b.url else b.name
        out.append(f"- {b.kind.title()}: {name}, {dates}, {_usd(b.price_usd)} ({b.status})")
    out += ["", "Nothing is booked or paid until you approve each one."]
    return out


def _ll(place: Place) -> str:
    return f"{place.lat:.5f},{place.lon:.5f}"


def _hours(h: float) -> str:
    whole, minutes = divmod(round(h * 60), 60)
    return f"{whole} h {minutes:02d} min" if whole else f"{minutes} min"


def _usd(x: float) -> str:
    return f"${x:,.2f}"
