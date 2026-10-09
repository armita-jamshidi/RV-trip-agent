import json
from pathlib import Path

import pytest
from conftest import ConceptEmbedder
from test_vectors import CAMPS, camp

from dave import embed_tune
from dave.models import Hookup
from dave.store.vectors import FastEmbedder

NOTEBOOK = Path(embed_tune.__file__).resolve().parents[2] / "training" / "finetune_embeddings.ipynb"

# Enough campgrounds that both splits hold matches and non-matches for several needs.
MANY = [
    camp(f"{c.name} {i}", c.description, c.location.lat, c.location.lon, c.hookups,
         c.max_rv_length_ft, c.electrical_amps)
    for i in range(12) for c in CAMPS
]  # fmt: skip


def test_needs_match_on_facts_and_descriptions():
    by_name = {c.name: c for c in CAMPS}
    need = {n.name: n for n in embed_tune.NEEDS}
    assert need["full hookups"].matches(by_name["Moab KOA"])
    assert not need["full hookups"].matches(by_name["Kens Lake"])
    assert need["50 amp"].matches(by_name["Kens Lake"])
    assert need["big rig"].matches(by_name["Cherry Creek"])
    assert need["lake"].matches(by_name["Warner Lake"])
    assert need["river"].matches(by_name["Goose Island"])
    assert need["desert"].matches(by_name["Sand Flats"])
    assert need["forest"].matches(by_name["Oowah Lake"])
    assert need["family"].matches(by_name["Moab KOA"])
    assert not need["beach"].matches(by_name["Moab KOA"])


def test_train_and_test_phrasings_never_overlap():
    for need in embed_tune.NEEDS:
        assert need.train and need.test
        assert not set(need.train) & set(need.test)


def test_split_is_stable_and_about_one_in_five():
    held_out = [c for c in MANY if embed_tune.is_test(c)]
    assert 0.1 < len(held_out) / len(MANY) < 0.3
    assert held_out == [c for c in MANY if embed_tune.is_test(c)]


def test_pairs_come_only_from_training_campgrounds_and_phrasings():
    rows = embed_tune.pairs(MANY)
    assert rows
    train_texts = {embed_tune.campground_text(c) for c in MANY if not embed_tune.is_test(c)}
    phrasings = {q for n in embed_tune.NEEDS for q in n.train}
    need = {q: n for n in embed_tune.NEEDS for q in n.train}
    by_text = {embed_tune.campground_text(c): c for c in MANY}
    for row in rows:
        assert row["query"] in phrasings
        assert row["positive"] in train_texts and row["negative"] in train_texts
        assert need[row["query"]].matches(by_text[row["positive"]])
        assert not need[row["query"]].matches(by_text[row["negative"]])
    assert rows == embed_tune.pairs(MANY)  # deterministic


def test_evaluate_reports_recall_and_mrr():
    report = embed_tune.evaluate(ConceptEmbedder(), MANY)
    assert 0 <= report["recall_at_5"] <= 1 and 0 < report["mrr"] <= 1
    assert report["queries"] == len(report["recall_at_5_by_need"])
    assert report["campgrounds"] == sum(embed_tune.is_test(c) for c in MANY)


class Oracle:
    """Puts every campground on the axis of the needs it meets: a perfect retriever."""

    def embed(self, texts):
        by_text = {embed_tune.campground_text(c): c for c in MANY}
        return [[float(n.matches(by_text[t])) for n in embed_tune.NEEDS] + [0.01] for t in texts]

    def embed_query(self, text):
        return [float(text in n.test or text in n.train) for n in embed_tune.NEEDS] + [0.0]


def test_a_perfect_retriever_scores_one():
    report = embed_tune.evaluate(Oracle(), MANY)
    assert report["recall_at_5"] == 1 and report["mrr"] == 1


def test_evaluate_needs_some_scoreable_query():
    with pytest.raises(ValueError):
        embed_tune.evaluate(ConceptEmbedder(), [c for c in MANY if Hookup.SEWER in c.hookups])


def test_tuned_model_loads_from_its_local_folder(tmp_path):
    # No download: fastembed goes straight to the folder and finds no model there.
    with pytest.raises(Exception, match="onnx/model.onnx"):
        FastEmbedder(tmp_path / "cache", tmp_path / "tuned")


def test_notebook_code_is_valid_python():
    import ast

    nb = json.loads(NOTEBOOK.read_text())
    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            lines = "".join(cell["source"]).splitlines()
            ast.parse("\n".join(ln for ln in lines if not ln.startswith(("!", "%"))))


def test_eval_embeddings_command(tmp_path, monkeypatch, capsys):
    from dave.cli import main
    from dave.store import vectors

    monkeypatch.setattr(vectors, "FastEmbedder", lambda cache_dir, model_path=None: Oracle())
    path = tmp_path / "campgrounds.jsonl"
    path.write_text("\n".join(c.model_dump_json() for c in MANY))
    assert main(["eval-embeddings", "--campgrounds", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["recall_at_5"] == 1
