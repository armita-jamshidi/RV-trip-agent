import json
from pathlib import Path

import httpx
import pytest

from dave.clearance import (
    CHUNK_POINTS,
    OVERPASS_URL,
    check,
    clear_route,
    parse_height,
    restrictions,
)
from dave.http import CachedClient
from dave.models import Place
from dave.routing import route

FIXTURES = Path(__file__).parent / "fixtures/clearance"
OSRM = json.loads((FIXTURES / "osrm_gregson_synthetic.json").read_text())
OVERPASS = json.loads((FIXTURES / "overpass_gregson_synthetic.json").read_text())
NORTH = Place(name="Brightleaf Square, Durham", lat=36.0010, lon=-78.9058)
SOUTH = Place(name="Gregson St south of the trestle", lat=35.9935, lon=-78.9062)


class Servers:
    """OSRM answers with the fixture's routes (alternatives only when asked); Overpass with
    the fixture's ways, or `overpass` when given."""

    def __init__(self, overpass=OVERPASS, detour=None):
        self.overpass, self.detour, self.osrm_calls, self.overpass_calls = overpass, detour, [], []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(OVERPASS_URL):
            self.overpass_calls.append(request.url.params["data"])
            return httpx.Response(200, json=self.overpass)
        self.osrm_calls.append(url)
        if url.count(";") == 2:  # start;detour;end
            if self.detour is None:
                return httpx.Response(400, json={"code": "NoRoute"})
            return httpx.Response(200, json={"code": "Ok", "routes": [self.detour]})
        wanted = OSRM["routes"] if "alternatives" in request.url.params else OSRM["routes"][:1]
        return httpx.Response(200, json={"code": "Ok", "routes": wanted})


def http(tmp_path, servers) -> CachedClient:
    return CachedClient(tmp_path, transport=httpx.MockTransport(servers), retries=0)


def test_12_ft_rv_is_rerouted_around_the_11foot8_bridge(tmp_path):
    result = clear_route(NORTH, SOUTH, 12.0, http(tmp_path, Servers()))
    assert result.rerouted and not result.too_low and result.warnings() == []
    assert result.route.miles == pytest.approx(1500 / 1609.344)  # the side-street alternative


def test_9_ft_van_keeps_the_direct_route(tmp_path):
    result = clear_route(NORTH, SOUTH, 9.0, http(tmp_path, Servers()))
    assert not result.rerouted and not result.too_low
    assert result.route.miles == pytest.approx(850 / 1609.344)


def test_margin_is_six_inches(tmp_path):
    direct = route([NORTH, SOUTH], http(tmp_path, Servers()))
    client = http(tmp_path, Servers())
    assert not check(direct, 11.8, client).too_low  # 12.3 ft needed, 12.33 ft available
    assert check(direct, 11.9, client).too_low


def test_crossing_road_limit_does_not_apply(tmp_path):
    direct = route([NORTH, SOUTH], http(tmp_path, Servers()))
    names = {r.name for r in restrictions(direct.geometry, http(tmp_path, Servers()))}
    assert names == {"South Gregson Street"}  # West Peabody St only crosses at one node


def test_no_way_around_keeps_the_warning(tmp_path):
    low_everywhere = {
        "elements": OVERPASS["elements"]
        + [
            {
                "type": "way",
                "id": 103,
                "tags": {"name": "Low underpass", "maxheight": "3.5"},
                "geometry": [{"lat": 36.0010, "lon": -78.9030}, {"lat": 36.0010, "lon": -78.9015}],
            }
        ]
    }
    servers = Servers(overpass=low_everywhere)
    result = clear_route(NORTH, SOUTH, 12.0, http(tmp_path, servers))
    assert not result.rerouted
    assert result.warnings() == ["South Gregson Street has 12.3 ft clearance, too low for this RV."]
    assert sum(c.count(";") == 2 for c in servers.osrm_calls) == 4  # tried a detour each way


def test_detour_waypoint_is_used_when_alternatives_fail(tmp_path):
    only_direct = {**OSRM, "routes": OSRM["routes"][:1]}
    detour = OSRM["routes"][1]

    class NoAlternatives(Servers):
        def __call__(self, request):
            if "alternatives" in request.url.params and not str(request.url).startswith(
                OVERPASS_URL
            ):
                self.osrm_calls.append(str(request.url))
                return httpx.Response(200, json=only_direct)
            return super().__call__(request)

    result = clear_route(NORTH, SOUTH, 12.0, http(tmp_path, NoAlternatives(detour=detour)))
    assert result.rerouted and result.route.miles == pytest.approx(1500 / 1609.344)


def test_propane_tunnel_is_flagged_not_blocking(tmp_path):
    tunnel = {
        "elements": [
            {
                "type": "way",
                "id": 201,
                "tags": {"name": "Harbor Tunnel", "tunnel": "yes", "hazmat": "no"},
                "geometry": [{"lat": 35.9990, "lon": -78.9059}, {"lat": 35.9975, "lon": -78.9060}],
            }
        ]
    }
    direct = route([NORTH, SOUTH], http(tmp_path, Servers()))
    result = check(direct, 13.0, http(tmp_path, Servers(overpass=tunnel)))
    assert not result.too_low and result.warnings() == []
    assert result.notes() == ["Harbor Tunnel restricts propane; check its rules or go around."]


def test_long_routes_are_queried_in_overlapping_chunks(tmp_path):
    line = [(36.0 + i * 0.001, -78.9) for i in range(150)]
    servers = Servers(overpass={"elements": []})
    restrictions(line, http(tmp_path, servers))
    assert len(servers.overpass_calls) == 2
    assert f"{line[CHUNK_POINTS - 1][0]:.5f}" in servers.overpass_calls[1]


@pytest.mark.parametrize(
    ("tag", "feet"),
    [
        ("12'4\"", 12.333),
        ("13'", 13.0),
        ("3.7", 12.139),
        ("3.7 m", 12.139),
        ("14 ft", 14.0),
        ("none", None),
        ("default", None),
    ],
)
def test_parse_height(tag, feet):
    assert parse_height(tag) == (pytest.approx(feet, abs=0.001) if feet else None)
