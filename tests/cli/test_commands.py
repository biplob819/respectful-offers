"""B2.2: the full command line (CLI-01..06), run the way a user runs it."""

import json

import pytest

from respectful_offers import cli
from tests.cli.test_modules import table

COMMANDS = (
    "data",
    "features",
    "churn",
    "prereg",
    "simulate",
    "evaluate",
    "report",
    "run",
    "doctor",
    "init",
)


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("proj")
    assert (
        cli.main(["data", "synthetic", "--data-dir", str(root / "data"), "--members", "4000"]) == 0
    )
    return root


def run_json(capsys, argv):
    """The whole of stdout must be exactly one JSON document."""
    capsys.readouterr()
    code = cli.main([*argv, "--json"])
    out = capsys.readouterr().out
    assert out.count("\n") == 1, out
    return code, json.loads(out)


# -- CLI-01 every command ---------------------------------------------------------------------


def test_every_documented_command_exists():
    sub = next(a for a in cli.build_parser()._actions if a.dest == "command")
    assert set(COMMANDS) <= set(sub.choices)  # type: ignore[union-attr]


def test_churn_and_simulate_run_on_verified_data(project, capsys):
    base = ["--data-dir", str(project / "data"), "--root", str(project), "--run-id", "c"]
    code, out = run_json(capsys, ["churn", *base])
    assert (
        code == 0 and out["data_source"] == "synthetic" and 0.5 < out["report"]["auc"]["point"] <= 1
    )
    code, out = run_json(capsys, ["simulate", "--variant", "central", *base])
    assert code == 0 and len(out["learning_curve"]) == 4
    assert (project / "runs" / "c" / "bandit-central.json").is_file()


# -- CLI-02 doctor ----------------------------------------------------------------------------


def test_doctor_works_in_an_empty_folder_and_never_prints_secrets(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KAGGLE_USERNAME", "someone")
    monkeypatch.setenv("KAGGLE_KEY", "s3cr3t-value-123")
    code, out = run_json(capsys, ["doctor"])
    assert code == 0 and out["ok"] is True  # the bundled templates stand in for configs/
    assert "s3cr3t" not in json.dumps(out) and "someone" not in json.dumps(out)


# -- CLI-03 report --example --------------------------------------------------------------------


def test_report_example_never_overwrites_anything(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code, _out = run_json(capsys, ["report", "--example"])
    assert code == 0 and (tmp_path / "report-example" / "index.html").is_file()
    assert run_json(capsys, ["report", "--example"])[0] == 0  # its own folder again: fine
    mine = tmp_path / "mine"
    mine.mkdir()
    (mine / "notes.txt").write_text("keep me", encoding="utf-8")
    code, _ = run_json(capsys, ["report", "--example", "--out", str(mine)])
    assert code == cli.EXIT_ERROR and (mine / "notes.txt").read_text(encoding="utf-8") == "keep me"
    assert not (mine / "index.html").exists()
    code, _ = run_json(capsys, ["report", "--example", "--out", str(tmp_path / "runs" / "x")])
    assert code == cli.EXIT_ERROR
    html = (tmp_path / "report-example" / "index.html").read_text(encoding="utf-8")
    assert "synthetic, generated for testing" in html


# -- CLI-04 exit codes and --json everywhere ------------------------------------------------------


def test_every_command_takes_json_and_exits_with_the_documented_codes(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    for cmd in ("features", "churn", "simulate", "evaluate"):
        code, out = run_json(
            capsys, [cmd, "--data-dir", str(tmp_path / "nodata"), "--root", str(tmp_path)]
        )
        assert code == cli.EXIT_DATA and out["ok"] is False, cmd  # 3: raw data missing
    code, out = run_json(capsys, ["run", "--root", str(tmp_path)])
    assert code == cli.EXIT_ERROR and out["ok"] is False  # 2: --all not given
    code, out = run_json(capsys, ["report", "--root", str(tmp_path), "--run-id", "none"])
    assert code == cli.EXIT_ERROR
    code, out = run_json(capsys, ["init", str(tmp_path / "p")])
    assert code == 0 and out["ok"]


# -- CLI-05 run --all ---------------------------------------------------------------------------


def test_run_all_from_raw_files(project, capsys):
    code, out = run_json(
        capsys,
        [
            "run",
            "--all",
            "--variant",
            "central",
            "--data-dir",
            str(project / "data"),
            "--root",
            str(project),
            "--run-id",
            "all",
            "--out",
            str(project / "rep"),
        ],
    )
    assert code == 0 and out["audit_clean"] is True
    assert (project / "rep" / "index.html").is_file() and (
        project / "runs" / "all" / "summary.json"
    ).is_file()


def test_run_all_on_your_own_table_in_a_fresh_project(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init", "."]) == 0
    table(n=2000, seed=3).to_csv(tmp_path / "features.csv", index=False)
    assert cli.main(["prereg"]) == 0  # writes docs/prereg.md in the fresh project
    code, out = run_json(
        capsys,
        [
            "run",
            "--all",
            "--variant",
            "central",
            "--from-table",
            "features.csv",
            "--exploratory",
        ],
    )
    assert code == 0 and out["audit_clean"] is True
    s = json.loads((tmp_path / "runs" / "latest" / "summary.json").read_text(encoding="utf-8"))
    assert s["data_source"] == "your_table" and s["prereg_status"] == "exploratory"
    # a synthetic-scope registration never certifies your own (real) data
    code, out = run_json(
        capsys, ["evaluate", "--variant", "central", "--from-table", "features.csv"]
    )
    assert code == cli.EXIT_ERROR and "real" in out["error"]


# -- CLI-06 init --------------------------------------------------------------------------------


def test_init_never_overwrites_user_files(tmp_path, capsys):
    (tmp_path / "features.csv").write_text("mine\n", encoding="utf-8")
    code, out = run_json(capsys, ["init", str(tmp_path)])
    assert code == 0 and "features.csv" in out["kept"]
    assert (tmp_path / "features.csv").read_text(encoding="utf-8") == "mine\n"
    f = tmp_path / "afile"
    f.write_text("x", encoding="utf-8")
    assert run_json(capsys, ["init", str(f)])[0] == cli.EXIT_ERROR


# -- B2.2 verifier round 1 ----------------------------------------------------------------------


def test_report_example_refuses_marked_folders_with_user_files_and_symlinks(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    assert run_json(capsys, ["report", "--example", "--out", "ex"])[0] == 0
    (tmp_path / "ex" / "notes.txt").write_text(
        "mine", encoding="utf-8"
    )  # a previous example + a user file
    assert run_json(capsys, ["report", "--example", "--out", "ex"])[0] == cli.EXIT_ERROR
    (tmp_path / "ex2").mkdir()
    (tmp_path / "ex2" / ".offers-example").write_text("x", encoding="utf-8")
    (tmp_path / "ex2" / "index.html").write_text("precious", encoding="utf-8")
    assert run_json(capsys, ["report", "--example", "--out", "ex2"])[0] == cli.EXIT_ERROR
    assert (tmp_path / "ex2" / "index.html").read_text(encoding="utf-8") == "precious"
    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    (tmp_path / "ex3").mkdir()
    try:
        (tmp_path / "ex3" / "index.html").symlink_to(victim)
    except OSError:
        pytest.skip("symlinks unavailable here")
    assert run_json(capsys, ["report", "--example", "--out", "ex3"])[0] == cli.EXIT_ERROR
    assert victim.read_text(encoding="utf-8") == "keep"


def test_usage_errors_and_every_command_answer_in_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code, out = run_json(capsys, ["evaluate", "--nope"])
    assert code == cli.EXIT_ERROR and out["ok"] is False and "--nope" in out["error"]
    code, out = run_json(capsys, ["nonesuch"])
    assert code == cli.EXIT_ERROR and out["ok"] is False
    code, out = run_json(capsys, ["data", "verify", "--data-dir", str(tmp_path / "d")])
    assert code == cli.EXIT_DATA
    code, out = run_json(capsys, ["prereg"])  # no simulator here: refused, never the bundled one
    assert code == cli.EXIT_ERROR and "offers init" in out["error"]


def test_run_all_exits_1_when_a_real_violation_happens(project, monkeypatch, capsys):
    import numpy as np

    from respectful_offers.ope import data as ope_data
    from respectful_offers.policy import rollout as rollout_module

    def broken(**k):  # a respect filter that allows everything, wherever it is used
        return np.ones((len(k["churn_risk"]), 4), bool)

    monkeypatch.setattr(rollout_module, "allowed_actions", broken)
    monkeypatch.setattr(ope_data, "allowed_actions", broken)
    code, out = run_json(
        capsys,
        [
            "run",
            "--all",
            "--variant",
            "central",
            "--data-dir",
            str(project / "data"),
            "--root",
            str(project),
            "--run-id",
            "bad",
            "--out",
            str(project / "badrep"),
        ],
    )
    assert code == cli.EXIT_AUDIT and out["audit_clean"] is False


def test_validation_agrees_with_running(tmp_path, capsys):
    one = table(n=300)
    one = one[one["cohort"] == "mar"]
    one.to_csv(tmp_path / "one.csv", index=False)
    code, out = run_json(capsys, ["features", "--from-table", str(tmp_path / "one.csv")])
    assert (
        code == cli.EXIT_ERROR
        and "no 'feb' rows" in out["error"]
        and str(tmp_path / "one.csv") in out["error"]
    )
    table(n=300).to_csv(tmp_path / "t.txt", index=False)
    for cmd in (["features"], ["churn", "--root", str(tmp_path)]):
        code, out = run_json(capsys, [*cmd, "--from-table", str(tmp_path / "t.txt")])
        assert code == cli.EXIT_ERROR and ".csv or .parquet" in out["error"], cmd
    for cmd in (["features"], ["churn", "--root", str(tmp_path)]):
        assert (
            run_json(capsys, [*cmd, "--from-table", str(tmp_path / "missing.csv")])[0]
            == cli.EXIT_DATA
        )


def test_audit_table_problems_are_named(tmp_path, capsys):
    import pandas as pd

    table(n=300).to_csv(tmp_path / "f.csv", index=False)
    pd.DataFrame({"msno": ["nobody"], "age_band": ["25-34"], "gender": ["male"]}).to_csv(
        tmp_path / "a.csv", index=False
    )
    code, out = run_json(
        capsys,
        [
            "features",
            "--from-table",
            str(tmp_path / "f.csv"),
            "--audit-table",
            str(tmp_path / "a.csv"),
        ],
    )
    assert code == cli.EXIT_ERROR and "no member in the audit table" in out["error"]
    code, out = run_json(
        capsys, ["churn", "--root", str(tmp_path), "--audit-table", str(tmp_path / "a.csv")]
    )
    assert code == cli.EXIT_ERROR and "--from-table" in out["error"]


def test_the_init_readme_can_be_followed_to_a_preregistered_run(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init", "."]) == 0
    table(n=2000, seed=5).to_csv(tmp_path / "features.csv", index=False)  # step 1: your members
    assert run_json(capsys, ["features", "--from-table", "features.csv"])[0] == 0
    assert run_json(capsys, ["prereg", "--scope", "real"])[0] == 0  # step 3
    code, out = run_json(
        capsys, ["run", "--all", "--variant", "central", "--from-table", "features.csv"]
    )  # step 4
    assert code == 0 and out["audit_clean"] is True
    s = json.loads((tmp_path / "runs" / "latest" / "summary.json").read_text(encoding="utf-8"))
    assert s["prereg_status"] == "preregistered" and s["data_source"] == "your_table"


def test_simulate_needs_a_registration_for_real_data(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init", "."]) == 0
    table(n=1500, seed=6).to_csv(tmp_path / "features.csv", index=False)
    assert cli.main(["prereg"]) == 0  # synthetic scope only
    code, out = run_json(capsys, ["simulate", "--from-table", "features.csv"])
    assert code == cli.EXIT_ERROR and "--scope real" in out["error"]
    code, out = run_json(capsys, ["simulate", "--from-table", "features.csv", "--exploratory"])
    assert code == 0 and out["prereg_status"] == "exploratory"
    saved = json.loads(
        (tmp_path / "runs" / "latest" / "bandit-central.json").read_text(encoding="utf-8")
    )
    assert saved["prereg_status"] == "exploratory" and saved["data_source"] == "your_table"


def test_a_missing_raw_file_is_caught_even_with_a_warm_cache(project, capsys):
    import shutil

    base = ["--data-dir", str(project / "data"), "--root", str(project)]
    assert run_json(capsys, ["churn", *base, "--run-id", "warm"])[0] == 0
    raw = project / "data" / "raw" / "train.csv"
    shutil.move(raw, raw.with_suffix(".bak"))
    try:
        assert run_json(capsys, ["churn", *base, "--run-id", "cold"])[0] == cli.EXIT_DATA
    finally:
        shutil.move(raw.with_suffix(".bak"), raw)


def test_new_files_in_a_synthetic_folder_are_not_labelled_synthetic(tmp_path):
    from respectful_offers.data.verify import verify

    data = tmp_path / "data"
    assert cli.main(["data", "synthetic", "--data-dir", str(data), "--members", "500"]) == 0
    (data / "manifest.json").unlink()
    raw = data / "raw" / "train.csv"
    raw.write_text(raw.read_text(encoding="utf-8") + "zzz-new-member,0\n", encoding="utf-8")
    assert verify(data / "raw")["source"] == "local"


def test_doctor_survives_a_corrupt_manifest(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "manifest.json").write_text("{not json", encoding="utf-8")
    code, out = run_json(capsys, ["doctor"])  # reported as a problem, never a crash
    assert code == cli.EXIT_ERROR and any(
        c["name"] == "data" and not c["ok"] and "corrupt" in c["detail"] for c in out["checks"]
    )
