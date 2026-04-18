"""
aureon.agents.payloads — Typed dataclass payloads for inter-agent communication.

Structural fix for the implicit-dict bug class observed in:
  5fb207d — task_id identity
  b7326af — notional field missing
  82cd9ef — decision_id field missing

Each dataclass validates required fields at construction time via
__post_init__. MissingPayloadFieldError names the missing field
explicitly — no silent defaulting.

Dict-compatible: .get(key, default) works for backward compatibility
with Ranger methods that use dict-style access.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, asdict
from datetime import datetime, timezone
from typing import Optional, Any


class MissingPayloadFieldError(ValueError):
    """Raised when a typed payload is constructed without a required field."""
    def __init__(self, payload_name: str, missing_field: str):
        self.payload_name = payload_name
        self.missing_field = missing_field
        super().__init__(f"{payload_name} missing required field: {missing_field}")


class _DictCompatMixin:
    """Makes dataclasses dict-compatible for Ranger method backward compat."""

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def to_dict(self) -> dict:
        def _convert(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, _DictCompatMixin):
                return obj.to_dict()
            return obj

        result = {}
        for f in fields(self):
            val = getattr(self, f.name)
            if isinstance(val, list):
                result[f.name] = [_convert(v) for v in val]
            elif isinstance(val, dict):
                result[f.name] = val
            else:
                result[f.name] = _convert(val)
        return result

    @classmethod
    def from_dict(cls, d: dict):
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**filtered)


def _validate_required(instance, required_fields: list[str]) -> None:
    name = type(instance).__name__
    for f in required_fields:
        if getattr(instance, f) is None:
            raise MissingPayloadFieldError(name, f)


# ── Payloads ──────────────────────────────────────────────────────────────────

@dataclass
class ExecutionConfirmation(_DictCompatMixin):
    """OMS execution confirmation — consumed by TradeSupport and Reconciliation."""
    task_id: str = None
    decision_id: str = None
    symbol: str = None
    action: str = None
    notional: float = None
    shares: float = None
    price: float = 0.0
    venue: str = ""
    execution_ts: str = ""
    fix_msg_ref: Optional[str] = None

    # Aliases for backward compat: 'id' maps to decision_id
    @property
    def id(self):
        return self.decision_id

    def __post_init__(self):
        _validate_required(self, ["task_id", "symbol", "action", "notional", "shares"])


@dataclass
class DSORIntent(_DictCompatMixin):
    """DSOR pre-trade intent record — consumed by every reconciliation layer."""
    task_id: str = None
    decision_id: str = None
    symbol: str = None
    action: str = None
    notional: float = None
    shares: float = None
    intended_price: float = 0.0
    counterparty_lei: str = ""
    counterparty_id: str = ""
    instrument_class: str = ""
    intent_ts: str = ""
    authority_hash: str = ""

    # Aliases for backward compat
    @property
    def id(self):
        return self.decision_id

    def __post_init__(self):
        _validate_required(self, ["task_id", "decision_id", "symbol", "action", "notional"])


@dataclass
class TradeReconciliationResult(_DictCompatMixin):
    """Output of TradeSupport.reconcile_execution."""
    task_id: str = ""
    status: str = None
    matched: bool = False
    fields_checked: list = field(default_factory=list)
    mismatches: list = field(default_factory=list)
    agent: str = ""
    ts: str = ""
    decision_id: str = ""

    def __post_init__(self):
        _validate_required(self, ["status"])


@dataclass
class LineageCheckResult(_DictCompatMixin):
    """Output of Reconciliation.match_intent_vs_execution."""
    task_id: str = ""
    status: str = None
    matched: bool = False
    fields_checked: list = field(default_factory=list)
    unmatched: list = field(default_factory=list)
    agent: str = ""
    ts: str = ""
    decision_id: str = ""
    break_id: Optional[str] = None

    def __post_init__(self):
        _validate_required(self, ["status"])


@dataclass
class SettlementConfirmation(_DictCompatMixin):
    """Output of SettlementOps — settlement instruction confirmation."""
    task_id: str = None
    rail: str = ""
    settlement_cycle: str = ""
    settlement_ts: str = ""
    fix_settlement_msg_ref: str = ""
    bcbs239_p3_record_ref: str = ""

    def __post_init__(self):
        _validate_required(self, ["task_id"])


@dataclass
class ReportingContext(_DictCompatMixin):
    """Lifecycle-close context for RegReporting.prepare_execution_package."""
    task_id: str = None
    decision_id: str = None
    symbol: str = None
    action: str = None
    notional: float = 0
    asset_class: str = ""
    counterparty_lei: str = ""
    authority_hash: str = ""
    doctrine_version: str = "unknown"
    release_target: str = "OMS"

    # Alias for backward compat: prepare_execution_package reads .get("id")
    @property
    def id(self):
        return self.decision_id

    def __post_init__(self):
        _validate_required(self, ["task_id", "symbol", "action"])


@dataclass
class BreachEvent(_DictCompatMixin):
    """Input to RegReporting.generate_rts6_alert."""
    task_id: str = None
    breach_ts: str = None
    breach_source_role_id: str = ""
    breach_type: str = ""
    symbol: str = ""
    detail: str = ""
    decision_id: str = ""
    breach_payload: dict = field(default_factory=dict)

    def __post_init__(self):
        _validate_required(self, ["task_id", "breach_ts"])


@dataclass
class RTS6Alert(_DictCompatMixin):
    """Output of RegReporting.generate_rts6_alert."""
    task_id: str = ""
    alert_type: str = "RTS6_POST_TRADE"
    breach_ts: str = ""
    alert_ts: str = ""
    elapsed_seconds: float = 0.0
    sla_met: bool = True
    sla_threshold: float = 5.0
    breach_type: str = ""
    symbol: str = ""
    detail: str = ""
    decision_id: str = ""
    breach_source_role_id: str = ""


# ── JTAC Phase 4 payloads ──────────────────────────────────────────────────────
# Introduced alongside JTACConcreteBase + Compliance (AUR-J-COMP-001) for the
# bounded-autonomy tier. The contract these payloads carry:
#   - Selected-path record with attribution (who selected, which doctrine version)
#   - Approval-gate context rich enough for the operator (or future Operator
#     Console) to render the decision
#   - Conflict-registry record requiring dual-authority (Compliance + Legal)
#     resolution when a named doctrine/regulatory conflict is triggered


@dataclass
class ApprovedPath(_DictCompatMixin):
    """A single approved path that a JTAC role can select among.

    Phase 4 is code-as-path: callable_ref is the dotted Python path resolved
    at runtime. Phase 7+ introduces data-as-path where rule_data replaces the
    callable entirely. Both fields coexist here for forward-compatibility.
    """
    path_id: str = None
    role_id: str = None
    description: str = ""
    callable_ref: Optional[str] = None
    rule_data: Optional[dict] = None
    requires_approval: bool = False
    approval_predicates: list = field(default_factory=list)
    conflict_keys: list = field(default_factory=list)

    def __post_init__(self):
        _validate_required(self, ["path_id", "role_id"])


@dataclass
class JTACPathSelection(_DictCompatMixin):
    """JTAC's output: which approved path was selected and what's required next.

    Returned by every JTAC task method (screen_ofac, etc.). C2 reads this to
    decide whether to continue the lifecycle (requires_approval=False),
    halt for single-authority approval (requires_approval=True), or halt for
    dual-authority conflict resolution (requires_authority_resolution=True).
    """
    task_id: str = None
    role_id: str = None
    selected_path_id: str = None
    selection_rationale: str = ""
    requires_approval: bool = False
    pending_approval_for: list = field(default_factory=list)
    requires_authority_resolution: bool = False
    conflict_id: Optional[str] = None
    doctrine_version: Optional[str] = None
    selected_at: str = ""

    def __post_init__(self):
        _validate_required(self, ["task_id", "role_id", "selected_path_id"])
        if not self.selected_at:
            self.selected_at = datetime.now(timezone.utc).isoformat()


@dataclass
class ApprovalGateContext(_DictCompatMixin):
    """Payload C2 receives when JTAC returns requires_approval=True.

    Carries enough context for the operator (or future Operator Console) to
    render the gate and make the decision. Serialized into
    aureon_state["paused_lifecycles"][task_id] so a pause survives a restart.
    """
    task_id: str = None
    role_id: str = None
    path_selection: Optional[JTACPathSelection] = None
    intent_summary: dict = field(default_factory=dict)
    risk_summary: dict = field(default_factory=dict)
    pending_predicates: list = field(default_factory=list)
    halt_ts: str = ""

    def __post_init__(self):
        _validate_required(self, ["task_id", "role_id", "path_selection"])
        if not self.halt_ts:
            self.halt_ts = datetime.now(timezone.utc).isoformat()


@dataclass
class ConflictResolution(_DictCompatMixin):
    """Pre-determined conflict requiring dual-authority human resolution.

    Phase 4 fills both authority slots via CAOM-001 (Bill holds all tiers);
    the dual-role distinction is preserved in the payload shape so future
    org expansion (separate Compliance head + General Counsel) doesn't
    require a schema change.

    combined_resolution is only valid when both decision dicts are present.
    """
    task_id: str = None
    conflict_id: str = None
    conflict_summary: str = ""
    requires_compliance_authority: bool = True
    requires_legal_authority: bool = True
    compliance_authority_decision: Optional[dict] = None
    legal_authority_decision: Optional[dict] = None
    combined_resolution: Optional[dict] = None
    halt_ts: str = ""

    def __post_init__(self):
        _validate_required(self, ["task_id", "conflict_id"])
        if not self.halt_ts:
            self.halt_ts = datetime.now(timezone.utc).isoformat()


@dataclass
class CounterpartyScreeningRequest(_DictCompatMixin):
    """Input to Compliance.screen_ofac (AUR-J-COMP-001).

    counterparty_name is the primary screening key for Phase 4's exact-match
    semantics. Fuzzy, phonetic, transliteration, 50%-rule, and SSI matching
    are explicitly deferred.
    """
    task_id: str = None
    counterparty_name: str = None
    counterparty_jurisdiction: str = ""
    counterparty_lei: Optional[str] = None
    requested_at: str = ""

    def __post_init__(self):
        _validate_required(self, ["task_id", "counterparty_name"])
        if not self.requested_at:
            self.requested_at = datetime.now(timezone.utc).isoformat()


# ── Compliance Phase 4.5 payloads ─────────────────────────────────────────────
# Pre-Trade Policy Checks + IPS Eligibility + Algo Inventory (MiFID II RTS 6) +
# Approval Lineage Routing. Each task runs through the same halt-and-pend +
# approved-paths machinery as OFAC Screening (Phase 4).


@dataclass
class PreTradePolicyCheckRequest(_DictCompatMixin):
    """Input to Compliance.check_pretrade_policy.

    intent_summary is the per-trade snapshot the policy engine needs:
    asset_class, side, notional, instrument, counterparty.
    """
    task_id: str = None
    decision_id: str = None
    intent_summary: dict = field(default_factory=dict)
    mandate_version: str = None
    ips_version: str = None
    requested_at: str = ""

    def __post_init__(self):
        _validate_required(self, ["task_id", "decision_id", "mandate_version", "ips_version"])
        if not self.requested_at:
            self.requested_at = datetime.now(timezone.utc).isoformat()


@dataclass
class IPSEligibilityResult(_DictCompatMixin):
    """Output of Compliance.validate_ips_eligibility.

    Invoked internally by check_pretrade_policy. Not an independent
    lifecycle gate — the caller aggregates this into PreTradePolicyCheckResult.
    """
    task_id: str = None
    status: str = None               # "ELIGIBLE" | "INELIGIBLE"
    checks_performed: list = field(default_factory=list)
    ineligibilities: list = field(default_factory=list)
    ips_version: str = ""

    def __post_init__(self):
        _validate_required(self, ["task_id", "status"])


@dataclass
class PreTradePolicyCheckResult(_DictCompatMixin):
    """Output of Compliance.check_pretrade_policy.

    status semantics:
      - "PASS"  → lifecycle continues to ThifurJ.
      - "HOLD"  → halt-and-pend single-authority (approval override allowed).
      - "BLOCK" → terminal halt, no pend (hard violation).
    """
    task_id: str = None
    status: str = None               # "PASS" | "HOLD" | "BLOCK"
    policy_checks_performed: list = field(default_factory=list)
    failures: list = field(default_factory=list)
    ips_eligibility: Optional[dict] = None
    pending_approval_for: list = field(default_factory=list)
    selected_path_id: Optional[str] = None  # PRETRADE_POLICY_PASS/HOLD/BLOCK
    mandate_version: Optional[str] = None
    ips_version: Optional[str] = None

    def __post_init__(self):
        _validate_required(self, ["task_id", "status"])


@dataclass
class AlgoInventoryCheckRequest(_DictCompatMixin):
    """Input to Compliance.check_algo_inventory — MiFID II RTS 6 session-level
    check. Runs once per algorithm activation, not per trade."""
    task_id: str = None
    active_algorithms: list = field(default_factory=list)
    requested_at: str = ""

    def __post_init__(self):
        _validate_required(self, ["task_id"])
        if not self.requested_at:
            self.requested_at = datetime.now(timezone.utc).isoformat()


@dataclass
class AlgoInventoryCheckResult(_DictCompatMixin):
    """Output of Compliance.check_algo_inventory.

    status semantics:
      - "REGISTERED" → all active algorithms on the inventory with a valid
        last_validated_at date (within validation_frequency_days).
      - "MISSING_REGISTRATION" → at least one algorithm absent or stale →
        halt-and-pend dual-authority (Compliance + Legal).
    """
    task_id: str = None
    status: str = None               # "REGISTERED" | "MISSING_REGISTRATION"
    registered_algorithms: list = field(default_factory=list)
    missing_registrations: list = field(default_factory=list)
    pending_approval_for: list = field(default_factory=list)
    selected_path_id: Optional[str] = None

    def __post_init__(self):
        _validate_required(self, ["task_id", "status"])


@dataclass
class ApprovalLineageRequirement(_DictCompatMixin):
    """Output of Compliance.determine_approval_lineage.

    Utility method — NOT a lifecycle gate. Called by halt-and-pend /
    resume logic to determine which human authorities must sign off
    for a given pause_reason. Replaces hardcoded authority lists.
    """
    task_id: str = None
    pause_reason: str = None
    required_authorities: list = field(default_factory=list)
    sla_seconds: Optional[int] = None
    fallback_authorities: list = field(default_factory=list)

    def __post_init__(self):
        _validate_required(self, ["task_id", "pause_reason"])
