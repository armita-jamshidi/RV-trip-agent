"""The fine-tuned request parser (T29) served over HTTP, with Claude as the fallback (T31).

The model runs behind any OpenAI-compatible chat endpoint: vLLM (`vllm serve ... --enable-lora`),
Ollama or llama.cpp's server. Set DAVE_PARSER_URL to its base URL to use it; when it is unset,
unreachable, or replies with something that isn't a valid constraint JSON, Dave asks Claude.
"""

import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx

from dave import parser_eval
from dave.finetune import SYSTEM, read_output, user_prompt
from dave.http import CachedClient
from dave.parser import Extracted, ParseResult, parse_request, to_result

DEMO = Path(__file__).resolve().parents[2] / "demo" / "README.md"

SmallParser = Callable[[str, date], Extracted | None]


def extract_small(
    text: str, today: date, *, http: CachedClient, url: str, model: str
) -> Extracted | None:
    """Ask the fine-tuned model. None when it can't be reached or its answer isn't valid."""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_prompt(today.isoformat(), text)},
        ],
        "temperature": 0,
        "max_tokens": 512,
    }
    try:
        response = http.post(url.rstrip("/") + "/v1/chat/completions", json_body=body)
        content = response.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        return None
    return read_output(content) if response.is_success else None


def small_parser(settings, http: CachedClient) -> SmallParser | None:
    """The configured fine-tuned parser, or None to use Claude only."""
    if not settings.parser_url:
        return None
    return lambda text, today: extract_small(
        text, today, http=http, url=settings.parser_url, model=settings.parser_model
    )


def demo_requests(path: Path = DEMO) -> list[str]:
    return re.findall(r'^\d+\. "(.+)"$', path.read_text(), re.MULTILINE)


def compare(requests: list[str], small: SmallParser, *, today: date, **claude_kwargs) -> list[dict]:
    """Each request parsed by Claude and by the fine-tuned model, and where they disagree."""
    rows = []
    for text in requests:
        claude = parse_request(text, today=today, **claude_kwargs)
        extracted = small(text, today)
        mine = to_result(extracted) if extracted else None
        rows.append(
            {
                "request": text,
                "valid_json": mine is not None,
                "differences": _differences(claude, mine),
                "claude": _view(claude),
                "fine_tuned": _view(mine),
            }
        )
    return rows


def _differences(a: ParseResult, b: ParseResult | None) -> list[str]:
    if b is None:
        return ["invalid output"]
    if a.spec is None or b.spec is None:
        return [] if set(a.missing) == set(b.missing) and a.spec == b.spec else ["missing"]
    fields = type(a.spec).model_fields
    return [f for f in fields if not parser_eval.field_matches(f, a.spec, b.spec)]


def _view(result: ParseResult | None) -> dict | None:
    if result is None:
        return None
    return result.spec.model_dump(mode="json") if result.spec else {"question": result.question}
