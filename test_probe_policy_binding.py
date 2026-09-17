"""AUR-I-01 probe: a failed pre-trade gate must bind the approval.

Reproduces the Aureon inventory probe (15 Sep 2026, commit a433577): the
pre-trade gate returned FAIL because drawdown was 9% against the 8% hard
limit, yet resolve_pending_decision() still approved the same decision, cash
fell from $10,000 to $9,000 and a position was created. The approval service
never consumes the gate result.

test_probe_policy_binding_gate_fails is an ordinary test. It proves the
fixture really does produce a FAIL today, so the xfail below cannot be
"expected to fail" for some unrelated reason.

test_failed_pretrade_gate_blocks_approval was a strict xfail until W2B-3
bound approval to the persisted gate result; the marker is removed and the
test passes. The full binding suite is test_policy_binding.py.

Run: pytest -q test_probe_policy_binding.py
"""

import copy
import threading

from aureon.approval_service.service import resolve_pending_decision
from aureon.policy_engine.binding import PolicyBindingError, pretrade_rules_digest
from aureon.policy_engine.service import evaluate_pretrade_decision

DECISION_ID = "DEC-PROBE-AUR-I-01"


def _state():
    return {
        "portfolio_value": 10_000.0,
        "cash": 10_000.0,
        "drawdown": 9.0,  # percent; the hard limit below is 8%
        "positions": [],
        "trades": [],
        "authority_log": [],
        "prices": {"TEST": 100.0},
        "pending_decisions": [{
            "id": DECISION_ID,
            "symbol": "TEST",
            "action": "BUY",
            "asset_class": "equity",
            "shares": 10,
            "price": 100.0,
            "notional": 1_000.0,
            "required_approvals": ["TRADER"],
            "current_approvals": [],
        }],
    }


RISK_POLICY = {"drawdown_warn_pct": 5.0, "drawdown_fail_pct": 8.0}


def _pretrade(state, lock):
    # Same limits server.py passes: RISK_MANAGER_POLICY drawdown 5% warn / 8% fail,
    # OPERATING_CASH_FLOOR_PCT 3%.
    return evaluate_pretrade_decision(
        state=state,
        lock=lock,
        decision_id=DECISION_ID,
        market_is_open=lambda: True,
        macro_snapshot_fn=dict,
        ofr_snapshot_fn=dict,
        operating_cash_floor_pct=0.03,
        risk_policy=RISK_POLICY,
        symbol_to_isin={},
        ofac_blocked_isins={},
    )


def test_probe_policy_binding_gate_fails():
    state, lock = _state(), threading.Lock()
    result = _pretrade(state, lock)
    gates = {g["gate"]: g["status"] for g in result["gates"]}
    assert gates["DRAWDOWN_LIMIT"] == "FAIL"
    assert result["overall"] == "FAIL"


def test_failed_pretrade_gate_blocks_approval():
    state, lock = _state(), threading.Lock()
    assert _pretrade(state, lock)["overall"] == "FAIL"
    cash_before = state["cash"]
    positions_before = copy.deepcopy(state["positions"])

    # The rules digest is the one in force, so the refusal below is the FAIL
    # itself, not missing context.
    try:
        result = resolve_pending_decision(
            state=state,
            lock=lock,
            decision_id=DECISION_ID,
            resolution="APPROVED",
            approval_role="TRADER",
            rules_digest=pretrade_rules_digest(
                risk_policy=RISK_POLICY, operating_cash_floor_pct=0.03, ofac_blocked_isins={}
            ),
        )
    except PolicyBindingError as exc:
        assert exc.code == "POLICY_BLOCK"
        result = None

    assert result is None
    assert state["cash"] == cash_before
    assert state["positions"] == positions_before
    assert state["trades"] == []
