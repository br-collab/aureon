"""
aureon.agents.base — Agent ABC + shared doctrine types.

Every Aureon doctrine-governed agent inherits from Agent.
Shared types encode the lifecycle vocabulary that flows between
agents, C2, Kaladan, and the DSOR.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ── Exceptions ────────────────────────────────────────────────────────────────

class NotActivatedError(RuntimeError):
    """Raised when a declared-but-not-activated agent method is called."""


# ── Agent ABC ─────────────────────────────────────────────────────────────────

class Agent(ABC):
    """
    Base contract for all Aureon agents.

    Constructor: (aureon_state: dict, state_lock: threading.Lock)
    Required:    get_status() -> dict
    """

    def __init__(self, aureon_state: dict, state_lock: threading.Lock):
        self._state = aureon_state
        self._lock = state_lock

    @abstractmethod
    def get_status(self) -> dict:
        """Return agent operational status for dashboard and regulatory display."""
        ...


# ── Shared Doctrine Types ────────────────────────────────────────────────────
# These encode the lifecycle vocabulary shared across agents, C2, and DSOR.
# All agents produce or consume these; keeping them here avoids circular deps.

@dataclass
class Intent:
    """Operator intent — the what and why before any agent touches it."""
    action: str                        # BUY | SELL
    symbol: str
    asset_class: str
    notional: float
    rationale: str = ""
    signal_type: str = ""
    is_tokenized: bool = False
    has_smart_contract: bool = False
    cross_border: bool = False


@dataclass
class Advisory:
    """Agent advisory output — recommendation, never an order."""
    agent_id: str
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    recommendation: str = ""
    confidence: float = 0.0
    rationale: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Tasking:
    """C2 task record — tracks a lifecycle object across agents."""
    task_id: str
    agents: list[str] = field(default_factory=list)
    doctrine_version: str = "unknown"
    convergence_scenario: str | None = None
    status: str = "ACTIVE"


@dataclass
class Result:
    """Standardised agent result envelope."""
    agent_id: str
    task_id: str
    status: str                        # PASS | WARN | BLOCKED | COMPLETE
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data: dict[str, Any] = field(default_factory=dict)
    block_reason: str | None = None


@dataclass
class DSORRecord:
    """Decision System of Record entry — immutable after assembly."""
    task_id: str
    lineage_hash: str
    doctrine_version: str
    agents_involved: list[str] = field(default_factory=list)
    assembled_ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    dsor_ready: bool = False
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Escalation:
    """C2 escalation record — routed to human authority surface."""
    escalation_id: str
    task_id: str
    escalating_agent: str
    reason: str
    severity: str = "WARN"             # WARN | HALT | SUSPEND
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    context: dict[str, Any] = field(default_factory=dict)
    gaps_flagged: list[str] = field(default_factory=list)
    resolved: bool = False


@dataclass
class GuardrailResult:
    """Single gate / guardrail check outcome."""
    gate: str
    layer: str
    status: str                        # PASS | WARN | FAIL
    detail: str = ""
