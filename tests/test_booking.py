from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from dave.booking import ApprovalRequired, approve, book
from dave.models import BookingProposal, BookingStatus
from dave.tools import allowed_tool_names

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)


def proposal(**changes) -> BookingProposal:
    terms = dict(
        kind="campground",
        name="Devils Garden Campground",
        start_date=date(2026, 11, 2),
        end_date=date(2026, 11, 4),
        price_usd=50,
        cancellation_policy="Full refund up to 2 days before arrival, minus a $10 fee",
        url="https://www.recreation.gov/camping/campgrounds/251535",
    )
    return BookingProposal(**{**terms, **changes})


class Booker:
    """Stands in for the code that reserves and pays; records whether it was ever called."""

    def __init__(self):
        self.calls: list[BookingProposal] = []

    def __call__(self, p: BookingProposal) -> str:
        self.calls.append(p)
        return "RES-123"


def test_unapproved_proposal_is_never_booked():
    booker = Booker()
    with pytest.raises(ApprovalRequired, match="not approved"):
        book(proposal(), booker)
    assert booker.calls == []


def test_approved_proposal_is_booked_once_with_the_approval_kept():
    approved = approve(proposal(), "Armita", now=NOW)
    assert approved.status is BookingStatus.APPROVED
    assert (approved.approved_by, approved.approved_at) == ("Armita", NOW)

    booker = Booker()
    booked = book(approved, booker)
    assert len(booker.calls) == 1
    assert booked.status is BookingStatus.BOOKED and booked.confirmation == "RES-123"
    assert booked.approved_by == "Armita"

    with pytest.raises(ApprovalRequired):  # already booked: not again
        book(booked, booker)
    assert len(booker.calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"price_usd": 95},
        {"end_date": date(2026, 11, 6)},
        {"url": "https://example.com/other-campground"},
        {"cancellation_policy": "No refunds"},
    ],
)
def test_changing_the_terms_after_approval_voids_it(change):
    approved = approve(proposal(), "Armita", now=NOW)
    changed = approved.model_copy(update=change)
    booker = Booker()
    with pytest.raises(ApprovalRequired, match="terms changed"):
        book(changed, booker)
    assert booker.calls == []


def test_approval_needs_a_person_and_a_fresh_proposal():
    with pytest.raises(ValueError, match="name of the person"):
        approve(proposal(), "  ")
    approved = approve(proposal(), "Armita", now=NOW)
    with pytest.raises(ValueError, match="Only a proposed booking"):
        approve(approved, "Someone else")


def test_an_approval_cannot_be_faked_by_setting_the_status():
    with pytest.raises(ValidationError, match="who approved it"):
        proposal(status=BookingStatus.APPROVED)
    with pytest.raises(ValidationError, match="who approved it"):
        proposal(status=BookingStatus.BOOKED, confirmation="RES-1")
    with pytest.raises(ValidationError, match="no approval"):
        proposal(approved_by="Armita")


def test_a_hand_built_approval_with_wrong_terms_is_refused():
    forged = proposal(
        status=BookingStatus.APPROVED,
        approved_by="Dave",
        approved_at=NOW,
        approved_terms="0" * 64,
    )
    booker = Booker()
    with pytest.raises(ApprovalRequired):
        book(forged, booker)
    assert booker.calls == []


def test_the_agent_has_no_tool_to_approve_book_or_pay():
    names = " ".join(allowed_tool_names()).lower()
    assert not any(word in names for word in ("approve", "book", "pay", "reserve"))
