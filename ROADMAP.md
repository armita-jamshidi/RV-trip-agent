# Roadmap

Each line is one Notion task (board "RV Travel Agent"). Work top to bottom; a task may start only when the tasks it builds on are merged.

## M0 Foundation
- T01 Project skeleton: uv, `src/dave`, ruff, pytest, GitHub Actions CI
- T02 Core data models: TripRequest, RVProfile, ConstraintSpec, DayLeg, Stop, Campground, Itinerary, CostBreakdown
- T03 Config, secrets and cached HTTP client
- T04 Agent shell on the Claude Agent SDK with a `dave plan "<request>"` CLI

## M1 Understanding the traveler
- T05 Trip request to constraint spec (Claude baseline)
- T06 RV model identification
- T07 RV dimensions lookup from manufacturer site
- T08 Interest profile scoring

## M2 Route that fits the RV
- T09 Base routing with drive times
- T10 Bridge and tunnel clearance check with rerouting
- T11 Split route into days of 5 hours or less
- T12 Route corridor search helper

## M3 Campgrounds
- T13 Campground data ingest (RIDB + Foursquare)
- T14 Hookup and RV length filter
- T15 Campground embeddings in LanceDB
- T16 Scenic appeal ranking
- T17 Pick a campground for each night

## M4 Stops and food
- T18 Pitstop finder by interest
- T19 "Largest X" landmark finder
- T20 Highly rated restaurants along the way

## M5 Costs
- T21 Fuel cost estimate from EIA prices
- T22 Daily gas station price snapshots
- T23 Cheapest gas stations along the route
- T24 Trip cost rollup and budget enforcement

## M6 Booking with approval
- T25 Booking proposals and approval gate
- T26 Campground booking handoff
- T27 Attraction ticket proposals

## M7 Fine-tuning and retrieval models
- T28 Build trip request to constraint spec dataset
- T29 QLoRA fine-tune of constraint spec model on Colab
- T30 Fine-tune campground embedding model
- T31 Use fine-tuned models in the agent behind a flag

## M8 Quality and demo
- T32 Itinerary validator
- T33 Itinerary output renderer
- T34 Real-world evaluation harness
- T35 Demo trips
