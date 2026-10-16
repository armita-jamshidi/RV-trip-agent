"""A whole trip from a parsed request: the pipeline behind `dave plan`.

RV size (T06, T07), a route the RV clears (T09, T10) cut into days of at most the daily limit
(T11), stops and meals (T18 to T20, with a Foursquare key), a campground for each night
(T13 to T17), fuel and fill-ups (T21 to T23), the budget (T24), and booking proposals for
the campgrounds and tickets (T25 to T27). The result renders with T33, which runs the
validator, so a plan that breaks a rule is shown as "Not final" with what to fix.

Gas stations and their posted prices come from Google Places when its key is set (T37), else
from Foursquare, priced at EIA averages.

Extra nights beyond the driving days are spent at the destination; on a round trip the drive
home starts after them. Whatever a missing key or source leaves out is said in the notes.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

import httpx

from dave import google_places
from dave.budget import DayCost, fit_budget
from dave.campground_booking import campground_proposals
from dave.campgrounds import ingest
from dave.clearance import ClearanceCheck, clear_route
from dave.corridor import locate
from dave.days import split_days, stay_nights
from dave.fillups import plan_fillups, stations_along
from dave.fuel_cost import FuelEstimate, estimate_fuel, mpg
from dave.geocode import geocode
from dave.http import CachedClient, SourceError
from dave.models import ConstraintSpec, DayLeg, FuelType, GasPrice, GasStation, Itinerary
from dave.overnight import overnight_centers, pick_campgrounds
from dave.pitstops import find_pitstops
from dave.render import render_markdown
from dave.restaurants import plan_meals
from dave.routing import route
from dave.rv_catalog import identify_rv
from dave.rv_specs import lookup_rv
from dave.store.vectors import Embedder
from dave.validator import validate_itinerary

DEFAULT_LEAD_DAYS = 14  # with no start date, plan for two weeks out
CAMPGROUND_SEARCH_MILES = 30.0


@dataclass
class Sources:
    http: CachedClient
    embedder: Embedder
    gas_prices: list[GasPrice]
    ridb_key: str | None
    foursquare_key: str | None = None
    google_places_key: str | None = None


@dataclass
class TripPlan:
    itinerary: Itinerary | None = None
    per_day: list[DayCost] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    question: str | None = None  # what to ask the traveler when no plan could be made

    @property
    def errors(self) -> list[str]:
        return validate_itinerary(self.itinerary) if self.itinerary else []

    def markdown(self) -> str:
        if self.itinerary is None:
            return f"{self.question}\n"
        return render_markdown(self.itinerary, per_day=self.per_day, notes=self.notes)


def plan_request(request: str, *, today: date | None = None) -> TripPlan:
    """`dave plan` and the dashboard: parse the request, then plan it with the configured keys.
    When the request is missing something essential, the plan is the question to ask."""
    from dave import gas_prices
    from dave.config import load_settings
    from dave.parser import parse_request
    from dave.small_parser import small_parser
    from dave.store.vectors import FastEmbedder

    settings = load_settings()
    with CachedClient(settings.cache_dir / "http", offline=settings.offline) as http:
        parsed = parse_request(
            request, small=small_parser(settings, http), cache_dir=settings.cache_dir
        )
        if parsed.question:
            return TripPlan(question=parsed.question)
        sources = Sources(
            http=http,
            embedder=FastEmbedder(settings.cache_dir / "models", settings.embed_model),
            gas_prices=gas_prices.load(gas_prices.STORE),
            ridb_key=settings.keys.get("RIDB_API_KEY"),
            foursquare_key=settings.keys.get("FOURSQUARE_API_KEY"),
            google_places_key=settings.keys.get("GOOGLE_PLACES_API_KEY"),
        )
        return plan_trip(request, parsed.spec, sources, today=today or date.today())


def plan_trip(request: str, spec: ConstraintSpec, sources: Sources, *, today: date) -> TripPlan:
    http, notes = sources.http, []

    found = identify_rv(request)
    if found.match is None or found.match.rv_class is None:
        names = ", ".join(f"{c.make} {c.model}" for c in found.candidates[:5])
        hint = f" For example: {names}." if names else ""
        return TripPlan(question=f"Which RV is it? Give its make, model and class.{hint}")
    rv = lookup_rv(found.match, http)
    if rv.estimated:
        notes.append(
            f"RV size and mileage are {rv.rv_class.value.replace('_', ' ')} averages; "
            "give the length and height to check bridges and sites exactly."
        )

    if spec.round_trip and spec.destination == spec.origin:
        return TripPlan(question="Where should the loop turn around?")
    origin, destination = geocode(spec.origin, http), geocode(spec.destination, http)
    legs = [(origin, destination)] + ([(destination, origin)] if spec.round_trip else [])
    driven: list[list[DayLeg]] = []
    for start, end in legs:
        try:
            checked = clear_route(start, end, rv.height_ft, http)
        except (SourceError, httpx.TransportError) as e:
            # Unknown clearances fail rather than pass: the plan shows, marked "Not final".
            checked = ClearanceCheck(route([start, end], http))
            unchecked = f"bridge heights weren't checked ({e}); rerun before driving this day."
        else:
            unchecked = None
        days = split_days(checked.route, start, end, max_hours=spec.max_drive_hours_per_day)
        days = _with_clearances(days, checked)
        if unchecked:
            days = [d.model_copy(update={"clearance_warnings": [unchecked]}) for d in days]
        driven.append(days)
        notes += checked.notes()
        if checked.rerouted:
            notes.append(f"{start.name} to {end.name} is rerouted around a low bridge.")

    nights_driving = sum(len(d) for d in driven) - (1 if spec.round_trip else 0)
    if nights_driving > spec.nights:
        notes.append(
            f"Driving at most {spec.max_drive_hours_per_day:g} h a day takes {nights_driving} "
            f"nights, not {spec.nights}; planned with {nights_driving}."
        )
        spec = spec.model_copy(update={"nights": nights_driving})
    extra = spec.nights - nights_driving
    if spec.start_date is None:
        spec = spec.model_copy(update={"start_date": today + timedelta(days=DEFAULT_LEAD_DAYS)})
        notes.append(
            f"No start date given; planned from {spec.start_date:%a %b %d}. "
            "Give a date for real prices and availability."
        )
    days = _dated(driven, spec.start_date, extra)

    if sources.foursquare_key:
        days = find_pitstops(
            days,
            spec.interests,
            http,
            sources.foursquare_key,
            rv_length_ft=rv.total_length_ft,
            max_hours=spec.max_drive_hours_per_day,
        )
        days = plan_meals(days, http, sources.foursquare_key, rv_length_ft=rv.total_length_ft)
    elif sources.google_places_key:
        notes.append("No stops or food: they need a FOURSQUARE_API_KEY.")
    else:
        notes.append("No stops, food or gas stations: they need a FOURSQUARE_API_KEY.")

    night_days = days[:-1] if spec.round_trip else days
    if sources.ridb_key:
        campgrounds = ingest(
            overnight_centers(night_days),
            CAMPGROUND_SEARCH_MILES,
            http,
            ridb_key=sources.ridb_key,
            foursquare_key=sources.foursquare_key,
        )
    else:
        campgrounds = []
        notes.append("No campgrounds: they need a RIDB_API_KEY.")
    picks = pick_campgrounds(
        days, campgrounds, rv, spec.hookups_required, sources.embedder, round_trip=spec.round_trip
    )
    notes += [p.note for p in picks if p.pick is None]

    stations, prices = _stations(days, rv.fuel_type, sources, notes, today)
    try:
        fuel = estimate_fuel(days, rv, prices, today=today)
    except ValueError as e:
        notes.append(f"{e} Fuel is left out of the costs.")
        fuel = FuelEstimate([], *mpg(rv), rv.fuel_type)
    if stations and fuel.days:
        fills = plan_fillups(days, rv, stations, prices, today=today)
        at = {d.day: [f.station for f in fills.stops if f.day == d.day] for d in days}
        days = [d.model_copy(update={"gas_stations": at[d.day]}) for d in days]
        notes += fills.warnings

    last_stay = 0 if spec.round_trip else 1 + extra
    budget = fit_budget(
        days, picks, fuel, spec.budget_usd, extra_nights=0 if spec.round_trip else extra
    )
    notes += budget.changes
    if budget.over_by_usd:
        notes.append(budget.summary()[-1])
    nights_at = stay_nights(budget.days, last_stay)
    stays = {d.day: n for d, n in zip(budget.days, nights_at, strict=True)}
    camp_bookings, unpriced = campground_proposals(budget.days, budget.picks, stays)
    notes += unpriced

    itinerary = Itinerary(
        spec=spec,
        rv=rv,
        days=budget.days,
        costs=budget.costs,
        bookings=camp_bookings + budget.tickets,
    )
    return TripPlan(itinerary, budget.per_day, notes)


def _stations(
    days: list[DayLeg], fuel_type: FuelType, sources: Sources, notes: list[str], today: date
) -> tuple[list[GasStation], list[GasPrice]]:
    """Stations along the route, and the prices to plan with: EIA's averages, overridden by
    the posted station prices Google has for the states the route crosses."""
    line = [p for d in days for p in d.geometry]
    if sources.google_places_key:
        try:
            stations = google_places.stations_along(
                line, sources.http, sources.google_places_key, fuel_type, today=today
            )
        except (SourceError, httpx.TransportError) as e:
            notes.append(f"No station prices ({e}); fuel uses EIA averages.")
        else:
            found = google_places.area_prices(stations, today=today)
            if not found:
                notes.append("Google Places had no recent prices on this route.")
            return stations, google_places.with_station_prices(sources.gas_prices, found)
    if sources.foursquare_key:
        return stations_along(line, sources.http, sources.foursquare_key, fuel_type), (
            sources.gas_prices
        )
    return [], sources.gas_prices


def _with_clearances(days: list[DayLeg], checked: ClearanceCheck) -> list[DayLeg]:
    """Each low clearance the route couldn't avoid goes on the day that passes it."""
    out = [d.model_copy() for d in days]
    for r, warning in zip(checked.too_low, checked.warnings(), strict=True):
        i = min(range(len(out)), key=lambda i: locate(r.at, out[i].geometry or [r.at])[1])
        out[i] = out[i].model_copy(
            update={"clearance_warnings": [*out[i].clearance_warnings, warning]}
        )
    return out


def _dated(legs: list[list[DayLeg]], start: date, extra_nights: int) -> list[DayLeg]:
    """One numbered list of days. A return leg sets off after the extra nights at the
    destination."""
    out: list[DayLeg] = []
    when = start
    for k, leg in enumerate(legs):
        if k:
            when += timedelta(days=extra_nights)
        for day in leg:
            out.append(day.model_copy(update={"day": len(out) + 1, "travel_date": when}))
            when += timedelta(days=1)
    return out
