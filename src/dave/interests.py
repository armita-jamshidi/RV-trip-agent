"""Rank candidate stops by what this traveler values.

Each interest maps to words found in Foursquare category labels (and, for "largest X", in the
place name). A stop's score is how much the traveler cares about what it offers, times how good
it is, discounted by the detour it costs.
"""

import math
import re

from dave.models import Interests, Stop

CATEGORY_WORDS = {
    "nature": r"park|nature|preserve|forest|lake|beach|trail|waterfall|canyon|mountain|scenic"
    r"|lookout|garden|river|hot spring|cave",
    "museums": r"museum|gallery|historic|history|planetarium|science center|memorial",
    "largest_x": r"monument|landmark|statue|sculpture|roadside attraction",
    "food": r"restaurant|bbq|barbecue|diner|bakery|cafe|food|brewery|winery",
}
TOP_LEVEL = {"dining and drinking": "food"}  # every place under this Foursquare root is food
NAME_WORDS = {"largest_x": r"world'?s largest|largest|biggest|giant"}
NOT_NATURE = re.compile(
    r"amusement|theme park|water park|dog park|skate park|rv park|parking", re.IGNORECASE
)

RATING_PRIOR = 6.0  # out of 10, for stops nobody has rated yet
POPULARITY_PRIOR = 0.5
DETOUR_HALF_MINUTES = 30  # a 30-minute detour halves a stop's score


def _has(pattern: str, text: str) -> bool:
    return re.search(rf"\b(?:{pattern})s?\b", text, re.IGNORECASE) is not None


def interest_matches(stop: Stop) -> set[str]:
    """Which interests a stop serves, from its category and name."""
    # Root labels like "Landmarks and Outdoors" say little, so match on the sub-categories.
    top, _, detail = stop.category.partition(" > ")
    matches = {i for i, words in CATEGORY_WORDS.items() if _has(words, detail or top)}
    if top.lower() in TOP_LEVEL:
        matches.add(TOP_LEVEL[top.lower()])
    matches |= {i for i, words in NAME_WORDS.items() if _has(words, stop.name)}
    if NOT_NATURE.search(stop.category):
        matches.discard("nature")
    return matches


def score_stop(stop: Stop, interests: Interests) -> float:
    weights = interests.model_dump()
    interest = max((weights[i] for i in interest_matches(stop)), default=0.0)
    rating = stop.rating if stop.rating is not None else RATING_PRIOR
    popularity = stop.popularity if stop.popularity is not None else POPULARITY_PRIOR
    quality = 0.6 * rating / 10 + 0.4 * popularity
    detour = math.pow(0.5, stop.detour_minutes / DETOUR_HALF_MINUTES)
    return interest * quality * detour


def rank_stops(stops: list[Stop], interests: Interests) -> list[Stop]:
    """Best first; stops that serve none of the traveler's interests are dropped."""
    scored = [(score_stop(s, interests), s) for s in stops]
    return [s for score, s in sorted(scored, key=lambda x: -x[0]) if score > 0]
