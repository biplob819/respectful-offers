"""Shared helpers for the Respectful Offers build harness (graph, catalog, specs).

The build graph lives in docs/graph/graph.md as a markdown table. The capability
ledger lives in docs/graph/catalog.tsv. These helpers parse both and derive node status.
Nothing here touches the network.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAPH_MD = ROOT / "docs" / "graph" / "graph.md"
CATALOG_TSV = ROOT / "docs" / "graph" / "catalog.tsv"
SPECS_DIR = ROOT / "specs"

STATUSES = ("not-started", "spec", "building", "green")
NODE_RE = re.compile(r"^[WNABPDE]\d+\.\d+$")
NODE_LIKE_RE = re.compile(r"^[A-Za-z]\d+\.\d+$")  # looks like a node id but may be malformed
CATALOG_FIELDS = ("cap_id", "node", "status", "proof", "note")
PROOF_DIMENSIONS = ("logical", "contract", "golden", "repro", "respect")


@dataclass
class Node:
    id: str
    title: str
    depends_on: list[str] = field(default_factory=list)
    verified_by: str = ""
    deliverable: str = ""


@dataclass
class Cap:
    cap_id: str
    node: str
    status: str
    proof: str
    note: str


class HarnessError(Exception):
    """Raised when a harness input file is malformed."""


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_graph(text: str) -> dict[str, Node]:
    """Parse every markdown table row whose first cell is a node id."""
    nodes: dict[str, Node] = {}
    in_fence = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if raw.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not raw.lstrip().startswith("|"):
            continue
        cells = _cells(raw)
        node_id = cells[0].strip("*` ")
        if not NODE_RE.match(node_id):
            if NODE_LIKE_RE.match(node_id):
                raise HarnessError(f"graph line {lineno}: malformed node id {node_id!r}")
            continue
        if len(cells) < 3:
            raise HarnessError(f"graph line {lineno}: node {node_id} row needs a depends_on cell")
        if node_id in nodes:
            raise HarnessError(f"duplicate node {node_id} in graph")
        deps_cell = cells[2]
        deps: list[str] = []
        if deps_cell not in ("", "—", "-"):
            for part in deps_cell.split(","):
                dep = part.strip().strip("*` ")
                if not NODE_RE.match(dep):
                    raise HarnessError(f"{node_id}: unparseable depends_on entry {part.strip()!r}")
                deps.append(dep)
        nodes[node_id] = Node(
            id=node_id,
            title=cells[1],
            depends_on=deps,
            verified_by=cells[3] if len(cells) > 3 else "",
            deliverable=cells[4] if len(cells) > 4 else "",
        )
    if not nodes:
        raise HarnessError("graph has no node rows")
    return nodes


def load_graph(path: Path = GRAPH_MD) -> dict[str, Node]:
    return parse_graph(path.read_text(encoding="utf-8"))


def parse_catalog(text: str) -> list[Cap]:
    rows = list(csv.reader(text.splitlines(), delimiter="\t"))
    if not rows or tuple(c.strip() for c in rows[0]) != CATALOG_FIELDS:
        raise HarnessError("catalog header must be exactly: " + " | ".join(CATALOG_FIELDS))
    caps: list[Cap] = []
    seen: set[str] = set()
    for i, row in enumerate(rows[1:], start=2):
        if not row or all(not c.strip() for c in row):
            continue
        if len(row) != len(CATALOG_FIELDS):
            raise HarnessError(f"catalog line {i}: expected 5 columns, got {len(row)}")
        cap_id, node, status, proof, note = (c.strip() for c in row)
        if not cap_id or not node:
            raise HarnessError(f"catalog line {i}: cap_id and node are required")
        if status not in STATUSES:
            raise HarnessError(f"catalog line {i}: unknown status {status!r}")
        if cap_id in seen:
            raise HarnessError(f"catalog line {i}: duplicate cap {cap_id}")
        seen.add(cap_id)
        caps.append(Cap(cap_id=cap_id, node=node, status=status, proof=proof, note=note))
    return caps


def load_catalog(path: Path = CATALOG_TSV) -> list[Cap]:
    return parse_catalog(path.read_text(encoding="utf-8"))


def write_catalog(caps: list[Cap], path: Path = CATALOG_TSV) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(CATALOG_FIELDS)
        for c in caps:
            writer.writerow([c.cap_id, c.node, c.status, c.proof, c.note])


def node_status(node_id: str, caps: list[Cap]) -> str:
    """green if every row is green; building if any row is building or green.

    Otherwise spec if any row is spec, else not-started.
    """
    rows = [c for c in caps if c.node == node_id]
    if not rows:
        return "not-started"
    statuses = {c.status for c in rows}
    if statuses == {"green"}:
        return "green"
    if statuses & {"building", "green"}:
        return "building"
    if "spec" in statuses:
        return "spec"
    return "not-started"


def find_cycle(nodes: dict[str, Node]) -> list[str] | None:
    """Return one dependency cycle as a list of node ids, or None."""
    white, grey, black = 0, 1, 2
    color = dict.fromkeys(nodes, white)
    stack: list[str] = []

    def visit(n: str) -> list[str] | None:
        color[n] = grey
        stack.append(n)
        for d in nodes[n].depends_on:
            if d not in nodes:
                continue
            if color[d] == grey:
                return [*stack[stack.index(d) :], d]
            if color[d] == white:
                found = visit(d)
                if found:
                    return found
        stack.pop()
        color[n] = black
        return None

    for n in nodes:
        if color[n] == white:
            found = visit(n)
            if found:
                return found
    return None


def eligibility_problems(
    nodes: dict[str, Node], caps: list[Cap], simulate_start: str | None = None
) -> list[str]:
    """All reasons the graph is not eligible. Empty list means eligible."""
    problems: list[str] = []
    for n in nodes.values():
        for d in n.depends_on:
            if d not in nodes:
                problems.append(f"{n.id} depends on unknown node {d}")
    cycle = find_cycle(nodes)
    if cycle:
        problems.append("dependency cycle: " + " -> ".join(cycle))
    for c in caps:
        if c.node not in nodes:
            problems.append(f"catalog row {c.cap_id} names unknown node {c.node}")
    for n in nodes.values():
        status = node_status(n.id, caps)
        active = status in ("building", "green") or n.id == simulate_start
        if not active:
            continue
        for d in n.depends_on:
            if d in nodes and node_status(d, caps) != "green":
                problems.append(
                    f"{n.id} is {'starting' if n.id == simulate_start else status} "
                    f"but dependency {d} is {node_status(d, caps)}"
                )
    return problems


def spec_dir(node_id: str, specs: Path = SPECS_DIR) -> Path | None:
    matches = sorted(specs.glob(f"{node_id}-*"))
    return matches[0] if matches else None
