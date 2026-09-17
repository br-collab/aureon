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

Schema ``0.1-draft`` (JUM-D-26). W2B-5 wraps this in the ApprovedIntentEnvelope.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
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
]

RELEASE_AUTHORIZED = "RELEASE_AUTHORIZED"
MAX_PERSISTED_RELEASES = 1000


class ReleaseAuthorized(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["aureon.release_authorized/0.1-draft"] = (
        "aureon.release_authorized/0.1-draft"
    )
    event_type: Literal["RELEASE_AUTHORIZED"] = RELEASE_AUTHORIZED
    release_id: str
    decision_id: str
    decision_digest: str
    policy_record_id: str
    policy_record_digest: str
    symbol: str
    action: str
    asset_class: str
    quantity: str | None
    notional: str
    reference_price: str | None
    release_target: str
    approvals: tuple[str, ...]
    authority_hash: str
    authorized_at: datetime
    provenance: Provenance = Provenance.HUMAN_JUDGMENT


def _text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def authorize_release(
    *,
    decision: Mapping[str, Any],
    policy_record: Any,
    approvals: list[str],
    authority_hash: str,
    now: datetime | None = None,
) -> ReleaseAuthorized:
    authorized_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    fields = {
        "decision_id": str(decision["id"]),
        "decision_digest": policy_record.decision_digest,
        "policy_record_id": policy_record.record_id,
        "policy_record_digest": policy_record.record_digest,
        "symbol": str(decision["symbol"]),
        "action": str(decision["action"]),
        "asset_class": str(decision.get("asset_class") or ""),
        "quantity": _text(decision.get("shares")),
        "notional": str(decision.get("notional", 0)),
        "reference_price": _text(decision.get("price")),
        "release_target": str(decision.get("release_target") or "OMS"),
        "approvals": tuple(approvals),
        "authority_hash": authority_hash,
    }
    # One release per decision digest: approving the same terms twice yields
    # the same release id, so a venue or booking consumer can deduplicate.
    release_id = "REL-" + digest_bytes(
        canonical_bytes_of({"decision_digest": fields["decision_digest"],
                            "decision_id": fields["decision_id"]})
    )[7:23].upper()
    return ReleaseAuthorized(release_id=release_id, authorized_at=authorized_at, **fields)


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
