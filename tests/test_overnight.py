import json
from pathlib import Path

import httpx
from conftest import ConceptEmbedder
from test_campgrounds import Sources

from dave.campgrounds import ingest
from dave.days import split_days
from dave.http import CachedClient
from dave.models import (
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
from dave.overnight import (
    campground_costs,
    overnight_centers,
    pick_campgrounds,
    pick_night,
    with_campgrounds,
)
from dave.routing import route
from dave.site_fit import Fit
from dave.validator import validate_itinerary

E, W = Hookup.ELECTRIC, Hookup.WATER
NEED = {E, W}
DENVER = Place(name="Denver, CO", lat=39.7392, lon=-104.9903)
MOAB = Place(name="Moab, UT", lat=38.5733, lon=-109.5498)
OSRM = json.loads((Path(__file__).parent / "fixtures/osrm_denver_moab_synthetic.json").read_text())

MINNIE = RVProfile(
    make="Winnebago",
    model="Minnie Winnie 31K",
    rv_class=RVClass.C,
    length_ft=32.75,
    height_ft=11,
    fuel_type=FuelType.GAS,
    electrical_amps=30,
)


def camp(name, lat, lon, description="", price=None, length=40.0, hookups=(E, W), rating=None):
    site = CampSite(name="1", hookups=set(hookups), max_rv_length_ft=length, electrical_amps={30})
    return Campground(
        name=name,
        location=Place(name=name, lat=lat, lon=lon),
        description=description,
        sites=[site],
        nightly_price_usd=price,
        rating=rating,
        source="ridb",
    )


def night(lat=39.3954, lon=-107.715, name="Overnight area 1") -> DayLeg:
    return DayLeg(
        day=1, start=DENVER, end=Place(name=name, lat=lat, lon=lon), drive_hours=3, miles=180
    )


# Synthetic pool near demo trip 1's first overnight area (between Glenwood Springs and Rifle).
# Hand-written, not recorded; real data comes from `campgrounds.ingest` once RIDB is reachable.
COLORADO = [
    camp("Rifle Falls", 39.675, -107.70, "Forest campground by the waterfall and creek.", 28),
    camp("Exit 90 RV Lot", 39.53, -107.78, "Gravel lot by the interstate.", 35),
    camp("Glenwood Canyon Resort", 39.56, -107.30, "Riverside sites in the canyon.", 95),
    camp("Harvey Gap", 39.61, -107.66, "Reservoir with mountain views.", 22, length=25),
    camp("Hilltop Park", 39.45, -107.60, "Quiet sites with views of the peaks.", None),
]


def test_scenic_cheap_and_close_wins_and_two_alternatives():
    pick = pick_night(night(), COLORADO, MINNIE, NEED, ConceptEmbedder())
    assert pick.pick.campground.name == "Rifle Falls"
    assert [c.campground.name for c in pick.alternatives] == [
        "Hilltop Park",
        "Glenwood Canyon Resort",
    ]
    assert "$28 a night" in pick.note and "86 min of extra driving" in pick.note


def test_too_short_and_too_far_are_left_out():
    pick = pick_night(night(), COLORADO, MINNIE, NEED, ConceptEmbedder(), radius_miles=20)
    names = {c.campground.name for c in [pick.pick, *pick.alternatives]}
    assert "Harvey Gap" not in names  # 25 ft sites, the RV is 32.75 ft
    assert "Glenwood Canyon Resort" not in names  # about 22 miles away


def test_price_cap_drops_expensive_campgrounds():
    pick = pick_night(
        night(), COLORADO, MINNIE, NEED, ConceptEmbedder(), radius_miles=40, max_nightly_usd=30
    )
    names = {c.campground.name for c in [pick.pick, *pick.alternatives]}
    assert names == {"Rifle Falls", "Hilltop Park"}  # unknown price kept, to confirm at booking


def test_known_fit_beats_a_prettier_call_to_confirm():
    rv_park = Campground(
        name="Lakeside Mountain Views RV",
        location=Place(name="x", lat=39.40, lon=-107.72),
        description="Lake and mountain views, sunset over the peaks.",
        rating=9.5,
        nightly_price_usd=10,
        source="foursquare",
    )
    plain = camp("Exit 90 RV Lot", 39.53, -107.78, "Gravel lot by the interstate.", 35)
    pick = pick_night(night(), [rv_park, plain], MINNIE, NEED, ConceptEmbedder())
    assert pick.pick.campground.name == "Exit 90 RV Lot"
    assert pick.alternatives[0].fit.fit is Fit.CONFIRM


def test_only_call_to_confirm_says_so():
    rv_park = Campground(name="Moab KOA", location=MOAB, source="foursquare")
    pick = pick_night(night(38.57, -109.55, "Moab, UT"), [rv_park], MINNIE, NEED, ConceptEmbedder())
    assert pick.note.startswith("Call to confirm Moab KOA: confirm electric and water hookups")


def test_nothing_nearby_explains_why():
    pick = pick_night(night(), [], MINNIE, NEED, ConceptEmbedder())
    assert pick.pick is None and pick.alternatives == []
    assert pick.note == (
        "No campground within 25 miles of Overnight area 1 fits the RV "
        "with electric, water hookups."
    )


def test_round_trip_needs_no_campground_on_the_last_night():
    days = [night(), night().model_copy(update={"day": 2, "end": DENVER})]
    picks = pick_campgrounds(days, COLORADO, MINNIE, NEED, ConceptEmbedder(), round_trip=True)
    assert [p.day for p in picks] == [1]


def test_demo_trip_1_gets_a_valid_campground_every_night(tmp_path):
    """Denver to Moab in a Minnie Winnie 31K: route, split into days, ingest, pick, validate."""
    osrm = CachedClient(
        tmp_path / "osrm", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=OSRM))
    )
    days = split_days(route([DENVER, MOAB], osrm), DENVER, MOAB)
    assert len(days) == 2

    sources = CachedClient(tmp_path / "camps", transport=httpx.MockTransport(Sources()))
    moab = ingest(overnight_centers(days)[1:], 30, sources, ridb_key="r", foursquare_key="f")
    picks = pick_campgrounds(days, COLORADO + moab, MINNIE, NEED, ConceptEmbedder())

    assert [p.pick.campground.name for p in picks] == [
        "Rifle Falls",
        "Devils Garden Campground (Arches)",
    ]
    assert all(p.pick.fit.fit is Fit.YES for p in picks)
    assert campground_costs(picks) == 28 + 25

    itinerary = Itinerary(
        spec=ConstraintSpec(origin="Denver, CO", destination="Moab, UT", nights=2),
        rv=MINNIE,
        days=with_campgrounds(days, picks),
        costs=CostBreakdown(campgrounds_usd=campground_costs(picks)),
    )
    assert [d.campground.name for d in itinerary.days] == [
        "Rifle Falls",
        "Devils Garden Campground (Arches)",
    ]
    assert validate_itinerary(itinerary) == []
