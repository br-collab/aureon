"""
fix_adapter.py — Aureon ↔ FIX 4.4 Translation Layer (Stub)
============================================================
Project Aureon | Kaladan L2 Execution Bridge

PURPOSE
-------
This module defines the translation contract between Aureon's internal
governance payload and the FIX 4.4 protocol used by institutional OMS/EMS
platforms (Bloomberg AIM, Charles River, Flextrade, Fidessa, etc.).

Aureon sits ABOVE the OMS in the execution stack:

    ┌────────────────────────────────────────────────────────┐
    │                   AUREON (Governance)                   │
    │  Verana L0 → Mentat L1 → Kaladan L2 → Thifur L3       │
    │                                                         │
    │  Decision: APPROVED (doctrine-stamped, hash-verified)  │
    └──────────────────────┬─────────────────────────────────┘
                           │
              translate_to_fix(aureon_decision)
                           │
                           ▼
    ┌────────────────────────────────────────────────────────┐
    │              EXISTING OMS / EMS LAYER                  │
    │   FIX NewOrderSingle (MsgType=D) → Exchange/Venue     │
    └────────────────────────────────────────────────────────┘

Aureon does NOT replace the OMS. It provides the governance gate that
PRECEDES order submission. Once Kaladan L2 marks a decision APPROVED,
this adapter constructs the FIX message that the OMS would consume.

INTEGRATION MODES
-----------------
Mode 1 — Direct FIX Session (future):
    Aureon opens a FIX session directly to the venue or prime broker.
    fix_adapter.py would call a FIX engine (QuickFIX/n, etc.) here.

Mode 2 — OMS Hand-off (current stub architecture):
    Aureon generates the FIX-compliant payload dict and passes it to the
    OMS via REST or MQ. The OMS handles the actual FIX session. Aureon
    retains the governance record and compliance report (PDF + email).

Mode 3 — Compliance Enrichment Only:
    Aureon's FIX payload is attached to the compliance trade report as a
    machine-readable block alongside the human-readable PDF. The OMS
    generates its own FIX message; Aureon provides the audit overlay.

STUB NOTICE
-----------
All functions below are stubs. They are correctly structured and fully
annotated to serve as the integration contract for a FIX engine vendor
or internal dev team. No live FIX session is opened in this file.
Replace the stub bodies with real FIX engine calls when integrating.

FIX 4.4 SPECIFICATION REFERENCES
---------------------------------
Tag 35  = MsgType        (D = NewOrderSingle, 8 = ExecutionReport)
Tag 49  = SenderCompID
Tag 56  = TargetCompID
Tag 11  = ClOrdID        (Aureon decision_id maps here)
Tag 55  = Symbol
Tag 54  = Side           (1=Buy, 2=Sell)
Tag 38  = OrderQty
Tag 40  = OrdType        (1=Market, 2=Limit)
Tag 44  = Price          (Limit price, omit for Market)
Tag 60  = TransactTime   (UTC, YYYYMMDD-HH:MM:SS)
Tag 167 = SecurityType   (CS, ETF, FXSPOT, CRYPTO, etc.)
Tag 460 = Product        (2=Commodity, 4=Currency, 5=Equity, 14=Other/Crypto)
Tag 207 = SecurityExchange (MIC code: XNAS, ARCX, XOFF, etc.)
Tag 15  = Currency       (ISO 4217)
Tag 58  = Text           (free text — Aureon doctrine hash embedded here)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

AUREON_SENDER_COMP_ID = "AUREON"          # Stub — replace with real CompID
DEFAULT_TARGET_COMP_ID = "OMS_PRIMARY"    # Stub — replace with OMS CompID
FIX_VERSION = "FIX.4.4"


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def translate_to_fix(aureon_decision: dict[str, Any]) -> dict[str, Any]:
    """
    Translate an Aureon APPROVED decision payload into a FIX 4.4
    NewOrderSingle (MsgType=D) field dictionary.

    Parameters
    ----------
    aureon_decision : dict
        The decision object from Aureon's internal state, as produced by
        Kaladan L2 after governance approval. Expected keys:

        Required
        --------
        decision_id     : str   — Aureon UUID, becomes FIX Tag 11 (ClOrdID)
        symbol          : str   — instrument ticker / pair
        direction       : str   — "BUY" or "SELL"
        quantity        : float — units to trade
        doctrine_hash   : str   — SHA-256 of governing doctrine version
        resolution      : str   — must be "APPROVED" to proceed

        Optional (from instrument reference / compliance report)
        --------------------------------------------------------
        isin            : str | None
        cusip           : str | None
        fix_type        : str   — FIX Tag 167 SecurityType
        fix_product     : int   — FIX Tag 460 Product
        mic             : str   — ISO 10383 execution venue
        currency        : str   — ISO 4217 settlement currency
        price           : float | None — limit price; None → Market order
        entity_lei      : str   — ISO 17442 LEI

    Returns
    -------
    dict
        FIX field dictionary keyed by tag number (int) and tag name (str).
        Suitable for serialisation to FIX wire format or REST hand-off to OMS.

    Raises
    ------
    ValueError
        If resolution is not APPROVED, or required fields are missing.
    """

    # ── Guard: only forward APPROVED decisions ──────────────────────────────
    resolution = aureon_decision.get("resolution", "")
    if resolution != "APPROVED":
        raise ValueError(
            f"[fix_adapter] Cannot translate non-APPROVED decision. "
            f"resolution='{resolution}', decision_id='{aureon_decision.get('decision_id')}'"
        )

    # ── Required fields ─────────────────────────────────────────────────────
    decision_id   = aureon_decision["decision_id"]
    symbol        = aureon_decision["symbol"]
    direction     = aureon_decision["direction"].upper()
    quantity      = float(aureon_decision["quantity"])
    doctrine_hash = aureon_decision.get("doctrine_hash", "")

    # ── Optional / enriched fields ──────────────────────────────────────────
    fix_type    = aureon_decision.get("fix_type", "CS")
    fix_product = aureon_decision.get("fix_product", 5)
    mic         = aureon_decision.get("mic", "XNAS")
    currency    = aureon_decision.get("currency", "USD")
    price       = aureon_decision.get("price")          # None → Market order

    # ── FIX side mapping ────────────────────────────────────────────────────
    side_map = {"BUY": "1", "SELL": "2"}
    side = side_map.get(direction)
    if side is None:
        raise ValueError(f"[fix_adapter] Unknown direction: '{direction}'")

    # ── Order type ──────────────────────────────────────────────────────────
    ord_type = "2" if price is not None else "1"   # 2=Limit, 1=Market

    # ── Timestamp ───────────────────────────────────────────────────────────
    transact_time = datetime.now(timezone.utc).strftime("%Y%m%d-%H:%M:%S")

    # ── Aureon doctrine provenance embedded in Tag 58 (Text) ────────────────
    text_field = f"AUREON|DOCTRINE_HASH={doctrine_hash[:16]}...|DECISION={decision_id}"

    # ── Build FIX field dict ─────────────────────────────────────────────────
    fix_msg: dict[str, Any] = {
        # Header
        "BeginString":    FIX_VERSION,               # Tag 8
        "MsgType":        "D",                        # Tag 35 — NewOrderSingle
        "SenderCompID":   AUREON_SENDER_COMP_ID,      # Tag 49
        "TargetCompID":   DEFAULT_TARGET_COMP_ID,     # Tag 56
        "MsgSeqNum":      _next_seq_num(),            # Tag 34 — stub counter

        # Order identity
        "ClOrdID":        decision_id,                # Tag 11
        "Symbol":         symbol,                     # Tag 55
        "Side":           side,                       # Tag 54
        "OrderQty":       quantity,                   # Tag 38
        "OrdType":        ord_type,                   # Tag 40
        "TransactTime":   transact_time,              # Tag 60

        # Instrument classification (FIX 4.4 Security Definition)
        "SecurityType":   fix_type,                   # Tag 167
        "Product":        fix_product,                # Tag 460
        "SecurityExchange": mic,                      # Tag 207
        "Currency":       currency,                   # Tag 15

        # Aureon provenance
        "Text":           text_field,                 # Tag 58
    }

    # Limit price — only include when order type is Limit
    if price is not None:
        fix_msg["Price"] = float(price)               # Tag 44

    # ISIN as SecurityID when available
    isin = aureon_decision.get("isin")
    if isin:
        fix_msg["SecurityID"]       = isin            # Tag 48
        fix_msg["SecurityIDSource"] = "4"             # Tag 22 — 4=ISIN

    return fix_msg


def translate_from_fix_execution(fix_exec_report: dict[str, Any]) -> dict[str, Any]:
    """
    Translate a FIX 4.4 ExecutionReport (MsgType=8) back into Aureon's
    internal execution confirmation format.

    This is called when the OMS/venue returns an execution report so
    Kaladan L2 can update its trade lifecycle state (T+0/T+1 settlement,
    fills, partial fills, cancellations).

    Parameters
    ----------
    fix_exec_report : dict
        FIX ExecutionReport field dictionary.

        Key FIX fields consumed
        -----------------------
        ClOrdID      (Tag 11) → maps back to Aureon decision_id
        ExecID       (Tag 17) → venue execution reference
        ExecType     (Tag 150) → 0=New, 1=PartialFill, 2=Fill, 4=Cancel, 8=Reject
        OrdStatus    (Tag 39) → 0=New, 1=PartiallyFilled, 2=Filled, 4=Cancelled
        LastPx       (Tag 31) → actual fill price
        LastQty      (Tag 32) → actual fill quantity
        LeavesQty    (Tag 151) → remaining unfilled quantity
        CumQty       (Tag 14) → cumulative filled quantity
        TransactTime (Tag 60) → execution timestamp

    Returns
    -------
    dict
        Aureon execution confirmation payload for updating decision state.
    """

    exec_type_map = {
        "0": "NEW",
        "1": "PARTIAL_FILL",
        "2": "FILL",
        "4": "CANCELLED",
        "8": "REJECTED",
    }

    exec_type_code = str(fix_exec_report.get("ExecType", ""))
    aureon_exec_status = exec_type_map.get(exec_type_code, f"UNKNOWN_{exec_type_code}")

    return {
        "decision_id":    fix_exec_report.get("ClOrdID"),
        "exec_id":        fix_exec_report.get("ExecID"),
        "exec_status":    aureon_exec_status,
        "fill_price":     fix_exec_report.get("LastPx"),
        "fill_qty":       fix_exec_report.get("LastQty"),
        "leaves_qty":     fix_exec_report.get("LeavesQty"),
        "cum_qty":        fix_exec_report.get("CumQty"),
        "exec_timestamp": fix_exec_report.get("TransactTime"),
        "raw_fix":        fix_exec_report,    # retain original for audit
    }


def serialize_to_wire(fix_msg: dict[str, Any]) -> str:
    """
    STUB: Serialize a FIX field dictionary to FIX wire format.

    In production this would be handled by a FIX engine library
    (e.g., QuickFIX/n, SimCorp, or a prime broker FIX gateway).
    The pipe-delimited string below is for illustration and logging only.

    FIX wire format uses SOH (ASCII 0x01) as field delimiter.
    This stub uses '|' for human readability.

    Parameters
    ----------
    fix_msg : dict
        FIX field dictionary as produced by translate_to_fix().

    Returns
    -------
    str
        Human-readable pipe-delimited FIX message string (NOT wire-ready).
    """

    tag_map = {
        "BeginString":      8,
        "MsgType":          35,
        "SenderCompID":     49,
        "TargetCompID":     56,
        "MsgSeqNum":        34,
        "ClOrdID":          11,
        "Symbol":           55,
        "Side":             54,
        "OrderQty":         38,
        "OrdType":          40,
        "Price":            44,
        "TransactTime":     60,
        "SecurityType":     167,
        "Product":          460,
        "SecurityExchange": 207,
        "Currency":         15,
        "SecurityID":       48,
        "SecurityIDSource": 22,
        "Text":             58,
    }

    parts = []
    for name, value in fix_msg.items():
        tag_num = tag_map.get(name, name)
        parts.append(f"{tag_num}={value}")

    return "|".join(parts)


def validate_fix_message(fix_msg: dict[str, Any]) -> list[str]:
    """
    Validate a FIX NewOrderSingle for required fields and value ranges.

    Returns a list of validation error strings. Empty list = valid.
    """

    errors: list[str] = []

    required = ["MsgType", "ClOrdID", "Symbol", "Side", "OrderQty", "OrdType", "TransactTime"]
    for field in required:
        if field not in fix_msg:
            errors.append(f"Missing required field: {field}")

    if fix_msg.get("MsgType") != "D":
        errors.append(f"MsgType must be 'D' (NewOrderSingle), got: {fix_msg.get('MsgType')}")

    if fix_msg.get("Side") not in ("1", "2"):
        errors.append(f"Side must be '1' (Buy) or '2' (Sell), got: {fix_msg.get('Side')}")

    if fix_msg.get("OrdType") == "2" and "Price" not in fix_msg:
        errors.append("OrdType=2 (Limit) requires Price field")

    qty = fix_msg.get("OrderQty", 0)
    try:
        if float(qty) <= 0:
            errors.append(f"OrderQty must be > 0, got: {qty}")
    except (TypeError, ValueError):
        errors.append(f"OrderQty must be numeric, got: {qty}")

    return errors


# ---------------------------------------------------------------------------
# INTERNAL HELPERS
# ---------------------------------------------------------------------------

_seq_counter = 0

def _next_seq_num() -> int:
    """Monotonic FIX MsgSeqNum counter (in-memory stub, resets on restart)."""
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


# ---------------------------------------------------------------------------
# USAGE EXAMPLE (run this file directly to see stub output)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    # Simulated Aureon approved decision (as produced by Kaladan L2)
    sample_decision = {
        "decision_id":   "dec-aureon-0042",
        "symbol":        "AAPL",
        "direction":     "BUY",
        "quantity":      500,
        "price":         None,           # Market order
        "resolution":    "APPROVED",
        "doctrine_hash": "a3f9c2e1b4d7890f1234567890abcdef1234567890abcdef1234567890abcdef",
        "isin":          "US0378331005",
        "cusip":         "037833100",
        "fix_type":      "CS",
        "fix_product":   5,
        "mic":           "XNAS",
        "currency":      "USD",
        "entity_lei":    "AUREON-LEI-PENDING-00001",
    }

    print("=" * 62)
    print("  Aureon FIX Adapter — Stub Output")
    print("=" * 62)

    fix_payload = translate_to_fix(sample_decision)
    errors = validate_fix_message(fix_payload)

    print("\n[1] FIX field dictionary:")
    print(json.dumps(fix_payload, indent=2))

    print("\n[2] Validation:", "PASS" if not errors else f"FAIL: {errors}")

    print("\n[3] Wire format preview (pipe-delimited stub):")
    print(serialize_to_wire(fix_payload))

    print("\n[4] Simulated ExecutionReport → Aureon confirmation:")
    sample_exec = {
        "ClOrdID":      "dec-aureon-0042",
        "ExecID":       "EXEC-XNAS-0099",
        "ExecType":     "2",        # Fill
        "OrdStatus":    "2",        # Filled
        "LastPx":       213.45,
        "LastQty":      500,
        "LeavesQty":    0,
        "CumQty":       500,
        "TransactTime": "20260310-14:30:01",
    }
    aureon_confirm = translate_from_fix_execution(sample_exec)
    print(json.dumps({k: v for k, v in aureon_confirm.items() if k != "raw_fix"}, indent=2))
