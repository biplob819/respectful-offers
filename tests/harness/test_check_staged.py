import ast

import check_staged
from harness_lib import ROOT


def test_check_staged_runs_every_gate_tool_on_the_staged_tree():
    src = (ROOT / "scripts" / "check_staged.py").read_text(encoding="utf-8")
    for tool in ('"ruff", "check"', '"ruff", "format", "--check"', '"pyright"', '"pytest"'):
        assert tool in src
    assert '"--locked"' in src and "worktree" in src
    tree = ast.parse(src)
    assert any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in tree.body)
    assert callable(check_staged.main)


def test_the_staged_patch_keeps_its_final_newline():
    src = (ROOT / "scripts" / "check_staged.py").read_text(encoding="utf-8")
    assert "diff = proc.stdout" in src  # a stripped patch is corrupt (found when first run)
