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
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
