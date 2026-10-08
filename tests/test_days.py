from datetime import date

import pytest

from dave.days import driving_days_needed, split_days
from dave.geo import cumulative_miles, haversine_miles
from dave.models import Place, Route, RouteLeg

DENVER = Place(name="Denver, CO", lat=39.7392, lon=-104.9903)
MOAB = Place(name="Moab, UT", lat=38.5733, lon=-109.5498)
LINE = [
    (39.7392, -104.9903), (39.7420, -105.5130), (39.6400, -106.3740), (39.5500, -107.3250),
    (39.0640, -108.5510), (38.9480, -109.8200), (38.5733, -109.5498),
]  # fmt: skip


def make_route(drive_hours: float, miles: float = 354, line=LINE) -> Route:
    return Route(
        miles=miles,
        car_hours=drive_hours / 1.1,
        drive_hours=drive_hours,
        legs=[RouteLeg(miles=miles, drive_hours=drive_hours)],
        geometry=line,
    )


def test_denver_to_moab_splits_into_two_balanced_days():
    days = split_days(make_route(5.9), DENVER, MOAB, start_date=date(2026, 11, 2))
    assert [d.day for d in days] == [1, 2]
    assert [d.drive_hours for d in days] == pytest.approx([2.95, 2.95])
    assert [d.travel_date for d in days] == [date(2026, 11, 2), date(2026, 11, 3)]
    assert days[0].start == DENVER and days[-1].end == MOAB
    assert days[0].end == days[1].start and days[0].end.name == "Overnight area 1"


def test_overnight_area_is_halfway_along_the_road():
    day1, day2 = split_days(make_route(5.9), DENVER, MOAB)
    assert cumulative_miles(day1.geometry)[-1] == pytest.approx(
        cumulative_miles(day2.geometry)[-1], rel=1e-3
    )
    assert day1.geometry[-1] == day2.geometry[0]


# Rough RV drive hours for the demo trips (demo/README.md), round trips included.
DEMO_TRIPS = {"Denver-Moab": 5.9, "Chicago-DC": 12.8, "Austin-Nashville": 14.3, "Seattle-YNP": 25.0}


@pytest.mark.parametrize("hours", [*DEMO_TRIPS.values(), 0.4, 4.99, 5.0, 5.01, 10.0, 47.3])
def test_every_day_is_at_most_five_hours_and_no_stubs(hours):
    days = split_days(make_route(hours), DENVER, MOAB)
    assert all(d.drive_hours <= 5.0 + 1e-9 for d in days)
    assert len(days) == driving_days_needed(make_route(hours))
    assert sum(d.drive_hours for d in days) == pytest.approx(hours)
    # Balanced: the shortest day is never a stub next to a long one.
    assert min(d.drive_hours for d in days) == pytest.approx(max(d.drive_hours for d in days))


def test_exactly_five_hours_is_one_day():
    assert driving_days_needed(make_route(5.0)) == 1
    assert driving_days_needed(make_route(5.0000000001)) == 1  # float noise, not a new day
    assert driving_days_needed(make_route(5.01)) == 2


def test_custom_daily_limit():
    assert len(split_days(make_route(5.9), DENVER, MOAB, max_hours=3)) == 2
    assert len(split_days(make_route(5.9), DENVER, MOAB, max_hours=2)) == 3


def test_days_cover_the_whole_line_in_order():
    days = split_days(make_route(25.0), DENVER, MOAB)
    assert days[0].geometry[0] == LINE[0] and days[-1].geometry[-1] == LINE[-1]
    walked = sum(cumulative_miles(d.geometry)[-1] for d in days)
    assert walked == pytest.approx(cumulative_miles(LINE)[-1], rel=1e-4)


def test_route_without_geometry_uses_straight_line():
    days = split_days(make_route(6.0, line=[]), DENVER, MOAB)
    assert len(days) == 2
    assert days[0].geometry[0] == (DENVER.lat, DENVER.lon)
    assert days[1].geometry[-1] == (MOAB.lat, MOAB.lon)


def test_haversine_known_distance():
    # Denver to Moab is about 250 miles as the crow flies.
    assert haversine_miles(LINE[0], LINE[-1]) == pytest.approx(250, rel=0.05)
