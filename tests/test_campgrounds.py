import json
from pathlib import Path

import httpx
import pytest

from dave import cli
from dave.campgrounds import (
    DEMO_REGIONS,
    SourceError,
    foursquare_campgrounds,
    ingest,
    merge,
    parse_site,
    ridb_campgrounds,
)
from dave.http import CachedClient
from dave.models import Campground, Hookup, Place

FIXTURES = Path(__file__).parent / "fixtures" / "campgrounds"
MOAB = (38.5733, -109.5498)


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class Sources:
    """Serves the synthetic fixtures by path, like RIDB and Foursquare would."""

    def __init__(self, ridb_pages: dict | None = None):
        self.requests: list[httpx.Request] = []
        self.ridb_pages = ridb_pages or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path in self.ridb_pages:
            offset = int(request.url.params["offset"])
            return httpx.Response(200, json=self.ridb_pages[path][offset])
        if path == "/api/v1/facilities":
            return httpx.Response(200, json=load("ridb_facilities_moab_synthetic.json"))
        if path.startswith("/api/v1/facilities/"):
            fid = path.split("/")[4]
            return httpx.Response(200, json=load(f"ridb_campsites_{fid}_synthetic.json"))
        if path == "/places/search":
            return httpx.Response(200, json=load("foursquare_moab_synthetic.json"))
        return httpx.Response(404, json={})


def client(tmp_path, server) -> CachedClient:
    return CachedClient(tmp_path, transport=httpx.MockTransport(server), sleep=lambda s: None)


def by_name(campgrounds):
    return {c.name: c for c in campgrounds}


def test_ridb_keeps_campgrounds_with_rv_sites_and_their_hookups(tmp_path):
    found = by_name(ridb_campgrounds(MOAB, 50, client(tmp_path, Sources()), "key"))
    assert set(found) == {"Devils Garden Campground (Arches)", "Ken's Lake Campground"}

    devils = found["Devils Garden Campground (Arches)"]
    assert [s.name for s in devils.sites] == ["001", "002"]  # tent-only site dropped
    assert devils.sites[0].hookups == set() and devils.sites[0].max_rv_length_ft == 30
    assert devils.sites[1].hookups == {Hookup.ELECTRIC, Hookup.WATER}
    assert devils.sites[1].electrical_amps == {30, 50}
    assert devils.sites[1].max_rv_length_ft == 40  # longest RV-type equipment
    assert devils.hookups == {Hookup.ELECTRIC, Hookup.WATER}
    assert devils.max_rv_length_ft == 40
    assert devils.nightly_price_usd == 25
    assert devils.description.startswith("Overview Devils Garden sits among red rock fins")
    assert "desert views & trailheads" in devils.description
    assert devils.booking_url == "https://www.recreation.gov/camping/campgrounds/251535"
    assert devils.source == "ridb"

    kens = found["Ken's Lake Campground"]
    assert kens.hookups == set(Hookup)  # "Full Hookup"
    assert kens.max_rv_length_ft == 45  # from the attribute when equipment has no length
    assert kens.booking_url is None  # first come, first served


def test_ridb_sends_key_as_header_and_search_area(tmp_path):
    server = Sources()
    ridb_campgrounds(MOAB, 50, client(tmp_path, server), "secret")
    first = server.requests[0]
    assert first.headers["apikey"] == "secret"
    assert "secret" not in str(first.url)
    assert first.url.params["latitude"] == "38.5733" and first.url.params["radius"] == "50"


def test_ridb_follows_pages(tmp_path):
    facility = load("ridb_facilities_moab_synthetic.json")["RECDATA"][1]
    pages = {
        "/api/v1/facilities": {
            0: {"RECDATA": [facility], "METADATA": {"RESULTS": {"TOTAL_COUNT": 2}}},
            1: {
                "RECDATA": [{**facility, "FacilityID": "251535", "FacilityName": "Second"}],
                "METADATA": {"RESULTS": {"TOTAL_COUNT": 2}},
            },
        }
    }
    found = ridb_campgrounds(MOAB, 50, client(tmp_path, Sources(pages)), "key")
    assert [c.name for c in found] == ["Ken's Lake Campground", "Second"]


def test_ridb_error_is_reported(tmp_path):
    server = lambda request: httpx.Response(401, json={})  # noqa: E731
    with pytest.raises(SourceError, match="401"):
        ridb_campgrounds(MOAB, 50, client(tmp_path, server), "bad")


def test_parse_site_reads_amps_and_type_hints():
    site = parse_site(
        {
            "CampsiteName": "B4",
            "CampsiteType": "STANDARD ELECTRIC",
            "ATTRIBUTES": [{"AttributeName": "Sewer Hookup", "AttributeValue": "Yes"}],
            "PERMITTEDEQUIPMENT": [{"EquipmentName": "Caravan/Camper Van", "MaxLength": 22}],
        }
    )
    assert site.hookups == {Hookup.ELECTRIC, Hookup.SEWER}
    assert site.electrical_amps == set() and site.max_rv_length_ft == 22


def test_foursquare_rv_parks_with_free_fields_only(tmp_path):
    server = Sources()
    found = foursquare_campgrounds(MOAB, 50, client(tmp_path, server), "fsq-key")
    gateway = by_name(found)["Sun Outdoors Arches Gateway"]
    assert gateway.location.address == "1621 N Hwy 191, Moab, UT 84532"
    assert gateway.source == "foursquare" and gateway.rating is None and not gateway.hookups

    request = server.requests[0]
    assert request.headers["Authorization"] == "Bearer fsq-key"
    assert request.url.params["radius"] == str(round(50 * 1609.344))
    assert "rating" not in request.url.params["fields"]  # rating is a paid field


def test_foursquare_radius_is_capped(tmp_path):
    server = Sources()
    foursquare_campgrounds(MOAB, 500, client(tmp_path, server), "k")
    assert server.requests[0].url.params["radius"] == "100000"


def test_merge_prefers_ridb_and_matches_names_nearby():
    def camp(name, lat, lon, source):
        return Campground(name=name, location=Place(name=name, lat=lat, lon=lon), source=source)

    fsq_devils = camp("Devils Garden Campground", 38.7790, -109.5880, "foursquare")
    ridb_devils = camp("Devils Garden Campground (Arches)", 38.7783, -109.5874, "ridb")
    gateway = camp("Sun Outdoors Arches Gateway", 38.6248, -109.6006, "foursquare")
    # Different names 0.3 mi apart stay separate; same spot under 0.1 mi always merges.
    neighbor = camp("Moab KOA", 38.6290, -109.6006, "foursquare")
    same_spot = camp("Arches Gateway RV", 38.6250, -109.6005, "foursquare")

    kept = merge([fsq_devils, gateway, ridb_devils, neighbor, same_spot])
    assert [c.name for c in kept] == [
        "Devils Garden Campground (Arches)",
        "Sun Outdoors Arches Gateway",
        "Moab KOA",
    ]


def test_ingest_merges_sources_and_overlapping_areas(tmp_path):
    http = client(tmp_path, Sources())
    found = ingest([MOAB, (38.58, -109.55)], 50, http, ridb_key="r", foursquare_key="f")
    assert sorted(c.name for c in found) == [
        "Devils Garden Campground (Arches)",
        "Ken's Lake Campground",
        "Sun Outdoors Arches Gateway",
    ]


def test_demo_regions_cover_the_four_demo_trips():
    regions = json.loads(DEMO_REGIONS.read_text())
    assert sorted(r["trip"] for r in regions) == [1, 2, 3, 4]


def test_cli_writes_jsonl(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RIDB_API_KEY", "r")
    monkeypatch.setenv("FOURSQUARE_API_KEY", "f")
    monkeypatch.setenv("DAVE_CACHE_DIR", str(tmp_path / "cache"))
    original = CachedClient.__init__

    def mocked(self, cache_dir, **kwargs):
        original(self, cache_dir, transport=httpx.MockTransport(Sources()), sleep=lambda s: None)

    monkeypatch.setattr(CachedClient, "__init__", mocked)
    out = tmp_path / "camps.jsonl"
    assert cli.main(["campgrounds", "38.5733,-109.5498", "--out", str(out)]) == 0
    lines = out.read_text().splitlines()
    assert len(lines) == 3
    assert Campground.model_validate_json(lines[0]).source == "ridb"
    assert "3 campgrounds (2 with hookups, 2 with RV length)" in capsys.readouterr().out


def test_cli_needs_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("RIDB_API_KEY", raising=False)
    monkeypatch.setenv("DAVE_CACHE_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # no .env here
    with pytest.raises(Exception, match="RIDB_API_KEY is not set"):
        cli.main(["campgrounds", "--demo"])
