"""
Aureon MMF — Redemption Engine (Phase 1, Sandbox)

PURPOSE:     Process redemptions from Arcadia Liquidity Fund. Mirrors
             subscription discipline but inverts the flow:

               Lane F → USD payout,  priced against CNAV ($1.0000)
               Lane D → USDC payout, priced against FNAV (4dp)

             Lane is determined by the investor's subscription record;
             there is no redemption-currency override (Prompt 6 BREAK 6
             validates this — "Lane F always redeems USD").

             Applies the liquidity-fee discipline when daily redemptions
             cross 5% of lane AUM. De minimis exemption zeros the fee
             when it would be under 1bp of gross payout.

             Checks the weekly liquid-asset (WLA) floor after every
             redemption and emits LIQUIDITY_BUFFER_WARNING if under
             30%. Phase 1 WLA is hardcoded 0.85 so the warning is
             dormant; Phase 3+ brings the real portfolio calc.

             Every path emits a DSOR. Event types:
               FIAT_REDEMPTION_COMPLETE
               DIGITAL_REDEMPTION_COMPLETE (flagged SIMULATED)
               REDEMPTION_REJECTED
               LIQUIDITY_FEE_APPLIED
               LIQUIDITY_BUFFER_WARNING

INPUTS:      process_redemption(investor_id, shares_to_redeem).

OUTPUTS:     dict with status, shares_redeemed, gross_payout,
             fee_amount, net_payout, currency, lane, nav_used,
             liquidity_fee_applied (bool), dsor_id.

ASSUMPTIONS: Lane F always pays USD. Lane D always pays USDC (Phase 1
             is simulated — no real USDC transfer). Investor lane is
             locked at first subscription per fund_state's single-lane
             discipline.

AUDIT NOTES: Liquidity fee threshold uses pre-redemption AUM as the
             denominator — the industry standard is fund NAV at the
             time of redemption, which we represent as the lane AUM
             immediately before the mutation. All figures SYNTHETIC.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from aureon.agents.base import DSORRecord
from aureon.mmf import fund_state, nav_engine

log = logging.getLogger("aureon.mmf.redemption_engine")

# ─── Constants ──────────────────────────────────────────────────────────────
LIQUIDITY_FEE_THRESHOLD_PCT  = Decimal("0.05")   # 5% daily net redemptions of lane AUM
LIQUIDITY_FEE_BPS            = Decimal("10")     # 10bps fee when threshold breached
LIQUIDITY_FEE_DE_MINIMIS_BPS = Decimal("1")      # Under 1bp → zero fee (de minimis)
WEEKLY_LIQUID_ASSET_FLOOR_PCT = Decimal("0.30")  # 30% floor — warning threshold

_PAYOUT_QUANTUM = Decimal("0.01")   # cents — USD and simulated USDC both at 2dp

_CAOM_OPERATOR = "CAOM-001"

# ─── Module state ───────────────────────────────────────────────────────────
_dsor_log: list[DSORRecord] = []


# ─── Helpers ────────────────────────────────────────────────────────────────
def _stamp_dsor(event_type: str, payload: dict) -> DSORRecord:
    record = DSORRecord(
        record_id=f"DSOR-MMF-RED-{uuid.uuid4().hex[:12]}",
        caom_mode="CAOM-001",
        operator=_CAOM_OPERATOR,
        timestamp=datetime.now(timezone.utc),
        event_type=event_type,
        payload=payload,
    )
    _dsor_log.append(record)
    log.info("DSOR %s %s", event_type, record.record_id)
    return record


def get_dsor_log() -> list[DSORRecord]:
    return list(_dsor_log)


def _pre_redemption_lane_aum(lane: str) -> Decimal:
    """Return the lane's current AUM from fund_state. Called before the
    redemption mutation so the liquidity-fee denominator is the NAV at
    the moment of redemption, not after the mutation drops it."""
    state = fund_state.get_state()
    return Decimal(state["aum_f"] if lane == "F" else state["aum_d"])


def _pre_redemption_lane_daily_redemptions(lane: str) -> Decimal:
    state = fund_state.get_state()
    return Decimal(state["daily_redemptions_f"] if lane == "F"
                   else state["daily_redemptions_d"])


# ─── Main entry point ───────────────────────────────────────────────────────
def process_redemption(investor_id: str, shares_to_redeem) -> dict:
    """Redeem `shares_to_redeem` from investor_id. Lane and payout
    currency are derived from the investor's record — no override."""
    # ── Validation ──────────────────────────────────────────────
    if not investor_id:
        return {"status": "INVALID", "reason": "investor_id required"}
    try:
        shares = Decimal(str(shares_to_redeem))
    except Exception:
        return {"status": "INVALID", "reason": f"shares not a number: {shares_to_redeem!r}"}
    if shares <= 0:
        return {"status": "INVALID", "reason": "shares_to_redeem must be > 0"}

    investor = fund_state.get_investor(investor_id)
    if investor is None:
        rec = _stamp_dsor("REDEMPTION_REJECTED", {
            "investor_id": investor_id,
            "reason":      "investor unknown",
            "shares_requested": str(shares),
        })
        return {"status": "REJECTED", "reason": "investor unknown",
                "dsor_id": rec.record_id}

    if shares > investor["shares"]:
        rec = _stamp_dsor("REDEMPTION_REJECTED", {
            "investor_id":      investor_id,
            "reason":           "insufficient shares",
            "shares_requested": str(shares),
            "shares_held":      str(investor["shares"]),
        })
        return {"status": "REJECTED", "reason": "insufficient shares",
                "dsor_id": rec.record_id}

    lane = investor["lane"]
    currency = "USD" if lane == "F" else "USDC"

    # ── NAV + payout ────────────────────────────────────────────
    nav_snapshot = nav_engine.get_nav_state()
    nav = Decimal(nav_snapshot["cnav"] if lane == "F" else nav_snapshot["fnav"])

    if nav <= 0:
        rec = _stamp_dsor("REDEMPTION_REJECTED", {
            "investor_id": investor_id,
            "reason":      "NAV non-positive — NAV engine circuit?",
            "lane":        lane,
        })
        return {"status": "REJECTED", "reason": "bad NAV",
                "dsor_id": rec.record_id}

    gross_payout = (shares * nav).quantize(_PAYOUT_QUANTUM, rounding=ROUND_DOWN)

    # ── Liquidity fee check ─────────────────────────────────────
    # Denominator is the lane AUM at time of redemption (pre-mutation).
    # Numerator is cumulative daily redemptions today + the current gross.
    aum_lane = _pre_redemption_lane_aum(lane)
    daily_pre = _pre_redemption_lane_daily_redemptions(lane)
    fee_amount = Decimal("0")
    liquidity_fee_applied = False

    if aum_lane > 0:
        projected_pct = (daily_pre + gross_payout) / aum_lane
        if projected_pct > LIQUIDITY_FEE_THRESHOLD_PCT:
            raw_fee = gross_payout * (LIQUIDITY_FEE_BPS / Decimal("10000"))
            de_minimis_floor = gross_payout * (LIQUIDITY_FEE_DE_MINIMIS_BPS / Decimal("10000"))
            if raw_fee < de_minimis_floor:
                # De minimis exemption: fee is below 1bp, waive.
                _stamp_dsor("LIQUIDITY_FEE_APPLIED", {
                    "investor_id":   investor_id,
                    "lane":          lane,
                    "gross_payout":  str(gross_payout),
                    "projected_pct": str(projected_pct),
                    "threshold_pct": str(LIQUIDITY_FEE_THRESHOLD_PCT),
                    "fee_bps":       str(LIQUIDITY_FEE_BPS),
                    "raw_fee":       str(raw_fee),
                    "fee_amount":    "0",
                    "de_minimis_exemption": True,
                })
            else:
                fee_amount = raw_fee.quantize(_PAYOUT_QUANTUM, rounding=ROUND_DOWN)
                liquidity_fee_applied = True
                _stamp_dsor("LIQUIDITY_FEE_APPLIED", {
                    "investor_id":   investor_id,
                    "lane":          lane,
                    "gross_payout":  str(gross_payout),
                    "projected_pct": str(projected_pct),
                    "threshold_pct": str(LIQUIDITY_FEE_THRESHOLD_PCT),
                    "fee_bps":       str(LIQUIDITY_FEE_BPS),
                    "fee_amount":    str(fee_amount),
                    "de_minimis_exemption": False,
                })

    net_payout = gross_payout - fee_amount

    # ── Apply to fund_state ─────────────────────────────────────
    # apply_redemption debits shares, reduces lane AUM by gross_payout,
    # increments daily_redemptions_lane, increments total_redemptions.
    fund_state.apply_redemption(investor_id, shares, gross_payout)

    # ── Weekly liquid asset floor check ─────────────────────────
    # Phase 1 simulated 0.85; warning path dormant but the check runs
    # and logs on breach. The check happens AFTER the redemption so
    # the post-redemption fund composition is what's evaluated.
    wla = fund_state.weekly_liquid_asset_pct()
    if wla < WEEKLY_LIQUID_ASSET_FLOOR_PCT:
        _stamp_dsor("LIQUIDITY_BUFFER_WARNING", {
            "investor_id": investor_id,
            "lane":        lane,
            "wla_pct":     str(wla),
            "floor_pct":   str(WEEKLY_LIQUID_ASSET_FLOOR_PCT),
            "trigger":     "post-redemption",
        })

    # ── Emit redemption DSOR ────────────────────────────────────
    now_utc = datetime.now(timezone.utc)

    if lane == "F":
        event_type = "FIAT_REDEMPTION_COMPLETE"
        payload_extras: dict = {}
    else:
        event_type = "DIGITAL_REDEMPTION_COMPLETE"
        payload_extras = {
            "simulated": True,
            "settlement_model": "atomic DvP (simulated, no USDC transfer performed)",
        }

    rec = _stamp_dsor(event_type, {
        "investor_id":           investor_id,
        "lane":                  lane,
        "shares_redeemed":       str(shares),
        "nav_used":              str(nav),
        "nav_type":              "CNAV" if lane == "F" else "FNAV",
        "gross_payout":          str(gross_payout),
        "fee_amount":            str(fee_amount),
        "net_payout":            str(net_payout),
        "currency":              currency,
        "liquidity_fee_applied": liquidity_fee_applied,
        "redemption_at":         now_utc.isoformat(),
        **payload_extras,
    })

    return {
        "status":                "COMPLETE",
        "lane":                  lane,
        "investor_id":           investor_id,
        "shares_redeemed":       str(shares),
        "gross_payout":          str(gross_payout),
        "fee_amount":            str(fee_amount),
        "net_payout":            str(net_payout),
        "currency":              currency,
        "nav_used":              str(nav),
        "liquidity_fee_applied": liquidity_fee_applied,
        "dsor_id":                rec.record_id,
    }


# ─── Standalone smoke test ──────────────────────────────────────────────────
if __name__ == "__main__":
    import json as _json
    import logging as _logging
    from dataclasses import asdict

    from aureon.mmf import subscription_engine

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    print("=" * 72)
    print("AUREON MMF — redemption_engine smoke test (SYNTHETIC / SANDBOX)")
    print("=" * 72)

    # Bootstrap NAV so CNAV/FNAV are valid.
    if nav_engine.get_nav_state()["circuit_open"]:
        nav_engine.reset_circuit("smoke bootstrap")
    if nav_engine.get_nav_state()["sweep_count"] == 0:
        nav_engine.run_sweep(force_allow_stale=True)

    # Seed two Lane F subscriptions. Smaller + larger so the second
    # redemption will cross the 5% threshold.
    print("\n--- seed subs ---")
    s1 = subscription_engine.process_subscription("INV-001-ACME-FO",     "F", "500.00")
    s2 = subscription_engine.process_subscription("INV-002-HORIZON-CAP", "F", "10000.00")
    for lbl, r in [("sub s1", s1), ("sub s2", s2)]:
        print(f"{lbl}: status={r['status']} shares={r.get('shares')}")

    print("\nFund state after subs:")
    print(_json.dumps(fund_state.get_state(), indent=2))

    # Redemption #1 — small; no fee expected.
    print("\n--- redemption #1: INV-001 full $500 (no fee expected) ---")
    r1 = process_redemption("INV-001-ACME-FO", Decimal("500.00"))
    print(_json.dumps(r1, indent=2, default=str))

    # Redemption #2 — large; should trigger liquidity fee.
    print("\n--- redemption #2: INV-002 full $10,000 (fee expected) ---")
    r2 = process_redemption("INV-002-HORIZON-CAP", Decimal("10000.00"))
    print(_json.dumps(r2, indent=2, default=str))

    print("\nFund state after redemptions:")
    print(_json.dumps(fund_state.get_state(), indent=2))

    print("\nDSOR log (redemption_engine only, chronological):")
    for rec in get_dsor_log():
        rec_dict = asdict(rec)
        rec_dict["timestamp"] = rec.timestamp.isoformat()
        print(_json.dumps(rec_dict, indent=2, default=str))

    print("=" * 72)
