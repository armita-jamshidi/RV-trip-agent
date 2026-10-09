import ast
import json
from datetime import date
from pathlib import Path

from dave import finetune
from dave.parser import Extracted

TEST = finetune.load("test")
NOTEBOOK = Path(finetune.__file__).resolve().parents[2] / "training" / "qlora_parser.ipynb"


def perfect(rows: list[dict]) -> list[Extracted]:
    return [Extracted.model_validate(r["extracted"]) for r in rows]


def test_messages_teach_the_label_as_json():
    row = TEST[0]
    example = finetune.messages(row)
    assert [m["role"] for m in example["prompt"]] == ["system", "user"]
    assert row["today"] in example["prompt"][1]["content"]
    assert row["request"] in example["prompt"][1]["content"]
    assert json.loads(example["completion"][0]["content"]) == row["extracted"]
    for field in Extracted.model_fields:
        assert field in finetune.SYSTEM


def test_read_output_accepts_json_and_rejects_the_rest():
    label = json.dumps(TEST[0]["extracted"])
    assert finetune.read_output(label) == Extracted.model_validate(TEST[0]["extracted"])
    assert finetune.read_output(f"```json\n{label}\n```") is not None
    assert finetune.read_output("I can't help with that.") is None
    assert finetune.read_output('{"origin": "Denver, CO"}') is None  # missing keys
    assert finetune.read_output(label[:-10]) is None  # cut off


def test_perfect_outputs_score_full_marks():
    report = finetune.score(perfect(TEST), TEST)
    assert report["valid_json"] == 1
    assert report["accuracy"] == 1
    assert report["misses"] == []


def test_invalid_outputs_score_zero():
    report = finetune.score([None] * len(TEST), TEST)
    assert report["valid_json"] == 0
    assert report["accuracy"] == 0


def test_a_wrong_field_costs_only_that_field():
    outputs = perfect(TEST)
    first = next(i for i, r in enumerate(TEST) if r["extracted"]["budget_usd"])
    outputs[first] = outputs[first].model_copy(update={"budget_usd": 1.0})
    report = finetune.score(outputs, TEST)
    assert report["misses"] == [{"id": TEST[first]["id"], "fields": ["budget_usd"]}]
    assert 0.99 < report["accuracy"] < 1


def test_baseline_reads_each_request_against_its_own_day():
    days = []

    def oracle(text: str, today: date) -> Extracted:
        days.append(today)
        return next(Extracted.model_validate(r["extracted"]) for r in TEST if r["request"] == text)

    assert finetune.baseline(oracle, TEST)["accuracy"] == 1
    assert days == [date.fromisoformat(r["today"]) for r in TEST]


def test_target_is_95_percent_of_baseline():
    assert finetune.meets_target({"accuracy": 0.86}, {"accuracy": 0.9})
    assert not finetune.meets_target({"accuracy": 0.85}, {"accuracy": 0.9})


def test_notebook_code_is_valid_python():
    nb = json.loads(NOTEBOOK.read_text())
    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            source = "".join(cell["source"])
            ast.parse("\n".join(ln for ln in source.splitlines() if not ln.startswith(("!", "%"))))
            assert 'HF_TOKEN"' not in source or "userdata.get" in source
