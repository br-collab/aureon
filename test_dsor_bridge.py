"""DSOR bridge verification (WS-1) — run against the PRODUCTION aureon package.

Proves:
  1. AureonStateDSORStore is append-only (Axiom 4) and mirrors records into
     the provided state dict under lock.
  2. A live cockpit cycle records its gate DSOR record into
     aureon_state["cockpit_dsor_log"] — clean pass -> telemetry, hold ->
     escalation with the discrepancy code in the payload.
  3. cockpit_dsor_log survives a persistence.store save_state -> load_state
     cycle (a deploy) — the cockpit lineage is now durable (WS-0.1 parity).
"""
import py311_shim  # noqa
import threading, tempfile, os, json
from decimal import Decimal
from datetime import datetime, timezone

from aureon.dsor.bridge import AureonStateDSORStore, DSORAppendOnlyError
from aureon.cockpit import ClearingCockpit, PortalRegime
from aureon.agents.tier1.outputs import SettlementRail, SettlementKind
from aureon.contracts.dsor_stub import CAOMTier
from aureon.persistence.store import save_state, load_state

FAIL = []
def ck(name, cond):
    print(("  PASS " if cond else "  FAIL ") + name)
    if not cond: FAIL.append(name)

SD = datetime(2026, 7, 16, tzinfo=timezone.utc)


class FakeOut:
    """Minimal stand-in with operation_id + kind + model_dump (like the real
    settlement outputs) for the pure unit test."""
    def __init__(self, op, kind): self.operation_id = op; self.kind = kind
    def model_dump(self, mode=None): return {"operation_id": str(self.operation_id), "kind": self.kind}


def unit_tests():
    import uuid
    state, lock = {}, threading.Lock()
    store = AureonStateDSORStore(state, lock, cap=3)
    op = uuid.uuid4()
    r1 = store.append(FakeOut(op, "settlement_telemetry"))
    ck("append returns record with record_id", hasattr(r1, "record_id"))
    ck("mirrored into state log", state["cockpit_dsor_log"][0]["operation_id"] == str(op))
    ck("replay returns the output", store.replay(r1.record_id).kind == "settlement_telemetry")
    try:
        store.append(FakeOut(op, "settlement_telemetry")); ck("append-only enforced", False)
    except DSORAppendOnlyError:
        ck("append-only enforced", True)
    store.append(FakeOut(op, "settlement_telemetry"), correction_of=r1.record_id)
    ck("correction append allowed", len(state["cockpit_dsor_log"]) == 2)
    for _ in range(5): store.append(FakeOut(uuid.uuid4(), "settlement_telemetry"))
    ck("cap trims log", len(state["cockpit_dsor_log"]) == 3)


def cockpit_integration():
    state, lock = {}, threading.Lock()
    cp = ClearingCockpit(dsor_store=AureonStateDSORStore(state, lock))

    t = cp.capture_tasking(regime=PortalRegime.CCP, rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP, counterparty_id="CP-A", settlement_date=SD,
        authority_id="operator-bill", authority_tier=CAOMTier.T1, cusip="912828XX",
        net_delivery_quantity=Decimal("1000000"), net_payment_amount=Decimal("1000000"),
        ficc_published_net_delivery=Decimal("1000000"),
        intraday_credit_limit=Decimal("100000000"), intraday_credit_current_usage=Decimal("1000000"))
    g = cp.run_validation_gates(t)
    ck("clean pass recorded to state log", state.get("cockpit_dsor_log") and
       state["cockpit_dsor_log"][0]["kind"] == "settlement_telemetry")
    ck("record_id in package matches bridged log", any(
        e["record_id"] == str(g.dsor_pre_trade_record_id) for e in state["cockpit_dsor_log"]))

    t2 = cp.capture_tasking(regime=PortalRegime.CCP, rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP, counterparty_id="CP-B", settlement_date=SD,
        authority_id="operator-bill", authority_tier=CAOMTier.T1, cusip="912828YY",
        net_delivery_quantity=Decimal("1000000"), net_payment_amount=Decimal("1000000"),
        ficc_published_net_delivery=Decimal("1000000"),
        intraday_credit_limit=Decimal("100000000"), intraday_credit_current_usage=Decimal("1000000"),
        ficc_clearing_fund_compliant=False)
    cp.run_validation_gates(t2)
    top = state["cockpit_dsor_log"][0]
    ck("hold recorded as escalation", top["kind"] == "settlement_escalation")
    ck("discrepancy code in payload", top["payload"].get("discrepancy_code") == "clearing_fund_deficiency")
    ck("two operations in the unified log", len(state["cockpit_dsor_log"]) == 2)
    return state


def persistence_roundtrip(state):
    tmp = tempfile.mkdtemp(); sf = os.path.join(tmp, "state.json")
    lock = threading.Lock()
    state.setdefault("positions", []); state.setdefault("trades", [])
    save_state(state=state, lock=lock, state_file=sf,
               resolve_mmf_provider=lambda p: p or "FIX", log_error=lambda *a: None)
    on_disk = json.load(open(sf))
    ck("cockpit_dsor_log persisted to disk", len(on_disk.get("cockpit_dsor_log", [])) == 2)
    reloaded = load_state(state_file=sf, log_error=lambda *a: None)
    ck("cockpit_dsor_log survives load", reloaded and len(reloaded.get("cockpit_dsor_log", [])) == 2)
    ck("escalation survived the deploy",
       any(e["kind"] == "settlement_escalation" for e in reloaded["cockpit_dsor_log"]))


if __name__ == "__main__":
    print("— unit —");            unit_tests()
    print("— cockpit integ —");   st = cockpit_integration()
    print("— persistence rt —");  persistence_roundtrip(st)
    print("\n" + ("ALL BRIDGE CHECKS PASSED — cockpit lineage now unified + durable"
                  if not FAIL else f"{len(FAIL)} FAILED: {FAIL}"))
    raise SystemExit(1 if FAIL else 0)
