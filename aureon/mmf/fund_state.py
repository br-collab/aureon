"""
Aureon MMF — Fund State (Phase 1, Sandbox)

PURPOSE:     Authoritative in-memory ledger of shares outstanding, AUM,
             and investor positions for the Arcadia Liquidity Fund
             sandbox. Two share classes: F (FIAT lane, CNAV) and D
             (Digital lane, FNAV). Exposes read snapshots and atomic
             apply/remove mutators used by subscription_engine and
             redemption_engine.

             Also binds an AUM-getter into nav_engine so NAV sweeps
             record the current AUM-by-lane in each DSOR entry.

INPUTS:      None direct — state is updated by sibling engines via
             apply_subscription() / apply_redemption().

OUTPUTS:     get_state()               -> dict snapshot for API / DSOR
             reset_daily_counters()    -> zeros the per-sweep redemption
                                           counters (nav_engine calls)
             weekly_liquid_asset_pct() -> Decimal; simulated 85% in
                                           Phase 1 per prompt

ASSUMPTIONS: In-memory only. A process restart clears all positions.
             Phase 1 does not persist fund_state; Phase 2 writes to
             aureon_state_persist.json. Investors dict is populated
             by subscription_engine on first subscription per
             investor_id.

AUDIT NOTES: Every mutator acquires the module RLock. Decimal math
             throughout. All figures SYNTHETIC / SANDBOX.
"""

from __future__ import annotations

import logging
import threading
from decimal import Decimal
from typing import Optional

from aureon.mmf import nav_engine

log = logging.getLogger("aureon.mmf.fund_state")

# ─── State (threading-locked) ───────────────────────────────────────────────
_state_lock = threading.RLock()

_state: dict = {
    "shares_f": Decimal("0"),                 # Class F shares outstanding
    "shares_d": Decimal("0"),                 # Class D shares outstanding
    "aum_f":    Decimal("0"),                 # Class F AUM in USD
    "aum_d":    Decimal("0"),                 # Class D AUM in USD
    "daily_redemptions_f": Decimal("0"),      # reset at each sweep
    "daily_redemptions_d": Decimal("0"),      # reset at each sweep
    "total_subscriptions": 0,
    "total_redemptions":   0,
    # investors: investor_id -> {"lane": "F"|"D", "shares": Decimal, "cost_basis": Decimal}
    # cost_basis is aggregate USD contributed (weighted average not tracked
    # in Phase 1; real funds compute WAC for tax lots — deferred).
    "investors": {},
}

# Simulated weekly liquid asset % — always 85% in Phase 1 per operator.
# Real funds compute this from portfolio holdings (T-bills maturing ≤60
# days, overnight repo, etc.). Phase 3+ will bring in the real calc.
_SIMULATED_WLA_PCT = Decimal("0.85")


# ─── Read ───────────────────────────────────────────────────────────────────
def get_state() -> dict:
    """Return a JSON-safe snapshot. Decimals stringified for transport."""
    with _state_lock:
        return {
            "shares_f": str(_state["shares_f"]),
            "shares_d": str(_state["shares_d"]),
            "aum_f":    str(_state["aum_f"]),
            "aum_d":    str(_state["aum_d"]),
            "aum_total": str(_state["aum_f"] + _state["aum_d"]),
            "daily_redemptions_f": str(_state["daily_redemptions_f"]),
            "daily_redemptions_d": str(_state["daily_redemptions_d"]),
            "total_subscriptions": _state["total_subscriptions"],
            "total_redemptions":   _state["total_redemptions"],
            "investor_count": len(_state["investors"]),
            "investors": {
                iid: {
                    "lane":       rec["lane"],
                    "shares":     str(rec["shares"]),
                    "cost_basis": str(rec["cost_basis"]),
                }
                for iid, rec in _state["investors"].items()
            },
        }


def get_investor(investor_id: str) -> Optional[dict]:
    """Return a single investor record as a Decimal-preserving dict,
    or None if not seen. Used by redemption_engine to resolve lane +
    share balance before processing a redemption."""
    with _state_lock:
        rec = _state["investors"].get(investor_id)
        if rec is None:
            return None
        return {
            "lane":       rec["lane"],
            "shares":     rec["shares"],
            "cost_basis": rec["cost_basis"],
        }


def weekly_liquid_asset_pct() -> Decimal:
    """Phase 1 simulation: always 0.85 (85%).

    Phase 3 will compute from actual portfolio composition. The return
    type is a Decimal fraction (0.85 == 85%), matching how redemption
    thresholds (e.g., 30% floor) are expressed."""
    return _SIMULATED_WLA_PCT


# ─── Mutators ───────────────────────────────────────────────────────────────
def apply_subscription(investor_id: str, lane: str, amount_usd: Decimal,
                       shares: Decimal) -> None:
    """Credit `shares` to the investor and increment AUM by `amount_usd`
    for the given lane. Creates the investor record on first touch.

    The caller (subscription_engine) is responsible for computing the
    share count against the correct NAV (CNAV for F, FNAV for D) and
    for KYC / Cato checks. This function assumes those gates have
    already passed — its job is atomic ledger update, nothing more."""
    if lane not in ("F", "D"):
        raise ValueError(f"unknown lane {lane!r}")
    with _state_lock:
        if lane == "F":
            _state["shares_f"] += shares
            _state["aum_f"]    += amount_usd
        else:
            _state["shares_d"] += shares
            _state["aum_d"]    += amount_usd
        rec = _state["investors"].get(investor_id)
        if rec is None:
            _state["investors"][investor_id] = {
                "lane":       lane,
                "shares":     shares,
                "cost_basis": amount_usd,
            }
        else:
            # Existing investor — enforce single-lane discipline in Phase 1.
            # A real fund may allow an investor to hold both classes; the
            # prompt's simulator keeps each investor on a single lane.
            if rec["lane"] != lane:
                raise ValueError(
                    f"investor {investor_id} already holds {rec['lane']}-class "
                    f"shares; cannot mix with {lane}-class in Phase 1"
                )
            rec["shares"]     += shares
            rec["cost_basis"] += amount_usd
        _state["total_subscriptions"] += 1


def apply_redemption(investor_id: str, shares_removed: Decimal,
                     gross_payout_usd: Decimal) -> None:
    """Debit `shares_removed` from the investor and reduce AUM by
    `gross_payout_usd`. Increments the lane's daily redemption counter
    (used by redemption_engine's liquidity-fee threshold check)."""
    with _state_lock:
        rec = _state["investors"].get(investor_id)
        if rec is None:
            raise ValueError(f"unknown investor {investor_id!r}")
        if shares_removed > rec["shares"]:
            raise ValueError(
                f"investor {investor_id} holds {rec['shares']} shares; "
                f"cannot redeem {shares_removed}"
            )
        lane = rec["lane"]
        rec["shares"]     -= shares_removed
        # Proportional cost-basis reduction (matches shares-redeemed ratio).
        # A real fund would track per-lot basis for tax purposes; Phase 1
        # uses aggregate pro-rata which is close enough for yield display.
        if rec["shares"] + shares_removed > 0:
            ratio = shares_removed / (rec["shares"] + shares_removed)
            rec["cost_basis"] -= rec["cost_basis"] * ratio
        if rec["shares"] == 0:
            rec["cost_basis"] = Decimal("0")

        if lane == "F":
            _state["shares_f"] -= shares_removed
            _state["aum_f"]    -= gross_payout_usd
            _state["daily_redemptions_f"] += gross_payout_usd
        else:
            _state["shares_d"] -= shares_removed
            _state["aum_d"]    -= gross_payout_usd
            _state["daily_redemptions_d"] += gross_payout_usd
        _state["total_redemptions"] += 1


def reset_daily_counters() -> None:
    """Zero the per-sweep redemption counters. nav_engine.run_sweep()
    calls this at the end of a successful sweep so the next 24h
    liquidity-fee threshold window starts clean."""
    with _state_lock:
        _state["daily_redemptions_f"] = Decimal("0")
        _state["daily_redemptions_d"] = Decimal("0")


# ─── Bind AUM getter into nav_engine ────────────────────────────────────────
def _aum_getter() -> dict:
    with _state_lock:
        return {
            "aum_f": _state["aum_f"],
            "aum_d": _state["aum_d"],
        }


nav_engine.bind_fund_state(_aum_getter)


# ─── KYC allowlist (Phase 1 seed) ───────────────────────────────────────────
# A real fund runs KYC / AML / sanctions-screening workflows upstream and
# materializes an approved-investors list. Phase 1 hardcodes three seeded
# investors for subscription_engine to check against. Subscription from
# an unlisted investor returns KYC_EXCEPTION (HITL gate opens).
KYC_ALLOWLIST: frozenset[str] = frozenset({
    "INV-001-ACME-FO",        # ACME Family Office
    "INV-002-HORIZON-CAP",    # Horizon Capital
    "INV-003-MERIDIAN-PAR",   # Meridian Partners
})


def is_kyc_approved(investor_id: str) -> bool:
    """Phase 1 KYC check — allowlist membership. No lane-specific rules."""
    return investor_id in KYC_ALLOWLIST


# ─── Standalone smoke test ──────────────────────────────────────────────────
if __name__ == "__main__":
    import json as _json
    print("=" * 72)
    print("AUREON MMF — fund_state smoke test (SYNTHETIC / SANDBOX)")
    print("=" * 72)
    print("\nInitial state:")
    print(_json.dumps(get_state(), indent=2))
    print("\nKYC allowlist (Phase 1 seed):")
    for iid in sorted(KYC_ALLOWLIST):
        print(f"  {iid}")
    print(f"\nweekly_liquid_asset_pct() = {weekly_liquid_asset_pct()}")
    print("=" * 72)
