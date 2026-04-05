"""
aureon.approval_service.release_control
========================================
Role-based release control for Aureon Grid 3.

Provides:
  - normalize_decision  — wraps a raw decision dict in a typed object
  - can_release         — checks whether all required approvals are present
  - missing_roles       — returns the list of roles still needed
  - release_to_oms      — packages and dispatches a governed release to the OMS
"""

from datetime import datetime, timezone
import hashlib


class Decision:
    """
    Typed wrapper around a raw pending-decision dict.

    Exposes required fields as attributes so callers can use
    ``decision.policy_exception`` instead of ``decision.get("policy_exception")``.
    Also provides ``to_mapping()`` for serialisation.
    """

    def __init__(self, raw: dict):
        self._raw = raw

    # ── Identity ──────────────────────────────────────────────────
    @property
    def id(self):
        return self._raw.get("id", "")

    @property
    def action(self):
        return self._raw.get("action", "")

    @property
    def symbol(self):
        return self._raw.get("symbol", "")

    @property
    def asset_class(self):
        return self._raw.get("asset_class", "")

    @property
    def shares(self):
        return self._raw.get("shares", 0)

    @property
    def price(self):
        return self._raw.get("price", 0.0)

    @property
    def notional(self):
        return self._raw.get("notional", 0)

    @property
    def rationale(self):
        return self._raw.get("rationale", "")

    @property
    def status(self):
        return self._raw.get("status", "PENDING")

    # ── Approval state ────────────────────────────────────────────
    @property
    def required_approvals(self):
        return list(self._raw.get("required_approvals", []))

    @property
    def current_approvals(self):
        return list(self._raw.get("current_approvals", []))

    # ── Governance flags ──────────────────────────────────────────
    @property
    def mandate_sensitive(self):
        return bool(self._raw.get("mandate_sensitive", False))

    @property
    def policy_exception(self):
        return bool(self._raw.get("policy_exception", False))

    @property
    def risk_exception(self):
        return bool(self._raw.get("risk_exception", False))

    @property
    def pm_signoff_required(self):
        return bool(self._raw.get("pm_signoff_required", False))

    @property
    def control_exception(self):
        return bool(self._raw.get("control_exception", False))

    @property
    def financing_relevant(self):
        return bool(self._raw.get("financing_relevant", False))

    @property
    def release_target(self):
        return self._raw.get("release_target", "OMS")

    # ── Pass-through for dict-style access ────────────────────────
    def get(self, key, default=None):
        return self._raw.get(key, default)

    def __getitem__(self, key):
        return self._raw[key]

    def __contains__(self, key):
        return key in self._raw

    def to_mapping(self) -> dict:
        """Return a plain dict copy suitable for JSON serialisation."""
        return dict(self._raw)


def normalize_decision(raw) -> Decision:
    """
    Wrap *raw* (a dict or Decision) in a Decision object.

    Idempotent — passing an already-wrapped Decision returns it unchanged.
    """
    if isinstance(raw, Decision):
        return raw
    return Decision(raw)


def missing_roles(decision: Decision) -> list:
    """
    Return the list of approval roles that have not yet signed off.

    Compares ``required_approvals`` against ``current_approvals``.
    """
    required = set(decision.required_approvals)
    current  = set(decision.current_approvals)
    return sorted(required - current)


def can_release(decision: Decision) -> bool:
    """
    Return True if all required approvals are present and the decision
    is ready for governed release to the OMS/EMS.
    """
    return len(missing_roles(decision)) == 0


def release_to_oms(decision, *, authority_hash: str, oms_send) -> dict:
    """
    Package a governed release packet and dispatch it to the OMS.

    Parameters
    ----------
    decision : dict or Decision
        The approved decision.
    authority_hash : str
        SHA-256 authority hash stamped at approval.
    oms_send : callable
        The OMS adapter send function.

    Returns
    -------
    dict
        The release packet that was sent (stored in integration_handoffs).
    """
    d = normalize_decision(decision)
    ts = datetime.now(timezone.utc).isoformat()

    packet = {
        "type":           "OMS_RELEASE",
        "decision_id":    d.id,
        "action":         d.action,
        "symbol":         d.symbol,
        "asset_class":    d.asset_class,
        "shares":         d.shares,
        "price":          d.price,
        "notional":       d.notional,
        "authority_hash": authority_hash,
        "release_target": d.release_target,
        "ts":             ts,
        "status":         "SENT",
    }

    try:
        oms_send(packet)
    except Exception as exc:
        packet["status"] = f"SEND_ERROR: {exc}"

    return packet
