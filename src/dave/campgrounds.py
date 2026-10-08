"""Campgrounds from free sources, normalized into `Campground`.

- Recreation.gov RIDB: federal campgrounds with per-site hookups, amperage and RV length.
- Foursquare OS Places: private campgrounds and RV parks. Only free ("Pro") fields are
  requested, so these come without hookups, length or rating; later tasks fill gaps.

The same place listed by both sources (or found from two overlapping search areas) is kept
once, preferring the RIDB record because it has site details.
"""

import re
from collections.abc import Iterable
from difflib import SequenceMatcher
from html import unescape
from pathlib import Path

from dave import foursquare
from dave.geo import Point, haversine_miles
from dave.http import CachedClient, SourceError
from dave.models import Campground, CampSite, Hookup, Place

DEMO_REGIONS = Path(__file__).resolve().parents[2] / "demo" / "regions.json"

RIDB_URL = "https://ridb.recreation.gov/api/v1"
RIDB_PAGE = 50
RECREATION_GOV_BOOKING = "https://www.recreation.gov/camping/campgrounds/{}"

FSQ_CAMPING = ("4bf58dd8d48988d1e4941735", "52f2ab2ebcbc57f1066b8b53")  # Campground, RV Park
FSQ_FIELDS = "fsq_place_id,name,latitude,longitude,location,website"

SAME_PLACE_MILES = 0.5
SAME_SPOT_MILES = 0.1  # this close, names need not match
GENERIC_WORDS = {"campground", "campgrounds", "camp", "rv", "park", "resort", "the", "and"}

RV_EQUIPMENT = re.compile(r"\brv\b|trailer|fifth wheel|motorhome|camper van", re.IGNORECASE)
YES = {"y", "yes", "true"}


# --- Recreation.gov RIDB ------------------------------------------------------------


def ridb_campgrounds(
    center: Point, radius_miles: float, http: CachedClient, api_key: str
) -> list[Campground]:
    params = {"latitude": center[0], "longitude": center[1], "radius": radius_miles}
    facilities = _ridb_all(http, f"{RIDB_URL}/facilities", params, api_key)
    out = []
    for f in facilities:
        if f.get("FacilityTypeDescription") != "Campground":
            continue
        raw_sites = _ridb_all(
            http, f"{RIDB_URL}/facilities/{f['FacilityID']}/campsites", {}, api_key
        )
        out.append(ridb_campground(f, [s for s in map(parse_site, raw_sites) if s]))
    return out


def ridb_campground(facility: dict, sites: list[CampSite]) -> Campground:
    lengths = [s.max_rv_length_ft for s in sites if s.max_rv_length_ft]
    fid = facility["FacilityID"]
    name = _tidy_name(facility["FacilityName"])
    return Campground(
        name=name,
        location=Place(
            name=name,
            lat=facility["FacilityLatitude"],
            lon=facility["FacilityLongitude"],
        ),
        description=_plain_text(facility.get("FacilityDescription") or "") or None,
        hookups=set().union(*(s.hookups for s in sites)),
        max_rv_length_ft=max(lengths, default=None),
        electrical_amps=set().union(*(s.electrical_amps for s in sites)),
        sites=sites,
        nightly_price_usd=_lowest_dollars(facility.get("FacilityUseFeeDescription") or ""),
        booking_url=RECREATION_GOV_BOOKING.format(fid) if facility.get("Reservable") else None,
        source="ridb",
    )


def parse_site(raw: dict) -> CampSite | None:
    """An RV-usable site, or None for tent-only, group and other non-RV sites."""
    attrs = {
        a["AttributeName"].strip().lower(): str(a["AttributeValue"]).strip().lower()
        for a in raw.get("ATTRIBUTES") or []
    }
    rv_equipment = [
        e for e in raw.get("PERMITTEDEQUIPMENT") or [] if RV_EQUIPMENT.search(e["EquipmentName"])
    ]
    site_type = (raw.get("CampsiteType") or "").lower()
    if not rv_equipment and "rv" not in site_type.split():
        return None

    lengths = [float(e["MaxLength"]) for e in rv_equipment if e.get("MaxLength")]
    if not lengths and _number(attrs.get("max vehicle length")):
        lengths = [_number(attrs["max vehicle length"])]

    power = attrs.get("electricity hookup", "")
    amps = {int(a) for a in re.findall(r"\d+", power)}
    hookups = set()
    if amps or power in YES or ("electric" in site_type and "nonelectric" not in site_type):
        hookups.add(Hookup.ELECTRIC)
    if attrs.get("water hookup") in YES:
        hookups.add(Hookup.WATER)
    if attrs.get("sewer hookup") in YES:
        hookups.add(Hookup.SEWER)
    if attrs.get("full hookup") in YES:
        hookups |= set(Hookup)

    return CampSite(
        name=str(raw.get("CampsiteName") or raw.get("CampsiteID")),
        hookups=hookups,
        max_rv_length_ft=max(lengths, default=None),
        electrical_amps=amps,
    )


def _ridb_all(http: CachedClient, url: str, params: dict, api_key: str) -> list[dict]:
    records, offset = [], 0
    while True:
        response = http.get(
            url,
            params={**params, "limit": RIDB_PAGE, "offset": offset},
            headers={"apikey": api_key},
        )
        if not response.is_success:
            raise SourceError(f"Recreation.gov returned {response.status_code} for {url}")
        data = response.json()
        page = data.get("RECDATA") or []
        records += page
        offset += len(page)
        total = data.get("METADATA", {}).get("RESULTS", {}).get("TOTAL_COUNT", 0)
        if not page or offset >= total:
            return records


# --- Foursquare OS Places -------------------------------------------------------------


def foursquare_campgrounds(
    center: Point, radius_miles: float, http: CachedClient, api_key: str
) -> list[Campground]:
    places = foursquare.search(
        center, radius_miles, http, api_key, categories=FSQ_CAMPING, fields=FSQ_FIELDS
    )
    return [foursquare_campground(p) for p in places]


def foursquare_campground(place: dict) -> Campground:
    return Campground(
        name=place["name"],
        location=Place(
            name=place["name"],
            lat=place["latitude"],
            lon=place["longitude"],
            address=(place.get("location") or {}).get("formatted_address"),
        ),
        booking_url=place.get("website"),
        source="foursquare",
    )


# --- Merging ----------------------------------------------------------------------------


def same_campground(a: Campground, b: Campground) -> bool:
    miles = haversine_miles((a.location.lat, a.location.lon), (b.location.lat, b.location.lon))
    if miles <= SAME_SPOT_MILES:
        return True
    return miles <= SAME_PLACE_MILES and _name_similarity(a.name, b.name) >= 0.6


def merge(campgrounds: Iterable[Campground]) -> list[Campground]:
    """Drop duplicates, keeping RIDB records over others and earlier records over later ones."""
    ordered = sorted(campgrounds, key=lambda c: c.source != "ridb")
    kept: list[Campground] = []
    for c in ordered:
        if not any(same_campground(c, k) for k in kept):
            kept.append(c)
    return kept


def ingest(
    centers: list[Point],
    radius_miles: float,
    http: CachedClient,
    *,
    ridb_key: str,
    foursquare_key: str,
) -> list[Campground]:
    found = []
    for center in centers:
        found += ridb_campgrounds(center, radius_miles, http, ridb_key)
        found += foursquare_campgrounds(center, radius_miles, http, foursquare_key)
    return merge(found)


def _plain_text(html: str) -> str:
    """RIDB descriptions are HTML; keep the words."""
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def _tidy_name(name: str) -> str:
    """RIDB names are often ALL CAPS; make those readable and leave the rest alone."""
    name = name.strip()
    if not name.isupper():
        return name
    return re.sub(r"[a-z]+(?:'[a-z]+)?", lambda m: m.group().capitalize(), name.lower())


def _name_similarity(a: str, b: str) -> float:
    def core(name: str) -> str:
        words = re.findall(r"[a-z0-9]+", name.lower())
        return " ".join(w for w in words if w not in GENERIC_WORDS)

    return SequenceMatcher(None, core(a), core(b)).ratio()


def _lowest_dollars(text: str) -> float | None:
    amounts = [float(x.replace(",", "")) for x in re.findall(r"\$\s?(\d[\d,]*(?:\.\d+)?)", text)]
    return min(amounts, default=None)


def _number(text: str | None) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", text or "")
    return float(match.group()) if match and float(match.group()) > 0 else None
