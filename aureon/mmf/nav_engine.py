"""
Aureon MMF — NAV Engine (Phase 1, Sandbox)

PURPOSE:     Daily NAV (Net Asset Value) computation and sweep for the
             Arcadia Liquidity Fund sandbox. Drives two share classes:

               Class F (CNAV) — $1.0000 stable (U.S. Government MMF
                                model); does not float.
               Class D (FNAV) — 4-decimal-place floating NAV accruing
                                from the yield_engine's net daily
                                yield.

             Emits DSOR (Decision System of Record) entries on every
             sweep outcome — NAV_SWEEP_COMPLETE or NAV_SWEEP_HALTED —
             using the canonical DSORRecord dataclass from
             aureon.agents.base.

             A background scheduler fires run_sweep() daily at 17:00 ET
             (stdlib threading only; no APScheduler per the operator's
             Leto-pattern preference). Scheduler is exposed via
             start_nav_scheduler() for server boot to call.

INPUTS:      yield_engine.get_current_yield_inputs() and
             yield_engine.compute_daily_accrual() — the FRED-backed
             DGS1MO/SOFR source. If `stale` is True or no rate source
             is available, the NAV engine opens its circuit breaker
             and halts the sweep.

OUTPUTS:     run_sweep() -> dict with sweep result + embedded DSOR id.
             get_nav_state() -> dict snapshot for API consumption.
             next_sweep_dt() -> UTC datetime of next 17:00 ET.
             get_dsor_log() -> list of DSORRecord (Prompt 5 will plumb
             this into aureon_state["operational_journal"]).

ASSUMPTIONS: In-memory state for Phase 1. Process restart resets the
             NAV to $1.0000 and sweep_count to 0. Persistence is a
             Phase 2 concern. Fund-state hooks (AUM by lane) are
             optional in Prompt 2 — the NAV engine works with zeros
             until fund_state is wired in Prompt 3 via bind_fund_state.

AUDIT NOTES: Every decision path produces a DSOR record — successful
             sweep, halted sweep, variance breach, stale oracle.
             Module state is threading-locked. Circuit breaker is
             sticky: once open, only a manual reset would close it
             (not in scope for Phase 1). All figures SYNTHETIC.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from aureon.agents.base import DSORRecord
from aureon.mmf import yield_engine

log = logging.getLogger("aureon.mmf.nav_engine")


# ─── Fund configuration ─────────────────────────────────────────────────────
FUND_NAME = "Arcadia Liquidity Fund — Sandbox Series"
CLASS_F_TYPE = "CNAV"            # stable $1.0000
CLASS_D_TYPE = "FNAV"            # floating, 4 decimal places
MANAGEMENT_FEE_BPS = 15          # sandbox — competitive vs BUIDL 20-50bps
SWEEP_HOUR_ET = 17               # 17:00 ET daily
ORACLE_STALE_THRESHOLD_MIN = 15  # reserved; not acted on in Phase 1 beyond yield_engine's own stale flag
NAV_VARIANCE_HALT_PCT = Decimal("0.10")  # halt if FNAV moves >0.10% unexplained in a single sweep
CAOM_OPERATOR = "CAOM-001"

_ET = ZoneInfo("America/New_York")
_NAV_QUANTUM = Decimal("0.0001")  # 4 decimal place quantization

# ─── Module state (threading-locked) ────────────────────────────────────────
_state_lock = threading.RLock()

_state: dict = {
    "cnav": Decimal("1.0000"),
    "fnav": Decimal("1.0000"),
    "last_sweep_at": None,                   # datetime | None
    "next_sweep_at": None,                   # populated lazily / on start_nav_scheduler
    "sweep_count": 0,
    "last_fred_rate": None,                  # dict | None — yield_engine's most recent input snapshot
    "circuit_open": False,
    "circuit_reason": "",
}

# DSOR log. Prompt 5 plumbs this into aureon_state["operational_journal"].
_dsor_log: list[DSORRecord] = []

# Fund state hooks — Prompt 3 (fund_state.py) binds these at import. Until
# bound, NAV sweep records 0 AUM without halting (sweep is NAV-only, not
# AUM-dependent). The reset hook zeros fund_state's daily-redemption
# counters at the end of a successful sweep; without it counters would
# accumulate across days, breaking the liquidity-fee denominator.
_fund_state_getter: Optional[Callable[[], dict]] = None
_fund_state_reset:  Optional[Callable[[], None]] = None


# ─── Fund-state dependency injection ────────────────────────────────────────
def bind_fund_state(getter: Callable[[], dict],
                    reset_daily_counters: Optional[Callable[[], None]] = None) -> None:
    """Called once from Prompt 3's fund_state module to register an AUM
    provider and (optionally) a post-sweep reset hook.

    `getter` must return a dict with Decimal keys `aum_f` and `aum_d`;
    anything else is treated as zero AUM.

    `reset_daily_counters` (optional) is invoked at the end of every
    SUCCESSFUL sweep to zero fund_state's daily redemption counters.
    Exceptions from the hook are logged but do not halt or rollback
    the sweep — the breaker is reserved for doctrine breaches, not
    integration bugs.
    """
    global _fund_state_getter, _fund_state_reset
    _fund_state_getter = getter
    _fund_state_reset = reset_daily_counters


def _aum_snapshot() -> tuple[Decimal, Decimal]:
    if _fund_state_getter is None:
        return Decimal("0"), Decimal("0")
    try:
        st = _fund_state_getter() or {}
        return (
            Decimal(str(st.get("aum_f", 0))),
            Decimal(str(st.get("aum_d", 0))),
        )
    except Exception as e:
        log.warning("fund_state getter failed: %s: %s", type(e).__name__, e)
        return Decimal("0"), Decimal("0")


# ─── Sweep-time helpers ─────────────────────────────────────────────────────
def next_sweep_dt() -> datetime:
    """Return the next 17:00 ET as a UTC datetime.

    If called before today's 17:00 ET, returns today at 17:00 ET in UTC.
    Otherwise returns tomorrow at 17:00 ET in UTC.
    """
    now_et = datetime.now(_ET)
    sweep_et = now_et.replace(hour=SWEEP_HOUR_ET, minute=0, second=0, microsecond=0)
    if now_et >= sweep_et:
        sweep_et = sweep_et + timedelta(days=1)
    return sweep_et.astimezone(timezone.utc)


def _quantize_nav(value: Decimal) -> Decimal:
    return value.quantize(_NAV_QUANTUM, rounding=ROUND_HALF_UP)


def _stamp_dsor(event_type: str, payload: dict) -> DSORRecord:
    """Build a DSORRecord, append to the module log, return it.

    The prompt's "Import the existing DSOR stamping function" hint maps
    to the DSORRecord dataclass in aureon.agents.base — no standalone
    stamping function exists at module level in the codebase; the
    Agent ABC's dsor_stamp() method isn't reachable without an Agent
    instance. We build records directly here and let Prompt 5 plumb
    this log into aureon_state["operational_journal"].
    """
    record = DSORRecord(
        record_id=f"DSOR-MMF-NAV-{uuid.uuid4().hex[:12]}",
        caom_mode="CAOM-001",
        operator=CAOM_OPERATOR,
        timestamp=datetime.now(timezone.utc),
        event_type=event_type,
        payload=payload,
    )
    _dsor_log.append(record)
    log.info("DSOR %s %s", event_type, record.record_id)
    return record


def get_dsor_log() -> list[DSORRecord]:
    """Return a copy of the DSOR log. Prompt 5 will call this to merge
    into the central operational journal."""
    return list(_dsor_log)


# ─── NAV compute + sweep ────────────────────────────────────────────────────
def compute_nav() -> dict:
    """Run a NAV computation without committing state or emitting DSOR.

    Reads yield_engine's current inputs; checks stale; computes FNAV
    accrual at the net daily yield; checks the unexplained-variance
    halt threshold against the previous FNAV. CNAV stays $1.0000 in
    all cases (U.S. Government MMF model).

    Returns one of:
      - HALTED  (stale oracle or variance breach) — circuit opens.
      - OK      — new CNAV/FNAV, ready for run_sweep() to persist.
    """
    with _state_lock:
        previous_fnav = _state["fnav"]
        previous_cnav = _state["cnav"]

    inputs = yield_engine.get_current_yield_inputs()

    if inputs["source"] == "NONE" or inputs["stale"]:
        reason = "oracle stale" if inputs["stale"] else "no yield source"
        return {
            "status": "HALTED",
            "reason": reason,
            "inputs": inputs,
            "last_good_cnav": previous_cnav,
            "last_good_fnav": previous_fnav,
        }

    accrual = yield_engine.compute_daily_accrual(previous_fnav, MANAGEMENT_FEE_BPS)

    new_fnav_raw = previous_fnav + accrual["net_yield_daily"]
    new_fnav = _quantize_nav(new_fnav_raw)
    new_cnav = previous_cnav  # CNAV does not float.

    # Variance halt check — unexplained swing vs previous FNAV.
    # NAV_VARIANCE_HALT_PCT is expressed in percentage units (e.g., 0.10
    # means 0.10%). A normal MMF daily move is ~0.01% at current rates;
    # anything 10x that is anomalous.
    if previous_fnav > 0:
        variance_pct = abs(new_fnav - previous_fnav) / previous_fnav * Decimal("100")
        if variance_pct > NAV_VARIANCE_HALT_PCT:
            return {
                "status": "HALTED",
                "reason": "variance breach",
                "variance_pct": str(variance_pct),
                "threshold_pct": str(NAV_VARIANCE_HALT_PCT),
                "proposed_fnav": new_fnav,
                "last_good_cnav": previous_cnav,
                "last_good_fnav": previous_fnav,
                "inputs": inputs,
            }

    return {
        "status": "OK",
        "cnav": new_cnav,
        "fnav": new_fnav,
        "gross_yield_daily": accrual["gross_yield_daily"],
        "fee_daily": accrual["fee_daily"],
        "net_yield_daily": accrual["net_yield_daily"],
        "annual_rate_pct": accrual["annual_rate_pct"],
        "fred_rate_used": accrual["source"],          # "DGS1MO" or "SOFR"
        "sofr_used": inputs["sofr_pct"],              # always carried for audit, even if source=DGS1MO
        "inputs": inputs,
    }


def reset_circuit(reason: str = "operator reset") -> dict:
    """Close an open circuit breaker. Operator-gated mechanism (at the
    Railway route layer in Prompt 5 — this function itself doesn't
    check authority; the route that calls it does).

    Emits NAV_CIRCUIT_RESET in the DSOR log with the supplied reason.
    Safe to call when the circuit is already closed (no-op + DSOR
    record capturing the redundant attempt — useful for audit)."""
    with _state_lock:
        was_open = _state["circuit_open"]
        prev_reason = _state["circuit_reason"]
        _state["circuit_open"] = False
        _state["circuit_reason"] = ""
    record = _stamp_dsor("NAV_CIRCUIT_RESET", {
        "was_open": was_open,
        "previous_reason": prev_reason,
        "reset_reason": reason,
        "reset_at": datetime.now(timezone.utc).isoformat(),
    })
    return {
        "status": "OK",
        "was_open": was_open,
        "previous_reason": prev_reason,
        "dsor_id": record.record_id,
    }


def run_sweep(force_allow_stale: bool = False) -> dict:
    """Execute a NAV sweep. Persists state on OK; opens circuit on HALTED.
    Always emits a DSOR record.

    Gate: if circuit is already open, returns HALTED immediately without
    attempting compute_nav() — sticky breaker per MMF ops discipline.

    `force_allow_stale` is a TEST-ONLY hook that overrides the stale
    oracle check when FRED has published nothing newer than 2 days
    ago (weekend / publication-lag timing) but the operator needs to
    validate the happy path. The scheduler never passes force=True.
    The resulting DSOR record carries `force_allow_stale: true` in
    its payload so the audit trail reflects that the sweep was taken
    with stale data deliberately.
    """
    with _state_lock:
        if _state["circuit_open"]:
            record = _stamp_dsor("NAV_SWEEP_HALTED", {
                "reason": "circuit already open",
                "circuit_reason": _state["circuit_reason"],
                "last_good_cnav": str(_state["cnav"]),
                "last_good_fnav": str(_state["fnav"]),
                "halted_at": datetime.now(timezone.utc).isoformat(),
                "sweep_count": _state["sweep_count"],
            })
            return {
                "status": "HALTED",
                "reason": "circuit already open",
                "circuit_reason": _state["circuit_reason"],
                "dsor_id": record.record_id,
            }

    result = compute_nav()

    # Test-only bypass: if the ONLY reason for HALT is stale oracle and
    # the caller has explicitly requested a forced run, re-compute
    # ignoring the stale flag. Variance breach and NONE-source still halt.
    if (result["status"] == "HALTED"
            and result.get("reason") == "oracle stale"
            and force_allow_stale):
        inputs = result["inputs"]
        with _state_lock:
            previous_fnav = _state["fnav"]
            previous_cnav = _state["cnav"]
        accrual = yield_engine.compute_daily_accrual(previous_fnav, MANAGEMENT_FEE_BPS)
        if accrual["annual_rate_pct"] is None:
            # No rate even available — force can't help, hold HALT.
            pass
        else:
            new_fnav = _quantize_nav(previous_fnav + accrual["net_yield_daily"])
            # Variance check still applies under force.
            if previous_fnav > 0:
                variance_pct = abs(new_fnav - previous_fnav) / previous_fnav * Decimal("100")
                if variance_pct > NAV_VARIANCE_HALT_PCT:
                    result = {
                        "status": "HALTED",
                        "reason": "variance breach",
                        "variance_pct": str(variance_pct),
                        "threshold_pct": str(NAV_VARIANCE_HALT_PCT),
                        "proposed_fnav": new_fnav,
                        "last_good_cnav": previous_cnav,
                        "last_good_fnav": previous_fnav,
                        "inputs": inputs,
                    }
                else:
                    result = {
                        "status": "OK",
                        "cnav": previous_cnav,
                        "fnav": new_fnav,
                        "gross_yield_daily": accrual["gross_yield_daily"],
                        "fee_daily": accrual["fee_daily"],
                        "net_yield_daily": accrual["net_yield_daily"],
                        "annual_rate_pct": accrual["annual_rate_pct"],
                        "fred_rate_used": accrual["source"],
                        "sofr_used": inputs["sofr_pct"],
                        "inputs": inputs,
                        "force_allow_stale_used": True,
                    }

    with _state_lock:
        if result["status"] == "HALTED":
            _state["circuit_open"] = True
            _state["circuit_reason"] = result["reason"]
            aum_f, aum_d = _aum_snapshot()
            record = _stamp_dsor("NAV_SWEEP_HALTED", {
                "reason": result["reason"],
                "circuit_reason": result["reason"],
                "last_good_cnav": str(_state["cnav"]),
                "last_good_fnav": str(_state["fnav"]),
                "variance_pct": result.get("variance_pct"),
                "threshold_pct": result.get("threshold_pct"),
                "proposed_fnav": str(result.get("proposed_fnav", "")),
                "halted_at": datetime.now(timezone.utc).isoformat(),
                "aum_class_f": str(aum_f),
                "aum_class_d": str(aum_d),
                "sweep_count": _state["sweep_count"],
                "fred_inputs": result.get("inputs"),
            })
            return {
                "status": "HALTED",
                "reason": result["reason"],
                "circuit_reason": _state["circuit_reason"],
                "dsor_id": record.record_id,
            }

        # OK path — commit new CNAV/FNAV and advance counters.
        _state["cnav"] = result["cnav"]
        _state["fnav"] = result["fnav"]
        _state["last_sweep_at"] = datetime.now(timezone.utc)
        _state["next_sweep_at"] = next_sweep_dt()
        _state["sweep_count"] += 1
        _state["last_fred_rate"] = result["inputs"]

        aum_f, aum_d = _aum_snapshot()
        record = _stamp_dsor("NAV_SWEEP_COMPLETE", {
            "cnav": str(result["cnav"]),
            "fnav": str(result["fnav"]),
            "gross_yield": str(result["gross_yield_daily"]),
            "net_yield": str(result["net_yield_daily"]),
            "fee_accrued": str(result["fee_daily"]),
            "fred_rate_used": result["fred_rate_used"],   # "DGS1MO" | "SOFR"
            "sofr_used": result["sofr_used"],
            "annual_rate_pct": result["annual_rate_pct"],
            "sweep_count": _state["sweep_count"],
            "aum_class_f": str(aum_f),
            "aum_class_d": str(aum_d),
            "sweep_at": _state["last_sweep_at"].isoformat(),
            "next_sweep_at": _state["next_sweep_at"].isoformat(),
            "status": "OK",
            "force_allow_stale_used": result.get("force_allow_stale_used", False),
        })

    # End-of-sweep fund_state reset — outside the state lock so the
    # fund_state module can acquire its own lock without contention.
    # Non-fatal on failure.
    if _fund_state_reset is not None:
        try:
            _fund_state_reset()
        except Exception as e:
            log.warning("fund_state reset hook failed after sweep: %s: %s",
                        type(e).__name__, e)

    with _state_lock:
        return {
            "status": "OK",
            "cnav": str(result["cnav"]),
            "fnav": str(result["fnav"]),
            "gross_yield_daily": str(result["gross_yield_daily"]),
            "net_yield_daily": str(result["net_yield_daily"]),
            "fee_daily": str(result["fee_daily"]),
            "annual_rate_pct": result["annual_rate_pct"],
            "fred_rate_used": result["fred_rate_used"],
            "sofr_used": result["sofr_used"],
            "sweep_count": _state["sweep_count"],
            "sweep_at": _state["last_sweep_at"].isoformat(),
            "next_sweep_at": _state["next_sweep_at"].isoformat(),
            "dsor_id": record.record_id,
        }


def get_nav_state() -> dict:
    """Return a JSON-safe snapshot of current NAV state for API consumption."""
    with _state_lock:
        return {
            "fund_name": FUND_NAME,
            "cnav": str(_state["cnav"]),
            "fnav": str(_state["fnav"]),
            "last_sweep_at": _state["last_sweep_at"].isoformat() if _state["last_sweep_at"] else None,
            "next_sweep_at": _state["next_sweep_at"].isoformat() if _state["next_sweep_at"] else next_sweep_dt().isoformat(),
            "sweep_count": _state["sweep_count"],
            "circuit_open": _state["circuit_open"],
            "circuit_reason": _state["circuit_reason"],
            "annual_rate_pct": (_state["last_fred_rate"] or {}).get("dgs1mo_pct")
                               or (_state["last_fred_rate"] or {}).get("sofr_pct"),
            "fred_rate_used": (_state["last_fred_rate"] or {}).get("source"),
            "management_fee_bps": MANAGEMENT_FEE_BPS,
        }


# ─── Scheduler (stdlib threading) ───────────────────────────────────────────
_scheduler_thread: Optional[threading.Thread] = None
_scheduler_stop = threading.Event()


def _sweep_loop() -> None:
    """Fires run_sweep() at each 17:00 ET boundary.

    Sleeps in 60s chunks so the stop event can interrupt within a minute.
    Recomputes the target time every loop iteration (robust against
    clock drift, DST transitions, and missed wake-ups).
    """
    log.info("NAV scheduler thread started — next sweep at %s",
             next_sweep_dt().isoformat())
    while not _scheduler_stop.is_set():
        next_dt = next_sweep_dt()
        while not _scheduler_stop.is_set():
            remaining = (next_dt - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                break
            _scheduler_stop.wait(min(60.0, remaining))
        if _scheduler_stop.is_set():
            break
        try:
            result = run_sweep()
            log.info("NAV scheduled sweep fired — status=%s sweep_count=%s",
                     result.get("status"), result.get("sweep_count"))
        except Exception as e:
            log.exception("NAV scheduled sweep raised: %s: %s",
                          type(e).__name__, e)
            # A raised exception does NOT open the circuit — the circuit
            # is reserved for doctrine breaches (stale oracle, variance).
            # An implementation bug in run_sweep is a distinct failure
            # class; the scheduler just logs and tries again tomorrow.
    log.info("NAV scheduler thread exiting")


def start_nav_scheduler() -> threading.Thread:
    """Start the background scheduler thread. Idempotent — returns the
    existing thread if already running. Called once from server.py's
    boot block in Prompt 5."""
    global _scheduler_thread
    with _state_lock:
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            log.info("NAV scheduler already running (thread=%s)",
                     _scheduler_thread.name)
            return _scheduler_thread
        _scheduler_stop.clear()
        _scheduler_thread = threading.Thread(
            target=_sweep_loop, daemon=True, name="aureon-mmf-nav-scheduler",
        )
        _scheduler_thread.start()
        _state["next_sweep_at"] = next_sweep_dt()
        return _scheduler_thread


def stop_nav_scheduler(join_timeout: float = 5.0) -> None:
    """Signal the scheduler thread to exit. Used by tests / graceful
    shutdown; not called from production boot."""
    _scheduler_stop.set()
    if _scheduler_thread is not None:
        _scheduler_thread.join(timeout=join_timeout)


# ─── Standalone smoke test ──────────────────────────────────────────────────
if __name__ == "__main__":
    import json as _json

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    print("=" * 72)
    print("AUREON MMF — nav_engine smoke test (SYNTHETIC / SANDBOX)")
    print("=" * 72)

    print("\nInitial state:")
    print(_json.dumps(get_nav_state(), indent=2, default=str))

    print("\nSweep #1 (normal; expect HALT — FRED publish lag):")
    r1 = run_sweep()
    print(_json.dumps(r1, indent=2, default=str))

    print("\nOperator reset (close circuit):")
    rst = reset_circuit("smoke test — force path coming next")
    print(_json.dumps(rst, indent=2, default=str))

    print("\nSweep #2 (force_allow_stale=True; expect NAV_SWEEP_COMPLETE):")
    r2 = run_sweep(force_allow_stale=True)
    print(_json.dumps(r2, indent=2, default=str))

    print("\nState after sweep #2:")
    print(_json.dumps(get_nav_state(), indent=2, default=str))

    print("\nDSOR log (all entries):")
    for rec in get_dsor_log():
        rec_dict = asdict(rec)
        rec_dict["timestamp"] = rec.timestamp.isoformat()
        print(_json.dumps(rec_dict, indent=2, default=str))

    print("=" * 72)
