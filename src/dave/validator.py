"""The last check before a plan is shown: every hard rule, enforced in code (CLAUDE.md rule 3).

`validate_itinerary` returns one plain message per broken rule, naming the day or booking and
what to change, so the agent can repair the plan and check again. An empty list means the plan
may be shown. Unknown facts fail rather than pass: a site with no listed length, or a route
with an unchecked bridge, is not assumed to fit (context/domain.md).
"""

from dave.booking import terms_digest
from dave.models import BookingStatus, Campground, CampSite, Itinerary, RVProfile

EPSILON = 1e-6  # rounding slack on hours and dollars


def validate_itinerary(itinerary: Itinerary) -> list[str]:
    errors: list[str] = []
    spec, rv = itinerary.spec, itinerary.rv
    for i, day in enumerate(itinerary.days):
        errors += [f"Day {day.day}: {w}" for w in day.clearance_warnings]
        if day.drive_hours > spec.max_drive_hours_per_day + EPSILON:
            errors.append(
                f"Day {day.day}: {day.drive_hours:.1f} h of driving is over the "
                f"{spec.max_drive_hours_per_day:g} h limit; split it or stop sooner."
            )
        home_tonight = spec.round_trip and i == len(itinerary.days) - 1
        if day.campground is None:
            if not home_tonight:
                errors.append(f"Day {day.day}: no campground for the night.")
        elif problem := _site_problem(day.campground, rv, itinerary):
            errors.append(f"Day {day.day}: {day.campground.name}: {problem}")

    budget = itinerary.costs.budget_usd or spec.budget_usd
    if budget is not None and itinerary.costs.total_usd > budget + EPSILON:
        errors.append(
            f"Costs of ${itinerary.costs.total_usd:,.2f} are over the ${budget:,.2f} budget by "
            f"${itinerary.costs.total_usd - budget:,.2f}."
        )

    for b in itinerary.bookings:
        if b.status is not BookingStatus.PROPOSED and b.approved_terms != terms_digest(b):
            errors.append(
                f"Booking {b.name}: {b.status} but its terms changed after approval; "
                "set it back to proposed and ask again."
            )
    return errors


def _site_problem(campground: Campground, rv: RVProfile, itinerary: Itinerary) -> str | None:
    """Why no site here fits the RV, or None when one does."""
    sites = campground.sites or [
        CampSite(
            name=campground.name,
            hookups=campground.hookups,
            max_rv_length_ft=campground.max_rv_length_ft,
            electrical_amps=campground.electrical_amps,
        )
    ]
    needed = itinerary.spec.hookups_required
    length = rv.total_length_ft
    problems = []
    for site in sites:
        if missing := needed - site.hookups:
            problems.append(f"no {', '.join(sorted(missing))} hookup")
        elif site.max_rv_length_ft is None:
            problems.append("site length unknown")
        elif site.max_rv_length_ft < length:
            problems.append(f"sites fit {site.max_rv_length_ft:g} ft, the RV is {length:g} ft")
        elif (
            rv.electrical_amps
            and site.electrical_amps
            and (rv.electrical_amps not in site.electrical_amps)
        ):
            problems.append(f"no {rv.electrical_amps}A power")
        else:
            return None
    return "no site fits: " + "; ".join(dict.fromkeys(problems)) + "."
