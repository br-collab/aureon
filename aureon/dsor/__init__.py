"""Vendored DSOR sink for the Clearing Operator Cockpit (WS-1, AUR-COCKPIT-001).

Append-only in-memory DSOR store that preserves AUR-CANONICAL-001 v1.6
Axiom 4 (immutable lineage): no update, no delete, and at most one
non-correction record per ``operation_id``. This is the prototype cockpit
DSOR sink; the full public implementation is an append-only SQLite store
(``Project-Atreides-public/aureon/dsor``).

Integration note: production's unified lineage record is assembled by
Thifur-C2 and held by Kaladan (aureon_state ``c2_lineage_log`` / the DSOR
conventions in ``aureon.agents.c2.coordinator``). A follow-up should bridge
cockpit gate outputs into that unified lineage rather than this local sink;
until then the cockpit records its pre-trade gate outputs here so
``emit_instruction_package`` can carry a real DSOR record reference.
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
class DSORRecord:
    """Immutable DTG-stamped wrapper around one agent output."""

    output: Any
    dtg: datetime
    kind: str
    record_id: uuid.UUID = field(default_factory=uuid.uuid4)
    correction_of: uuid.UUID | None = None


class DSORStore:
    """Append-only in-memory DSOR store (prototype).

    Interface parity with the public SQLite ``DSORStore``: ``append`` and
    ``replay`` only — no update, no delete.
    """

    def __init__(self, db_path: Any = ":memory:") -> None:
        self._by_id: dict[uuid.UUID, Any] = {}
        self._originals: set = set()

    def append(self, output, *, dtg=None, correction_of=None) -> DSORRecord:
        dtg = dtg or datetime.now(tz=timezone.utc)
        op = getattr(output, "operation_id", None)
        if correction_of is None and op is not None and op in self._originals:
            raise DSORAppendOnlyError(
                f"non-correction DSOR record for operation_id={op} already "
                f"exists (Axiom 4). Pass correction_of to append a correction."
            )
        rec = DSORRecord(
            output=output,
            dtg=dtg,
            kind=getattr(output, "kind", "unknown"),
            correction_of=correction_of,
        )
        self._by_id[rec.record_id] = output
        if correction_of is None and op is not None:
            self._originals.add(op)
        return rec

    def replay(self, record_id: uuid.UUID):
        return self._by_id[record_id]

    def __enter__(self) -> "DSORStore":
        return self

    def __exit__(self, *_: object) -> bool:
        return False


__all__ = ["DSORStore", "DSORRecord", "DSORAppendOnlyError"]
