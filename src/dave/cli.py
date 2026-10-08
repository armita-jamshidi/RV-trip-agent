"""Command-line entry point."""

import argparse
import asyncio
import json

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
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
