import pytest

import verify_graph_eligibility as vge
from harness_lib import (
    HarnessError,
    eligibility_problems,
    find_cycle,
    load_catalog,
    load_graph,
    node_status,
    parse_catalog,
    parse_graph,
)

HDR = "cap_id\tnode\tstatus\tproof\tnote\n"
GRAPH = parse_graph(
    "| **W0.1** | Harness | — |\n"
    "| **N1.1** | Schemas | W0.1 |\n"
    "| **N1.2** | Adapters | N1.1, W0.1 |\n"
)


def cat(*rows):
    return parse_catalog(HDR + "".join(r + "\n" for r in rows))


def test_self_test_passes():
    assert vge.self_test() == 0


def test_detects_cycle():
    g = parse_graph("| **W0.1** | A | N1.1 |\n| **N1.1** | B | W0.1 |\n")
    assert find_cycle(g) is not None
    assert any("cycle" in p for p in eligibility_problems(g, cat()))


def test_detects_unknown_dependency():
    g = parse_graph("| **W0.1** | A | — |\n| **N1.1** | B | N9.9 |\n")
    assert any("unknown node N9.9" in p for p in eligibility_problems(g, cat()))


def test_rejects_unparseable_depends_on():
    with pytest.raises(HarnessError):
        parse_graph("| **W0.1** | A | the harness |\n")


def test_building_ahead_of_dependency_fails():
    problems = eligibility_problems(GRAPH, cat("H\tW0.1\tbuilding\t\t", "S\tN1.1\tbuilding\t\t"))
    assert problems == ["N1.1 is building but dependency W0.1 is building"]


def test_starting_ahead_of_dependency_fails():
    problems = eligibility_problems(GRAPH, cat("H\tW0.1\tgreen\t\t", "S\tN1.1\tspec\t\t"), "N1.2")
    assert "N1.2 is starting but dependency N1.1 is spec" in problems


def test_catalog_row_with_unknown_node_fails():
    assert eligibility_problems(GRAPH, cat("X\tQ1.1\tspec\t\t")) == [
        "catalog row X names unknown node Q1.1"
    ]


def test_node_status_rules():
    caps = cat(
        "A\tW0.1\tgreen\t\t", "B\tW0.1\tgreen\t\t", "C\tN1.1\tgreen\t\t", "D\tN1.1\tspec\t\t"
    )
    assert node_status("W0.1", caps) == "green"
    assert node_status("N1.1", caps) == "building"
    assert node_status("N1.2", caps) == "not-started"


def test_unknown_status_rejected():
    with pytest.raises(HarnessError):
        cat("A\tW0.1\tdone\t\t")


def test_live_graph_is_eligible_and_complete():
    nodes, caps = load_graph(), load_catalog()
    assert len(nodes) == 20
    assert len(caps) == 116
    assert find_cycle(nodes) is None
    assert eligibility_problems(nodes, caps) == []
    assert all(any(c.node == n for c in caps) for n in nodes), "every node has capability rows"


def test_cli_exit_codes(monkeypatch):
    assert vge.main([]) == 0
    assert vge.main(["--start", "Z9.9"]) == 1


@pytest.mark.parametrize(
    "graph",
    [
        "| **n1.1** | lower-case id | — |\n",
        "| **X1.1** | unknown prefix | — |\n",
        "| **W0.1** | two cells only |\n",
    ],
)
def test_malformed_graph_rows_are_rejected(graph):
    with pytest.raises(HarnessError):
        parse_graph(graph)


def test_tables_inside_code_fences_are_ignored():
    g = parse_graph("| **W0.1** | A | — |\n```\n| **N1.1** | example | W0.1 |\n```\n")
    assert list(g) == ["W0.1"]


@pytest.mark.parametrize(
    "text",
    [
        "H\tW0.1\tspec\t\t\n",  # no header
        HDR + "H\tW0.1\tspec\n",  # 3 columns
        HDR + "H\tW0.1\tspec\t\t\textra\n",  # 6 columns
        HDR + "\tW0.1\tspec\t\t\n",  # empty cap_id
    ],
)
def test_malformed_catalog_is_rejected(text):
    with pytest.raises(HarnessError):
        parse_catalog(text)


def test_cli_refuses_start_ahead_of_dependency(tmp_path):
    graph = tmp_path / "graph.md"
    graph.write_text("| **W0.1** | A | — |\n| **N1.1** | B | W0.1 |\n", encoding="utf-8")
    catalog = tmp_path / "catalog.tsv"
    catalog.write_text(HDR + "H\tW0.1\tbuilding\t\t\nS\tN1.1\tspec\t\t\n", encoding="utf-8")
    args = ["--graph", str(graph), "--catalog", str(catalog)]
    assert vge.main(args) == 0
    assert vge.main([*args, "--start", "N1.1"]) == 1
