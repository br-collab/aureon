"""
aureon.agents.ranger — Ranger agents (500 ft, deterministic execution)

Zero-variance guardrails: one input, one output, always.
No self-initiation — requires C2 handoff authorization.
"""

from aureon.agents.ranger._base import ThifurR

RANGER_AGENTS: dict[str, type] = {
    "THIFUR_R": ThifurR,
}

__all__ = ["ThifurR", "RANGER_AGENTS"]
