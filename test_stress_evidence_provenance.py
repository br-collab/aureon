"""W2B-3 fix F1 (AUR-I-10): a fabricated stress reading is not evidence.

The defect, open in TRACKERS.md since 14 September: when the OFR (Office of
Financial Research) page cannot be scraped, the proxy is computed from the FRED
(Federal Reserve Economic Data) macro snapshot. When FRED is also unreachable,
that snapshot is fixed constants (VIX 24.0, high-yield option-adjusted spread
4.25, curve -20), and the proxy returns a measured-looking 0.38 with
source="ofr_proxy". Gate 6 read it as PASS, and `ofr_fsi_at_exec` stored it as
a number in the compliance artifact.

Provenance now decides:

- official reading → evaluated as before;
- proxy over live FRED series → evaluated, labelled, and HOLD at or above the
  warning threshold;
- any fixed constant in the chain → INDETERMINATE, so approval is refused
  through every path, and audit fields record no number.

Run: pytest -q test_stress_evidence_provenance.py
"""

from __future__ import annotations

import copy
import os
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("RAILWAY_VOLUME_MOUNT_PATH", tempfile.mkdtemp(prefix="aureon-f1-test-"))

from aureon.policy_engine.binding import PolicyBindingError, pretrade_rules_digest  # noqa: E402
from aureon.policy_engine.evidence import EvidenceProvenance, provenance_of  # noqa: E402
from aureon.policy_engine.service import evaluate_pretrade_decision  # noqa: E402

RISK = {"drawdown_warn_pct": 5.0, "drawdown_fail_pct": 8.0}
RULES = pretrade_rules_digest(risk_policy=RISK, operating_cash_floor_pct=0.03, ofac_blocked_isins={})
T0 = datetime(2026, 9, 17, 17, 0, tzinfo=timezone.utc)

OFFICIAL = {"source": "ofr", "provenance": "FACT_EXTERNAL", "fsi_value": 0.2, "fsi_band": "watch"}


def _state():
    return {"portfolio_value": 100_000.0, "cash": 50_000.0, "drawdown": 1.0, "positions": [],
            "trades": [], "authority_log": [], "prices": {"TEST": 100.0},
            "pending_decisions": [{
                "id": "DEC-F1", "symbol": "TEST", "action": "BUY", "asset_class": "equities",
                "shares": 10, "price": 100.0, "notional": 1_000.0,
                "required_approvals": ["TRADER"], "current_approvals": []}]}


def _gate(state, ofr):
    payload = evaluate_pretrade_decision(
        state=state, lock=threading.RLock(), decision_id="DEC-F1", market_is_open=lambda: True,
        macro_snapshot_fn=dict, ofr_snapshot_fn=lambda _m: ofr, operating_cash_floor_pct=0.03,
        risk_policy=RISK, symbol_to_isin={}, ofac_blocked_isins={}, now=T0,
    )
    macro = next(g for g in payload["gates"] if g["gate"] == "MACRO_STRESS_OVERLAY")
    return payload, macro


# ── The snapshots label themselves ──────────────────────────────────────────────


def test_the_fred_fallback_is_labelled_fabricated() -> None:
    import server

    snapshot = server._fallback_macro_snapshot()
    assert provenance_of(snapshot) is EvidenceProvenance.FABRICATED_DEFAULT
    assert "fixed constants" in snapshot["fabricated_reason"]


def test_the_proxy_is_a_computation_over_live_inputs_or_nothing() -> None:
    import server

    live = {"source": "fred", "provenance": "FACT_EXTERNAL", "vix": 26.0, "hy_oas": 4.4,
            "curve_spread_bps": -40.0, "as_of": "2026-09-17"}
    from_live = server._fallback_ofr_snapshot(live)
    assert provenance_of(from_live) is EvidenceProvenance.POLICY_RESULT
    assert from_live["derived_from"] == "fred"
    assert "fabricated_reason" not in from_live

    from_constants = server._fallback_ofr_snapshot(server._fallback_macro_snapshot())
    assert provenance_of(from_constants) is EvidenceProvenance.FABRICATED_DEFAULT
    # The number the finding is about: it still looks measured.
    assert isinstance(from_constants["fsi_value"], float)
    assert "not a measurement" in from_constants["summary"]


# ── Gate 6 ──────────────────────────────────────────────────────────────────────


def test_fred_down_and_ofr_down_is_indeterminate() -> None:
    import server

    fabricated = server._fallback_ofr_snapshot(server._fallback_macro_snapshot())
    payload, macro = _gate(_state(), fabricated)
    assert macro["status"] == "INDETERMINATE"
    assert macro["disposition"] == "INDETERMINATE"
    assert macro["provenance"] == "FABRICATED_DEFAULT"
    assert payload["disposition"] == "INDETERMINATE"


def test_an_unlabelled_reading_is_indeterminate() -> None:
    _, macro = _gate(_state(), {"source": "ofr", "fsi_value": 0.2})
    assert macro["disposition"] == "INDETERMINATE"


def test_the_official_reading_is_evaluated_as_before() -> None:
    _, macro = _gate(_state(), OFFICIAL)
    assert (macro["status"], macro["disposition"]) == ("PASS", "PASS")
    assert "official reading 0.20" in macro["detail"]

    _, elevated = _gate(_state(), {**OFFICIAL, "fsi_value": 0.9})
    assert (elevated["status"], elevated["disposition"]) == ("WARN", "PASS")


def test_a_proxy_over_live_fred_is_labelled_and_holds_when_elevated() -> None:
    calm = {"source": "ofr_proxy", "provenance": "POLICY_RESULT", "fsi_value": 0.3}
    _, macro = _gate(_state(), calm)
    assert (macro["status"], macro["disposition"]) == ("PASS", "PASS")
    assert "source=ofr_proxy" in macro["detail"]

    stressed = {**calm, "fsi_value": 0.8}
    _, held = _gate(_state(), stressed)
    assert (held["status"], held["disposition"]) == ("HOLD", "HOLD")
    assert "source=ofr_proxy" in held["detail"]


def test_a_proxy_hold_is_not_overrideable() -> None:
    from aureon.policy_engine.binding import HOLD_OVERRIDE_POLICY

    assert "MACRO_STRESS_OVERLAY" not in HOLD_OVERRIDE_POLICY


# ── Approval is refused through every path ──────────────────────────────────────


def test_a_fabricated_reading_refuses_a_direct_approval() -> None:
    import server
    from aureon.approval_service.service import resolve_pending_decision

    state = _state()
    _gate(state, server._fallback_ofr_snapshot(server._fallback_macro_snapshot()))
    before = copy.deepcopy(state["pending_decisions"])
    with pytest.raises(PolicyBindingError) as info:
        resolve_pending_decision(
            state=state, lock=threading.RLock(), decision_id="DEC-F1", resolution="APPROVED",
            approval_role="TRADER", rules_digest=RULES, now=T0 + timedelta(seconds=10),
        )
    assert info.value.code == "POLICY_INDETERMINATE"
    assert state["pending_decisions"] == before
    assert state["trades"] == []


@pytest.fixture
def server_client(monkeypatch):  # type: ignore[no-untyped-def]
    import server

    monkeypatch.setenv("AUREON_ADMIN_KEY", "f1-test-key-0123456789")
    monkeypatch.setattr(server._session_protocol, "is_session_open", lambda: True)
    monkeypatch.setattr(server, "_is_instrument_tradeable", lambda *_a: (True, "open"))
    monkeypatch.setattr(server, "_market_is_open", lambda: True)
    monkeypatch.setattr(server, "_get_fred_macro_snapshot", server._fallback_macro_snapshot)
    monkeypatch.setattr(server, "_send_trade_confirmation_email", lambda *_a: None)
    monkeypatch.setattr(server, "_save_state", lambda: None)
    keys = ("pending_decisions", "positions", "cash", "portfolio_value", "drawdown", "prices",
            "trades", "halt_active", "policy_evaluations")
    with server._lock:
        saved = {k: copy.deepcopy(server.aureon_state[k]) for k in keys if k in server.aureon_state}
        server.aureon_state.update({
            "pending_decisions": [dict(_state()["pending_decisions"][0], id="DEC-F1-API")],
            "positions": [], "cash": 50_000.0, "portfolio_value": 100_000.0, "drawdown": 1.0,
            "prices": {"TEST": 100.0}, "trades": [], "halt_active": False,
        })
    yield server, server.app.test_client()
    with server._lock:
        for k in keys:
            server.aureon_state.pop(k, None)
        server.aureon_state.update(saved)


def _headers():
    return {"X-Admin-Key": "f1-test-key-0123456789", "X-Request-Nonce": uuid.uuid4().hex}


def test_the_api_refuses_when_both_feeds_are_down(server_client, monkeypatch) -> None:
    server, client = server_client
    fabricated = server._fallback_ofr_snapshot(server._fallback_macro_snapshot())
    monkeypatch.setitem(server._ofr_cache, "data", fabricated)
    payload = client.get("/api/decisions/DEC-F1-API/pretrade").get_json()
    assert payload["disposition"] == "INDETERMINATE"
    cash = server.aureon_state["cash"]
    response = client.post("/api/decisions/DEC-F1-API", headers=_headers(),
                           json={"resolution": "APPROVED"})
    assert response.status_code == 409
    assert response.get_json()["code"] == "POLICY_INDETERMINATE"
    assert server.aureon_state["cash"] == cash and server.aureon_state["trades"] == []


def test_the_api_works_when_the_ofr_feed_is_down_but_fred_is_live(server_client, monkeypatch) -> None:
    server, client = server_client
    live_macro = {"source": "fred", "provenance": "FACT_EXTERNAL", "vix": 19.0, "hy_oas": 3.6,
                  "curve_spread_bps": -20.0, "as_of": "2026-09-17", "macro_regime": "balanced"}
    monkeypatch.setattr(server, "_get_fred_macro_snapshot", lambda: live_macro)
    monkeypatch.setitem(server._ofr_cache, "data", server._fallback_ofr_snapshot(live_macro))
    payload = client.get("/api/decisions/DEC-F1-API/pretrade").get_json()
    assert payload["disposition"] == "PASS"
    macro = next(g for g in payload["gates"] if g["gate"] == "MACRO_STRESS_OVERLAY")
    assert macro["provenance"] == "POLICY_RESULT" and "source=ofr_proxy" in macro["detail"]
    assert client.post("/api/decisions/DEC-F1-API", headers=_headers(),
                       json={"resolution": "APPROVED"}).get_json()["status"] == "ok"


# ── Audit fields ────────────────────────────────────────────────────────────────


def test_the_audit_field_is_null_with_a_reason_when_the_reading_is_fabricated() -> None:
    import server
    from aureon.evidence_service.service import build_trade_report

    fabricated_macro = server._fallback_macro_snapshot()
    report = build_trade_report(
        decision={"id": "DEC-F1", "symbol": "TEST", "action": "BUY", "asset_class": "equities",
                  "shares": 10, "price": 100.0, "notional": 1_000.0},
        exec_price=100.0, authority_hash="HASH", gate_results=[],
        portfolio_before={"portfolio_value": 100_000.0, "cash": 50_000.0, "drawdown": 1.0,
                          "n_positions": 0},
        doctrine_version="test", instrument_ref={}, entity_lei="LEI",
        macro_snapshot_fn=lambda: fabricated_macro,
        ofr_snapshot_fn=server._fallback_ofr_snapshot,
    )
    assert report["ofr_fsi_at_exec"] is None
    assert report["ofr_band_at_exec"] is None
    assert report["macro_regime_at_exec"] is None
    assert report["systemic_overlay_provenance"] == "FABRICATED_DEFAULT"
    assert "fixed" in report["market_evidence_unavailable_reason"]


def test_the_audit_field_records_an_official_reading() -> None:
    from aureon.evidence_service.service import build_trade_report

    report = build_trade_report(
        decision={"id": "DEC-F1", "symbol": "TEST", "action": "BUY", "asset_class": "equities",
                  "shares": 10, "price": 100.0, "notional": 1_000.0},
        exec_price=100.0, authority_hash="HASH", gate_results=[],
        portfolio_before={"portfolio_value": 100_000.0, "cash": 50_000.0, "drawdown": 1.0,
                          "n_positions": 0},
        doctrine_version="test", instrument_ref={}, entity_lei="LEI",
        macro_snapshot_fn=lambda: {"source": "fred", "provenance": "FACT_EXTERNAL",
                                   "macro_regime": "balanced"},
        ofr_snapshot_fn=lambda _m: OFFICIAL,
    )
    assert report["ofr_fsi_at_exec"] == 0.2
    assert report["systemic_overlay_provenance"] == "FACT_EXTERNAL"
    assert "market_evidence_unavailable_reason" not in report


def test_cato_is_not_fed_a_fabricated_reading() -> None:
    """The settlement gate scores stress too; a constant must not reach it."""
    import pathlib
    import re

    source = pathlib.Path(__import__("server").__file__).read_text(encoding="utf-8")
    block = source[source.index("# OFR stress — read from the market_loop"):]
    block = block[: block.index("\n\n")]
    assert re.search(r"not _is_fabricated\(ofr_data\)", block)
