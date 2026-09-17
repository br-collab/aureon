"""
aureon.policy_engine.binding
============================
Pre-trade policy evidence that binds approval (AUR-I-01, AUR-I-10).

Before Wave 2 the pre-trade gates were advisory: a decision whose gates
returned FAIL could still be approved, and the approval moved cash and created
a position. This module makes the gate result a persisted record and makes
approval depend on it.

A :class:`PolicyEvaluationRecord` is written every time the gates run. It
carries:

- the decision's **content digest** (kernel ``digest`` over its economic
  terms), so changing any term makes the record stale;
- the **rules digest** (rule-set version, risk limits, cash floor, sanctions
  list, HOLD override policy), so changing a rule makes the record stale;
- one kernel :class:`~cannae_kernel.disposition.Disposition` per gate and
  overall, and an expiry.

:func:`require_approvable` is the single check every approval path calls.
Approval proceeds only when the latest record for the decision is intact, is
for the decision's current digest and the current rules, has not expired, and:

- is ``PASS``; or
- is ``HOLD`` and a valid :class:`PolicyHoldException` covers every held gate:
  the policy marks each one overrideable, the granting role is one the policy
  requires, a reason is given, and it has not expired.

``BLOCK`` and ``INDETERMINATE`` are always refused. ``INDETERMINATE`` means
required evidence was unavailable (for example an unusable OFR stress reading
or a check that could not run). It is not a HOLD and no exception overrides it.

Gate statuses map to dispositions as follows: ``PASS`` and ``WARN`` → ``PASS``
(a warning is shown to the approver but does not stop approval, as before);
``HOLD`` → ``HOLD``; ``FAIL`` and ``BLOCKED`` → ``BLOCK``; anything else →
``INDETERMINATE``. A gate may also state its disposition explicitly; the more
restrictive of the two is used.

The record schema is ``0.1-draft`` (JUM-D-26): Wave 3 freezes shapes.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from cannae_kernel.actor import ActorRef
from cannae_kernel.canonical import canonical_bytes_of, digest_bytes
from cannae_kernel.disposition import Disposition
from cannae_kernel.provenance import Provenance
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "DECISION_TERM_FIELDS",
    "HOLD_OVERRIDE_POLICY",
    "MAX_HOLD_EXCEPTION_SECONDS",
    "POLICY_EVIDENCE_TTL_SECONDS",
    "RULE_SET_VERSION",
    "GateOutcome",
    "HoldOverrideRule",
    "PolicyBindingError",
    "PolicyEvaluationRecord",
    "PolicyHoldException",
    "aggregate_disposition",
    "build_policy_record",
    "decision_digest",
    "gate_disposition",
    "grant_hold_exception",
    "latest_policy_record",
    "persist_hold_exception",
    "persist_policy_record",
    "pretrade_rules_digest",
    "require_approvable",
]

RULE_SET_VERSION = "aureon-pretrade/0.2"
"""0.2: gates bind approval; pro-forma concentration; evidence failure is INDETERMINATE."""

POLICY_EVIDENCE_TTL_SECONDS = 300
"""How long a gate result stays current. The dashboard runs the gates when the
approver opens the pre-trade check, so five minutes covers review and approval."""

MAX_HOLD_EXCEPTION_SECONDS = 3600
MAX_PERSISTED_EVALUATIONS = 500
MAX_PERSISTED_EXCEPTIONS = 200

#: The terms that define what is being approved. Status, approvals so far and
#: display text are not terms: they change during approval without changing
#: what would be released.
DECISION_TERM_FIELDS = (
    "id",
    "action",
    "symbol",
    "asset_class",
    "product_type",
    "shares",
    "price",
    "notional",
    "release_target",
    "mandate_sensitive",
    "policy_exception",
    "risk_exception",
    "pm_signoff_required",
    "control_exception",
    "financing_relevant",
    "token_issuer_id",
    "settlement_rail",
    "custody_class",
    "instrument_subtype",
    "bond_liquidity",
    "pretrade_published",
    "waiver_claimed",
    "counterparty_name",
    "counterparty_jurisdiction",
)


@dataclass(frozen=True)
class HoldOverrideRule:
    overrideable: bool
    required_roles: frozenset[str]
    basis: str


#: Which HOLDs a human may override, and who. A HOLD from a gate not listed
#: here is not overrideable: the decision must change, or the gate must clear.
HOLD_OVERRIDE_POLICY: Mapping[str, HoldOverrideRule] = {
    "MIFIR_PRETRADE_TRANSPARENCY": HoldOverrideRule(
        overrideable=True,
        required_roles=frozenset({"COMPLIANCE"}),
        basis=(
            "Transparency or a waiver was not evidenced on the order. Compliance may "
            "attest that it is satisfied outside the order record."
        ),
    ),
}


class PolicyBindingError(RuntimeError):
    """Approval refused because the policy evidence does not permit it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


_Frozen = ConfigDict(frozen=True, extra="forbid")


class GateOutcome(BaseModel):
    model_config = _Frozen

    gate: str
    layer: str
    status: str
    disposition: Disposition
    detail: str
    overrideable: bool


class PolicyEvaluationRecord(BaseModel):
    model_config = _Frozen

    schema_version: Literal["aureon.policy_evaluation/0.1-draft"] = (
        "aureon.policy_evaluation/0.1-draft"
    )
    record_id: str
    decision_id: str
    decision_digest: str
    rule_set_version: str
    rules_digest: str
    disposition: Disposition
    gates: tuple[GateOutcome, ...]
    inputs: dict[str, str | None]
    provenance: Provenance = Provenance.POLICY_RESULT
    evaluated_at: datetime
    expires_at: datetime
    record_digest: str


class PolicyHoldException(BaseModel):
    """A human decision to proceed despite an overrideable HOLD."""

    model_config = _Frozen

    schema_version: Literal["aureon.policy_hold_exception/0.1-draft"] = (
        "aureon.policy_hold_exception/0.1-draft"
    )
    exception_id: str
    decision_id: str
    decision_digest: str
    policy_record_digest: str
    held_gates: tuple[str, ...]
    authority: ActorRef
    authority_role: str
    reason: str = Field(min_length=1)
    overrideable: bool
    granted_at: datetime
    expires_at: datetime
    provenance: Provenance = Provenance.HUMAN_JUDGMENT


# ── Canonical forms ────────────────────────────────────────────────────────────


def _canonical_scalar(value: Any) -> Any:
    """Make a prototype-state value digestible: numbers become normalized decimal strings."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float, Decimal)):
        try:
            number = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
        except InvalidOperation:
            return str(value)
        if not number.is_finite():
            return str(value)
        return format(number.normalize(), "f") if number != 0 else "0"
    if isinstance(value, (list, tuple)):
        return [_canonical_scalar(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): _canonical_scalar(v) for k, v in value.items()}
    return str(value)


def decision_digest(decision: Mapping[str, Any]) -> str:
    terms = {name: _canonical_scalar(decision.get(name)) for name in DECISION_TERM_FIELDS}
    return digest_bytes(canonical_bytes_of({"decision_terms": terms}))


def pretrade_rules_digest(
    *,
    risk_policy: Mapping[str, Any],
    operating_cash_floor_pct: Any,
    ofac_blocked_isins: Iterable[str],
) -> str:
    rules = {
        "rule_set_version": RULE_SET_VERSION,
        "risk_policy": _canonical_scalar(dict(risk_policy)),
        "operating_cash_floor_pct": _canonical_scalar(operating_cash_floor_pct),
        "ofac_blocked_isins": sorted(ofac_blocked_isins),
        "hold_override_policy": {
            gate: {
                "overrideable": rule.overrideable,
                "required_roles": sorted(rule.required_roles),
            }
            for gate, rule in sorted(HOLD_OVERRIDE_POLICY.items())
        },
        "evidence_ttl_seconds": POLICY_EVIDENCE_TTL_SECONDS,
    }
    return digest_bytes(canonical_bytes_of(rules))


# ── Dispositions ───────────────────────────────────────────────────────────────

_STATUS_DISPOSITION = {
    "PASS": Disposition.PASS,
    "WARN": Disposition.PASS,
    "HOLD": Disposition.HOLD,
    "FAIL": Disposition.BLOCK,
    "BLOCKED": Disposition.BLOCK,
    "BLOCK": Disposition.BLOCK,
    "INDETERMINATE": Disposition.INDETERMINATE,
}

#: Most restrictive first.
_PRECEDENCE = (
    Disposition.BLOCK,
    Disposition.INDETERMINATE,
    Disposition.HOLD,
    Disposition.PASS,
)


def aggregate_disposition(dispositions: Iterable[Disposition]) -> Disposition:
    """The most restrictive disposition; no gates at all is INDETERMINATE."""
    seen = set(dispositions)
    if not seen:
        return Disposition.INDETERMINATE
    return next(d for d in _PRECEDENCE if d in seen)


def gate_disposition(gate: Mapping[str, Any]) -> Disposition:
    by_status = _STATUS_DISPOSITION.get(gate.get("status"), Disposition.INDETERMINATE)
    explicit = gate.get("disposition")
    if explicit is None:
        return by_status
    by_label = _STATUS_DISPOSITION.get(explicit, Disposition.INDETERMINATE)
    return aggregate_disposition((by_status, by_label))


# ── Records ────────────────────────────────────────────────────────────────────


def _utc(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _record_digest(fields: Mapping[str, Any]) -> str:
    return digest_bytes(canonical_bytes_of({k: v for k, v in fields.items() if k != "record_digest"}))


def build_policy_record(
    *,
    decision: Mapping[str, Any],
    gates: Iterable[Mapping[str, Any]],
    rules_digest: str,
    inputs: Mapping[str, Any],
    now: datetime | None = None,
) -> PolicyEvaluationRecord:
    evaluated_at = _utc(now)
    outcomes = tuple(
        GateOutcome(
            gate=str(g.get("gate", "")),
            layer=str(g.get("layer", "")),
            status=str(g.get("status", "")),
            disposition=gate_disposition(g),
            detail=str(g.get("detail", "")),
            overrideable=(
                gate_disposition(g) is Disposition.HOLD
                and HOLD_OVERRIDE_POLICY.get(str(g.get("gate")), _NOT_OVERRIDEABLE).overrideable
            ),
        )
        for g in gates
    )
    d_digest = decision_digest(decision)
    fields: dict[str, Any] = {
        "schema_version": "aureon.policy_evaluation/0.1-draft",
        "decision_id": str(decision.get("id")),
        "decision_digest": d_digest,
        "rule_set_version": RULE_SET_VERSION,
        "rules_digest": rules_digest,
        "disposition": aggregate_disposition(o.disposition for o in outcomes),
        "gates": outcomes,
        "inputs": {k: _as_text(v) for k, v in inputs.items()},
        "provenance": Provenance.POLICY_RESULT,
        "evaluated_at": evaluated_at,
        "expires_at": evaluated_at + timedelta(seconds=POLICY_EVIDENCE_TTL_SECONDS),
    }
    fields["record_id"] = "PEV-" + _record_digest(fields)[7:23].upper()
    fields["record_digest"] = _record_digest(fields)
    return PolicyEvaluationRecord(**fields)


_NOT_OVERRIDEABLE = HoldOverrideRule(overrideable=False, required_roles=frozenset(), basis="")


def _as_text(value: Any) -> str | None:
    canonical = _canonical_scalar(value)
    return None if canonical is None else str(canonical)


def persist_policy_record(state: dict[str, Any], record: PolicyEvaluationRecord) -> None:
    """Store ``record`` newest first. The caller holds the state lock."""
    log = state.setdefault("policy_evaluations", [])
    log.insert(0, record.model_dump(mode="json"))
    del log[MAX_PERSISTED_EVALUATIONS:]


def latest_policy_record(
    state: Mapping[str, Any], decision_id: str
) -> PolicyEvaluationRecord | None:
    """The newest record for ``decision_id``, re-validated from storage."""
    for raw in state.get("policy_evaluations", []):
        if raw.get("decision_id") == decision_id:
            return PolicyEvaluationRecord.model_validate_json(json.dumps(raw))
    return None


def _intact(record: PolicyEvaluationRecord) -> bool:
    return _record_digest(record.model_dump(mode="python")) == record.record_digest


# ── HOLD exceptions ────────────────────────────────────────────────────────────


def _held_gates(record: PolicyEvaluationRecord) -> tuple[str, ...]:
    return tuple(sorted(g.gate for g in record.gates if g.disposition is Disposition.HOLD))


def grant_hold_exception(
    *,
    record: PolicyEvaluationRecord,
    actor: ActorRef,
    authority_role: str,
    reason: str,
    ttl_seconds: int,
    now: datetime | None = None,
) -> PolicyHoldException:
    """Build an exception for ``record``'s HOLD, or raise if policy does not allow one."""
    granted_at = _utc(now)
    if record.disposition is not Disposition.HOLD:
        raise PolicyBindingError(
            "HOLD_EXCEPTION_NOT_APPLICABLE",
            f"the gate result is {record.disposition.value}; only a HOLD can be overridden",
        )
    if not reason or not reason.strip():
        raise PolicyBindingError("HOLD_EXCEPTION_INVALID", "a reason is required")
    if not 0 < ttl_seconds <= MAX_HOLD_EXCEPTION_SECONDS:
        raise PolicyBindingError(
            "HOLD_EXCEPTION_INVALID",
            f"expiry must be between 1 and {MAX_HOLD_EXCEPTION_SECONDS} seconds",
        )
    held = _held_gates(record)
    for gate in held:
        rule = HOLD_OVERRIDE_POLICY.get(gate, _NOT_OVERRIDEABLE)
        if not rule.overrideable:
            raise PolicyBindingError(
                "HOLD_NOT_OVERRIDEABLE", f"policy does not allow an exception for {gate}"
            )
        if authority_role not in rule.required_roles:
            raise PolicyBindingError(
                "HOLD_EXCEPTION_AUTHORITY",
                f"an exception for {gate} requires {sorted(rule.required_roles)}, "
                f"not {authority_role}",
            )
    fields: dict[str, Any] = {
        "decision_id": record.decision_id,
        "decision_digest": record.decision_digest,
        "policy_record_digest": record.record_digest,
        "held_gates": held,
        "authority": actor,
        "authority_role": authority_role,
        "reason": reason.strip(),
        "overrideable": True,
        "granted_at": granted_at,
        "expires_at": granted_at + timedelta(seconds=ttl_seconds),
    }
    exception_id = "HEX-" + digest_bytes(canonical_bytes_of(fields))[7:23].upper()
    return PolicyHoldException(exception_id=exception_id, **fields)


def persist_hold_exception(state: dict[str, Any], exception: PolicyHoldException) -> None:
    log = state.setdefault("policy_hold_exceptions", [])
    log.insert(0, exception.model_dump(mode="json"))
    del log[MAX_PERSISTED_EXCEPTIONS:]


def _exception_covers(
    exception: PolicyHoldException, record: PolicyEvaluationRecord, now: datetime
) -> bool:
    if not (
        exception.overrideable
        and exception.decision_id == record.decision_id
        and exception.decision_digest == record.decision_digest
        and exception.policy_record_digest == record.record_digest
        and exception.held_gates == _held_gates(record)
        and exception.granted_at <= now < exception.expires_at
    ):
        return False
    return all(
        HOLD_OVERRIDE_POLICY.get(gate, _NOT_OVERRIDEABLE).overrideable
        and exception.authority_role
        in HOLD_OVERRIDE_POLICY.get(gate, _NOT_OVERRIDEABLE).required_roles
        for gate in exception.held_gates
    )


# ── The approval check ─────────────────────────────────────────────────────────


def require_approvable(
    state: Mapping[str, Any],
    decision: Mapping[str, Any],
    *,
    rules_digest: str | None,
    now: datetime | None = None,
) -> PolicyEvaluationRecord:
    """Return the record that permits approving ``decision``, or raise PolicyBindingError."""
    at = _utc(now)
    decision_id = str(decision.get("id"))
    if not rules_digest:
        raise PolicyBindingError(
            "RULES_UNKNOWN", "the current pre-trade rules were not supplied; approval refused"
        )
    try:
        record = latest_policy_record(state, decision_id)
    except ValueError as exc:
        raise PolicyBindingError(
            "POLICY_EVIDENCE_INVALID", f"the stored gate result is malformed ({exc})"
        ) from exc
    if record is None:
        raise PolicyBindingError(
            "NO_POLICY_EVIDENCE",
            f"no pre-trade gate result for {decision_id}; run the pre-trade check first",
        )
    if not _intact(record):
        raise PolicyBindingError(
            "POLICY_EVIDENCE_INVALID", "the stored gate result does not match its digest"
        )
    if record.decision_digest != decision_digest(decision):
        raise PolicyBindingError(
            "STALE_POLICY_EVIDENCE",
            "the decision changed after its pre-trade check; run the check again",
        )
    if record.rules_digest != rules_digest:
        raise PolicyBindingError(
            "STALE_POLICY_EVIDENCE",
            "the pre-trade rules changed after the check; run the check again",
        )
    if not record.evaluated_at <= at < record.expires_at:
        raise PolicyBindingError(
            "STALE_POLICY_EVIDENCE",
            f"the pre-trade check expired at {record.expires_at.isoformat()}; run it again",
        )
    if record.disposition is Disposition.PASS:
        return record
    if record.disposition is Disposition.HOLD:
        for raw in state.get("policy_hold_exceptions", []):
            if raw.get("policy_record_digest") != record.record_digest:
                continue
            try:
                # JSON mode: stored records are JSON, and the kernel's strict
                # ActorRef accepts a JSON array, not a Python list, for a tuple.
                exception = PolicyHoldException.model_validate_json(json.dumps(raw))
            except ValueError:
                continue
            if _exception_covers(exception, record, at):
                return record
        raise PolicyBindingError(
            "HOLD_EXCEPTION_REQUIRED",
            "pre-trade gates HOLD "
            f"({', '.join(_held_gates(record))}); approval needs a current, typed "
            "exception from the authority the policy requires",
        )
    blocking = [g.gate for g in record.gates if g.disposition is record.disposition]
    raise PolicyBindingError(
        f"POLICY_{record.disposition.value}",
        f"pre-trade gates returned {record.disposition.value} ({', '.join(blocking)}); "
        "approval refused",
    )
