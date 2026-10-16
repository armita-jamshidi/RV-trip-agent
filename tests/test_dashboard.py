import asyncio
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from urllib.parse import urlencode

import pytest
from test_agent import fake_query
from test_render import DEMO_1, demo_1

from dave import agent
from dave.dashboard import demo_requests, handler, itinerary_html, page, trip_request
from dave.render import render_markdown

DEMO_REQUEST_1 = (
    "We have a 2023 Winnebago Minnie Winnie 31K. Denver to Moab, 4 nights in November, "
    "$1,500, love hiking and big views."
)


@contextmanager
def dashboard(planner):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(planner))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def post(url: str, form: dict[str, str]) -> str:
    data = urlencode(form).encode()
    return urllib.request.urlopen(url, data=data).read().decode()


def test_every_page_has_the_rv_icon_top_right():
    html = page("")
    assert '<div class="rv-icon"><svg' in html
    assert ".rv-icon { position: fixed; top: 10px; right: 14px;" in html
    assert "http" not in html.split('<div class="rv-icon">')[1].split("</svg>")[0].replace(
        "http://www.w3.org/2000/svg", ""
    )  # bundled, not loaded from an image host


def test_form_offers_the_demo_trips():
    assert demo_requests()[0] == DEMO_REQUEST_1 and len(demo_requests()) == 4
    html = page("")
    assert "Plan my trip" in html
    assert "1. We have a 2023 Winnebago Minnie Winnie 31K." in html


def test_form_fields_become_one_request():
    form = {
        "rv": "Thor Four Winds 28A",
        "origin": "Chicago",
        "destination": "Washington DC",
        "start_date": "2026-11-02",
        "nights": "7",
        "budget": "2500",
        "interests": "museums and kid-friendly food",
        "notes": "family of four",
    }
    assert trip_request(form) == (
        "We have a Thor Four Winds 28A. Chicago to Washington DC. 7 nights from 2026-11-02. "
        "Budget $2500. We love museums and kid-friendly food. family of four"
    )
    assert trip_request({"request": " As written ", "rv": "ignored"}) == "As written"
    assert trip_request({}) == ""


def test_itinerary_shows_day_cards_costs_and_bookings(tmp_path):
    itinerary, per_day = demo_1(tmp_path)
    html = itinerary_html(render_markdown(itinerary, per_day=per_day))
    assert '<header class="trip"><h1>Denver, CO to Moab, UT</h1>' in html
    assert html.count('<section class="card day">') == 2
    assert "<h2>Day 1 · Mon Nov 02: Denver, CO to Rifle Falls</h2>" in html
    assert "<p><strong>Tonight</strong></p>\n<ul>\n<li>Rifle Falls, $28 a night" in html
    assert '<a target="_blank" rel="noopener" href="https://www.google.com/maps/dir/' in html
    assert '<section class="card costs">' in html and "<table>" in html
    assert "<strong>$223.12</strong></td>" in html
    assert '<section class="card bookings">' in html and "(proposed)" in html
    assert "<button" not in html  # nothing to pay or book from here
    assert "<blockquote>" not in html


def test_validator_warnings_are_shown(tmp_path):
    itinerary, _ = demo_1(tmp_path)
    long_day = itinerary.days[0].model_copy(update={"drive_hours": 6.5})
    text = render_markdown(itinerary.model_copy(update={"days": [long_day, *itinerary.days[1:]]}))
    html = itinerary_html(text)
    assert "<blockquote>" in html and "Not final: this plan breaks a rule." in html
    assert "6.5 h of driving is over the 5 h limit" in html


def test_planner_output_cannot_inject_html():
    assert "<script>" not in itinerary_html("# Trip\n\n<script>alert(1)</script>")


def test_demo_trip_plans_and_renders_through_dave_plan():
    """The form calls `dave.agent.plan`; the recorded reply is demo trip 1's itinerary."""
    run, prompts = fake_query(DEMO_1.read_text())

    def planner(request: str) -> str:
        return asyncio.run(agent.plan(request, options=object(), run=run))

    with dashboard(planner) as url:
        html = post(f"{url}/plan", {"request": DEMO_REQUEST_1})
    assert prompts == [DEMO_REQUEST_1]
    assert f"You asked: {DEMO_REQUEST_1}" in html
    assert html.count('<section class="card day">') == 2
    assert '<div class="rv-icon"><svg' in html


def test_planner_errors_show_on_the_page():
    def broken(request: str) -> str:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    with dashboard(broken) as url:
        html = post(f"{url}/plan", {"origin": "Denver", "destination": "Moab"})
        empty = post(f"{url}/plan", {})
    assert "Dave couldn't plan this: ANTHROPIC_API_KEY is not set" in html
    assert 'value="Denver"' in html  # the form keeps what was typed
    assert "Tell Dave where you are going first." in empty


def test_saved_demo_itineraries_open_without_planning():
    with dashboard(lambda r: pytest.fail("should not plan")) as url:
        home = urllib.request.urlopen(f"{url}/").read().decode()
        saved = urllib.request.urlopen(f"{url}/saved/{DEMO_1.name}").read().decode()
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(f"{url}/saved/../README.md")
    assert f'href="/saved/{DEMO_1.name}"' in home
    assert saved.count('<section class="card day">') == 2
    assert missing.value.code == 404


def test_cli_starts_the_dashboard(monkeypatch):
    from dave import dashboard
    from dave.cli import main

    calls = []
    monkeypatch.setattr(
        dashboard, "serve", lambda port, open_browser: calls.append((port, open_browser))
    )
    assert main(["dashboard", "--no-browser", "--port", "9000"]) == 0
    assert main(["dashboard"]) == 0
    assert calls == [(9000, False), (8765, True)]
