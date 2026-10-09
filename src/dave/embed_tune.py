"""Training pairs and scoring for the fine-tuned campground embedding model (T30).

A query ("full hookups", "camp in the woods") is relevant to a campground when the campground's
known facts or its own description back it up. Training uses some phrasings of each need on 80%
of the campgrounds; scoring uses other phrasings on the held-out 20%, so a model can't pass by
memorizing either. The Colab notebook `training/finetune_embeddings.ipynb` uses both.
"""

import hashlib
import random
import re
from collections.abc import Callable
from dataclasses import dataclass

from dave.models import Campground, Hookup
from dave.store.vectors import Embedder, campground_text

K = 5


def _mentions(*words: str) -> Callable[[Campground], bool]:
    pattern = re.compile(r"\b(" + "|".join(words) + r")", re.IGNORECASE)
    return lambda c: bool(pattern.search(f"{c.name} {c.description or ''}"))


@dataclass(frozen=True)
class Need:
    name: str
    matches: Callable[[Campground], bool]
    train: tuple[str, ...]
    test: tuple[str, ...]


NEEDS = (
    Need("full hookups", lambda c: c.hookups >= set(Hookup),
         ("full hookups", "electric, water and sewer at the site", "full hook-up sites"),
         ("need sewer hookups too",)),
    Need("electric", lambda c: Hookup.ELECTRIC in c.hookups,
         ("campground with electric hookups", "power at the site"),
         ("somewhere to plug in the RV",)),
    Need("50 amp", lambda c: 50 in c.electrical_amps,
         ("50 amp service", "50A power for a big motorhome"),
         ("fifty amp hookups",)),
    Need("big rig", lambda c: (c.max_rv_length_ft or 0) >= 40,
         ("big rig friendly", "room for a 40 foot motorhome", "long pull-through sites"),
         ("fits a 45 ft class A towing a car",)),
    Need("lake", _mentions("lake", "reservoir"),
         ("camping by a lake", "lakeside campsites"),
         ("near a lake for kayaking",)),
    Need("river", _mentions("river", "creek", "stream"),
         ("riverside camping", "camp next to a creek"),
         ("by the river",)),
    Need("mountains", _mentions("mountain", "peak", "alpine"),
         ("mountain views", "alpine campground"),
         ("up in the mountains",)),
    Need("desert", _mentions("desert", "red rock", "slickrock", "canyon", "mesa"),
         ("desert camping", "red rock scenery"),
         ("camp among the canyons",)),
    Need("forest", _mentions("forest", "pine", "aspen", "shad", "trees", "woods"),
         ("shady sites under trees", "forest campground"),
         ("camp in the woods",)),
    Need("family", _mentions("pool", "playground", "kids", "family", "children"),
         ("family friendly with a playground", "pool for the kids"),
         ("good for children",)),
    Need("quiet", _mentions("quiet", "secluded", "remote", "peaceful", "solitude"),
         ("quiet and secluded", "peaceful campground away from crowds"),
         ("remote spot with no neighbors",)),
    Need("beach", _mentions("beach", "ocean", "coast", "shore"),
         ("beachfront camping", "campsites on the coast"),
         ("near the ocean",)),
)  # fmt: skip


def is_test(c: Campground) -> bool:
    """A stable 1-in-5 split by name, so reruns and new data keep the same held-out campgrounds."""
    return int(hashlib.sha1(c.name.encode()).hexdigest(), 16) % 5 == 0


def pairs(campgrounds: list[Campground], seed: int = 30, per_phrase: int = 50) -> list[dict]:
    """(query, matching campground, non-matching campground) triples from the training split."""
    rng = random.Random(seed)
    train = [c for c in campgrounds if not is_test(c)]
    rows = []
    for need in NEEDS:
        pos = [c for c in train if need.matches(c)]
        neg = [c for c in train if not need.matches(c)]
        if not pos or not neg:
            continue
        for query in need.train:
            for c in rng.sample(pos, min(per_phrase, len(pos))):
                rows.append({"query": query, "positive": campground_text(c),
                             "negative": campground_text(rng.choice(neg))})  # fmt: skip
    rng.shuffle(rows)
    return rows


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = (sum(x * x for x in a) * sum(y * y for y in b)) ** 0.5
    return dot / norm if norm else 0.0


def evaluate(embedder: Embedder, campgrounds: list[Campground]) -> dict:
    """recall@5 and MRR of held-out phrasings over the held-out campgrounds."""
    test = [c for c in campgrounds if is_test(c)]
    vectors = embedder.embed([campground_text(c) for c in test])
    recalls, ranks, per_need = [], [], {}
    for need in NEEDS:
        relevant = {i for i, c in enumerate(test) if need.matches(c)}
        if not relevant or len(relevant) == len(test):
            continue
        for query in need.test:
            q = embedder.embed_query(query)
            order = sorted(range(len(test)), key=lambda i: -_cosine(q, vectors[i]))
            recall = len(relevant & set(order[:K])) / min(K, len(relevant))
            recalls.append(recall)
            ranks.append(1 / (1 + next(r for r, i in enumerate(order) if i in relevant)))
            per_need[need.name] = recall
    if not recalls:
        raise ValueError("No held-out queries have both matching and non-matching campgrounds.")
    return {
        "recall_at_5": sum(recalls) / len(recalls),
        "mrr": sum(ranks) / len(ranks),
        "queries": len(recalls),
        "campgrounds": len(test),
        "recall_at_5_by_need": per_need,
    }
