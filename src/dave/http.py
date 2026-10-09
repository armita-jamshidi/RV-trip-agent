"""HTTP client with retries, per-host rate limiting and an on-disk response cache.

Every external call goes through `CachedClient` so reruns are cheap and tests are deterministic.
Tests point `cache_dir` at recorded fixtures and set `offline=True`, so a missing fixture fails
loudly instead of touching the network. To record fixtures, run once with `offline=False`.
"""

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import httpx

RETRY_STATUSES = {429, 500, 502, 503, 504}


class OfflineCacheMiss(RuntimeError):
    pass


class SourceError(RuntimeError):
    """An external data source answered with an error."""


def cache_key(method: str, url: str, params: dict | None = None, body: object = None) -> str:
    payload = json.dumps(
        {"method": method.upper(), "url": url, "params": params or {}, "body": body},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class CachedClient:
    def __init__(
        self,
        cache_dir: Path | str,
        *,
        offline: bool = False,
        timeout: float = 20.0,
        retries: int = 3,
        backoff: float = 1.0,
        min_interval: float = 0.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.offline = offline
        self.retries = retries
        self.backoff = backoff
        self.min_interval = min_interval
        self._sleep = sleep
        self._last_call: dict[str, float] = {}
        self._http = httpx.Client(timeout=timeout, transport=transport, follow_redirects=True)

    def get(
        self,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        secret_params: dict | None = None,
    ):
        return self.request("GET", url, params=params, headers=headers, secret_params=secret_params)

    def post(self, url: str, *, json_body: object = None, headers: dict | None = None):
        return self.request("POST", url, json_body=json_body, headers=headers)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json_body: object = None,
        headers: dict | None = None,
        secret_params: dict | None = None,
    ) -> httpx.Response:
        """Return a cached response when present; otherwise fetch, cache 2xx and return.

        Headers and `secret_params` (API keys a source wants in the query string) are not part
        of the cache key, so keys never affect it.
        """
        path = self.cache_dir / f"{cache_key(method, url, params, json_body)}.json"
        if path.exists():
            return _load(path, method, url)
        if self.offline:
            raise OfflineCacheMiss(f"No cached response for {method} {url} {params or ''}")

        query = {**(params or {}), **(secret_params or {})} or None
        response = self._fetch(method, url, params=query, json=json_body, headers=headers)
        if response.is_success:
            _store(path, response)
        return response

    def _fetch(self, method: str, url: str, **kwargs) -> httpx.Response:
        for attempt in range(self.retries + 1):
            self._wait_for_host(url)
            try:
                response = self._http.request(method, url, **kwargs)
            except httpx.TransportError:
                if attempt == self.retries:
                    raise
            else:
                if response.status_code not in RETRY_STATUSES or attempt == self.retries:
                    return response
            self._sleep(self.backoff * 2**attempt)
        raise AssertionError("unreachable")

    def _wait_for_host(self, url: str) -> None:
        host = urlsplit(url).netloc
        last = self._last_call.get(host)
        if last is not None and self.min_interval:
            wait = self.min_interval - (time.monotonic() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_call[host] = time.monotonic()

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "CachedClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _store(path: Path, response: httpx.Response) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "status": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "text": response.text,
    }
    path.write_text(json.dumps(record))


def _load(path: Path, method: str, url: str) -> httpx.Response:
    record = json.loads(path.read_text())
    return httpx.Response(
        record["status"],
        text=record["text"],
        headers={"content-type": record["content_type"]},
        request=httpx.Request(method, url),
    )
