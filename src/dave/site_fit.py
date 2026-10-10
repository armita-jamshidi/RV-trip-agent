"""Does this RV fit at this campground? Pass, fail, or call to confirm.

A campground fits when one of its sites has every required hookup, is long enough for the RV
plus anything it tows, and has the RV's amperage when both are known. Unknown hookups or
length never pass silently: the campground is kept but marked "call to confirm".

Hookups count as unknown only for a campground listed without sites (Foursquare's free
fields carry none); a listed site with no hookups has none.
"""

from dataclasses import dataclass
from enum import StrEnum

from dave.models import Campground, CampSite, Hookup, RVProfile


class Fit(StrEnum):
    YES = "fits"
    CONFIRM = "call to confirm"
    NO = "doesn't fit"


@dataclass(frozen=True)
class SiteFit:
    campground: Campground
    fit: Fit
    reason: str  # what fits, what to confirm, or why not
    sites: tuple[str, ...] = ()  # the sites that fit (or might)


def check_site(
    site: CampSite, rv: RVProfile, required: set[Hookup], hookups_known: bool = True
) -> tuple[Fit, str]:
    length = rv.total_length_ft
    unknown = []
    if hookups_known:
        if missing := required - site.hookups:
            return Fit.NO, f"no {', '.join(sorted(missing))} hookup"
    elif required:
        unknown.append(f"{' and '.join(sorted(required))} hookups")
    if site.max_rv_length_ft is None:
        unknown.append(f"room for {length:g} ft")
    elif site.max_rv_length_ft < length:
        return Fit.NO, f"sites fit {site.max_rv_length_ft:g} ft, the RV is {length:g} ft"
    if (
        rv.electrical_amps
        and site.electrical_amps
        and rv.electrical_amps not in site.electrical_amps
    ):
        return Fit.NO, f"no {rv.electrical_amps}A power"
    if unknown:
        return Fit.CONFIRM, "confirm " + " and ".join(unknown)
    return Fit.YES, f"fits {length:g} ft with " + ", ".join(sorted(site.hookups) or ["no hookups"])


def check_campground(campground: Campground, rv: RVProfile, required: set[Hookup]) -> SiteFit:
    """The best answer over the campground's sites: one site that fits is enough."""
    if campground.sites:
        sites, hookups_known = campground.sites, True
    else:
        summary = CampSite(
            name=campground.name,
            hookups=campground.hookups,
            max_rv_length_ft=campground.max_rv_length_ft,
            electrical_amps=campground.electrical_amps,
        )
        sites, hookups_known = [summary], bool(campground.hookups)

    results = [(s, *check_site(s, rv, required, hookups_known)) for s in sites]
    for wanted in (Fit.YES, Fit.CONFIRM):
        matching = [(s, why) for s, fit, why in results if fit is wanted]
        if matching:
            names = tuple(s.name for s, _ in matching) if campground.sites else ()
            return SiteFit(campground, wanted, matching[0][1], names)
    reasons = "; ".join(dict.fromkeys(why for _, _, why in results))
    return SiteFit(campground, Fit.NO, f"no site fits: {reasons}")


def filter_campgrounds(
    campgrounds: list[Campground], rv: RVProfile, required: set[Hookup]
) -> list[SiteFit]:
    """Campgrounds the RV fits, then those to call and confirm. Ones that don't fit are dropped."""
    checked = [check_campground(c, rv, required) for c in campgrounds]
    return [c for c in checked if c.fit is Fit.YES] + [c for c in checked if c.fit is Fit.CONFIRM]
