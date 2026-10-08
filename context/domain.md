# RV domain rules

Defaults Dave applies unless the user says otherwise.

| Rule | Default | Notes |
|---|---|---|
| Max driving per day | 5 h | Includes estimated RV speed penalty (about 10% slower than car times). |
| Bridge clearance margin | RV height + 6 in | Low-clearance data comes from OSM `maxheight`; missing data is flagged, not assumed safe. |
| Hookups | Electric and water both required | Electric amperage (30A/50A) must match the RV when known. |
| Site length | Site max length >= RV length (+ tow vehicle if towing) | |
| Propane | Some tunnels ban propane | Flag tunnels with hazmat restrictions. |
| Fuel | Use RV MPG from specs; fall back to class averages | Class A ~8 mpg, Class C ~12 mpg, Class B ~18 mpg, towing trailer ~10 mpg. |

## RV classes
- **Class A:** bus-style, 29 to 45 ft, 12 to 13.5 ft tall.
- **Class B:** camper van, 17 to 24 ft, 9 to 10 ft tall.
- **Class C:** cab-over, 21 to 35 ft, 10 to 12 ft tall.
- **Travel trailer / fifth wheel:** towed; combined length matters for sites, trailer height for bridges.
