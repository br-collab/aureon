"""AureonStateDSORStore — bridge cockpit DSOR records into the unified,
persisted audit trail (WS-1 · AUR-COCKPIT-001, AUR-CANONICAL-001 v1.6 Axiom 4).

The Clearing Operator Cockpit runs its Beat-2 gates through the Settlement
Operations Analyst, which appends a pre-trade DSOR record (telemetry on a
clean pass, escalation on a hold). The prototype sink kept those records in
process memory only — so the cockpit cycle never reached the unified lineage
and died on restart.

This store is the bridge. It preserves the append-only invariant (Axiom 4:
one non-correction record per ``operation_id``; no update, no delete) AND, on
every append, mirrors a compact, JSON-safe record into ``state[log_key]`` —
the same ``aureon_state`` that ``aureon.persistence.store`` persists across
deploys (WS-0.1). The cockpit's decisions therefore survive restarts and
surface in the DSOR conventions the dashboard reads.

The store is dependency-free: it takes any mapping ``state`` and any
context-manager ``lock`` (e.g. ``threading.Lock``), so it works identically
in the production server and in tests.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class DSORAppendOnlyError(Exception):
    """Raised when an append would overwrite an existing (non-correction)
    record for an ``operation_id``. Per Axiom 4 (immutable lineage)."""


@dataclass(frozen=True)
class BridgedDSORRecord:
    """Immutable DTG-stamped wrapper the store returns. ``record_id`` is what
    the cockpit carries into the emitted instruction package."""

    output: Any
    dtg: datetime
    kind: str
    record_id: uuid.UUID = field(default_factory=uuid.uuid4)
    correction_of: uuid.UUID | None = None


class AureonStateDSORStore:
    """Append-only DSOR store that mirrors records into persisted state.

    Interface parity with the SQLite / in-memory ``DSORStore``: ``append``
    and ``replay`` only. On ``append`` it also inserts a compact record at the
    head of ``state[log_key]`` under ``lock`` and trims to ``cap``.
    """

    def __init__(self, state, lock, *, log_key: str = "cockpit_dsor_log", cap: int = 500) -> None:
        self._state = state
        self._lock = lock
        self._log_key = log_key
        self._cap = cap
        self._by_id: dict[uuid.UUID, Any] = {}
        self._originals: set = set()

    def append(self, output, *, dtg: datetime | None = None, correction_of=None) -> BridgedDSORRecord:
        dtg = dtg or datetime.now(tz=timezone.utc)
        op = getattr(output, "operation_id", None)
        if correction_of is None and op is not None and op in self._originals:
            raise DSORAppendOnlyError(
                f"non-correction DSOR record for operation_id={op} already "
                f"exists (Axiom 4). Pass correction_of to append a correction."
            )
        rec = BridgedDSORRecord(
            output=output,
            dtg=dtg,
            kind=getattr(output, "kind", "unknown"),
            correction_of=correction_of,
        )
        self._by_id[rec.record_id] = output
        if correction_of is None and op is not None:
            self._originals.add(op)

        entry = {
            "record_id": str(rec.record_id),
            "dtg": dtg.isoformat(),
            "kind": rec.kind,
            "operation_id": str(op) if op is not None else None,
            "correction_of": str(correction_of) if correction_of is not None else None,
            "payload": self._compact(output),
        }
        with self._lock:
            log = self._state.setdefault(self._log_key, [])
            log.insert(0, entry)
            if len(log) > self._cap:
                del log[self._cap:]
        return rec

    def replay(self, record_id: uuid.UUID):
        return self._by_id[record_id]

    @staticmethod
    def _compact(output) -> dict:
        """JSON-safe projection of the agent output for the persisted log."""
        if hasattr(output, "model_dump"):
            try:
                return output.model_dump(mode="json")
            except Exception:
                pass
        return {"repr": str(output)}

    def __enter__(self) -> "AureonStateDSORStore":
        return self

    def __exit__(self, *_: object) -> bool:
        return False


__all__ = ["AureonStateDSORStore", "BridgedDSORRecord", "DSORAppendOnlyError"]
