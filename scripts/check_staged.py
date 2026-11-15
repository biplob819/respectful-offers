#!/usr/bin/env python3
"""Check exactly what is staged, in isolation, before a node commit (L-24).

Drafts of later nodes live in the same working tree, so a green converge proves nothing
about the commit: a staged file can import an unstaged one. This script builds a throwaway
git worktree from HEAD, applies the staged diff, and runs ruff, pyright and pytest there.

Usage:
    python scripts/check_staged.py            # exit 0 only if the staged tree is clean
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from harness_lib import ROOT


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    return p.returncode, (p.stdout + p.stderr).strip()


def main() -> int:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--binary"], cwd=ROOT, capture_output=True, text=True
    )
    if proc.returncode != 0:
        print(proc.stderr)
        return 1
    diff = proc.stdout  # unstripped: a patch needs its final newline
    with tempfile.TemporaryDirectory(prefix="staged-") as tmp:
        tree = Path(tmp) / "tree"
        code, out = run(["git", "worktree", "add", "--detach", str(tree), "HEAD"], ROOT)
        if code != 0:
            print(out)
            return 1
        try:
            if diff:
                p = subprocess.run(
                    ["git", "apply", "--index", "-"],
                    cwd=tree,
                    input=diff,
                    text=True,
                    capture_output=True,
                )
                if p.returncode != 0:
                    print("cannot apply staged diff:", p.stderr)
                    return 1
            env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(Path(tmp) / "venv")}
            steps = [
                ["uv", "sync", "-q", "--locked", "--all-extras"],
                ["uv", "run", "ruff", "check", "."],
                ["uv", "run", "ruff", "format", "--check", "."],
                ["uv", "run", "pyright"],
                ["uv", "run", "pytest", "-q", "-x"],
            ]
            for step in steps:
                code, out = run(step, tree, env)
                status = "PASS" if code == 0 else "FAIL"
                print(f"{status}  {' '.join(step[2:] if step[0] == 'uv' else step)}")
                if code != 0:
                    print("\n".join(out.splitlines()[-15:]))
                    return 1
        finally:
            run(["git", "worktree", "remove", "--force", str(tree)], ROOT)
    print("staged tree: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
