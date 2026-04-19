"""
Atrox — Alpha Origination Layer (Sandbox Signal Generator)
==========================================================
Generates trade signals for Thifur-H sandbox validation.

In production: Atrox synthesizes across 6 live data pipes.
In sandbox: Atrox uses Gemini sandbox ticker + simple momentum logic
to generate realistic signals for governance validation.

Every signal is ADVISORY. No signal executes without CAOM-001 approval.

Named for: Atrox. Executed blind into denied territory with incomplete
information, zero margin for error, single objective.
"""

import time
import uuid
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional
import urllib.request
import json

from aureon.thifur.thifur_h import AtroxSignal

logger = logging.getLogger("atrox")


class AtroxSandboxSignalGenerator:
    """
    Sandbox signal generator for Thifur-H activation validation.

    Signal logic (simplified for validation purposes):
    - Fetches live sandbox BTC price
    - Generates buy signal if price is within position bounds
    - Generates sell signal to close existing positions
    - All signals are advisory — require CAOM-001 approval before use

    In production: replace with full 6-pipe synthesis (Unusual Whales,
    Tradier, Alpaca, CBOE, EDGAR, Blockscout).
    """

    SANDBOX_TICKER_URL = "https://api.sandbox.gemini.com/v1/pubticker/btcusd"

    # Sandbox signal parameters
    BUY_OFFSET_PCT = -0.001   # Limit 0.1% below last price (maker order)
    SELL_OFFSET_PCT = +0.001  # Limit 0.1% above last price (maker order)
    SANDBOX_QTY = 0.0004      # ~$40 at $100k BTC — well within $50 limit

    def __init__(self):
        self.signal_count = 0
        logger.info("Atrox sandbox signal generator initialized")

    def _get_sandbox_price(self) -> Optional[float]:
        """Fetch live BTC price from Gemini sandbox."""
        try:
            req = urllib.request.Request(self.SANDBOX_TICKER_URL)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                price = float(data.get("last", 0))
                logger.info(f"Atrox price feed: BTC/USD ${price:,.2f} (sandbox)")
                return price
        except Exception as e:
            logger.error(f"Atrox price fetch failed: {e}")
            return None

    def generate_buy_signal(self, rationale_override: str = None) -> Optional[AtroxSignal]:
        """
        Generate a buy signal. Advisory only.
        Caller must set caom_approved=True after human approval.
        """
        price = self._get_sandbox_price()
        if not price:
            logger.warning("Atrox: Cannot generate signal — no price data")
            return None

        limit_price = round(price * (1 + self.BUY_OFFSET_PCT), 2)
        self.signal_count += 1

        signal = AtroxSignal(
            signal_id=f"ATROX-{uuid.uuid4().hex[:8].upper()}",
            symbol="BTCUSD",
            side="buy",
            rationale=rationale_override or (
                f"Sandbox validation cycle {self.signal_count}. "
                f"BTC/USD last ${price:,.2f}. "
                f"Limit buy ${limit_price:,.2f} (0.1% below market). "
                f"Maker-or-cancel — no immediate fill risk. "
                f"Position size ${limit_price * self.SANDBOX_QTY:.2f} within $50 governance bound."
            ),
            confidence=0.72,
            suggested_price=limit_price,
            suggested_qty=self.SANDBOX_QTY,
            caom_approved=False,  # Must be set to True by human operator
        )
        logger.info(f"Atrox generated BUY signal {signal.signal_id} | ${limit_price:,.2f} | {self.SANDBOX_QTY} BTC")
        return signal

    def generate_sell_signal(self, rationale_override: str = None) -> Optional[AtroxSignal]:
        """Generate a sell signal for position close or short."""
        price = self._get_sandbox_price()
        if not price:
            return None

        limit_price = round(price * (1 + self.SELL_OFFSET_PCT), 2)
        self.signal_count += 1

        signal = AtroxSignal(
            signal_id=f"ATROX-{uuid.uuid4().hex[:8].upper()}",
            symbol="BTCUSD",
            side="sell",
            rationale=rationale_override or (
                f"Sandbox validation cycle {self.signal_count}. "
                f"BTC/USD last ${price:,.2f}. "
                f"Limit sell ${limit_price:,.2f} (0.1% above market). "
                f"Position size ${limit_price * self.SANDBOX_QTY:.2f} within $50 governance bound."
            ),
            confidence=0.68,
            suggested_price=limit_price,
            suggested_qty=self.SANDBOX_QTY,
            caom_approved=False,
        )
        logger.info(f"Atrox generated SELL signal {signal.signal_id} | ${limit_price:,.2f}")
        return signal

    def generate_breach_signal(self, breach_type: str) -> Optional[AtroxSignal]:
        """
        Intentionally generate a signal designed to breach a specific gate.
        Used for governance validation cycles 6-20 (stress testing).

        breach_type: "size" | "symbol" | "no_approval"
        """
        price = self._get_sandbox_price() or 95000.0
        self.signal_count += 1

        if breach_type == "size":
            # Intentional: position value > $50 limit
            signal = AtroxSignal(
                signal_id=f"ATROX-BREACH-SIZE-{uuid.uuid4().hex[:6].upper()}",
                symbol="BTCUSD",
                side="buy",
                rationale="INTENTIONAL GATE 3 BREACH TEST — position size exceeds $50 hard limit",
                confidence=0.99,
                suggested_price=price,
                suggested_qty=0.01,   # ~$1000 — far above $50 limit
                caom_approved=True,
                approval_timestamp=datetime.now(timezone.utc).isoformat(),
            )
        elif breach_type == "symbol":
            # Intentional: symbol not in whitelist
            signal = AtroxSignal(
                signal_id=f"ATROX-BREACH-SYM-{uuid.uuid4().hex[:6].upper()}",
                symbol="ETHUSD",      # Not in whitelist
                side="buy",
                rationale="INTENTIONAL GATE 2 BREACH TEST — symbol not in whitelist",
                confidence=0.99,
                suggested_price=3000.0,
                suggested_qty=0.001,
                caom_approved=True,
                approval_timestamp=datetime.now(timezone.utc).isoformat(),
            )
        elif breach_type == "no_approval":
            # Intentional: CAOM-001 approval missing
            signal = AtroxSignal(
                signal_id=f"ATROX-BREACH-AUTH-{uuid.uuid4().hex[:6].upper()}",
                symbol="BTCUSD",
                side="buy",
                rationale="INTENTIONAL GATE 1 BREACH TEST — no CAOM-001 approval",
                confidence=0.99,
                suggested_price=price * 0.999,
                suggested_qty=self.SANDBOX_QTY,
                caom_approved=False,   # Missing approval
                approval_timestamp=None,
            )
        else:
            raise ValueError(f"Unknown breach_type: {breach_type}")

        logger.warning(f"Atrox BREACH SIGNAL generated: {breach_type} | {signal.signal_id}")
        return signal
