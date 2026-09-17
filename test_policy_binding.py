"""W2B-3: pre-trade policy binds approval (AUR-I-01, AUR-I-08, AUR-I-09, AUR-I-10).

Aureon inventory §14 criteria turned into tests:

- Given any gate result FAIL or BLOCK, no API or internal call produces an
  approval. There is no CLI or MCP approval path (asserted below), so every
  approval goes through resolve_pending_decision, where the check lives.
- HOLD proceeds only with a typed exception: required authority, reason,
  expiry, and the policy's overrideable flag.
- Changing an economic term invalidates prior evidence.
- Unavailable required evidence is INDETERMINATE, never PASS.
- Primary and fallback evaluation return the same result (one pro-forma
  concentration calculation).
- Materiality and exception flags change required approvals.

Run: pytest -q test_policy_binding.py
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("RAILWAY_VOLUME_MOUNT_PATH", tempfile.mkdtemp(prefix="aureon-binding-test-"))

from aureon.approval_service.operator_auth import OPERATOR_ACTOR  # noqa: E402
from aureon.approval_service.service import (  # noqa: E402
    resolve_pending_decision,
    routed_required_approvals,
)
from aureon.policy_engine import binding  # noqa: E402
from aureon.policy_engine.binding import (  # noqa: E402
    PolicyBindingError,
    grant_hold_exception,
    latest_policy_record,
    pretrade_rules_digest,
)
from aureon.policy_engine.service import evaluate_pretrade_decision  # noqa: E402

RISK = {"drawdown_warn_pct": 5.0, "drawdown_fail_pct": 8.0,
        "position_warn_pct": 20.0, "position_fail_pct": 35.0}
FLOOR = 0.03
OFAC: dict[str, str] = {}
RULES = pretrade_rules_digest(risk_policy=RISK, operating_cash_floor_pct=FLOOR, ofac_blocked_isins=OFAC)
T0 = datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc)
GOOD_OFR = {"fsi_value": 0.2, "source": "test"}


def _decision(**overrides):
    decision = {
        "id": "DEC-BIND-1", "symbol": "TEST", "action": "BUY", "asset_class": "equities",
        "shares": 10, "price": 100.0, "notional": 1_000.0,
        "required_approvals": ["TRADER"], "current_approvals": [],
    }
    decision.update(overrides)
    return decision


def _state(decision=None, **overrides):
    state = {
        "portfolio_value": 100_000.0, "cash": 50_000.0, "drawdown": 1.0,
        "positions": [], "trades": [], "authority_log": [], "prices": {"TEST": 100.0},
        "pending_decisions": [decision or _decision()],
    }
    state.update(overrides)
    return state


def _evaluate(state, *, ofr=GOOD_OFR, extra_gates=None, now=T0, risk=RISK, decision_id=None):
    return evaluate_pretrade_decision(
        state=state, lock=threading.RLock(),
        decision_id=decision_id or state["pending_decisions"][0]["id"],
        market_is_open=lambda: True,
        macro_snapshot_fn=dict,
        ofr_snapshot_fn=lambda _macro: ofr,
        operating_cash_floor_pct=FLOOR, risk_policy=risk,
        symbol_to_isin={}, ofac_blocked_isins=OFAC,
        asset_class_gate_fn=(lambda _d: list(extra_gates)) if extra_gates else None,
        now=now,
    )


def _resolve(state, *, role="TRADER", now=T0 + timedelta(seconds=30), rules=RULES,
             hold_exception=None, decision_id=None):
    return resolve_pending_decision(
        state=state, lock=threading.RLock(),
        decision_id=decision_id or state["pending_decisions"][0]["id"],
        resolution="APPROVED", approval_role=role,
        build_trade_report=lambda *a: {"report_id": "RPT-TEST"},
        rules_digest=rules, hold_exception=hold_exception, now=now,
    )


def _refused(state, code, **kwargs):
    before = copy.deepcopy({k: v for k, v in state.items() if k not in ("policy_evaluations",)})
    with pytest.raises(PolicyBindingError) as info:
        _resolve(state, **kwargs)
    assert info.value.code == code, info.value
    after = {k: v for k, v in state.items() if k not in ("policy_evaluations",)}
    assert after == before, "a refused approval must change nothing"
    return info.value


MIFIR_HOLD = {"gate": "MIFIR_PRETRADE_TRANSPARENCY", "layer": "Thifur-J", "status": "HOLD",
              "detail": "transparency not evidenced"}


# ── Refusals ────────────────────────────────────────────────────────────────────


def test_pass_is_approved_and_the_trade_carries_the_policy_record() -> None:
    state = _state()
    payload = _evaluate(state)
    assert payload["disposition"] == "PASS"
    result = _resolve(state)
    assert result["status"] == "ok"
    assert state["cash"] == 49_000.0
    assert state["trades"][0]["policy"]["record_id"] == payload["policy_record"]["record_id"]
    assert state["authority_log"][0]["policy"]["disposition"] == "PASS"


def test_fail_is_refused_whichever_gate_fails() -> None:
    for state in (
        _state(drawdown=9.0),                                            # drawdown
        _state(cash=500.0),                                              # cash
        _state(positions=[{"symbol": "TEST", "shares": 400, "cost": 100.0}]),  # concentration
    ):
        assert _evaluate(state)["disposition"] == "BLOCK"
        _refused(state, "POLICY_BLOCK")


def test_a_partial_approval_is_refused_too() -> None:
    state = _state(_decision(required_approvals=["TRADER", "RISK"]), drawdown=9.0)
    _evaluate(state)
    _refused(state, "POLICY_BLOCK", role="RISK")
    assert state["pending_decisions"][0]["current_approvals"] == []


def test_no_evidence_is_refused() -> None:
    _refused(_state(), "NO_POLICY_EVIDENCE")


def test_missing_rules_digest_is_refused() -> None:
    state = _state()
    _evaluate(state)
    _refused(state, "RULES_UNKNOWN", rules=None)


def test_changed_terms_make_the_evidence_stale() -> None:
    state = _state()
    _evaluate(state)
    state["pending_decisions"][0]["notional"] = 40_000.0
    _refused(state, "STALE_POLICY_EVIDENCE")


def test_changed_rules_make_the_evidence_stale() -> None:
    state = _state()
    _evaluate(state)
    tighter = pretrade_rules_digest(
        risk_policy={**RISK, "drawdown_fail_pct": 0.5}, operating_cash_floor_pct=FLOOR,
        ofac_blocked_isins=OFAC,
    )
    _refused(state, "STALE_POLICY_EVIDENCE", rules=tighter)


def test_expired_evidence_is_refused() -> None:
    state = _state()
    _evaluate(state)
    expiry = binding.POLICY_EVIDENCE_TTL_SECONDS
    _refused(state, "STALE_POLICY_EVIDENCE", now=T0 + timedelta(seconds=expiry))


def test_the_latest_evaluation_governs() -> None:
    state = _state()
    _evaluate(state)                                 # PASS
    state["drawdown"] = 9.0
    _evaluate(state, now=T0 + timedelta(seconds=10))  # FAIL
    _refused(state, "POLICY_BLOCK")


def test_a_tampered_record_is_refused() -> None:
    state = _state(drawdown=9.0)
    _evaluate(state)
    raw = state["policy_evaluations"][0]
    raw["disposition"] = "PASS"
    for gate in raw["gates"]:
        gate["disposition"] = "PASS"
    _refused(state, "POLICY_EVIDENCE_INVALID")


# ── AUR-I-10: unavailable evidence is INDETERMINATE ─────────────────────────────


@pytest.mark.parametrize("ofr", [{}, None, {"fsi_value": float("nan")}, {"fsi_value": "high"}])
def test_unusable_stress_reading_is_indeterminate_and_refused(ofr) -> None:
    state = _state()
    payload = _evaluate(state, ofr=ofr)
    macro = next(g for g in payload["gates"] if g["gate"] == "MACRO_STRESS_OVERLAY")
    assert macro["status"] == "INDETERMINATE"
    assert macro["disposition"] == "INDETERMINATE"
    assert payload["disposition"] == "INDETERMINATE"
    assert payload["overall"] == "INDETERMINATE"
    _refused(state, "POLICY_INDETERMINATE")


def test_a_stress_feed_that_raises_is_indeterminate() -> None:
    state = _state()

    def broken(_macro):
        raise TimeoutError("feed down")

    payload = evaluate_pretrade_decision(
        state=state, lock=threading.RLock(), decision_id="DEC-BIND-1",
        market_is_open=lambda: True, macro_snapshot_fn=dict, ofr_snapshot_fn=broken,
        operating_cash_floor_pct=FLOOR, risk_policy=RISK, symbol_to_isin={},
        ofac_blocked_isins=OFAC, now=T0,
    )
    assert payload["disposition"] == "INDETERMINATE"


def test_indeterminate_cannot_be_overridden() -> None:
    state = _state()
    _evaluate(state, ofr={})
    record = latest_policy_record(state, "DEC-BIND-1")
    with pytest.raises(PolicyBindingError) as info:
        grant_hold_exception(record=record, actor=OPERATOR_ACTOR, authority_role="COMPLIANCE",
                             reason="looks fine", ttl_seconds=600, now=T0)
    assert info.value.code == "HOLD_EXCEPTION_NOT_APPLICABLE"


@pytest.mark.parametrize("gate", [
    {"gate": "TOKENIZED_ELIGIBILITY", "layer": "Thifur-J", "status": "HOLD",
     "disposition": "INDETERMINATE", "detail": "declared, not yet implemented"},
    {"gate": "ASSET_CLASS_DISPATCH", "layer": "Thifur-J", "status": "INDETERMINATE", "detail": "x"},
    {"gate": "SOMETHING_NEW", "layer": "x", "status": "UNHEARD_OF", "detail": "x"},
])
def test_checks_that_could_not_run_are_indeterminate(gate) -> None:
    state = _state()
    assert _evaluate(state, extra_gates=[gate])["disposition"] == "INDETERMINATE"


def test_an_explicit_disposition_never_loosens_a_status() -> None:
    assert binding.gate_disposition({"status": "FAIL", "disposition": "PASS"}).value == "BLOCK"


def test_asset_class_gates_that_cannot_run_declare_indeterminate() -> None:
    from aureon.agents.jtac import pretrade_structuring
    source = pathlib.Path(pretrade_structuring.__file__).read_text(encoding="utf-8")
    assert source.count('"disposition": "INDETERMINATE"') >= 4


# ── HOLD needs a typed exception ────────────────────────────────────────────────


def test_hold_without_an_exception_is_refused() -> None:
    state = _state()
    assert _evaluate(state, extra_gates=[MIFIR_HOLD])["disposition"] == "HOLD"
    _refused(state, "HOLD_EXCEPTION_REQUIRED")


def test_hold_exception_requires_the_policy_role() -> None:
    state = _state()
    _evaluate(state, extra_gates=[MIFIR_HOLD])
    record = latest_policy_record(state, "DEC-BIND-1")
    with pytest.raises(PolicyBindingError) as info:
        grant_hold_exception(record=record, actor=OPERATOR_ACTOR, authority_role="TRADER",
                             reason="published on venue", ttl_seconds=600, now=T0)
    assert info.value.code == "HOLD_EXCEPTION_AUTHORITY"


@pytest.mark.parametrize(("reason", "ttl"), [("", 600), ("   ", 600), ("ok", 0),
                                             ("ok", binding.MAX_HOLD_EXCEPTION_SECONDS + 1)])
def test_hold_exception_requires_reason_and_bounded_expiry(reason, ttl) -> None:
    state = _state()
    _evaluate(state, extra_gates=[MIFIR_HOLD])
    record = latest_policy_record(state, "DEC-BIND-1")
    with pytest.raises(PolicyBindingError) as info:
        grant_hold_exception(record=record, actor=OPERATOR_ACTOR, authority_role="COMPLIANCE",
                             reason=reason, ttl_seconds=ttl, now=T0)
    assert info.value.code == "HOLD_EXCEPTION_INVALID"


def test_a_hold_the_policy_does_not_list_is_not_overrideable() -> None:
    state = _state()
    held = {"gate": "TOKENIZED_ELIGIBILITY", "layer": "Thifur-J", "status": "HOLD",
            "detail": "issuer authorization pending"}
    payload = _evaluate(state, extra_gates=[held])
    assert payload["disposition"] == "HOLD"
    assert payload["gates"][-1]["overrideable"] is False
    record = latest_policy_record(state, "DEC-BIND-1")
    with pytest.raises(PolicyBindingError) as info:
        grant_hold_exception(record=record, actor=OPERATOR_ACTOR, authority_role="COMPLIANCE",
                             reason="trust me", ttl_seconds=600, now=T0)
    assert info.value.code == "HOLD_NOT_OVERRIDEABLE"


def test_hold_with_a_valid_exception_proceeds_and_is_recorded() -> None:
    state = _state()
    _evaluate(state, extra_gates=[MIFIR_HOLD])
    record = latest_policy_record(state, "DEC-BIND-1")
    exception = grant_hold_exception(
        record=record, actor=OPERATOR_ACTOR, authority_role="COMPLIANCE",
        reason="Published on the venue's APA; screenshot filed", ttl_seconds=600,
        now=T0 + timedelta(seconds=5),
    )
    # COMPLIANCE is not a required role: the grant is recorded as a partial approval.
    partial = _resolve(state, role="COMPLIANCE", hold_exception=exception)
    assert partial["status"] == "ok" or partial["status"] == "pending"
    assert state["policy_hold_exceptions"][0]["exception_id"] == exception.exception_id
    assert any(e["id"] == exception.exception_id for e in state["authority_log"])
    if partial["status"] == "pending":
        assert _resolve(state, role="TRADER")["status"] == "ok"
    assert state["cash"] == 49_000.0


def test_an_expired_exception_no_longer_covers_the_hold() -> None:
    state = _state()
    _evaluate(state, extra_gates=[MIFIR_HOLD])
    record = latest_policy_record(state, "DEC-BIND-1")
    exception = grant_hold_exception(record=record, actor=OPERATOR_ACTOR,
                                     authority_role="COMPLIANCE", reason="attested",
                                     ttl_seconds=10, now=T0)
    _refused(state, "HOLD_EXCEPTION_REQUIRED", role="COMPLIANCE", hold_exception=exception,
             now=T0 + timedelta(seconds=11))


def test_an_exception_for_other_evidence_does_not_carry_over() -> None:
    state = _state()
    _evaluate(state, extra_gates=[MIFIR_HOLD])
    old = latest_policy_record(state, "DEC-BIND-1")
    exception = grant_hold_exception(record=old, actor=OPERATOR_ACTOR,
                                     authority_role="COMPLIANCE", reason="attested",
                                     ttl_seconds=600, now=T0)
    binding.persist_hold_exception(state, exception)
    _evaluate(state, extra_gates=[MIFIR_HOLD], now=T0 + timedelta(seconds=20))  # a new record
    _refused(state, "HOLD_EXCEPTION_REQUIRED", now=T0 + timedelta(seconds=25))


# ── AUR-I-09: one pro-forma concentration; cash floor ───────────────────────────


def test_concentration_is_pro_forma() -> None:
    # 30% held (WARN before the trade); buying 10% more reaches 40% (FAIL).
    state = _state(_decision(shares=100, notional=10_000.0),
                   positions=[{"symbol": "TEST", "shares": 300, "cost": 100.0}])
    gate = next(g for g in _evaluate(state)["gates"] if g["gate"] == "POSITION_CONCENTRATION")
    assert gate["status"] == "FAIL"
    assert "30.0% → 40.0%" in gate["detail"]


def test_a_sell_reduces_pro_forma_concentration() -> None:
    state = _state(_decision(action="SELL", shares=100, notional=10_000.0),
                   positions=[{"symbol": "TEST", "shares": 400, "cost": 100.0}])
    gate = next(g for g in _evaluate(state)["gates"] if g["gate"] == "POSITION_CONCENTRATION")
    assert gate["status"] == "WARN"  # 40% → 30%


def test_the_cash_floor_is_enforced_at_the_gate() -> None:
    # 3% of 100,000 stays liquid: 10,000 cash leaves 7,000 available.
    ok = _state(_decision(shares=70, notional=7_000.0), cash=10_000.0)
    assert _evaluate(ok)["disposition"] == "PASS"
    breach = _state(_decision(shares=71, notional=7_100.0), cash=10_000.0)
    gate = next(g for g in _evaluate(breach)["gates"] if g["gate"] == "CASH_SUFFICIENCY")
    assert gate["status"] == "FAIL"
    _refused(breach, "POLICY_BLOCK")


def test_no_portfolio_value_is_indeterminate_not_pass() -> None:
    state = _state(portfolio_value=0.0)
    gate = next(g for g in _evaluate(state)["gates"] if g["gate"] == "POSITION_CONCENTRATION")
    assert gate["disposition"] == "INDETERMINATE"


# ── AUR-I-08: routing ───────────────────────────────────────────────────────────


def test_routing_adds_roles_for_materiality_and_flags() -> None:
    assert routed_required_approvals(_decision()) == ["TRADER"]
    assert routed_required_approvals(_decision(notional=400_000.0)) == ["TRADER", "RISK"]
    assert routed_required_approvals(_decision(mandate_sensitive=True)) == ["TRADER", "COMPLIANCE"]
    assert routed_required_approvals(_decision(pm_signoff_required=True,
                                               control_exception=True)) == ["TRADER", "PM", "CONTROL"]
    # An operator order without shares or price still routes (AUR-I-04 is W2B-5).
    operator = {k: v for k, v in _decision(notional=500_000.0).items() if k not in ("shares", "price")}
    assert routed_required_approvals(operator) == ["TRADER", "RISK"]


def test_resolution_applies_routing_even_if_creation_did_not() -> None:
    state = _state(_decision(shares=4_000, notional=400_000.0), portfolio_value=10_000_000.0,
                   cash=5_000_000.0)
    assert _evaluate(state)["disposition"] == "PASS"
    result = _resolve(state, role="TRADER")
    assert result["status"] == "pending"
    assert state["pending_decisions"][0]["required_approvals"] == ["TRADER", "RISK"]
    assert state["cash"] == 5_000_000.0


# ── Server: API path, fallback parity, persistence, no other approval path ──────


@pytest.fixture
def server_client(monkeypatch):  # type: ignore[no-untyped-def]
    import server

    monkeypatch.setenv("AUREON_ADMIN_KEY", "binding-test-key-0123456789")
    monkeypatch.setattr(server._session_protocol, "is_session_open", lambda: True)
    monkeypatch.setattr(server, "_is_instrument_tradeable", lambda *_a: (True, "open"))
    monkeypatch.setattr(server, "_market_is_open", lambda: True)
    monkeypatch.setattr(server, "_get_fred_macro_snapshot", dict)
    monkeypatch.setattr(server, "_send_trade_confirmation_email", lambda *_a: None)
    monkeypatch.setattr(server, "_save_state", lambda: None)
    monkeypatch.setitem(server._ofr_cache, "data", dict(GOOD_OFR))
    with server._lock:
        saved = {k: copy.deepcopy(server.aureon_state.get(k)) for k in
                 ("pending_decisions", "positions", "cash", "portfolio_value", "drawdown",
                  "prices", "trades", "halt_active")}
        server.aureon_state.update({
            "pending_decisions": [], "positions": [], "cash": 50_000.0,
            "portfolio_value": 100_000.0, "drawdown": 1.0, "prices": {"TEST": 100.0},
            "trades": [], "halt_active": False,
        })
    yield server, server.app.test_client()
    with server._lock:
        server.aureon_state.update(saved)


def _headers():
    return {"X-Admin-Key": "binding-test-key-0123456789", "X-Request-Nonce": uuid.uuid4().hex}


def _add(server, decision):
    with server._lock:
        server.aureon_state["pending_decisions"].append(decision)


def test_api_refuses_a_failed_gate_before_any_change(server_client) -> None:
    server, client = server_client
    _add(server, _decision(id="DEC-API-FAIL"))
    server.aureon_state["drawdown"] = 9.0
    assert client.get("/api/decisions/DEC-API-FAIL/pretrade").get_json()["disposition"] == "BLOCK"
    cash, trades = server.aureon_state["cash"], list(server.aureon_state["trades"])
    response = client.post("/api/decisions/DEC-API-FAIL", headers=_headers(),
                           json={"resolution": "APPROVED", "approval_role": "TRADER"})
    assert response.status_code == 409
    assert response.get_json()["code"] == "POLICY_BLOCK"
    assert server.aureon_state["cash"] == cash
    assert server.aureon_state["trades"] == trades
    assert any(d["id"] == "DEC-API-FAIL" for d in server.aureon_state["pending_decisions"])


def test_api_refuses_without_a_pretrade_check(server_client) -> None:
    server, client = server_client
    _add(server, _decision(id="DEC-API-NOCHECK"))
    response = client.post("/api/decisions/DEC-API-NOCHECK", headers=_headers(),
                           json={"resolution": "APPROVED"})
    assert response.status_code == 409
    assert response.get_json()["code"] == "NO_POLICY_EVIDENCE"


def test_api_refuses_a_deferred_approval_too(server_client, monkeypatch) -> None:
    server, client = server_client
    monkeypatch.setattr(server, "_is_instrument_tradeable", lambda *_a: (False, "market closed"))
    _add(server, _decision(id="DEC-API-DEFER"))
    server.aureon_state["drawdown"] = 9.0
    client.get("/api/decisions/DEC-API-DEFER/pretrade")
    response = client.post("/api/decisions/DEC-API-DEFER", headers=_headers(),
                           json={"resolution": "APPROVED"})
    assert response.status_code == 409
    decision = next(d for d in server.aureon_state["pending_decisions"] if d["id"] == "DEC-API-DEFER")
    assert decision.get("status") != "APPROVED_PENDING_SESSION"


def test_api_approves_a_current_pass(server_client) -> None:
    server, client = server_client
    _add(server, _decision(id="DEC-API-PASS"))
    assert client.get("/api/decisions/DEC-API-PASS/pretrade").get_json()["disposition"] == "PASS"
    response = client.post("/api/decisions/DEC-API-PASS", headers=_headers(),
                           json={"resolution": "APPROVED"})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["status"] == "ok"
    journal = server.aureon_state["decision_journal"][0]
    assert journal["decision_id"] == "DEC-API-PASS"
    assert journal["policy_record_id"].startswith("PEV-")
    assert journal["pretrade_gates"], "the journal records the gates that bound the approval"


def test_api_hold_exception_by_compliance(server_client, monkeypatch) -> None:
    server, client = server_client
    monkeypatch.setattr(server._agent_j, "asset_class_gates", lambda _d: [dict(MIFIR_HOLD)])
    _add(server, _decision(id="DEC-API-HOLD"))
    assert client.get("/api/decisions/DEC-API-HOLD/pretrade").get_json()["disposition"] == "HOLD"
    refused = client.post("/api/decisions/DEC-API-HOLD", headers=_headers(),
                          json={"resolution": "APPROVED", "approval_role": "TRADER"})
    assert refused.get_json()["code"] == "HOLD_EXCEPTION_REQUIRED"
    wrong_role = client.post("/api/decisions/DEC-API-HOLD", headers=_headers(), json={
        "resolution": "APPROVED", "approval_role": "TRADER",
        "hold_exception": {"reason": "published", "ttl_seconds": 600}})
    assert wrong_role.get_json()["code"] == "HOLD_EXCEPTION_AUTHORITY"
    granted = client.post("/api/decisions/DEC-API-HOLD", headers=_headers(), json={
        "resolution": "APPROVED", "approval_role": "COMPLIANCE",
        "hold_exception": {"reason": "Published on the APA", "ttl_seconds": 600}})
    assert granted.status_code == 200, granted.get_json()
    exception = server.aureon_state["policy_hold_exceptions"][0]
    assert exception["authority"]["actor_kind"] == "HUMAN"
    assert exception["authority_role"] == "COMPLIANCE"
    approved = client.post("/api/decisions/DEC-API-HOLD", headers=_headers(),
                           json={"resolution": "APPROVED", "approval_role": "TRADER"})
    assert approved.get_json()["status"] == "ok"


def test_api_create_routes_material_orders_to_risk(server_client) -> None:
    server, client = server_client
    response = client.post("/api/decisions/create", headers=_headers(), json={
        "symbol": "TEST", "action": "BUY", "asset_class": "equities", "notional": 500_000})
    decision_id = response.get_json()["decision_id"]
    decision = next(d for d in server.aureon_state["pending_decisions"] if d["id"] == decision_id)
    assert decision["required_approvals"] == ["TRADER", "RISK"]


def test_timeout_fallback_returns_the_primary_result(server_client, monkeypatch) -> None:
    import concurrent.futures

    server, client = server_client
    _add(server, _decision(id="DEC-API-FALLBACK", shares=100, notional=10_000.0))
    server.aureon_state["positions"] = [
        {"symbol": "TEST", "shares": 300, "cost": 100.0, "asset_class": "equities"}]
    primary = client.get("/api/decisions/DEC-API-FALLBACK/pretrade").get_json()

    class TimedOut:
        def __init__(self, *a, **k): pass
        def submit(self, *a, **k):
            class F:
                def result(self, timeout=None):
                    raise concurrent.futures.TimeoutError
            return F()
        def shutdown(self, wait=True): pass

    monkeypatch.setattr(server, "ThreadPoolExecutor", TimedOut)
    fallback = client.get("/api/decisions/DEC-API-FALLBACK/pretrade").get_json()
    assert "timed out" in fallback["message"]
    strip = lambda p: [(g["gate"], g["status"], g["disposition"], g["detail"]) for g in p["gates"]]
    assert strip(fallback) == strip(primary)
    assert fallback["disposition"] == primary["disposition"] == "BLOCK"
    assert not hasattr(server, "_build_pretrade_checks_from_cache")


def test_policy_evidence_is_persisted(tmp_path) -> None:
    from aureon.persistence.store import save_state

    state = _state()
    _evaluate(state, extra_gates=[MIFIR_HOLD])
    record = latest_policy_record(state, "DEC-BIND-1")
    binding.persist_hold_exception(state, grant_hold_exception(
        record=record, actor=OPERATOR_ACTOR, authority_role="COMPLIANCE", reason="attested",
        ttl_seconds=60, now=T0))
    path = tmp_path / "state.json"
    save_state(state=state, lock=threading.RLock(), state_file=str(path),
               resolve_mmf_provider=lambda p: p, log_error=lambda *a: None)
    saved = json.loads(path.read_text())
    assert saved["policy_evaluations"] == state["policy_evaluations"]
    assert saved["policy_hold_exceptions"] == state["policy_hold_exceptions"]


def test_every_approval_goes_through_the_bound_service() -> None:
    root = pathlib.Path(__file__).parent
    sources = [p for p in root.rglob("*.py")
               if "__pycache__" not in p.parts and not p.name.startswith("test_")
               and ".venv" not in p.parts and "venv" not in p.parts]
    apply_trade_callers = {p.relative_to(root).as_posix() for p in sources
                           if "_apply_trade(" in p.read_text(encoding="utf-8", errors="ignore")}
    assert apply_trade_callers == {"aureon/approval_service/service.py"}
    for surface in ("aureon/cli", "aureon/mcp"):
        for p in (root / surface).rglob("*.py"):
            text = p.read_text(encoding="utf-8", errors="ignore")
            assert "resolve_pending_decision" not in text and "pending_decisions" not in text, (
                f"{p}: a CLI or MCP approval path must call resolve_pending_decision with the "
                "rules digest; add it to this test when one is built"
            )
