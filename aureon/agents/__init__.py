"""
aureon.agents — Aureon Agent Package

Subpackages:
    aureon.agents.c2             — Thifur-C2 Command & Control (1,000 ft)
    aureon.agents.jtac           — JTAC bounded-autonomy agents (500 ft)
    aureon.agents.ranger         — Ranger deterministic-execution agents (500 ft)
    aureon.agents.hunter_killer  — Hunter-Killer adaptive agents (500 ft, DECLARED)

Import pattern:
    from aureon.agents import ThifurC2, ThifurJ, ThifurR, ThifurH
    from aureon.agents import Agent, NotActivatedError
    from aureon.agents.base import Intent, Advisory, Tasking, Result, DSORRecord, Escalation, GuardrailResult
"""

from aureon.agents.base import Agent, NotActivatedError
from aureon.agents.c2 import ThifurC2
from aureon.agents.jtac import ThifurJ
from aureon.agents.ranger import ThifurR
from aureon.agents.hunter_killer import ThifurH

__all__ = [
    "Agent",
    "NotActivatedError",
    "ThifurC2",
    "ThifurJ",
    "ThifurR",
    "ThifurH",
]
