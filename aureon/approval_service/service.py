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
from datetime import datetime, timezone

from aureon.approval_service.release import authorize_release, persist_release
from aureon.approval_service.routing import apply_routing
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


def resolve_pending_decision(
    *,
    state,
    lock,
    decision_id,
    resolution,
    approval_role,
    rules_digest=None,
    hold_exception=None,
    now=None,
):
    """
    Resolve a pending decision as APPROVED or REJECTED.

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
    rules_digest : str
        ``pretrade_rules_digest(...)`` of the rules in force. Required to
        approve: without it the evidence cannot be shown to be current.
    hold_exception : PolicyHoldException, optional
        An exception granted with this request for an overrideable HOLD. It is
        checked against the record and persisted only if the approval is
        permitted.
    now : datetime, optional
        Evaluation time (UTC) for expiry checks; defaults to now.

    Returns
    -------
    dict
        Keys: status, resolution, decision_id, hash, decision,
              policy_record, release. ``status`` is "ok" when release is
              authorized, "pending" after a partial approval, "rejected".

    Raises
    ------
    LookupError
        If *decision_id* is not found in pending_decisions.
    PolicyBindingError
        (a RuntimeError) If the pre-trade policy record does not permit
        approval. Nothing is recorded or changed.
    RuntimeError
        If the system halt is active (status 423).
    ValueError
        If *resolution* is not "APPROVED" or "REJECTED".
    """
    if resolution not in ("APPROVED", "REJECTED"):
        raise ValueError(f"Invalid resolution: {resolution!r}")

    ts = datetime.now(timezone.utc).isoformat()
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
                "outcome":   f"REJECTED — ${decision.get('notional', 0):,}",
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
            }

        # ── Approval path ─────────────────────────────────────────
        # Policy binds before anything is recorded, partial approvals included.
        if hold_exception is not None:
            candidate = dict(state)
            candidate["policy_hold_exceptions"] = [
                hold_exception.model_dump(mode="json"),
                *state.get("policy_hold_exceptions", []),
            ]
            policy_record = require_approvable(
                candidate, decision, rules_digest=rules_digest, now=now
            )
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
        else:
            policy_record = require_approvable(
                state, decision, rules_digest=rules_digest, now=now
            )
        policy_ref = {
            "record_id":       policy_record.record_id,
            "record_digest":   policy_record.record_digest,
            "decision_digest": policy_record.decision_digest,
            "disposition":     policy_record.disposition.value,
        }

        decision["required_approvals"] = routed_required_approvals(decision)
        current = list(decision.get("current_approvals", []))
        if approval_role not in current:
            current.append(approval_role)
        decision["current_approvals"] = current

        required = list(decision.get("required_approvals", []))
        all_approved = all(r in current for r in required)

        if not all_approved:
            # Partial approval — record and return "pending" status
            state["authority_log"].insert(0, {
                "id":        f"HAD-{decision_id[-8:]}",
                "ts":        ts,
                "tier":      "Tier 1 — Human Authority",
                "type":      f"PARTIAL APPROVE {decision['action']} {decision['symbol']}",
                "authority": approval_role,
                "outcome":   f"Role {approval_role} approved — awaiting {set(required) - set(current)}",
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
            }

        # ── Full approval — authorize release, nothing more ───────
        release = authorize_release(
            decision=decision,
            policy_record=policy_record,
            approvals=current,
            authority_hash=authority_hash,
            now=now,
        )
        persist_release(state, release)
        pending[:] = [d for d in pending if d["id"] != decision_id]
        decision["status"] = "RELEASE_AUTHORIZED"
        decision["release_id"] = release.release_id

        state["authority_log"].insert(0, {
            "id":        f"HAD-{decision_id[-8:]}",
            "ts":        ts,
            "tier":      "Tier 1 — Human Authority",
            "type":      f"APPROVE {decision['action']} {decision['symbol']}",
            "authority": approval_role,
            "outcome":   (f"RELEASE AUTHORIZED — ${float(decision.get('notional', 0)):,.0f} "
                          f"({release.release_id}); books only on execution"),
            "policy":    policy_ref,
            "release_id": release.release_id,
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
    }


__all__ = ["PolicyBindingError", "resolve_pending_decision", "routed_required_approvals"]
