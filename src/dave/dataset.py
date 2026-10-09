"""Training data for the fine-tuned trip request parser (T29): request text -> `Extracted`.

Requests are composed from clauses (route, RV, nights, dates, budget, people, interests, rules)
in several voices, from the personas in `customers/personas.md`. Each label is built alongside
its text, so it is right by construction: what the traveler said, null for what they did not.
The test set uses places the training set never mentions, so it measures generalization.
"""

import json
import random
from datetime import date, timedelta
from pathlib import Path

from dave.models import Hookup
from dave.parser import Extracted, to_result
from dave.rv_catalog import CATALOG

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "training" / "data"
SEED = 28

ORIGINS = [
    ("Denver", "CO"),
    ("Phoenix", "AZ"),
    ("Austin", "TX"),
    ("Dallas", "TX"),
    ("Houston", "TX"),
    ("Chicago", "IL"),
    ("Seattle", "WA"),
    ("Portland", "OR"),
    ("Salt Lake City", "UT"),
    ("Albuquerque", "NM"),
    ("Las Vegas", "NV"),
    ("Sacramento", "CA"),
    ("San Diego", "CA"),
    ("Boise", "ID"),
    ("Minneapolis", "MN"),
    ("Kansas City", "MO"),
    ("St. Louis", "MO"),
    ("Nashville", "TN"),
    ("Atlanta", "GA"),
    ("Charlotte", "NC"),
    ("Orlando", "FL"),
    ("Tampa", "FL"),
    ("Columbus", "OH"),
    ("Indianapolis", "IN"),
    ("Detroit", "MI"),
    ("Milwaukee", "WI"),
    ("Omaha", "NE"),
    ("Oklahoma City", "OK"),
    ("Memphis", "TN"),
    ("Louisville", "KY"),
    ("Pittsburgh", "PA"),
    ("Richmond", "VA"),
    ("Spokane", "WA"),
    ("Tucson", "AZ"),
    ("San Antonio", "TX"),
    ("Reno", "NV"),
    ("Fresno", "CA"),
    ("Savannah", "GA"),
    ("Albany", "NY"),
    ("Des Moines", "IA"),
]
TEST_ORIGINS = [
    ("Bozeman", "MT"),
    ("Rapid City", "SD"),
    ("El Paso", "TX"),
    ("Little Rock", "AR"),
    ("Raleigh", "NC"),
    ("Jacksonville", "FL"),
    ("Buffalo", "NY"),
    ("Tulsa", "OK"),
]

# (place as the traveler says it, its state, a sight they might insist on near there)
DESTINATIONS = [
    ("Moab", "UT", "Arches National Park"),
    ("Yellowstone", "WY", "Old Faithful"),
    ("the Grand Canyon", "AZ", "Desert View Watchtower"),
    ("Zion", "UT", "Angels Landing"),
    ("Big Bend National Park", "TX", None),
    ("Glacier National Park", "MT", "Going-to-the-Sun Road"),
    ("Great Smoky Mountains National Park", "TN", "Cades Cove"),
    ("Yosemite", "CA", "Glacier Point"),
    ("Rocky Mountain National Park", "CO", None),
    ("Sedona", "AZ", "Grand Canyon National Park"),
    ("Santa Fe", "NM", "Bandelier National Monument"),
    ("Gulf Shores", "AL", None),
    ("Myrtle Beach", "SC", None),
    ("Key West", "FL", None),
    ("Branson", "MO", None),
    ("Hot Springs", "AR", "Hot Springs National Park"),
    ("Mount Rushmore", "SD", "Badlands National Park"),
    ("Bryce Canyon", "UT", None),
    ("Joshua Tree", "CA", None),
    ("Shenandoah", "VA", "Skyline Drive"),
    ("Niagara Falls", "NY", None),
    ("Traverse City", "MI", "Sleeping Bear Dunes"),
    ("Galveston", "TX", None),
    ("Jackson Hole", "WY", "Grand Teton National Park"),
    ("Durango", "CO", "Mesa Verde National Park"),
    ("Bar Harbor", "ME", "Acadia National Park"),
]
TEST_DESTINATIONS = [
    ("Crater Lake", "OR", None),
    ("Olympic National Park", "WA", "Hurricane Ridge"),
    ("Taos", "NM", "Rio Grande Gorge Bridge"),
    ("Mammoth Cave", "KY", None),
    ("Marfa", "TX", None),
    ("the Outer Banks", "NC", "Cape Hatteras Lighthouse"),
]

PERSONAS = {
    "retired explorers": {
        "classes": {"class_a", "fifth_wheel"},
        "people": [(None, None), ("my wife and I", 2), ("retired couple here", 2)],
        "budget": (2000, 6000),
        "leans": {"nature": 0.9, "food": 0.5},
    },
    "young family": {
        "classes": {"class_c", "travel_trailer"},
        "people": [("family of 4", 4), ("family of five", 5), ("two adults and two kids", 4)],
        "budget": (800, 2500),
        "leans": {"museums": 0.9, "food": 0.5},
    },
    "weekend van-lifer": {
        "classes": {"class_b"},
        "people": [(None, None), ("just me", 1), ("me and my partner", 2), ("solo", 1)],
        "budget": (300, 1500),
        "leans": {"largest_x": 0.9, "food": 0.9},
    },
}

INTEREST_PHRASES = {
    "nature": {
        0.9: ["love hiking", "big on national parks", "want big views and good trails"],
        0.5: ["maybe a hike or two", "some nature would be nice"],
        0.1: ["not really outdoorsy"],
    },
    "museums": {
        0.9: ["museum nerds", "love a good science museum", "really into history museums"],
        0.5: ["a museum if it rains", "open to a museum stop"],
        0.1: ["skip the museums"],
    },
    "largest_x": {
        0.9: [
            "love weird roadside attractions like the world's largest ball of twine",
            "giant statues and roadside oddities are our thing",
        ],
        0.5: ["a quirky roadside stop or two"],
        0.1: ["no tourist-trap roadside stuff"],
    },
    "food": {
        0.9: ["we're foodies", "BBQ is a must", "want great local food"],
        0.5: ["a good diner now and then", "happy to try a local spot or two"],
        0.1: ["we cook our own meals so food isn't a priority"],
    },
}

AVOID = [
    ("no interstates", "interstates"),
    ("avoid toll roads", "toll roads"),
    ("stay out of big cities", "big cities"),
    ("no steep mountain passes", "mountain passes"),
]
HOOKUPS = [
    ("need full hookups", [Hookup.ELECTRIC, Hookup.WATER, Hookup.SEWER]),
    ("full hookups including sewer please", [Hookup.ELECTRIC, Hookup.WATER, Hookup.SEWER]),
    ("we only need electric", [Hookup.ELECTRIC]),
    ("water and electric at every site", [Hookup.ELECTRIC, Hookup.WATER]),
]
FLOORPLANS = ["31K", "28A", "24D", "26X", "37R", "22E", "29MV", "32SA", "38KA", "19D"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]  # fmt: skip
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 10: "ten"}


def _rv(rng: random.Random, persona: dict) -> tuple[str, dict]:
    fits = [(m, ln) for m in CATALOG for ln in m.lines if set(ln.classes) & persona["classes"]]
    maker, line = rng.choice(fits)
    model = line.name + (" " + rng.choice(FLOORPLANS) if rng.random() < 0.4 else "")
    year = rng.randint(2012, 2026) if rng.random() < 0.5 else None
    named_make = line.generic or rng.random() < 0.8  # generic line names need the make
    text = " ".join(str(x) for x in (year, maker.name if named_make else None, model) if x)
    label = {"rv_make": maker.name if named_make else None, "rv_model": model, "rv_year": year}
    article = "an" if text[0] in "AEIOU" else "a"
    templates = [
        f"we have {article} {{}}",
        f"our rig is {article} {{}}",
        "{}",
        f"driving {article} {{}}",
    ]
    return rng.choice(templates).format(text), label


def _start(rng: random.Random, today: date) -> tuple[str | None, date | None]:
    kind = rng.choice(["none", "none", "month_day", "iso", "weekday", "month_only", "tomorrow"])
    if kind == "none":
        return None, None
    if kind == "tomorrow":
        return "leaving tomorrow", today + timedelta(days=1)
    if kind == "month_only":
        return f"sometime in {rng.choice(MONTHS)}", None
    if kind == "weekday":
        wd = rng.randrange(7)
        ahead = (wd - today.weekday() - 1) % 7 + 1  # the coming one, never today
        return f"leaving this coming {WEEKDAYS[wd]}", today + timedelta(days=ahead)
    when = today + timedelta(days=rng.randint(3, 200))
    if kind == "iso":
        return f"starting {when.isoformat()}", when
    return f"starting {MONTHS[when.month - 1][:3]} {when.day}", when


def _nights(rng: random.Random) -> tuple[str, int]:
    n = rng.choice([2, 3, 4, 5, 6, 7, 7, 10, 14])
    phrases = {7: ["a week", "7 nights"], 14: ["two weeks", "14 nights"], 3: ["a long weekend"]}
    options = phrases.get(n, []) + [f"{n} nights", f"{NUMBER_WORDS.get(n, n)} nights"]
    return rng.choice(options), n


def _budget(rng: random.Random, lo: int, hi: int) -> tuple[str, float]:
    usd = rng.randrange(lo, hi + 1, 100)
    k = f"{usd // 1000}k" if usd % 1000 == 0 else None
    return rng.choice(
        [f"${usd:,} budget", f"budget is {usd} dollars", f"keep it under ${usd:,}"]
        + ([f"about {k} total"] if k else [])
    ), float(usd)


def _interests(rng: random.Random, leans: dict) -> tuple[list[str], dict | None]:
    picked = {k: v for k, v in leans.items() if rng.random() < 0.7}
    for k in INTEREST_PHRASES:
        if k not in picked and rng.random() < 0.2:
            picked[k] = rng.choice([0.9, 0.5, 0.1])
    if not picked:
        return [], None
    phrases = [rng.choice(INTEREST_PHRASES[k][w]) for k, w in picked.items()]
    return phrases, {k: picked.get(k) for k in INTEREST_PHRASES}


def make_example(rng: random.Random, today: date, origins: list, destinations: list) -> dict:
    """One request and its label. About one in ten leaves out something the planner needs."""
    persona_name = rng.choice(list(PERSONAS))
    persona = PERSONAS[persona_name]
    city, state = rng.choice(origins)
    spoken, dest_state, sight = rng.choice(destinations)
    label: dict = {
        "origin": f"{city}, {state}",
        "destination": f"{spoken.removeprefix('the ')}, {dest_state}",
        "round_trip": None,
        "start_date": None,
        "nights": None,
        "travelers": None,
        "rv_make": None,
        "rv_model": None,
        "rv_year": None,
        "budget_usd": None,
        "max_drive_hours_per_day": None,
        "hookups_required": None,
        "interests": None,
        "must_visit": [],
        "avoid": [],
    }
    loop = rng.random() < 0.15
    there_and_back = not loop and rng.random() < 0.15
    if loop:
        route = f"a loop out of {city}"
        label.update(destination=None, round_trip=True)
    else:
        route = f"{city} to {spoken}" + (" and back" if there_and_back else "")
        if there_and_back:
            label["round_trip"] = True
    clauses = [route]

    rv_text, rv_label = _rv(rng, persona)
    label.update(rv_label)
    nights_text, label["nights"] = _nights(rng)
    clauses += [rv_text, nights_text]

    start_text, label["start_date"] = _start(rng, today)
    people_text, label["travelers"] = rng.choice(persona["people"])
    if rng.random() < 0.7:
        budget_text, label["budget_usd"] = _budget(rng, *persona["budget"])
        clauses.append(budget_text)
    if rng.random() < 0.25:
        hours = rng.choice([3, 4, 4.5, 6])
        clauses.append(rng.choice([f"no more than {hours} hours of driving a day",
                                   f"max {hours} hrs driving per day"]))  # fmt: skip
        label["max_drive_hours_per_day"] = float(hours)
    if rng.random() < 0.2:
        hookup_text, hookups = rng.choice(HOOKUPS)
        clauses.append(hookup_text)
        label["hookups_required"] = hookups
    interest_texts, label["interests"] = _interests(rng, persona["leans"])
    if sight and not loop and rng.random() < 0.3:
        clauses.append(
            rng.choice(["have to see {}", "{} is a must", "want to stop at {}"]).format(sight)
        )
        label["must_visit"] = [sight]
    if rng.random() < 0.2:
        avoid_text, avoid = rng.choice(AVOID)
        clauses.append(avoid_text)
        label["avoid"] = [avoid]
    clauses += [t for t in (start_text, people_text) if t] + interest_texts

    # Leave out an essential field now and then, so the model learns to answer null.
    if rng.random() < 0.1:
        drop = rng.choice(["origin", "nights", "rv"])
        if drop == "origin":
            clauses[0] = (
                "a loop trip"
                if loop
                else f"headed to {spoken}" + (" and back" if there_and_back else "")
            )
            label["origin"] = None
        elif drop == "nights":
            clauses.remove(nights_text)
            label["nights"] = None
        else:
            clauses.remove(rv_text)
            label.update(rv_make=None, rv_model=None, rv_year=None)

    return {"today": today.isoformat(), "request": _voice(rng, clauses), "extracted": label,
            "persona": persona_name}  # fmt: skip


def _voice(rng: random.Random, clauses: list[str]) -> str:
    """Join clauses as a casual message, a terse list, or a formal TravelPlanner-style ask."""
    head, rest = clauses[0], clauses[1:]
    rng.shuffle(rest)
    style = rng.choice(["casual", "terse", "formal"])
    if style == "terse":
        text = "; ".join([head, *rest])
    elif style == "formal":
        text = (
            f"Please help me plan an RV trip: {head}. "
            + ". ".join(c[0].upper() + c[1:] for c in rest)
            + "."
        )
    else:
        text = f"{head[0].upper()}{head[1:]}, " + ", ".join(rest) + "."
    return text.lower() if rng.random() < 0.1 else text


def build(n: int, seed: int, origins: list, destinations: list) -> list[dict]:
    rng = random.Random(seed)
    rows, seen = [], set()
    while len(rows) < n:
        today = date(2026, 1, 1) + timedelta(days=rng.randrange(365))
        row = make_example(rng, today, origins, destinations)
        if row["request"] not in seen:
            seen.add(row["request"])
            rows.append({"id": len(rows) + 1, **row})
    return rows


def validate(row: dict) -> None:
    """The label parses as `Extracted` and yields a ConstraintSpec or a follow-up question."""
    result = to_result(Extracted.model_validate(row["extracted"]))
    assert (result.spec is None) == bool(result.missing), row["id"]


def write(out: Path = OUT, n_train: int = 2000, n_test: int = 100) -> dict[str, int]:
    splits = {
        "train": build(n_train, SEED, ORIGINS, DESTINATIONS),
        "test": build(n_test, SEED + 1, TEST_ORIGINS, TEST_DESTINATIONS),
    }
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in splits.items():
        for row in rows:
            validate(row)
        lines = (json.dumps(row, default=str) for row in rows)
        (out / f"{name}.jsonl").write_text("\n".join(lines) + "\n")
    return {name: len(rows) for name, rows in splits.items()}


if __name__ == "__main__":
    print(write())
