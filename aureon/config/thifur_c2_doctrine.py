"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/config/thifur_c2_doctrine.py                                 ║
║  Thifur-C2 — Command and Control Doctrine Declaration                ║
║                                                                      ║
║  DOCTRINE REFERENCE: Thifur-C2 · Draft 1.0                          ║
║  Ravelo Strategic Solutions LLC                                      ║
║  Author: Guillermo "Bill" Ravelo · Columbia University MS TM         ║
║                                                                      ║
║  MANDATE: C2 sequences, coordinates, records handoffs, assembles     ║
║  unified lineage, and presents a single human authority surface      ║
║  across all execution agents simultaneously.                         ║
║                                                                      ║
║  C2 does not originate. C2 does not execute.                         ║
║  C2 does not interpret doctrine. C2 governs the handoff chain.       ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Document Identity ─────────────────────────────────────────────────────────
C2_DOC_ID    = "THIFUR-C2"
C2_VERSION   = "Draft 1.0"
C2_EFFECTIVE = "2026-04-09"

# ── Agent Identity ────────────────────────────────────────────────────────────
C2_AGENT: dict = {
    "id":        "C2-001",
    "name":      "Thifur-C2",
    "short_name": "C2",
    "role":      "Command and Control — Execution Coordination",
    "doc_id":    C2_DOC_ID,
    "version":   C2_VERSION,
    "effective": C2_EFFECTIVE,
}

# ── Five Immutable Stops ──────────────────────────────────────────────────────
# Not configurable. Not subject to override by any agent.
# May only be modified by the operator through a formal doctrine addendum
# recorded in Verana's Network Registry.
C2_IMMUTABLE_STOPS: list[dict] = [
    {
        "stop":        1,
        "name":        "No Self-Execution",
        "rule":        "C2 never takes a market action",
        "enforcement": "Any market action attempted by C2 code is a doctrine breach",
    },
    {
        "stop":        2,
        "name":        "No Doctrine Interpretation",
        "rule":        "Mentat owns doctrine. C2 sequences it.",
        "enforcement": "C2 receives doctrine version from the lifecycle packet, never evaluates it",
    },
    {
        "stop":        3,
        "name":        "Handoff Before Action",
        "rule":        "No agent acts on a lifecycle object without a C2 handoff record",
        "enforcement": "Receiving agent must confirm handoff via confirm_handoff_received() before acting",
    },
    {
        "stop":        4,
        "name":        "One Lineage Record",
        "rule":        "DSOR never receives raw agent telemetry",
        "enforcement": "All agent telemetry feeds C2. C2 assembles unified lineage. C2 feeds DSOR.",
    },
    {
        "stop":        5,
        "name":        "Escalation Completeness",
        "rule":        "C2 never escalates partial context",
        "enforcement": (
            "C2 waits for all active agent context within ESCALATION_TIMEOUT before "
            "packaging escalation. Gaps are flagged explicitly — never silently dropped."
        ),
    },
]

# ── C2 Task Registry ──────────────────────────────────────────────────────────
C2_TASK_REGISTRY: list[dict] = [
    {"task": "TASK-1", "name": "Accept lifecycle from Kaladan", "agent": "Kaladan → C2"},
    {"task": "TASK-2", "name": "Issue tasking to Thifur agents", "agent": "C2 → R/J/H"},
    {"task": "TASK-3", "name": "Govern agent handoffs with signed records", "agent": "C2"},
    {"task": "TASK-4", "name": "Collect agent telemetry", "agent": "R/J/H → C2"},
    {"task": "TASK-5", "name": "Assemble unified lineage record", "agent": "C2"},
    {"task": "TASK-6", "name": "Submit DSOR-ready record", "agent": "C2 → DSOR"},
    {"task": "TASK-7", "name": "Route escalations to single human surface", "agent": "C2 → Operator"},
    {"task": "TASK-8", "name": "Govern TradFi-DeFi boundary crossings", "agent": "C2"},
]

# ── Convergence Governance Summary ────────────────────────────────────────────
# Full table lives in c2.py. This is the doctrine declaration.
C2_CONVERGENCE_MANDATE: str = (
    "C2 is the sole coordination point when lifecycle objects cross the "
    "TradFi-DeFi boundary. No agent on either side of that boundary "
    "communicates directly across it. All cross-boundary coordination "
    "routes through C2."
)

# ── Authority Chain (complete) ────────────────────────────────────────────────
C2_AUTHORITY_CHAIN: list[str] = [
    "Neptune Spear: origination & recommendation",
    "Human Authority: approval required before any action",
    "Kaladan L2: lifecycle structuring & packaging",
    "Thifur-C2: coordination, handoff governance, unified lineage",
    "Thifur-R: TradFi settlement execution (deterministic)",
    "Thifur-J: DeFi / programmable asset governance",
    "Thifur-H: adaptive execution optimization",
]

# ── Why C2 Must Exist ─────────────────────────────────────────────────────────
C2_RATIONALE: str = (
    "The Thifur execution triplet — R, J, H — solves the three distinct "
    "execution problems of modern global finance. Each agent is specialized, "
    "governed, and powerful within its domain. But specialization creates a new "
    "problem: when all three are active simultaneously on a single lifecycle "
    "object, who holds the complete picture? Without C2, the answer is: nobody. "
    "With C2, the answer is: always C2. One unified lineage. One escalation "
    "surface. One coordination point at the convergence boundary. One authority "
    "hash trail from Neptune origination to final settlement. C2 is what makes "
    "the Aureon architecture auditable at institutional scale."
)


def get_c2_doctrine_declaration() -> dict:
    """
    Returns the full Thifur-C2 doctrine declaration record.
    Stamped into authority_log at startup.
    """
    from datetime import datetime, timezone
    return {
        "id":              f"C2-DECL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "ts":              datetime.now(timezone.utc).isoformat(),
        "type":            "THIFUR_C2_DOCTRINE_DECLARATION",
        "doc_id":          C2_DOC_ID,
        "version":         C2_VERSION,
        "effective":       C2_EFFECTIVE,
        "agent":           C2_AGENT,
        "immutable_stops": C2_IMMUTABLE_STOPS,
        "task_registry":   C2_TASK_REGISTRY,
        "authority_chain": C2_AUTHORITY_CHAIN,
        "convergence_mandate": C2_CONVERGENCE_MANDATE,
        "dsor_stamped":    True,
    }


def get_c2_source_document_text() -> str:
    """
    Returns the canonicalized doctrine text for knowledge base registration.
    """
    stops_text = "\n".join(
        f"  Stop {s['stop']} — {s['name']}: {s['rule']}"
        for s in C2_IMMUTABLE_STOPS
    )
    chain_text = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(C2_AUTHORITY_CHAIN))
    tasks_text = "\n".join(f"  {t['task']}: {t['name']}" for t in C2_TASK_REGISTRY)

    return f"""PROJECT AUREON
THIFUR-C2 — Command and Control · Execution Coordination Doctrine
Doctrine: {C2_DOC_ID} · {C2_VERSION} · Effective {C2_EFFECTIVE}
Author: Guillermo "Bill" Ravelo · Columbia University MS Technology Management

I. WHAT THIFUR-C2 IS
Thifur-C2 is the Command and Control coordination layer of the Aureon execution
architecture. C2 does not originate. C2 does not execute. C2 does not interpret
doctrine. C2 sequences, coordinates, records handoffs, assembles unified lineage,
and presents a single human authority surface across all execution agents simultaneously.

C2 is the architectural answer to a problem no existing system has solved: when a
single financial lifecycle object simultaneously requires deterministic TradFi rail
execution (Thifur-R), programmable asset governance (Thifur-J), and adaptive
optimization (Thifur-H), who holds the unified picture across all three? C2 holds
that picture. Always. Without exception.

C2 also receives Neptune Spear's operator-approved recommendations as the first
downstream recipient after Kaladan structures the lifecycle. Neptune originates,
the operator approves, Kaladan packages, C2 coordinates execution. That is the
complete authority chain.

II. FIVE IMMUTABLE STOPS
These rules are not configurable. Not subject to override by any agent. May only
be modified by the operator through a formal doctrine addendum in Verana's Network Registry.
{stops_text}

III. C2 TASK REGISTRY
{tasks_text}

IV. CONVERGENCE GOVERNANCE
{C2_CONVERGENCE_MANDATE}

V. COMPLETE AUTHORITY CHAIN
{chain_text}

VI. WHY C2 MUST EXIST
{C2_RATIONALE}
"""
