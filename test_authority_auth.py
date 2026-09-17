"""AUR-I-03: every authority mutation is authenticated before any state change (W2B-2).

Before Wave 2 anyone who could reach the service could create and approve
decisions, open the session, propose and approve doctrine, resume paused
lifecycles and move MMF positions. The Aureon inventory §14 criterion: missing
or insufficient credentials fail before mutation.

Run: pytest -q test_authority_auth.py
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid

import pytest

os.environ.setdefault("RAILWAY_VOLUME_MOUNT_PATH", tempfile.mkdtemp(prefix="aureon-auth-test-"))

import server  # noqa: E402
from aureon.approval_service.operator_auth import (  # noqa: E402
    BOOT_SERVICE_ACTOR,
    OPERATOR_ACTOR,
    NonceCache,
    authenticate,
)

KEY = "test-operator-key-" + "x" * 16

#: (endpoint function, method, path, body). Bodies are realistic, so a route
#: that lost its guard would mutate state and the unchanged-state checks fail.
COVERED = [
    ("api_session_step1", "/api/session/step/1", {}),
    ("api_session_step2", "/api/session/step/2", {}),
    ("api_session_step3", "/api/session/step/3", {"acknowledged_tiers": [1, 2, 3]}),
    ("api_session_open", "/api/session/open", {}),
    ("api_create_decision", "/api/decisions/create",
     {"symbol": "SPY", "action": "BUY", "notional": 1000, "asset_class": "equity"}),
    ("api_resolve_decision", "/api/decisions/DEC-DOES-NOT-EXIST",
     {"resolution": "APPROVED", "approval_role": "TRADER"}),
    ("api_doctrine_propose", "/api/doctrine/propose",
     {"title": "t", "trigger": "t", "urgency": "LOW", "reason": "r", "frameworks": []}),
    ("api_doctrine_approve", "/api/doctrine/approve/DU-1", {"action": "APPROVE"}),
    ("api_c2_resume", "/api/c2/resume/TSK-1", {}),
    ("api_mmf_hitl_resolve", "/api/mmf/hitl/resolve", {}),
    ("api_mmf_subscribe", "/api/mmf/subscribe", {"amount": "100"}),
    ("api_mmf_redeem", "/api/mmf/redeem", {"amount": "100"}),
    ("api_mmf_register_investor", "/api/mmf/digital/register_investor", {}),
    ("api_mmf_test_cato_override", "/api/mmf/_test/cato_override", {"decision": "PROCEED"}),
    ("api_mmf_sweep_trigger", "/api/mmf/sweep/trigger", {}),
    ("api_mmf_circuit_reset", "/api/mmf/circuit/reset", {"reason": "x"}),
    ("api_atrox_promote", "/api/atrox/recommendations/REC-1/promote", {}),
    ("api_atrox_dismiss", "/api/atrox/recommendations/REC-1/dismiss", {}),
    ("api_c2_algo_inventory_check", "/api/c2/algo-inventory-check", {"active_algorithms": []}),
    ("cockpit_capture", "/api/cockpit/capture", {"rail": "ficc_gsd_dvp"}),
    ("cockpit_validate", "/api/cockpit/validate", {"operation_id": str(uuid.uuid4())}),
    ("cockpit_prepare", "/api/cockpit/prepare", {"operation_id": str(uuid.uuid4())}),
    ("cockpit_readback", "/api/cockpit/readback", {"operation_id": str(uuid.uuid4())}),
    ("cockpit_reconcile", "/api/cockpit/reconcile", {"operation_id": str(uuid.uuid4())}),
    ("cockpit_break", "/api/cockpit/break", {"operation_id": str(uuid.uuid4())}),
]

#: POST routes reviewed and deliberately left without the operator key, with why.
REVIEWED_UNGUARDED = {
    # Already gated inline by the same key before Wave 2.
    "api_halt_activate", "api_halt_resume", "api_admin_reset_state",
    "thifur_h_start_session", "thifur_h_generate_signal", "thifur_h_approve_signal",
    "thifur_h_rollback", "thifur_h_auto_close_arm",
    # Reduce exposure by design: stopping must never wait for a key.
    "thifur_h_kill_switch", "thifur_h_auto_close_disarm",
    # Advisory analysis, pure computations or data-pipe reads: no authority,
    # position or doctrine change.
    "api_thesis_analyze", "api_thesis_register", "api_thesis_upload",
    "api_cato_compare_rails", "api_aml_screen", "api_surveillance_screen",
    "api_atrox_packet", "api_tradier_stress_packet", "api_alpaca_packet",
    "api_edgar_institutional_packet", "api_atrox_scan", "api_blockscout_onchain_packet",
    "cashleg_funding", "cashleg_gate", "cashleg_instruction",
    # Sends a test email; no state change. Listed in the W2B report as an abuse risk.
    "api_email_test", "api_test_email",
}


def _state() -> str:
    return json.dumps(server.aureon_state, default=str, sort_keys=True)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AUREON_ADMIN_KEY", KEY)
    server.app.config["TESTING"] = True
    return server.app.test_client()


def _nonce() -> str:
    return uuid.uuid4().hex


@pytest.mark.parametrize(("endpoint", "path", "body"), COVERED, ids=[c[0] for c in COVERED])
@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({}, 401),
        ({"X-Admin-Key": "wrong-key"}, 403),
        ({"X-Admin-Key": ""}, 401),
    ],
    ids=["missing-key", "wrong-key", "empty-key"],
)
def test_refused_before_any_state_change(client, endpoint, path, body, headers, expected) -> None:  # type: ignore[no-untyped-def]
    before = _state()
    response = client.post(path, json=body, headers={**headers, "X-Request-Nonce": _nonce()})
    assert response.status_code == expected
    assert response.get_json()["action"]
    assert _state() == before


@pytest.mark.parametrize(("endpoint", "path", "body"), COVERED, ids=[c[0] for c in COVERED])
def test_refused_when_the_server_has_no_key(monkeypatch, endpoint, path, body) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("AUREON_ADMIN_KEY", raising=False)
    before = _state()
    response = server.app.test_client().post(
        path, json=body, headers={"X-Admin-Key": KEY, "X-Request-Nonce": _nonce()}
    )
    assert response.status_code == 403
    assert "fails closed" in response.get_json()["detail"]
    assert _state() == before


def test_missing_or_malformed_nonce_is_refused(client) -> None:  # type: ignore[no-untyped-def]
    before = _state()
    for headers in ({"X-Admin-Key": KEY}, {"X-Admin-Key": KEY, "X-Request-Nonce": "short"},
                    {"X-Admin-Key": KEY, "X-Request-Nonce": "has spaces in it ok?"}):
        assert client.post("/api/decisions/create", json={}, headers=headers).status_code == 401
    assert _state() == before


def test_a_replayed_request_is_refused(client) -> None:  # type: ignore[no-untyped-def]
    headers = {"X-Admin-Key": KEY, "X-Request-Nonce": _nonce()}
    first = client.post("/api/atrox/recommendations/REC-DOES-NOT-EXIST/dismiss", headers=headers)
    assert first.status_code == 404  # authenticated; the recommendation does not exist
    before = _state()
    replay = client.post("/api/atrox/recommendations/REC-DOES-NOT-EXIST/dismiss", headers=headers)
    assert replay.status_code == 403
    assert "replay" in replay.get_json()["detail"]
    assert _state() == before


def test_an_authenticated_request_is_recorded_as_the_human_operator(client) -> None:  # type: ignore[no-untyped-def]
    nonce = _nonce()
    response = client.post(
        "/api/atrox/recommendations/REC-DOES-NOT-EXIST/dismiss",
        headers={"X-Admin-Key": KEY, "X-Request-Nonce": nonce},
    )
    assert response.status_code == 404
    entry = next(e for e in server.aureon_state["authority_log"] if e.get("nonce") == nonce)
    assert entry["type"] == "AUTHENTICATED ATROX_DISMISS"
    assert entry["actor"]["actor_kind"] == "HUMAN"
    assert entry["actor"]["authenticated"] is True
    assert entry["actor"] == OPERATOR_ACTOR.model_dump(mode="json")


def test_every_covered_endpoint_is_guarded() -> None:
    assert {c[0] for c in COVERED} == server.AUTHORITY_ENDPOINTS
    for endpoint in server.AUTHORITY_ENDPOINTS:
        assert getattr(server.app.view_functions[endpoint], "__authority_action__", None)


def test_every_post_route_is_either_guarded_or_reviewed() -> None:
    post_endpoints = {
        rule.endpoint
        for rule in server.app.url_map.iter_rules()
        if "POST" in (rule.methods or set()) and rule.endpoint in server.app.view_functions
        and not rule.endpoint.startswith(("mcp.", "static"))
    }
    unclassified = post_endpoints - server.AUTHORITY_ENDPOINTS - REVIEWED_UNGUARDED
    assert unclassified == set(), (
        f"new POST routes must be guarded with _authority_required or reviewed: {unclassified}"
    )


def test_boot_session_auto_open_is_recorded_as_the_deterministic_service() -> None:
    server._record_boot_session_actor()
    entry = server.aureon_state["authority_log"][0]
    assert entry["id"] == "BOOT-SESSION-AUTO-OPEN"
    assert entry["actor"]["actor_kind"] == "DETERMINISTIC_SERVICE"
    assert entry["actor"] == BOOT_SERVICE_ACTOR.model_dump(mode="json")
    source = open(server.__file__, encoding="utf-8").read()
    boot = source[source.index("def _start_background_threads():"):]
    boot = boot[: boot.index("\ndef ", 10)]
    assert re.search(r"run_step_6_open_session\(\)\n\s+_record_boot_session_actor\(\)", boot)


# ---- operator_auth unit tests ------------------------------------------------------------------


def test_authenticate_unit_cases() -> None:
    cache = NonceCache(window_seconds=60)
    ok = authenticate({"X-Admin-Key": "k" * 20, "X-Request-Nonce": "n" * 20},
                      admin_key="k" * 20, nonces=cache, now=0.0)
    assert ok.ok and ok.actor == OPERATOR_ACTOR
    assert authenticate({}, admin_key=None, nonces=cache, now=0.0).status == 403
    again = authenticate({"X-Admin-Key": "k" * 20, "X-Request-Nonce": "n" * 20},
                         admin_key="k" * 20, nonces=cache, now=30.0)
    assert again.status == 403
    later = authenticate({"X-Admin-Key": "k" * 20, "X-Request-Nonce": "n" * 20},
                         admin_key="k" * 20, nonces=cache, now=61.0)
    assert later.ok, "a nonce may be reused only after the replay window"


def test_nonce_cache_refuses_a_flood_rather_than_forgetting_early() -> None:
    cache = NonceCache(window_seconds=60, max_entries=2)
    assert cache.first_use("a" * 16, 0.0)
    assert cache.first_use("b" * 16, 0.0)
    assert not cache.first_use("c" * 16, 1.0)
    assert cache.first_use("c" * 16, 61.0)
