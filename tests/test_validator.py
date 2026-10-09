from datetime import UTC, date, datetime

import pytest

from dave.booking import approve
from dave.models import (
    BookingProposal,
    Campground,
    CampSite,
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
from dave.validator import validate_itinerary

MOAB = Place(name="Moab, UT", lat=38.57, lon=-109.55)
GREEN_RIVER = Place(name="Green River, UT", lat=38.99, lon=-110.16)
FULL = {Hookup.ELECTRIC, Hookup.WATER, Hookup.SEWER}


def campground(**changes) -> Campground:
    fields = dict(
        name="Green River State Park",
        location=GREEN_RIVER,
        hookups=FULL,
        max_rv_length_ft=40,
        electrical_amps={30, 50},
        nightly_price_usd=45,
        source="ridb",
    )
    return Campground(**{**fields, **changes})


def day(n: int = 1, **changes) -> DayLeg:
    fields = dict(
        day=n, start=MOAB, end=GREEN_RIVER, drive_hours=4.5, miles=200, campground=campground()
    )
    return DayLeg(**{**fields, **changes})


def plan(*, spec: dict | None = None, rv: dict | None = None, **changes) -> Itinerary:
    rv_fields = dict(
        make="Winnebago", model="Minnie Winnie 26T", rv_class=RVClass.C, length_ft=27.5,
        height_ft=11.2, fuel_type=FuelType.GAS, electrical_amps=30,
    )  # fmt: skip
    fields = dict(
        spec=ConstraintSpec(**{"origin": "Moab, UT", "destination": "Green River, UT",
                               "nights": 2, "budget_usd": 1000, **(spec or {})}),
        rv=RVProfile(**{**rv_fields, **(rv or {})}),
        days=[day(1), day(2, drive_hours=0, miles=0)],
        costs=CostBreakdown(fuel_usd=120, campgrounds_usd=90),
    )  # fmt: skip
    return Itinerary(**{**fields, **changes})


def booking(**changes) -> BookingProposal:
    fields = dict(kind="campground", name="Green River State Park", start_date=date(2026, 11, 2),
                  price_usd=45)  # fmt: skip
    return BookingProposal(**{**fields, **changes})


def test_a_plan_that_obeys_every_rule_passes():
    assert validate_itinerary(plan(bookings=[booking()])) == []


def test_low_clearance_on_the_route_fails():
    bad = plan(days=[day(1, clearance_warnings=["I-70 overpass at mile 182 is 11 ft 6 in"])])
    assert validate_itinerary(bad) == ["Day 1: I-70 overpass at mile 182 is 11 ft 6 in"]


def test_more_than_the_daily_driving_limit_fails():
    (error,) = validate_itinerary(plan(days=[day(1, drive_hours=5.4)]))
    assert error.startswith("Day 1: 5.4 h of driving is over the 5 h limit")


def test_daily_limit_follows_the_travelers_own_limit():
    assert (
        validate_itinerary(
            plan(days=[day(1, drive_hours=5.4)], spec={"max_drive_hours_per_day": 6})
        )
        == []
    )
    assert validate_itinerary(plan(days=[day(1, drive_hours=5.0)])) == []


def test_a_night_without_a_campground_fails():
    assert validate_itinerary(plan(days=[day(1, campground=None)])) == [
        "Day 1: no campground for the night."
    ]


def test_last_day_of_a_round_trip_ends_at_home():
    days = [day(1), day(2, campground=None)]
    assert validate_itinerary(plan(days=days, spec={"round_trip": True})) == []
    assert validate_itinerary(plan(days=days)) == ["Day 2: no campground for the night."]


def test_missing_hookups_fail():
    (error,) = validate_itinerary(
        plan(days=[day(1, campground=campground(hookups={Hookup.ELECTRIC}))])
    )
    assert error == "Day 1: Green River State Park: no site fits: no water hookup."


def test_rv_longer_than_the_site_fails():
    errors = validate_itinerary(plan(rv={"length_ft": 38, "tow_length_ft": 15}))
    assert [e[:6] for e in errors] == ["Day 1:", "Day 2:"]
    assert "sites fit 40 ft, the RV is 53 ft" in errors[0]


def test_unknown_site_length_is_not_assumed_to_fit():
    (error,) = validate_itinerary(plan(days=[day(1, campground=campground(max_rv_length_ft=None))]))
    assert error.endswith("no site fits: site length unknown.")


def test_wrong_amperage_fails_only_when_both_are_known():
    fifty_only = campground(electrical_amps={50})
    assert "no 30A power" in validate_itinerary(plan(days=[day(1, campground=fifty_only)]))[0]
    assert (
        validate_itinerary(plan(days=[day(1, campground=fifty_only)], rv={"electrical_amps": None}))
        == []
    )


def test_one_fitting_site_is_enough():
    sites = [
        CampSite(name="Loop A 3", hookups={Hookup.ELECTRIC}, max_rv_length_ft=60),
        CampSite(name="Loop B 12", hookups=FULL, max_rv_length_ft=25),
        CampSite(name="Loop B 14", hookups=FULL, max_rv_length_ft=35),
    ]
    assert validate_itinerary(plan(days=[day(1, campground=campground(sites=sites))])) == []
    (error,) = validate_itinerary(plan(days=[day(1, campground=campground(sites=sites[:2]))]))
    assert error.endswith("no site fits: no water hookup; sites fit 25 ft, the RV is 27.5 ft.")


def test_over_budget_fails():
    (error,) = validate_itinerary(plan(costs=CostBreakdown(fuel_usd=800, campgrounds_usd=300)))
    assert error == "Costs of $1,100.00 are over the $1,000.00 budget by $100.00."


def test_no_budget_means_no_budget_rule():
    assert (
        validate_itinerary(plan(spec={"budget_usd": None}, costs=CostBreakdown(fuel_usd=5000)))
        == []
    )


@pytest.mark.parametrize("approved", [True, False])
def test_booking_changed_after_approval_fails(approved):
    ok = approve(booking(), "Armita", now=datetime(2026, 10, 9, tzinfo=UTC))
    changed = ok.model_copy(update={"price_usd": 90}) if not approved else ok
    errors = validate_itinerary(plan(bookings=[changed]))
    if approved:
        assert errors == []
    else:
        assert errors == [
            "Booking Green River State Park: approved but its terms changed after approval; "
            "set it back to proposed and ask again."
        ]


def test_every_broken_rule_is_reported():
    bad = plan(
        days=[day(1, drive_hours=7, clearance_warnings=["low bridge"], campground=None)],
        costs=CostBreakdown(fuel_usd=2000),
    )
    assert len(validate_itinerary(bad)) == 4
