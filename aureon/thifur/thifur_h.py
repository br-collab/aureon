"""
Thifur-H — Hunter-Killer — Adaptive Intelligence
================================================
Phase 2 Activation — Gemini Exchange Sandbox Validation
CAOM-001 Sole Operator Mode

Thifur-H is Aureon's adaptive execution intelligence layer.
It does NOT initiate, approve, or release trades.
It advises on execution strategy and executes within pre-approved,
hard-coded bounds after HITL gate clearance.

SR 11-7 Tier 1 — Independent validation in progress via sandbox.
MiFID II RTS 6 — Kill switch active. Algorithm inventory recorded.

Architecture position:
  Atrox → CAOM-001 approval → Thifur-C2 → Thifur-H → Gemini MCP → Exchange

Author: Project Aureon · Guillermo "Bill" Ravelo
"""

import asyncio
import hashlib
import hmac
import base64
import json
import time
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import urllib.request
import urllib.parse
import urllib.error

logger = logging.getLogger("thifur_h")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [THIFUR-H] %(levelname)s %(message)s"
)


class _DSOREncoder(json.JSONEncoder):
    """Handles enums and datetimes in DSOR export — both leak through asdict()."""
    def default(self, o):
        if isinstance(o, Enum):
            return o.value
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


# ─────────────────────────────────────────────
# DOCTRINE CONSTANTS — NOT CONFIGURABLE BY AGENT
# ─────────────────────────────────────────────

class ThifurHDoctrine:
    """
    Hard-coded governance bounds for Thifur-H sandbox activation.
    These values are constants. The agent cannot read, modify,
    or reason about them. SR 11-7 principle: model cannot validate itself.
    """
    MAX_POSITION_USD: float = 50.0          # Max single position value
    MAX_SESSION_LOSS_USD: float = 25.0      # Session drawdown kill threshold
    MAX_ORDER_QTY_BTC: float = 0.0005       # ~$50 at $100k BTC
    MAX_ORDERS_PER_SESSION: int = 20        # Cycle limit per validation run
    HITL_REQUIRED: bool = True              # Human approval always required
    SANDBOX_ONLY: bool = True               # Hard block on live execution
    ALLOWED_SYMBOLS: tuple = ("BTCUSD",)   # Sandbox symbol whitelist
    ALLOWED_SIDES: tuple = ("buy", "sell")
    ALLOWED_ORDER_TYPES: tuple = ("limit",) # No market orders in sandbox
    CANCEL_ON_DISCONNECT: bool = True       # Native Gemini circuit breaker
    # Rail discipline: sandbox is also a digital-asset rail (Gemini BTCUSD).
    # Equities trading hours do not apply. Same posture as ThifurHDoctrineLive.
    MARKET_RAIL: str = "digital_assets"


# ─────────────────────────────────────────────
# DATA MODELS
# ─────────────────────────────────────────────

class GateResult(Enum):
    PASS = "PASS"
    HOLD = "HOLD"       # HITL queue — awaiting human approval
    BLOCK = "BLOCK"     # Hard breach — order never reaches exchange
    ROLLBACK = "ROLLBACK"  # Post-execution breach — issue cancel


class SessionState(Enum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    HALTED = "HALTED"   # Kill switch triggered
    CLOSED = "CLOSED"


@dataclass
class AtroxSignal:
    """
    Signal packet from Atrox alpha origination layer.
    Arrives after CAOM-001 human approval.
    """
    signal_id: str
    symbol: str
    side: str                    # buy | sell
    rationale: str               # Atrox analytical lineage
    confidence: float            # 0.0 - 1.0
    suggested_price: float       # Limit price suggestion
    suggested_qty: float         # Quantity suggestion
    caom_approved: bool = False  # Must be True before Thifur-H acts
    approved_by: str = "CAOM-001"
    approval_timestamp: Optional[str] = None


@dataclass
class GateRecord:
    """Immutable audit record for every gate evaluation."""
    gate_id: str
    gate_name: str
    result: GateResult
    signal_id: str
    timestamp: str
    reason: str
    checked_value: Optional[float] = None
    threshold: Optional[float] = None


@dataclass
class SessionLedger:
    """
    Real-time position and P&L tracking for Thifur-H session.
    Pre/post state snapshot for rollback authority.
    """
    session_id: str
    started_at: str
    state: SessionState = SessionState.IDLE
    orders_placed: int = 0
    orders_filled: int = 0
    orders_cancelled: int = 0
    total_bought_usd: float = 0.0
    total_sold_usd: float = 0.0
    realized_pnl_usd: float = 0.0
    realized_pnl_gross_usd: float = 0.0
    total_fees_usd: float = 0.0
    auto_executions: int = 0           # SELL/STOP fired via auto-close policy
    session_loss_usd: float = 0.0
    open_positions: dict = field(default_factory=dict)  # order_id → order details
    gate_records: list = field(default_factory=list)
    dsor_entries: list = field(default_factory=list)    # Decision System of Record


@dataclass
class DSOREntry:
    """
    Decision System of Record entry.
    Every decision — approved or blocked — is logged.
    This is the SR 11-7 evidence package.
    """
    entry_id: str
    decision_type: str          # GATE_PASS | GATE_HOLD | GATE_BLOCK | ORDER_PLACED | FILL | CANCEL | ROLLBACK
    signal_id: str
    session_id: str
    timestamp: str
    details: dict
    gate_result: Optional[str] = None
    order_id: Optional[str] = None
    caom_operator: str = "CAOM-001"


# ─────────────────────────────────────────────
# GEMINI SANDBOX CLIENT
# ─────────────────────────────────────────────

class GeminiSandboxClient:
    """
    Minimal Gemini sandbox REST client.
    Uses only: place order, cancel order, get order status, get balances.
    No market orders. No leverage. Sandbox only.
    """

    BASE_URL = "https://api.sandbox.gemini.com"

    def __init__(self, api_key: str, api_secret: str):
        if ThifurHDoctrine.SANDBOX_ONLY:
            assert "sandbox" in self.BASE_URL, "DOCTRINE BREACH: Live URL in sandbox-only mode"
        self.api_key = api_key
        self.api_secret = api_secret.encode()

    def _sign(self, endpoint: str, payload: dict) -> dict:
        """HMAC-SHA384 signing per Gemini API spec."""
        payload["request"] = endpoint
        payload["nonce"] = str(int(time.time() * 1000))
        encoded = base64.b64encode(json.dumps(payload).encode())
        signature = hmac.new(self.api_secret, encoded, hashlib.sha384).hexdigest()
        return {
            "Content-Type": "text/plain",
            "X-GEMINI-APIKEY": self.api_key,
            "X-GEMINI-PAYLOAD": encoded.decode(),
            "X-GEMINI-SIGNATURE": signature,
        }

    def _post(self, endpoint: str, payload: dict) -> dict:
        headers = self._sign(endpoint, payload)
        url = self.BASE_URL + endpoint
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            logger.error(f"Gemini API error {e.code}: {body}")
            return {"error": body, "code": e.code}

    def _get(self, endpoint: str) -> dict:
        url = self.BASE_URL + endpoint
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return {"error": e.read().decode(), "code": e.code}

    def get_balances(self) -> list:
        return self._post("/v1/balances", {})

    def get_ticker(self, symbol: str) -> dict:
        return self._get(f"/v1/pubticker/{symbol.lower()}")

    def place_limit_order(
        self,
        symbol: str,
        side: str,
        price: str,
        quantity: str,
        client_order_id: str
    ) -> dict:
        """Place a limit order. Only order type permitted by doctrine."""
        assert ThifurHDoctrine.SANDBOX_ONLY, "DOCTRINE BREACH"
        assert symbol in ThifurHDoctrine.ALLOWED_SYMBOLS, f"Symbol {symbol} not in whitelist"
        assert side in ThifurHDoctrine.ALLOWED_SIDES, f"Side {side} not allowed"
        payload = {
            "symbol": symbol.lower(),
            "amount": quantity,
            "price": price,
            "side": side,
            "type": "exchange limit",
            "client_order_id": client_order_id,
            "options": ["maker-or-cancel"],  # No immediate fill — controlled execution
        }
        return self._post("/v1/order/new", payload)

    def cancel_order(self, order_id: str) -> dict:
        """Rollback mechanism — cancel by order_id."""
        return self._post("/v1/order/cancel", {"order_id": order_id})

    def cancel_all_session_orders(self) -> dict:
        """Kill switch — cancel all open orders."""
        return self._post("/v1/order/cancel/session", {})

    def get_order_status(self, order_id: str) -> dict:
        return self._post("/v1/order/status", {"order_id": order_id})


# ─────────────────────────────────────────────
# GATE LAYER — AUREON GOVERNANCE MIDDLEWARE
# ─────────────────────────────────────────────

class ThifurHGates:
    """
    Five-gate governance layer.
    Every signal passes all five gates before reaching the exchange.
    Failure at any gate = BLOCK. HITL gate = HOLD pending human approval.

    Gate 1: CAOM-001 Authorization check
    Gate 2: Symbol + side whitelist
    Gate 3: Position size hard limit
    Gate 4: Session drawdown check
    Gate 5: HITL — human approval queue
    """

    def __init__(self, ledger: SessionLedger, doctrine=ThifurHDoctrine):
        self.ledger = ledger
        self.doctrine = doctrine

    def _record(self, gate_id, name, result, signal_id, reason,
                checked=None, threshold=None) -> GateRecord:
        rec = GateRecord(
            gate_id=gate_id,
            gate_name=name,
            result=result,
            signal_id=signal_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            reason=reason,
            checked_value=checked,
            threshold=threshold,
        )
        self.ledger.gate_records.append(asdict(rec))
        logger.info(f"GATE {gate_id} [{name}] → {result.value} | {reason}")
        return rec

    def gate1_caom_authorization(self, signal: AtroxSignal) -> GateRecord:
        """Gate 1: Was this signal approved by CAOM-001 human authority?"""
        if not signal.caom_approved or not signal.approval_timestamp:
            return self._record("G1", "CAOM-001 Authorization",
                                GateResult.BLOCK, signal.signal_id,
                                "Signal not approved by CAOM-001 human authority")
        return self._record("G1", "CAOM-001 Authorization",
                            GateResult.PASS, signal.signal_id,
                            f"Approved by {signal.approved_by} at {signal.approval_timestamp}")

    def gate2_symbol_whitelist(self, signal: AtroxSignal) -> GateRecord:
        """Gate 2: Symbol and side within doctrine whitelist?"""
        if signal.symbol not in self.doctrine.ALLOWED_SYMBOLS:
            return self._record("G2", "Symbol Whitelist",
                                GateResult.BLOCK, signal.signal_id,
                                f"Symbol {signal.symbol} not in whitelist {self.doctrine.ALLOWED_SYMBOLS}")
        if signal.side not in self.doctrine.ALLOWED_SIDES:
            return self._record("G2", "Symbol Whitelist",
                                GateResult.BLOCK, signal.signal_id,
                                f"Side {signal.side} not allowed")
        return self._record("G2", "Symbol Whitelist",
                            GateResult.PASS, signal.signal_id,
                            f"{signal.symbol} {signal.side} — whitelisted")

    def gate3_position_size(self, signal: AtroxSignal) -> GateRecord:
        """Gate 3: Position value within hard limit?"""
        position_usd = signal.suggested_price * signal.suggested_qty
        if position_usd > self.doctrine.MAX_POSITION_USD:
            return self._record("G3", "Position Size",
                                GateResult.BLOCK, signal.signal_id,
                                f"Position ${position_usd:.2f} exceeds hard limit ${self.doctrine.MAX_POSITION_USD}",
                                checked=position_usd,
                                threshold=self.doctrine.MAX_POSITION_USD)
        if signal.suggested_qty > self.doctrine.MAX_ORDER_QTY_BTC:
            return self._record("G3", "Position Size",
                                GateResult.BLOCK, signal.signal_id,
                                f"Qty {signal.suggested_qty} BTC exceeds max {self.doctrine.MAX_ORDER_QTY_BTC} BTC",
                                checked=signal.suggested_qty,
                                threshold=self.doctrine.MAX_ORDER_QTY_BTC)
        return self._record("G3", "Position Size",
                            GateResult.PASS, signal.signal_id,
                            f"Position ${position_usd:.2f} within limit ${self.doctrine.MAX_POSITION_USD}",
                            checked=position_usd,
                            threshold=self.doctrine.MAX_POSITION_USD)

    def gate4_session_drawdown(self, signal: AtroxSignal) -> GateRecord:
        """Gate 4: Session loss within kill threshold?"""
        if self.ledger.session_loss_usd >= self.doctrine.MAX_SESSION_LOSS_USD:
            return self._record("G4", "Session Drawdown",
                                GateResult.BLOCK, signal.signal_id,
                                f"Session loss ${self.ledger.session_loss_usd:.2f} at or beyond kill threshold ${self.doctrine.MAX_SESSION_LOSS_USD}",
                                checked=self.ledger.session_loss_usd,
                                threshold=self.doctrine.MAX_SESSION_LOSS_USD)
        if self.ledger.orders_placed >= self.doctrine.MAX_ORDERS_PER_SESSION:
            return self._record("G4", "Session Drawdown",
                                GateResult.BLOCK, signal.signal_id,
                                f"Session order count {self.ledger.orders_placed} at max {self.doctrine.MAX_ORDERS_PER_SESSION}",
                                checked=float(self.ledger.orders_placed),
                                threshold=float(self.doctrine.MAX_ORDERS_PER_SESSION))
        return self._record("G4", "Session Drawdown",
                            GateResult.PASS, signal.signal_id,
                            f"Session loss ${self.ledger.session_loss_usd:.2f}, orders {self.ledger.orders_placed}/{self.doctrine.MAX_ORDERS_PER_SESSION}",
                            checked=self.ledger.session_loss_usd,
                            threshold=self.doctrine.MAX_SESSION_LOSS_USD)

    def gate5_hitl(self, signal: AtroxSignal) -> GateRecord:
        """
        Gate 5: Human In The Loop.
        In sandbox validation, HITL is simulated as a console prompt.
        In production: routes to CAOM-001 approval queue.
        """
        if not self.doctrine.HITL_REQUIRED:
            return self._record("G5", "HITL",
                                GateResult.PASS, signal.signal_id,
                                "HITL bypassed — doctrine flag off (not permitted in production)")

        if signal.caom_approved and signal.approval_timestamp:
            return self._record("G5", "HITL",
                                GateResult.PASS, signal.signal_id,
                                f"CAOM-001 operator approved at {signal.approval_timestamp} (pre-gate stamp)")

        return self._record("G5", "HITL",
                            GateResult.BLOCK, signal.signal_id,
                            "CAOM-001 approval missing — signal cannot pass HITL")

    def run_all_gates(self, signal: AtroxSignal) -> tuple[GateResult, list[GateRecord]]:
        """
        Evaluate all five gates regardless of intermediate failures.
        Every gate is recorded for SR 11-7 evidence completeness.
        Final decision: first non-PASS result if any, else PASS.
        """
        gates = [
            self.gate1_caom_authorization,
            self.gate2_symbol_whitelist,
            self.gate3_position_size,
            self.gate4_session_drawdown,
            self.gate5_hitl,
        ]
        records = []
        final_result = GateResult.PASS
        for gate_fn in gates:
            rec = gate_fn(signal)
            records.append(rec)
            if rec.result != GateResult.PASS and final_result == GateResult.PASS:
                final_result = rec.result
                logger.warning(f"Gate {rec.gate_name} → {rec.result.value} (continuing for evidence)")
        return final_result, records


# ─────────────────────────────────────────────
# THIFUR-H CORE ENGINE
# ─────────────────────────────────────────────

class ThifurH:
    """
    Thifur-H — Hunter-Killer — Adaptive Intelligence
    Phase 2 Sandbox Activation

    Wraps the Gemini MCP/REST layer with full Aureon governance.
    The agent never touches the exchange directly.
    Every action is: Signal → Gates → HITL → Exchange → Ledger → DSOR.
    """

    def __init__(self, api_key: str, api_secret: str, doctrine=ThifurHDoctrine):
        self.session_id = f"THIFUR-H-{int(time.time())}"
        self.ledger = SessionLedger(
            session_id=self.session_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self.doctrine = doctrine
        self.gates = ThifurHGates(self.ledger, doctrine)
        self.exchange = GeminiSandboxClient(api_key, api_secret)
        self.ledger.state = SessionState.ACTIVE
        logger.info(f"Thifur-H activated | Session: {self.session_id} | SANDBOX ONLY")

    def _dsor(self, decision_type: str, signal_id: str, details: dict,
              gate_result=None, order_id=None) -> DSOREntry:
        """Write to Decision System of Record."""
        entry = DSOREntry(
            entry_id=f"DSOR-{self.session_id}-{len(self.ledger.dsor_entries):04d}",
            decision_type=decision_type,
            signal_id=signal_id,
            session_id=self.session_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            details=details,
            gate_result=gate_result,
            order_id=order_id,
        )
        self.ledger.dsor_entries.append(asdict(entry))
        logger.info(f"DSOR ← {decision_type} | {entry.entry_id}")
        return entry

    def _generate_client_order_id(self, signal_id: str) -> str:
        return f"aureon-{self.session_id[-8:]}-{signal_id[-6:]}"

    def process_signal(self, signal: AtroxSignal) -> dict:
        """
        Main entry point. One signal in, one governed outcome out.
        Returns a result dict for DSOR and session reporting.
        """
        if self.ledger.state != SessionState.ACTIVE:
            return {"result": "BLOCKED", "reason": f"Session state: {self.ledger.state.value}"}

        logger.info(f"Processing signal {signal.signal_id} | {signal.symbol} {signal.side} @ ${signal.suggested_price}")

        # ── Run gate chain ──────────────────────────
        final_result, gate_records = self.gates.run_all_gates(signal)

        if final_result != GateResult.PASS:
            self._dsor(
                f"GATE_{final_result.value}",
                signal.signal_id,
                {"gates": [asdict(g) for g in gate_records], "signal": asdict(signal)},
                gate_result=final_result.value,
            )
            return {"result": final_result.value, "signal_id": signal.signal_id,
                    "gates_passed": sum(1 for g in gate_records if g.result == GateResult.PASS)}

        # ── All gates passed — place order ──────────
        client_order_id = self._generate_client_order_id(signal.signal_id)
        price_str = f"{signal.suggested_price:.2f}"
        qty_str = f"{signal.suggested_qty:.6f}"

        logger.info(f"Submitting to Gemini sandbox: {signal.symbol} {signal.side} {qty_str} @ ${price_str}")
        order_response = self.exchange.place_limit_order(
            symbol=signal.symbol,
            side=signal.side,
            price=price_str,
            quantity=qty_str,
            client_order_id=client_order_id,
        )

        if order_response.get("error"):
            self._dsor("ORDER_ERROR", signal.signal_id,
                       {"error": order_response, "signal": asdict(signal)})
            logger.error(f"Order placement failed: {order_response}")
            return {"result": "ORDER_ERROR", "error": order_response}

        kraken_txids = (order_response.get("result") or {}).get("txid") or []
        order_id = kraken_txids[0] if kraken_txids else order_response.get("order_id", "UNKNOWN")
        self.ledger.orders_placed += 1
        self.ledger.open_positions[order_id] = {
            "signal_id": signal.signal_id,
            "symbol": signal.symbol,
            "side": signal.side,
            "price": signal.suggested_price,
            "qty": signal.suggested_qty,
            "placed_at": datetime.now(timezone.utc).isoformat(),
            "status": order_response.get("is_live", False),
        }

        self._dsor("ORDER_PLACED", signal.signal_id,
                   {"order_response": order_response, "signal": asdict(signal)},
                   gate_result="PASS", order_id=order_id)

        logger.info(f"Order placed ✓ | order_id={order_id} | client_id={client_order_id}")
        return {
            "result": "ORDER_PLACED",
            "order_id": order_id,
            "client_order_id": client_order_id,
            "signal_id": signal.signal_id,
            "symbol": signal.symbol,
            "side": signal.side,
            "price": price_str,
            "qty": qty_str,
        }

    def process_close_signal(self, signal: AtroxSignal, kind: str, force_market: bool = False) -> dict:
        """
        Auto-execute a close signal (SELL or STOP) generated by Atrox Live.
        Bypasses HITL gate per pre-armed close-policy (operator-armed, time-bounded).
        Still runs gates 2/3/4 (symbol, size, drawdown). Records P&L net of fees.

        kind: "sell" | "stop"
        force_market: if True and STOP_ALLOW_MARKET, use Kraken market order
        """
        from aureon.thifur.kraken_client import ThifurHDoctrineLive
        # Kraken fee constants — duplicated here vs atrox_live.py to avoid
        # the live -> sandbox -> live circular import. Keep the two in sync.
        MAKER_FEE = 0.0016
        TAKER_FEE = 0.0025

        if self.ledger.state != SessionState.ACTIVE:
            return {"result": "BLOCKED", "reason": f"Session state: {self.ledger.state.value}"}

        # Pull entry price from the open position (assumes single-position discipline)
        entry_price = 0.0
        entry_txid = None
        if self.ledger.open_positions:
            entry_txid, entry_pos = next(iter(self.ledger.open_positions.items()))
            entry_price = float(entry_pos.get("price", 0))

        # Run gates (gate 1 / 5 already cleared by pre-arm; we still want
        # symbol whitelist + size + drawdown enforced as belt-and-braces)
        for gate_fn in (self.gates.gate2_symbol_whitelist,
                        self.gates.gate3_position_size,
                        self.gates.gate4_session_drawdown):
            rec = gate_fn(signal)
            if rec.result != GateResult.PASS:
                self._dsor(f"AUTO_{kind.upper()}_BLOCKED", signal.signal_id,
                           {"gate": asdict(rec), "signal": asdict(signal),
                            "kind": kind, "force_market": force_market},
                           gate_result=rec.result.value)
                return {"result": "BLOCKED", "reason": rec.reason, "gate": rec.gate_id}

        # Submit to exchange
        client_order_id = self._generate_client_order_id(signal.signal_id)
        qty_str = f"{signal.suggested_qty:.6f}"
        if force_market:
            order_response = self.exchange.place_market_order(
                symbol=signal.symbol,
                side=signal.side,
                quantity=qty_str,
                client_order_id=client_order_id,
            )
            order_type = "market"
        else:
            price_str = f"{signal.suggested_price:.1f}"
            order_response = self.exchange.place_limit_order(
                symbol=signal.symbol,
                side=signal.side,
                price=price_str,
                quantity=qty_str,
                client_order_id=client_order_id,
            )
            order_type = "limit"

        if order_response.get("error"):
            self._dsor(f"AUTO_{kind.upper()}_ERROR", signal.signal_id,
                       {"error": order_response, "signal": asdict(signal),
                        "kind": kind, "order_type": order_type})
            return {"result": "ORDER_ERROR", "error": order_response}

        # Extract Kraken txid (result.txid[0])
        kraken_txids = (order_response.get("result") or {}).get("txid") or []
        order_id = kraken_txids[0] if kraken_txids else "UNKNOWN"

        # P&L estimation (assumes immediate-fill semantics for sell side;
        # actual realized P&L will reconcile when Kraken reports the fill —
        # for v1 this is the operator-visible estimate).
        fee_pct = TAKER_FEE if order_type == "market" else MAKER_FEE
        notional = signal.suggested_price * signal.suggested_qty
        fee_usd = notional * fee_pct
        # If we're closing a long position, P&L = (exit - entry) * qty - exit_fee
        # entry fee was already booked at the open order
        gross_pnl = (signal.suggested_price - entry_price) * signal.suggested_qty if entry_price > 0 else 0.0
        net_pnl = gross_pnl - fee_usd

        self.ledger.orders_placed += 1
        self.ledger.auto_executions += 1
        self.ledger.realized_pnl_gross_usd += gross_pnl
        self.ledger.total_fees_usd += fee_usd
        self.ledger.realized_pnl_usd += net_pnl
        if net_pnl < 0:
            self.ledger.session_loss_usd += abs(net_pnl)

        # Close the open position (logical close — Kraken match settles it)
        if entry_txid and entry_txid in self.ledger.open_positions:
            del self.ledger.open_positions[entry_txid]

        self._dsor(f"AUTO_{kind.upper()}_EXECUTED", signal.signal_id,
                   {"order_response": order_response, "signal": asdict(signal),
                    "kind": kind, "order_type": order_type,
                    "entry_price": entry_price, "exit_price": signal.suggested_price,
                    "gross_pnl_usd": round(gross_pnl, 4),
                    "fee_usd": round(fee_usd, 4),
                    "net_pnl_usd": round(net_pnl, 4),
                    "closed_txid": entry_txid},
                   gate_result="PASS", order_id=order_id)

        logger.warning(
            f"AUTO-{kind.upper()} executed | order_id={order_id} | "
            f"order_type={order_type} | net_pnl=${net_pnl:.4f}"
        )
        return {
            "result": "ORDER_PLACED",
            "kind": kind,
            "order_id": order_id,
            "order_type": order_type,
            "signal_id": signal.signal_id,
            "entry_price": entry_price,
            "exit_price": signal.suggested_price,
            "gross_pnl_usd": round(gross_pnl, 4),
            "fee_usd": round(fee_usd, 4),
            "net_pnl_usd": round(net_pnl, 4),
        }

    def rollback(self, order_id: str, reason: str) -> dict:
        """
        Rollback — issue cancel on a specific order_id.
        Used when post-execution breach is detected.
        """
        logger.warning(f"ROLLBACK initiated | order_id={order_id} | reason={reason}")
        cancel_response = self.exchange.cancel_order(order_id)
        self.ledger.orders_cancelled += 1
        if order_id in self.ledger.open_positions:
            del self.ledger.open_positions[order_id]
        self._dsor("ROLLBACK", "ROLLBACK",
                   {"order_id": order_id, "reason": reason, "response": cancel_response},
                   order_id=order_id)
        return cancel_response

    def kill_switch(self, reason: str = "Manual kill switch") -> dict:
        """
        MiFID II RTS 6 kill switch.
        Cancels ALL open session orders. Halts session.
        Persists DSOR to Railway Volume so the evidence survives restarts.
        """
        logger.critical(f"KILL SWITCH ENGAGED | reason={reason}")
        self.ledger.state = SessionState.HALTED
        response = self.exchange.cancel_all_session_orders()
        self._dsor("KILL_SWITCH", "KILL_SWITCH",
                   {"reason": reason, "response": response,
                    "open_positions_at_halt": dict(self.ledger.open_positions)})
        self.ledger.open_positions.clear()
        try:
            self.export_dsor(to_volume=True)
        except Exception as e:
            logger.error(f"DSOR persist on kill failed: {type(e).__name__}: {e}")
        return response

    def get_balances(self) -> list:
        """Check sandbox account balances."""
        return self.exchange.get_balances()

    def get_current_price(self, symbol: str = "BTCUSD") -> float:
        """Get live sandbox price for signal calibration."""
        ticker = self.exchange.get_ticker(symbol)
        return float(ticker.get("last", 0.0))

    def session_report(self) -> dict:
        """Full session summary for DSOR and audit."""
        return {
            "session_id": self.session_id,
            "state": self.ledger.state.value,
            "started_at": self.ledger.started_at,
            "orders_placed": self.ledger.orders_placed,
            "orders_filled": self.ledger.orders_filled,
            "orders_cancelled": self.ledger.orders_cancelled,
            "auto_executions": self.ledger.auto_executions,
            "open_positions": len(self.ledger.open_positions),
            "realized_pnl_usd": round(self.ledger.realized_pnl_usd, 4),
            "realized_pnl_gross_usd": round(self.ledger.realized_pnl_gross_usd, 4),
            "total_fees_usd": round(self.ledger.total_fees_usd, 4),
            "session_loss_usd": round(self.ledger.session_loss_usd, 4),
            "gate_records_count": len(self.ledger.gate_records),
            "dsor_entries_count": len(self.ledger.dsor_entries),
            "doctrine": {
                "market_rail": getattr(self.doctrine, "MARKET_RAIL", "unspecified"),
                "max_position_usd": self.doctrine.MAX_POSITION_USD,
                "max_session_loss_usd": self.doctrine.MAX_SESSION_LOSS_USD,
                "max_orders": self.doctrine.MAX_ORDERS_PER_SESSION,
                "sandbox_only": self.doctrine.SANDBOX_ONLY,
                "hitl_required": self.doctrine.HITL_REQUIRED,
                "allowed_symbols": list(self.doctrine.ALLOWED_SYMBOLS),
            },
        }

    def export_dsor(self, path: str = None, to_volume: bool = False) -> str:
        """
        Export full DSOR as JSON for audit and SR 11-7 evidence packaging.

        path: optional explicit file path to write the export to.
        to_volume: if True, also persists to the Railway volume at
                   $RAILWAY_VOLUME_MOUNT_PATH/dsor/dsor_{session_id}_{ts}.json
                   (defaults to /data/dsor on Railway). Survives restarts.
        """
        import os, pathlib
        export = {
            "session_summary": self.session_report(),
            "gate_records": self.ledger.gate_records,
            "dsor_entries": self.ledger.dsor_entries,
            "open_positions": self.ledger.open_positions,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
        body = json.dumps(export, indent=2, cls=_DSOREncoder)
        if path:
            with open(path, "w") as f:
                f.write(body)
            logger.info(f"DSOR exported → {path}")
        if to_volume:
            try:
                base = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "/data")
                vol_dir = pathlib.Path(base) / "dsor"
                vol_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                vol_path = vol_dir / f"dsor_{self.session_id}_{ts}.json"
                vol_path.write_text(body)
                logger.info(f"DSOR persisted to volume: {vol_path}")
            except Exception as e:
                logger.error(f"DSOR volume persist failed: {type(e).__name__}: {e}")
        return body
