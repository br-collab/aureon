"""
aureon.agents.triplet — Thifur Execution Triplet (500 ft)

    ThifurJ  — JTAC — Bounded autonomy pre-trade structuring
    ThifurR  — Ranger — Deterministic settlement execution
    ThifurH  — Hunter-Killer — Adaptive intelligence (DECLARED, NOT ACTIVATED)
"""

from aureon.agents.triplet.agent_j import ThifurJ
from aureon.agents.triplet.agent_r import ThifurR
from aureon.agents.triplet.agent_h import ThifurH

__all__ = ["ThifurJ", "ThifurR", "ThifurH"]
