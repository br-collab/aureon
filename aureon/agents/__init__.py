"""aureon.agents — Aureon Agent Package."""

from aureon.agents.base import (
    Agent, NotActivatedError,
    RangerAgent, JTACAgent, HunterKillerAgent,
    Intent, Advisory, Tasking, Result, DSORRecord, Escalation, GuardrailResult,
)
from aureon.agents.c2 import ThifurC2
from aureon.agents.jtac import ThifurJ
from aureon.agents.ranger import RangerConcreteBase, SettlementOps
# ThifurHAgent is the agent-framework class. The live session engine is
# aureon.thifur.thifur_h.ThifurH -- a different class (AUR-CANONICAL-AMD-001 §II).
from aureon.agents.hunter_killer import ThifurHAgent

__all__ = [
    "Agent", "NotActivatedError",
    "RangerAgent", "JTACAgent", "HunterKillerAgent",
    "RangerConcreteBase", "SettlementOps",
    "ThifurC2", "ThifurJ", "ThifurHAgent",
    "Intent", "Advisory", "Tasking", "Result",
    "DSORRecord", "Escalation", "GuardrailResult",
]
