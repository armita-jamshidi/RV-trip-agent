"""Identify a traveler's RV from loose text ("our 2023 Minnie Winnie 31") using a small catalog.

Matching is offline and deterministic. Each manufacturer lists its model lines; a line whose name
is an everyday word ("View", "Classic") only matches when the manufacturer is named too.
"""

import re
from dataclasses import dataclass

from dave.models import RVClass, RVIdentification, RVIdentity

A, B, C = RVClass.A, RVClass.B, RVClass.C
TT, FW = RVClass.TRAVEL_TRAILER, RVClass.FIFTH_WHEEL


@dataclass(frozen=True)
class Line:
    name: str
    classes: tuple[RVClass, ...]
    aliases: tuple[str, ...] = ()
    generic: bool = False  # an everyday word: needs the make in the text


@dataclass(frozen=True)
class Maker:
    name: str
    site: str
    aliases: tuple[str, ...]
    lines: tuple[Line, ...]


def _g(name: str, *classes: RVClass) -> Line:
    return Line(name, classes, generic=True)


CATALOG = (
    Maker("Winnebago", "https://www.winnebago.com", ("winnebago",), (
        Line("Minnie Winnie", (C,), ("minnie",)),
        Line("Micro Minnie", (TT,), ("minnie",)),
        Line("Revel", (B,)), Line("Travato", (B,)), Line("Solis", (B,)), Line("Navion", (C,)),
        _g("View", C), _g("Vista", A), _g("Adventurer", A), _g("Forza", A), _g("Journey", A),
        _g("Voyage", FW), _g("Hike", TT),
    )),
    Maker("Thor Motor Coach", "https://www.thormotorcoach.com", ("thor",), (
        Line("Four Winds", (C,)), Line("Chateau", (C,)), Line("Freedom Elite", (C,)),
        Line("Tellaro", (B,)), _g("Quantum", C), _g("ACE", A), _g("Hurricane", A),
        _g("Windsport", A), _g("Aria", A), _g("Sequence", B),
    )),
    Maker("Forest River", "https://forestriverinc.com", ("forest river",), (
        Line("Sunseeker", (C,)), Line("Forester", (C,)), Line("Georgetown", (A,)),
        Line("Berkshire", (A,)), Line("Rockwood", (TT, FW)), Line("Cherokee", (TT,)),
        Line("Wildwood", (TT, FW)), Line("Sandpiper", (FW,)), _g("FR3", A), _g("Salem", TT),
        _g("Cardinal", FW),
    )),
    Maker("Jayco", "https://www.jayco.com", ("jayco",), (
        Line("Greyhawk", (C,)), Line("Redhawk", (C,)), Line("Alante", (A,)),
        Line("Jay Flight", (TT,)), Line("White Hawk", (TT,)), Line("North Point", (FW,)),
        _g("Melbourne", C), _g("Precept", A), _g("Embark", A), _g("Eagle", TT, FW),
    )),
    Maker("Tiffin", "https://www.tiffinmotorhomes.com", ("tiffin",), (
        Line("Allegro", (A,)), Line("Allegro Red", (A,)), Line("Allegro Bus", (A,)),
        Line("Allegro Open Road", (A,)), Line("Phaeton", (A,)), Line("Wayfarer", (C,)),
        _g("Zephyr", A), _g("Byway", C),
    )),
    Maker("Airstream", "https://www.airstream.com", ("airstream",), (
        Line("Flying Cloud", (TT,)), Line("Bambi", (TT,)), Line("Basecamp", (TT,)),
        Line("Globetrotter", (TT,)), _g("Classic", TT), _g("International", TT),
        _g("Caravel", TT), _g("Trade Wind", TT), _g("Interstate", B), _g("Atlas", C),
    )),
    Maker("Coachmen", "https://www.coachmenrv.com", ("coachmen",), (
        Line("Leprechaun", (C,)), Line("Freelander", (C,)), Line("Mirada", (A,)),
        _g("Prism", C), _g("Pursuit", A), _g("Galleria", B), _g("Beyond", B), _g("Apex", TT),
        _g("Catalina", TT),
    )),
    Maker("Keystone", "https://www.keystone-rv.com", ("keystone",), (
        Line("Cougar", (TT, FW)), Line("Montana", (FW,)), Line("Avalanche", (FW,)),
        Line("Springdale", (TT,)), _g("Passport", TT), _g("Hideout", TT),
    )),
    Maker("Grand Design", "https://www.granddesignrv.com", ("grand design",), (
        _g("Solitude", FW), _g("Reflection", TT, FW), _g("Imagine", TT), _g("Transcend", TT),
        _g("Influence", FW), _g("Momentum", TT, FW), _g("Lineage", C),
    )),
)  # fmt: skip

CLASS_HINTS = {
    r"class a": A,
    r"class b|camper van": B,
    r"class c": C,
    r"travel trailer": TT,
    r"fifth wheel|5th wheel": FW,
}
YEAR = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
SHORT_YEAR = re.compile(r"'(\d{2})\b")
FLOORPLAN = re.compile(r"^(\d{2,4}) ?([a-z]{1,4})?$")
UNITS = {"night", "nights", "day", "days", "ft", "feet", "foot", "hours", "miles", "people"}


def _norm(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9']+", " ", text.lower()).strip() + " "


def _find(alias: str, text: str) -> int:
    """Index just past the alias as a whole phrase in normalized text, or -1."""
    i = text.find(f" {alias} ")
    return -1 if i < 0 else i + len(alias) + 1


def _year(text: str) -> int | None:
    if m := YEAR.search(text):
        return int(m.group(1))
    if m := SHORT_YEAR.search(text):
        yy = int(m.group(1))
        return 2000 + yy if yy <= 50 else 1900 + yy
    return None


def _floorplan(after: str, year: int | None) -> str | None:
    """A floorplan code ("31K", "38 KA", "2108DS") within the three words after the model."""
    words = after.split()[:3]
    for i in range(len(words)):
        for chunk in (" ".join(words[i : i + 2]), words[i]):
            m = FLOORPLAN.match(chunk)
            unit = chunk == words[i] and i + 1 < len(words) and words[i + 1] in UNITS
            if m and int(m.group(1)) != year and not unit:
                return (m.group(1) + (m.group(2) or "")).upper()
    return None


def identify_rv(text: str) -> RVIdentification:
    norm = _norm(text)
    year = _year(norm)
    hint = next((cls for pat, cls in CLASS_HINTS.items() if re.search(pat, norm)), None)
    makers = [m for m in CATALOG if any(_find(a, norm) >= 0 for a in m.aliases)]

    # Every line whose name (or alias) appears, keeping the longest phrase that matched.
    hits: list[tuple[int, int, Maker, Line]] = []  # (alias length, end index, maker, line)
    for maker in makers or CATALOG:
        for line in maker.lines:
            if line.generic and maker not in makers:
                continue
            for alias in (line.name.lower(), *line.aliases):
                if (end := _find(alias, norm)) >= 0:
                    hits.append((len(alias), end, maker, line))
    best = max((h[0] for h in hits), default=0)
    hits = [h for h in hits if h[0] == best]

    def identity(maker: Maker, line: Line, end: int | None = None) -> RVIdentity:
        cls = line.classes[0] if len(line.classes) == 1 else hint if hint in line.classes else None
        return RVIdentity(
            make=maker.name,
            model=line.name,
            floorplan=_floorplan(norm[end:], year) if end is not None else None,
            year=year,
            rv_class=cls,
            site=maker.site,
        )

    if len({(m.name, ln.name) for _, _, m, ln in hits}) == 1:
        _, end, maker, line = hits[0]
        return RVIdentification(match=identity(maker, line, end))
    if hits:
        unique = {(m.name, ln.name): (m, ln) for _, _, m, ln in hits}
        return RVIdentification(candidates=[identity(m, ln) for m, ln in unique.values()])
    if len(makers) == 1:  # make only: offer its lines, narrowed by any class the text gives
        lines = [ln for ln in makers[0].lines if hint is None or hint in ln.classes]
        return RVIdentification(candidates=[identity(makers[0], ln) for ln in lines])
    return RVIdentification()
