"""Rank campgrounds by how scenic they are, with the reasons.

Three signals, each 0 to 1:
- meaning: how close the campground's text is to scenic descriptions, relative to the
  other candidates (the embedding model's raw similarities sit in a narrow band, so they are
  rescaled across the set being ranked);
- mentions: distinct scenic words in the name and description (views, lake, sunset...);
- rating: the campground's rating out of 10, or a neutral prior when there is none.

Nearby natural features (from Overpass or Foursquare) are a planned fourth signal.
"""

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from dave.models import Campground
from dave.store.vectors import Embedder, campground_text

SCENIC_QUERIES = (
    "campground with sweeping mountain views",
    "lakeside or riverside campsites by the water",
    "quiet forest campground among tall trees",
    "red rock canyon and desert scenery at sunset",
    "oceanfront camping with beach views",
)
SCENIC_WORDS = {
    "view", "views", "vista", "overlook", "panoramic", "sunset", "sunrise", "stargazing",
    "lake", "lakeside", "lakefront", "reservoir", "river", "riverside", "creek", "waterfall",
    "ocean", "beach", "coast", "forest", "pines", "aspens", "redwoods", "meadow", "mountain",
    "mountains", "peaks", "alpine", "canyon", "arches", "cliffs", "scenic", "wildflowers",
}  # fmt: skip
ENOUGH_MENTIONS = 3
RATING_PRIOR = 0.5
WEIGHTS = {"meaning": 0.5, "mentions": 0.3, "rating": 0.2}


@dataclass(frozen=True)
class ScenicScore:
    score: float  # 0 to 1
    parts: dict[str, float]
    reasons: list[str] = field(default_factory=list)


def rank_scenic(
    campgrounds: list[Campground], embedder: Embedder
) -> list[tuple[Campground, ScenicScore]]:
    """Campgrounds from most to least scenic, each with its score and reasons."""
    if not campgrounds:
        return []
    texts = [campground_text(c) for c in campgrounds]
    queries = [embedder.embed_query(q) for q in SCENIC_QUERIES]
    raw = [max(_cosine(v, q) for q in queries) for v in embedder.embed(texts)]
    low, high = min(raw), max(raw)
    meaning = [(r - low) / (high - low) if high > low else 0.5 for r in raw]

    ranked = [
        (c, _score(c, text, m)) for c, text, m in zip(campgrounds, texts, meaning, strict=True)
    ]
    return sorted(ranked, key=lambda pair: pair[1].score, reverse=True)


def scenic_mentions(text: str) -> list[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return sorted(set(words) & SCENIC_WORDS)


def _score(c: Campground, text: str, meaning: float) -> ScenicScore:
    mentions = scenic_mentions(text)
    parts = {
        "meaning": meaning,
        "mentions": min(len(mentions), ENOUGH_MENTIONS) / ENOUGH_MENTIONS,
        "rating": c.rating / 10 if c.rating is not None else RATING_PRIOR,
    }
    reasons = []
    if meaning >= 0.75:
        reasons.append("reads like the most scenic campgrounds in this area")
    if mentions:
        reasons.append("mentions " + ", ".join(mentions))
    if c.rating is not None and c.rating >= 8:
        reasons.append(f"rated {c.rating:.1f}/10")
    return ScenicScore(
        score=sum(WEIGHTS[k] * v for k, v in parts.items()), parts=parts, reasons=reasons
    )


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


# --- Evaluation ---------------------------------------------------------------------

LABELS = Path(__file__).resolve().parents[2] / "evals" / "scenic" / "labels.jsonl"
TARGET = 0.8


def top_third_precision(ranked_names: list[str], scenic: set[str]) -> float:
    """Share of the top third of the ranking that people labeled scenic."""
    top = ranked_names[: max(1, len(ranked_names) // 3)]
    return sum(name in scenic for name in top) / len(top)


def evaluate(campgrounds: list[Campground], labels: dict[str, bool], embedder: Embedder) -> dict:
    """Rank the labeled campgrounds and score the ranking against the labels."""
    labeled = [c for c in campgrounds if c.name in labels]
    missing = sorted(set(labels) - {c.name for c in labeled})
    ranked = [c.name for c, _ in rank_scenic(labeled, embedder)]
    scenic = {name for name, is_scenic in labels.items() if is_scenic}
    return {
        "precision": top_third_precision(ranked, scenic),
        "ranked": ranked,
        "missing": missing,
    }
