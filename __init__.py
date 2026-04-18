"""
aureon.thifur — Thifur Execution Intelligence Layer

Phase 1 agents:
    ThifurC2  — Command and Control master agent
    ThifurJ   — JTAC bounded autonomy agent (pre-trade structuring)
    ThifurR   — Ranger deterministic execution agent (settlement)

Phase 2+ declared (not active):
    ThifurH   — Hunter-Killer adaptive intelligence agent

Import pattern:
    from aureon.agents import ThifurC2, ThifurJ, ThifurR, ThifurH
"""

from aureon.agents import ThifurC2, ThifurJ, ThifurR, ThifurH

__all__ = ["ThifurC2", "ThifurJ", "ThifurR", "ThifurH"]
