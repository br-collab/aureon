"""
aureon.approval_service.release
===============================
The one thing a full approval produces: a ``RELEASE_AUTHORIZED`` event (AUR-I-02).

Before Wave 2 approval moved cash, created a position and wrote a trade record
from the approved decision, before anything had executed. Approval now records
that release is authorized and nothing else. Cash, positions and trades change
only when an execution event arrives from a venue (``aureon.booking``).

``reference_price`` is the decision's price at approval. It is carried for
reconciliation only; a venue must never fill at it.

Since W2B-5 every term is taken from the sealed ApprovedIntentEnvelope, and the
event carries the envelope id, digest and expiry. Schema ``0.2-draft`` (JUM-D-26).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from cannae_kernel.canonical import canonical_bytes_of, digest_bytes
from cannae_kernel.provenance import Provenance
from pydantic import BaseModel, ConfigDict

__all__ = [
    "RELEASE_AUTHORIZED",
    "ReleaseAuthorized",
    "authorize_release",
    "find_release",
    "persist_release",
    "release_id_for",
]

RELEASE_AUTHORIZED = "RELEASE_AUTHORIZED"
MAX_PERSISTED_RELEASES = 1000


class ReleaseAuthorized(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["aureon.release_authorized/0.2-draft"] = (
        "aureon.release_authorized/0.2-draft"
    )
    event_type: Literal["RELEASE_AUTHORIZED"] = RELEASE_AUTHORIZED
    release_id: str
    envelope_id: str
    envelope_digest: str
    expires_at: datetime
    decision_id: str
    decision_digest: str
    policy_record_id: str
    policy_record_digest: str
    symbol: str
    action: str
    asset_class: str
    quantity_basis: Literal["QUANTITY", "NOTIONAL"]
    quantity: str | None
    quantity_unit: str | None
    whole_units: bool
    notional: str | None
    currency: str
    reference_price: str | None
    release_target: str
    approvals: tuple[str, ...]
    authority_hash: str
    authorized_at: datetime
    provenance: Provenance = Provenance.HUMAN_JUDGMENT


def release_id_for(decision_id: str, decision_digest: str) -> str:
    """One release per decision digest: approving the same terms twice yields the
    same release id, so a venue or booking consumer can deduplicate."""
    return "REL-" + digest_bytes(
        canonical_bytes_of({"decision_digest": decision_digest, "decision_id": decision_id})
    )[7:23].upper()


def authorize_release(*, envelope: Any, release_id: str) -> ReleaseAuthorized:
    """The release event for a sealed ApprovedIntentEnvelope; every term comes from the envelope."""
    intent = envelope.intent
    last = max(envelope.authority_manifest.approvals, key=lambda a: a.approved_at)
    return ReleaseAuthorized(
        release_id=release_id,
        envelope_id=str(envelope.envelope_id),
        envelope_digest=envelope.digest,
        expires_at=envelope.expires_at,
        decision_id=intent.decision_id,
        decision_digest=envelope.policy_manifest.decision_digest,
        policy_record_id=envelope.policy_manifest.policy_record_id,
        policy_record_digest=envelope.policy_manifest.policy_record_digest,
        symbol=intent.instrument_id,
        action=intent.side,
        asset_class=intent.asset_class,
        quantity_basis=intent.quantity.basis,
        quantity=intent.quantity.quantity,
        quantity_unit=intent.quantity.quantity_unit,
        whole_units=intent.quantity.whole_units,
        notional=intent.quantity.notional,
        currency=intent.quantity.currency,
        reference_price=intent.reference_price,
        release_target=envelope.execution_constraints.release_target,
        approvals=tuple(a.role for a in envelope.authority_manifest.approvals),
        authority_hash=last.authority_hash,
        authorized_at=envelope.created_at,
    )


def persist_release(state: dict[str, Any], release: ReleaseAuthorized) -> None:
    """Append ``release`` newest first. The caller holds the state lock."""
    log = state.setdefault("release_events", [])
    log.insert(0, release.model_dump(mode="json"))
    del log[MAX_PERSISTED_RELEASES:]


def find_release(state: Mapping[str, Any], release_id: str) -> ReleaseAuthorized | None:
    for raw in state.get("release_events", []):
        if raw.get("release_id") == release_id:
            return ReleaseAuthorized.model_validate_json(json.dumps(raw))
    return None
