#!/usr/bin/env python3
"""One-table build status, read live from graph.md and catalog.tsv.

Usage:
    python scripts/status.py          # every node: status, rows green, dependencies
    python scripts/status.py A2.4     # one node: each capability and its status
"""

from __future__ import annotations

import argparse
import sys

from harness_lib import HarnessError, load_catalog, load_graph, node_status


def render_graph(nodes, caps) -> str:
    lines = [f"{'Node':<6} {'Status':<12} {'Green':>7}  {'Title':<36} Depends on"]
    for n in nodes.values():
        rows = [c for c in caps if c.node == n.id]
        green = sum(c.status == "green" for c in rows)
        st = node_status(n.id, caps)
        ready = st in ("not-started", "spec") and all(
            node_status(d, caps) == "green" for d in n.depends_on
        )
        label = "ready" if ready else st
        lines.append(
            f"{n.id:<6} {label:<12} {green:>3}/{len(rows):<3}  "
            f"{n.title[:36]:<36} {', '.join(n.depends_on) or '—'}"
        )
    total = sum(c.status == "green" for c in caps)
    done = sum(node_status(n, caps) == "green" for n in nodes)
    lines.append(f"\n{done}/{len(nodes)} nodes green, {total}/{len(caps)} capabilities green")
    return "\n".join(lines)


def render_node(node_id, nodes, caps) -> str:
    n = nodes[node_id]
    lines = [f"{n.id} — {n.title}  [{node_status(n.id, caps)}]", ""]
    for c in (c for c in caps if c.node == node_id):
        lines.append(f"  {c.cap_id:<7} {c.status:<12} {c.note[:90]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("node", nargs="?")
    args = ap.parse_args(argv)
    try:
        nodes, caps = load_graph(), load_catalog()
    except (HarnessError, OSError) as exc:
        print(f"status: cannot read inputs: {exc}")
        return 1
    if args.node:
        if args.node not in nodes:
            print(f"status: unknown node {args.node}")
            return 1
        print(render_node(args.node, nodes, caps))
    else:
        print(render_graph(nodes, caps))
    return 0


if __name__ == "__main__":
    sys.exit(main())
