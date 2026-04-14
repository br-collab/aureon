"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/approval_service/release_control.py                          ║
║                                                                      ║
║  CAOM-001 PATCH — 6 April 2026                                       ║
║                                                                      ║
║  WHAT CHANGED AND WHY:                                               ║
║    missing_roles() and can_release() now check is_caom_active()      ║
║    before evaluating which roles are "missing".                      ║
║                                                                      ║
║    Under CAOM-001, the operator holds all roles simultaneously.      ║
║    Any role in the required set that exists in CAOM_ROLES is         ║
║    considered satisfied by the operator — no separate credential     ║
║    needed.                                                           ║
║                                                                      ║
║    The gate still fires. Approval action is still required.          ║
║    The difference: the operator's action IS recognized as valid      ║
║    for every role token, so the gate clears.                         ║
║                                                                      ║
║  ROOT CAUSE OF 6 APRIL 2026 FAILURE:                                 ║
║    Decision required ["TRADER"]. current_approvals = [].             ║
║    missing_roles() returned ["TRADER"].                              ║
║    Operator clicked Approve but approval_role was not in a           ║
║    recognized set — system waited for a role that was never          ║
║    mapped to any user. CAOM-001 fixes this by mapping every          ║
║    role to the operator.                                             ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

# ── CAOM-001 integration ──────────────────────────────────────────────────────
from aureon.config.caom import (
    is_caom_active,
    get_caom_roles,
    get_operator_approval_token,
    CAOM_OPERATOR,
)


# ── Decision Dataclass ────────────────────────────────────────────────────────

@dataclass
class Decision:
    """
    Normalized view of a pending decision dict.
    Immutable after construction — use to_mapping() to get the dict back.
    """
    id:                  str
    action:              str
    symbol:              str
    asset_class:         str
    shares:              float
    notional:            float
    signal_type:         str
    rationale:           str
    release_target:      str
    required_approvals:  list[str]
    current_approvals:   list[str]

    # Flags
    mandate_sensitive:   bool = False
    policy_exception:    bool = False
    risk_exception:      bool = False
    control_exception:   bool = False
    pm_signoff_required: bool = False
    financing_relevant:  bool = False

    def to_mapping(self) -> dict:
        return {
            "id":                  self.id,
            "action":              self.action,
            "symbol":              self.symbol,
            "asset_class":         self.asset_class,
            "shares":              self.shares,
            "notional":            self.notional,
            "signal_type":         self.signal_type,
            "rationale":           self.rationale,
            "release_target":      self.release_target,
            "required_approvals":  self.required_approvals,
            "current_approvals":   self.current_approvals,
            "mandate_sensitive":   self.mandate_sensitive,
            "policy_exception":    self.policy_exception,
            "risk_exception":      self.risk_exception,
            "control_exception":   self.control_exception,
            "pm_signoff_required": self.pm_signoff_required,
            "financing_relevant":  self.financing_relevant,
        }


def normalize_decision(raw: dict) -> Decision:
    """Convert a raw state dict decision to a typed Decision object."""
    return Decision(
        id                  = raw.get("id", ""),
        action              = raw.get("action", ""),
        symbol              = raw.get("symbol", ""),
        asset_class         = raw.get("asset_class", "equities"),
        shares              = float(raw.get("shares", 0)),
        notional            = float(raw.get("notional", 0)),
        signal_type         = raw.get("signal_type", ""),
        rationale           = raw.get("rationale", ""),
        release_target      = raw.get("release_target", "OMS"),
        required_approvals  = list(raw.get("required_approvals", ["TRADER"])),
        current_approvals   = list(raw.get("current_approvals", [])),
        mandate_sensitive   = bool(raw.get("mandate_sensitive", False)),
        policy_exception    = bool(raw.get("policy_exception", False)),
        risk_exception      = bool(raw.get("risk_exception", False)),
        control_exception   = bool(raw.get("control_exception", False)),
        pm_signoff_required = bool(raw.get("pm_signoff_required", False)),
        financing_relevant  = bool(raw.get("financing_relevant", False)),
    )


# ── Core Gate Functions ───────────────────────────────────────────────────────

def missing_roles(decision: Decision) -> list[str]:
    """
    Returns the list of required approval roles not yet satisfied.

    CAOM-001 BEHAVIOUR:
        If CAOM is active, every required role that exists in the
        operator's consolidated role set is considered pre-satisfied
        as long as at least one operator approval action has been
        recorded (current_approvals is not empty) OR the role is in
        the CAOM role set and the session is open.

        The gate still requires an explicit operator action.
        The difference from the pre-CAOM behaviour: the operator's
        action satisfies ALL required roles, not just one.

    MULTI-ROLE INSTITUTIONAL BEHAVIOUR (CAOM inactive):
        Each role in required_approvals must be independently present
        in current_approvals. Original pre-patch logic unchanged.
    """
    required = set(decision.required_approvals)
    satisfied = set(decision.current_approvals)

    if is_caom_active():
        caom_roles = get_caom_roles()

        # Any role the operator holds (all of them under CAOM) is
        # satisfied as soon as ANY approval action has been recorded.
        # The operator's single approval action covers all role tokens.
        if satisfied:
            # Operator has acted — all CAOM-covered roles are satisfied.
            caom_satisfied = required & caom_roles
            remaining = required - caom_satisfied - satisfied
            return sorted(remaining)
        else:
            # No approval action yet — gate still needs the operator to act.
            # Return the required roles so the UI shows what's pending.
            # But label them as operator-satisfiable (not externally blocked).
            return sorted(required)

    # ── Non-CAOM path (multi-role institutional) ───────────────────────────
    return sorted(required - satisfied)


def can_release(decision: Decision) -> bool:
    """
    Returns True if the decision has all required approvals and
    may be released to OMS.

    Under CAOM-001: True when missing_roles() returns [].
    Under multi-role: same condition, but each role needs its own approval.
    """
    return len(missing_roles(decision)) == 0


# ── Approval Recording ────────────────────────────────────────────────────────

def record_approval(decision_raw: dict, approval_role: str) -> dict:
    """
    Record an approval action against a decision.

    Under CAOM-001: the operator's approval token is stamped, and
    because the operator holds all roles, the action is recorded as
    satisfying the specific role requested AND sets the CAOM operator
    token in current_approvals.

    Returns the updated decision dict.
    """
    # Normalize the role token
    role = approval_role.upper().strip()

    # Stamp operator token under CAOM
    if is_caom_active():
        operator_token = get_operator_approval_token()
        approvals = list(decision_raw.get("current_approvals", []))
        if role not in approvals:
            approvals.append(role)
        if operator_token not in approvals:
            approvals.append(operator_token)
        decision_raw["current_approvals"] = approvals
    else:
        approvals = list(decision_raw.get("current_approvals", []))
        if role not in approvals:
            approvals.append(role)
        decision_raw["current_approvals"] = approvals

    decision_raw["last_approval_ts"]   = datetime.now(timezone.utc).isoformat()
    decision_raw["last_approval_role"]  = role
    return decision_raw


# ── OMS Release Package ───────────────────────────────────────────────────────

def release_to_oms(
    decision:       dict,
    authority_hash: str,
    oms_send:       Optional[Callable] = None,
) -> dict:
    """
    Build the governed OMS release package and optionally call oms_send.

    Stamps CAOM-001 operating mode on the package if CAOM is active.
    """
    ts = datetime.now(timezone.utc).isoformat()

    package = {
        "package_id":       f"OMS-{authority_hash[:8]}",
        "ts":               ts,
        "decision_id":      decision.get("id"),
        "action":           decision.get("action"),
        "symbol":           decision.get("symbol"),
        "shares":           decision.get("shares"),
        "notional":         decision.get("notional"),
        "asset_class":      decision.get("asset_class"),
        "release_target":   decision.get("release_target", "OMS"),
        "authority_hash":   authority_hash,
        "approval_lineage": decision.get("current_approvals", []),
        "status":           "RELEASED",
        "dsor_stamped":     True,
    }

    # Stamp CAOM operating mode on the release record
    if is_caom_active():
        package["operating_mode"]    = "CAOM-001"
        package["caom_operator"]     = CAOM_OPERATOR["name"]
        package["caom_operator_id"]  = CAOM_OPERATOR["id"]

    if oms_send is not None:
        try:
            oms_send(package)
        except Exception as exc:
            package["oms_send_error"] = str(exc)
            package["status"]         = "RELEASED_SEND_FAILED"

    return package


# ── Execution Release (EMS path) ──────────────────────────────────────────────

def build_execution_release(decision: dict, authority_hash: str) -> dict:
    """Build the EMS release package (used when release_target == 'EMS')."""
    ts = datetime.now(timezone.utc).isoformat()
    return {
        "package_id":     f"EMS-{authority_hash[:8]}",
        "ts":             ts,
        "decision_id":    decision.get("id"),
        "action":         decision.get("action"),
        "symbol":         decision.get("symbol"),
        "shares":         decision.get("shares"),
        "notional":       decision.get("notional"),
        "release_target": "EMS",
        "authority_hash": authority_hash,
        "status":         "RELEASED_TO_EMS",
        "dsor_stamped":   True,
        **({"operating_mode": "CAOM-001"} if is_caom_active() else {}),
    }


# ── Authority Hash ────────────────────────────────────────────────────────────

def build_authority_hash(decision_id: str, resolution: str,
                          approval_role: str, ts: str) -> str:
    """Build the immutable authority hash for a resolution event."""
    seed = f"{decision_id}{resolution}{approval_role}{ts}"
    if is_caom_active():
        seed += CAOM_OPERATOR["id"]
    return hashlib.sha256(seed.encode()).hexdigest()[:32].upper()
