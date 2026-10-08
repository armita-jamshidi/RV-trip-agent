"""Shared data models. Units are explicit in field names: feet, miles, hours, USD."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Hookup(StrEnum):
    ELECTRIC = "electric"
    WATER = "water"
    SEWER = "sewer"


class FuelType(StrEnum):
    GAS = "gas"
    DIESEL = "diesel"


class RVClass(StrEnum):
    A = "class_a"
    B = "class_b"
    C = "class_c"
    TRAVEL_TRAILER = "travel_trailer"
    FIFTH_WHEEL = "fifth_wheel"


class Place(Model):
    name: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    address: str | None = None


# --- What the traveler asked for -------------------------------------------------


class TripRequest(Model):
    """The traveler's request in their own words."""

    text: str = Field(min_length=1)


class RVRequest(Model):
    """The RV as the traveler described it, before lookup."""

    make: str | None = None
    model: str | None = None
    year: int | None = Field(default=None, ge=1950, le=2100)


class Interests(Model):
    nature: float = Field(default=0.5, ge=0, le=1)
    museums: float = Field(default=0.5, ge=0, le=1)
    largest_x: float = Field(default=0.0, ge=0, le=1)
    food: float = Field(default=0.5, ge=0, le=1)


class ConstraintSpec(Model):
    """Structured trip constraints. See specs/constraint-spec.md."""

    origin: str
    destination: str
    round_trip: bool = False
    start_date: date | None = None
    nights: int = Field(ge=1)
    travelers: int = Field(default=2, ge=1)
    rv: RVRequest = Field(default_factory=RVRequest)
    budget_usd: float | None = Field(default=None, gt=0)
    max_drive_hours_per_day: float = Field(default=5, gt=0, le=12)
    hookups_required: set[Hookup] = Field(default_factory=lambda: {Hookup.ELECTRIC, Hookup.WATER})
    interests: Interests = Field(default_factory=Interests)
    must_visit: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)


# --- What Dave found ---------------------------------------------------------------


class RVIdentity(Model):
    """A specific RV line from the catalog, before its dimensions are looked up."""

    make: str
    model: str
    floorplan: str | None = None
    year: int | None = Field(default=None, ge=1950, le=2100)
    rv_class: RVClass | None = None
    site: str


class RVIdentification(Model):
    """One confident match, or a short list for the agent to ask the traveler about."""

    match: RVIdentity | None = None
    candidates: list[RVIdentity] = []


class RVProfile(Model):
    make: str
    model: str
    year: int | None = None
    rv_class: RVClass
    length_ft: float = Field(gt=0)
    height_ft: float = Field(gt=0)
    width_ft: float | None = Field(default=None, gt=0)
    gvwr_lbs: float | None = Field(default=None, gt=0)
    fuel_type: FuelType
    fuel_tank_gal: float | None = Field(default=None, gt=0)
    mpg: float | None = Field(default=None, gt=0)
    electrical_amps: int | None = Field(default=None, description="30 or 50")
    tow_length_ft: float = Field(default=0, ge=0, description="Towed car, if any")
    source_url: str | None = None
    estimated: bool = Field(default=False, description="True when values are class averages")

    @property
    def total_length_ft(self) -> float:
        return self.length_ft + self.tow_length_ft


class RouteLeg(Model):
    """Driving between two consecutive points of a route."""

    miles: float = Field(ge=0)
    drive_hours: float = Field(ge=0)


class Route(Model):
    """A drivable route. `drive_hours` already includes the RV speed penalty."""

    miles: float = Field(ge=0)
    car_hours: float = Field(ge=0)
    drive_hours: float = Field(ge=0)
    legs: list[RouteLeg]
    geometry: list[tuple[float, float]]  # (lat, lon) along the road


class Stop(Model):
    name: str
    location: Place
    category: str  # Foursquare label path, e.g. "Landmarks and Outdoors > Park > National Park"
    rating: float | None = Field(default=None, ge=0, le=10)
    popularity: float | None = Field(default=None, ge=0, le=1)
    detour_minutes: float = Field(default=0, ge=0)
    ticket_price_usd: float | None = Field(default=None, ge=0)


class Restaurant(Model):
    name: str
    location: Place
    rating: float | None = Field(default=None, ge=0, le=10)
    cuisine: str | None = None
    price_level: int | None = Field(default=None, ge=1, le=4)


class GasStation(Model):
    name: str
    location: Place
    fuel_type: FuelType
    price_per_gal: float | None = Field(default=None, gt=0)
    avg_price_60d: float | None = Field(default=None, gt=0)
    rv_accessible: bool | None = None


class Campground(Model):
    name: str
    location: Place
    hookups: set[Hookup] = Field(default_factory=set)
    max_rv_length_ft: float | None = Field(default=None, gt=0)
    electrical_amps: set[int] = Field(default_factory=set)
    nightly_price_usd: float | None = Field(default=None, ge=0)
    rating: float | None = Field(default=None, ge=0, le=10)
    booking_url: str | None = None
    source: str


class DayLeg(Model):
    day: int = Field(ge=1)
    travel_date: date | None = None
    start: Place
    end: Place
    drive_hours: float = Field(ge=0)
    miles: float = Field(ge=0)
    geometry: list[tuple[float, float]] = Field(default_factory=list, description="(lat, lon)")
    clearance_warnings: list[str] = Field(default_factory=list)
    stops: list[Stop] = Field(default_factory=list)
    restaurants: list[Restaurant] = Field(default_factory=list)
    gas_stations: list[GasStation] = Field(default_factory=list)
    campground: Campground | None = None


class CostBreakdown(Model):
    fuel_usd: float = Field(default=0, ge=0)
    campgrounds_usd: float = Field(default=0, ge=0)
    tickets_usd: float = Field(default=0, ge=0)
    budget_usd: float | None = Field(default=None, gt=0)

    @property
    def total_usd(self) -> float:
        return round(self.fuel_usd + self.campgrounds_usd + self.tickets_usd, 2)

    @property
    def remaining_usd(self) -> float | None:
        return None if self.budget_usd is None else round(self.budget_usd - self.total_usd, 2)


class BookingStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    BOOKED = "booked"


class BookingProposal(Model):
    kind: str = Field(description="campground or ticket")
    name: str
    start_date: date
    end_date: date | None = None
    price_usd: float = Field(ge=0)
    cancellation_policy: str | None = None
    url: str | None = None
    status: BookingStatus = BookingStatus.PROPOSED
    approved_by: str | None = None
    approved_at: datetime | None = None


class Itinerary(Model):
    spec: ConstraintSpec
    rv: RVProfile
    days: list[DayLeg] = Field(default_factory=list)
    costs: CostBreakdown = Field(default_factory=CostBreakdown)
    bookings: list[BookingProposal] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
