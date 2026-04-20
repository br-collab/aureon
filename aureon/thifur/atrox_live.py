"""
Atrox Live — automated 5-min BTC/USD signal generator for Thifur-H.

Runs in a background thread on the Railway worker. Active only when a
Thifur-H session is ACTIVE; dormant otherwise.

Strategy (operator-specified, doctrine-bounded):
  - Pull XBTUSD price every 5 min from Kraken
  - 1-hour rolling high (12 × 5-min candles)
  - BUY when price drops >0.3% from rolling high AND no open position
        -> emits AtroxSignal pending CAOM-001 approval (HITL Tier C: entries gated)
  - SELL when open position is up >0.5% from entry
        -> auto-executes if auto-close policy is armed; else pending HITL
  - STOP when open position is down >0.3% from entry
        -> auto-executes as market order if armed (STOP_ALLOW_MARKET);
           else limit sell at -0.3%; else pending HITL

P&L tracking includes Kraken fees (0.16% maker, 0.25% taker).

Author: Project Aureon · Aureon-Leto
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Optional

from aureon.thifur.thifur_h import AtroxSignal

logger = logging.getLogger("atrox_live")


# ─────────────────────────────────────────────────────────────────
# STRATEGY CONSTANTS — per CAOM-001 spec
# ─────────────────────────────────────────────────────────────────

LOOP_INTERVAL_SEC = 300              # 5-min cadence
LOOKBACK_CANDLES = 12                # 1h rolling high (12 × 5 min)
BUY_TRIGGER_DROP_PCT = 0.003         # 0.3% drop from recent high
SELL_TRIGGER_GAIN_PCT = 0.005        # 0.5% above entry
STOP_TRIGGER_LOSS_PCT = 0.003        # 0.3% below entry
LIMIT_OFFSET_PCT = 0.001             # 0.1% off market for limits

KRAKEN_MAKER_FEE_PCT = 0.0016
KRAKEN_TAKER_FEE_PCT = 0.0025


class AtroxLive:
    """Background signal generator. Decoupled from server.py via callbacks."""

    def __init__(
        self,
        get_session: Callable[[], object],
        get_kraken_price: Callable[[str], float],
        set_pending_signal: Callable[[AtroxSignal], None],
        get_pending_signal: Callable[[], Optional[AtroxSignal]],
        is_auto_close_armed: Callable[[], bool],
        consume_auto_close_cycle: Callable[[], bool],
        execute_close_signal: Callable[[AtroxSignal, str, bool], dict],
        persist_state: Callable[[], None],
        interval_sec: int = LOOP_INTERVAL_SEC,
    ):
        self.get_session = get_session
        self.get_kraken_price = get_kraken_price
        self.set_pending_signal = set_pending_signal
        self.get_pending_signal = get_pending_signal
        self.is_auto_close_armed = is_auto_close_armed
        self.consume_auto_close_cycle = consume_auto_close_cycle
        self.execute_close_signal = execute_close_signal
        self.persist_state = persist_state
        self.interval_sec = interval_sec

        self.price_history: deque = deque(maxlen=LOOKBACK_CANDLES)
        self.last_tick_at: Optional[str] = None
        self.last_decision: dict = {"type": "init", "ts": _now_iso()}
        self.tick_count = 0
        self.lock = threading.Lock()
        self._stop = threading.Event()

    # ── Loop lifecycle ────────────────────────────────────────────

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True, name="atrox-live").start()
        logger.info(f"Atrox Live loop started (interval={self.interval_sec}s)")

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # Initial burn-in: take a few quick samples so we have history fast
        # rather than waiting LOOKBACK_CANDLES × interval before any signal.
        burn_in = 0
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error(f"Atrox tick crashed: {type(e).__name__}: {e}")
            # Burn-in: 30s polling for first 6 ticks, then fall to interval
            if burn_in < 6:
                burn_in += 1
                self._stop.wait(30)
            else:
                self._stop.wait(self.interval_sec)

    # ── Tick ──────────────────────────────────────────────────────

    def _tick(self) -> None:
        engine = self.get_session()
        if engine is None:
            return
        try:
            state = engine.ledger.state.value
        except Exception:
            return
        if state != "ACTIVE":
            return

        price = self.get_kraken_price("XBTUSD")
        if not price or price <= 0:
            self._record_decision("noop", "bad price feed")
            return

        with self.lock:
            self.price_history.append({"ts": _now_iso(), "price": price})
            self.last_tick_at = _now_iso()
            self.tick_count += 1

        if len(self.price_history) < 3:
            self._record_decision("warming_up", f"history={len(self.price_history)}/3")
            return

        recent_high = max(c["price"] for c in self.price_history)

        # Position state
        positions = engine.ledger.open_positions
        if not positions:
            # Don't double-emit if a buy is already pending HITL
            if self.get_pending_signal() is not None:
                self._record_decision("noop", "buy already pending HITL")
                return
            drop_pct = (recent_high - price) / recent_high if recent_high > 0 else 0
            if drop_pct >= BUY_TRIGGER_DROP_PCT:
                self._emit_buy(price, recent_high, drop_pct)
            else:
                self._record_decision("hold", f"drop={drop_pct:.4%} < {BUY_TRIGGER_DROP_PCT:.4%}")
        else:
            # Single concurrent position by doctrine — take the first
            txid, pos = next(iter(positions.items()))
            entry = float(pos.get("price", 0))
            if entry <= 0:
                self._record_decision("noop", f"bad entry on {txid}")
                return
            gain_pct = (price - entry) / entry
            if gain_pct >= SELL_TRIGGER_GAIN_PCT:
                self._emit_sell_or_stop(engine, price, entry, gain_pct, txid, pos, kind="sell")
            elif gain_pct <= -STOP_TRIGGER_LOSS_PCT:
                self._emit_sell_or_stop(engine, price, entry, gain_pct, txid, pos, kind="stop")
            else:
                self._record_decision("hold", f"pnl={gain_pct:+.4%} band=[-{STOP_TRIGGER_LOSS_PCT:.4%}, +{SELL_TRIGGER_GAIN_PCT:.4%}]")

        try:
            self.persist_state()
        except Exception as e:
            logger.error(f"Atrox state persist failed: {e}")

    # ── Signal emission ───────────────────────────────────────────

    def _emit_buy(self, price: float, recent_high: float, drop_pct: float) -> None:
        from aureon.thifur.kraken_client import ThifurHDoctrineLive
        limit_price = round(price * (1 - LIMIT_OFFSET_PCT), 1)
        signal = AtroxSignal(
            signal_id=f"ATROX-AUTO-BUY-{uuid.uuid4().hex[:6].upper()}",
            symbol="XBTUSD",
            side="buy",
            rationale=(
                f"Auto-BUY (1h reversion). Recent high ${recent_high:,.1f}, "
                f"current ${price:,.1f}, drop {drop_pct:.3%}. "
                f"Limit buy ${limit_price} (0.1% below market). Post-only. "
                f"Position size doctrine-capped at "
                f"${ThifurHDoctrineLive.MAX_POSITION_USD}."
            ),
            confidence=min(0.5 + drop_pct * 50, 0.95),  # scales with drop magnitude
            suggested_price=limit_price,
            suggested_qty=ThifurHDoctrineLive.MAX_ORDER_QTY_BTC,
            caom_approved=False,
        )
        self.set_pending_signal(signal)
        self._record_decision("buy_pending_hitl", f"drop={drop_pct:.3%} signal={signal.signal_id}")
        logger.info(f"Atrox AUTO-BUY emitted (pending HITL) {signal.signal_id}")

    def _emit_sell_or_stop(
        self,
        engine,
        price: float,
        entry: float,
        gain_pct: float,
        txid: str,
        pos: dict,
        kind: str,
    ) -> None:
        from aureon.thifur.kraken_client import ThifurHDoctrineLive
        is_stop = (kind == "stop")
        # Limit price for sell: 0.1% above market; for stop: -0.3% (catastrophe band)
        limit_price = round(price * (1 + LIMIT_OFFSET_PCT), 1) if not is_stop else round(price * (1 - 0.003), 1)
        qty = float(pos.get("qty", ThifurHDoctrineLive.MAX_ORDER_QTY_BTC))
        signal = AtroxSignal(
            signal_id=f"ATROX-AUTO-{kind.upper()}-{uuid.uuid4().hex[:6].upper()}",
            symbol="XBTUSD",
            side="sell",
            rationale=(
                f"Auto-{kind.upper()} on open position {txid}. "
                f"Entry ${entry:,.1f}, current ${price:,.1f}, P&L {gain_pct:+.3%}. "
                + (
                    f"Stop triggered (>0.3% loss). "
                    f"Market order if STOP_ALLOW_MARKET; else limit ${limit_price}."
                    if is_stop
                    else f"Limit sell ${limit_price} (0.1% above market)."
                )
            ),
            confidence=0.99 if is_stop else 0.85,
            suggested_price=limit_price,
            suggested_qty=qty,
            caom_approved=True,
            approval_timestamp=_now_iso(),
            approved_by="ATROX-AUTO-CLOSE",
        )
        # Decide auto-execute vs pending HITL
        armed = self.is_auto_close_armed()
        if not armed:
            # Auto-close policy not armed — fall back to HITL
            signal.caom_approved = False
            signal.approval_timestamp = None
            signal.approved_by = "CAOM-001"
            self.set_pending_signal(signal)
            self._record_decision(
                f"{kind}_pending_hitl",
                f"close-policy not armed; pnl={gain_pct:+.3%}",
            )
            logger.info(f"Atrox AUTO-{kind.upper()} -> HITL (no close-policy armed) {signal.signal_id}")
            return
        # Armed: auto-execute. Stops use market order if doctrine allows.
        force_market = is_stop and getattr(ThifurHDoctrineLive, "STOP_ALLOW_MARKET", False)
        if not self.consume_auto_close_cycle():
            signal.caom_approved = False
            signal.approval_timestamp = None
            self.set_pending_signal(signal)
            self._record_decision(
                f"{kind}_pending_hitl",
                "close-policy exhausted/expired; falling back to HITL",
            )
            return
        try:
            result = self.execute_close_signal(signal, kind, force_market)
            self._record_decision(
                f"{kind}_executed",
                f"pnl={gain_pct:+.3%} result={result.get('result')} order={result.get('order_id')}",
            )
            logger.warning(
                f"Atrox AUTO-{kind.upper()} EXECUTED {signal.signal_id} "
                f"(market={force_market}) -> {result.get('result')}"
            )
        except Exception as e:
            self._record_decision(f"{kind}_error", f"{type(e).__name__}: {e}")
            logger.error(f"Atrox auto-execute failed: {e}")

    # ── Diagnostics ───────────────────────────────────────────────

    def _record_decision(self, kind: str, detail: str) -> None:
        self.last_decision = {"type": kind, "detail": detail, "ts": _now_iso()}

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "tick_count": self.tick_count,
                "last_tick_at": self.last_tick_at,
                "last_decision": self.last_decision,
                "history_len": len(self.price_history),
                "recent_high": max((c["price"] for c in self.price_history), default=None),
                "current_price": self.price_history[-1]["price"] if self.price_history else None,
                "history": list(self.price_history),
                "constants": {
                    "interval_sec": self.interval_sec,
                    "lookback_candles": LOOKBACK_CANDLES,
                    "buy_drop_pct": BUY_TRIGGER_DROP_PCT,
                    "sell_gain_pct": SELL_TRIGGER_GAIN_PCT,
                    "stop_loss_pct": STOP_TRIGGER_LOSS_PCT,
                    "limit_offset_pct": LIMIT_OFFSET_PCT,
                    "maker_fee_pct": KRAKEN_MAKER_FEE_PCT,
                    "taker_fee_pct": KRAKEN_TAKER_FEE_PCT,
                },
            }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
