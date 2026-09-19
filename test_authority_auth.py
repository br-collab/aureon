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
    # Both send real mail through the operator's account; the first sends the
    # portfolio report itself. Gated after the W2B-2 sweep recommended it.
    ("api_email_test", "/api/email/test", {}),
    # W3 R4: durable writes this process does not own, and a cooldown bypass.
    ("api_thesis_register", "/api/thesis/register", {"memo": "m"}),
    ("api_thesis_upload", "/api/thesis/upload", {}),
    ("api_atrox_scan", "/api/atrox/recommendations/scan", {}),
    ("api_test_email", "/api/test/email", {}),
]

#: POST routes reviewed and deliberately left without the operator key.
#:
#: W3 § R4 re-read every entry against a different question. The W2B-2 sweep asked
#: "does this mutate application state"; R4 asks **"is anything irreversible outside
#: this process"** — sends, pays, submits, publishes, or writes to anything the
#: process does not own. That is the question #34 failed: two routes that send real
#: mail change no application state at all.
#:
#: Each entry is now classified rather than listed. `()` is a claim of containment.
#: `UNCONTAINED_ACCEPTED` below carries the ones that reach outside and are still
#: ungated, with the reason — so the exposure is stated, not hidden, and a new
#: uncontained route cannot join the list without a decision.
#:
#: The effect names mirror cannae_kernel.effects.ExternalEffect. They are spelled
#: locally because aureon pins the kernel by tag and v0.5.0 is not tagged yet;
#: swapping to the kernel type is a follow-up once it is.
SENDS = "SENDS"
WRITES_FOREIGN_STORE = "WRITES_FOREIGN_STORE"
CONSUMES_CREDENTIALED_QUOTA = "CONSUMES_CREDENTIALED_QUOTA"

REVIEWED_UNGUARDED_EFFECTS: dict[str, tuple[tuple[str, ...], str]] = {
    # --- Already gated inline by the same operator key before Wave 2 -------------
    "api_halt_activate":          ((), "gated inline by X-Admin-Key"),
    "api_halt_resume":            ((), "gated inline by X-Admin-Key"),
    "api_admin_reset_state":      ((), "gated inline by X-Admin-Key"),
    "thifur_h_start_session":     ((), "gated inline by X-Admin-Key"),
    "thifur_h_generate_signal":   ((), "gated inline by X-Admin-Key"),
    "thifur_h_approve_signal":    ((), "gated inline by X-Admin-Key"),
    "thifur_h_rollback":          ((), "gated inline by X-Admin-Key"),
    "thifur_h_auto_close_arm":    ((), "gated inline by X-Admin-Key"),

    # --- Reduce exposure by design: stopping must never wait for a key ----------
    "thifur_h_kill_switch":       ((), "stopping must not require a credential"),
    "thifur_h_auto_close_disarm": ((), "disarming must not require a credential"),

    # --- Contained: computed from the request and returned ----------------------
    "api_thesis_analyze":     ((), "parses the supplied memo and returns the analysis; registers nothing"),
    "api_aml_screen":         ((), "read-only screening of a supplied counterparty"),
    "api_surveillance_screen": ((), "read-only screening of a supplied record"),
    "api_cato_compare_rails": ((), "ranks rails from cached SOFR, OFR stress and prices; no outbound call"),
    "cashleg_funding":        ((), "intraday funding projection; pure computation"),
    "cashleg_gate":           ((), "CATO-F decision; deterministic and replayable"),
    "cashleg_instruction":    ((), "prepares an ISO 20022 artefact for the member to submit under their "
                                   "own credentials; is_submission is Literal[False] and no submit path exists"),
    "api_edgar_institutional_packet": ((), "served from the 60s background cache; the request body is ignored, "
                                           "so a caller drives no outbound traffic"),

    # --- Uncontained: they reach outside this process ---------------------------
    "api_alpaca_packet":   ((CONSUMES_CREDENTIALED_QUOTA,),
                            "calls Alpaca on ALPACA_API_KEY with a caller-supplied symbol list and bar_limit"),
    "api_tradier_stress_packet": ((CONSUMES_CREDENTIALED_QUOTA,),
                            "calls Tradier on our credentials with caller-supplied parameters"),
    "api_atrox_packet":    ((CONSUMES_CREDENTIALED_QUOTA,),
                            "calls the Atrox feed on our credentials with a caller-supplied symbol list"),
    "api_blockscout_onchain_packet": ((CONSUMES_CREDENTIALED_QUOTA,),
                            "calls Blockscout on our credentials with caller-supplied parameters"),
}

#: Uncontained and still ungated. Each one is an accepted exposure, not an oversight.
#:
#: The three that wrote — api_thesis_register, api_thesis_upload and api_atrox_scan —
#: were gated and have moved into COVERED. These four remain, and the reason is a
#: trade rather than an oversight: they are read-only against third parties, bounded
#: by those providers' own rate limits, and the dashboard calls all four automatically
#: to populate panels. Gating them would put an operator-key prompt on page load in
#: exchange for quota that a rate limit already caps. Revisit if a provider bills by
#: call or the panels stop being load-bearing.
UNCONTAINED_ACCEPTED = {
    "api_alpaca_packet", "api_tradier_stress_packet", "api_atrox_packet",
    "api_blockscout_onchain_packet",
}

REVIEWED_UNGUARDED = set(REVIEWED_UNGUARDED_EFFECTS)


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


# --- W3 § R4: is anything irreversible outside this process? --------------------


def test_every_reviewed_route_is_classified_with_a_reason() -> None:
    """A verdict with no reasoning is the kind nobody can disagree with.

    #34's entry said "no authority, position or doctrine change", which was true,
    and the routes sent real mail.
    """
    for endpoint, (effects, reason) in REVIEWED_UNGUARDED_EFFECTS.items():
        assert reason.strip(), f"{endpoint} is classified with no reason"
        assert len(reason) > 25, f"{endpoint}: the reason is too short to be checkable"
        for effect in effects:
            assert effect in (SENDS, WRITES_FOREIGN_STORE, CONSUMES_CREDENTIALED_QUOTA)


def test_an_uncontained_route_is_either_gated_or_an_accepted_exposure() -> None:
    """The point of the classification: nothing reaches outside by accident.

    A new ungated route that writes, sends or spends has to be added to
    UNCONTAINED_ACCEPTED deliberately, which is a decision someone makes rather
    than a line someone forgets.
    """
    uncontained = {e for e, (effects, _) in REVIEWED_UNGUARDED_EFFECTS.items() if effects}
    undeclared = uncontained - UNCONTAINED_ACCEPTED
    assert undeclared == set(), (
        f"these reach outside this process and nobody has accepted the exposure: {undeclared}"
    )
    stale = UNCONTAINED_ACCEPTED - uncontained
    assert stale == set(), (
        f"accepted as exposures but now classified as contained; remove them: {stale}"
    )


def test_a_gated_route_is_not_also_listed_as_ungated() -> None:
    assert REVIEWED_UNGUARDED.isdisjoint(server.AUTHORITY_ENDPOINTS)


def test_the_email_routes_left_the_reviewed_list_when_they_were_gated() -> None:
    """The regression #34 fixed, held in place."""
    for endpoint in ("api_email_test", "api_test_email"):
        assert endpoint not in REVIEWED_UNGUARDED_EFFECTS
        assert endpoint in server.AUTHORITY_ENDPOINTS
