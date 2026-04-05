"""Explicit persistence boundary for the prototype DSOR state."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable


def save_state(
    state: dict[str, Any],
    lock: Any,
    state_file: str,
    resolve_mmf_provider: Callable[[Any], dict[str, Any]],
    log_error: Callable[[str, str, str], None],
) -> None:
    """Persist the subset of state that must survive restarts."""
    try:
        with lock:
            trade_reports = [{k: v for k, v in report.items() if k != "pdf_bytes"} for report in state["trade_reports"]]
            snapshot = {
                "positions": list(state["positions"]),
                "cash": state["cash"],
                "trades": list(state["trades"]),
                "trade_reports": trade_reports,
                "source_documents": list(state.get("source_documents", [])),
                "authority_log": list(state["authority_log"]),
                "compliance_alerts": list(state["compliance_alerts"]),
                "alert_history": list(state["alert_history"]),
                "mmf_balance": state.get("mmf_balance", 0.0),
                "mmf_yield_accrued": state.get("mmf_yield_accrued", 0.0),
                "mmf_provider": resolve_mmf_provider(state.get("mmf_provider")),
                "sweep_log": list(state.get("sweep_log", [])),
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
        tmp_file = state_file + ".tmp"
        with open(tmp_file, "w") as fh:
            json.dump(snapshot, fh, indent=2)
        os.replace(tmp_file, state_file)
        print(f"[AUREON] State saved — {len(snapshot['positions'])} positions, {len(snapshot['trades'])} trades")
    except Exception as exc:
        log_error("WARN", "_save_state", str(exc))


def load_state(
    state_file: str,
    log_error: Callable[[str, str, str], None],
) -> dict[str, Any] | None:
    """Load or salvage persisted state for the prototype DSOR."""
    if not os.path.exists(state_file):
        print("[AUREON] No persisted state found — initialising from INITIAL_POSITIONS")
        return None

    try:
        with open(state_file, "r") as fh:
            snapshot = json.load(fh)
        n_pos = len(snapshot.get("positions", []))
        n_trades = len(snapshot.get("trades", []))
        saved_at = snapshot.get("saved_at", "unknown")
        print(f"[AUREON] Persisted state loaded — {n_pos} positions, {n_trades} trades — last saved {saved_at}")
        return snapshot
    except Exception as exc:
        log_error("WARN", "_load_state", f"{exc} — attempting salvage from corrupted state")

    try:
        text = open(state_file, "r", errors="ignore").read()
        snapshot: dict[str, Any] = {}

        def _extract(key: str, next_key: str | None = None) -> str | None:
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
        cash_raw = _extract("cash", "trades")
        trades_raw = _extract("trades", "trade_reports")
        if positions_raw:
            snapshot["positions"] = json.loads(positions_raw)
        if cash_raw:
            snapshot["cash"] = json.loads(cash_raw)
        if trades_raw:
            snapshot["trades"] = json.loads(trades_raw)

        snapshot["trade_reports"] = []
        snapshot["source_documents"] = []
        snapshot["authority_log"] = []
        snapshot["compliance_alerts"] = []
        snapshot["alert_history"] = []
        snapshot["mmf_balance"] = 0.0
        snapshot["mmf_yield_accrued"] = 0.0
        snapshot["sweep_log"] = []
        snapshot["saved_at"] = datetime.now(timezone.utc).isoformat()

        if snapshot.get("positions") is not None and snapshot.get("trades") is not None and "cash" in snapshot:
            print(
                f"[AUREON] Salvaged corrupted state — {len(snapshot['positions'])} positions, "
                f"{len(snapshot['trades'])} trades"
            )
            return snapshot
    except Exception as salvage_exc:
        log_error("WARN", "_load_state", f"{salvage_exc} — salvage failed")

    print("[AUREON] Falling back to INITIAL_POSITIONS")
    return None
