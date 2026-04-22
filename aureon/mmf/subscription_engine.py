"""
Aureon MMF — Subscription Engine (Phase 1, Sandbox)

PURPOSE:     Accept subscriptions into the Arcadia Liquidity Fund
             sandbox via two lanes:

               Lane F (FIAT)    — simulated T+1 USD settlement; shares
                                   priced against CNAV ($1.0000 stable).
               Lane D (Digital) — simulated ~8s atomic DvP; shares
                                   priced against FNAV (4-decimal
                                   floating). Phase 1 is simulated —
                                   no real XRPL call yet (that's
                                   Phase 2's tokenized_mmf_xrpl_leg
                                   integration).

             Every path emits a DSOR (Decision System of Record) entry
             with the canonical DSORRecord shape. Three event types:

               FIAT_SUBSCRIPTION_COMPLETE
               DIGITAL_SUBSCRIPTION_COMPLETE  (flagged SIMULATED)
               KYC_EXCEPTION_HITL_GATE_OPEN
               CATO_HOLD_OPERATOR_DECISION
               SUBSCRIPTION_DUPLICATE_REJECTED

INPUTS:      process_subscription(investor_id, lane, amount_usd).

OUTPUTS:     dict with status + lane + shares + NAV used + settlement
             timestamp + dsor_id. HITL-required outcomes carry
             `hitl_required: True` and surface the exception reason.

ASSUMPTIONS: Cato gate state is fetched via HTTP from Railway prod
             (/api/cato/gate). Phase 5 can optimize to read the
             in-process _cato_input_cache directly; for Phase 1 the
             HTTP path keeps subscription_engine independent of
             server.py import order.

             KYC allowlist is the 3-seed Phase 1 set in fund_state.
             Real onboarding pipeline materializes this list Phase 3+.

AUDIT NOTES: Idempotency via sha256(investor_id + lane + amount +
             minute_bucket) with a 60s rejection window. Non-blocking
             and memory-only; a process restart clears the cache.
             All figures SYNTHETIC / SANDBOX.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from zoneinfo import ZoneInfo

from typing import Callable
from aureon.agents.base import DSORRecord
from aureon.mmf import fund_state, nav_engine

log = logging.getLogger("aureon.mmf.subscription_engine")

# Phase 2 P2-1: operational journal sink. server.py binds this at
# boot so DSOR events flow into aureon_state["operational_journal"].
_journal_sink: Optional[Callable[[dict], None]] = None


def bind_journal_sink(fn: Callable[[dict], None]) -> None:
    """Called by server.py to route subscription DSOR events into
    the operational_journal."""
    global _journal_sink
    _journal_sink = fn

# ─── Configuration ──────────────────────────────────────────────────────────
# RAILWAY_BASE used only by the Cato gate fetch. Mirrors Leto's pattern of
# reading from env first, then defaulting.
RAILWAY_BASE = os.environ.get(
    "RAILWAY_BASE",
    "https://aureon-production.up.railway.app",
).rstrip("/")

CATO_GATE_TIMEOUT_S = 6.0
CATO_GATE_URL = f"{RAILWAY_BASE}/api/cato/gate"

# Simulated digital-lane finality — real XRPL Phase 2 takes ~8s end-to-end
# for an atomic DvP validation. We carry the number forward as a stand-in.
DIGITAL_FINALITY_SIMULATED_S = 8

# Idempotency window.
_IDEMPOTENCY_WINDOW_S = 60
_IDEMPOTENCY_BUCKET_S = 60  # minute-bucket matches the 60s window

_ET = ZoneInfo("America/New_York")

# Share quantization. Lane F uses CNAV $1.0000 so shares ~= USD notional.
# Lane D uses FNAV at 4dp — shares are quantized to 4 decimals too.
_SHARE_QUANTUM_F = Decimal("0.01")     # cents of a share on the fiat side
_SHARE_QUANTUM_D = Decimal("0.0001")   # 4dp, matches FNAV quantization

_CAOM_OPERATOR = "CAOM-001"

# ─── Module state ───────────────────────────────────────────────────────────
_lock = threading.RLock()
_dsor_log: list[DSORRecord] = []
_recent_hashes: dict[str, float] = {}   # hash -> first_seen_ts


# ─── Helpers ────────────────────────────────────────────────────────────────
def _stamp_dsor(event_type: str, payload: dict) -> DSORRecord:
    record = DSORRecord(
        record_id=f"DSOR-MMF-SUB-{uuid.uuid4().hex[:12]}",
        caom_mode="CAOM-001",
        operator=_CAOM_OPERATOR,
        timestamp=datetime.now(timezone.utc),
        event_type=event_type,
        payload=payload,
    )
    with _lock:
        _dsor_log.append(record)
    if _journal_sink is not None:
        try:
            _journal_sink({
                "record_id":  record.record_id,
                "event_type": event_type,
                "timestamp":  record.timestamp.isoformat(),
                "operator":   record.operator,
                "payload":    payload,
            })
        except Exception as e:
            log.warning("subscription_engine journal sink failed: %s: %s",
                        type(e).__name__, e)
    log.info("DSOR %s %s", event_type, record.record_id)
    return record


def get_dsor_log() -> list[DSORRecord]:
    with _lock:
        return list(_dsor_log)


def _idempotency_hash(investor_id: str, lane: str, amount: Decimal) -> str:
    """Hash includes a minute-bucket so same-second repeats collide but
    a retry one minute later is admitted as a new subscription."""
    bucket = int(time.time() / _IDEMPOTENCY_BUCKET_S)
    raw = f"{investor_id}:{lane}:{amount}:{bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _check_and_record_idempotency(h: str) -> bool:
    """Returns True if duplicate (caller should reject), False if new."""
    now = time.time()
    with _lock:
        # Opportunistic TTL cleanup.
        stale = [k for k, ts in _recent_hashes.items()
                 if (now - ts) >= _IDEMPOTENCY_WINDOW_S]
        for k in stale:
            del _recent_hashes[k]
        if h in _recent_hashes:
            return True
        _recent_hashes[h] = now
        return False


def _next_business_day_0900_et(now_utc: datetime) -> datetime:
    """Simulated T+1 settlement timestamp: tomorrow 09:00 ET. Phase 1
    ignores weekends and holidays per operator (Phase 3 brings the real
    business-day calendar). This is a display timestamp only — no actual
    wait is performed."""
    now_et = now_utc.astimezone(_ET)
    tomorrow_et = (now_et + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0,
    )
    return tomorrow_et.astimezone(timezone.utc)


# Test-only override hook for Prompt 6 break testing. Setting this to
# "HOLD" / "ESCALATE" / "PROCEED" forces _fetch_cato_gate() to return
# that decision without hitting the network. Set to None to restore
# normal fetch. Production callers never touch this — only the
# /api/mmf/_test/cato_override route does.
#
# Phase 2 P2-4 hardening: the override is ONLY honored when the env
# var AUREON_MMF_TEST_HOOKS_ENABLED is set to 1/true/yes. Otherwise
# set_test_cato_override is a no-op (with a warning log), and even
# if _TEST_CATO_OVERRIDE gets set by some other means, _fetch_cato_gate
# will ignore it. Defense in depth — the env flag is the single source
# of authorization for test-hook activation.
_TEST_CATO_OVERRIDE: Optional[str] = None


def _test_hooks_enabled() -> bool:
    """True iff AUREON_MMF_TEST_HOOKS_ENABLED is set to a truthy value.
    Read on every call so toggling in a running process is possible
    (used by tests; ops would just set the env var and redeploy)."""
    return os.environ.get("AUREON_MMF_TEST_HOOKS_ENABLED", "").strip().lower() in ("1", "true", "yes")


def set_test_cato_override(decision: Optional[str]) -> None:
    """Toggle the Cato gate test override. Break testing only.
    Passing None clears the override and restores normal fetch.

    No-op with a warning log when AUREON_MMF_TEST_HOOKS_ENABLED is
    not set (Phase 2 P2-4 production hardening)."""
    if not _test_hooks_enabled():
        log.warning(
            "set_test_cato_override called with decision=%r but "
            "AUREON_MMF_TEST_HOOKS_ENABLED is not set — no-op. Set "
            "AUREON_MMF_TEST_HOOKS_ENABLED=1 to enable test hooks.",
            decision,
        )
        return
    global _TEST_CATO_OVERRIDE
    _TEST_CATO_OVERRIDE = decision.upper() if decision else None
    log.info("set_test_cato_override: now=%s", _TEST_CATO_OVERRIDE)


def _fetch_cato_gate() -> dict:
    """Fetch the Cato gate decision from Railway. Returns a dict with
    `decision` ∈ {PROCEED, HOLD, ESCALATE, UNAVAILABLE} and
    `recommended_chain`. On any error the decision is UNAVAILABLE —
    subscription_engine treats that as HOLD (fail-closed for Lane D).

    Test override: if AUREON_MMF_TEST_HOOKS_ENABLED is set AND
    _TEST_CATO_OVERRIDE is populated, the override decision is
    returned without a network call. Both conditions must hold —
    the env flag gates honoring the override even if it was set by
    some other means."""
    if _test_hooks_enabled() and _TEST_CATO_OVERRIDE is not None:
        return {
            "decision":          _TEST_CATO_OVERRIDE,
            "recommended_chain": "simulated-test-override",
            "reasons":           [f"test override forcing {_TEST_CATO_OVERRIDE}"],
            "doctrine":          "TEST-OVERRIDE",
            "raw_ok":            True,
        }
    try:
        req = urllib.request.Request(CATO_GATE_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=CATO_GATE_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return {
            "decision":          (payload.get("gate_decision") or "UNAVAILABLE").upper(),
            "recommended_chain": payload.get("recommended_chain"),
            "reasons":           payload.get("reasons", []),
            "doctrine":          payload.get("doctrine"),
            "raw_ok":            True,
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        log.warning("Cato gate fetch failed: %s: %s", type(e).__name__, e)
    except Exception as e:
        log.warning("Cato gate unexpected error: %s: %s", type(e).__name__, e)
    return {
        "decision":          "UNAVAILABLE",
        "recommended_chain": None,
        "reasons":           ["fetch failed"],
        "doctrine":          None,
        "raw_ok":            False,
    }


# ─── Main entry point ───────────────────────────────────────────────────────
def process_subscription(investor_id: str, lane: str,
                         amount_usd) -> dict:
    """Process a subscription into Lane F (FIAT) or Lane D (Digital).

    Returns a result dict. Every path is DSOR-stamped — success, KYC
    exception, Cato hold, duplicate, validation failure. The caller
    (Railway route in Prompt 5) surfaces hitl_required=True to the
    operator UI for KYC / Cato paths.
    """
    # ── Input validation ──────────────────────────────────────────
    if not investor_id or not isinstance(investor_id, str):
        return {"status": "INVALID", "reason": "investor_id required"}
    if lane not in ("F", "D"):
        return {"status": "INVALID", "reason": f"lane must be F or D, got {lane!r}"}
    try:
        amount = Decimal(str(amount_usd))
    except Exception:
        return {"status": "INVALID", "reason": f"amount not a number: {amount_usd!r}"}
    if amount <= 0:
        return {"status": "INVALID", "reason": "amount_usd must be > 0"}

    # ── Idempotency check ─────────────────────────────────────────
    h = _idempotency_hash(investor_id, lane, amount)
    if _check_and_record_idempotency(h):
        rec = _stamp_dsor("SUBSCRIPTION_DUPLICATE_REJECTED", {
            "investor_id": investor_id,
            "lane":        lane,
            "amount_usd":  str(amount),
            "hash":        h,
            "window_s":    _IDEMPOTENCY_WINDOW_S,
        })
        return {
            "status":      "DUPLICATE",
            "reason":      f"same request within {_IDEMPOTENCY_WINDOW_S}s window",
            "investor_id": investor_id,
            "lane":        lane,
            "amount_usd":  str(amount),
            "dsor_id":     rec.record_id,
        }

    # ── KYC check (both lanes) ────────────────────────────────────
    if not fund_state.is_kyc_approved(investor_id):
        rec = _stamp_dsor("KYC_EXCEPTION_HITL_GATE_OPEN", {
            "investor_id": investor_id,
            "lane":        lane,
            "amount_usd":  str(amount),
            "reason":      "investor not on KYC allowlist",
            "opened_at":   datetime.now(timezone.utc).isoformat(),
        })
        return {
            "status":        "KYC_EXCEPTION",
            "reason":        "investor not on KYC allowlist",
            "hitl_required": True,
            "investor_id":   investor_id,
            "lane":          lane,
            "amount_usd":    str(amount),
            "event_id":      rec.record_id,
            "dsor_id":       rec.record_id,
        }

    # ── Lane-specific processing ──────────────────────────────────
    try:
        if lane == "F":
            return _process_fiat(investor_id, amount)
        return _process_digital(investor_id, amount)
    except ValueError as e:
        # fund_state enforces single-lane-per-investor discipline in
        # Phase 1; collision raises ValueError. Catch it here so API
        # callers get a clean status code instead of a 500.
        rec = _stamp_dsor("SUBSCRIPTION_REJECTED", {
            "investor_id": investor_id,
            "lane":        lane,
            "amount_usd":  str(amount),
            "reason":      str(e),
        })
        return {
            "status":      "REJECTED",
            "reason":      str(e),
            "investor_id": investor_id,
            "lane":        lane,
            "amount_usd":  str(amount),
            "dsor_id":     rec.record_id,
        }


# ─── Lane F — FIAT, T+1 simulated ───────────────────────────────────────────
def _process_fiat(investor_id: str, amount: Decimal) -> dict:
    nav_snapshot = nav_engine.get_nav_state()
    cnav = Decimal(nav_snapshot["cnav"])

    if cnav <= 0:
        rec = _stamp_dsor("FIAT_SUBSCRIPTION_REJECTED", {
            "investor_id": investor_id,
            "reason":      "CNAV is non-positive — NAV engine circuit?",
            "amount_usd":  str(amount),
        })
        return {"status": "REJECTED", "reason": "bad CNAV",
                "dsor_id": rec.record_id}

    # shares = amount_usd / cnav. With CNAV locked at 1.0000, shares == amount.
    shares = (amount / cnav).quantize(_SHARE_QUANTUM_F, rounding=ROUND_DOWN)

    fund_state.apply_subscription(investor_id, "F", amount, shares)

    now_utc = datetime.now(timezone.utc)
    settlement_at = _next_business_day_0900_et(now_utc)

    rec = _stamp_dsor("FIAT_SUBSCRIPTION_COMPLETE", {
        "investor_id":             investor_id,
        "lane":                    "F",
        "amount_usd":              str(amount),
        "shares":                  str(shares),
        "nav_used":                str(cnav),
        "nav_type":                "CNAV",
        "subscription_intent_at":  now_utc.isoformat(),
        "settlement_simulated_at": settlement_at.isoformat(),
        "settlement_model":        "T+1 (simulated; no wait performed)",
    })

    return {
        "status":                  "COMPLETE",
        "lane":                    "F",
        "investor_id":             investor_id,
        "amount_usd":              str(amount),
        "shares":                  str(shares),
        "nav_used":                str(cnav),
        "subscription_intent_at":  now_utc.isoformat(),
        "settlement_simulated_at": settlement_at.isoformat(),
        "dsor_id":                 rec.record_id,
    }


# ─── Lane D — Digital, REAL XRPL atomic DvP (Phase 2 P2-2) ─────────────────
def _process_digital(investor_id: str, amount: Decimal) -> dict:
    # Investor must have an XRPL wallet registered before Lane D.
    # Phase 2 P2-2 sandbox custody model — the fund manages the
    # investor's XRPL wallet via xrpl_integration.register_investor.
    # Import inside the function so subscription_engine remains
    # importable even if xrpl-py isn't installed yet (Phase 1
    # compatibility during the requirements.txt rollout).
    from aureon.mmf import xrpl_integration

    xrpl_addr = xrpl_integration.get_investor_xrpl_address(investor_id)
    if not xrpl_addr:
        rec = _stamp_dsor("DIGITAL_SUBSCRIPTION_REJECTED", {
            "investor_id": investor_id,
            "reason":      "no XRPL wallet — call POST /api/mmf/digital/register_investor first",
            "amount_usd":  str(amount),
            "lane":        "D",
        })
        return {
            "status":  "REJECTED",
            "reason":  "investor has no registered XRPL wallet",
            "investor_id": investor_id,
            "dsor_id": rec.record_id,
        }

    cato = _fetch_cato_gate()
    decision = cato["decision"]

    if decision in ("HOLD", "ESCALATE", "UNAVAILABLE"):
        rec = _stamp_dsor("CATO_HOLD_OPERATOR_DECISION", {
            "investor_id":       investor_id,
            "lane":              "D",
            "amount_usd":        str(amount),
            "cato_decision":     decision,
            "cato_chain":        cato["recommended_chain"],
            "cato_reasons":      cato["reasons"],
            "cato_doctrine":     cato["doctrine"],
            "opened_at":         datetime.now(timezone.utc).isoformat(),
        })
        return {
            "status":        "CATO_HOLD",
            "reason":        f"Cato gate {decision}",
            "hitl_required": True,
            "investor_id":   investor_id,
            "lane":          "D",
            "amount_usd":    str(amount),
            "cato_decision": decision,
            "cato_chain":    cato["recommended_chain"],
            "event_id":      rec.record_id,
            "dsor_id":       rec.record_id,
        }

    # PROCEED path.
    nav_snapshot = nav_engine.get_nav_state()
    fnav = Decimal(nav_snapshot["fnav"])

    if fnav <= 0:
        rec = _stamp_dsor("DIGITAL_SUBSCRIPTION_REJECTED", {
            "investor_id": investor_id,
            "reason":      "FNAV is non-positive — NAV engine circuit?",
            "amount_usd":  str(amount),
        })
        return {"status": "REJECTED", "reason": "bad FNAV",
                "dsor_id": rec.record_id}

    shares = (amount / fnav).quantize(_SHARE_QUANTUM_D, rounding=ROUND_DOWN)

    # Stamp the pre-atomic DSOR for audit lineage — if the XRPL
    # submission fails, we still have a record that the operator's
    # request was received and validated through to the atomic step.
    pre_rec = _stamp_dsor("DIGITAL_SUBSCRIPTION_DVP_SUBMITTED", {
        "investor_id":     investor_id,
        "lane":            "D",
        "amount_usd":      str(amount),
        "shares":          str(shares),
        "nav_used":        str(fnav),
        "nav_type":        "FNAV",
        "xrpl_address":    xrpl_addr,
        "cato_decision":   decision,
        "cato_chain":      cato["recommended_chain"],
        "submitted_at":    datetime.now(timezone.utc).isoformat(),
    })

    # Real atomic DvP on XRPL testnet. Blocks for ~15-25s typically.
    try:
        dvp = xrpl_integration.execute_subscription_dvp(
            investor_id=investor_id,
            amount_usd=amount,
            share_count=shares,
        )
    except Exception as e:
        log.exception("xrpl_integration raised: %s: %s",
                      type(e).__name__, e)
        rec = _stamp_dsor("DIGITAL_SUBSCRIPTION_REJECTED", {
            "investor_id":    investor_id,
            "lane":           "D",
            "amount_usd":     str(amount),
            "shares":         str(shares),
            "xrpl_address":   xrpl_addr,
            "reason":         "xrpl_integration raised",
            "error":          f"{type(e).__name__}: {str(e)[:240]}",
            "submitted_dsor": pre_rec.record_id,
        })
        return {
            "status":  "REJECTED",
            "reason":  f"XRPL submission error: {type(e).__name__}",
            "dsor_id": rec.record_id,
        }

    if dvp["status"] != "COMPLETE":
        rec = _stamp_dsor("DIGITAL_SUBSCRIPTION_REJECTED", {
            "investor_id":    investor_id,
            "lane":           "D",
            "amount_usd":     str(amount),
            "shares":         str(shares),
            "xrpl_address":   xrpl_addr,
            "reason":         dvp.get("status", "unknown"),
            "engine_result":  dvp.get("engine_result", ""),
            "dvp_detail":     dvp,
            "submitted_dsor": pre_rec.record_id,
        })
        return {
            "status":           "REJECTED",
            "reason":           f"atomic DvP {dvp.get('status')}",
            "engine_result":    dvp.get("engine_result", ""),
            "dvp_detail":       dvp,
            "dsor_id":          rec.record_id,
        }

    # tesSUCCESS path — commit to fund_state and stamp COMPLETE.
    fund_state.apply_subscription(investor_id, "D", amount, shares)

    now_utc = datetime.now(timezone.utc)

    rec = _stamp_dsor("DIGITAL_SUBSCRIPTION_COMPLETE", {
        "investor_id":           investor_id,
        "lane":                  "D",
        "amount_usd":            str(amount),
        "shares":                str(shares),
        "nav_used":              str(fnav),
        "nav_type":              "FNAV",
        "xrpl_address":          dvp["investor_address"],
        "share_issuer_address":  dvp["share_issuer_address"],
        "cash_issuer_address":   dvp["cash_issuer_address"],
        "pre_fund_tx_hash":      dvp["pre_fund_tx_hash"],
        "offer_tx_hash":         dvp["offer_tx_hash"],
        "payment_tx_hash":       dvp["payment_tx_hash"],
        "ledger_index":          dvp["ledger_index"],
        "ledger_close_time_utc": dvp["ledger_close_time_utc"],
        "engine_result":         dvp["engine_result"],
        "simulated":             False,   # Phase 2: REAL.
        "cato_decision":         decision,
        "cato_chain":            cato["recommended_chain"],
        "submitted_dsor":        pre_rec.record_id,
        "settled_at":            now_utc.isoformat(),
    })

    return {
        "status":                "COMPLETE",
        "lane":                  "D",
        "investor_id":           investor_id,
        "amount_usd":            str(amount),
        "shares":                str(shares),
        "nav_used":              str(fnav),
        "simulated":             False,
        "xrpl_address":          dvp["investor_address"],
        "pre_fund_tx_hash":      dvp["pre_fund_tx_hash"],
        "offer_tx_hash":         dvp["offer_tx_hash"],
        "payment_tx_hash":       dvp["payment_tx_hash"],
        "ledger_index":          dvp["ledger_index"],
        "ledger_close_time_utc": dvp["ledger_close_time_utc"],
        "cato_decision":         decision,
        "cato_chain":            cato["recommended_chain"],
        "dsor_id":               rec.record_id,
    }


# ─── Standalone smoke test ──────────────────────────────────────────────────
if __name__ == "__main__":
    import json as _json
    from dataclasses import asdict

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    print("=" * 72)
    print("AUREON MMF — subscription_engine smoke test (SYNTHETIC / SANDBOX)")
    print("=" * 72)

    # Bootstrap: ensure NAV is non-zero. Force a sweep if needed (calendar
    # day rule may return stale=True today; the test forces so we have a
    # valid FNAV to price Lane D against).
    if nav_engine.get_nav_state()["circuit_open"]:
        nav_engine.reset_circuit("smoke bootstrap")
    if nav_engine.get_nav_state()["sweep_count"] == 0:
        nav_engine.run_sweep(force_allow_stale=True)

    print("\nNAV after bootstrap:")
    print(_json.dumps(nav_engine.get_nav_state(), indent=2, default=str))

    # Two Lane F subs (INV-001, INV-002) + two Lane D subs (two different
    # amounts for INV-003 — we only have 3 KYC-approved investors in the
    # seed and single-lane discipline prevents INV-001 or INV-002 from
    # crossing into Lane D in Phase 1). Waits between D subs so the 60s
    # idempotency window doesn't collide.
    subs = [
        ("INV-001-ACME-FO",     "F", "5000.00"),
        ("INV-002-HORIZON-CAP", "F", "7500.00"),
        ("INV-003-MERIDIAN-PAR","D", "10000.00"),
        ("INV-003-MERIDIAN-PAR","D", "3500.00"),     # same investor, same lane, different amount
    ]

    for i, (iid, lane, amt) in enumerate(subs, 1):
        print(f"\n--- sub #{i}: {iid} lane={lane} amount={amt}")
        r = process_subscription(iid, lane, amt)
        print(_json.dumps(r, indent=2, default=str))

    print("\nFund state after all attempts:")
    print(_json.dumps(fund_state.get_state(), indent=2))

    print("\nDSOR log (all entries):")
    for rec in get_dsor_log():
        rec_dict = asdict(rec)
        rec_dict["timestamp"] = rec.timestamp.isoformat()
        print(_json.dumps(rec_dict, indent=2, default=str))

    print("=" * 72)
