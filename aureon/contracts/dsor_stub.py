"""DSOR (Decision System of Record) lineage stub fields.

Per AUR-CANONICAL-001 v1.6 Layer 2 (Kaladan — Lifecycle Orchestration)
and Axiom 1 (Doctrine Before Execution), every custody operation must
carry an immutable lineage stamp recording the doctrine version, the
authority that approved the operation, the C2 handoff that authorized
agent execution, and the pre/post operation state hashes that allow
DSOR replay.

This module is the **stub** — the minimum lineage fields operations
carry at the contracts layer. Full DSOR record assembly (the unified
lineage that Thifur-C2 builds and delivers to Kaladan, per
AUR-CANONICAL-001 v1.6 C2 Stop #4 "One Lineage Record") lives in
``aureon.dsor`` and is out of scope for the contracts build.

The five fields the doctrine binds:

1. ``doctrine_version`` — the Aureon doctrine version active at
   operation time (Axiom 1: "doctrine version stamp"). Defaults to the
   currently active version.
2. ``authority_tier`` and ``authority_id`` — the CAOM-001 authority
   tier and identity that approved the operation (Axiom 1: "authority
   hash"). For quorum-required operations the authority tier is
   ``QUORUM`` and the authority_id references the ceremony.
3. ``c2_handoff_id`` — the Thifur-C2 handoff record (Axiom 3:
   "handoff before action"). Required when the operation is
   agent-executed; None for operator-direct operations.
4. ``session_id`` — the Verana-issued session identifier (CAOM-001
   Section V Step 1).
5. ``pre_operation_state_hash`` and ``post_operation_state_hash`` —
   SHA-256 hashes of the DSOR state before and after the operation
   (Axiom 4: "one lineage record"). Pre is required at construction;
   post is None until the operation completes.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

CURRENT_DOCTRINE_VERSION: str = "1.6"
"""The active Aureon doctrine version. Per AUR-CANONICAL-001 v1.6
masthead. Updates to this constant are doctrine-modifying changes that
flow through the propose/approve workflow (Section VII)."""

CAOM_MODE_DEFAULT: str = "CAOM-001"
"""The active operating mode per AUR-CANONICAL-001 v1.6 Section V."""

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_DOCTRINE_VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")


class CAOMTier(StrEnum):
    """CAOM-001 authority tier per AUR-CANONICAL-001 v1.6 Section V.

    The four CAOM tiers (T0/T1/T2/T3) plus the QUORUM tier for
    operations that require N-of-M independent signatures
    (AUR-CUSTODY-001 v1.0 Section VII). Quorum-required operations are
    out of scope under CAOM-001 (Section V "Quorum Authority — Future
    Mode") but the tier identifier is reserved here so that operations
    can declare it; ceremony execution itself is out of scope.
    """

    T0 = "T0"
    """Emergency Halt — above the three-tier CAOM structure (Axiom 9).
    Any authority can trigger; resumption requires explicit operator
    action and generates a doctrine-change-style audit record."""

    T1 = "T1"
    """Operational — Trader, Risk Manager, Portfolio Manager. Single
    operator under CAOM-001."""

    T2 = "T2"
    """Governance — Compliance Officer, Head of Risk / CRO. Single
    operator under CAOM-001."""

    T3 = "T3"
    """Executive — systemic, doctrine-change, kill-switch decisions.
    Single operator under CAOM-001."""

    QUORUM = "QUORUM"
    """Quorum-required (post-CAOM authority structure). Per
    AUR-CUSTODY-001 v1.0 Section VII — N-of-M independent signatures
    with separation of duties enforced architecturally. Out of scope
    under CAOM-001; reserved here for forward compatibility."""


class DSORLineageStub(BaseModel):
    """Minimum DSOR lineage fields every custody operation carries.

    Per AUR-CANONICAL-001 v1.6 Axiom 1 (Doctrine Before Execution),
    Axiom 3 (Handoff Before Action), and Axiom 4 (One Lineage Record).
    The full DSOR record is assembled by Thifur-C2 from agent
    telemetry and operator action; this stub holds the fields that
    must travel with the operation itself for the assembly to succeed.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    operation_id: UUID = Field(
        default_factory=uuid4,
        description=(
            "Unique identifier for this operation. Used to correlate "
            "agent telemetry, signature records, and downstream "
            "settlement confirmations into the unified DSOR record."
        ),
    )
    doctrine_version: str = Field(
        default=CURRENT_DOCTRINE_VERSION,
        description=(
            "Aureon doctrine version active at operation time per "
            "Axiom 1. Format: 'major.minor' or 'major.minor.patch'."
        ),
    )
    caom_mode: str = Field(
        default=CAOM_MODE_DEFAULT,
        min_length=1,
        description=(
            "Active CAOM operating mode (e.g., 'CAOM-001'). Per Section "
            "V 'Every approval action is stamped with CAOM-001 mode "
            "identifier'."
        ),
    )
    authority_tier: CAOMTier = Field(
        description="CAOM-001 authority tier that approved the operation.",
    )
    authority_id: str = Field(
        min_length=1,
        description=(
            "Identifier of the approving authority — operator id for "
            "T0/T1/T2/T3, ceremony session id for QUORUM."
        ),
    )
    initiated_at: datetime = Field(
        description="UTC timestamp at which the operation was initiated.",
    )
    session_id: str | None = Field(
        default=None,
        description=(
            "Verana-issued session identifier (CAOM-001 Section V Step "
            "1). None when operation is initiated outside a session "
            "boundary (e.g., scheduled / batch operations)."
        ),
    )
    c2_handoff_id: str | None = Field(
        default=None,
        description=(
            "Thifur-C2 handoff authorization identifier. Required when "
            "the operation is agent-executed (Axiom 3: 'no Thifur agent "
            "may act on a lifecycle object without a recorded C2 "
            "handoff authorization'). None for operator-direct "
            "operations."
        ),
    )
    pre_operation_state_hash: str = Field(
        description=(
            "SHA-256 hex digest of the DSOR state immediately before "
            "the operation. Per Axiom 4 'one lineage record' — Section "
            "VII Step 1 names this the 'pre-operation DSOR state'."
        ),
    )
    post_operation_state_hash: str | None = Field(
        default=None,
        description=(
            "SHA-256 hex digest of the DSOR state immediately after "
            "the operation. None until the operation completes; set "
            "when post-operation reconciliation runs (Section VII "
            "Step 6)."
        ),
    )

    @model_validator(mode="after")
    def _validate_doctrine_version(self) -> Self:
        """Doctrine version must be ``major.minor`` or
        ``major.minor.patch``. Per the Section VII propose/approve
        version log format."""
        if not _DOCTRINE_VERSION_RE.match(self.doctrine_version):
            raise ValueError(
                f"doctrine_version {self.doctrine_version!r} must "
                f"match 'major.minor' or 'major.minor.patch' per "
                f"AUR-CANONICAL-001 v1.6 Section VII."
            )
        return self

    @model_validator(mode="after")
    def _validate_state_hashes(self) -> Self:
        """State hashes must be SHA-256 lowercase hex (64 chars).

        Per AUR-CANONICAL-001 v1.6 Axiom 1 ('SHA-256 audit hash') and
        Section VII (the propose/approve workflow stamps fresh SHA-256
        hashes). Tightening to a single canonical hash format keeps
        lineage records bit-for-bit comparable across the parity
        boundary (Section VII 'Parity Principle').
        """
        if not _SHA256_HEX.match(self.pre_operation_state_hash):
            raise ValueError(
                "pre_operation_state_hash must be a 64-character "
                "lowercase hex SHA-256 digest per AUR-CANONICAL-001 "
                "v1.6 Axiom 1."
            )
        if (
            self.post_operation_state_hash is not None
            and not _SHA256_HEX.match(self.post_operation_state_hash)
        ):
            raise ValueError(
                "post_operation_state_hash, when set, must be a "
                "64-character lowercase hex SHA-256 digest per "
                "AUR-CANONICAL-001 v1.6 Axiom 1."
            )
        return self


__all__ = [
    "CAOM_MODE_DEFAULT",
    "CURRENT_DOCTRINE_VERSION",
    "CAOMTier",
    "DSORLineageStub",
]
