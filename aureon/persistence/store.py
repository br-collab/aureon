"""
aureon.persistence.store
========================
State persistence boundary for Aureon Grid 3.

Handles serialisation of critical aureon_state fields to disk and
restoration on restart.  Ephemeral data (prices, cycle_count, etc.)
is always recalculated at runtime and is never persisted.
"""

import json
import os
from datetime import datetime, timezone


def save_state(*, state, lock, state_file, resolve_mmf_provider, log_error):
    """
    Serialize critical aureon_state fields to *state_file* atomically.
    Called in a background thread after every HITL decision so it never
    blocks the HTTP response.
    """
    try:
        with lock:
            trade_reports = []
            for r in state.get("trade_reports", []):
                trade_reports.append({k: v for k, v in r.items() if k != "pdf_bytes"})
            snapshot = {
                "positions":         list(state.get("positions", [])),
                "cash":              state.get("cash", 0.0),
                "trades":            list(state.get("trades", [])),
                "trade_reports":     trade_reports,
                "source_documents":  list(state.get("source_documents", [])),
                "authority_log":     list(state.get("authority_log", [])),
                "compliance_alerts": list(state.get("compliance_alerts", [])),
                "alert_history":     list(state.get("alert_history", [])),
                # ── MMF / Cash management ──────────────────────────
                "mmf_balance":       state.get("mmf_balance", 0.0),
                "mmf_yield_accrued": state.get("mmf_yield_accrued", 0.0),
                "mmf_provider":      resolve_mmf_provider(state.get("mmf_provider")),
                "sweep_log":         list(state.get("sweep_log", [])),
                "saved_at":          datetime.now(timezone.utc).isoformat(),
            }
        tmp_file = state_file + ".tmp"
        with open(tmp_file, "w") as fh:
            json.dump(snapshot, fh, indent=2)
        os.replace(tmp_file, state_file)
        print(
            f"[AUREON] State saved — {len(snapshot['positions'])} positions, "
            f"{len(snapshot['trades'])} trades"
        )
    except Exception as exc:
        log_error("WARN", "persistence.save_state", str(exc))


def load_state(*, state_file, log_error):
    """
    Load persisted state from *state_file*.
    Returns the snapshot dict on success, or None if no file / parse error.
    Does NOT acquire any lock — must be called before the lock block in
    run_doctrine_stack() to avoid a deadlock.
    """
    if not os.path.exists(state_file):
        print("[AUREON] No persisted state found — initialising from INITIAL_POSITIONS")
        return None
    try:
        with open(state_file, "r") as fh:
            snapshot = json.load(fh)
        n_pos    = len(snapshot.get("positions", []))
        n_trades = len(snapshot.get("trades", []))
        saved_at = snapshot.get("saved_at", "unknown")
        print(
            f"[AUREON] Persisted state loaded — {n_pos} positions, "
            f"{n_trades} trades — last saved {saved_at}"
        )
        return snapshot
    except Exception as exc:
        log_error("WARN", "persistence.load_state", f"{exc} — attempting salvage")

    # ── Salvage attempt on corrupted JSON ─────────────────────────
    try:
        text = open(state_file, "r", errors="ignore").read()
        snapshot = {}

        def _extract(key, next_key=None):
            key_pat = f'"{key}":'
            start = text.find(key_pat)
            if start == -1:
                return None
            start += len(key_pat)
            if next_key:
                end = text.find(f',\n  "{next_key}":', start)
                if end == -1:
                    return None
                raw = text[start:end].strip()
            else:
                raw = text[start:].strip()
            return raw

        positions_raw = _extract("positions", "cash")
        cash_raw      = _extract("cash", "trades")
        trades_raw    = _extract("trades", "trade_reports")
        if positions_raw:
            snapshot["positions"] = json.loads(positions_raw)
        if cash_raw:
            snapshot["cash"] = json.loads(cash_raw)
        if trades_raw:
            snapshot["trades"] = json.loads(trades_raw)

        snapshot.setdefault("trade_reports", [])
        snapshot.setdefault("source_documents", [])
        snapshot.setdefault("authority_log", [])
        snapshot.setdefault("compliance_alerts", [])
        snapshot.setdefault("alert_history", [])
        snapshot.setdefault("mmf_balance", 0.0)
        snapshot.setdefault("mmf_yield_accrued", 0.0)
        snapshot.setdefault("sweep_log", [])
        snapshot["saved_at"] = datetime.now(timezone.utc).isoformat()

        if (
            snapshot.get("positions") is not None
            and snapshot.get("trades") is not None
            and "cash" in snapshot
        ):
            print(
                f"[AUREON] Salvaged corrupted state — "
                f"{len(snapshot['positions'])} positions, {len(snapshot['trades'])} trades"
            )
            return snapshot
    except Exception as salvage_exc:
        log_error("WARN", "persistence.load_state", f"{salvage_exc} — salvage failed")

    print("[AUREON] Falling back to INITIAL_POSITIONS")
    return None
