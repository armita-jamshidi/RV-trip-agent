"""Tickets the planned stops need, proposed for the traveler's approval (never bought here).

Fees and timed-entry rules change every year, so they live in a checked list
(`tickets.json`, each entry with its official page and the date it was checked) rather
than being guessed. A stop not on the list gets no proposal.

- One entrance pass per park per trip, starting the first day the trip stops there.
- A timed-entry reservation when that day falls in one of the park's reservation windows.
- When the separate passes cost more than the America the Beautiful annual pass, one annual
  pass is proposed instead.

Every result is a `BookingProposal` in the `proposed` state; buying goes through
`dave.booking`, which needs a person's approval first.
"""

import json
from datetime import date, timedelta
from pathlib import Path

from dave.models import BookingProposal, DayLeg

TICKETS = Path(__file__).with_name("tickets.json")


def ticket_proposals(days: list[DayLeg], rules: dict | None = None) -> list[BookingProposal]:
    rules = rules or json.loads(TICKETS.read_text())
    passes: dict[str, BookingProposal] = {}
    timed: list[BookingProposal] = []
    for day in days:
        for stop in day.stops:
            site = _site(stop.name, rules["sites"])
            if site is None:
                continue
            if day.travel_date is None:
                raise ValueError("Ticket proposals need trip dates; the plan has none.")
            if site["match"] not in passes:
                passes[site["match"]] = _entrance(site, day.travel_date)
            window = _timed_window(site, day.travel_date)
            if window:
                timed.append(_timed_entry(site, window, day.travel_date))

    entrance = list(passes.values())
    annual = rules["annual_pass"]
    if entrance and sum(p.price_usd for p in entrance) > annual["price_usd"]:
        entrance = [_annual(annual, min(p.start_date for p in entrance), list(passes))]
    return entrance + timed


def _site(stop_name: str, sites: list[dict]) -> dict | None:
    return next((s for s in sites if s["match"].lower() in stop_name.lower()), None)


def _entrance(site: dict, day: date) -> BookingProposal:
    return BookingProposal(
        kind="ticket",
        name=site["name"],
        start_date=day,
        end_date=day + timedelta(days=site["valid_days"] - 1),
        price_usd=site["price_usd"],
        url=site["url"],
    )


def _timed_window(site: dict, day: date) -> dict | None:
    return next(
        (
            w
            for w in site.get("timed_entry", [])
            if date.fromisoformat(w["start"]) <= day <= date.fromisoformat(w["end"])
        ),
        None,
    )


def _timed_entry(site: dict, window: dict, day: date) -> BookingProposal:
    return BookingProposal(
        kind="ticket",
        name=f"{site['match']} timed-entry reservation ({window['hours']})",
        start_date=day,
        price_usd=window["price_usd"],
        url=site["timed_entry_url"],
    )


def _annual(annual: dict, first_day: date, parks: list[str]) -> BookingProposal:
    return BookingProposal(
        kind="ticket",
        name=f"{annual['name']}, covers {', '.join(parks)}",
        start_date=first_day,
        price_usd=annual["price_usd"],
        url=annual["url"],
    )
