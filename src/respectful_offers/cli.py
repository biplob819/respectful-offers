"""The `offers` command line. Stage commands arrive with their nodes; B2.2 owns the full CLI."""

from __future__ import annotations

import argparse
import sys

from respectful_offers import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="offers", description=__doc__)
    parser.add_argument("--version", action="version", version=f"offers {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
