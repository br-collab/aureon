"""
Aureon MMF — XRPL Integration (Phase 2 P2-2)

PURPOSE:     Real atomic Delivery-versus-Payment (DvP) on XRPL testnet.
             Replaces the Phase 1 Lane D 8-second simulation with
             actual on-chain settlement. Mechanics ported from
             ~/sam/builds/tokenized_mmf_xrpl_leg/dvp_swap_permissioned.py:
             asfRequireAuth + TF_SET_AUTH + resting OfferCreate +
             consuming cross-currency Payment with SendMax +
             tfLimitQuality.

DOCTRINE:    - Testnet ONLY. Endpoint pinned; mainnet hosts blocked
               at module load via assertion.
             - Sandbox custody model: the fund auto-generates investor
               XRPL wallets on registration and holds their seeds in
               the Railway volume. This is a SANDBOX SHORTCUT; real
               tokenization has investors hold their own keys and
               submit signed txs via wallet-connect / signed-tx APIs.
               Phase 3+ replaces this with investor-side custody.
             - HITL gate remains in subscription_engine — the
               atomic Payment only submits on an operator-approved
               subscription path. This module doesn't decide; it
               executes.

INPUTS:      - `RAILWAY_VOLUME_MOUNT_PATH` (from env) for wallet
               state persistence. Falls back to ~/.aureon/ locally.
             - No secret env vars required — ShareIssuer / CashIssuer
               wallets are auto-created on first call and persisted.

OUTPUTS:     register_investor(investor_id) ->
                 {status, xrpl_address, setup_tx_hashes: list}
             execute_subscription_dvp(investor_id, amount_usd,
                                      share_count) ->
                 {status, investor_address, share_issuer_address,
                  cash_issuer_address, pre_fund_tx_hash,
                  offer_tx_hash, payment_tx_hash, ledger_index,
                  ledger_close_time_utc, engine_result}

ASSUMPTIONS: XRPL testnet is reachable via altnet.rippletest.net.
             Faucet funding works (free test XRP for wallet setup).
             xrpl-py 4.5.0+ installed. asfRequireAuth active on
             testnet (baseline; no amendment dependency in practice).

AUDIT NOTES: Every XRPL tx hash, ledger index, and ledger close
             time is returned to the caller for DSOR stamping.
             Subscription Lane D emits DIGITAL_SUBSCRIPTION_COMPLETE
             with these fields (previously they were placeholder
             simulated stamps). Persisted wallet state is the only
             durable record of which investors have been registered
             under the fund.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet, generate_faucet_wallet
from xrpl.models.transactions import (
    AccountSet,
    AccountSetAsfFlag,
    OfferCreate,
    Payment,
    PaymentFlag,
    TrustSet,
    TrustSetFlag,
)
from xrpl.models.requests import AccountLines
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.transaction import submit_and_wait

log = logging.getLogger("aureon.mmf.xrpl_integration")

# ─── Doctrine rails ─────────────────────────────────────────────────────────
TESTNET_RPC = "https://s.altnet.rippletest.net:51234"
MAINNET_HOSTS_BLOCK = ("xrplcluster.com", "s1.ripple.com", "s2.ripple.com")

# Startup assertion — this module only connects to testnet.
assert "altnet" in TESTNET_RPC, "XRPL integration must point at testnet"
for _blocked in MAINNET_HOSTS_BLOCK:
    assert _blocked not in TESTNET_RPC, f"refuses mainnet host {_blocked}"

SHARE_CURRENCY = "MMF"
CASH_CURRENCY = "USD"
TRUST_LIMIT = "10000000"            # operational headroom on trust lines
PIE_SHARE_ISSUER_LABEL = "Arcadia Liquidity Fund — Share Issuer (SANDBOX)"
PIE_CASH_ISSUER_LABEL  = "Arcadia Liquidity Fund — Cash Issuer (SANDBOX)"


# ─── Persistence ────────────────────────────────────────────────────────────
def _wallets_file() -> Path:
    vol = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    base = Path(vol) if vol else (Path.home() / ".aureon")
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.warning("xrpl wallets dir %s: %s: %s",
                    base, type(e).__name__, e)
    return base / "aureon_mmf_xrpl_wallets.json"


_state_lock = threading.RLock()
_state: dict = {
    "share_issuer_seed":     None,     # str | None
    "cash_issuer_seed":      None,     # str | None
    "share_issuer_address":  None,
    "cash_issuer_address":   None,
    "fund_setup_complete":   False,    # asfDefaultRipple + asfRequireAuth + mutual trust line done
    "investors": {},  # investor_id -> {"xrpl_address", "seed", "setup_complete", "setup_tx_hashes"}
}


def _load_state() -> None:
    """Load wallet state from the volume if present."""
    path = _wallets_file()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
        with _state_lock:
            _state.update(data)
    except Exception as e:
        log.warning("xrpl_integration: load_state failed: %s: %s",
                    type(e).__name__, e)


def _save_state() -> None:
    """Atomic save — tempfile + os.replace."""
    path = _wallets_file()
    tmp = path.with_suffix(".tmp")
    try:
        with _state_lock:
            snap = json.dumps(_state, indent=2)
        tmp.write_text(snap)
        os.replace(tmp, path)
    except Exception as e:
        log.warning("xrpl_integration: save_state failed: %s: %s",
                    type(e).__name__, e)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


# Hydrate at module load.
_load_state()


# ─── XRPL primitives ────────────────────────────────────────────────────────
_client: Optional[JsonRpcClient] = None


def _get_client() -> JsonRpcClient:
    global _client
    if _client is None:
        _client = JsonRpcClient(TESTNET_RPC)
    return _client


def _submit(label: str, tx: Any, signer: Wallet) -> dict:
    """Submit and wait. Returns a dict with tx_hash, ledger_index,
    ledger_close_time_utc, engine_result, wall_seconds. On exception,
    engine_result=SUBMIT_EXCEPTION and error is recorded."""
    import time as _t
    client = _get_client()
    t0 = _t.time()
    started_at = datetime.now(timezone.utc).isoformat()
    log.info("xrpl submit %s (signer=%s)", label, signer.classic_address)
    try:
        result = submit_and_wait(tx, client, signer)
    except Exception as e:
        wall = round(_t.time() - t0, 3)
        log.warning("xrpl submit %s failed: %s: %s",
                    label, type(e).__name__, e)
        return {
            "label":                label,
            "tx_hash":              "",
            "ledger_index":         0,
            "ledger_close_time_utc": "",
            "engine_result":        "SUBMIT_EXCEPTION",
            "error":                f"{type(e).__name__}: {str(e)[:200]}",
            "wall_seconds":         wall,
            "started_at":           started_at,
        }
    wall = round(_t.time() - t0, 3)
    r = result.result if hasattr(result, "result") else {}
    tx_hash = r.get("hash") or (r.get("tx_json") or {}).get("hash") or ""
    ledger_index = r.get("ledger_index") or 0
    close_raw = (
        r.get("close_time_iso")
        or r.get("date")
        or (r.get("tx_json") or {}).get("date")
    )
    if isinstance(close_raw, int):
        # XRPL Ripple epoch offset (2000-01-01T00:00:00Z Unix = 946684800).
        close_iso = datetime.fromtimestamp(
            close_raw + 946684800, timezone.utc,
        ).isoformat()
    elif isinstance(close_raw, str):
        close_iso = close_raw
    else:
        close_iso = ""
    engine_result = (
        r.get("engine_result")
        or (r.get("meta") or {}).get("TransactionResult")
        or ""
    )
    return {
        "label":                 label,
        "tx_hash":               tx_hash,
        "ledger_index":          ledger_index,
        "ledger_close_time_utc": close_iso,
        "engine_result":         engine_result,
        "error":                 "",
        "wall_seconds":          wall,
        "started_at":            started_at,
    }


# ─── Fund-level setup (ShareIssuer + CashIssuer) ────────────────────────────
def _ensure_fund_initialized() -> dict:
    """Idempotent fund-level XRPL setup: ShareIssuer + CashIssuer
    wallets exist (faucet-funded), both have asfDefaultRipple set,
    ShareIssuer has asfRequireAuth, and ShareIssuer holds a USD trust
    line to CashIssuer so it can receive the cash leg of DvPs.

    Safe to call on every subscription — subsequent calls are no-ops
    once _state['fund_setup_complete'] is True.

    Returns: {status, share_issuer_address, cash_issuer_address,
              setup_tx_hashes: list}. `setup_tx_hashes` is non-empty
              only on the setup run."""
    with _state_lock:
        if _state["fund_setup_complete"]:
            return {
                "status":                "ALREADY_INITIALIZED",
                "share_issuer_address":  _state["share_issuer_address"],
                "cash_issuer_address":   _state["cash_issuer_address"],
                "setup_tx_hashes":       [],
            }

    client = _get_client()
    setup_hashes: list[str] = []

    # 1-2. Create or resume ShareIssuer + CashIssuer wallets.
    with _state_lock:
        existing_share_seed = _state["share_issuer_seed"]
        existing_cash_seed  = _state["cash_issuer_seed"]

    if existing_share_seed:
        share_issuer = Wallet.from_seed(existing_share_seed)
    else:
        log.info("xrpl: creating ShareIssuer wallet via faucet...")
        share_issuer = generate_faucet_wallet(client, debug=False)
        with _state_lock:
            _state["share_issuer_seed"]    = share_issuer.seed
            _state["share_issuer_address"] = share_issuer.classic_address
        _save_state()

    if existing_cash_seed:
        cash_issuer = Wallet.from_seed(existing_cash_seed)
    else:
        log.info("xrpl: creating CashIssuer wallet via faucet...")
        cash_issuer = generate_faucet_wallet(client, debug=False)
        with _state_lock:
            _state["cash_issuer_seed"]    = cash_issuer.seed
            _state["cash_issuer_address"] = cash_issuer.classic_address
        _save_state()

    # 3. ShareIssuer: asfDefaultRipple so MMF balances can route.
    step = _submit(
        "ShareIssuer AccountSet (enable DefaultRipple)",
        AccountSet(
            account=share_issuer.classic_address,
            set_flag=AccountSetAsfFlag.ASF_DEFAULT_RIPPLE,
        ),
        share_issuer,
    )
    if step["engine_result"] != "tesSUCCESS":
        return {"status": "SETUP_FAILED", "step": step}
    setup_hashes.append(step["tx_hash"])

    # 4. ShareIssuer: asfRequireAuth. Must precede any trust line on this account.
    step = _submit(
        "ShareIssuer AccountSet (enable RequireAuth)",
        AccountSet(
            account=share_issuer.classic_address,
            set_flag=AccountSetAsfFlag.ASF_REQUIRE_AUTH,
        ),
        share_issuer,
    )
    if step["engine_result"] != "tesSUCCESS":
        return {"status": "SETUP_FAILED", "step": step}
    setup_hashes.append(step["tx_hash"])

    # 5. CashIssuer: asfDefaultRipple so USD balances can route.
    step = _submit(
        "CashIssuer AccountSet (enable DefaultRipple)",
        AccountSet(
            account=cash_issuer.classic_address,
            set_flag=AccountSetAsfFlag.ASF_DEFAULT_RIPPLE,
        ),
        cash_issuer,
    )
    if step["engine_result"] != "tesSUCCESS":
        return {"status": "SETUP_FAILED", "step": step}
    setup_hashes.append(step["tx_hash"])

    # 6. ShareIssuer opens USD trust line to CashIssuer so it can
    #    receive the cash leg of DvPs. RequireAuth on ShareIssuer
    #    does not affect its ability to hold other issuers' IOUs.
    step = _submit(
        f"ShareIssuer TrustSet (hold {CASH_CURRENCY} from CashIssuer)",
        TrustSet(
            account=share_issuer.classic_address,
            limit_amount=IssuedCurrencyAmount(
                currency=CASH_CURRENCY,
                issuer=cash_issuer.classic_address,
                value=TRUST_LIMIT,
            ),
        ),
        share_issuer,
    )
    if step["engine_result"] != "tesSUCCESS":
        return {"status": "SETUP_FAILED", "step": step}
    setup_hashes.append(step["tx_hash"])

    with _state_lock:
        _state["fund_setup_complete"] = True
    _save_state()

    return {
        "status":                "INITIALIZED",
        "share_issuer_address":  share_issuer.classic_address,
        "cash_issuer_address":   cash_issuer.classic_address,
        "setup_tx_hashes":       setup_hashes,
    }


def _get_fund_wallets() -> tuple[Wallet, Wallet]:
    """Return (share_issuer, cash_issuer) Wallet objects. Assumes
    _ensure_fund_initialized has run."""
    with _state_lock:
        share_seed = _state["share_issuer_seed"]
        cash_seed  = _state["cash_issuer_seed"]
    if not share_seed or not cash_seed:
        raise RuntimeError("fund wallets not initialized")
    return Wallet.from_seed(share_seed), Wallet.from_seed(cash_seed)


# ─── Investor registration ──────────────────────────────────────────────────
def register_investor(investor_id: str) -> dict:
    """Register a new investor for Lane D atomic DvP. Runs fund
    initialization if not done, then per-investor setup:

      - Generate a faucet-funded XRPL wallet for the investor
        (sandbox custody model).
      - Investor opens MMF trust line to ShareIssuer (unauthorized).
      - ShareIssuer flips TF_SET_AUTH on the investor's MMF line.
      - Investor opens USD trust line to CashIssuer.

    Idempotent: if the investor already has a complete setup,
    returns the existing state.

    Blocks for ~30-60s on first run (fund setup + investor setup).
    ~15-25s if fund is already initialized.
    """
    if not investor_id:
        return {"status": "INVALID", "reason": "investor_id required"}

    with _state_lock:
        existing = _state["investors"].get(investor_id)
    if existing and existing.get("setup_complete"):
        return {
            "status":           "ALREADY_REGISTERED",
            "investor_id":      investor_id,
            "xrpl_address":     existing["xrpl_address"],
            "setup_tx_hashes":  existing.get("setup_tx_hashes", []),
        }

    fund_init = _ensure_fund_initialized()
    if fund_init["status"] == "SETUP_FAILED":
        return {"status": "FUND_SETUP_FAILED", "detail": fund_init}

    share_issuer, cash_issuer = _get_fund_wallets()
    client = _get_client()

    # Faucet-fund a new investor wallet (sandbox custody).
    log.info("xrpl: creating investor wallet for %s via faucet...", investor_id)
    investor = generate_faucet_wallet(client, debug=False)
    setup_hashes: list[str] = []

    # Investor opens MMF trust line to ShareIssuer (unauthorized until next step).
    step = _submit(
        f"Investor[{investor_id}] TrustSet (hold {SHARE_CURRENCY} from ShareIssuer)",
        TrustSet(
            account=investor.classic_address,
            limit_amount=IssuedCurrencyAmount(
                currency=SHARE_CURRENCY,
                issuer=share_issuer.classic_address,
                value=TRUST_LIMIT,
            ),
        ),
        investor,
    )
    if step["engine_result"] != "tesSUCCESS":
        return {"status": "INVESTOR_SETUP_FAILED", "step": step}
    setup_hashes.append(step["tx_hash"])

    # ShareIssuer authorizes the investor's MMF line — the on-ledger
    # KYC-admission flip. Without this, DvP Payment will fail with
    # tecNO_AUTH.
    step = _submit(
        f"ShareIssuer TrustSet (authorize Investor[{investor_id}] {SHARE_CURRENCY} line)",
        TrustSet(
            account=share_issuer.classic_address,
            limit_amount=IssuedCurrencyAmount(
                currency=SHARE_CURRENCY,
                issuer=investor.classic_address,
                value="0",
            ),
            flags=TrustSetFlag.TF_SET_AUTH,
        ),
        share_issuer,
    )
    if step["engine_result"] != "tesSUCCESS":
        return {"status": "INVESTOR_SETUP_FAILED", "step": step}
    setup_hashes.append(step["tx_hash"])

    # Investor opens USD trust line to CashIssuer.
    step = _submit(
        f"Investor[{investor_id}] TrustSet (hold {CASH_CURRENCY} from CashIssuer)",
        TrustSet(
            account=investor.classic_address,
            limit_amount=IssuedCurrencyAmount(
                currency=CASH_CURRENCY,
                issuer=cash_issuer.classic_address,
                value=TRUST_LIMIT,
            ),
        ),
        investor,
    )
    if step["engine_result"] != "tesSUCCESS":
        return {"status": "INVESTOR_SETUP_FAILED", "step": step}
    setup_hashes.append(step["tx_hash"])

    # Persist the investor record.
    with _state_lock:
        _state["investors"][investor_id] = {
            "xrpl_address":     investor.classic_address,
            "seed":             investor.seed,
            "setup_complete":   True,
            "setup_tx_hashes":  setup_hashes,
            "registered_at":    datetime.now(timezone.utc).isoformat(),
        }
    _save_state()

    return {
        "status":           "REGISTERED",
        "investor_id":      investor_id,
        "xrpl_address":     investor.classic_address,
        "setup_tx_hashes":  setup_hashes,
    }


def _get_investor_wallet(investor_id: str) -> Optional[Wallet]:
    with _state_lock:
        rec = _state["investors"].get(investor_id)
    if not rec or not rec.get("seed"):
        return None
    return Wallet.from_seed(rec["seed"])


def get_investor_xrpl_address(investor_id: str) -> Optional[str]:
    """Return the investor's registered XRPL address, or None if not
    registered. Used by subscription_engine to decide whether Lane D
    can proceed."""
    with _state_lock:
        rec = _state["investors"].get(investor_id)
    return rec.get("xrpl_address") if rec else None


# ─── Atomic DvP ─────────────────────────────────────────────────────────────
def execute_subscription_dvp(investor_id: str,
                             amount_usd,
                             share_count) -> dict:
    """Execute the real atomic DvP for a Lane D subscription.

    Flow:
      1. Verify fund + investor are set up.
      2. CashIssuer pre-funds the investor with `amount_usd` of USD
         IOU (simulates the operator receiving the investor's USD wire
         + minting USD IOU for on-chain use).
      3. ShareIssuer posts a resting Offer:
           TakerPays = amount_usd USD (from CashIssuer)
           TakerGets = share_count MMF (from ShareIssuer)
      4. Investor submits a cross-currency Payment to themselves:
           Amount  = share_count MMF
           SendMax = amount_usd USD
           Flags   = tfLimitQuality
         This consumes the Offer atomically. Shares + cash swap in
         one validated ledger.

    Returns a dict with all tx hashes, ledger indices, close times,
    and the final engine_result. Caller (subscription_engine) stamps
    DSOR based on status.
    """
    amount = Decimal(str(amount_usd))
    shares = Decimal(str(share_count))

    investor_wallet = _get_investor_wallet(investor_id)
    if investor_wallet is None:
        return {
            "status": "NOT_REGISTERED",
            "reason": f"investor {investor_id} has no XRPL wallet — call register_investor first",
        }

    share_issuer, cash_issuer = _get_fund_wallets()

    # Step A: pre-fund investor with USD IOU (simulated wire-in).
    pre_fund_step = _submit(
        f"CashIssuer Payment: pre-fund Investor[{investor_id}] with {amount} {CASH_CURRENCY}",
        Payment(
            account=cash_issuer.classic_address,
            destination=investor_wallet.classic_address,
            amount=IssuedCurrencyAmount(
                currency=CASH_CURRENCY,
                issuer=cash_issuer.classic_address,
                value=str(amount),
            ),
        ),
        cash_issuer,
    )
    if pre_fund_step["engine_result"] != "tesSUCCESS":
        return {
            "status":            "PRE_FUND_FAILED",
            "investor_address":  investor_wallet.classic_address,
            "pre_fund_step":     pre_fund_step,
        }

    # Step B: ShareIssuer posts resting Offer.
    offer_step = _submit(
        f"ShareIssuer OfferCreate (resting): {shares} {SHARE_CURRENCY} for {amount} {CASH_CURRENCY}",
        OfferCreate(
            account=share_issuer.classic_address,
            taker_pays=IssuedCurrencyAmount(
                currency=CASH_CURRENCY,
                issuer=cash_issuer.classic_address,
                value=str(amount),
            ),
            taker_gets=IssuedCurrencyAmount(
                currency=SHARE_CURRENCY,
                issuer=share_issuer.classic_address,
                value=str(shares),
            ),
        ),
        share_issuer,
    )
    if offer_step["engine_result"] != "tesSUCCESS":
        return {
            "status":            "OFFER_FAILED",
            "investor_address":  investor_wallet.classic_address,
            "pre_fund_tx_hash":  pre_fund_step["tx_hash"],
            "offer_step":        offer_step,
        }

    # Step C: Atomic cross-currency Payment. The DvP moment.
    payment_step = _submit(
        f"Investor[{investor_id}] Payment (atomic DvP): {amount} {CASH_CURRENCY} -> {shares} {SHARE_CURRENCY}",
        Payment(
            account=investor_wallet.classic_address,
            destination=investor_wallet.classic_address,
            amount=IssuedCurrencyAmount(
                currency=SHARE_CURRENCY,
                issuer=share_issuer.classic_address,
                value=str(shares),
            ),
            send_max=IssuedCurrencyAmount(
                currency=CASH_CURRENCY,
                issuer=cash_issuer.classic_address,
                value=str(amount),
            ),
            flags=PaymentFlag.TF_LIMIT_QUALITY,
        ),
        investor_wallet,
    )

    status = "COMPLETE" if payment_step["engine_result"] == "tesSUCCESS" else "REJECTED"

    return {
        "status":                 status,
        "investor_id":            investor_id,
        "investor_address":       investor_wallet.classic_address,
        "share_issuer_address":   share_issuer.classic_address,
        "cash_issuer_address":    cash_issuer.classic_address,
        "pre_fund_tx_hash":       pre_fund_step["tx_hash"],
        "offer_tx_hash":          offer_step["tx_hash"],
        "payment_tx_hash":        payment_step["tx_hash"],
        "ledger_index":           payment_step["ledger_index"],
        "ledger_close_time_utc":  payment_step["ledger_close_time_utc"],
        "engine_result":          payment_step["engine_result"],
        "steps": [pre_fund_step, offer_step, payment_step],
    }


def execute_redemption_dvp(investor_id: str,
                           shares_to_burn,
                           net_payout_usd) -> dict:
    """Execute real atomic REVERSE DvP for a Lane D redemption
    (Phase 2 P2-3). Burn-on-receipt semantics: because ShareIssuer
    is the MMF issuer, when the investor's MMF trust-line balance
    returns to ShareIssuer, those shares cease to exist in the
    total supply — equivalent to a burn.

    Flow (mirror of execute_subscription_dvp with Offer direction
    flipped):
      1. Verify fund + investor are set up.
      2. ShareIssuer posts a resting Offer:
           TakerPays = shares_to_burn MMF   (investor gives up shares)
           TakerGets = net_payout_usd USD   (investor receives USD)
         Note: net_payout is already post-liquidity-fee. The fee is
         an implicit haircut — shares worth gross_payout at NAV are
         exchanged for less USD (net_payout). ShareIssuer retains
         the difference as a fee accrual off-ledger.
      3. Investor submits a cross-currency Payment:
           Amount  = net_payout_usd USD
           SendMax = shares_to_burn MMF
           Flags   = tfLimitQuality
         This consumes the Offer atomically. Shares burn (return to
         ShareIssuer) + USD lands in investor's trust line in one
         validated ledger.

    Returns a dict with all tx hashes, ledger index, close time,
    and final engine_result. Caller stamps DSOR based on status.
    """
    shares = Decimal(str(shares_to_burn))
    net_payout = Decimal(str(net_payout_usd))

    if shares <= 0 or net_payout <= 0:
        return {
            "status": "INVALID",
            "reason": "shares and net_payout must both be > 0",
        }

    investor_wallet = _get_investor_wallet(investor_id)
    if investor_wallet is None:
        return {
            "status": "NOT_REGISTERED",
            "reason": f"investor {investor_id} has no XRPL wallet — call register_investor first",
        }

    share_issuer, cash_issuer = _get_fund_wallets()

    # Step A: ShareIssuer posts resting Offer — MMF for USD (reverse direction).
    offer_step = _submit(
        f"ShareIssuer OfferCreate (redemption): {shares} {SHARE_CURRENCY} for {net_payout} {CASH_CURRENCY}",
        OfferCreate(
            account=share_issuer.classic_address,
            taker_pays=IssuedCurrencyAmount(
                currency=SHARE_CURRENCY,
                issuer=share_issuer.classic_address,
                value=str(shares),
            ),
            taker_gets=IssuedCurrencyAmount(
                currency=CASH_CURRENCY,
                issuer=cash_issuer.classic_address,
                value=str(net_payout),
            ),
        ),
        share_issuer,
    )
    if offer_step["engine_result"] != "tesSUCCESS":
        return {
            "status":            "OFFER_FAILED",
            "investor_address":  investor_wallet.classic_address,
            "offer_step":        offer_step,
        }

    # Step B: Atomic cross-currency Payment — USD to investor, MMF burned.
    # tfLimitQuality at rate net_payout/shares guarantees the investor
    # doesn't pay more MMF than the posted rate requires.
    payment_step = _submit(
        f"Investor[{investor_id}] Payment (atomic reverse DvP): {shares} {SHARE_CURRENCY} -> {net_payout} {CASH_CURRENCY}",
        Payment(
            account=investor_wallet.classic_address,
            destination=investor_wallet.classic_address,
            amount=IssuedCurrencyAmount(
                currency=CASH_CURRENCY,
                issuer=cash_issuer.classic_address,
                value=str(net_payout),
            ),
            send_max=IssuedCurrencyAmount(
                currency=SHARE_CURRENCY,
                issuer=share_issuer.classic_address,
                value=str(shares),
            ),
            flags=PaymentFlag.TF_LIMIT_QUALITY,
        ),
        investor_wallet,
    )

    status = "COMPLETE" if payment_step["engine_result"] == "tesSUCCESS" else "REJECTED"

    return {
        "status":                 status,
        "investor_id":            investor_id,
        "investor_address":       investor_wallet.classic_address,
        "share_issuer_address":   share_issuer.classic_address,
        "cash_issuer_address":    cash_issuer.classic_address,
        "offer_tx_hash":          offer_step["tx_hash"],
        "burn_tx_hash":           payment_step["tx_hash"],
        "ledger_index":           payment_step["ledger_index"],
        "ledger_close_time_utc":  payment_step["ledger_close_time_utc"],
        "engine_result":          payment_step["engine_result"],
        "steps": [offer_step, payment_step],
    }


def diagnostic_status() -> dict:
    """Read-only snapshot of module state for /api/mmf/digital/status."""
    with _state_lock:
        return {
            "testnet_rpc":           TESTNET_RPC,
            "share_issuer_address":  _state["share_issuer_address"],
            "cash_issuer_address":   _state["cash_issuer_address"],
            "fund_setup_complete":   _state["fund_setup_complete"],
            "registered_investors": [
                {
                    "investor_id":    iid,
                    "xrpl_address":   rec["xrpl_address"],
                    "registered_at":  rec.get("registered_at"),
                }
                for iid, rec in _state["investors"].items()
            ],
        }
