"""Add up fuel, campgrounds and tickets per day, and bring an over-budget plan under budget.

When the plan costs more than the budget, Dave makes the cheapest-to-the-traveler changes
first, each with what it saves and what it gives up:

1. Swap a night's campground for a cheaper alternative from T17 that is known to fit.
2. Drop the paid stop whose tickets cost the most.

Fuel is fixed by the route. If both are used up and the plan is still over, the plan says by
how much and that the trip needs to be shorter (fewer nights or a closer destination); Dave
doesn't reroute on its own. Campgrounds without a listed price count as $0 and are named, so
the traveler knows the total may be low.
"""

from dataclasses import dataclass, field

from dave.fuel_cost import FuelEstimate
from dave.models import BookingProposal, CostBreakdown, DayLeg
from dave.overnight import NightPick, with_campgrounds
from dave.site_fit import Fit
from dave.tickets import ticket_proposals


@dataclass(frozen=True)
class DayCost:
    day: int
    fuel_usd: float
    campground_usd: float
    tickets_usd: float

    @property
    def total_usd(self) -> float:
        return round(self.fuel_usd + self.campground_usd + self.tickets_usd, 2)


@dataclass
class BudgetPlan:
    days: list[DayLeg]
    picks: list[NightPick]
    tickets: list[BookingProposal]
    per_day: list[DayCost]
    costs: CostBreakdown
    changes: list[str] = field(default_factory=list)
    unpriced: list[str] = field(default_factory=list)  # campgrounds with no listed price

    @property
    def over_by_usd(self) -> float:
        remaining = self.costs.remaining_usd
        return 0.0 if remaining is None or remaining >= 0 else round(-remaining, 2)

    def summary(self) -> list[str]:
        lines = [
            f"Day {d.day}: fuel ${d.fuel_usd:,.2f}, campground ${d.campground_usd:,.2f}, "
            f"tickets ${d.tickets_usd:,.2f}: ${d.total_usd:,.2f}"
            for d in self.per_day
        ]
        lines.append(f"Total: ${self.costs.total_usd:,.2f}" + _vs_budget(self.costs))
        lines += self.changes
        if self.unpriced:
            lines.append(f"No listed price for {', '.join(self.unpriced)}; the total may be low.")
        if self.over_by_usd:
            lines.append(
                f"Still ${self.over_by_usd:,.2f} over budget: shorten the trip by a night or "
                "pick a closer destination."
            )
        return lines


def day_costs(
    days: list[DayLeg],
    fuel: FuelEstimate,
    tickets: list[BookingProposal],
    *,
    extra_nights: int = 0,
) -> list[DayCost]:
    """Each day's spending. `extra_nights` are spent at the last campground (a longer stay)."""
    fuel_by_day = {d.day: d.usd for d in fuel.days}
    out = []
    for i, day in enumerate(days):
        nights = 1 + (extra_nights if i == len(days) - 1 else 0)
        price = day.campground.nightly_price_usd if day.campground else None
        on_day = [
            t.price_usd
            for t in tickets
            if t.start_date == day.travel_date or (day.travel_date is None and i == 0)
        ]
        out.append(
            DayCost(
                day=day.day,
                fuel_usd=fuel_by_day.get(day.day, 0.0),
                campground_usd=round((price or 0) * nights, 2),
                tickets_usd=round(sum(on_day), 2),
            )
        )
    return out


def fit_budget(
    days: list[DayLeg],
    picks: list[NightPick],
    fuel: FuelEstimate,
    budget_usd: float | None,
    *,
    extra_nights: int = 0,
    ticket_rules: dict | None = None,
) -> BudgetPlan:
    """The plan's costs, after any campground swaps and dropped stops the budget needs."""
    picks = list(picks)
    days = with_campgrounds(days, picks)
    changes: list[str] = []
    while True:
        plan = _plan(days, picks, fuel, budget_usd, extra_nights, ticket_rules, changes)
        if not plan.over_by_usd:
            return plan
        swap = _best_swap(days, picks, extra_nights)
        if swap:
            i, alt, saving, note = swap
            old = picks[i]
            picks[i] = NightPick(
                old.day, alt, [old.pick, *[a for a in old.alternatives if a is not alt]], old.note
            )
            days = with_campgrounds(days, picks)
            changes.append(note)
            continue
        drop = _best_drop(days, plan.tickets, ticket_rules)
        if drop:
            days, note = drop
            changes.append(note)
            continue
        return plan


def _plan(days, picks, fuel, budget_usd, extra_nights, ticket_rules, changes) -> BudgetPlan:
    tickets = _tickets(days, ticket_rules)
    per_day = day_costs(days, fuel, tickets, extra_nights=extra_nights)
    costs = CostBreakdown(
        fuel_usd=round(sum(d.fuel_usd for d in per_day), 2),
        campgrounds_usd=round(sum(d.campground_usd for d in per_day), 2),
        tickets_usd=round(sum(d.tickets_usd for d in per_day), 2),
        budget_usd=budget_usd,
    )
    unpriced = [
        d.campground.name for d in days if d.campground and d.campground.nightly_price_usd is None
    ]
    return BudgetPlan(days, picks, tickets, per_day, costs, list(changes), unpriced)


def _best_swap(days, picks, extra_nights):
    """The campground swap that saves the most: (pick index, alternative, saving, note)."""
    best = None
    last = days[-1].day if days else None
    for i, p in enumerate(picks):
        if p.pick is None or p.pick.campground.nightly_price_usd is None:
            continue
        now = p.pick.campground.nightly_price_usd
        nights = 1 + (extra_nights if p.day == last else 0)
        for alt in p.alternatives:
            price = alt.campground.nightly_price_usd
            if alt.fit.fit is not Fit.YES or price is None or price >= now:
                continue
            saving = round((now - price) * nights, 2)
            if best is None or saving > best[2]:
                lost = [
                    r for r in p.pick.reasons if r not in alt.reasons and r.startswith("mentions")
                ]
                trade = f"; gives up: {lost[0]}" if lost else ""
                note = (
                    f"Night {p.day}: {p.pick.campground.name} (${now:g}) swapped for "
                    f"{alt.campground.name} (${price:g}), saving ${saving:,.2f}{trade}."
                )
                best = (i, alt, saving, note)
    return best


def _best_drop(days, tickets, ticket_rules):
    """Drop the stop whose removal saves the most in tickets: (new days, note), or None."""
    now = sum(t.price_usd for t in tickets)
    best = None
    for di, day in enumerate(days):
        for si, stop in enumerate(day.stops):
            trial = [*days]
            trial[di] = day.model_copy(update={"stops": day.stops[:si] + day.stops[si + 1 :]})
            saving = round(now - sum(t.price_usd for t in _tickets(trial, ticket_rules)), 2)
            if saving > 0 and (best is None or saving > best[2]):
                note = f"Day {day.day}: dropped {stop.name}, saving ${saving:,.2f} in tickets."
                best = (trial, note, saving)
    return best[:2] if best else None


def _tickets(days, ticket_rules) -> list[BookingProposal]:
    if not any(d.stops for d in days):
        return []
    return ticket_proposals(days, ticket_rules)


def _vs_budget(costs: CostBreakdown) -> str:
    if costs.budget_usd is None:
        return ""
    if costs.remaining_usd >= 0:
        return f", ${costs.remaining_usd:,.2f} under the ${costs.budget_usd:,.2f} budget"
    return f", ${-costs.remaining_usd:,.2f} over the ${costs.budget_usd:,.2f} budget"
