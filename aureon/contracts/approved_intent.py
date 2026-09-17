"""
aureon.contracts.approved_intent
================================
The ApprovedIntentEnvelope, ``0.1-draft`` (AUR-I-04, AUR-I-07, AUR-I-11).

**Naming note.** ``aureon/contracts/`` was deleted on 31 July 2026 under
AUR-ADD-006 because it held vendored copies of Atreides *custody* code. This
module is not that: it holds only Aureon's own approved-intent contract, which
Aureon produces and L.C. will consume. Custody symbols still come from
``atreides.*``.

What an approval hands downstream, sealed so no consumer can alter it:

- ``intent`` — what is to be done, with **one quantity model**: either a
  quantity and its unit, or a notional and its currency, validated per asset
  class (:func:`normalize_quantity`). Operator-created orders and signal
  decisions normalize to the same shape (AUR-I-04).
- ``policy_manifest`` — the bound pre-trade record from W2B-3.
- ``authority_manifest`` — who approved, in which role, authenticated how
  (W2B-2), and any HOLD exceptions.
- ``downstream_permissions`` — what a consumer may and may not do, the
  idempotency key and correlation ids. Settlement submission is never
  permitted here.
- ``evidence_manifest`` — versioned references, with digests, to every record
  the approval relied on (AUR-I-11).
- ``expires_at`` and ``digest`` — kernel canonical digest over everything else.

:func:`seal_approved_intent` is the only way to build one; every approval path
reaches it through ``resolve_pending_decision``. Field names follow CL-JUM-001
§13 and the Aureon inventory §15 and are a draft: Wave 3 freezes them
(JUM-D-26). Fields Aureon cannot yet fill (legal entity, account, settlement
projection) are present and ``None`` rather than invented.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from cannae_kernel.actor import ActorRef
from cannae_kernel.canonical import canonical_bytes_of, digest_bytes
from cannae_kernel.disposition import Disposition
from cannae_kernel.ids import IntentId, LifecycleId
from cannae_kernel.provenance import Provenance
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "APPROVED_INTENT_TTL_SECONDS",
    "ENVELOPE_SCHEMA_VERSION",
    "QUANTITY_RULES",
    "ApprovalRecord",
    "ApprovedIntentEnvelope",
    "EvidenceRef",
    "IntentShapeError",
    "QuantityTerms",
    "canonical_asset_class",
    "normalize_quantity",
    "seal_approved_intent",
    "verify_envelope",
]

ENVELOPE_SCHEMA_VERSION = "aureon.approved_intent/0.1-draft"
EVIDENCE_MANIFEST_VERSION = "aureon.evidence_manifest/0.1-draft"
SERIALIZATION_PROFILE = "cannae-kernel canonical_bytes (v0.1.0)"
APPROVED_INTENT_TTL_SECONDS = 15 * 60
PERMITTED_VENUES = ("AUREON-PAPER",)

_Frozen = ConfigDict(frozen=True, extra="forbid")


class IntentShapeError(ValueError):
    """The request cannot be normalized to a valid intent."""


# ── Quantity model (AUR-I-04) ──────────────────────────────────────────────────

_CLASS_ALIASES = {
    "equities": "equity", "equity": "equity", "stock": "equity",
    "real_assets": "fund", "absolute_return": "fund", "commodities": "fund", "etf": "fund",
    "fixed_income": "fixed_income", "bond": "fixed_income", "ficc": "fixed_income",
    "crypto": "digital", "crypto_spot": "digital", "digital": "digital", "native_digital": "digital",
    "tokenized": "tokenized", "tokenised": "tokenized", "tokenized_security": "tokenized",
    "fx": "fx",
}

#: Per canonical asset class: accepted quantity units, whether a quantity must
#: be whole, and whether a notional-only instruction is accepted.
QUANTITY_RULES: Mapping[str, Mapping[str, Any]] = {
    "equity":       {"units": ("SHARES",), "whole": True, "notional": True},
    "fund":         {"units": ("SHARES",), "whole": True, "notional": True},
    "fixed_income": {"units": ("SHARES", "FACE"), "whole": True, "notional": True},
    "digital":      {"units": ("UNITS",), "whole": False, "notional": True},
    "tokenized":    {"units": ("TOKENS",), "whole": False, "notional": True},
    "fx":           {"units": (), "whole": False, "notional": True},
}

_CURRENCY = re.compile(r"^[A-Z]{3}$")


def canonical_asset_class(asset_class: str) -> str:
    canon = _CLASS_ALIASES.get((asset_class or "").strip().lower())
    if canon is None:
        raise IntentShapeError(f"asset class {asset_class!r} is not in the quantity model")
    return canon


def _positive(value: Any, name: str) -> Decimal:
    if isinstance(value, bool):
        raise IntentShapeError(f"{name} must be a positive number")
    try:
        number = Decimal(repr(value)) if isinstance(value, float) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise IntentShapeError(f"{name} must be a positive number, got {value!r}") from None
    if not number.is_finite() or number <= 0:
        raise IntentShapeError(f"{name} must be a positive number, got {value!r}")
    return number


def _text(number: Decimal) -> str:
    return format(number.normalize(), "f") if number != number.to_integral() else str(int(number))


class QuantityTerms(BaseModel):
    """Either a quantity with its unit, or a notional with its currency, binds."""

    model_config = _Frozen

    basis: Literal["QUANTITY", "NOTIONAL"]
    quantity: str | None
    quantity_unit: str | None
    whole_units: bool
    notional: str | None
    currency: str


def normalize_quantity(
    asset_class: str,
    *,
    quantity: Any = None,
    quantity_unit: str | None = None,
    notional: Any = None,
    currency: str | None = None,
    estimated_notional: Any = None,
) -> QuantityTerms:
    """Validate one instruction for ``asset_class``. Give a quantity or a notional, not both.

    ``estimated_notional`` is the informational value a quantity instruction
    carries (a signal's shares × price); it never becomes the binding term.
    """
    canon = canonical_asset_class(asset_class)
    rules = QUANTITY_RULES[canon]
    ccy = (currency or "USD").strip().upper()
    if not _CURRENCY.match(ccy):
        raise IntentShapeError(f"currency must be a three-letter ISO 4217 code, got {currency!r}")
    has_quantity = quantity not in (None, "")
    has_notional = notional not in (None, "")
    if has_quantity == has_notional:
        raise IntentShapeError("give either quantity (with its unit) or notional (with its currency)")
    if has_notional:
        if not rules["notional"]:
            raise IntentShapeError(f"{canon} orders need a quantity")
        amount = _positive(notional, "notional")
        return QuantityTerms(basis="NOTIONAL", quantity=None, quantity_unit=None,
                             whole_units=bool(rules["whole"]), notional=_text(amount), currency=ccy)
    if not rules["units"]:
        raise IntentShapeError(f"{canon} orders are given as notional and currency")
    unit = (quantity_unit or rules["units"][0]).strip().upper()
    if unit not in rules["units"]:
        raise IntentShapeError(f"{canon} quantity unit must be one of {list(rules['units'])}, got {unit!r}")
    amount = _positive(quantity, "quantity")
    if rules["whole"] and amount != amount.to_integral():
        raise IntentShapeError(f"{canon} quantity must be a whole number of {unit}")
    estimate = None
    if estimated_notional not in (None, ""):
        estimate = _text(_positive(estimated_notional, "estimated notional"))
    return QuantityTerms(basis="QUANTITY", quantity=_text(amount), quantity_unit=unit,
                         whole_units=bool(rules["whole"]), notional=estimate, currency=ccy)


# ── Envelope ───────────────────────────────────────────────────────────────────


class IntentTerms(BaseModel):
    model_config = _Frozen

    decision_id: str
    instrument_id: str
    instrument_type: str
    asset_class: str
    side: Literal["BUY", "SELL"]
    quantity: QuantityTerms
    price_type: Literal["MARKET", "LIMIT"]
    reference_price: str | None
    strategy_id: str | None
    rationale: str


class Ownership(BaseModel):
    model_config = _Frozen

    legal_entity_id: str | None = None
    portfolio_id: str
    account_id: str | None = None


class ExecutionConstraints(BaseModel):
    model_config = _Frozen

    release_target: str
    permitted_venues: tuple[str, ...]
    time_in_force: Literal["DAY", "IOC"]


class GateRef(BaseModel):
    model_config = _Frozen

    gate: str
    disposition: Disposition


class PolicyManifest(BaseModel):
    model_config = _Frozen

    disposition: Disposition
    policy_record_id: str
    policy_record_digest: str
    decision_digest: str
    rule_set_version: str
    rules_digest: str
    gates: tuple[GateRef, ...]
    hold_exception_ids: tuple[str, ...]


class ApprovalRecord(BaseModel):
    model_config = _Frozen

    role: str
    actor: ActorRef
    approved_at: datetime
    authority_hash: str


class AuthorityManifest(BaseModel):
    model_config = _Frozen

    decision_type: Literal["APPROVE_RELEASE"] = "APPROVE_RELEASE"
    required_roles: tuple[str, ...]
    approvals: tuple[ApprovalRecord, ...]
    quorum_met: bool


class DownstreamPermissions(BaseModel):
    model_config = _Frozen

    permitted_actions: tuple[str, ...]
    prohibited_actions: tuple[str, ...]
    settlement_submit: Literal[False] = False
    idempotency_key: str
    correlation_ids: Mapping[str, str]


class EvidenceRef(BaseModel):
    model_config = _Frozen

    kind: str
    ref_id: str
    digest: str | None


class EvidenceManifest(BaseModel):
    model_config = _Frozen

    manifest_version: Literal["aureon.evidence_manifest/0.1-draft"] = EVIDENCE_MANIFEST_VERSION
    refs: tuple[EvidenceRef, ...]


class ApprovedIntentEnvelope(BaseModel):
    model_config = _Frozen

    schema_version: Literal["aureon.approved_intent/0.1-draft"] = ENVELOPE_SCHEMA_VERSION
    envelope_id: IntentId
    lifecycle_id: LifecycleId
    revision: int = Field(ge=1)
    prior_digest: str | None
    created_at: datetime
    expires_at: datetime
    intent: IntentTerms
    ownership: Ownership
    execution_constraints: ExecutionConstraints
    policy_manifest: PolicyManifest
    authority_manifest: AuthorityManifest
    settlement_projection_ref: str | None = None
    downstream_permissions: DownstreamPermissions
    evidence_manifest: EvidenceManifest
    provenance: Provenance = Provenance.HUMAN_JUDGMENT
    serialization_profile: str = SERIALIZATION_PROFILE
    digest: str


def _validated_asset_class(asset_class: Any) -> str:
    """The asset class as the book records it, after checking the quantity model knows it."""
    canonical_asset_class(str(asset_class or ""))
    return str(asset_class)


def _digest_without_seal(fields: Mapping[str, Any]) -> str:
    return digest_bytes(canonical_bytes_of({k: v for k, v in fields.items() if k != "digest"}))


def _typed_id(cls: type, seed: str, at: datetime) -> Any:
    entropy = hashlib.sha256(seed.encode("utf-8")).digest()
    return cls.new(clock=lambda: at, entropy=lambda n: entropy[:n])


def decision_quantity_terms(decision: Mapping[str, Any]) -> QuantityTerms:
    """The quantity terms a stored decision carries, whatever path created it."""
    basis = decision.get("quantity_basis")
    shares = decision.get("shares")
    if basis == "NOTIONAL" or (basis is None and shares in (None, "", 0)):
        return normalize_quantity(decision.get("asset_class", ""),
                                  notional=decision.get("notional"),
                                  currency=decision.get("currency"))
    return normalize_quantity(decision.get("asset_class", ""), quantity=shares,
                              quantity_unit=decision.get("quantity_unit"),
                              currency=decision.get("currency"),
                              estimated_notional=decision.get("notional"))


def seal_approved_intent(
    *,
    decision: Mapping[str, Any],
    policy_record: Any,
    hold_exception_ids: Sequence[str],
    approvals: Sequence[ApprovalRecord],
    required_roles: Sequence[str],
    release_id: str,
    now: datetime,
    evidence: Sequence[EvidenceRef] = (),
) -> ApprovedIntentEnvelope:
    """The one method that seals an approved intent. Raises IntentShapeError if it cannot."""
    created_at = now.astimezone(timezone.utc)
    if not approvals:
        raise IntentShapeError("an approved intent needs at least one authenticated approval")
    for record in approvals:
        if not record.actor.authenticated:
            raise IntentShapeError(f"approval by {record.role} is not from an authenticated actor")
    side = str(decision.get("action", "")).upper()
    if side not in ("BUY", "SELL"):
        raise IntentShapeError(f"side must be BUY or SELL, got {side!r}")
    quantity = decision_quantity_terms(decision)
    price = decision.get("price")
    required = tuple(required_roles)
    approved_roles = {a.role for a in approvals}
    fields: dict[str, Any] = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "envelope_id": _typed_id(IntentId, f"intent:{policy_record.decision_digest}", created_at),
        "lifecycle_id": _typed_id(LifecycleId, f"lifecycle:{decision['id']}", created_at),
        "revision": 1,
        "prior_digest": None,
        "created_at": created_at,
        "expires_at": created_at + timedelta(seconds=APPROVED_INTENT_TTL_SECONDS),
        "intent": IntentTerms(
            decision_id=str(decision["id"]),
            instrument_id=str(decision.get("symbol", "")),
            instrument_type=str(decision.get("product_type") or "UNSPECIFIED"),
            asset_class=_validated_asset_class(decision.get("asset_class")),
            side=side,  # type: ignore[arg-type]
            quantity=quantity,
            price_type="MARKET",
            reference_price=None if price in (None, "") else _text(_positive(price, "price")),
            strategy_id=decision.get("signal_type"),
            rationale=str(decision.get("rationale") or ""),
        ),
        "ownership": Ownership(portfolio_id="AUREON-ENDOWMENT-SERIES-I-PAPER"),
        "execution_constraints": ExecutionConstraints(
            release_target=str(decision.get("release_target") or "OMS"),
            permitted_venues=PERMITTED_VENUES,
            time_in_force="DAY",
        ),
        "policy_manifest": PolicyManifest(
            disposition=policy_record.disposition,
            policy_record_id=policy_record.record_id,
            policy_record_digest=policy_record.record_digest,
            decision_digest=policy_record.decision_digest,
            rule_set_version=policy_record.rule_set_version,
            rules_digest=policy_record.rules_digest,
            gates=tuple(GateRef(gate=g.gate, disposition=g.disposition) for g in policy_record.gates),
            hold_exception_ids=tuple(hold_exception_ids),
        ),
        "authority_manifest": AuthorityManifest(
            required_roles=required,
            approvals=tuple(approvals),
            quorum_met=all(role in approved_roles for role in required),
        ),
        "settlement_projection_ref": None,
        "downstream_permissions": DownstreamPermissions(
            permitted_actions=("EXECUTE_ON_PERMITTED_VENUE", "BOOK_FROM_EXECUTION_EVENT"),
            prohibited_actions=("MODIFY_TERMS", "EXECUTE_AFTER_EXPIRY", "EXECUTE_TWICE",
                                "SUBMIT_TO_SETTLEMENT_RAIL"),
            idempotency_key=release_id,
            correlation_ids={"decision_id": str(decision["id"]), "release_id": release_id},
        ),
        "evidence_manifest": EvidenceManifest(refs=(
            EvidenceRef(kind="POLICY_EVALUATION", ref_id=policy_record.record_id,
                        digest=policy_record.record_digest),
            *(EvidenceRef(kind="POLICY_HOLD_EXCEPTION", ref_id=i, digest=None)
              for i in hold_exception_ids),
            *(EvidenceRef(kind="AUTHORITY_APPROVAL", ref_id=a.authority_hash, digest=None)
              for a in approvals),
            *evidence,
        )),
        "provenance": Provenance.HUMAN_JUDGMENT,
        "serialization_profile": SERIALIZATION_PROFILE,
    }
    if not fields["authority_manifest"].quorum_met:
        raise IntentShapeError("required roles have not all approved")
    fields["digest"] = _digest_without_seal(fields)
    return ApprovedIntentEnvelope(**fields)


def verify_envelope(envelope: ApprovedIntentEnvelope, *, now: datetime | None = None) -> None:
    """Raise IntentShapeError unless ``envelope`` is intact and unexpired."""
    if _digest_without_seal(envelope.model_dump(mode="python")) != envelope.digest:
        raise IntentShapeError("envelope digest does not match its content")
    at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not envelope.created_at <= at < envelope.expires_at:
        raise IntentShapeError(f"envelope expired at {envelope.expires_at.isoformat()}")
