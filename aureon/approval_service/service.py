"""
aureon.approval_service.service
================================
Human-in-the-loop (HITL) decision resolution for Aureon Grid 3.

Handles the core approve/reject lifecycle:
  - Validates the decision exists and the system is not halted
  - Refuses any approval the persisted pre-trade policy record does not
    permit: a current PASS for this decision's digest and rules, or a HOLD
    covered by a typed exception (AUR-I-01; aureon.policy_engine.binding)
  - Recomputes the required roles from the decision's terms (AUR-I-08)
  - Records partial approvals (multi-role workflows)
  - On full approval: emits a RELEASE_AUTHORIZED event and nothing else. No
    trade record, cash movement or position change (AUR-I-02); those follow
    from an execution fill, in aureon.booking
  - On rejection: marks the decision cancelled
  - Stamps every action with a deterministic authority hash
"""

import hashlib
import json
from datetime import datetime, timezone

from aureon.approval_service.release import authorize_release, persist_release, release_id_for
from aureon.approval_service.routing import apply_routing
from aureon.contracts.approved_intent import ApprovalRecord, seal_approved_intent
from aureon.policy_engine.binding import (
    PolicyBindingError,
    persist_hold_exception,
    require_approvable,
)


def routed_required_approvals(decision):
    """Roles the decision needs: those already required plus those routing adds.

    Routing never removes a role a decision was created with; it adds the roles
    that materiality and exception flags demand (AUR-I-08).
    """
    required = list(decision.get("required_approvals") or [])
    for role in apply_routing(decision).required_approvals:
        if role not in required:
            required.append(role)
    return required


class AuthorityError(RuntimeError):
    """Approval refused because it does not come from an authenticated actor."""

    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def resolve_pending_decision(
    *,
    state,
    lock,
    decision_id,
    resolution,
    approval_role,
    actor=None,
    rules_digest=None,
    hold_exception=None,
    now=None,
):
    """
    Resolve a pending decision as APPROVED or REJECTED.

    Every entry point (dashboard, API, CLI, MCP) reaches approval through this
    function, so policy binding, authority and envelope sealing are the same
    whichever path a request took (AUR-I-05, partial).

    Parameters
    ----------
    state : dict
        The live aureon_state dictionary (mutated in-place under *lock*).
    lock : threading.Lock
        The state lock.
    decision_id : str
        ID of the decision to resolve.
    resolution : str
        "APPROVED" or "REJECTED".
    approval_role : str
        The role of the approving/rejecting authority (e.g. "TRADER").
    actor : cannae_kernel.actor.ActorRef
        The authenticated actor. Required to approve (W2B-2).
    rules_digest : str
        ``pretrade_rules_digest(...)`` of the rules in force. Required to
        approve: without it the evidence cannot be shown to be current.
    hold_exception : PolicyHoldException, optional
        An exception granted with this request for an overrideable HOLD. It is
        checked against the record and persisted only if the approval is
        permitted.
    now : datetime, optional
        The approval time (UTC); defaults to now. A fixed clock gives a
        reproducible envelope digest.

    Returns
    -------
    dict
        Keys: status, resolution, decision_id, hash, decision, policy_record,
        release, envelope. ``status`` is "ok" when the intent is sealed and
        release authorized, "pending" after a partial approval, "rejected".

    Raises
    ------
    LookupError
        If *decision_id* is not found in pending_decisions.
    AuthorityError
        (a RuntimeError) If the approval has no authenticated actor.
    PolicyBindingError
        (a RuntimeError) If the pre-trade policy record does not permit
        approval.
    IntentShapeError
        (a ValueError) If the decision cannot be sealed as a valid intent.
    RuntimeError
        If the system halt is active (status 423).
    ValueError
        If *resolution* is not "APPROVED" or "REJECTED".

    Nothing is recorded or changed when any of these is raised.
    """
    if resolution not in ("APPROVED", "REJECTED"):
        raise ValueError(f"Invalid resolution: {resolution!r}")

    at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    ts = at.isoformat()
    authority_hash = hashlib.sha256(
        f"AUREON-{resolution}-{decision_id}-{approval_role}-{ts}".encode()
    ).hexdigest()[:16].upper()

    with lock:
        # ── Halt check ────────────────────────────────────────────
        if state.get("halt_active"):
            raise RuntimeError(
                f"SYSTEM HALTED — {state.get('halt_reason', 'emergency halt active')}"
            )

        # ── Find the decision ─────────────────────────────────────
        pending = state.get("pending_decisions", [])
        decision = next((d for d in pending if d["id"] == decision_id), None)
        if decision is None:
            raise LookupError(f"Decision {decision_id!r} not found")

        if resolution == "REJECTED":
            # ── Rejection path ────────────────────────────────────
            pending[:] = [d for d in pending if d["id"] != decision_id]
            decision["status"] = "REJECTED"

            state["authority_log"].insert(0, {
                "id":        f"HAD-{decision_id[-8:]}",
                "ts":        ts,
                "tier":      "Tier 1 — Human Authority",
                "type":      f"REJECT {decision['action']} {decision['symbol']}",
                "authority": approval_role,
                "outcome":   f"REJECTED — ${float(decision.get('notional', 0) or 0):,.0f}",
                **({"actor": actor.model_dump(mode="json")} if actor is not None else {}),
                "hash":      authority_hash,
            })

            return {
                "status":      "rejected",
                "resolution":  "REJECTED",
                "decision_id": decision_id,
                "hash":        authority_hash,
                "decision":    decision,
                "policy_record": None,
                "release":     None,
                "envelope":    None,
            }

        # ── Approval path: check everything, then change anything ─
        if actor is None or not actor.authenticated:
            raise AuthorityError(
                "ACTOR_REQUIRED", "an approval must come from an authenticated actor"
            )

        # Policy binds before anything is recorded, partial approvals included.
        evidence = state
        if hold_exception is not None:
            evidence = dict(state)
            evidence["policy_hold_exceptions"] = [
                hold_exception.model_dump(mode="json"),
                *state.get("policy_hold_exceptions", []),
            ]
        policy_record = require_approvable(evidence, decision, rules_digest=rules_digest, now=at)
        policy_ref = {
            "record_id":       policy_record.record_id,
            "record_digest":   policy_record.record_digest,
            "decision_digest": policy_record.decision_digest,
            "disposition":     policy_record.disposition.value,
        }

        required = routed_required_approvals(decision)
        current = list(decision.get("current_approvals", []))
        if approval_role not in current:
            current.append(approval_role)
        records = [
            ApprovalRecord.model_validate_json(json.dumps(raw))
            for raw in decision.get("approval_records", [])
            if raw.get("role") != approval_role
        ]
        records.append(ApprovalRecord(role=approval_role, actor=actor, approved_at=at,
                                      authority_hash=authority_hash))
        all_approved = all(r in current for r in required)

        envelope = release = None
        if all_approved:
            missing_actor = [r for r in required if r not in {x.role for x in records}]
            if missing_actor:
                raise AuthorityError(
                    "ACTOR_REQUIRED",
                    f"roles {missing_actor} approved without an authenticated actor; "
                    "they must approve again",
                )
            exception_ids = [
                raw["exception_id"] for raw in evidence.get("policy_hold_exceptions", [])
                if raw.get("policy_record_digest") == policy_record.record_digest
            ] if policy_record.disposition.value == "HOLD" else []
            release_id = release_id_for(decision_id, policy_record.decision_digest)
            envelope = seal_approved_intent(
                decision=decision,
                policy_record=policy_record,
                hold_exception_ids=exception_ids,
                approvals=sorted(records, key=lambda r: r.role),
                required_roles=required,
                release_id=release_id,
                now=at,
            )
            release = authorize_release(envelope=envelope, release_id=release_id)

        # ── Everything checked; record it ─────────────────────────
        if hold_exception is not None:
            persist_hold_exception(state, hold_exception)
            state["authority_log"].insert(0, {
                "id":        hold_exception.exception_id,
                "ts":        ts,
                "tier":      "Tier 1 — Human Authority",
                "type":      f"HOLD EXCEPTION {decision['action']} {decision['symbol']}",
                "authority": hold_exception.authority_role,
                "outcome":   (f"Overrides {', '.join(hold_exception.held_gates)} until "
                              f"{hold_exception.expires_at.isoformat()}: {hold_exception.reason}"),
                "actor":     hold_exception.authority.model_dump(mode="json"),
                "hash":      hold_exception.exception_id,
            })
        decision["required_approvals"] = required
        decision["current_approvals"] = current
        decision["approval_records"] = [r.model_dump(mode="json") for r in records]

        if not all_approved:
            state["authority_log"].insert(0, {
                "id":        f"HAD-{decision_id[-8:]}",
                "ts":        ts,
                "tier":      "Tier 1 — Human Authority",
                "type":      f"PARTIAL APPROVE {decision['action']} {decision['symbol']}",
                "authority": approval_role,
                "outcome":   f"Role {approval_role} approved — awaiting {set(required) - set(current)}",
                "actor":     actor.model_dump(mode="json"),
                "policy":    policy_ref,
                "hash":      authority_hash,
            })
            return {
                "status":      "pending",
                "resolution":  "APPROVED",
                "decision_id": decision_id,
                "hash":        authority_hash,
                "decision":    decision,
                "policy_record": policy_record,
                "release":     None,
                "envelope":    None,
            }

        # ── Full approval — seal the intent, authorize release, nothing more ─
        persist_approved_intent(state, envelope)
        persist_release(state, release)
        pending[:] = [d for d in pending if d["id"] != decision_id]
        decision["status"] = "RELEASE_AUTHORIZED"
        decision["release_id"] = release.release_id
        decision["envelope_id"] = str(envelope.envelope_id)
        decision["envelope_digest"] = envelope.digest

        state["authority_log"].insert(0, {
            "id":        f"HAD-{decision_id[-8:]}",
            "ts":        ts,
            "tier":      "Tier 1 — Human Authority",
            "type":      f"APPROVE {decision['action']} {decision['symbol']}",
            "authority": approval_role,
            "outcome":   (f"INTENT SEALED, RELEASE AUTHORIZED — {release.release_id}; "
                          f"books only on execution"),
            "actor":     actor.model_dump(mode="json"),
            "policy":    policy_ref,
            "release_id": release.release_id,
            "envelope_digest": envelope.digest,
            "hash":      authority_hash,
        })

    return {
        "status":      "ok",
        "resolution":  "APPROVED",
        "decision_id": decision_id,
        "hash":        authority_hash,
        "decision":    decision,
        "policy_record": policy_record,
        "release":     release,
        "envelope":    envelope,
    }


def persist_approved_intent(state, envelope):
    log = state.setdefault("approved_intents", [])
    log.insert(0, envelope.model_dump(mode="json"))
    del log[1000:]


__all__ = [
    "AuthorityError",
    "PolicyBindingError",
    "persist_approved_intent",
    "resolve_pending_decision",
    "routed_required_approvals",
]
