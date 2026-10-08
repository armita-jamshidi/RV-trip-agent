import asyncio
import json

import pytest

from dave.models import RVClass
from dave.rv_catalog import CATALOG, identify_rv
from dave.tools.rv import identify_rv_tool

A, B, C = RVClass.A, RVClass.B, RVClass.C
TT, FW = RVClass.TRAVEL_TRAILER, RVClass.FIFTH_WHEEL

# (phrasing, (make, model, floorplan, year, class))
MATCHES = [
    ("our 2023 Minnie Winnie 31", ("Winnebago", "Minnie Winnie", "31", 2023, C)),
    ("Thor Four Winds 28A, family of four", ("Thor Motor Coach", "Four Winds", "28A", None, C)),
    ("Class B Winnebago Revel. Austin to Nashville", ("Winnebago", "Revel", None, None, B)),
    ("Tiffin Allegro Red 38 KA towing a Jeep", ("Tiffin", "Allegro Red", "38KA", None, A)),
    ("2019 jayco greyhawk 29mv", ("Jayco", "Greyhawk", "29MV", 2019, C)),
    ("Airstream Classic 33 behind a pickup", ("Airstream", "Classic", "33", None, TT)),
    ("'21 Coachmen Leprechaun 311FS", ("Coachmen", "Leprechaun", "311FS", 2021, C)),
    ("Keystone Cougar 29BHS travel trailer", ("Keystone", "Cougar", "29BHS", None, TT)),
    (
        "our Grand Design Solitude 310GK fifth wheel",
        ("Grand Design", "Solitude", "310GK", None, FW),
    ),
    ("Forest River Sunseeker 2850S", ("Forest River", "Sunseeker", "2850S", None, C)),
    ("a 2022 Micro Minnie 2108DS", ("Winnebago", "Micro Minnie", "2108DS", 2022, TT)),
    ("Wildwood 26DBUD, no make given", ("Forest River", "Wildwood", "26DBUD", None, None)),
    ("Winnebago Revel 10 nights out west", ("Winnebago", "Revel", None, None, B)),
]

# (phrasing, expected candidate models)
SHORT_LISTS = [
    ("we have a Minnie", {"Minnie Winnie", "Micro Minnie"}),
    ("a Thor class C", {"Four Winds", "Chateau", "Freedom Elite", "Quantum"}),
    ("Jayco fifth wheel", {"North Point", "Eagle"}),
]

NO_MATCH = [
    "Newmar Dutch Star 4369",  # not in the catalog
    "we love big views, no interstates, and a classic diner",  # everyday words, no make
]


@pytest.mark.parametrize("text, expected", MATCHES)
def test_resolves_to_one_rv(text, expected):
    match = identify_rv(text).match
    assert match is not None
    assert (match.make, match.model, match.floorplan, match.year, match.rv_class) == expected


@pytest.mark.parametrize("text, models", SHORT_LISTS)
def test_ambiguous_text_gives_short_list(text, models):
    result = identify_rv(text)
    assert result.match is None
    assert {c.model for c in result.candidates} == models


@pytest.mark.parametrize("text", NO_MATCH)
def test_unknown_or_generic_text_matches_nothing(text):
    result = identify_rv(text)
    assert result.match is None and result.candidates == []


def test_at_least_15_phrasings():
    assert len(MATCHES) + len(SHORT_LISTS) >= 15


def test_catalog_covers_required_manufacturers():
    required = {"Winnebago", "Thor Motor Coach", "Forest River", "Jayco", "Tiffin", "Airstream"}
    required |= {"Coachmen", "Keystone", "Grand Design"}
    assert {m.name for m in CATALOG} == required
    assert all(m.site.startswith("https://") for m in CATALOG)


def test_tool_returns_json():
    result = asyncio.run(identify_rv_tool.handler({"text": "2023 Minnie Winnie 31K"}))
    data = json.loads(result["content"][0]["text"])
    assert data["match"]["model"] == "Minnie Winnie"
    assert data["match"]["floorplan"] == "31K"
