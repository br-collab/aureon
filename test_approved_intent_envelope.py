"""W2B-5: the ApprovedIntentEnvelope (AUR-I-04, AUR-I-07, AUR-I-11; AUR-I-05 partial).

Aureon inventory §14 criteria covered:

- Operator and UI requests normalize to the same valid schema (one quantity
  model: quantity + unit, or notional + currency, per asset class).
- Content integrity: changing any economic term, policy result or authority
  record changes the envelope digest; a tampered envelope does not verify.
- Actor authority: an approval without an authenticated actor is refused
  before any state change.
- Release carries complete evidence references unchanged: the OMS and EMS
  packets carry the envelope and its digest.
- One sealing path: the same request through the dashboard, the API, the CLI
  and the MCP tool yields the same envelope digest under a fixed clock.

Run: pytest -q test_approved_intent_envelope.py
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("RAILWAY_VOLUME_MOUNT_PATH", tempfile.mkdtemp(prefix="aureon-envelope-test-"))

from cannae_kernel.actor import ActorKind, ActorRef  # noqa: E402

from aureon.approval_service.operator_auth import OPERATOR_ACTOR  # noqa: E402
from aureon.approval_service.service import AuthorityError, resolve_pending_decision  # noqa: E402
from aureon.contracts.approved_intent import (  # noqa: E402
    ApprovedIntentEnvelope,
    IntentShapeError,
    normalize_quantity,
    verify_envelope,
)
from aureon.policy_engine.binding import pretrade_rules_digest  # noqa: E402
from aureon.policy_engine.service import evaluate_pretrade_decision  # noqa: E402

RISK = {"drawdown_warn_pct": 5.0, "drawdown_fail_pct": 8.0}
RULES = pretrade_rules_digest(risk_policy=RISK, operating_cash_floor_pct=0.03, ofac_blocked_isins={})
T0 = datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc)


# ── One quantity model (AUR-I-04) ───────────────────────────────────────────────


def test_quantity_or_notional_normalizes_per_asset_class() -> None:
    shares = normalize_quantity("equities", quantity="10", estimated_notional=1000.0)
    assert (shares.basis, shares.quantity, shares.quantity_unit, shares.notional) == \
        ("QUANTITY", "10", "SHARES", "1000")
    notional = normalize_quantity("equities", notional=5000, currency="usd")
    assert (notional.basis, notional.notional, notional.currency, notional.quantity) == \
        ("NOTIONAL", "5000", "USD", None)
    crypto = normalize_quantity("crypto", quantity="0.25")
    assert (crypto.quantity, crypto.quantity_unit, crypto.whole_units) == ("0.25", "UNITS", False)
    bond = normalize_quantity("fixed_income", quantity=100000, quantity_unit="face")
    assert bond.quantity_unit == "FACE"
    assert normalize_quantity("fx", notional="250000", currency="EUR").currency == "EUR"


@pytest.mark.parametrize(("asset_class", "kwargs", "message"), [
    ("equities", {"quantity": "10", "notional": 1000}, "either"),
    ("equities", {}, "either"),
    ("equities", {"quantity": "10.5"}, "whole"),
    ("equities", {"quantity": "-1"}, "positive"),
    ("equities", {"quantity": "abc"}, "positive"),
    ("equities", {"quantity": "10", "quantity_unit": "TOKENS"}, "unit"),
    ("equities", {"notional": 1000, "currency": "DOLLARS"}, "ISO 4217"),
    ("fx", {"quantity": "5"}, "notional"),
    ("options", {"quantity": "1"}, "not in the quantity model"),
])
def test_invalid_instructions_are_refused(asset_class, kwargs, message) -> None:
    with pytest.raises(IntentShapeError, match=message):
        normalize_quantity(asset_class, **kwargs)


# ── Sealing ─────────────────────────────────────────────────────────────────────


def _state(**overrides):
    decision = {"id": "DEC-ENV-1", "symbol": "TEST", "action": "BUY", "asset_class": "equities",
                "shares": 10, "price": 100.0, "notional": 1_000.0, "signal_type": "REBALANCE",
                "rationale": "drift", "required_approvals": ["TRADER"], "current_approvals": []}
    decision.update(overrides)
    return {"portfolio_value": 100_000.0, "cash": 50_000.0, "drawdown": 1.0, "positions": [],
            "trades": [], "authority_log": [], "prices": {"TEST": 100.0},
            "pending_decisions": [decision]}


def _approve(state, *, role="TRADER", actor=OPERATOR_ACTOR, at=T0 + timedelta(seconds=10)):
    lock = threading.RLock()
    if not any(r.get("decision_id") == state["pending_decisions"][0]["id"]
               for r in state.get("policy_evaluations", [])):
        evaluate_pretrade_decision(
            state=state, lock=lock, decision_id=state["pending_decisions"][0]["id"],
            market_is_open=lambda: True, macro_snapshot_fn=dict,
            ofr_snapshot_fn=lambda _m: {"fsi_value": 0.1, "source": "test"},
            operating_cash_floor_pct=0.03, risk_policy=RISK, symbol_to_isin={},
            ofac_blocked_isins={}, now=T0,
        )
    return resolve_pending_decision(
        state=state, lock=lock, decision_id=state["pending_decisions"][0]["id"],
        resolution="APPROVED", approval_role=role, actor=actor, rules_digest=RULES, now=at,
    )


def test_approval_seals_a_verifiable_envelope() -> None:
    state = _state()
    result = _approve(state)
    envelope = result["envelope"]
    verify_envelope(envelope, now=T0 + timedelta(seconds=20))
    assert str(envelope.envelope_id).startswith("int_")
    assert str(envelope.lifecycle_id).startswith("lif_")
    assert envelope.intent.quantity.basis == "QUANTITY"
    assert envelope.policy_manifest.disposition.value == "PASS"
    assert envelope.policy_manifest.policy_record_id == state["policy_evaluations"][0]["record_id"]
    assert envelope.authority_manifest.approvals[0].actor == OPERATOR_ACTOR
    assert envelope.authority_manifest.quorum_met is True
    assert envelope.downstream_permissions.settlement_submit is False
    assert envelope.downstream_permissions.idempotency_key == result["release"].release_id
    kinds = {ref.kind for ref in envelope.evidence_manifest.refs}
    assert {"POLICY_EVALUATION", "AUTHORITY_APPROVAL"} <= kinds
    stored = ApprovedIntentEnvelope.model_validate_json(json.dumps(state["approved_intents"][0]))
    assert stored == envelope
    assert result["release"].envelope_digest == envelope.digest


def test_a_tampered_or_expired_envelope_does_not_verify() -> None:
    envelope = _approve(_state())["envelope"]
    tampered = envelope.model_copy(update={"intent": envelope.intent.model_copy(
        update={"quantity": envelope.intent.quantity.model_copy(update={"quantity": "1000"})})})
    with pytest.raises(IntentShapeError, match="digest"):
        verify_envelope(tampered, now=T0 + timedelta(seconds=20))
    with pytest.raises(IntentShapeError, match="expired"):
        verify_envelope(envelope, now=envelope.expires_at)


@pytest.mark.parametrize("change", [
    {"shares": 11, "notional": 1_100.0},
    {"action": "SELL"},
    {"symbol": "OTHER"},
    {"price": 101.0},
])
def test_changing_a_term_changes_the_digest(change) -> None:
    base = _approve(_state())["envelope"]
    state = _state(**change)
    state["prices"]["OTHER"] = 100.0
    state["positions"] = [{"symbol": change.get("symbol", "TEST"), "shares": 100, "cost": 100.0}]
    other = _approve(state)["envelope"]
    assert other.digest != base.digest


def test_an_unauthenticated_actor_is_refused_before_any_change() -> None:
    state = _state()
    # Evaluate first, so the refusal is about the actor and not missing evidence.
    evaluate_pretrade_decision(
        state=state, lock=threading.RLock(), decision_id="DEC-ENV-1",
        market_is_open=lambda: True, macro_snapshot_fn=dict,
        ofr_snapshot_fn=lambda _m: {"fsi_value": 0.1, "source": "test"},
        operating_cash_floor_pct=0.03, risk_policy=RISK, symbol_to_isin={},
        ofac_blocked_isins={}, now=T0,
    )
    before = copy.deepcopy(state)
    anonymous = ActorRef(actor_id=OPERATOR_ACTOR.actor_id, actor_kind=ActorKind.HUMAN,
                         role="unknown", entitlement_refs=(), authenticated=False)
    for actor in (None, anonymous):
        with pytest.raises(AuthorityError):
            _approve(state, actor=actor)
    assert state == before


def test_the_envelope_is_sealed_only_when_every_required_role_approved() -> None:
    state = _state(required_approvals=["TRADER", "RISK"])
    first = _approve(state, role="RISK", at=T0 + timedelta(seconds=5))
    assert first["status"] == "pending" and first["envelope"] is None
    assert "approved_intents" not in state
    second = _approve(state, role="TRADER", at=T0 + timedelta(seconds=9))
    envelope = second["envelope"]
    assert [a.role for a in envelope.authority_manifest.approvals] == ["RISK", "TRADER"]
    assert envelope.authority_manifest.required_roles == ("TRADER", "RISK")


def test_notional_orders_seal_with_the_notional_basis() -> None:
    state = _state(shares=None, price=None, notional=5_000.0, quantity_basis="NOTIONAL",
                   currency="USD")
    envelope = _approve(state)["envelope"]
    assert envelope.intent.quantity.model_dump() == {
        "basis": "NOTIONAL", "quantity": None, "quantity_unit": None, "whole_units": True,
        "notional": "5000", "currency": "USD"}
    assert envelope.intent.reference_price is None


# ── Server: release packets and channel parity ──────────────────────────────────

KEY = "envelope-test-key-0123456789"
FIXED = datetime(2026, 9, 17, 15, 30, tzinfo=timezone.utc)


@pytest.fixture
def server_client(monkeypatch):  # type: ignore[no-untyped-def]
    import server

    monkeypatch.setenv("AUREON_ADMIN_KEY", KEY)
    monkeypatch.setattr(server._session_protocol, "is_session_open", lambda: True)
    monkeypatch.setattr(server, "_is_instrument_tradeable", lambda *_a: (True, "open"))
    monkeypatch.setattr(server, "_market_is_open", lambda: True)
    monkeypatch.setattr(server, "_get_fred_macro_snapshot", dict)
    monkeypatch.setattr(server, "_send_trade_confirmation_email", lambda *_a: None)
    monkeypatch.setattr(server, "_save_state", lambda: None)
    monkeypatch.setattr(server, "_approval_clock", lambda: FIXED)
    monkeypatch.setitem(server._ofr_cache, "data", {"fsi_value": 0.2, "source": "test"})
    # Boot calls init_mcp; the test client has not booted.
    server.init_mcp(server.aureon_state, server._lock, server.OFAC_BLOCKED_ISINS,
                    resolve_decision=server._mcp_resolve_decision)
    keys = ("pending_decisions", "positions", "cash", "portfolio_value", "drawdown", "prices",
            "prices_observed_at", "trades", "halt_active", "release_events", "venue_fills",
            "booked_fill_ids", "booking_breaks", "approved_intents", "policy_evaluations",
            "integration_handoffs")
    with server._lock:
        saved = {k: copy.deepcopy(server.aureon_state[k]) for k in keys if k in server.aureon_state}
    yield server, server.app.test_client(), keys
    with server._lock:
        for k in keys:
            server.aureon_state.pop(k, None)
        server.aureon_state.update(saved)


def _reset(server, keys, decision_overrides=None):
    decision = {"id": "DEC-PARITY", "symbol": "TEST", "action": "BUY", "asset_class": "equities",
                "shares": 10, "price": 100.0, "notional": 1_000.0, "signal_type": "OPERATOR_ORDER",
                "rationale": "parity", "required_approvals": ["TRADER"], "current_approvals": [],
                "release_target": "OMS"}
    decision.update(decision_overrides or {})
    with server._lock:
        for k in keys:
            server.aureon_state.pop(k, None)
        server.aureon_state.update({
            "pending_decisions": [decision], "positions": [], "cash": 50_000.0,
            "portfolio_value": 100_000.0, "drawdown": 1.0, "prices": {"TEST": 100.0},
            "prices_observed_at": datetime.now(timezone.utc).isoformat(), "trades": [],
            "halt_active": False,
        })


def _headers():
    return {"X-Admin-Key": KEY, "X-Request-Nonce": uuid.uuid4().hex}


def test_release_packets_carry_the_envelope_unchanged(server_client, monkeypatch) -> None:
    server, client, keys = server_client
    sent = []
    monkeypatch.setattr(server, "oms_send", lambda packet: sent.append(copy.deepcopy(packet)) or
                        {"oms_status": "ACCEPTED"})
    for target in ("OMS", "EMS"):
        _reset(server, keys, {"release_target": target})
        client.get("/api/decisions/DEC-PARITY/pretrade")
        body = client.post("/api/decisions/DEC-PARITY", headers=_headers(),
                           json={"resolution": "APPROVED"}).get_json()
        assert body["status"] == "ok", body
        stored = server.aureon_state["approved_intents"][0]
        packet = server.aureon_state["integration_handoffs"][0]
        assert packet["approved_intent"] == stored
        assert packet["approved_intent_digest"] == stored["digest"] == body["envelope_digest"]
    assert sent and sent[0]["approved_intent"]["digest"] == sent[0]["approved_intent_digest"]


def _via_dashboard(server, client):
    return client.post("/api/decisions/DEC-PARITY", headers={**_headers(), "Content-Type": "application/json"},
                       data=json.dumps({"resolution": "APPROVED", "approval_role": "TRADER"})).get_json()


def _via_api(server, client):
    return client.post("/api/decisions/DEC-PARITY", headers=_headers(),
                       json={"resolution": "approved"}).get_json()


def _via_cli(server, client):
    from aureon.cli.main import resolve_decision

    def transport(url, data, headers):
        path = url.split("://", 1)[-1].split("/", 1)[1]
        response = client.post("/" + path, data=data, headers=headers)
        return response.status_code, response.get_json()

    status, payload = resolve_decision("DEC-PARITY", "APPROVED", role="TRADER", admin_key=KEY,
                                       transport=transport)
    return payload


def _via_mcp(server, client):
    response = client.post("/mcp", headers=_headers(), json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "aureon_resolve_decision",
                   "arguments": {"decision_id": "DEC-PARITY", "resolution": "APPROVED",
                                 "approval_role": "TRADER"}}})
    return response.get_json()["result"]


def test_every_channel_seals_the_same_envelope(server_client) -> None:
    server, client, keys = server_client
    digests = {}
    for name, channel in (("dashboard", _via_dashboard), ("api", _via_api), ("cli", _via_cli),
                          ("mcp", _via_mcp)):
        _reset(server, keys)
        assert client.get("/api/decisions/DEC-PARITY/pretrade").get_json()["disposition"] == "PASS"
        payload = channel(server, client)
        assert payload["status"] == "ok", (name, payload)
        digests[name] = payload["envelope_digest"]
        assert server.aureon_state["approved_intents"][0]["digest"] == payload["envelope_digest"]
    assert len(set(digests.values())) == 1, digests


def test_mcp_approval_requires_the_operator_key(server_client) -> None:
    server, client, keys = server_client
    _reset(server, keys)
    client.get("/api/decisions/DEC-PARITY/pretrade")
    before = copy.deepcopy(server.aureon_state["pending_decisions"])
    response = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "aureon_resolve_decision",
                   "arguments": {"decision_id": "DEC-PARITY", "resolution": "APPROVED"}}})
    result = response.get_json()["result"]
    assert result["http_status"] == 401
    assert server.aureon_state["pending_decisions"] == before
    assert "approved_intents" not in server.aureon_state


def test_cli_without_a_key_does_not_call_the_server() -> None:
    from aureon.cli.main import resolve_decision

    calls = []
    status, _payload = resolve_decision("DEC-X", "APPROVED", admin_key="",
                                        transport=lambda *a: calls.append(a) or (200, {}))
    assert status == 401 and calls == []


@pytest.mark.parametrize(("body", "expected"), [
    ({"notional": 5000}, {"quantity_basis": "NOTIONAL", "currency": "USD", "notional": 5000.0}),
    ({"quantity": 10, "price": 100}, {"quantity_basis": "QUANTITY", "quantity_unit": "SHARES",
                                      "shares": 10, "notional": 1000.0}),
])
def test_operator_orders_normalize_to_the_quantity_model(server_client, body, expected) -> None:
    server, client, keys = server_client
    _reset(server, keys)
    response = client.post("/api/decisions/create", headers=_headers(), json={
        "symbol": "TEST", "action": "BUY", "asset_class": "equities", **body})
    assert response.status_code == 200, response.get_json()
    decision_id = response.get_json()["decision_id"]
    decision = next(d for d in server.aureon_state["pending_decisions"] if d["id"] == decision_id)
    for key, value in expected.items():
        assert decision[key] == value, key


@pytest.mark.parametrize("body", [
    {"quantity": 10, "notional": 1000},
    {},
    {"quantity": 10.5, "price": 100},
    {"notional": 5000, "asset_class": "options"},
])
def test_invalid_operator_orders_are_refused(server_client, body) -> None:
    server, client, keys = server_client
    _reset(server, keys)
    response = client.post("/api/decisions/create", headers=_headers(), json={
        "symbol": "TEST", "action": "BUY", "asset_class": "equities", **body})
    assert response.status_code == 400
    assert len(server.aureon_state["pending_decisions"]) == 1


def test_an_operator_notional_order_executes_end_to_end(server_client) -> None:
    """AUR-I-04: the any-asset front door now reaches a booked fill."""
    server, client, keys = server_client
    _reset(server, keys)
    server.aureon_state["pending_decisions"] = []
    created = client.post("/api/decisions/create", headers=_headers(), json={
        "symbol": "TEST", "action": "BUY", "asset_class": "equities", "notional": 5_000}).get_json()
    decision_id = created["decision_id"]
    assert client.get(f"/api/decisions/{decision_id}/pretrade").get_json()["disposition"] == "PASS"
    body = client.post(f"/api/decisions/{decision_id}", headers=_headers(),
                       json={"resolution": "APPROVED"}).get_json()
    assert body["status"] == "ok", body
    assert body["execution"]["status"] == "BOOKED"
    assert body["execution"]["quantity"] == "50"
