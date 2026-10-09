import json
from dataclasses import replace
from datetime import date

import httpx
import pytest

from dave import finetune, parser, small_parser
from dave.config import load_settings
from dave.http import CachedClient
from dave.parser import Extracted

ROW = finetune.load("test")[0]
TODAY = date.fromisoformat(ROW["today"])
LABEL = Extracted.model_validate(ROW["extracted"])


def server(reply, calls=None):
    """A fake OpenAI-compatible endpoint answering every chat request with `reply`."""

    def handle(request):
        if calls is not None:
            calls.append(json.loads(request.content))
        if isinstance(reply, int):
            return httpx.Response(reply)
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    return httpx.MockTransport(handle)


def ask(tmp_path, transport):
    with CachedClient(tmp_path, transport=transport, retries=0) as http:
        return small_parser.extract_small(
            ROW["request"], TODAY, http=http, url="http://gpu:8000/", model="dave-parser"
        )


def test_valid_reply_is_parsed_and_cached(tmp_path):
    calls = []
    assert ask(tmp_path, server(json.dumps(ROW["extracted"]), calls)) == LABEL
    assert ask(tmp_path, server(500)) == LABEL  # second time comes from the disk cache
    sent = calls[0]
    assert sent["model"] == "dave-parser" and sent["temperature"] == 0
    assert sent["messages"][0]["content"] == finetune.SYSTEM
    assert ROW["request"] in sent["messages"][1]["content"]


@pytest.mark.parametrize("reply", ["Sure! Here is your trip.", '{"origin": "Denver"}', 500])
def test_unusable_replies_give_none(tmp_path, reply):
    assert ask(tmp_path, server(reply)) is None


def test_unreachable_server_gives_none(tmp_path):
    def refuse(request):
        raise httpx.ConnectError("refused")

    assert ask(tmp_path, httpx.MockTransport(refuse)) is None


@pytest.fixture
def claude(monkeypatch):
    calls = []

    def fake_extract(text, *, today, **kwargs):
        calls.append(text)
        return LABEL

    monkeypatch.setattr(parser, "extract", fake_extract)
    return calls


def test_fine_tuned_answer_skips_claude(claude):
    result = parser.parse_request(ROW["request"], today=TODAY, small=lambda t, d: LABEL)
    assert result.parser == "fine-tuned" and result.spec
    assert claude == []


def test_invalid_answer_falls_back_to_claude(claude):
    result = parser.parse_request(ROW["request"], today=TODAY, small=lambda t, d: None)
    assert result.parser == "claude" and result.spec
    assert claude == [ROW["request"]]


def test_without_a_server_dave_uses_claude_only(tmp_path):
    settings = replace(load_settings(tmp_path / "none.env"), parser_url=None)
    assert small_parser.small_parser(settings, http=None) is None
    configured = replace(settings, parser_url="http://gpu:8000")
    assert callable(small_parser.small_parser(configured, http=None))


def test_demo_requests_are_the_four_demo_trips():
    requests = small_parser.demo_requests()
    assert len(requests) == 4
    assert requests[0].startswith("We have a 2023 Winnebago Minnie Winnie 31K")


def test_compare_lists_fields_that_disagree(claude):
    wrong = LABEL.model_copy(update={"nights": (LABEL.nights or 1) + 1})
    rows = small_parser.compare([ROW["request"]], lambda t, d: wrong, today=TODAY)
    assert rows[0]["valid_json"] and rows[0]["differences"] == ["nights"]
    rows = small_parser.compare([ROW["request"]], lambda t, d: None, today=TODAY)
    assert rows[0]["differences"] == ["invalid output"] and rows[0]["fine_tuned"] is None


def test_compare_command_needs_the_server(monkeypatch, capsys):
    from dave.cli import main

    monkeypatch.delenv("DAVE_PARSER_URL", raising=False)
    assert main(["compare-parsers"]) == 2
    assert "DAVE_PARSER_URL" in capsys.readouterr().out
