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
    route_cmd = sub.add_parser("route", help="RV route through points given as lat,lon.")
    route_cmd.add_argument("points", nargs="+", metavar="LAT,LON")
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
    stops_cmd = sub.add_parser("pitstops", help="Stops worth making along a route, per day.")
    stops_cmd.add_argument("points", nargs="+", metavar="LAT,LON")
    stops_cmd.add_argument("--interests", default="", help="e.g. nature=0.9,museums=0.2")
    stops_cmd.add_argument("--rv-length", type=float, help="RV length in feet, tow included")
    scenic_cmd = sub.add_parser("eval-scenic", help="Score scenic ranking on labeled campgrounds.")
    scenic_cmd.add_argument("--campgrounds", default="data/campgrounds.jsonl")
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
    if args.command == "parse":
        from dave.config import load_settings
        from dave.parser import parse_request

        result = parse_request(args.request, cache_dir=load_settings().cache_dir)
        print(result.question or result.spec.model_dump_json(indent=2))
        return 0
    if args.command == "eval-parser":
        from dave import parser_eval
        from dave.config import load_settings
        from dave.parser import parse_request

        cache_dir = load_settings().cache_dir
        report = parser_eval.evaluate(
            lambda text: parse_request(text, today=parser_eval.TODAY, cache_dir=cache_dir),
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
            r = route(places, http)
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
    if args.command in {"index-campgrounds", "find-campgrounds"}:
        from pathlib import Path

        from dave.config import load_settings
        from dave.models import Campground, Hookup
        from dave.store.vectors import INDEX_PATH, CampgroundIndex, FastEmbedder

        settings = load_settings()
        index = CampgroundIndex(INDEX_PATH, FastEmbedder(settings.cache_dir / "models"))
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
