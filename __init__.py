"""
aureon.thifur — Thifur Execution Intelligence Layer

Phase 1 agents:
    ThifurC2  — Command and Control master agent
    ThifurJ   — JTAC bounded autonomy agent (pre-trade structuring)
    ThifurR   — Ranger deterministic execution agent (settlement)

Phase 2+ declared (not active):
    ThifurH   — Hunter-Killer adaptive intelligence agent

Import pattern:
    from aureon.thifur.c2 import ThifurC2
    from aureon.thifur.agent_j import ThifurJ
    from aureon.thifur.agent_r import ThifurR
"""

from aureon.thifur.c2 import ThifurC2
from aureon.thifur.agent_j import ThifurJ
from aureon.thifur.agent_r import ThifurR

__all__ = ["ThifurC2", "ThifurJ", "ThifurR"]
