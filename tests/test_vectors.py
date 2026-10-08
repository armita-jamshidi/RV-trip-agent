import math
import re

import pytest

from dave.models import Campground, Hookup, Place
from dave.store.vectors import CampgroundIndex, campground_text

# A stand-in for the real embedding model: one dimension per concept, synonyms share it.
# Enough to check the index and filters; the real model's quality is checked live (see PR).
CONCEPTS = [
    {"lake", "lakeside", "reservoir", "lakefront"},
    {"mountain", "mountains", "peaks", "alpine"},
    {"desert", "canyon", "red", "rock", "arches"},
    {"quiet", "peaceful", "secluded", "remote"},
    {"river", "creek", "riverside"},
    {"forest", "pines", "trees", "shade", "shady"},
    {"city", "downtown", "museums", "museum"},
    {"family", "kids", "playground", "pool"},
]


class ConceptEmbedder:
    def embed(self, texts):
        return [self.embed_query(t) for t in texts]

    def embed_query(self, text):
        words = set(re.findall(r"[a-z]+", text.lower()))
        v = [float(len(words & c)) for c in CONCEPTS] + [0.01]
        norm = math.sqrt(sum(x * x for x in v))
        return [x / norm for x in v]


def camp(name, description, lat, lon, hookups=(), length=None, amps=()):
    return Campground(
        name=name,
        location=Place(name=name, lat=lat, lon=lon),
        description=description,
        hookups=set(hookups),
        max_rv_length_ft=length,
        electrical_amps=set(amps),
        source="ridb",
    )


EW = (Hookup.ELECTRIC, Hookup.WATER)
CAMPS = [
    camp("Kens Lake", "Quiet reservoir below snowy peaks.", 38.48, -109.43, EW, 45, (30, 50)),
    camp("Devils Garden", "Red rock fins and arches in the desert.", 38.78, -109.59, (), 30),
    camp("Sand Flats", "Remote desert camping on slickrock.", 38.58, -109.52),
    camp("Goose Island", "Riverside sites along the Colorado River.", 38.61, -109.56, EW, 35),
    camp(
        "Warner Lake",
        "Secluded alpine lake in the La Sal mountains, under aspens.",
        38.52,
        -109.28,
        (Hookup.WATER,),
        20,
    ),
    camp(
        "Moab KOA",
        "Family park with a pool and playground for kids.",
        38.53,
        -109.50,
        set(Hookup),
        45,
        (30, 50),
    ),
    camp("Oowah Lake", "Shady forest lake among the pines.", 38.50, -109.27),
    camp(
        "Cherry Creek",
        "Peaceful forest camp by a mountain creek near Denver.",
        39.65,
        -104.85,
        EW,
        40,
    ),
]


@pytest.fixture
def index(tmp_path):
    idx = CampgroundIndex(tmp_path / "camps.lance", ConceptEmbedder())
    assert idx.build(CAMPS) == len(CAMPS)
    return idx


def names(results):
    return [c.name for c, _ in results]


@pytest.mark.parametrize(
    "query, best",
    [
        ("quiet lakeside with mountain views", "Kens Lake"),
        ("red rock desert near the arches", "Devils Garden"),
        ("camp right on the river", "Goose Island"),
        ("somewhere the kids can swim in a pool", "Moab KOA"),
        ("shady spot under the pines", "Oowah Lake"),
    ],
)
def test_five_queries_find_the_obvious_match(index, query, best):
    results = index.search(query)
    assert names(results)[0] == best
    assert len(results) == 5
    scores = [s for _, s in results]
    assert scores == sorted(scores, reverse=True)


def test_hookup_filter_keeps_only_known_matches(index):
    results = index.search("quiet lakeside with mountain views", hookups=EW)
    assert names(results)[0] == "Kens Lake"
    assert set(names(results)) == {"Kens Lake", "Cherry Creek", "Moab KOA", "Goose Island"}
    assert all({Hookup.ELECTRIC, Hookup.WATER} <= c.hookups for c, _ in results)


def test_length_filter_drops_short_and_unknown(index):
    results = index.search("desert", min_length_ft=35, k=10)
    assert all(c.max_rv_length_ft and c.max_rv_length_ft >= 35 for c, _ in results)
    assert "Devils Garden" not in names(results)  # 30 ft
    assert "Sand Flats" not in names(results)  # length unknown


def test_distance_filter(index):
    moab = (38.5733, -109.5498)
    results = index.search("peaceful forest creek", near=moab, radius_miles=50, k=10)
    assert "Cherry Creek" not in names(results)  # Denver is about 250 miles away
    assert "Oowah Lake" in names(results)


def test_filters_combine(index):
    results = index.search(
        "lake", hookups=EW, min_length_ft=40, near=(38.5733, -109.5498), radius_miles=50
    )
    assert set(names(results)) == {"Kens Lake", "Moab KOA"}


def test_round_trips_the_full_campground(index):
    (best, _), *_ = index.search("quiet lakeside with mountain views")
    assert best == CAMPS[0]


def test_text_includes_the_facts_travelers_ask_about():
    text = campground_text(CAMPS[0])
    assert "Quiet reservoir" in text
    assert "electric and water hookups" in text
    assert "30/50 amp" in text and "up to 45 ft" in text


def test_empty_build_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="dave campgrounds"):
        CampgroundIndex(tmp_path / "x.lance", ConceptEmbedder()).build([])


def test_cli_indexes_and_searches(tmp_path, monkeypatch, capsys):
    from dave import cli
    from dave.store import vectors

    monkeypatch.setattr(vectors, "FastEmbedder", lambda cache_dir: ConceptEmbedder())
    monkeypatch.setattr(vectors, "INDEX_PATH", tmp_path / "camps.lance")
    source = tmp_path / "camps.jsonl"
    source.write_text("".join(c.model_dump_json() + "\n" for c in CAMPS))

    assert cli.main(["index-campgrounds", "--from", str(source)]) == 0
    assert "Indexed 8 campgrounds" in capsys.readouterr().out
    args = ["find-campgrounds", "lake", "--hookups", "electric,water", "--length", "40"]
    assert cli.main([*args, "--near", "38.5733,-109.5498"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 2 and {line.split("  ")[1] for line in out} == {"Kens Lake", "Moab KOA"}
