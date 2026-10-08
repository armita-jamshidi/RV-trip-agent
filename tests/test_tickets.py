import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from dave.booking import ApprovalRequired, book
from dave.days import split_days
from dave.http import CachedClient
from dave.models import BookingStatus, DayLeg, Interests, Place, Stop
from dave.pitstops import find_pitstops
from dave.routing import route
from dave.tickets import TICKETS, ticket_proposals

FIXTURES = Path(__file__).parent / "fixtures"
OSRM = json.loads((FIXTURES / "osrm_denver_moab_synthetic.json").read_text())
PLACES = json.loads((FIXTURES / "pitstops/foursquare_denver_moab_synthetic.json").read_text())
DENVER = Place(name="Denver, CO", lat=39.7392, lon=-104.9903)
MOAB = Place(name="Moab, UT", lat=38.5733, lon=-109.5498)
HIKER = Interests(nature=0.9, museums=0.1, largest_x=0.0, food=0.5)  # demo trip 1


def server(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=PLACES if request.url.path == "/places/search" else OSRM)


def demo_trip(tmp_path, start: date) -> list[DayLeg]:
    http = CachedClient(tmp_path, transport=httpx.MockTransport(server), sleep=lambda s: None)
    days = split_days(route([DENVER, MOAB], http), DENVER, MOAB, start_date=start)
    return find_pitstops(days, HIKER, http, "k")


def arches_day(day: date) -> DayLeg:
    arches = Stop(
        name="Arches National Park",
        location=Place(name="Arches", lat=38.7331, lon=-109.5925),
        category="National Park",
    )
    return DayLeg(day=1, travel_date=day, start=DENVER, end=MOAB, drive_hours=3, miles=150,
                  stops=[arches])  # fmt: skip


def test_denver_to_moab_in_november_proposes_the_two_park_passes(tmp_path):
    proposals = ticket_proposals(demo_trip(tmp_path, date(2026, 11, 2)))
    assert {(p.name, p.price_usd) for p in proposals} == {
        ("Arches National Park entrance, private vehicle", 30),
        ("Colorado National Monument entrance, private vehicle", 25),
    }
    for p in proposals:
        assert p.status is BookingStatus.PROPOSED
        assert p.start_date == date(2026, 11, 3)  # both are on day 2
        assert p.end_date == date(2026, 11, 9)  # 7-day pass
        assert p.url.startswith("https://www.nps.gov/")
    assert not any("timed-entry" in p.name for p in proposals)  # none required in 2026


def test_a_day_in_a_timed_entry_window_also_gets_the_reservation():
    proposals = ticket_proposals([arches_day(date(2025, 5, 10))])
    timed = [p for p in proposals if "timed-entry" in p.name]
    assert len(timed) == 1
    assert timed[0].price_usd == 2 and timed[0].start_date == date(2025, 5, 10)
    assert timed[0].url.startswith("https://www.recreation.gov/timed-entry/")
    # Between the two 2025 windows, and in 2026, no reservation is needed.
    for day in (date(2025, 7, 20), date(2026, 5, 10)):
        assert not any("timed-entry" in p.name for p in ticket_proposals([arches_day(day)]))


def test_one_annual_pass_replaces_separate_passes_that_cost_more():
    def site(name):
        return {"match": name, "name": f"{name} entrance", "price_usd": 30, "valid_days": 7,
                "url": "https://www.nps.gov/"}  # fmt: skip

    rules = {
        **json.loads(TICKETS.read_text()),
        "sites": [site(n) for n in ("Arches", "Zion", "Bryce")],
    }
    stops = [Stop(name=f"{n} National Park", location=MOAB, category="National Park")
             for n in ("Arches", "Zion", "Bryce")]  # fmt: skip
    days = [
        arches_day(date(2026, 11, 3 + i)).model_copy(update={"day": i + 1, "stops": [s]})
        for i, s in enumerate(stops)
    ]
    proposals = ticket_proposals(days, rules)  # 3 x $30 = $90 > $80
    assert len(proposals) == 1
    assert proposals[0].price_usd == 80 and "America the Beautiful" in proposals[0].name
    assert "Arches, Zion, Bryce" in proposals[0].name
    assert proposals[0].start_date == date(2026, 11, 3)


def test_stops_without_known_tickets_get_no_proposal_and_dates_are_required():
    museum = Stop(name="Museum of the West", location=MOAB, category="History Museum")
    day = arches_day(date(2026, 11, 3)).model_copy(update={"stops": [museum]})
    assert ticket_proposals([day]) == []
    with pytest.raises(ValueError, match="need trip dates"):
        ticket_proposals([arches_day(date(2026, 11, 3)).model_copy(update={"travel_date": None})])


def test_ticket_proposals_cannot_be_bought_without_approval(tmp_path):
    proposal = ticket_proposals(demo_trip(tmp_path, date(2026, 11, 2)))[0]
    with pytest.raises(ApprovalRequired):
        book(proposal, lambda p: pytest.fail("payment must not run"))
