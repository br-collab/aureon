"""aureon.agents — Aureon Agent Package."""

from aureon.agents.base import (
    Advisory,
    Agent,
    DSORRecord,
    Escalation,
    GuardrailResult,
    HunterKillerAgent,
    Intent,
    JTACAgent,
    NotActivatedError,
    RangerAgent,
    Result,
    Tasking,
)
from aureon.agents.c2 import ThifurC2

# ThifurHAgent is the agent-framework class. The live session engine is
# aureon.thifur.thifur_h.ThifurH -- a different class (AUR-CANONICAL-AMD-001 §II).
from aureon.agents.hunter_killer import ThifurHAgent
from aureon.agents.jtac import ThifurJ
from aureon.agents.ranger import RangerConcreteBase, SettlementOps

__all__ = [
    "Advisory",
    "Agent",
    "DSORRecord",
    "Escalation",
    "GuardrailResult",
    "HunterKillerAgent",
    "Intent",
    "JTACAgent",
    "NotActivatedError",
    "RangerAgent",
    "RangerConcreteBase",
    "Result",
    "SettlementOps",
    "Tasking",
    "ThifurC2",
    "ThifurHAgent",
    "ThifurJ",
]
