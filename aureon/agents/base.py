"""aureon.agents.base — Agent ABC, tier base classes, and shared doctrine types."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ── Exceptions ────────────────────────────────────────────────────────────────

class NotActivatedError(RuntimeError):
    """Raised when a declared-but-not-activated agent is invoked."""


# ── Shared Doctrine Types ────────────────────────────────────────────────────

@dataclass
class Intent:
    """Advisory input."""
    timestamp: datetime
    operator: str
    payload: dict


@dataclass
class Advisory:
    """Advisory output."""
    timestamp: datetime
    agent_role_id: str
    summary: str
    recommendation: dict
    requires_approval: bool = True


@dataclass
class Tasking:
    """Execution input (R/J only)."""
    timestamp: datetime
    operator: str
    c2_tasking_id: str
    payload: dict


@dataclass
class Result:
    """Execution output (R/J only)."""
    timestamp: datetime
    agent_role_id: str
    outcome: str
    dsor_record_id: str


@dataclass
class DSORRecord:
    """Decision System of Record entry — immutable after assembly."""
    record_id: str
    caom_mode: str = "CAOM-001"
    operator: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str = ""
    payload: dict = field(default_factory=dict)


@dataclass
class GuardrailResult:
    """Single gate / guardrail check outcome."""
    passed: bool
    rule: str
    reason: Optional[str] = None


@dataclass
class Escalation:
    """Routed to human authority surface."""
    timestamp: datetime
    agent_role_id: str
    reason: str
    requires_authority_tier: int


# ── Agent ABC ─────────────────────────────────────────────────────────────────

class Agent(ABC):
    """Uniform contract for all Aureon doctrine-governed agents."""

    tier: int
    thifur_class: str
    role_id: str
    activated: bool = True

    def __init__(self, aureon_state: dict, state_lock: threading.Lock):
        self._state = aureon_state
        self._lock = state_lock

    @abstractmethod
    def advise(self, intent: Intent) -> Advisory:
        """Produce an advisory from an operator intent."""
        ...

    @abstractmethod
    def execute(self, tasking: Tasking) -> Result:
        """Execute a C2-issued tasking."""
        ...

    @abstractmethod
    def get_status(self) -> dict:
        """Return agent operational status for dashboard and regulatory display."""
        ...

    def guardrail_check(self, action) -> GuardrailResult:
        """Default guardrail — pass. Overridden by tier base classes."""
        return GuardrailResult(passed=True, rule="default")

    def dsor_stamp(self, event) -> DSORRecord:
        """Stamp a DSOR record for the given event."""
        return DSORRecord(
            record_id=f"DSOR-{id(event)}",
            operator=event.get("operator", "") if isinstance(event, dict) else "",
            event_type=event.get("event_type", "") if isinstance(event, dict) else "",
            payload=event if isinstance(event, dict) else {},
        )

    def escalate(self, reason: str) -> Escalation:
        """Escalate to human authority."""
        return Escalation(
            timestamp=datetime.now(timezone.utc),
            agent_role_id=self.role_id,
            reason=reason,
            requires_authority_tier=self.tier,
        )


# ── Tier Base Classes ─────────────────────────────────────────────────────────

class RangerAgent(Agent):
    """Tier 1 — zero-variance deterministic execution."""
    tier = 1
    thifur_class = "R"

    def guardrail_check(self, action) -> GuardrailResult:
        """Enforce zero variance and no self-initiation."""
        if isinstance(action, dict) and action.get("self_initiated"):
            return GuardrailResult(
                passed=False,
                rule="no-self-initiation",
                reason="Ranger agents require C2 handoff authorization",
            )
        return GuardrailResult(passed=True, rule="zero-variance")


class JTACAgent(Agent):
    """Tier 2 — bounded-autonomy pre-trade governance."""
    tier = 2
    thifur_class = "J"

    def guardrail_check(self, action) -> GuardrailResult:
        """Enforce approved paths only and approval lineage."""
        if isinstance(action, dict):
            if action.get("unapproved_path"):
                return GuardrailResult(
                    passed=False,
                    rule="approved-paths-only",
                    reason="JTAC selects among pre-approved paths, never generates new ones",
                )
            if action.get("missing_approval_lineage"):
                return GuardrailResult(
                    passed=False,
                    rule="no-release-without-approval-lineage",
                    reason="No release without complete approval lineage",
                )
        return GuardrailResult(passed=True, rule="bounded-autonomy")


class HunterKillerAgent(Agent):
    """Tier 3 — adaptive intelligence. DECLARED, NOT ACTIVATED."""
    tier = 3
    thifur_class = "H"
    activated = False

    def execute(self, tasking: Tasking) -> Result:
        """Always raises — Thifur-H is declared, not activated."""
        raise NotActivatedError(
            "Thifur-H is declared, not activated under current doctrine."
        )

    def guardrail_check(self, action) -> GuardrailResult:
        """Block all execution while not activated."""
        return GuardrailResult(
            passed=False,
            rule="activation-required",
            reason="Hunter-Killer agent not activated — SR 11-7 Tier 1 validation pending",
        )
