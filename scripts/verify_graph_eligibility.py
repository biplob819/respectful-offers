#!/usr/bin/env python3
"""Check the build graph.

No cycles, no unknown nodes, and no node building ahead of its dependencies.

Usage:
    python scripts/verify_graph_eligibility.py                 # check the live graph
    python scripts/verify_graph_eligibility.py --start N1.1    # would starting N1.1 be allowed?
    python scripts/verify_graph_eligibility.py --self-test     # prove the check can fail

Exit 0 when eligible, 1 when not.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness_lib import (
    CATALOG_TSV,
    GRAPH_MD,
    HarnessError,
    eligibility_problems,
    load_catalog,
    load_graph,
    parse_catalog,
    parse_graph,
)

_GRAPH_OK = """
| Node | Title | Depends on |
| --- | --- | --- |
| **W0.1** | Harness | — |
| **N1.1** | Schemas | W0.1 |
| **N1.2** | Adapters | N1.1 |
"""
_GRAPH_CYCLE = """
| **W0.1** | Harness | N1.2 |
| **N1.1** | Schemas | W0.1 |
| **N1.2** | Adapters | N1.1 |
"""
_GRAPH_UNKNOWN = """
| **W0.1** | Harness | — |
| **N1.1** | Schemas | W9.9 |
"""
_HEADER = "cap_id\tnode\tstatus\tproof\tnote\n"


def _cat(*rows: str) -> str:
    return _HEADER + "".join(r + "\n" for r in rows)


def self_test() -> int:
    cases: list[tuple[str, str, str, str | None, bool]] = [
        ("valid graph, nothing started", _GRAPH_OK, _cat("H-1\tW0.1\tnot-started\t\t"), None, True),
        (
            "valid order",
            _GRAPH_OK,
            _cat("H-1\tW0.1\tgreen\t\t", "S-1\tN1.1\tbuilding\t\t"),
            None,
            True,
        ),
        ("cycle", _GRAPH_CYCLE, _cat("H-1\tW0.1\tnot-started\t\t"), None, False),
        ("unknown dependency", _GRAPH_UNKNOWN, _cat("H-1\tW0.1\tnot-started\t\t"), None, False),
        (
            "building ahead of dependency",
            _GRAPH_OK,
            _cat("H-1\tW0.1\tbuilding\t\t", "S-1\tN1.1\tbuilding\t\t"),
            None,
            False,
        ),
        (
            "starting ahead of dependency",
            _GRAPH_OK,
            _cat("H-1\tW0.1\tgreen\t\t", "S-1\tN1.1\tnot-started\t\t"),
            "N1.2",
            False,
        ),
        ("catalog names unknown node", _GRAPH_OK, _cat("X-1\tZ9.9\tspec\t\t"), None, False),
    ]
    failures = 0
    for name, graph, catalog, start, expect_ok in cases:
        problems = eligibility_problems(parse_graph(graph), parse_catalog(catalog), start)
        ok = not problems
        verdict = "ok" if ok == expect_ok else "WRONG"
        if ok != expect_ok:
            failures += 1
        print(f"  [{verdict}] {name}: {'eligible' if ok else problems[0]}")
    try:
        parse_graph("| **W0.1** | Harness | not a node |")
        print("  [WRONG] unparseable depends_on was accepted")
        failures += 1
    except HarnessError:
        print("  [ok] unparseable depends_on rejected")
    print("self-test", "PASSED" if failures == 0 else f"FAILED ({failures})")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--start", metavar="NODE", help="check eligibility as if NODE were starting")
    ap.add_argument("--graph", type=Path, default=GRAPH_MD, help=argparse.SUPPRESS)
    ap.add_argument("--catalog", type=Path, default=CATALOG_TSV, help=argparse.SUPPRESS)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    try:
        nodes = load_graph(args.graph)
        caps = load_catalog(args.catalog)
    except (HarnessError, OSError) as exc:
        print(f"graph eligibility: cannot read inputs: {exc}")
        return 1
    if args.start and args.start not in nodes:
        print(f"graph eligibility: unknown node {args.start}")
        return 1
    problems = eligibility_problems(nodes, caps, args.start)
    if problems:
        print("graph eligibility: FAIL")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"graph eligibility: OK ({len(nodes)} nodes, {len(caps)} capabilities)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
