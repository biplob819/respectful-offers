"""B2.2 building blocks: your own table as features, doctor, init, templates, the example."""

import json

import numpy as np
import pandas as pd
import pytest

from harness_lib import ROOT
from respectful_offers.doctor import run_checks
from respectful_offers.features.table import TableFeaturesStage
from respectful_offers.runtime import RunContext, import_artifact, run_stage
from respectful_offers.scaffold import scaffold
from respectful_offers.schemas.contracts import ContractError
from respectful_offers.schemas.summary import RunSummary


def table(n=600, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for cohort, as_of in (("feb", "2017-02-01"), ("mar", "2017-03-01")):
        for i in range(n):
            rows.append(
                {
                    "msno": f"U{i:05d}",
                    "cohort": cohort,
                    "as_of": as_of,
                    "tenure_days": int(rng.integers(30, 2000)),
                    "auto_renew": bool(rng.uniform() < 0.8),
                    "cancels_90d": int(rng.poisson(0.1)),
                    "listening_trend_30d": float(np.clip(rng.normal(0, 0.3), -1, 3)),
                    "price_30d": float(rng.choice([99.0, 149.0])),
                    "plan_days": 30,
                    "churn_label": bool(rng.uniform() < 0.1),
                }
            )
    return pd.DataFrame(rows)


def test_your_own_table_becomes_the_features_artifact(tmp_path):
    t = table()
    t.to_csv(tmp_path / "features.csv", index=False)
    audit = pd.DataFrame(
        {"msno": [f"U{i:05d}" for i in range(0, 600, 2)], "age_band": "25-34", "gender": "female"}
    )
    audit.to_csv(tmp_path / "audit.csv", index=False)
    ctx = RunContext(tmp_path / "proj", run_id="t", config_hash="c", seed=0)
    src = import_artifact(
        ctx,
        "table",
        {"features.csv": tmp_path / "features.csv", "audit.csv": tmp_path / "audit.csv"},
    )
    ref = run_stage(TableFeaturesStage(), {"table": src}, ctx)
    feb = pd.read_parquet(ref.path / "features_feb.parquet")
    mar = pd.read_parquet(ref.path / "features_mar.parquet")
    assert len(feb) == len(mar) == 600 and set(feb["cohort"]) == {"feb"}
    attrs = pd.read_parquet(ref.path / "audit_attributes.parquet")
    assert (
        len(attrs) == 600 and (attrs["gender"] == "unknown").sum() == 300
    )  # missing rows → unknown
    stats = json.loads((ref.path / "stats.json").read_text(encoding="utf-8"))
    assert stats["mar"]["provenance"] == {"source": "your own features table"}


@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda t: t[t["cohort"] == "mar"], "no 'feb' rows"),
        (lambda t: t.assign(churn_label=False), "both churners and renewers"),
        (lambda t: t.assign(gender="x"), "unexpected column"),
    ],
)
def test_bad_tables_name_the_problem(tmp_path, mutate, match):
    mutate(table()).to_csv(tmp_path / "features.csv", index=False)
    ctx = RunContext(tmp_path / "proj", run_id="t", config_hash="c", seed=0)
    src = import_artifact(ctx, "table", {"features.csv": tmp_path / "features.csv"})
    with pytest.raises(ContractError, match=match):
        run_stage(TableFeaturesStage(), {"table": src}, ctx)


def test_audit_table_errors_name_row_and_column(tmp_path):
    table().to_csv(tmp_path / "features.csv", index=False)
    pd.DataFrame({"msno": ["U00000"], "age_band": ["30ish"], "gender": ["female"]}).to_csv(
        tmp_path / "audit.csv", index=False
    )
    ctx = RunContext(tmp_path / "proj", run_id="t", config_hash="c", seed=0)
    src = import_artifact(
        ctx,
        "table",
        {"features.csv": tmp_path / "features.csv", "audit.csv": tmp_path / "audit.csv"},
    )
    with pytest.raises(ContractError, match=r"row 2: column age_band"):
        run_stage(TableFeaturesStage(), {"table": src}, ctx)


def test_doctor_reports_without_printing_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("KAGGLE_USERNAME", "someone")
    monkeypatch.setenv("KAGGLE_KEY", "s3cr3t-value-123")
    checks = run_checks(
        tmp_path,
        tmp_path / "data",
        ROOT / "configs" / "simulator.yaml",
        ROOT / "docs" / "prereg.md",
        ROOT / "configs" / "run.yaml",
    )
    by = {c.name: c for c in checks}
    assert by["python"].ok and by["run config"].ok and by["simulator"].ok
    assert by["kaggle credentials"].ok and "never shown" in by["kaggle credentials"].detail
    assert not by["data"].ok and not by["data"].required
    assert all("s3cr3t" not in c.detail and "someone" not in c.detail for c in checks)


def test_init_scaffolds_and_never_overwrites(tmp_path):
    first = scaffold(tmp_path / "p")
    assert sorted(first["written"]) == [
        "README.md",
        "audit.csv",
        "features.csv",
        "offers-run.yaml",
        "simulator.yaml",
    ]
    (tmp_path / "p" / "features.csv").write_text("mine\n", encoding="utf-8")
    again = scaffold(tmp_path / "p")
    assert again["written"] == [] and len(again["kept"]) == 5
    assert (tmp_path / "p" / "features.csv").read_text(encoding="utf-8") == "mine\n"


def test_templates_are_byte_for_byte_copies_of_the_configs():
    for name in ("run.yaml", "simulator.yaml"):
        tpl = ROOT / "src" / "respectful_offers" / "templates" / name
        assert tpl.read_bytes() == (ROOT / "configs" / name).read_bytes(), name


def test_the_bundled_example_is_a_valid_clean_synthetic_run():
    from respectful_offers.sim.prereg import sha256

    ex = ROOT / "src" / "respectful_offers" / "examples"
    s = RunSummary.model_validate_json((ex / "summary.json").read_text(encoding="utf-8"))
    assert s.simulated is True and s.run_id == "example"
    assert (
        s.simulator_hash == sha256(ROOT / "configs" / "simulator.yaml")[:16]
    )  # regenerate after editing it
    assert json.loads((ex / "audit.json").read_text(encoding="utf-8"))["clean"] is True
    assert "msno" not in (ex / "summary.json").read_text(encoding="utf-8")
