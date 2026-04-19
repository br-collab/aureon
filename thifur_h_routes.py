"""
Thifur-H Flask Routes — Drop into server.py
=============================================
Add these routes to the existing Aureon Flask server.

SETUP in server.py:
  1. Import at top:
       from aureon.thifur.thifur_h import ThifurH, AtroxSignal
       from aureon.thifur.atrox_sandbox import AtroxSandboxSignalGenerator
       from aureon.thifur.kraken_client import KrakenLiveClient, ThifurHDoctrineLive
       import os

  2. Initialize after app = Flask(__name__):
       thifur_h_engine = None   # initialized on first session start

  3. Paste the routes below into server.py

ROUTES ADDED:
  POST /api/thifur-h/session/start    — initialize Thifur-H session
  POST /api/thifur-h/signal           — Atrox generates signal, surfaces for CAOM-001 approval
  POST /api/thifur-h/approve          — CAOM-001 approves signal, runs gates, submits to Kraken
  POST /api/thifur-h/rollback         — cancel specific order by txid
  POST /api/thifur-h/kill-switch      — cancel ALL open orders, halt session
  GET  /api/thifur-h/session          — session status and ledger summary
  GET  /api/thifur-h/dsor             — full DSOR export
  GET  /api/thifur-h/balance          — Kraken account balance
"""

# ─────────────────────────────────────────────────────────────────
# PASTE BELOW INTO server.py
# ─────────────────────────────────────────────────────────────────

THIFUR_H_ROUTES = '''

# ══════════════════════════════════════════════════════════════════
# THIFUR-H — ADAPTIVE EXECUTION INTELLIGENCE — PHASE 2 ACTIVATION
# CAOM-001 · SR 11-7 Tier 1 · Kraken Live Account
# ══════════════════════════════════════════════════════════════════

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aureon.thifur.thifur_h import (
    ThifurH, AtroxSignal, SessionState, ThifurHDoctrine
)
from aureon.thifur.atrox_sandbox import AtroxSandboxSignalGenerator
from aureon.thifur.kraken_client import KrakenLiveClient, ThifurHDoctrineLive

# Global session — one active session at a time per CAOM-001 doctrine
_thifur_h_session = None
_atrox_generator = AtroxSandboxSignalGenerator()
_pending_signal = None   # Signal staged for CAOM-001 approval


def _get_kraken_engine():
    """Initialize Thifur-H with Kraken live client."""
    api_key = os.environ.get("KRAKEN_API_KEY", "")
    api_secret = os.environ.get("KRAKEN_API_SECRET", "")
    if not api_key or not api_secret:
        return None, "KRAKEN_API_KEY or KRAKEN_API_SECRET not set in environment"
    engine = ThifurH.__new__(ThifurH)
    engine.session_id = f"THIFUR-H-KRAKEN-{int(__import__('time').time())}"
    from aureon.thifur.thifur_h import SessionLedger, ThifurHGates, SessionState
    from datetime import datetime, timezone
    engine.ledger = SessionLedger(
        session_id=engine.session_id,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    engine.gates = ThifurHGates(engine.ledger)
    engine.exchange = KrakenLiveClient(api_key, api_secret)
    engine.ledger.state = SessionState.ACTIVE
    return engine, None


@app.route("/api/thifur-h/session/start", methods=["POST"])
def thifur_h_start_session():
    """
    Start a new Thifur-H session.
    CAOM-001 operator must explicitly start each session.
    """
    global _thifur_h_session
    if _thifur_h_session and _thifur_h_session.ledger.state == SessionState.ACTIVE:
        return jsonify({
            "status": "error",
            "message": "Session already active. Kill or close existing session first.",
            "session_id": _thifur_h_session.session_id,
        }), 400

    engine, error = _get_kraken_engine()
    if error:
        return jsonify({"status": "error", "message": error}), 500

    _thifur_h_session = engine
    return jsonify({
        "status": "ok",
        "message": "Thifur-H session started. CAOM-001 active.",
        "session_id": engine.session_id,
        "doctrine": {
            "max_position_usd": ThifurHDoctrineLive.MAX_POSITION_USD,
            "max_session_loss_usd": ThifurHDoctrineLive.MAX_SESSION_LOSS_USD,
            "max_orders": ThifurHDoctrineLive.MAX_ORDERS_PER_SESSION,
            "hitl_required": ThifurHDoctrineLive.HITL_REQUIRED,
            "allowed_symbols": list(ThifurHDoctrineLive.ALLOWED_SYMBOLS),
        }
    })


@app.route("/api/thifur-h/signal", methods=["POST"])
def thifur_h_generate_signal():
    """
    Atrox generates a signal and stages it for CAOM-001 approval.
    Signal is NOT sent to exchange. It is held pending /approve.

    Body (optional):
      { "side": "buy" | "sell", "breach_test": "size" | "symbol" | "no_approval" }
    """
    global _pending_signal

    if not _thifur_h_session:
        return jsonify({"status": "error", "message": "No active session. POST /api/thifur-h/session/start first."}), 400

    body = request.get_json(silent=True) or {}
    breach_test = body.get("breach_test")
    side = body.get("side", "buy")

    if breach_test:
        signal = _atrox_generator.generate_breach_signal(breach_test)
    elif side == "sell":
        signal = _atrox_generator.generate_sell_signal()
    else:
        signal = _atrox_generator.generate_buy_signal()

    if not signal:
        return jsonify({"status": "error", "message": "Atrox: Could not fetch price data"}), 503

    # Override price fetch with Kraken live price
    live_price = _thifur_h_session.exchange.get_current_price("XBTUSD")
    if live_price > 0 and not breach_test:
        from aureon.thifur.kraken_client import ThifurHDoctrineLive
        offset = -0.001 if side == "buy" else 0.001
        signal.suggested_price = round(live_price * (1 + offset), 2)
        signal.symbol = "XBTUSD"   # Kraken symbol
        signal.suggested_qty = ThifurHDoctrineLive.MAX_ORDER_QTY_BTC

    _pending_signal = signal

    return jsonify({
        "status": "pending_caom_approval",
        "signal_id": signal.signal_id,
        "symbol": signal.symbol,
        "side": signal.side,
        "price": signal.suggested_price,
        "qty": signal.suggested_qty,
        "position_usd": round(signal.suggested_price * signal.suggested_qty, 2),
        "confidence": signal.confidence,
        "rationale": signal.rationale,
        "caom_approved": signal.caom_approved,
        "next_step": "POST /api/thifur-h/approve to approve or discard this signal",
    })


@app.route("/api/thifur-h/approve", methods=["POST"])
def thifur_h_approve_signal():
    """
    CAOM-001 operator approves the pending signal.
    Runs all five gates. Submits to Kraken if all pass.

    Body:
      { "approved": true | false }
    """
    global _pending_signal

    if not _thifur_h_session:
        return jsonify({"status": "error", "message": "No active session."}), 400
    if not _pending_signal:
        return jsonify({"status": "error", "message": "No pending signal. Generate one first via /api/thifur-h/signal."}), 400

    body = request.get_json(silent=True) or {}
    approved = body.get("approved", False)

    if not approved:
        signal_id = _pending_signal.signal_id
        _pending_signal = None
        return jsonify({
            "status": "declined",
            "message": "Signal declined by CAOM-001 operator. No order submitted.",
            "signal_id": signal_id,
        })

    # Stamp CAOM-001 approval
    from datetime import datetime, timezone
    _pending_signal.caom_approved = True
    _pending_signal.approval_timestamp = datetime.now(timezone.utc).isoformat()

    result = _thifur_h_session.process_signal(_pending_signal)
    _pending_signal = None

    return jsonify({
        "status": "ok",
        "result": result,
        "session_summary": _thifur_h_session.session_report(),
    })


@app.route("/api/thifur-h/rollback", methods=["POST"])
def thifur_h_rollback():
    """
    Cancel a specific order by Kraken txid.
    Body: { "txid": "XXXXXX-XXXXX-XXXXXX", "reason": "..." }
    """
    if not _thifur_h_session:
        return jsonify({"status": "error", "message": "No active session."}), 400

    body = request.get_json(silent=True) or {}
    txid = body.get("txid")
    reason = body.get("reason", "Manual rollback by CAOM-001 operator")

    if not txid:
        return jsonify({"status": "error", "message": "txid required"}), 400

    result = _thifur_h_session.rollback(txid, reason)
    return jsonify({"status": "ok", "rollback_result": result})


@app.route("/api/thifur-h/kill-switch", methods=["POST"])
def thifur_h_kill_switch():
    """
    MiFID II RTS 6 kill switch.
    Cancels ALL open Kraken orders. Halts session.
    Body (optional): { "reason": "..." }
    """
    global _thifur_h_session, _pending_signal

    if not _thifur_h_session:
        return jsonify({"status": "error", "message": "No active session."}), 400

    body = request.get_json(silent=True) or {}
    reason = body.get("reason", "Manual kill switch — CAOM-001 operator")

    result = _thifur_h_session.kill_switch(reason)
    _pending_signal = None

    return jsonify({
        "status": "halted",
        "message": "Kill switch engaged. All orders cancelled. Session halted.",
        "kill_switch_result": result,
        "session_summary": _thifur_h_session.session_report(),
    })


@app.route("/api/thifur-h/session", methods=["GET"])
def thifur_h_session_status():
    """Current session status and ledger summary."""
    if not _thifur_h_session:
        return jsonify({"status": "no_session", "message": "No active Thifur-H session."})
    return jsonify({
        "status": "ok",
        "session": _thifur_h_session.session_report(),
        "pending_signal": _pending_signal.signal_id if _pending_signal else None,
    })


@app.route("/api/thifur-h/dsor", methods=["GET"])
def thifur_h_dsor_export():
    """Full DSOR export — SR 11-7 evidence package."""
    if not _thifur_h_session:
        return jsonify({"status": "no_session"}), 404
    dsor_json = _thifur_h_session.export_dsor()
    import json
    return jsonify(json.loads(dsor_json))


@app.route("/api/thifur-h/balance", methods=["GET"])
def thifur_h_balance():
    """Kraken account balance check."""
    if not _thifur_h_session:
        return jsonify({"status": "error", "message": "No active session."}), 400
    balance = _thifur_h_session.exchange.get_balance()
    return jsonify({"status": "ok", "balance": balance})

'''

# ─────────────────────────────────────────────────────────────────
# USAGE GUIDE
# ─────────────────────────────────────────────────────────────────

USAGE = """
Thifur-H API — Governed Trading Flow
======================================

1. Start session:
   curl -X POST https://aureon-production.up.railway.app/api/thifur-h/session/start

2. Generate Atrox signal (buy):
   curl -X POST https://aureon-production.up.railway.app/api/thifur-h/signal \\
     -H "Content-Type: application/json" \\
     -d '{"side": "buy"}'

3. CAOM-001 approve signal → runs all 5 gates → submits to Kraken if clean:
   curl -X POST https://aureon-production.up.railway.app/api/thifur-h/approve \\
     -H "Content-Type: application/json" \\
     -d '{"approved": true}'

4. Check session status:
   curl https://aureon-production.up.railway.app/api/thifur-h/session

5. Rollback a specific order:
   curl -X POST https://aureon-production.up.railway.app/api/thifur-h/rollback \\
     -H "Content-Type: application/json" \\
     -d '{"txid": "XXXXXX-XXXXX-XXXXXX", "reason": "test rollback"}'

6. Kill switch (all orders):
   curl -X POST https://aureon-production.up.railway.app/api/thifur-h/kill-switch

7. DSOR export:
   curl https://aureon-production.up.railway.app/api/thifur-h/dsor

BREACH TESTS (gate validation):
   curl -X POST .../api/thifur-h/signal -d '{"breach_test": "no_approval"}'  # Gate 1
   curl -X POST .../api/thifur-h/signal -d '{"breach_test": "symbol"}'       # Gate 2
   curl -X POST .../api/thifur-h/signal -d '{"breach_test": "size"}'         # Gate 3
"""

if __name__ == "__main__":
    print(USAGE)
