import subprocess
from pathlib import Path

import node_start
from harness_lib import parse_catalog, parse_graph

HDR = "cap_id\tnode\tstatus\tproof\tnote\n"
GRAPH = parse_graph("| **W0.1** | Harness | — |\n| **N1.1** | Schemas | W0.1 |\n")


def make_spec(root: Path, node: str, criteria: str, files=node_start.SPEC_FILES) -> Path:
    d = root / "specs" / f"{node}-x"
    d.mkdir(parents=True)
    for f in files:
        (d / f).write_text(criteria if f == "criteria.md" else "x", encoding="utf-8")
    return root / "specs"


def test_self_test_passes():
    assert node_start.self_test() == 0


def test_go_when_everything_ready(tmp_path):
    specs = make_spec(tmp_path, "N1.1", "SCH-01")
    caps = parse_catalog(HDR + "H\tW0.1\tgreen\t\t\nSCH-01\tN1.1\tspec\t\t\n")
    assert node_start.check_start("N1.1", GRAPH, caps, specs) == []


def test_refuses_when_dependency_not_green(tmp_path):
    specs = make_spec(tmp_path, "N1.1", "SCH-01")
    caps = parse_catalog(HDR + "H\tW0.1\tbuilding\t\t\nSCH-01\tN1.1\tspec\t\t\n")
    assert any("dependency W0.1" in p for p in node_start.check_start("N1.1", GRAPH, caps, specs))


def test_refuses_when_criteria_miss_a_capability(tmp_path):
    specs = make_spec(tmp_path, "N1.1", "SCH-01")
    caps = parse_catalog(
        HDR + "H\tW0.1\tgreen\t\t\nSCH-01\tN1.1\tspec\t\t\nSCH-02\tN1.1\tspec\t\t\n"
    )
    assert node_start.check_start("N1.1", GRAPH, caps, specs) == [
        "criteria.md does not cover: SCH-02"
    ]


def test_refuses_when_spec_file_missing(tmp_path):
    specs = make_spec(tmp_path, "N1.1", "SCH-01", files=("spec.md", "criteria.md"))
    caps = parse_catalog(HDR + "H\tW0.1\tgreen\t\t\nSCH-01\tN1.1\tspec\t\t\n")
    assert any("tasks.md" in p for p in node_start.check_start("N1.1", GRAPH, caps, specs))


def test_refuses_without_spec_folder_or_rows(tmp_path):
    caps = parse_catalog(HDR + "H\tW0.1\tgreen\t\t\n")
    problems = node_start.check_start("N1.1", GRAPH, caps, tmp_path / "specs")
    assert "N1.1 has no capability rows in catalog.tsv" in problems
    assert any("no spec folder" in p for p in problems)


def test_refuses_unknown_node(tmp_path):
    assert node_start.check_start("Z1.1", GRAPH, [], tmp_path) == ["unknown node Z1.1"]


def test_live_w01_is_startable():
    # check only: main() would rewrite specs/W0.1-harness/.base on every test run
    nodes, caps = node_start.load_graph(), node_start.load_catalog()
    assert node_start.check_start("W0.1", nodes, caps, node_start.SPECS_DIR) == []


def _repo(tmp_path: Path) -> dict:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "a",
        ],
        cwd=tmp_path,
        check=True,
    )
    graph = tmp_path / "graph.md"
    graph.write_text("| **W0.1** | Harness | — |\n", encoding="utf-8")
    catalog = tmp_path / "catalog.tsv"
    catalog.write_text(HDR + "HAR-01\tW0.1\tspec\t\tnote one\n", encoding="utf-8")
    specs = make_spec(tmp_path, "W0.1", "HAR-01")
    return {"graph_path": graph, "catalog_path": catalog, "specs": specs, "root": tmp_path}


def _head(root: Path) -> str:
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True)
    return out.stdout.strip()


def test_check_only_writes_nothing(tmp_path):
    kw = _repo(tmp_path)
    before = kw["catalog_path"].read_bytes()
    assert node_start.start("W0.1", **kw) == 0
    assert not (kw["specs"] / "W0.1-x" / ".base").exists()
    assert kw["catalog_path"].read_bytes() == before


def test_mark_building_records_base_and_flips_rows(tmp_path):
    kw = _repo(tmp_path)
    assert node_start.start("W0.1", mark_building=True, **kw) == 0
    assert (kw["specs"] / "W0.1-x" / ".base").read_text(encoding="utf-8").strip() == _head(tmp_path)
    assert "HAR-01\tW0.1\tbuilding\t\tnote one" in kw["catalog_path"].read_text(encoding="utf-8")


def test_existing_base_is_kept_unless_reset(tmp_path):
    kw = _repo(tmp_path)
    base = kw["specs"] / "W0.1-x" / ".base"
    base.write_text("0123abcd\n", encoding="utf-8")
    node_start.start("W0.1", mark_building=True, **kw)
    assert base.read_text(encoding="utf-8").strip() == "0123abcd"
    node_start.start("W0.1", mark_building=True, reset_base=True, **kw)
    assert base.read_text(encoding="utf-8").strip() == _head(tmp_path)


def test_a_longer_cap_id_does_not_cover_a_shorter_one(tmp_path):
    specs = make_spec(tmp_path, "N1.1", "SCH-010")
    caps = parse_catalog(HDR + "H\tW0.1\tgreen\t\t\nSCH-01\tN1.1\tspec\t\t\n")
    problems = node_start.check_start("N1.1", GRAPH, caps, specs)
    assert any("SCH-01" in p for p in problems)
