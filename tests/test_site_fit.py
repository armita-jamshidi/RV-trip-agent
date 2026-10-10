from dave.models import Campground, CampSite, FuelType, Hookup, Place, RVClass, RVProfile
from dave.site_fit import Fit, check_campground, filter_campgrounds

E, W, S = Hookup.ELECTRIC, Hookup.WATER, Hookup.SEWER
NEED = {E, W}
HERE = Place(name="Moab, UT", lat=38.57, lon=-109.55)


def rv(length=32.75, amps=30, tow=0.0) -> RVProfile:
    return RVProfile(
        make="Winnebago",
        model="Minnie Winnie 31K",
        rv_class=RVClass.C,
        length_ft=length,
        height_ft=11,
        fuel_type=FuelType.GAS,
        electrical_amps=amps,
        tow_length_ft=tow,
    )


def ridb(*sites: CampSite, name="Ken's Lake") -> Campground:
    return Campground(name=name, location=HERE, sites=list(sites), source="ridb")


def site(name="A1", hookups=(E, W), length=40.0, amps=(30,)) -> CampSite:
    return CampSite(
        name=name, hookups=set(hookups), max_rv_length_ft=length, electrical_amps=set(amps)
    )


def test_site_with_hookups_and_room_fits():
    result = check_campground(ridb(site()), rv(), NEED)
    assert result.fit is Fit.YES and result.sites == ("A1",)
    assert result.reason == "fits 32.75 ft with electric, water"


def test_one_fitting_site_is_enough():
    camp = ridb(site("A1", hookups=(E,)), site("B2", length=25), site("C3"), site("C4"))
    result = check_campground(camp, rv(), NEED)
    assert result.fit is Fit.YES and result.sites == ("C3", "C4")


def test_missing_hookup_fails():
    result = check_campground(ridb(site(hookups=(E,))), rv(), NEED)
    assert result.fit is Fit.NO and result.reason == "no site fits: no water hookup"


def test_too_short_counts_the_towed_car():
    assert check_campground(ridb(site(length=40)), rv(tow=14), NEED).fit is Fit.NO
    assert check_campground(ridb(site(length=40)), rv(tow=0), NEED).fit is Fit.YES


def test_amperage_must_match_when_both_known():
    assert check_campground(ridb(site(amps=(50,))), rv(amps=30), NEED).fit is Fit.NO
    assert check_campground(ridb(site(amps=(30, 50))), rv(amps=50), NEED).fit is Fit.YES
    assert check_campground(ridb(site(amps=())), rv(amps=50), NEED).fit is Fit.YES
    assert check_campground(ridb(site(amps=(20,))), rv(amps=None), NEED).fit is Fit.YES


def test_unknown_length_is_call_to_confirm():
    result = check_campground(ridb(site(length=None)), rv(), NEED)
    assert result.fit is Fit.CONFIRM and result.reason == "confirm room for 32.75 ft"


def test_unlisted_hookups_are_unknown_not_missing():
    rv_park = Campground(name="Moab KOA", location=HERE, source="foursquare")
    result = check_campground(rv_park, rv(), NEED)
    assert result.fit is Fit.CONFIRM
    assert result.reason == "confirm electric and water hookups and room for 32.75 ft"


def test_confirm_never_beats_a_known_no():
    # Unknown length can't rescue a site that is missing water.
    camp = ridb(site(hookups=(E,), length=None))
    assert check_campground(camp, rv(), NEED).fit is Fit.NO


def test_filter_keeps_fits_first_then_confirms_and_drops_the_rest():
    fits = ridb(site(), name="Fits")
    confirm = Campground(name="Confirm", location=HERE, source="foursquare")
    no = ridb(site(length=20), name="Too short")
    names = [c.campground.name for c in filter_campgrounds([confirm, no, fits], rv(), NEED)]
    assert names == ["Fits", "Confirm"]


def test_no_hookups_required():
    dry = ridb(site(hookups=(), amps=()))
    assert check_campground(dry, rv(), set()).reason == "fits 32.75 ft with no hookups"
    assert check_campground(dry, rv(), {S}).fit is Fit.NO
