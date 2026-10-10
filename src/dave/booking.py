"""The approval gate: Dave prepares bookings, a person approves each one, only then is it booked.

- `approve` records who approved, when, and a digest of the exact terms they saw (what, dates,
  price, cancellation policy, link). Changing any of those afterwards voids the approval.
- `book` refuses anything that isn't approved with matching terms, and only then calls the
  `booker` that actually reserves and pays. No booker exists in this repo yet; whoever adds
  one passes it in here, so every payment goes through this check.

The agent gets no tool for `approve` or `book`: approval comes from a person, outside the model.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime

from dave.models import BookingProposal, BookingStatus

TERMS = ("kind", "name", "start_date", "end_date", "price_usd", "cancellation_policy", "url")

Booker = Callable[[BookingProposal], str]  # reserves and pays; returns the confirmation number


class ApprovalRequired(PermissionError):
    """Raised instead of booking anything a person has not approved as-is."""


def terms_digest(proposal: BookingProposal) -> str:
    terms = proposal.model_dump(mode="json", include=set(TERMS))
    return hashlib.sha256(json.dumps(terms, sort_keys=True).encode()).hexdigest()


def approve(
    proposal: BookingProposal, approved_by: str, *, now: datetime | None = None
) -> BookingProposal:
    """Record a person's OK for this exact booking."""
    if proposal.status is not BookingStatus.PROPOSED:
        raise ValueError(f"Only a proposed booking can be approved; this one is {proposal.status}.")
    if not approved_by.strip():
        raise ValueError("An approval needs the name of the person approving.")
    return _with(
        proposal,
        status=BookingStatus.APPROVED,
        approved_by=approved_by.strip(),
        approved_at=now or datetime.now(UTC),
        approved_terms=terms_digest(proposal),
    )


def require_approval(proposal: BookingProposal) -> None:
    """Raise unless a person approved this proposal with exactly these terms."""
    if proposal.status is not BookingStatus.APPROVED:
        raise ApprovalRequired(f"{proposal.name}: {proposal.status}, not approved; nothing booked.")
    if proposal.approved_terms != terms_digest(proposal):
        raise ApprovalRequired(
            f"{proposal.name}: the terms changed after approval; ask again before booking."
        )


def book(proposal: BookingProposal, booker: Booker) -> BookingProposal:
    """Book an approved proposal. Anything else raises before `booker` is called."""
    require_approval(proposal)
    confirmation = booker(proposal)
    return _with(proposal, status=BookingStatus.BOOKED, confirmation=confirmation)


def _with(proposal: BookingProposal, **changes) -> BookingProposal:
    """A changed copy, validated again (`model_copy` would skip the model's approval checks)."""
    return BookingProposal.model_validate({**proposal.model_dump(), **changes})
