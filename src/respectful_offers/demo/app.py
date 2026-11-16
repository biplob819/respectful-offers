"""The demo page (D3.2): a policy simulator for a growth PM, in Streamlit.

    streamlit run src/respectful_offers/demo/app.py -- --cube demo/cube.json

Sliders for the discount budget and the risk threshold, a variant switch (central by default),
members retained and discount spent per policy, the live auditor's counts, a holdout card and a
footer that never lets anyone forget the outcomes are simulated. It reads one local file, the
aggregates-only cube; it makes no network or model calls (DEM-02). The deployed page asks for
a passkey first (DEM-04, `demo/gate.py`): only passkey hashes live in the app's secrets.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

POLICY_LABEL = {
    "no_offer": "No offer",
    "rule_following_baseline": "Rule-following baseline",
    "bandit": "Bandit",
    "status_quo": "Status quo (breaks the rules)",
}
CITATION = (  # OWNER D-46: outputs built from KKBox data cite the challenge
    "Members: aggregates of real, anonymised KKBox subscribers from the WSDM Cup 2018 KKBox "
    "churn prediction challenge (kaggle.com/competitions/kkbox-churn-prediction-challenge), "
    "used under its rules for non-commercial research and education. No member data is in "
    "this page or its cube."
)
MEMBERS = {
    "kaggle": "real, anonymised KKBox subscribers (aggregates)",
    "synthetic": "synthetic, not real people",
    "local": "from verified local files (aggregates)",
    "your_table": "from your own table (aggregates)",
}
FOOTER = (
    "Every outcome on this screen is simulated: members are sampled from an aggregates-only "
    "cube and respond as the pre-registered simulator says. Assumptions: the simulator YAML "
    "below, quoted in full."
)


def cube_path(argv: list[str]) -> Path:
    if "--cube" in argv:
        return Path(argv[argv.index("--cube") + 1])
    return Path(os.environ.get("OFFERS_DEMO_CUBE", "demo/cube.json"))


def rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for name, r in result["policies"].items():
        out.append(
            {
                "Policy": POLICY_LABEL.get(name, name),
                "Retained per 1,000": round(r["retained_per_1000"], 1),
                "Extra kept per 1,000 vs no offer": round(r["incremental_per_1000"], 1),
                "Discount spent per member (NTD)": round(r["discount_per_member"], 2),
                "Offers per member-month": round(r["offers_per_member_month"], 3),
                "Rule violations": sum(r["violations"].values()),
            }
        )
    return out


def threshold_range(cube: Any) -> tuple[float, float]:
    """Slider bounds from the cube: up to where members still sit (highest cell risk mean plus
    two spreads), never past 0.95, and always containing the reference threshold."""
    top = max(
        c["means"]["churn_risk"] + 2 * c["sds"].get("churn_risk", 0.0) for c in cube.data["cells"]
    )
    ref = float(cube.reference["risk_threshold"])
    return 0.01, round(min(0.95, max(top, ref + 0.05)), 2)


def _secrets_section(st: Any) -> Any:
    try:
        return st.secrets.get("demo") or {}
    except Exception:  # no secrets file: a local run
        return {}


def unlocked(st: Any, require: bool = False) -> bool:
    """The passkey gate (DEM-04). Draws the gate and returns False until the page may show."""
    import time

    from respectful_offers.demo import gate

    @st.cache_resource
    def throttle() -> gate.Throttle:  # one per app process, shared by every session
        return gate.Throttle()

    try:
        hashes = gate.configured_hashes(_secrets_section(st))
    except gate.PasskeyError as exc:
        st.error(f"This demo is locked: its passkey setting is broken ({exc}).")
        return False
    except Exception:  # any other malformed setting: locked, never open
        st.error("This demo is locked: its passkey setting is broken.")
        return False
    if not hashes:
        if require or gate.required():
            st.error("This demo is locked: its owner has not set a passkey yet.")
            return False
        return True  # a local run with no passkey configured
    state = st.session_state
    if state.get("passkey_ok"):
        return True
    st.markdown("**This demo is protected by a passkey.** Ask the owner for one.")
    now = time.time()
    if state.get("passkey_locked_until", 0.0) > now:
        wait = int(state["passkey_locked_until"] - now) + 1
        st.error(f"Too many wrong passkeys. Try again in {wait} seconds.")
        return False
    if throttle().blocked():
        st.error("Too many wrong passkeys from many visitors. Try again in a minute.")
        return False
    with st.form("passkey", clear_on_submit=True):
        entered = st.text_input("Passkey", type="password")
        submitted = st.form_submit_button("Unlock")
    if not submitted:
        return False
    slot = throttle().try_acquire()  # reserved before the slow check: no overshoot
    if slot is None:
        st.error("Too many wrong passkeys from many visitors. Try again in a minute.")
        return False
    if gate.check_passkey(entered, hashes):
        throttle().refund(slot)
        state["passkey_ok"] = True
        state["passkey_attempts"] = 0
        st.rerun()
        return True  # not reached: rerun draws the page
    state["passkey_attempts"] = state.get("passkey_attempts", 0) + 1
    if state["passkey_attempts"] >= gate.MAX_ATTEMPTS:
        state["passkey_locked_until"] = now + gate.LOCKOUT_SECONDS
        state["passkey_attempts"] = 0
    st.error("That passkey is not right.")
    return False


def main(require_passkey: bool = False) -> None:
    import altair as alt
    import pandas as pd
    import streamlit as st

    from respectful_offers.demo.engine import load_cube, simulate

    st.set_page_config(page_title="Respectful Offers: policy simulator", layout="wide")
    if not unlocked(st, require=require_passkey):
        st.caption(FOOTER)
        st.stop()

    @st.cache_resource
    def cube(path: str):
        return load_cube(Path(path))

    c = cube(str(cube_path(sys.argv)))
    ref = c.reference
    variants = list(ref["variants"])
    st.title("Respectful Offers: policy simulator")
    st.caption(
        f"Simulated · members: {MEMBERS.get(c.data['data_source'], c.data['data_source'])} · "
        "pre-registration: "
        f"{ref['prereg_status']} · simulator {ref['simulator_hash']}"
    )
    lo, hi = threshold_range(c)
    left, mid, right = st.columns(3)
    budget = left.slider(
        "Discount budget (NTD per 1,000 members per month)",
        0,
        12000,
        int(ref["budget_per_1000"]),
        step=500,
    )
    threshold = mid.slider(
        "Risk threshold (members at or above it count as at risk)",
        lo,
        hi,
        float(ref["risk_threshold"]),
        step=0.01,
    )
    variant = right.radio(
        "Simulator variant",
        variants,
        index=variants.index("central") if "central" in variants else 0,
        horizontal=True,
    )
    result = simulate(c, float(budget), float(threshold), str(variant))

    audit_ok = all(
        sum(r["violations"].values()) == 0 for r in result["policies"].values() if r["respectful"]
    )
    if not audit_ok:  # never show numbers the audit says must not be shown
        st.error("A respectful policy broke a rule in this simulation: no results are shown.")
        st.caption(FOOTER)
        st.stop()

    st.info(
        f"Bandit trained at threshold {result['bandit_trained_at']:.2f}; moving the slider "
        "changes which offers the rules allow, not what the bandit learned."
    )
    if result["at_risk_now"] == 0:
        st.warning(
            "At this threshold no member counts as at risk, so the rules allow every "
            "offer to everyone and the status quo offers nothing: lower the threshold."
        )

    table = pd.DataFrame(rows(result))
    cols = st.columns(len(table))
    for col, (_, r) in zip(cols, table.iterrows(), strict=True):
        is_base = r["Policy"] == POLICY_LABEL["no_offer"]
        col.metric(
            f"{r['Policy']}: members kept per 1,000 (simulated)",
            f"{r['Retained per 1,000']:.1f}",
            None if is_base else f"{r['Extra kept per 1,000 vs no offer']:+.1f} vs no offer",
        )
        col.caption(
            f"{r['Discount spent per member (NTD)']:.2f} NTD per member · "
            f"{r['Rule violations']} rule violations (simulated)"
        )
    st.subheader("Members kept against discount spent (simulated)")
    chart = (
        alt.Chart(table)
        .mark_point(size=120, filled=True)
        .encode(
            x=alt.X("Discount spent per member (NTD):Q"),
            y=alt.Y("Retained per 1,000:Q", scale=alt.Scale(zero=False)),
            shape="Policy:N",
            color="Policy:N",
            tooltip=list(table.columns),
        )
    )
    st.altair_chart(chart, width="stretch")
    st.subheader("Live respect audit (simulated)")
    st.dataframe(table, hide_index=True, width="stretch")
    st.success("Every respectful policy: zero violations of R1, R2, R3, R7, R8.")
    with st.container(border=True):
        share = ref.get("holdout_share")
        check = ref.get("holdout_check", {}).get(str(variant))
        st.markdown("**Holdout (simulated)**")
        if share is not None and check is not None:
            verdict = (
                "consistent with" if check["lo"] <= 0 <= check["hi"] else "NOT consistent with"
            )
            st.write(
                f"{share:.0%} of members are never offered anything. In the full run, holdout "
                f"retention minus no-offer retention was {check['point']:+.1f} per 1,000 "
                f"(95% interval {check['lo']:+.1f} to {check['hi']:+.1f}), {verdict} no "
                "difference, which is how we know the lift is not a measurement artefact."
            )
        else:
            st.write("This cube does not carry the run's holdout check.")
    st.divider()
    st.caption(FOOTER)
    if c.data["data_source"] == "kaggle":
        st.caption(CITATION)
    with st.expander("The simulator, quoted in full"):
        st.code(c.data["simulator_yaml"], language="yaml")


if __name__ == "__main__":
    main()
