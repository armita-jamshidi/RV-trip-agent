# Itinerary

What Dave returns for a trip.

- `rv`: resolved RV profile (length, height, width, weight, fuel type, MPG, source URL).
- `days[]`: for each day: start, end, drive hours, miles, route geometry, clearance warnings, stops, restaurants, gas stations, campground.
- `costs`: fuel, campgrounds, tickets, total, budget, remaining.
- `bookings[]`: proposals with status `proposed`, `approved` or `booked`.
- `validation`: result of `validate_itinerary()`; a plan with failures is never presented as final.
