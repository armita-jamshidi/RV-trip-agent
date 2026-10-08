import pytest
from conftest import ConceptEmbedder

from dave import cli, scenic
from dave.models import Campground, Place
from dave.scenic import evaluate, rank_scenic, scenic_mentions, top_third_precision


def camp(name, description, rating=None):
    return Campground(
        name=name,
        location=Place(name=name, lat=38.5, lon=-109.5),
        description=description,
        rating=rating,
        source="ridb",
    )


# Hand-labeled sample: the first four are scenic, the rest are not.
SCENIC = [
    camp("Warner Lake", "Alpine lake under the peaks with sunset views over the meadow."),
    camp("Devils Garden", "Red rock canyon fins and arches; stargazing from every site."),
    camp("Goose Island", "Riverside sites below the cliffs along the Colorado River."),
    camp("Oowah Lake", "Quiet forest lake among the pines and aspens."),
]
PLAIN = [
    camp("Highway 191 RV Park", "Gravel pull-throughs next to the highway, close to town."),
    camp("Downtown RV Lot", "Paved city lot near shops, laundry on site."),
    camp("Truck Stop Overnight", "Overnight parking behind the fuel station."),
    camp("Fairgrounds Camping", "Open field at the county fairgrounds, events most weekends."),
    camp("Exit 182 Campground", "Convenient stop off the interstate with dump station."),
    camp("Storage Yard RV", "Long-term RV storage with a few overnight spots."),
    camp("Mall Parking Camp", "Overnight parking near the shopping center."),
    camp("Industrial Park RV", "Sites by the warehouses, wifi and showers."),
]
ALL = PLAIN[:4] + SCENIC + PLAIN[4:]  # scenic ones not first, so order isn't doing the work


def test_scenic_campgrounds_fill_the_top_third():
    ranked = [c.name for c, _ in rank_scenic(ALL, ConceptEmbedder())]
    assert top_third_precision(ranked, {c.name for c in SCENIC}) >= scenic.TARGET
    assert set(ranked[:4]) == {c.name for c in SCENIC}


def test_scores_explain_themselves():
    ranked = rank_scenic(ALL, ConceptEmbedder())
    best, score = ranked[0]
    assert 0 <= score.score <= 1
    assert set(score.parts) == {"meaning", "mentions", "rating"}
    assert any(r.startswith("mentions ") for r in score.reasons)
    plain_score = dict((c.name, s) for c, s in ranked)["Truck Stop Overnight"]
    assert plain_score.reasons == [] and plain_score.parts["mentions"] == 0


def test_rating_breaks_ties_and_shows_in_reasons():
    a = camp("Lake A", "Lake views.", rating=9.2)
    b = camp("Lake B", "Lake views.", rating=5.0)
    (first, first_score), (second, _) = rank_scenic([b, a], ConceptEmbedder())
    assert first.name == "Lake A"
    assert "rated 9.2/10" in first_score.reasons


def test_missing_rating_is_neutral():
    a = camp("Lake A", "Lake views.")
    b = camp("Lake B", "Lake views.", rating=5.0)
    scores = {c.name: s for c, s in rank_scenic([a, b], ConceptEmbedder())}
    assert scores["Lake A"].parts["rating"] == scores["Lake B"].parts["rating"] == 0.5


def test_mentions_are_whole_words():
    assert scenic_mentions("Lakeview Drive near Lakewood") == []
    assert scenic_mentions("Views of the lake at sunset, lake again") == ["lake", "sunset", "views"]


def test_empty_and_single():
    assert rank_scenic([], ConceptEmbedder()) == []
    [(only, score)] = rank_scenic([SCENIC[0]], ConceptEmbedder())
    assert score.parts["meaning"] == 0.5


def test_top_third_precision():
    assert top_third_precision(list("abcdefghi"), {"a", "b", "c"}) == 1
    assert top_third_precision(list("abcdefghi"), {"a", "x"}) == pytest.approx(1 / 3)


def test_evaluate_reports_missing_labels():
    labels = {c.name: c in SCENIC for c in ALL} | {"Not Ingested": True}
    report = evaluate(ALL, labels, ConceptEmbedder())
    assert report["missing"] == ["Not Ingested"]
    assert report["precision"] == 1
    assert len(report["ranked"]) == len(ALL)


def test_cli_explains_missing_labels(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scenic, "LABELS", tmp_path / "labels.jsonl")
    with pytest.raises(SystemExit):
        cli.main(["eval-scenic"])
    assert "label ingested campgrounds" in capsys.readouterr().err
