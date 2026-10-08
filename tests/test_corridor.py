import json
import math
from pathlib import Path

import pytest

from dave.corridor import (
    DEFAULT_BUFFER_MILES,
    along_route,
    detour_minutes,
    locate,
    query_radius_miles,
    search_points,
)
from dave.geo import haversine_miles
from dave.models import Place, Stop

FIXTURE = Path(__file__).parent / "fixtures" / "osrm_denver_moab_synthetic.json"
DENVER_MOAB = [
    (lat, lon)
    for lon, lat in json.loads(FIXTURE.read_text())["routes"][0]["geometry"]["coordinates"]
]

# A straight east-west line along 39°N, about 108 miles long.
LINE = [(39.0, -105.0), (39.0, -104.0), (39.0, -103.0)]
MILES_PER_DEG_LAT = 69.09


def north_of(point, miles):
    return (point[0] + miles / MILES_PER_DEG_LAT, point[1])


def stop(name, point):
    return Stop(
        name=name,
        location=Place(name=name, lat=point[0], lon=point[1]),
        category="Landmarks and Outdoors > Park",
    )


def test_locate_on_the_line():
    along, off = locate((39.0, -104.0), LINE)
    assert off == pytest.approx(0, abs=1e-6)
    assert along == pytest.approx(haversine_miles(LINE[0], LINE[1]), rel=1e-3)


def test_locate_beside_the_line():
    along, off = locate(north_of((39.0, -104.5), 10), LINE)
    assert off == pytest.approx(10, rel=0.01)
    assert along == pytest.approx(haversine_miles(LINE[0], (39.0, -104.5)), rel=0.01)


def test_locate_past_the_end_measures_to_the_endpoint():
    along, off = locate((39.0, -102.9), LINE)
    assert along == pytest.approx(haversine_miles(LINE[0], LINE[-1]), rel=1e-3)
    assert off == pytest.approx(haversine_miles((39.0, -102.9), LINE[-1]), rel=0.01)


def test_detour_is_there_and_back_on_slow_roads():
    assert detour_minutes(0) == 0
    # 10 mi off route = 20 mi straight line, 26 mi of road at 35 mph.
    assert detour_minutes(10) == pytest.approx(26 / 35 * 60)


def test_corridor_keeps_nearby_places_with_detours_and_drops_far_ones():
    near = stop("Near", north_of((39.0, -104.2), 2))
    edge = stop("Edge", north_of((39.0, -104.8), 14))
    far = stop("Far", north_of((39.0, -103.5), 40))
    behind = stop("Behind start", (39.0, -105.5))  # 27 mi west of the start
    hits = along_route([near, edge, far, behind], LINE, lambda s: (s.location.lat, s.location.lon))

    assert [h.item.name for h in hits] == ["Edge", "Near"]  # trip order, not input order
    by_name = {h.item.name: h for h in hits}
    assert by_name["Near"].off_route_miles == pytest.approx(2, rel=0.01)
    assert by_name["Near"].detour_minutes == pytest.approx(detour_minutes(2), rel=0.01)
    assert by_name["Edge"].detour_minutes > by_name["Near"].detour_minutes


def test_buffer_width_is_configurable():
    place = north_of((39.0, -104.0), 8)
    assert along_route([place], LINE, lambda p: p, buffer_miles=10)
    assert not along_route([place], LINE, lambda p: p, buffer_miles=5)


def test_search_points_cover_the_whole_corridor():
    centers = search_points(DENVER_MOAB)
    assert centers[0] == pytest.approx(DENVER_MOAB[0])
    assert centers[-1] == pytest.approx(DENVER_MOAB[-1])
    radius = query_radius_miles()
    # Every route vertex, and points pushed to the edge of the band, fall in some query circle.
    for p in DENVER_MOAB:
        for q in (p, north_of(p, DEFAULT_BUFFER_MILES * 0.99)):
            assert min(haversine_miles(q, c) for c in centers) <= radius


def test_search_points_spacing_follows_buffer():
    total = haversine_miles(LINE[0], LINE[1]) + haversine_miles(LINE[1], LINE[2])
    centers = search_points(LINE, buffer_miles=20)
    assert len(centers) == math.ceil(total / 20) + 1
    gaps = [haversine_miles(a, b) for a, b in zip(centers, centers[1:], strict=False)]
    assert max(gaps) <= 20


def test_degenerate_lines():
    assert search_points([]) == []
    assert search_points([(39.0, -105.0)]) == [(39.0, -105.0)]
    assert locate(north_of((39.0, -105.0), 3), [(39.0, -105.0)]) == (
        0.0,
        pytest.approx(3, rel=0.01),
    )
