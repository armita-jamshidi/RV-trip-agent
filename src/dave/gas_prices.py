"""Weekly gas and diesel price snapshots from EIA, stored on disk so we keep our own history.

Station-level prices are not used: no free source allows collecting them (decision 2026-10-09).
EIA publishes retail averages every Monday for the U.S., its regions (PADDs and sub-regions) and
nine states (CA, CO, FL, MA, MN, NY, OH, TX, WA). `collect` saves each week once, as
`<store>/<period>.json`, so running it daily is cheap and harmless. `price_for` answers with the
most specific area that covers a state: the state itself, else its region, else the U.S.
Every answer is an average, so callers must label fuel costs built on it as estimates.
"""

from datetime import date, timedelta
from pathlib import Path

from pydantic import TypeAdapter

from dave.http import CachedClient, SourceError
from dave.models import FuelType, GasPrice

EIA_URL = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"
STORE = Path("data/gas_prices")
PRODUCTS = {"EPMR": FuelType.GAS, "EPD2D": FuelType.DIESEL}  # regular gasoline, No. 2 diesel
PAGE = 5000

# State to EIA region. West Coast states other than California use "West Coast less California".
REGIONS = {
    "R1X": "CT ME MA NH RI VT",
    "R1Y": "DE DC MD NJ NY PA",
    "R1Z": "FL GA NC SC VA WV",
    "R20": "IL IN IA KS KY MI MN MO NE ND SD OH OK TN WI",
    "R30": "AL AR LA MS NM TX",
    "R40": "CO ID MT UT WY",
    "R5XCA": "AK AZ HI NV OR WA",
    "R50": "CA",
}
STATE_REGION = {s: region for region, states in REGIONS.items() for s in states.split()}
PARENT = {"R1X": "R10", "R1Y": "R10", "R1Z": "R10", "R5XCA": "R50"}
_rows = TypeAdapter(list[GasPrice])


def fetch(http: CachedClient, api_key: str, since: date) -> list[GasPrice]:
    """Weekly U.S., region and state averages for regular gas and diesel since `since`."""
    prices: list[GasPrice] = []
    offset = 0
    while True:
        params = {
            "frequency": "weekly",
            "data[]": "value",
            "facets[product][]": list(PRODUCTS),
            "start": since.isoformat(),
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "offset": offset,
            "length": PAGE,
        }
        response = http.get(EIA_URL, params=params, secret_params={"api_key": api_key})
        if not response.is_success:
            raise SourceError(f"EIA answered {response.status_code}: {response.text[:200]}")
        body = response.json()["response"]
        rows = body.get("data", [])
        prices += [p for row in rows if (p := _parse(row))]
        offset += len(rows)
        if not rows or offset >= int(body.get("total", 0)):
            return prices


def _parse(row: dict) -> GasPrice | None:
    """Keep U.S., region and state rows with a price; skip city series and empty weeks."""
    area = row.get("duoarea", "")
    if not (area == "NUS" or area.startswith(("R", "S"))) or row.get("value") in (None, ""):
        return None
    return GasPrice(
        period=date.fromisoformat(row["period"]),
        area=area,
        area_name=row.get("area-name") or area,
        fuel_type=PRODUCTS[row["product"]],
        usd_per_gal=float(row["value"]),
    )


def collect(
    http: CachedClient, api_key: str, store: Path = STORE, *, weeks: int = 10, today: date
) -> list[date]:
    """Save every published week from the last `weeks` that is new or revised. Returns those."""
    by_week: dict[date, list[GasPrice]] = {}
    for p in fetch(http, api_key, today - timedelta(weeks=weeks)):
        by_week.setdefault(p.period, []).append(p)
    saved = []
    store.mkdir(parents=True, exist_ok=True)
    for period, prices in sorted(by_week.items()):
        path = store / f"{period.isoformat()}.json"
        text = _rows.dump_json(sorted(prices, key=lambda p: (p.area, p.fuel_type)), indent=1)
        if not path.exists() or path.read_bytes() != text:
            path.write_bytes(text)
            saved.append(period)
    return saved


def load(store: Path = STORE) -> list[GasPrice]:
    return [p for f in sorted(store.glob("*.json")) for p in _rows.validate_json(f.read_bytes())]


def price_for(
    prices: list[GasPrice], state: str, fuel_type: FuelType, on: date, *, days: int = 60
) -> GasPrice | None:
    """The average price for `state` over the `days` before `on`, from its most specific area.

    Returned as one GasPrice dated the latest week used. A trip after the newest snapshot uses
    the newest two months, so a single week's spike doesn't set the whole estimate.
    """
    if not prices:
        return None
    end = min(on, max(p.period for p in prices))
    start = end - timedelta(days=days)
    window = [p for p in prices if p.fuel_type == fuel_type and start < p.period <= end]
    for area in _areas(state.upper()):
        found = [p for p in window if p.area == area]
        if found:
            latest = max(found, key=lambda p: p.period)
            average = sum(p.usd_per_gal for p in found) / len(found)
            return latest.model_copy(update={"usd_per_gal": round(average, 3)})
    return None


def _areas(state: str) -> list[str]:
    region = STATE_REGION.get(state)
    chain = [f"S{state}"]
    while region:
        chain.append(region)
        region = PARENT.get(region)
    return [*chain, "NUS"]


def coverage(prices: list[GasPrice]) -> dict:
    """What the stored snapshots cover: weeks, and which states have their own series."""
    weeks = sorted({p.period for p in prices})
    own = sorted({p.area[1:] for p in prices if p.area.startswith("S")})
    return {
        "weeks": len(weeks),
        "first": weeks[0].isoformat() if weeks else None,
        "last": weeks[-1].isoformat() if weeks else None,
        "states_with_own_series": own,
        "states_using_region": sorted(set(STATE_REGION) - set(own)),
    }
