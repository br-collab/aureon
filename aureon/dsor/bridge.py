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

from cannae_kernel.governance import ActionClass, AutonomyLevel


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
    autonomy_level: AutonomyLevel | None = None
    action_class: ActionClass | None = None


class AureonStateDSORStore:
    """Append-only DSOR store that mirrors records into persisted state.

    Interface parity with the SQLite / in-memory ``DSORStore``: ``append``
    and ``replay`` only. On ``append`` it also inserts a compact record at the
    head of ``state[log_key]`` under ``lock`` and trims to ``cap``.
    """

    def __init__(
        self,
        state,
        lock,
        *,
        log_key: str = "cockpit_dsor_log",
        header_key: str = "cockpit_dsor_header",
        cap: int = 500,
    ) -> None:
        self._state = state
        self._lock = lock
        self._log_key = log_key
        self._header_key = header_key
        self._cap = cap
        with self._lock:
            self._state.setdefault(
                self._header_key,
                {"schema_version": "aureon.cockpit_dsor_log/1", "append_only": True},
            )
            persisted = list(self._state.get(self._log_key, []))
        self._by_id: dict[uuid.UUID, Any] = {
            uuid.UUID(entry["record_id"]): entry["payload"] for entry in persisted
        }
        self._originals: set[str] = {
            entry["operation_id"]
            for entry in persisted
            if entry.get("operation_id") is not None and entry.get("correction_of") is None
        }

    @property
    def header(self) -> dict[str, object]:
        return dict(self._state[self._header_key])

    def append(self, output, *, dtg: datetime | None = None, correction_of=None, autonomy_level=None, action_class=None) -> BridgedDSORRecord:
        dtg = dtg or datetime.now(tz=timezone.utc)
        op = getattr(output, "operation_id", None)
        if correction_of is None and op is not None and str(op) in self._originals:
            raise DSORAppendOnlyError(
                f"non-correction DSOR record for operation_id={op} already "
                f"exists (Axiom 4). Pass correction_of to append a correction."
            )
        rec = BridgedDSORRecord(
            output=output,
            dtg=dtg,
            kind=output.get("kind", "unknown") if isinstance(output, dict) else getattr(output, "kind", "unknown"),
            correction_of=correction_of,
            autonomy_level=AutonomyLevel(autonomy_level) if autonomy_level else None,
            action_class=ActionClass(action_class) if action_class else None,
        )
        self._by_id[rec.record_id] = output
        if correction_of is None and op is not None:
            self._originals.add(str(op))

        entry = {
            "record_id": str(rec.record_id),
            "dtg": dtg.isoformat(),
            "kind": rec.kind,
            "operation_id": str(op) if op is not None else None,
            "correction_of": str(correction_of) if correction_of is not None else None,
            "autonomy_level": rec.autonomy_level.value if rec.autonomy_level else None,
            "action_class": rec.action_class.value if rec.action_class else None,
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

    def append_metadata_migration(
        self, record_ids, *, autonomy_level, action_class, classification_basis,
        classifier_version, migrated_at
    ) -> BridgedDSORRecord:
        event = {
            "kind": "dsor_metadata_migration",
            "schema_version": "3",
            "record_ids": [str(value) for value in record_ids],
            "autonomy_level": AutonomyLevel(autonomy_level).value,
            "action_class": ActionClass(action_class).value,
            "classification_basis": classification_basis,
            "classifier_version": classifier_version,
            "migrated_at": migrated_at.isoformat(),
        }
        return self.append(
            event, dtg=migrated_at,
            autonomy_level=AutonomyLevel.CONSTRAINED_EXECUTION,
            action_class=ActionClass.WRITE_CORE_RECORD,
        )

    @staticmethod
    def _compact(output) -> dict:
        """JSON-safe projection of the agent output for the persisted log."""
        if hasattr(output, "model_dump"):
            try:
                return output.model_dump(mode="json")
            except Exception:
                pass
        if isinstance(output, dict):
            return output.copy()
        return {"repr": str(output)}

    def __enter__(self) -> AureonStateDSORStore:
        return self

    def __exit__(self, *_: object) -> bool:
        return False


__all__ = ["AureonStateDSORStore", "BridgedDSORRecord", "DSORAppendOnlyError"]
