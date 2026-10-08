import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from dave.models import (
    BookingProposal,
    BookingStatus,
    Campground,
    ConstraintSpec,
    CostBreakdown,
    DayLeg,
    FuelType,
    Hookup,
    Itinerary,
    Place,
    RVClass,
    RVProfile,
)

FIXTURE = Path(__file__).parent / "fixtures" / "constraint_spec_example.json"

DENVER = Place(name="Denver, CO", lat=39.74, lon=-104.99)
MOAB = Place(name="Moab, UT", lat=38.57, lon=-109.55)


def minnie_winnie() -> RVProfile:
    return RVProfile(
        make="Winnebago",
        model="Minnie Winnie 31K",
        year=2023,
        rv_class=RVClass.C,
        length_ft=32.9,
        height_ft=11.3,
        fuel_type=FuelType.GAS,
        mpg=10,
    )


def test_spec_example_validates():
    spec = ConstraintSpec.model_validate_json(FIXTURE.read_text())
    assert spec.rv.model == "Minnie Winnie 31K"
    assert spec.hookups_required == {Hookup.ELECTRIC, Hookup.WATER}
    assert spec.start_date == date(2026, 11, 2)


def test_spec_defaults_follow_domain_rules():
    spec = ConstraintSpec(origin="Austin, TX", destination="Nashville, TN", nights=5)
    assert spec.max_drive_hours_per_day == 5
    assert spec.hookups_required == {Hookup.ELECTRIC, Hookup.WATER}


def test_spec_rejects_unknown_fields():
    data = json.loads(FIXTURE.read_text()) | {"pets": 2}
    with pytest.raises(ValidationError):
        ConstraintSpec.model_validate(data)


@pytest.mark.parametrize("weight", [-0.1, 1.5])
def test_spec_rejects_out_of_range_interest(weight):
    data = json.loads(FIXTURE.read_text())
    data["interests"]["nature"] = weight
    with pytest.raises(ValidationError):
        ConstraintSpec.model_validate(data)


def test_rv_total_length_includes_tow():
    rv = minnie_winnie().model_copy(update={"tow_length_ft": 15})
    assert rv.total_length_ft == pytest.approx(47.9)


def test_costs_total_and_remaining():
    costs = CostBreakdown(fuel_usd=310.5, campgrounds_usd=240, tickets_usd=30, budget_usd=1500)
    assert costs.total_usd == 580.5
    assert costs.remaining_usd == 919.5
    assert CostBreakdown(fuel_usd=10).remaining_usd is None


def test_booking_starts_as_proposed():
    booking = BookingProposal(
        kind="campground", name="Sun Outdoors Arches", start_date=date(2026, 11, 2), price_usd=72
    )
    assert booking.status is BookingStatus.PROPOSED


def test_itinerary_json_round_trip():
    spec = ConstraintSpec.model_validate_json(FIXTURE.read_text())
    campground = Campground(
        name="Sun Outdoors Arches",
        location=MOAB,
        hookups={Hookup.ELECTRIC, Hookup.WATER, Hookup.SEWER},
        max_rv_length_ft=45,
        electrical_amps={30, 50},
        nightly_price_usd=72,
        source="ridb",
    )
    day = DayLeg(day=1, start=DENVER, end=MOAB, drive_hours=4.8, miles=352, campground=campground)
    itinerary = Itinerary(spec=spec, rv=minnie_winnie(), days=[day])
    assert Itinerary.model_validate_json(itinerary.model_dump_json()) == itinerary
