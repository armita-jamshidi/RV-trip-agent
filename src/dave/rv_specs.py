"""RV dimensions from the manufacturer's spec page, checked against plausible ranges per class.

Spec pages put one floorplan per column ("Exterior Length | 24'5" | 32'9" ..."), so the table is
read in code. Pages without such a table go to Claude, when a key is set. Anything missing or out
of range falls back to a conservative class average marked `estimated`. Traveler overrides win.
"""

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import anthropic
from pydantic import BaseModel

from dave.http import CachedClient
from dave.models import FuelType, RVClass, RVIdentity, RVProfile

A, B, C = RVClass.A, RVClass.B, RVClass.C
TT, FW = RVClass.TRAVEL_TRAILER, RVClass.FIFTH_WHEEL

MODEL = "claude-opus-5-5"

# Where each manufacturer keeps spec pages, by RV class. Only patterns checked against the live
# site are listed; other makes fall back to class averages until their sites are reachable.
SPEC_PAGES = {
    "Winnebago": (
        "https://www.winnebago.com/models/product/specifications/motorhomes/{segment}/{slug}",
        {A: "class-a", B: "camper-van", C: "class-c"},
    ),
}

# Spec-table row labels -> RVProfile fields.
ROWS = {
    "exterior length": "length_ft",
    "exterior height": "height_ft",
    "exterior width": "width_ft",
    "gvwr": "gvwr_lbs",
    "fuel capacity": "fuel_tank_gal",
}

# (low, high) per field and class. A value outside its range is treated as unread.
RANGES = {
    A: {"length_ft": (25, 45), "height_ft": (10, 14), "gvwr_lbs": (14_000, 55_000)},
    B: {"length_ft": (16, 25), "height_ft": (7.5, 11), "gvwr_lbs": (6_000, 12_000)},
    C: {"length_ft": (20, 41), "height_ft": (9.5, 13), "gvwr_lbs": (10_000, 26_000)},
    TT: {"length_ft": (10, 45), "height_ft": (7, 13.5), "gvwr_lbs": (1_500, 12_000)},
    FW: {"length_ft": (20, 45), "height_ft": (10, 13.6), "gvwr_lbs": (6_000, 22_000)},
}
COMMON = {"width_ft": (6, 8.7), "fuel_tank_gal": (15, 200)}

# Class averages for when the page can't be read. Length and height lean high on purpose:
# an estimate that is too short or too low could send the RV under a bridge it doesn't clear.
ESTIMATES = {
    A: {"length_ft": 40, "height_ft": 13.5, "width_ft": 8.5, "fuel_type": FuelType.GAS,
        "electrical_amps": 50},
    B: {"length_ft": 21, "height_ft": 10, "width_ft": 7, "fuel_type": FuelType.GAS,
        "electrical_amps": 30},
    C: {"length_ft": 31, "height_ft": 12, "width_ft": 8.5, "fuel_type": FuelType.GAS,
        "electrical_amps": 30},
    TT: {"length_ft": 30, "height_ft": 11.5, "width_ft": 8.5, "fuel_type": FuelType.GAS,
         "electrical_amps": 30},
    FW: {"length_ft": 38, "height_ft": 13.5, "width_ft": 8.5, "fuel_type": FuelType.GAS,
         "electrical_amps": 50},
}  # fmt: skip

REQUIRED = ("length_ft", "height_ft")

INSTRUCTIONS = """From this RV manufacturer's spec page, give the numbers for the named \
floorplan (or, when none is named, the largest floorplan): exterior length, height and width \
in feet, GVWR in pounds, fuel tank in gallons, fuel type, and shore power amps (30 or 50). Use \
null for anything the page doesn't state; never guess."""


class Specs(BaseModel):
    """What a spec page states. Null means not stated."""

    length_ft: float | None = None
    height_ft: float | None = None
    width_ft: float | None = None
    gvwr_lbs: float | None = None
    fuel_tank_gal: float | None = None
    fuel_type: FuelType | None = None
    electrical_amps: int | None = None


def spec_url(rv: RVIdentity) -> str | None:
    if rv.make not in SPEC_PAGES or rv.rv_class is None:
        return None
    template, segments = SPEC_PAGES[rv.make]
    segment = segments.get(rv.rv_class)
    slug = re.sub(r"[^a-z0-9]+", "-", rv.model.lower()).strip("-")
    return template.format(segment=segment, slug=slug) if segment else None


def feet(value: str) -> float | None:
    """`32'9"` -> 32.75, `11'` -> 11.0, `8'5.5"` -> 8.458."""
    m = re.fullmatch(r"\s*(\d+)\s*'\s*(?:(\d+(?:\.\d+)?)\s*\"?)?\s*", value)
    return round(int(m.group(1)) + float(m.group(2) or 0) / 12, 3) if m else None


def number(value: str) -> float | None:
    m = re.fullmatch(r"\s*([\d,]+(?:\.\d+)?)\s*", value)
    return float(m.group(1).replace(",", "")) if m else None


class _Tables(HTMLParser):
    """Every table row as a list of cell texts, plus the page's visible text."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.text: list[str] = []
        self._cell: list[str] | None = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "button", "sup"}:
            self._skip += 1
        elif tag == "tr":
            self.rows.append([])
        elif tag in {"td", "th"}:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in {"script", "style", "button", "sup"}:
            self._skip = max(0, self._skip - 1)
        elif tag in {"td", "th"} and self._cell is not None and self.rows:
            self.rows[-1].append(" ".join("".join(self._cell).split()))
            self._cell = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._cell is not None:
            self._cell.append(data)
        if data.strip():
            self.text.append(data.strip())


def _norm_plan(plan: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", plan.upper())


def read_spec_table(html: str, floorplan: str | None) -> Specs | None:
    """Read the spec table, or None when the page has none.

    With no floorplan, or one the page doesn't list, each number is the largest across
    floorplans, so length and height are never understated.
    """
    page = _Tables()
    page.feed(html)
    header = next((r for r in page.rows if r and r[0].lower() == "details"), None)
    if not header or len(header) < 2:
        return None
    plans = [_norm_plan(p) for p in header[1:]]
    wanted = _norm_plan(floorplan or "")
    col = plans.index(wanted) if wanted in plans else None

    found: dict = {}
    for row in page.rows:
        label = row[0].lower() if row else ""
        field = next((f for key, f in ROWS.items() if label.startswith(key)), None)
        if field is None or field in found or len(row) != len(header):
            continue
        parse = feet if field.endswith("_ft") else number
        values = [parse(v) for v in row[1:]]
        if col is not None:
            value = values[col]
        else:
            value = max((v for v in values if v is not None), default=None)
        if value is not None:
            found[field] = value
    if not found:
        return None

    chassis = " ".join(t for t in page.text if "chassis" in t.lower()).lower()
    if chassis:
        found["fuel_type"] = FuelType.DIESEL if "diesel" in chassis else FuelType.GAS
    text = " ".join(page.text)
    if amps := re.search(r"\b(30|50)[- ]amp\.?\s[^.]{0,60}?(power cord|service)", text, re.I):
        found["electrical_amps"] = int(amps.group(1))
    return Specs(**found)


def page_text(html: str) -> str:
    page = _Tables()
    page.feed(html)
    return "\n".join(page.text)


def ask_claude(
    html: str,
    rv: RVIdentity,
    *,
    client: anthropic.Anthropic | None = None,
    cache_dir: Path | None = None,
) -> Specs:
    """Claude reads a spec page that has no table. Answers are cached by page and floorplan."""
    name = " ".join(str(p) for p in (rv.year, rv.make, rv.model, rv.floorplan) if p)
    prompt = f"RV: {name}\n\nSpec page text:\n{page_text(html)[:60_000]}"
    key = hashlib.sha256(json.dumps([MODEL, INSTRUCTIONS, prompt]).encode()).hexdigest()
    path = cache_dir / "rv_specs" / f"{key}.json" if cache_dir else None
    if path and path.exists():
        return Specs.model_validate_json(path.read_text())

    client = client or anthropic.Anthropic()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=2048,
        system=INSTRUCTIONS,
        messages=[{"role": "user", "content": prompt}],
        output_format=Specs,
        output_config={"effort": "low"},
    )
    specs = response.parsed_output
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(specs.model_dump_json())
    return specs


def plausible(specs: Specs, rv_class: RVClass) -> Specs:
    """Drop any number outside the plausible range for the class."""
    ranges = RANGES[rv_class] | COMMON
    kept = {
        f: v
        for f, v in specs.model_dump().items()
        if v is None or f not in ranges or ranges[f][0] <= v <= ranges[f][1]
    }
    if kept.get("electrical_amps") not in {None, 30, 50}:
        kept["electrical_amps"] = None
    return Specs(**kept)


def lookup_rv(
    rv: RVIdentity,
    http: CachedClient,
    *,
    overrides: dict | None = None,
    claude: anthropic.Anthropic | None = None,
    cache_dir: Path | None = None,
) -> RVProfile:
    """The RV's dimensions: spec page, then traveler overrides on top, then class estimates.

    `claude` is used only for a spec page with no readable table; pass None to skip it.
    """
    if rv.rv_class is None:
        raise ValueError(f"Need the RV class of the {rv.make} {rv.model} to look up its size.")
    url = spec_url(rv)
    specs = Specs()
    if url:
        response = http.get(url)
        if response.is_success:
            specs = read_spec_table(response.text, rv.floorplan) or (
                ask_claude(response.text, rv, client=claude, cache_dir=cache_dir)
                if claude
                else Specs()
            )
    from_page = plausible(specs, rv.rv_class).model_dump(exclude_none=True)
    stated = from_page | {k: v for k, v in (overrides or {}).items() if v is not None}

    estimate = ESTIMATES[rv.rv_class]
    estimated = any(f not in stated for f in REQUIRED)
    fields = (estimate if estimated else {"fuel_type": estimate["fuel_type"]}) | stated
    return RVProfile(
        make=rv.make,
        model=" ".join(p for p in (rv.model, rv.floorplan) if p),
        year=rv.year,
        rv_class=rv.rv_class,
        source_url=url if from_page else None,
        estimated=estimated,
        **fields,
    )
