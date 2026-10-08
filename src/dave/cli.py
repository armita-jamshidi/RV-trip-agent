"""Command-line entry point."""

import argparse

from dave import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dave", description="Plan an RV road trip.")
    parser.add_argument("--version", action="version", version=f"dave {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
