"""Campground bookings: proposed for approval, then handed to the traveler to book themselves.

Recreation.gov has no public booking API (RIDB is read-only), so Dave never reserves a site.
Each night's pick (T17) becomes a `BookingProposal` with a link straight to the site that
fits, set to the stay's dates. Once a person has approved it (`dave.booking.approve`),
`handoff` gives the steps to book it: the link, which site, the dates, the approved price,
and for private parks their website and phone. Consecutive nights at one campground are one
stay and one booking.

Campgrounds without a listed price get no proposal, since a $0 approval would mean nothing;
they get a note to ask for the price instead.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlencode

from dave.booking import require_approval
from dave.models import BookingProposal, Campground, DayLeg
from dave.overnight import NightPick

RECREATION_GOV = "https://www.recreation.gov/"
RECREATION_GOV_SITE = "https://www.recreation.gov/camping/campsites/{}"


@dataclass(frozen=True)
class Stay:
    campground: Campground
    check_in: date
    nights: int
    site: str | None  # the site name that fits, when the source lists sites
    site_id: str | None
    fit: str  # what fits, or what to confirm, from T14

    @property
    def check_out(self) -> date:
        return self.check_in + timedelta(days=self.nights)

    @property
    def price_usd(self) -> float | None:
        price = self.campground.nightly_price_usd
        return None if price is None else round(price * self.nights, 2)


def stays(days: list[DayLeg], picks: list[NightPick]) -> list[Stay]:
    """One stay per run of nights at the same campground. Days need their travel dates."""
    dated = {d.day: d.travel_date for d in days}
    out: list[Stay] = []
    for p in sorted((p for p in picks if p.pick), key=lambda p: p.day):
        night = dated.get(p.day)
        if night is None:
            raise ValueError(f"Day {p.day} has no date; set travel dates before booking.")
        camp = p.pick.campground
        last = out[-1] if out else None
        if last and last.campground == camp and last.check_out == night:
            out[-1] = Stay(camp, last.check_in, last.nights + 1, last.site, last.site_id, last.fit)
            continue
        site = next((s for s in camp.sites if s.name in p.pick.fit.sites), None)
        out.append(
            Stay(
                camp,
                night,
                1,
                site.name if site else None,
                site.site_id if site else None,
                p.pick.fit.reason,
            )
        )
    return out


def booking_link(stay: Stay) -> str | None:
    """Recreation.gov: the fitting site's page with the dates; private parks: their website."""
    url = stay.campground.booking_url
    if url and url.startswith(RECREATION_GOV) and stay.site_id:
        url = RECREATION_GOV_SITE.format(stay.site_id)
    if url and url.startswith(RECREATION_GOV):
        dates = {"startDate": stay.check_in.isoformat(), "endDate": stay.check_out.isoformat()}
        url = f"{url}?{urlencode(dates)}"
    return url


def campground_proposals(
    days: list[DayLeg], picks: list[NightPick]
) -> tuple[list[BookingProposal], list[str]]:
    """Proposals for every priced stay, and a note for each stay that has no listed price."""
    proposals, notes = [], []
    for stay in stays(days, picks):
        if stay.price_usd is None:
            contact = f" ({stay.campground.phone})" if stay.campground.phone else ""
            notes.append(
                f"{stay.campground.name}{contact} lists no price; ask for {_dates(stay)}, "
                "then propose it again."
            )
            continue
        proposals.append(
            BookingProposal(
                kind="campground",
                name=stay.campground.name,
                start_date=stay.check_in,
                end_date=stay.check_out,
                price_usd=stay.price_usd,
                url=booking_link(stay),
            )
        )
    return proposals, notes


def handoff(proposal: BookingProposal, stay: Stay) -> list[str]:
    """Steps for the traveler to book an approved stay. Raises if it isn't approved as-is."""
    require_approval(proposal)
    if (proposal.name, proposal.start_date, proposal.end_date) != (
        stay.campground.name,
        stay.check_in,
        stay.check_out,
    ):
        raise ValueError(f"{proposal.name}: this proposal is for a different stay.")
    camp = stay.campground
    steps = []
    if proposal.url and proposal.url.startswith(RECREATION_GOV):
        steps.append(f"Open {proposal.url} and sign in to your Recreation.gov account.")
    elif proposal.url:
        steps.append(f"Book on {proposal.url}" + (f" or call {camp.phone}." if camp.phone else "."))
    elif camp.phone:
        steps.append(f"Call {camp.phone}; there is no online booking.")
    else:
        steps.append(f"{camp.name} takes no reservations: arrive early for a first-come site.")
    if stay.site:
        steps.append(f"Choose site {stay.site} ({stay.fit}).")
    else:
        steps.append(f"Ask for a site that works for the RV: {stay.fit}.")
    steps.append(f"Dates: {_dates(stay)}.")
    steps.append(
        f"Approved price: ${proposal.price_usd:,.2f}. If checkout shows more, stop and ask "
        "Dave to propose it again."
    )
    return steps


def _dates(stay: Stay) -> str:
    nights = f"{stay.nights} night" + ("s" if stay.nights > 1 else "")
    return f"check in {stay.check_in:%a %b %d}, check out {stay.check_out:%a %b %d} ({nights})"
