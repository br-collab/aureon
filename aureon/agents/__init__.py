"""
aureon.agents — Aureon Agent Package

Tier-based subpackages:
    aureon.agents.c2        — Thifur-C2 Command & Control (1,000 ft)
    aureon.agents.triplet   — Thifur execution triplet (500 ft): J, R, H

Import pattern:
    from aureon.agents import ThifurC2, ThifurJ, ThifurR, ThifurH
    from aureon.agents import AureonAgent, NotActivatedError
"""

from aureon.agents._base import AureonAgent, NotActivatedError
from aureon.agents.c2 import ThifurC2
from aureon.agents.triplet import ThifurJ, ThifurR, ThifurH

__all__ = [
    "AureonAgent",
    "NotActivatedError",
    "ThifurC2",
    "ThifurJ",
    "ThifurR",
    "ThifurH",
]
