import asyncio
import json
from pathlib import Path

import httpx
import pytest

from dave.http import CachedClient
from dave.models import FuelType, RVClass, RVIdentity
from dave.rv_catalog import identify_rv
from dave.rv_specs import Specs, feet, lookup_rv, plausible, read_spec_table, spec_url
from dave.tools.rv import rv_dimensions_tool

FIXTURES = Path(__file__).parent / "fixtures/rv_specs"
# Pages recorded from www.winnebago.com on 2026-10-09 (current model year).
PAGES = {
    "https://www.winnebago.com/models/product/specifications/motorhomes/class-c/minnie-winnie": (
        FIXTURES / "winnebago_minnie_winnie.html"
    ),
    "https://www.winnebago.com/models/product/specifications/motorhomes/camper-van/revel": (
        FIXTURES / "winnebago_revel.html"
    ),
}


class Site:
    def __init__(self, pages=PAGES):
        self.pages, self.requests = pages, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        page = self.pages.get(str(request.url))
        return httpx.Response(200, text=page.read_text()) if page else httpx.Response(404)


def http(tmp_path, site=None) -> CachedClient:
    return CachedClient(tmp_path, transport=httpx.MockTransport(site or Site()), retries=0)


def rv(text: str) -> RVIdentity:
    return identify_rv(text).match


# Checked by hand against the same spec pages (Weights & Measurements, Chassis, Electrical).
def test_minnie_winnie_31k_from_spec_page(tmp_path):
    p = lookup_rv(rv("2023 Winnebago Minnie Winnie 31K"), http(tmp_path))
    assert (p.length_ft, p.height_ft, p.width_ft) == (32.75, 11.0, pytest.approx(8.458, abs=0.01))
    assert (p.gvwr_lbs, p.fuel_tank_gal, p.fuel_type, p.electrical_amps) == (
        14_500,
        55,
        FuelType.GAS,
        30,
    )
    assert p.model == "Minnie Winnie 31K" and p.year == 2023 and not p.estimated
    assert p.source_url.endswith("/class-c/minnie-winnie")


def test_revel_from_spec_page(tmp_path):
    p = lookup_rv(rv("Class B Winnebago Revel"), http(tmp_path))
    assert (p.length_ft, p.height_ft) == (pytest.approx(19.583, abs=0.01), 10.0)
    assert (p.gvwr_lbs, p.fuel_tank_gal, p.fuel_type, p.electrical_amps) == (
        9_050,
        24.5,
        FuelType.DIESEL,
        30,
    )
    assert not p.estimated


def test_no_floorplan_takes_the_largest(tmp_path):
    p = lookup_rv(rv("Winnebago Minnie Winnie"), http(tmp_path))
    assert p.length_ft == 32.75  # 31H and 31K, the longest of six floorplans


def test_floorplan_column_is_used():
    page = (FIXTURES / "winnebago_minnie_winnie.html").read_text()
    assert read_spec_table(page, "22R").length_ft == pytest.approx(23.833, abs=0.01)
    assert read_spec_table(page, "22 r").length_ft == pytest.approx(23.833, abs=0.01)


def test_unreachable_makes_get_flagged_class_estimates(tmp_path):
    site = Site()
    thor = lookup_rv(rv("Thor Four Winds 28A"), http(tmp_path, site))
    tiffin = lookup_rv(rv("Tiffin Allegro Red 38 KA"), http(tmp_path, site))
    assert thor.estimated and tiffin.estimated and site.requests == []
    assert thor.source_url is None
    assert (thor.height_ft, tiffin.height_ft) == (12, 13.5)  # high end of the class


def test_missing_page_falls_back_to_estimate(tmp_path):
    p = lookup_rv(rv("Winnebago Minnie Winnie 31K"), http(tmp_path, Site({})))
    assert p.estimated and p.source_url is None and p.rv_class == RVClass.C


def test_overrides_win_and_clear_the_estimate(tmp_path):
    p = lookup_rv(
        rv("Thor Four Winds 28A"),
        http(tmp_path),
        overrides={"length_ft": 29.9, "height_ft": 11.3, "electrical_amps": None},
    )
    assert (p.length_ft, p.height_ft) == (29.9, 11.3) and not p.estimated
    assert p.electrical_amps is None  # no estimate filled in once the real numbers are known


def test_implausible_numbers_are_dropped():
    specs = Specs(length_ft=327.5, height_ft=11, gvwr_lbs=145, width_ft=8.4, electrical_amps=20)
    kept = plausible(specs, RVClass.C)
    assert (kept.length_ft, kept.gvwr_lbs, kept.electrical_amps) == (None, None, None)
    assert (kept.height_ft, kept.width_ft) == (11, 8.4)


def test_page_without_table_goes_to_claude(tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<p>Exterior length 32 ft 9 in, height 11 ft</p>")
    url = spec_url(rv("Winnebago Minnie Winnie 31K"))

    class Claude:
        class messages:
            @staticmethod
            def parse(**kwargs):
                assert "Minnie Winnie 31K" in kwargs["messages"][0]["content"]
                specs = Specs(length_ft=32.75, height_ft=11, fuel_type=FuelType.GAS)
                return type("R", (), {"parsed_output": specs})

    client = http(tmp_path / "http", Site({url: page}))
    p = lookup_rv(rv("Winnebago Minnie Winnie 31K"), client, claude=Claude(), cache_dir=tmp_path)
    assert (p.length_ft, p.height_ft, p.estimated) == (32.75, 11, False)
    # Cached: a second lookup doesn't ask again.
    p2 = lookup_rv(rv("Winnebago Minnie Winnie 31K"), client, claude=None, cache_dir=tmp_path)
    assert p2.estimated  # without a Claude client the page is unreadable
    p3 = lookup_rv(rv("Winnebago Minnie Winnie 31K"), client, claude=object(), cache_dir=tmp_path)
    assert p3.length_ft == 32.75


def test_unknown_class_needs_asking(tmp_path):
    with pytest.raises(ValueError, match="RV class"):
        lookup_rv(rv("Wildwood 26DBUD"), http(tmp_path))


@pytest.mark.parametrize(
    ("text", "value"),
    [("32'9\"", 32.75), ("11'", 11.0), ("8'5.5\"", 8.458), ("19' 7\"", 19.583), ("tall", None)],
)
def test_feet(text, value):
    assert feet(text) == (pytest.approx(value, abs=0.001) if value else None)


def test_tool_returns_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("DAVE_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("DAVE_OFFLINE", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = asyncio.run(rv_dimensions_tool.handler({"text": "Tiffin Allegro Red 38 KA"}))
    profile = json.loads(out["content"][0]["text"])
    assert profile["model"] == "Allegro Red 38KA" and profile["estimated"] is True


def test_tool_asks_when_rv_is_ambiguous(tmp_path, monkeypatch):
    monkeypatch.setenv("DAVE_CACHE_DIR", str(tmp_path))
    out = asyncio.run(rv_dimensions_tool.handler({"text": "we have a Minnie"}))
    assert "Which RV" in out["content"][0]["text"]
