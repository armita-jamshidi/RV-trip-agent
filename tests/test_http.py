import httpx
import pytest

from dave.http import CachedClient, OfflineCacheMiss


class FakeServer:
    """Answers with the queued status codes, then 200 forever, and counts calls."""

    def __init__(self, *statuses: int):
        self.statuses = list(statuses)
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        status = self.statuses.pop(0) if self.statuses else 200
        return httpx.Response(status, json={"q": request.url.params.get("q"), "status": status})


def client(tmp_path, server, **kwargs) -> CachedClient:
    return CachedClient(
        tmp_path, transport=httpx.MockTransport(server), sleep=lambda s: None, **kwargs
    )


def test_cached_calls_are_not_repeated(tmp_path):
    server = FakeServer()
    with client(tmp_path, server) as http:
        first = http.get("https://api.example.com/places", params={"q": "moab"})
        second = http.get("https://api.example.com/places", params={"q": "moab"})
    assert server.calls == 1
    assert first.json() == second.json() == {"q": "moab", "status": 200}


def test_different_params_are_cached_separately(tmp_path):
    server = FakeServer()
    with client(tmp_path, server) as http:
        http.get("https://api.example.com/places", params={"q": "moab"})
        http.get("https://api.example.com/places", params={"q": "denver"})
    assert server.calls == 2


def test_headers_do_not_change_cache_key(tmp_path):
    server = FakeServer()
    with client(tmp_path, server) as http:
        http.get("https://api.example.com/x", headers={"apikey": "one"})
        http.get("https://api.example.com/x", headers={"apikey": "two"})
    assert server.calls == 1


def test_retries_transient_errors(tmp_path):
    server = FakeServer(503, 429)
    with client(tmp_path, server, retries=3) as http:
        response = http.get("https://api.example.com/x")
    assert response.status_code == 200
    assert server.calls == 3


def test_gives_up_after_retries_and_does_not_cache_errors(tmp_path):
    server = FakeServer(500, 500, 500)
    with client(tmp_path, server, retries=2) as http:
        assert http.get("https://api.example.com/x").status_code == 500
        assert http.get("https://api.example.com/x").status_code == 200
    assert server.calls == 4


def test_offline_cache_miss_fails_loudly(tmp_path):
    server = FakeServer()
    with client(tmp_path, server, offline=True) as http:
        with pytest.raises(OfflineCacheMiss):
            http.get("https://api.example.com/x")
    assert server.calls == 0


def test_offline_serves_recorded_fixture(tmp_path):
    with client(tmp_path, FakeServer()) as http:
        http.get("https://api.example.com/x", params={"q": "zion"})
    with client(tmp_path, FakeServer(), offline=True) as http:
        assert http.get("https://api.example.com/x", params={"q": "zion"}).json()["q"] == "zion"


def test_rate_limit_waits_between_calls_to_same_host(tmp_path):
    waits = []
    http = CachedClient(
        tmp_path,
        transport=httpx.MockTransport(FakeServer()),
        min_interval=1.0,
        sleep=waits.append,
    )
    http.get("https://api.example.com/a")
    http.get("https://api.example.com/b")
    http.get("https://other.example.com/a")
    http.close()
    assert len(waits) == 1
    assert 0 < waits[0] <= 1.0
