"""
aureon.agents.jtac — JTAC agents (500 ft, bounded autonomy)

Bounded-autonomy guardrails: approved paths only, doctrine over code,
no release without approval lineage.
"""

from aureon.agents.jtac._base import ThifurJ

JTAC_AGENTS: dict[str, type] = {
    "THIFUR_J": ThifurJ,
}

__all__ = ["ThifurJ", "JTAC_AGENTS"]
