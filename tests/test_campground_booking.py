from datetime import UTC, date, datetime

import httpx
import pytest
from conftest import ConceptEmbedder
from test_campgrounds import Sources
from test_overnight import COLORADO, DENVER, MINNIE, MOAB, NEED, OSRM, camp, night

from dave.booking import ApprovalRequired, approve
from dave.campground_booking import booking_link, campground_proposals, handoff, stays
from dave.campgrounds import ingest
from dave.days import split_days
from dave.http import CachedClient
from dave.models import Campground, Place
from dave.overnight import overnight_centers, pick_campgrounds, pick_night
from dave.routing import route

NOW = datetime(2026, 10, 10, 3, 0, tzinfo=UTC)
NOV_2 = date(2026, 11, 2)


def dated(day: int, when: date, **where):
    return night(**where).model_copy(update={"day": day, "travel_date": when})


def demo_trip_1(tmp_path):
    """Denver to Moab, leaving Nov 2: the same days and picks as T17's demo trip 1 test."""
    osrm = CachedClient(
        tmp_path / "osrm", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=OSRM))
    )
    days = split_days(route([DENVER, MOAB], osrm), DENVER, MOAB)
    days = [d.model_copy(update={"travel_date": date(2026, 11, 1 + d.day)}) for d in days]
    sources = CachedClient(tmp_path / "camps", transport=httpx.MockTransport(Sources()))
    moab = ingest(overnight_centers(days)[1:], 30, sources, ridb_key="r", foursquare_key="f")
    return days, pick_campgrounds(days, COLORADO + moab, MINNIE, NEED, ConceptEmbedder())


def test_demo_trip_1_links_go_to_the_fitting_site_on_the_right_dates(tmp_path):
    days, picks = demo_trip_1(tmp_path)
    proposals, notes = campground_proposals(days, picks)
    assert notes == []
    devils = proposals[1]
    assert (devils.name, devils.start_date, devils.end_date, devils.price_usd) == (
        "Devils Garden Campground (Arches)",
        date(2026, 11, 3),
        date(2026, 11, 4),
        25,
    )
    # Site 002 is the one with electric and water for the 32.75 ft Minnie Winnie.
    assert devils.url == (
        "https://www.recreation.gov/camping/campsites/2?startDate=2026-11-03&endDate=2026-11-04"
    )
    assert proposals[0].name == "Rifle Falls" and proposals[0].url is None  # no reservations

    steps = handoff(approve(devils, "Armita", now=NOW), stays(days, picks)[1])
    assert steps == [
        f"Open {devils.url} and sign in to your Recreation.gov account.",
        "Choose site 002 (fits 32.75 ft with electric, water).",
        "Dates: check in Tue Nov 03, check out Wed Nov 04 (1 night).",
        "Approved price: $25.00. If checkout shows more, stop and ask Dave to propose it again.",
    ]


def test_handoff_needs_an_approval_for_the_exact_terms(tmp_path):
    days, picks = demo_trip_1(tmp_path)
    proposal = campground_proposals(days, picks)[0][1]
    stay = stays(days, picks)[1]
    with pytest.raises(ApprovalRequired, match="not approved"):
        handoff(proposal, stay)
    changed = approve(proposal, "Armita", now=NOW).model_copy(update={"price_usd": 40})
    with pytest.raises(ApprovalRequired, match="terms changed"):
        handoff(changed, stay)
    with pytest.raises(ValueError, match="different stay"):
        handoff(approve(proposal, "Armita", now=NOW), stays(days, picks)[0])


def test_back_to_back_nights_at_one_campground_are_one_booking():
    days = [dated(1, NOV_2), dated(2, date(2026, 11, 3)), dated(3, date(2026, 11, 4))]
    rifle = [c for c in COLORADO if c.name == "Rifle Falls"]
    picks = [pick_night(d, rifle, MINNIE, NEED, ConceptEmbedder()) for d in days[:2]]
    picks.append(pick_night(days[2], COLORADO[1:2], MINNIE, NEED, ConceptEmbedder()))
    proposals, _ = campground_proposals(days, picks)
    assert [(p.name, p.start_date, p.end_date, p.price_usd) for p in proposals] == [
        ("Rifle Falls", NOV_2, date(2026, 11, 4), 56),
        ("Exit 90 RV Lot", date(2026, 11, 4), date(2026, 11, 5), 35),
    ]


def test_private_park_gives_website_and_phone():
    park = Campground(
        name="Sun Outdoors Arches Gateway",
        location=Place(name="x", lat=39.40, lon=-107.72),
        hookups=set(NEED),
        max_rv_length_ft=45,
        nightly_price_usd=72,
        booking_url="https://www.sunoutdoors.com/utah/sun-outdoors-arches-gateway",
        phone="(435) 259-6682",
        source="foursquare",
    )
    day = dated(1, NOV_2)
    picks = [pick_night(day, [park], MINNIE, NEED, ConceptEmbedder())]
    (proposal,), _ = campground_proposals([day], picks)
    assert proposal.url == park.booking_url  # private sites get no date parameters
    steps = handoff(approve(proposal, "Armita", now=NOW), stays([day], picks)[0])
    assert steps[:2] == [
        f"Book on {park.booking_url} or call (435) 259-6682.",
        "Ask for a site that works for the RV: fits 32.75 ft with electric, water.",
    ]


def test_unpriced_campground_gets_a_note_not_a_zero_dollar_proposal():
    hilltop = camp("Hilltop Park", 39.45, -107.60, "Quiet sites with views.", None)
    hilltop = hilltop.model_copy(update={"phone": "970-555-0100"})
    day = dated(1, NOV_2)
    picks = [pick_night(day, [hilltop], MINNIE, NEED, ConceptEmbedder())]
    proposals, notes = campground_proposals([day], picks)
    assert proposals == []
    assert notes == [
        "Hilltop Park (970-555-0100) lists no price; ask for check in Mon Nov 02, "
        "check out Tue Nov 03 (1 night), then propose it again."
    ]


def test_undated_days_are_refused():
    picks = [pick_night(night(), COLORADO, MINNIE, NEED, ConceptEmbedder())]
    with pytest.raises(ValueError, match="Day 1 has no date"):
        stays([night()], picks)


def test_campground_page_link_when_no_site_is_known():
    rec = camp("Ken's Lake", 39.40, -107.72, price=20).model_copy(
        update={"booking_url": "https://www.recreation.gov/camping/campgrounds/234567"}
    )
    day = dated(1, NOV_2)
    stay = stays([day], [pick_night(day, [rec], MINNIE, NEED, ConceptEmbedder())])[0]
    assert booking_link(stay) == (
        "https://www.recreation.gov/camping/campgrounds/234567"
        "?startDate=2026-11-02&endDate=2026-11-03"
    )
