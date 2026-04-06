"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/config/caom.py                                               ║
║  CAOM-001 — Consolidated Authority Operating Mode                    ║
║                                                                      ║
║  Implements the CAOM-001 doctrine addendum.                          ║
║  Registers a single operator as holder of all three Human Authority  ║
║  tiers. Enables approval gate resolution without requiring distinct  ║
║  credentialed role-holders.                                          ║
║                                                                      ║
║  DOCTRINE REFERENCE: CAOM-001 Draft 1.0 — Ravelo Strategic          ║
║  Solutions LLC — Effective 6 April 2026                             ║
║                                                                      ║
║  WHAT THIS FILE DOES:                                                ║
║    - Declares the operator identity and all role mappings            ║
║    - Exposes is_caom_active() for runtime gate checks                ║
║    - Exposes get_caom_roles() so release_control.py can resolve      ║
║      which approvals the operator already satisfies                  ║
║    - Documents the transition triggers for when CAOM ends            ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os
from datetime import datetime, timezone

# ── CAOM-001 Master Switch ────────────────────────────────────────────────────
# Set AUREON_CAOM=false in environment to disable CAOM and revert to
# multi-role institutional mode (e.g. when staff are onboarded).
#
# Default: True — CAOM is active for the one-man shop proof-of-concept.
CAOM_ACTIVE: bool = os.environ.get("AUREON_CAOM", "true").lower() != "false"

# ── Operator Identity ─────────────────────────────────────────────────────────
# The single human who holds all three authority tiers under CAOM-001.
CAOM_OPERATOR: dict = {
    "id":           "GR-001",
    "name":         "Guillermo Ravelo",
    "display_name": "Bill",
    "entity":       "Ravelo Strategic Solutions LLC",
    "email":        os.environ.get("AUREON_EMAIL", "aureonfsos@gmail.com"),
}

# ── Document Identity ─────────────────────────────────────────────────────────
CAOM_DOC_ID      = "CAOM-001"
CAOM_VERSION     = "Draft 1.0"
CAOM_EFFECTIVE   = "2026-04-06"

# ── Role-to-Tier Mapping ──────────────────────────────────────────────────────
# Under CAOM-001, the operator holds every approval role simultaneously.
# This maps each role token (used by approval_service) to the operator.
#
# CRITICAL: This does not remove approval gates. Gates still fire.
# The operator's identity satisfies the gate — agents do not.
#
# Doctrine reference: CAOM-001 §IV.A — Operator Identity Registration
CAOM_ROLE_MAP: dict[str, dict] = {
    # ── Tier 1 — Operational ──────────────────────────────────────────
    "TRADER":              {"tier": 1, "holder": CAOM_OPERATOR},
    "RISK_MANAGER":        {"tier": 1, "holder": CAOM_OPERATOR},
    "PORTFOLIO_MANAGER":   {"tier": 1, "holder": CAOM_OPERATOR},
    "PM":                  {"tier": 1, "holder": CAOM_OPERATOR},  # alias
    # ── Tier 2 — Governance ───────────────────────────────────────────
    "COMPLIANCE_OFFICER":  {"tier": 2, "holder": CAOM_OPERATOR},
    "RISK_COMMITTEE":      {"tier": 2, "holder": CAOM_OPERATOR},
    "CRO":                 {"tier": 2, "holder": CAOM_OPERATOR},
    "TIER_1":              {"tier": 2, "holder": CAOM_OPERATOR},  # Thifur-J tier label
    "TIER_1_RISK":         {"tier": 2, "holder": CAOM_OPERATOR},  # Thifur-J tier label
    "TIER_2":              {"tier": 2, "holder": CAOM_OPERATOR},  # Thifur-J tier label
    # ── Tier 3 — Executive ────────────────────────────────────────────
    # No agent substitution permitted. Operator action always required.
    "EXECUTIVE":           {"tier": 3, "holder": CAOM_OPERATOR},
}

# ── Agent Advisory Assignments ────────────────────────────────────────────────
# Which agent surfaces advisory analysis for each approval gate.
# Agents advise — operator decides. This is documentation, not execution logic.
#
# Doctrine reference: CAOM-001 §IV.B — Agent Role Assignments
CAOM_AGENT_ADVISORY: dict[str, str] = {
    "TRADER":            "Thifur-H: execution strategy, slippage, liquidity depth",
    "RISK_MANAGER":      "Mentat: risk framing; Kaladan: drawdown + position status; Thifur-J: policy compliance",
    "PORTFOLIO_MANAGER": "Mentat: mandate alignment, underweight/overweight flag, conviction score",
    "COMPLIANCE_OFFICER":"Verana: OFAC screening, doctrine integrity, systemic stress (auto-enforced)",
    "RISK_COMMITTEE":    "All layers via Thifur-C2: unified risk picture",
    "EXECUTIVE":         "All layers via Thifur-C2: unified picture. No agent substitution.",
}

# ── Transition Triggers ───────────────────────────────────────────────────────
# Conditions that require a formal review of whether CAOM should end.
# Doctrine reference: CAOM-001 §VII — Transition Out of CAOM
CAOM_TRANSITION_TRIGGERS: list[str] = [
    "AUM exceeds $10M — review dedicated Risk Manager separation",
    "External investor capital onboarded — Compliance Officer role separation required",
    "Regulatory examination scheduled — Tier 2/3 authority review required",
    "First institutional staff member hired — begin CAOM transition plan",
    "Strategy licensing to third party — licensing governance may impose role separation",
]


# ── Runtime API ───────────────────────────────────────────────────────────────

def is_caom_active() -> bool:
    """
    Returns True if CAOM-001 is the active operating mode.

    Called by release_control.py at every approval gate check.
    If False, the system reverts to multi-role institutional mode
    where each role must be held by a distinct credentialed user.
    """
    return CAOM_ACTIVE


def get_caom_roles() -> set[str]:
    """
    Returns the set of all role tokens the operator satisfies under CAOM.

    Used by missing_roles() in release_control.py to determine
    which required approvals are already met by the operator identity.

    Example: if a decision requires ["TRADER", "RISK_MANAGER"],
    both are in this set, so missing_roles() returns [] and the
    gate is satisfied.
    """
    return set(CAOM_ROLE_MAP.keys())


def get_operator_approval_token() -> str:
    """
    Returns the canonical operator identity string for stamping
    approval lineage in the DSOR record.

    Format: "OPERATOR:{name} (CAOM-{doc_id})"
    """
    return f"OPERATOR:{CAOM_OPERATOR['name']} ({CAOM_DOC_ID})"


def build_caom_session_declaration() -> dict:
    """
    Builds the DSOR-stamped CAOM session declaration record.

    Called at Step 2 of the Session Open Protocol (session_protocol.py).
    Logged to aureon_state["authority_log"] at session open.
    """
    return {
        "id":               f"CAOM-DECL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "ts":               datetime.now(timezone.utc).isoformat(),
        "type":             "CAOM_SESSION_DECLARATION",
        "doc_id":           CAOM_DOC_ID,
        "version":          CAOM_VERSION,
        "effective":        CAOM_EFFECTIVE,
        "operator":         CAOM_OPERATOR,
        "roles_held":       list(CAOM_ROLE_MAP.keys()),
        "tiers_held":       [1, 2, 3],
        "deployment":       "One-man shop · Agent-augmented",
        "agents_advisory":  CAOM_AGENT_ADVISORY,
        "immutable":        True,
        "dsor_stamped":     True,
    }


def build_caom_role_ack_record(acknowledged_tiers: list[int]) -> dict:
    """
    Builds the DSOR-stamped role acknowledgment record.

    Called at Step 3 of the Session Open Protocol after the operator
    checks all four acknowledgment boxes.
    """
    return {
        "id":                 f"CAOM-ACK-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "ts":                 datetime.now(timezone.utc).isoformat(),
        "type":               "CAOM_ROLE_ACK",
        "operator":           CAOM_OPERATOR,
        "acknowledged_tiers": acknowledged_tiers,
        "tier1_roles":        ["TRADER", "RISK_MANAGER", "PORTFOLIO_MANAGER"],
        "tier2_roles":        ["COMPLIANCE_OFFICER", "RISK_COMMITTEE", "CRO"],
        "tier3_roles":        ["EXECUTIVE"],
        "agents_advise_only": True,
        "operator_decides":   True,
        "dsor_stamped":       True,
    }
