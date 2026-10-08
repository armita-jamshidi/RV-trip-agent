import json
from pathlib import Path

import httpx
import pytest

from dave.http import CachedClient
from dave.models import Place
from dave.routing import RoutingError, route

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/osrm_denver_moab_synthetic.json").read_text()
)
DENVER = Place(name="Denver, CO", lat=39.7392, lon=-104.9903)
GLENWOOD = Place(name="Glenwood Springs, CO", lat=39.5505, lon=-107.3248)
MOAB = Place(name="Moab, UT", lat=38.5733, lon=-109.5498)

# Published Denver → Moab drive: about 354 miles and 5 h 20 min by car.
KNOWN_MILES, KNOWN_CAR_HOURS = 354, 5.33


class OSRM:
    def __init__(self, body: dict, status: int = 200):
        self.body, self.status, self.requests = body, status, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=self.body)


def http(tmp_path, server) -> CachedClient:
    return CachedClient(tmp_path, transport=httpx.MockTransport(server), sleep=lambda s: None)


def test_denver_to_moab_within_10_percent_of_known(tmp_path):
    r = route([DENVER, MOAB], http(tmp_path, OSRM(FIXTURE)))
    assert r.miles == pytest.approx(KNOWN_MILES, rel=0.10)
    assert r.car_hours == pytest.approx(KNOWN_CAR_HOURS, rel=0.10)


def test_rv_drive_time_is_10_percent_slower(tmp_path):
    r = route([DENVER, MOAB], http(tmp_path, OSRM(FIXTURE)))
    assert r.drive_hours == pytest.approx(r.car_hours * 1.10)
    slow = route([DENVER, MOAB], http(tmp_path, OSRM(FIXTURE)), speed_factor=1.25)
    assert slow.drive_hours == pytest.approx(r.car_hours * 1.25)


def test_geometry_is_lat_lon_from_origin_to_destination(tmp_path):
    r = route([DENVER, MOAB], http(tmp_path, OSRM(FIXTURE)))
    assert r.geometry[0] == (39.7392, -104.9903)
    assert r.geometry[-1] == (38.5733, -109.5498)
    assert len(r.legs) == 1 and r.legs[0].miles == pytest.approx(r.miles)


def test_request_uses_lon_lat_order_and_full_geometry(tmp_path):
    server = OSRM(FIXTURE)
    route([DENVER, GLENWOOD, MOAB], http(tmp_path, server))
    url = server.requests[0].url
    assert url.path == ("/route/v1/driving/-104.9903,39.7392;-107.3248,39.5505;-109.5498,38.5733")
    assert url.params["overview"] == "full" and url.params["geometries"] == "geojson"


def test_repeat_route_is_served_from_cache(tmp_path):
    server = OSRM(FIXTURE)
    client = http(tmp_path, server)
    route([DENVER, MOAB], client)
    route([DENVER, MOAB], client)
    assert len(server.requests) == 1


def test_no_route_raises(tmp_path):
    server = OSRM({"code": "NoRoute", "message": "Impossible route between points"}, 400)
    with pytest.raises(RoutingError, match="Denver, CO → Moab, UT: Impossible route"):
        route([DENVER, MOAB], http(tmp_path, server))


def test_needs_two_points(tmp_path):
    with pytest.raises(ValueError):
        route([DENVER], http(tmp_path, OSRM(FIXTURE)))


def test_cli_route(monkeypatch, capsys, tmp_path):
    import dave.routing
    from dave.cli import main

    monkeypatch.setenv("DAVE_CACHE_DIR", str(tmp_path))
    real_route = dave.routing.route
    fake_osrm = http(tmp_path, OSRM(FIXTURE))
    monkeypatch.setattr(dave.routing, "route", lambda places, _: real_route(places, fake_osrm))
    assert main(["route", "39.7392,-104.9903", "38.5733,-109.5498"]) == 0
    assert capsys.readouterr().out == "354 miles, 5.3 h by car, 5.9 h by RV\n"
