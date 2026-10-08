import pytest

from dave.interests import interest_matches, rank_stops, score_stop
from dave.models import Interests, Place, Stop

HERE = Place(name="I-70", lat=39.0, lon=-108.5)


def stop(name, category, rating=8.0, popularity=0.7, detour=10):
    return Stop(
        name=name,
        location=HERE,
        category=category,
        rating=rating,
        popularity=popularity,
        detour_minutes=detour,
    )


CANDIDATES = [
    stop("Colorado National Monument", "Landmarks and Outdoors > Park > National Park", 9.2),
    stop("Museum of Western Colorado", "Arts and Entertainment > Museum > History Museum", 8.4),
    stop("Dinosaur Journey", "Arts and Entertainment > Museum > Science Museum", 8.1),
    stop("Rattlesnake Canyon Trail", "Landmarks and Outdoors > Hiking Trail", 8.8),
    stop("World's Largest Fork", "Landmarks and Outdoors > Monument", 7.0, 0.4),
    stop("Kokopelli BBQ", "Dining and Drinking > Restaurant > BBQ Joint", 8.6),
    stop("Gas N Go", "Retail > Gas Station", 6.0),
]
NATURE_LOVER = Interests(nature=0.9, museums=0.1, largest_x=0.0, food=0.3)
MUSEUM_LOVER = Interests(nature=0.1, museums=0.9, largest_x=0.0, food=0.3)


def test_nature_and_museum_lovers_get_different_top_stops():
    nature_top = rank_stops(CANDIDATES, NATURE_LOVER)[:2]
    museum_top = rank_stops(CANDIDATES, MUSEUM_LOVER)[:2]
    assert {s.name for s in nature_top} == {
        "Colorado National Monument",
        "Rattlesnake Canyon Trail",
    }
    assert {s.name for s in museum_top} == {"Museum of Western Colorado", "Dinosaur Journey"}


def test_stops_serving_no_interest_are_dropped():
    assert "Gas N Go" not in {s.name for s in rank_stops(CANDIDATES, NATURE_LOVER)}
    only_food = Interests(nature=0, museums=0, largest_x=0, food=1)
    assert [s.name for s in rank_stops(CANDIDATES, only_food)] == ["Kokopelli BBQ"]


@pytest.mark.parametrize(
    "name, category, expected",
    [
        ("Arches", "Landmarks and Outdoors > Park > National Park", {"nature"}),
        ("Six Flags", "Arts and Entertainment > Amusement Park", set()),
        ("World's Largest Ball of Twine", "Landmarks and Outdoors > Monument", {"largest_x"}),
        ("Giant Peach", "Landmarks and Outdoors > Scenic Lookout", {"largest_x", "nature"}),
        ("The Henry Ford", "Arts and Entertainment > Museum > History Museum", {"museums"}),
        ("Central BBQ", "Dining and Drinking > Restaurant > BBQ Joint", {"food"}),
    ],
)
def test_interest_matches(name, category, expected):
    assert interest_matches(stop(name, category)) == expected


def test_longer_detour_lowers_score():
    near = stop("Lake", "Landmarks and Outdoors > Lake", detour=0)
    far = near.model_copy(update={"detour_minutes": 30})
    assert score_stop(far, NATURE_LOVER) == pytest.approx(score_stop(near, NATURE_LOVER) / 2)


def test_better_rating_ranks_higher():
    good = stop("Good Trail", "Landmarks and Outdoors > Hiking Trail", rating=9.5)
    meh = stop("Meh Trail", "Landmarks and Outdoors > Hiking Trail", rating=5.0)
    assert rank_stops([meh, good], NATURE_LOVER) == [good, meh]


def test_unrated_stop_uses_prior():
    unrated = Stop(name="New Park", location=HERE, category="Landmarks and Outdoors > Park")
    assert 0 < score_stop(unrated, NATURE_LOVER) < score_stop(CANDIDATES[0], NATURE_LOVER)
