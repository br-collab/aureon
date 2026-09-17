"""W2B-4: approval has no economic side effect; booking follows independent fills.

Aureon inventory findings and §14 criteria covered:

- AUR-I-02 — Approval creates a release-authorized intent only: no order,
  fill, position, cash movement or trade record. Only fill events book, and a
  replayed fill books once.
- AUR-I-06 — No fill is copied from the approved intent. The paper venue
  prices from the market-data cache at its own observation time, and
  reconciliation detects a price or quantity difference.
- AUR-I-17 — Pending decisions and approval-side events survive a restart.
- Amendment 1 — a failed OMS send still raises (from PR #13), and now nothing
  reaches the venue or the book.

Run: pytest -q test_release_execution_booking.py
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

os.environ.setdefault("RAILWAY_VOLUME_MOUNT_PATH", tempfile.mkdtemp(prefix="aureon-booking-test-"))

from cannae_kernel.provenance import Provenance  # noqa: E402

from aureon.approval_service.release import find_release  # noqa: E402
from aureon.approval_service.service import resolve_pending_decision  # noqa: E402
from aureon.booking.consumer import book_fill  # noqa: E402
from aureon.booking.reconcile import PRICE_TOLERANCE_BPS, compare_intent_with_execution  # noqa: E402
from aureon.integration_adapters.paper_venue import (  # noqa: E402
    PaperFill,
    PaperVenue,
    PriceObservation,
    VenueRejection,
)
from aureon.policy_engine.binding import pretrade_rules_digest  # noqa: E402
from aureon.policy_engine.service import evaluate_pretrade_decision  # noqa: E402

RISK = {"drawdown_warn_pct": 5.0, "drawdown_fail_pct": 8.0}
RULES = pretrade_rules_digest(risk_policy=RISK, operating_cash_floor_pct=0.03, ofac_blocked_isins={})
T0 = datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc)
# Fix F1: a stress reading must say where it came from, or it is fabricated.
OFFICIAL_OFR = {"fsi_value": 0.1, "source": "ofr", "provenance": "FACT_EXTERNAL"}
OBSERVED = T0 + timedelta(seconds=40)


def _state(**decision_overrides):
    decision = {"id": "DEC-REL-1", "symbol": "TEST", "action": "BUY", "asset_class": "equities",
                "shares": 10, "price": 100.0, "notional": 1_000.0,
                "required_approvals": ["TRADER"], "current_approvals": []}
    decision.update(decision_overrides)
    return {"portfolio_value": 100_000.0, "cash": 50_000.0, "drawdown": 1.0,
            "positions": [], "trades": [], "authority_log": [], "prices": {"TEST": 100.0},
            "pending_decisions": [decision]}


def _authorize(state):
    lock = threading.RLock()
    evaluate_pretrade_decision(
        state=state, lock=lock, decision_id=state["pending_decisions"][0]["id"],
        market_is_open=lambda: True, macro_snapshot_fn=dict,
        ofr_snapshot_fn=lambda _m: OFFICIAL_OFR,
        operating_cash_floor_pct=0.03, risk_policy=RISK, symbol_to_isin={},
        ofac_blocked_isins={}, now=T0,
    )
    return resolve_pending_decision(
        state=state, lock=lock, decision_id=state["pending_decisions"][0]["id"],
        resolution="APPROVED", approval_role="TRADER", rules_digest=RULES,
        now=T0 + timedelta(seconds=30),
    )


def _venue(price="101.50"):
    def source(symbol):
        if price is None:
            return None
        return PriceObservation(price=price, observed_at=OBSERVED, source="test cache")
    return PaperVenue(price_source=source, clock=lambda: OBSERVED + timedelta(seconds=1))


# ── AUR-I-02: approval authorizes release and nothing else ──────────────────────


def test_approval_changes_no_cash_position_or_trade() -> None:
    state = _state()
    economic = copy.deepcopy({k: state[k] for k in ("cash", "positions", "trades")})
    result = _authorize(state)
    assert result["status"] == "ok"
    assert {k: state[k] for k in ("cash", "positions", "trades")} == economic
    assert "trade_reports" not in state
    release = state["release_events"][0]
    assert release["event_type"] == "RELEASE_AUTHORIZED"
    assert release["decision_id"] == "DEC-REL-1"
    assert release["provenance"] == "HUMAN_JUDGMENT"
    assert state["pending_decisions"] == []
    assert result["decision"]["status"] == "RELEASE_AUTHORIZED"


def test_the_approval_service_has_no_booking_code() -> None:
    import aureon.approval_service.service as service
    source = pathlib.Path(service.__file__).read_text(encoding="utf-8")
    for forbidden in ('["cash"]', '"positions"', '"trades"', "_apply_trade", "build_trade_report"):
        assert forbidden not in source, forbidden


# ── AUR-I-06: the venue is independent of the intent ────────────────────────────


def test_the_venue_prices_from_its_own_observation_not_the_decision() -> None:
    state = _state(price=1.0)  # an absurd decision price the venue must ignore
    release = _authorize(state)["release"]
    assert release.reference_price == "1.0"
    fill = _venue(price="101.50").execute(state, release)
    assert isinstance(fill, PaperFill)
    assert fill.price == "101.50"
    assert fill.notional == "1015.00"
    assert fill.price_observed_at == OBSERVED
    assert fill.provenance is Provenance.FACT_SYNTHETIC


def test_the_venue_source_never_reads_the_reference_price() -> None:
    import aureon.integration_adapters.paper_venue as venue
    source = pathlib.Path(venue.__file__).read_text(encoding="utf-8")
    code = source.split('"""', 2)[2]  # skip the module docstring, which names the field
    assert "reference_price" not in code


def test_the_venue_rejects_rather_than_invents() -> None:
    state = _state()
    release = _authorize(state)["release"]
    no_price = _venue(price=None).execute(state, release)
    assert isinstance(no_price, VenueRejection) and "price" in no_price.reason

    operator = _state(shares=None, price=None, notional=5_000.0)
    operator_release = _authorize(operator)["release"]
    no_quantity = _venue().execute(operator, operator_release)
    assert isinstance(no_quantity, VenueRejection) and "quantity" in no_quantity.reason
    assert "venue_fills" not in operator


def test_a_release_fills_once() -> None:
    state = _state()
    release = _authorize(state)["release"]
    first = _venue(price="100").execute(state, release)
    second = _venue(price="250").execute(state, release)
    assert second == first
    assert len(state["venue_fills"]) == 1


# ── Booking consumes fills, once ────────────────────────────────────────────────


def test_booking_comes_from_the_fill_and_a_duplicate_books_once() -> None:
    state = _state()
    decision = copy.deepcopy(state["pending_decisions"][0])
    release = _authorize(state)["release"]
    fill = _venue(price="101.50").execute(state, release)

    first = book_fill(state, fill, release, decision=decision)
    assert first.status == "BOOKED"
    assert state["cash"] == pytest.approx(50_000.0 - 1_015.0)
    assert state["positions"][0]["cost"] == 101.5
    trade = state["trades"][0]
    assert trade["fill_id"] == fill.fill_id
    assert trade["exec_price"] == 101.5
    assert trade["provenance"] == "FACT_SYNTHETIC"

    replay = book_fill(state, PaperFill.model_validate_json(fill.model_dump_json()), release,
                       decision=decision)
    assert replay.status == "DUPLICATE"
    assert state["cash"] == pytest.approx(48_985.0)
    assert len(state["positions"]) == 1 and len(state["trades"]) == 1


def test_a_fill_for_another_release_is_refused() -> None:
    state = _state()
    decision = copy.deepcopy(state["pending_decisions"][0])
    release = _authorize(state)["release"]
    fill = _venue().execute(state, release)
    stranger = fill.model_copy(update={"release_id": "REL-SOMEONE-ELSE"})
    assert book_fill(state, stranger, release, decision=decision).status == "REFUSED"
    assert state["trades"] == []


def test_an_unfundable_fill_is_refused_whole_and_recorded_as_a_break() -> None:
    state = _state()
    decision = copy.deepcopy(state["pending_decisions"][0])
    release = _authorize(state)["release"]
    state["cash"] = 10.0  # cash spent elsewhere between approval and fill
    fill = _venue().execute(state, release)
    outcome = book_fill(state, fill, release, decision=decision)
    assert outcome.status == "REFUSED"
    assert state["cash"] == 10.0 and state["positions"] == [] and state["trades"] == []
    assert state["booking_breaks"][0]["type"] == "BOOKING_REFUSED"


# ── Reconciliation detects differences ──────────────────────────────────────────


def test_reconciliation_detects_a_quantity_difference() -> None:
    intent = {"symbol": "TEST", "action": "BUY", "shares": 10, "intended_price": 100.0,
              "notional": 1_000.0}
    execution = {"symbol": "TEST", "action": "BUY", "shares": "9", "price": "100",
                 "notional": "900"}
    fields = {m["field"] for m in compare_intent_with_execution(intent, execution)}
    assert "shares" in fields


def test_reconciliation_detects_a_price_difference_beyond_tolerance() -> None:
    intent = {"symbol": "TEST", "action": "BUY", "shares": 10, "intended_price": 100.0,
              "notional": 1_000.0}
    within = {"symbol": "TEST", "action": "BUY", "shares": "10.0", "price": "101.5",
              "notional": "1015"}
    assert compare_intent_with_execution(intent, within) == []
    beyond = {**within, "price": "103", "notional": "1030"}
    mismatches = compare_intent_with_execution(intent, beyond)
    assert {m["field"] for m in mismatches} == {"price", "notional"}
    assert mismatches[0]["deviation_bps"] > PRICE_TOLERANCE_BPS


def test_a_discrepant_fill_books_and_raises_a_break() -> None:
    state = _state()
    decision = copy.deepcopy(state["pending_decisions"][0])
    release = _authorize(state)["release"]
    fill = _venue(price="120").execute(state, release)
    outcome = book_fill(state, fill, release, decision=decision)
    assert outcome.status == "BOOKED"
    assert state["trades"][0]["reconciliation"] == "DISCREPANCY"
    assert state["booking_breaks"][0]["type"] == "EXECUTION_DISCREPANCY"


# ── C2 waits for an execution event ─────────────────────────────────────────────


def test_c2_no_longer_builds_a_confirmation_from_the_decision() -> None:
    import aureon.agents.c2.coordinator as coordinator
    source = pathlib.Path(coordinator.__file__).read_text(encoding="utf-8")
    assert source.count("ExecutionConfirmation(") == 1
    block = source[source.index("ExecutionConfirmation("):]
    block = block[: block.index(")\n")]
    assert "decision.get" not in block
    assert "execution_event.get" in block


@pytest.fixture
def c2():  # type: ignore[no-untyped-def]
    from aureon.agents.c2.coordinator import ThifurC2

    state = {"authority_log": [], "doctrine_version": "test", "positions": [], "cash": 0.0}
    return ThifurC2(state, threading.RLock()), state


def _fill_event(**overrides):
    event = {"fill_id": "FILL-C2", "release_id": "REL-C2", "decision_id": "DEC-C2",
             "symbol": "TEST", "action": "BUY", "asset_class": "equities", "quantity": "10",
             "price": "100", "notional": "1000", "venue": "AUREON-PAPER",
             "provenance": "FACT_SYNTHETIC", "filled_at": OBSERVED.isoformat()}
    event.update(overrides)
    return event


C2_DECISION = {"id": "DEC-C2", "symbol": "TEST", "action": "BUY", "shares": 10, "price": 100.0,
               "notional": 1_000.0, "asset_class": "equities"}


def test_c2_waits_when_there_is_no_execution_event(c2) -> None:  # type: ignore[no-untyped-def]
    coordinator, state = c2
    assert coordinator._find_execution_event("DEC-C2") is None
    coordinator._await_execution("TSK-C2", dict(C2_DECISION), [], "test", {})
    assert "TSK-C2" in state["c2_awaiting_execution"]


@pytest.mark.parametrize(("fill", "recon", "lifecycle"), [
    (_fill_event(), "MATCHED", "COMPLETE"),
    (_fill_event(quantity="9", notional="900"), "DISCREPANCY", "DISCREPANCY_HALTED"),
    (_fill_event(price="130", notional="1300"), "DISCREPANCY", "DISCREPANCY_HALTED"),
])
def test_c2_resumes_on_the_fill_and_reconciles_against_it(c2, fill, recon, lifecycle) -> None:  # type: ignore[no-untyped-def]
    coordinator, state = c2
    task_id = coordinator.issue_task(dict(C2_DECISION), agents=[])
    coordinator._await_execution(task_id, dict(C2_DECISION), [], "test", {})
    results = coordinator.on_execution_event(fill)
    assert [r["status"] for r in results] == [lifecycle]
    assert results[0]["ts_recon_result"]["status"] == recon
    assert results[0]["execution_event"]["fill_id"] == fill["fill_id"]
    assert task_id not in state["c2_awaiting_execution"]


# ── Server: end to end, OMS failure, restart ────────────────────────────────────


@pytest.fixture
def server_client(monkeypatch):  # type: ignore[no-untyped-def]
    import server

    monkeypatch.setenv("AUREON_ADMIN_KEY", "booking-test-key-0123456789")
    monkeypatch.setattr(server._session_protocol, "is_session_open", lambda: True)
    monkeypatch.setattr(server, "_is_instrument_tradeable", lambda *_a: (True, "open"))
    monkeypatch.setattr(server, "_market_is_open", lambda: True)
    monkeypatch.setattr(server, "_get_fred_macro_snapshot", dict)
    monkeypatch.setattr(server, "_send_trade_confirmation_email", lambda *_a: None)
    monkeypatch.setattr(server, "_save_state", lambda: None)
    monkeypatch.setitem(server._ofr_cache, "data", dict(OFFICIAL_OFR))
    keys = ("pending_decisions", "positions", "cash", "portfolio_value", "drawdown", "prices",
            "prices_observed_at", "trades", "halt_active", "release_events", "venue_fills",
            "booked_fill_ids", "booking_breaks")
    with server._lock:
        saved = {k: copy.deepcopy(server.aureon_state[k]) for k in keys if k in server.aureon_state}
        server.aureon_state.update({
            "pending_decisions": [], "positions": [], "cash": 50_000.0,
            "portfolio_value": 100_000.0, "drawdown": 1.0, "prices": {"TEST": 102.0},
            "prices_observed_at": datetime.now(timezone.utc).isoformat(),
            "trades": [], "halt_active": False,
        })
    yield server, server.app.test_client()
    with server._lock:
        for k in keys:
            server.aureon_state.pop(k, None)
        server.aureon_state.update(saved)


def _headers():
    return {"X-Admin-Key": "booking-test-key-0123456789", "X-Request-Nonce": uuid.uuid4().hex}


def _approve(server, client, decision_id, price=100.0):
    with server._lock:
        server.aureon_state["pending_decisions"].append(
            {"id": decision_id, "symbol": "TEST", "action": "BUY", "asset_class": "equities",
             "shares": 10, "price": price, "notional": 10 * price,
             "required_approvals": ["TRADER"], "current_approvals": []})
    assert client.get(f"/api/decisions/{decision_id}/pretrade").get_json()["disposition"] == "PASS"
    return client.post(f"/api/decisions/{decision_id}", headers=_headers(),
                       json={"resolution": "APPROVED", "approval_role": "TRADER"})


def test_api_approval_books_only_from_the_venue_fill(server_client) -> None:
    server, client = server_client
    response = _approve(server, client, "DEC-E2E-1")
    body = response.get_json()
    assert response.status_code == 200, body
    assert body["execution"]["status"] == "BOOKED"
    assert body["execution"]["provenance"] == "FACT_SYNTHETIC"
    trade = server.aureon_state["trades"][0]
    assert trade["exec_price"] == 102.0          # the cache price, not the decision's 100
    assert trade["release_id"] == body["release_id"]
    assert server.aureon_state["cash"] == pytest.approx(50_000.0 - 1_020.0)
    assert find_release(server.aureon_state, body["release_id"]) is not None
    journal = server.aureon_state["decision_journal"][0]
    assert journal["exec_price"] == 102.0 and journal["execution"]["fill_id"] == trade["fill_id"]


def test_api_stale_market_price_is_rejected_by_the_venue(server_client) -> None:
    server, client = server_client
    server.aureon_state["prices_observed_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    body = _approve(server, client, "DEC-E2E-STALE").get_json()
    assert body["status"] == "ok"
    assert body["execution"]["status"] == "VENUE_REJECTED"
    assert server.aureon_state["trades"] == []
    assert server.aureon_state["cash"] == 50_000.0


def test_api_failed_oms_send_raises_and_nothing_reaches_the_venue(server_client, monkeypatch) -> None:
    server, client = server_client

    def down(_packet):
        raise ConnectionError("OMS unreachable")

    monkeypatch.setattr(server, "oms_send", down)
    response = _approve(server, client, "DEC-E2E-OMS")
    assert response.status_code == 502
    assert "Nothing was booked" in response.get_json()["error"]
    assert server.aureon_state["trades"] == []
    assert server.aureon_state["cash"] == 50_000.0
    assert not any(f["decision_id"] == "DEC-E2E-OMS"
                   for f in server.aureon_state.get("venue_fills", []))


def _raise(level, where, message):
    raise AssertionError(f"{level} {where}: {message}")


def test_pending_decisions_and_release_events_survive_a_restart(server_client, tmp_path, monkeypatch) -> None:
    """AUR-I-17: 17 Sep, 4 pending decisions became 0 after the #15 deploy."""
    from aureon.persistence.store import save_state

    server, client = server_client
    body = _approve(server, client, "DEC-RESTART-APPROVED").get_json()
    with server._lock:
        server.aureon_state["pending_decisions"] = [
            {"id": f"DEC-RESTART-{i}", "symbol": "TEST", "action": "BUY",
             "asset_class": "equities", "shares": 1, "price": 100.0, "notional": 100.0,
             "required_approvals": ["TRADER"], "current_approvals": []}
            for i in range(4)
        ]
    state_file = tmp_path / "aureon_state_persist.json"
    save_state(state=server.aureon_state, lock=server._lock, state_file=str(state_file),
               resolve_mmf_provider=server._resolve_mmf_provider, log_error=_raise)
    expected = {k: copy.deepcopy(server.aureon_state[k])
                for k in ("pending_decisions", "release_events", "venue_fills", "booked_fill_ids")}

    # The redeploy: in-memory state is gone; boot reloads from the volume.
    with server._lock:
        for key in expected:
            server.aureon_state[key] = []
    monkeypatch.setattr(server, "STATE_FILE", str(state_file))
    server.run_doctrine_stack()

    for key, value in expected.items():
        assert server.aureon_state[key] == value, key
    assert len(server.aureon_state["pending_decisions"]) == 4
    assert any(r["release_id"] == body["release_id"] for r in server.aureon_state["release_events"])

    # A redelivered fill after restart still books once.
    release = find_release(server.aureon_state, body["release_id"])
    fill = PaperFill.model_validate_json(json.dumps(server.aureon_state["venue_fills"][0]))
    cash = server.aureon_state["cash"]
    with server._lock:
        again = book_fill(server.aureon_state, fill, release, decision={"id": release.decision_id})
    assert again.status == "DUPLICATE" and server.aureon_state["cash"] == cash
