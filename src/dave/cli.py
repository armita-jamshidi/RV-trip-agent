"""Command-line entry point."""

import argparse
import asyncio
import json
from datetime import date

from dave import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dave", description="Plan an RV road trip.")
    parser.add_argument("--version", action="version", version=f"dave {__version__}")
    sub = parser.add_subparsers(dest="command")
    plan_cmd = sub.add_parser("plan", help="Plan a trip from a plain-language request.")
    plan_cmd.add_argument("request", help='e.g. "5 nights from Denver, 32 ft Class A, $1500"')
    parse_cmd = sub.add_parser("parse", help="Turn a trip request into a constraint spec.")
    parse_cmd.add_argument("request")
    sub.add_parser("eval-parser", help="Score the request parser on evals/parser/cases.jsonl.")
    sub.add_parser("compare-parsers", help="Demo trips parsed by Claude and the fine-tuned model.")
    route_cmd = sub.add_parser("route", help="RV route through points given as lat,lon.")
    route_cmd.add_argument("points", nargs="+", metavar="LAT,LON")
    route_cmd.add_argument(
        "--rv-height", type=float, help="Feet; checks bridges and reroutes (start and end only)"
    )
    camp_cmd = sub.add_parser("campgrounds", help="Ingest campgrounds around points.")
    camp_cmd.add_argument("points", nargs="*", metavar="LAT,LON")
    camp_cmd.add_argument("--demo", action="store_true", help="Use the demo/regions.json areas.")
    camp_cmd.add_argument("--radius", type=float, default=50, help="Miles around each point.")
    camp_cmd.add_argument("--out", default="data/campgrounds.jsonl")
    index_cmd = sub.add_parser("index-campgrounds", help="Embed ingested campgrounds for search.")
    index_cmd.add_argument("--from", dest="source", default="data/campgrounds.jsonl")
    find_cmd = sub.add_parser("find-campgrounds", help="Search campgrounds by meaning.")
    find_cmd.add_argument("query", help='e.g. "quiet lakeside with mountain views"')
    find_cmd.add_argument("--hookups", default="", help="e.g. electric,water")
    find_cmd.add_argument("--length", type=float, help="RV length in feet, tow vehicle included")
    find_cmd.add_argument("--near", metavar="LAT,LON")
    find_cmd.add_argument("--radius", type=float, default=50, help="Miles around --near.")
    tune_cmd = sub.add_parser(
        "eval-embeddings", help="recall@5 and MRR of campground search on held-out queries."
    )
    tune_cmd.add_argument("--campgrounds", default="data/campgrounds.jsonl")
    stops_cmd = sub.add_parser("pitstops", help="Stops worth making along a route, per day.")
    stops_cmd.add_argument("points", nargs="+", metavar="LAT,LON")
    stops_cmd.add_argument("--interests", default="", help="e.g. nature=0.9,museums=0.2")
    stops_cmd.add_argument("--rv-length", type=float, help="RV length in feet, tow included")
    rv_cmd = sub.add_parser("rv", help="Look up an RV's size from the manufacturer's spec page.")
    rv_cmd.add_argument("description", help='e.g. "2023 Winnebago Minnie Winnie 31K"')
    scenic_cmd = sub.add_parser("eval-scenic", help="Score scenic ranking on labeled campgrounds.")
    scenic_cmd.add_argument("--campgrounds", default="data/campgrounds.jsonl")
    fuel_cmd = sub.add_parser("fuel", help="Fuel cost per day for an RV on a route.")
    fuel_cmd.add_argument("rv", help='e.g. "2023 Winnebago Minnie Winnie 31K"')
    fuel_cmd.add_argument("points", nargs="+", metavar="LAT,LON")
    fuel_cmd.add_argument("--on", type=date.fromisoformat, help="First travel day, YYYY-MM-DD")
    sub.add_parser("gas-snapshot", help="Save this week's EIA gas and diesel averages.")
    gas_cmd = sub.add_parser("gas-price", help="Average gas price for a state, from snapshots.")
    gas_cmd.add_argument("state", help="Two-letter state code, e.g. UT")
    gas_cmd.add_argument("--diesel", action="store_true")
    gas_cmd.add_argument("--on", type=date.fromisoformat, help="Trip date, YYYY-MM-DD")
    args = parser.parse_args(argv)

    # Imports are deferred so --help stays fast.
    if args.command == "plan":
        from dave.agent import plan

        print(asyncio.run(plan(args.request)))
        return 0
    if args.command in {"parse", "eval-parser", "compare-parsers"}:
        from dave import parser_eval
        from dave.config import load_settings
        from dave.http import CachedClient
        from dave.parser import parse_request
        from dave.small_parser import compare, demo_requests, small_parser

        settings = load_settings()
        cache_dir = settings.cache_dir
        with CachedClient(cache_dir / "http", offline=settings.offline) as http:
            small = small_parser(settings, http)
            if args.command == "parse":
                result = parse_request(args.request, small=small, cache_dir=cache_dir)
                print(result.question or result.spec.model_dump_json(indent=2))
                return 0
            if args.command == "compare-parsers":
                if small is None:
                    print("Set DAVE_PARSER_URL to the fine-tuned parser's server first.")
                    return 2
                rows = compare(demo_requests(), small, today=parser_eval.TODAY, cache_dir=cache_dir)
                print(json.dumps(rows, indent=2))
                return 0
            report = parser_eval.evaluate(
                lambda text: parse_request(
                    text, today=parser_eval.TODAY, small=small, cache_dir=cache_dir
                ),
                parser_eval.load_cases(),
            )
        print(json.dumps(report, indent=2))
        return 0 if report["accuracy"] >= parser_eval.TARGET else 1
    if args.command == "route":
        from dave.config import load_settings
        from dave.http import CachedClient
        from dave.models import Place
        from dave.routing import route

        settings = load_settings()
        places = [Place(name=p, lat=p.split(",")[0], lon=p.split(",")[1]) for p in args.points]
        with CachedClient(settings.cache_dir / "http", offline=settings.offline) as http:
            if args.rv_height is None:
                r = route(places, http)
            else:
                from dave.clearance import clear_route

                if len(places) != 2:
                    parser.error("--rv-height takes a start and an end point only")
                checked = clear_route(places[0], places[1], args.rv_height, http)
                r = checked.route
                if checked.rerouted:
                    print("Rerouted around a low bridge.")
                for line in checked.warnings() + checked.notes():
                    print(line)
        print(f"{r.miles:.0f} miles, {r.car_hours:.1f} h by car, {r.drive_hours:.1f} h by RV")
        return 0
    if args.command == "campgrounds":
        from pathlib import Path

        from dave.campgrounds import DEMO_REGIONS, ingest
        from dave.config import load_settings
        from dave.http import CachedClient

        settings = load_settings()
        centers = [tuple(map(float, p.split(","))) for p in args.points]
        if args.demo:
            centers += [(r["lat"], r["lon"]) for r in json.loads(DEMO_REGIONS.read_text())]
        if not centers:
            parser.error("give LAT,LON points or --demo")
        with CachedClient(settings.cache_dir / "http", offline=settings.offline) as http:
            found = ingest(
                centers,
                args.radius,
                http,
                ridb_key=settings.require("RIDB_API_KEY"),
                foursquare_key=settings.require("FOURSQUARE_API_KEY"),
            )
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(c.model_dump_json() + "\n" for c in found))
        hookups = sum(1 for c in found if c.hookups)
        lengths = sum(1 for c in found if c.max_rv_length_ft)
        print(
            f"{len(found)} campgrounds ({hookups} with hookups, {lengths} with RV length) -> {out}"
        )
        return 0
    if args.command == "eval-embeddings":
        from pathlib import Path

        from dave.config import load_settings
        from dave.embed_tune import evaluate
        from dave.models import Campground
        from dave.store.vectors import FastEmbedder

        settings = load_settings()
        lines = Path(args.campgrounds).read_text().splitlines()
        camps = [Campground.model_validate_json(line) for line in lines]
        embedder = FastEmbedder(settings.cache_dir / "models", settings.embed_model)
        print(json.dumps(evaluate(embedder, camps), indent=2))
        return 0
    if args.command in {"index-campgrounds", "find-campgrounds"}:
        from pathlib import Path

        from dave.config import load_settings
        from dave.models import Campground, Hookup
        from dave.store.vectors import INDEX_PATH, CampgroundIndex, FastEmbedder

        settings = load_settings()
        embedder = FastEmbedder(settings.cache_dir / "models", settings.embed_model)
        index = CampgroundIndex(INDEX_PATH, embedder)
        if args.command == "index-campgrounds":
            lines = Path(args.source).read_text().splitlines()
            count = index.build(Campground.model_validate_json(line) for line in lines)
            print(f"Indexed {count} campgrounds")
            return 0
        near = tuple(map(float, args.near.split(","))) if args.near else None
        for camp, score in index.search(
            args.query,
            hookups=[Hookup(h.strip()) for h in args.hookups.split(",") if h.strip()],
            min_length_ft=args.length,
            near=near,
            radius_miles=args.radius if near else None,
        ):
            print(f"{score:.2f}  {camp.name}  ({camp.location.lat:.3f}, {camp.location.lon:.3f})")
        return 0
    if args.command == "pitstops":
        from dave.config import load_settings
        from dave.days import split_days
        from dave.http import CachedClient
        from dave.models import Interests, Place
        from dave.pitstops import find_pitstops
        from dave.routing import route

        settings = load_settings()
        places = [Place(name=p, lat=p.split(",")[0], lon=p.split(",")[1]) for p in args.points]
        interests = Interests(
            **{k: float(v) for k, v in (kv.split("=") for kv in args.interests.split(",") if kv)}
        )
        with CachedClient(settings.cache_dir / "http", offline=settings.offline) as http:
            days = split_days(route(places, http), places[0], places[-1])
            days = find_pitstops(
                days,
                interests,
                http,
                settings.require("FOURSQUARE_API_KEY"),
                rv_length_ft=args.rv_length,
            )
        for day in days:
            print(f"Day {day.day}: {day.drive_hours:.1f} h driving")
            for s in day.stops:
                print(f"  {s.name} ({s.category}), +{s.detour_minutes:.0f} min detour")
                if s.rv_parking_note:
                    print(f"    {s.rv_parking_note}")
        return 0
    if args.command == "rv":
        from dave.tools.rv import rv_dimensions_tool

        out = asyncio.run(rv_dimensions_tool.handler({"text": args.description}))
        print(out["content"][0]["text"])
        return 0
    if args.command == "eval-scenic":
        from pathlib import Path

        from dave import scenic
        from dave.config import load_settings
        from dave.models import Campground
        from dave.store.vectors import FastEmbedder

        if not scenic.LABELS.exists():
            parser.error(f"label ingested campgrounds in {scenic.LABELS} first")
        rows = [json.loads(line) for line in scenic.LABELS.read_text().splitlines()]
        lines = Path(args.campgrounds).read_text().splitlines()
        report = scenic.evaluate(
            [Campground.model_validate_json(line) for line in lines],
            {r["name"]: r["scenic"] for r in rows},
            FastEmbedder(load_settings().cache_dir / "models"),
        )
        print(json.dumps(report, indent=2))
        return 0 if report["precision"] >= scenic.TARGET and not report["missing"] else 1
    if args.command == "fuel":
        from dave import gas_prices
        from dave.config import load_settings
        from dave.days import split_days
        from dave.fuel_cost import estimate_fuel
        from dave.http import CachedClient
        from dave.models import Place
        from dave.routing import route
        from dave.rv_catalog import identify_rv
        from dave.rv_specs import lookup_rv

        settings = load_settings()
        found = identify_rv(args.rv)
        if found.match is None or found.match.rv_class is None:
            parser.error(f"name one RV, with its class if unusual: {args.rv!r} is ambiguous")
        places = [Place(name=p, lat=p.split(",")[0], lon=p.split(",")[1]) for p in args.points]
        with CachedClient(settings.cache_dir / "http", offline=settings.offline) as http:
            rv = lookup_rv(found.match, http)
            days = split_days(route(places, http), places[0], places[-1], start_date=args.on)
        try:
            estimate = estimate_fuel(
                days, rv, gas_prices.load(gas_prices.STORE), today=date.today()
            )
        except ValueError as e:
            print(e)
            return 1
        print("\n".join(estimate.summary()))
        return 0
    if args.command == "gas-snapshot":
        from dave import gas_prices
        from dave.config import load_settings
        from dave.http import CachedClient

        settings = load_settings()
        with CachedClient(settings.cache_dir / "http", offline=settings.offline) as http:
            saved = gas_prices.collect(http, settings.require("EIA_API_KEY"), today=date.today())
        print(f"Saved {len(saved)} new or revised weeks to {gas_prices.STORE}")
        print(json.dumps(gas_prices.coverage(gas_prices.load(gas_prices.STORE)), indent=2))
        return 0
    if args.command == "gas-price":
        from dave import gas_prices
        from dave.models import FuelType

        fuel = FuelType.DIESEL if args.diesel else FuelType.GAS
        found = gas_prices.price_for(
            gas_prices.load(gas_prices.STORE), args.state, fuel, args.on or date.today()
        )
        if not found:
            print("No snapshots yet; run `dave gas-snapshot` first.")
            return 1
        print(
            f"${found.usd_per_gal:.3f}/gal {fuel} in {args.state.upper()}, estimated from the "
            f"EIA {found.area_name} average (weeks through {found.period})"
        )
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
