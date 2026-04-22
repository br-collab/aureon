"""
Aureon MMF — Persistence (Phase 2 P2-1)

PURPOSE:     Durable storage for fund_state and nav_engine snapshots
             so Phase 1's in-memory state survives Railway redeploys.
             Mirrors the atomic tempfile+rename pattern from
             aureon/persistence/store.py; MMF state is smaller so no
             salvage logic needed here.

INPUTS:      Called by fund_state.apply_subscription /
             apply_redemption / reset_daily_counters, and by
             nav_engine.run_sweep (on successful commit) and
             reset_circuit. Snapshots are Decimal-stringified dicts.

OUTPUTS:     Two files in the Railway volume (or ~/.aureon/ locally):
               aureon_mmf_fund_state.json
               aureon_mmf_nav_state.json
             Each holds a flat JSON object with one snapshot +
             a saved_at ISO timestamp.

ASSUMPTIONS: Failure to persist is non-fatal — logged and swallowed.
             The engine keeps operating with in-memory state; on the
             NEXT successful write the latest state lands. Phase 1
             behavior survives if persistence is broken.

AUDIT NOTES: Atomic write via temp + os.replace. Each engine writes
             to its own file — no cross-engine atomicity, so a
             partial persist (fund loaded, nav missing) degrades
             gracefully: the engine with no file starts fresh.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("aureon.mmf.persistence")


def _base_dir() -> Path:
    """Resolve the persistence base directory.

    Railway sets RAILWAY_VOLUME_MOUNT_PATH when a volume is attached;
    we write inside it. Local / dev falls back to ~/.aureon/. The
    directory is created on demand."""
    vol = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if vol:
        base = Path(vol)
    else:
        base = Path.home() / ".aureon"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.warning("mmf persistence: mkdir %s failed: %s: %s",
                    base, type(e).__name__, e)
    return base


def _file_for(key: str) -> Path:
    return _base_dir() / f"aureon_mmf_{key}_state.json"


def save_snapshot(key: str, snapshot: dict) -> bool:
    """Atomic write of a snapshot dict to the keyed file. Returns
    True on success, False on any error (logged, not raised). Adds a
    saved_at ISO timestamp and schema_version to the envelope."""
    path = _file_for(key)
    envelope = {
        "schema_version": 1,
        "key":            key,
        "saved_at":       datetime.now(timezone.utc).isoformat(),
        "snapshot":       snapshot,
    }
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(envelope, indent=2, default=str))
        os.replace(tmp, path)
        return True
    except Exception as e:
        log.warning("mmf persistence: save %s failed: %s: %s",
                    path, type(e).__name__, e)
        # Best-effort cleanup of the tempfile if the rename didn't happen.
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def load_snapshot(key: str) -> Optional[dict]:
    """Load the snapshot dict for the given key, or None if the file
    doesn't exist or is unreadable/malformed. Non-fatal on error —
    the engine falls back to fresh state.

    Returns the INNER snapshot, not the envelope."""
    path = _file_for(key)
    if not path.exists():
        return None
    try:
        envelope = json.loads(path.read_text())
        return envelope.get("snapshot") if isinstance(envelope, dict) else None
    except Exception as e:
        log.warning("mmf persistence: load %s failed: %s: %s",
                    path, type(e).__name__, e)
        return None
