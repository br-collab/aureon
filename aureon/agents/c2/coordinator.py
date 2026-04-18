"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/agents/c2/coordinator.py                                     ║
║  Thifur-C2 — Command and Control Master Agent                        ║
║                                                                      ║
║  MANDATE:                                                            ║
║    Sequence, coordinate, and govern handoff between Thifur-R, J, H. ║
║    Hold the unified lineage record.                                  ║
║    Present a single human authority surface across all agents.       ║
║    Route escalation with complete multi-agent context.               ║
║    Receive Neptune Spear outputs post-operator-approval via Kaladan. ║
║                                                                      ║
║  FIVE IMMUTABLE STOPS:                                               ║
║    1. No self-execution — C2 never takes a market action             ║
║    2. No doctrine interpretation — Mentat owns doctrine              ║
║    3. Handoff before action — no agent acts without C2 record        ║
║    4. One lineage record — DSOR never receives raw agent telemetry   ║
║    5. Escalation completeness — C2 never escalates partial context   ║
║                                                                      ║
║  TradFi-DeFi Convergence:                                            ║
║    C2 is the layer that makes tokenized assets, AI execution,        ║
║    and payment rails governable under a single doctrine-aligned      ║
║    lifecycle — without forcing either model to become the other.     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime, timezone
from typing import Any

from aureon.agents.base import Agent, Intent, Advisory, Tasking, Result

# ── C2 Operating Constants ────────────────────────────────────────────────────
C2_VERSION          = "1.0"
ESCALATION_TIMEOUT  = 30    # seconds C2 waits for agent context before flagging gap
MAX_HANDOFF_LOG     = 500   # ring buffer cap for handoff records
MAX_LINEAGE_LOG     = 200   # ring buffer cap for unified lineage records

# ── Handoff States ────────────────────────────────────────────────────────────
HS_ISSUED    = "ISSUED"       # C2 has tasked the agent
HS_ACTIVE    = "ACTIVE"       # agent has acknowledged and is executing
HS_COMPLETE  = "COMPLETE"     # agent returned telemetry, handoff closed
HS_ESCALATED = "ESCALATED"    # agent triggered escalation, C2 packaged and routed
HS_FAILED    = "FAILED"       # agent failed — fallback or suspend

# ── Agent Identifiers ─────────────────────────────────────────────────────────
AGENT_R       = "THIFUR_R"
AGENT_J       = "THIFUR_J"
AGENT_H       = "THIFUR_H"
AGENT_C2      = "THIFUR_C2"
AGENT_NEPTUNE = "THIFUR_NEPTUNE_SPEAR"   # origination tier — above execution triplet

# ── Authority Chain (Neptune → Operator → Kaladan → C2 → R/J/H) ──────────────
# Neptune Spear originates. Operator approves. Kaladan packages.
# C2 receives from Kaladan and is the first execution-tier downstream point.
# Doctrine ref: Thifur-Neptune Spear · Draft 1.0 — Neptune-to-C2 Handoff Protocol
AUTHORITY_CHAIN = [
    AGENT_NEPTUNE,   # origination — recommendation with full analytical lineage
    "OPERATOR",      # human authority — approval required, basis recorded
    "KALADAN",       # lifecycle structuring
    AGENT_C2,        # coordination, handoff governance, unified lineage
    AGENT_J,         # pre-trade governance / DeFi programmable assets
    AGENT_R,         # TradFi settlement execution (deterministic)
    AGENT_H,         # adaptive execution optimization
]

# ── Convergence Zone Scenario Types ──────────────────────────────────────────
CONV_TOKENIZED_TO_RAIL      = "TOKENIZED_TO_RAIL"
CONV_AI_CONCURRENT          = "AI_CONCURRENT_SETTLEMENT"
CONV_CONTRACT_CONFLICT      = "SMART_CONTRACT_DOCTRINE_CONFLICT"
CONV_RAIL_FAILURE           = "PAYMENT_RAIL_FAILURE_MID_LIFECYCLE"
CONV_CONCENTRATION_BREACH   = "CONCENTRATION_BREACH_MID_LIFECYCLE"
CONV_JURISDICTIONAL_CONFLICT = "JURISDICTIONAL_CONFLICT"


class ThifurC2(Agent):
    """
    Thifur-C2 Master Agent.

    One instance per Aureon deployment. Injected into server.py at startup.
    Thread-safe — all state mutations hold self._lock.

    Usage:
        c2 = ThifurC2(aureon_state=aureon_state, state_lock=_lock)

        # Phase 1: pre-trade lifecycle
        task_id = c2.issue_task(lifecycle_packet, agents=[AGENT_J])

        # After J completes and returns telemetry:
        c2.record_agent_telemetry(task_id, AGENT_J, telemetry)

        # When J approves and R is ready:
        c2.handoff(task_id, from_agent=AGENT_J, to_agent=AGENT_R, object_state=packet)

        # Get the unified lineage record for DSOR:
        lineage = c2.get_unified_lineage(task_id)
    """

    tier = 0
    thifur_class = "C2"
    role_id = "AUR-C2-COORD-001"

    def __init__(self, aureon_state: dict, state_lock: threading.Lock):
        super().__init__(aureon_state, state_lock)
        self._c2_lock = threading.Lock()   # C2's own internal lock

        # ── C2 internal registers ─────────────────────────────────
        # _tasks: task_id → task record (active lifecycle objects)
        # _handoff_log: ordered list of all handoff events
        # _lineage: task_id → assembled unified lineage record
        self._tasks       = {}
        self._handoff_log = []
        self._lineage     = {}

        print(f"[THIFUR-C2] Initialized — v{C2_VERSION} — "
              "Coordination, Handoff Governance, Unified Lineage, Escalation")

    # ─────────────────────────────────────────────────────────────────────────
    # MANDATE 1: SEQUENCING AUTHORITY
    # ─────────────────────────────────────────────────────────────────────────

    def issue_task(self,
                   lifecycle_packet: dict,
                   agents: list[str],
                   doctrine_version: str | None = None,
                   convergence_scenario: str | None = None) -> str:
        """
        Accept a governed lifecycle packet from Kaladan and issue tasking
        to specified Thifur agents in the defined activation sequence.

        Returns task_id — the unified identifier for this lifecycle object
        across all agent interactions.

        Immutable Stop 1: C2 never initiates a market action here.
        Immutable Stop 2: Doctrine version comes from the packet, not C2 logic.
        """
        ts      = datetime.now(timezone.utc).isoformat()
        task_id = self._make_task_id(lifecycle_packet)
        dv      = doctrine_version or self._state.get("doctrine_version", "unknown")

        task = {
            "task_id":             task_id,
            "created_ts":          ts,
            "doctrine_version":    dv,
            "lifecycle_packet":    lifecycle_packet,
            "agents_tasked":       list(agents),
            "agent_states":        {a: HS_ISSUED for a in agents},
            "handoff_sequence":    [],
            "telemetry":           {},
            "escalations":         [],
            "convergence_scenario": convergence_scenario,
            "unified_lineage_ready": False,
            "dsor_submitted":      False,
            "status":              "ACTIVE",
        }

        with self._c2_lock:
            self._tasks[task_id] = task

        # Log the issuance in the Aureon authority log
        self._authority_log_entry(
            task_id    = task_id,
            event_type = "C2_TASK_ISSUED",
            detail     = (f"Task {task_id} issued to agents: {', '.join(agents)} | "
                          f"Doctrine v{dv} | "
                          f"Convergence: {convergence_scenario or 'none'}"),
        )

        # Write C2 task entry into aureon_state for dashboard visibility
        with self._lock:
            c2_log = self._state.setdefault("c2_task_log", [])
            c2_log.insert(0, {
                "task_id":          task_id,
                "ts":               ts,
                "agents":           agents,
                "decision_id":      lifecycle_packet.get("id"),
                "symbol":           lifecycle_packet.get("symbol"),
                "action":           lifecycle_packet.get("action"),
                "notional":         lifecycle_packet.get("notional"),
                "status":           "ACTIVE",
                "convergence":      convergence_scenario,
                "doctrine_version": dv,
            })
            if len(c2_log) > 200:
                self._state["c2_task_log"] = c2_log[:200]

        print(f"[THIFUR-C2] Task {task_id} issued — agents: {agents} — "
              f"symbol: {lifecycle_packet.get('symbol')} — "
              f"convergence: {convergence_scenario or 'none'}")

        return task_id

    # ─────────────────────────────────────────────────────────────────────────
    # MANDATE 2: HANDOFF GOVERNANCE
    # ─────────────────────────────────────────────────────────────────────────

    def handoff(self,
                task_id: str,
                from_agent: str,
                to_agent: str,
                object_state: dict,
                handoff_reason: str = "") -> dict:
        """
        Govern the transfer of a lifecycle object between Thifur agents.

        Records: originating agent, receiving agent, object state at transfer,
        timestamp, and doctrine version active at transfer time.

        Immutable Stop 3: No agent acts on a lifecycle object without this record.
        The receiving agent must wait for the returned handoff_record before acting.

        Returns the handoff_record dict — the receiving agent presents this
        as proof of authorized transfer before executing any action.
        """
        ts = datetime.now(timezone.utc).isoformat()

        with self._c2_lock:
            task = self._tasks.get(task_id)
            if not task:
                raise ValueError(
                    f"[THIFUR-C2] HANDOFF BLOCKED — task {task_id} not found in C2 registry. "
                    "No agent may act without a valid C2 task record."
                )

            dv = task["doctrine_version"]

            handoff_record = {
                "handoff_id":       self._make_handoff_id(task_id, from_agent, to_agent),
                "task_id":          task_id,
                "ts":               ts,
                "from_agent":       from_agent,
                "to_agent":         to_agent,
                "object_state":     dict(object_state),
                "doctrine_version": dv,
                "handoff_reason":   handoff_reason,
                "status":           HS_ISSUED,
                "c2_authorized":    True,
            }

            # Mark from_agent complete, to_agent issued
            task["agent_states"][from_agent] = HS_COMPLETE
            task["agent_states"][to_agent]   = HS_ISSUED
            task["handoff_sequence"].append(handoff_record)

            # Push to handoff log (ring buffer)
            self._handoff_log.insert(0, handoff_record)
            if len(self._handoff_log) > MAX_HANDOFF_LOG:
                self._handoff_log = self._handoff_log[:MAX_HANDOFF_LOG]

        # Write to aureon_state for dashboard and DSOR visibility
        with self._lock:
            hlog = self._state.setdefault("c2_handoff_log", [])
            hlog.insert(0, {
                "handoff_id":   handoff_record["handoff_id"],
                "task_id":      task_id,
                "ts":           ts,
                "from_agent":   from_agent,
                "to_agent":     to_agent,
                "doctrine_version": dv,
                "handoff_reason": handoff_reason,
                "symbol":       object_state.get("symbol"),
                "action":       object_state.get("action"),
                "notional":     object_state.get("notional"),
            })
            if len(hlog) > MAX_HANDOFF_LOG:
                self._state["c2_handoff_log"] = hlog[:MAX_HANDOFF_LOG]

        self._authority_log_entry(
            task_id    = task_id,
            event_type = "C2_HANDOFF",
            detail     = (f"{from_agent} → {to_agent} | "
                          f"Handoff ID: {handoff_record['handoff_id']} | "
                          f"Reason: {handoff_reason or 'sequence'}"),
        )

        print(f"[THIFUR-C2] Handoff authorized: {from_agent} → {to_agent} | "
              f"Task {task_id} | {handoff_record['handoff_id']}")

        return handoff_record

    def confirm_handoff_received(self, handoff_record: dict) -> bool:
        """
        Receiving agent calls this to confirm handoff receipt before acting.
        Updates agent state from ISSUED to ACTIVE.
        Returns True if handoff is valid and C2-authorized.

        This is the enforcement point for Immutable Stop 3.
        """
        if not handoff_record.get("c2_authorized"):
            print(f"[THIFUR-C2] HANDOFF REJECTED — not C2-authorized: {handoff_record}")
            return False

        task_id  = handoff_record["task_id"]
        to_agent = handoff_record["to_agent"]

        with self._c2_lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            task["agent_states"][to_agent] = HS_ACTIVE

            # Mark the handoff record as active in the sequence
            for hr in task["handoff_sequence"]:
                if hr["handoff_id"] == handoff_record["handoff_id"]:
                    hr["status"] = HS_ACTIVE
                    break

        return True

    # ─────────────────────────────────────────────────────────────────────────
    # MANDATE 3: UNIFIED LINEAGE
    # ─────────────────────────────────────────────────────────────────────────

    def record_agent_telemetry(self,
                               task_id: str,
                               agent_id: str,
                               telemetry: dict) -> None:
        """
        Receive telemetry from a completing agent and incorporate it into
        the unified lineage record for this task.

        Immutable Stop 4: Agent telemetry feeds C2. C2 feeds DSOR.
        Raw agent telemetry never reaches DSOR directly.
        """
        ts = datetime.now(timezone.utc).isoformat()

        with self._c2_lock:
            task = self._tasks.get(task_id)
            if not task:
                print(f"[THIFUR-C2] Telemetry from {agent_id} for unknown task {task_id} — discarded")
                return

            task["telemetry"][agent_id] = {
                "received_ts": ts,
                "agent_id":    agent_id,
                "data":        dict(telemetry),
            }
            task["agent_states"][agent_id] = HS_COMPLETE

        print(f"[THIFUR-C2] Telemetry received from {agent_id} for task {task_id}")

        # Attempt lineage assembly after each telemetry receipt
        self._attempt_lineage_assembly(task_id)

    def _attempt_lineage_assembly(self, task_id: str) -> bool:
        """
        Attempt to assemble the unified lineage record.
        Succeeds when all tasked agents have returned telemetry.

        Returns True if assembly is complete and DSOR-ready.
        """
        with self._c2_lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task["unified_lineage_ready"]:
                return True

            agents_tasked    = task["agents_tasked"]
            agents_complete  = [a for a in agents_tasked
                                 if task["agent_states"].get(a) == HS_COMPLETE]
            all_complete     = len(agents_complete) == len(agents_tasked)

            if not all_complete:
                return False

            # All agents complete — assemble the unified record
            ts = datetime.now(timezone.utc).isoformat()
            lineage = {
                "task_id":             task_id,
                "assembled_ts":        ts,
                "doctrine_version":    task["doctrine_version"],
                "lifecycle_packet":    task["lifecycle_packet"],
                "agents_tasked":       agents_tasked,
                "handoff_sequence":    list(task["handoff_sequence"]),
                "agent_telemetry":     dict(task["telemetry"]),
                "escalations":         list(task["escalations"]),
                "convergence_scenario": task["convergence_scenario"],
                "lineage_hash":        self._make_lineage_hash(task),
                "dsor_ready":          True,
                "c2_version":          C2_VERSION,
            }

            task["unified_lineage_ready"] = True
            self._lineage[task_id] = lineage

        # Push to aureon_state for DSOR pickup
        with self._lock:
            lineage_log = self._state.setdefault("c2_lineage_log", [])
            lineage_log.insert(0, {
                "task_id":          lineage["task_id"],
                "assembled_ts":     lineage["assembled_ts"],
                "doctrine_version": lineage["doctrine_version"],
                "symbol":           lineage["lifecycle_packet"].get("symbol"),
                "action":           lineage["lifecycle_packet"].get("action"),
                "notional":         lineage["lifecycle_packet"].get("notional"),
                "agents":           agents_tasked,
                "lineage_hash":     lineage["lineage_hash"],
                "dsor_ready":       True,
            })
            if len(lineage_log) > MAX_LINEAGE_LOG:
                self._state["c2_lineage_log"] = lineage_log[:MAX_LINEAGE_LOG]

        self._authority_log_entry(
            task_id    = task_id,
            event_type = "C2_LINEAGE_ASSEMBLED",
            detail     = (f"Unified lineage complete for task {task_id} | "
                          f"Agents: {agents_tasked} | "
                          f"Hash: {lineage['lineage_hash']}"),
        )

        print(f"[THIFUR-C2] Unified lineage assembled for task {task_id} | "
              f"Hash: {lineage['lineage_hash']} | DSOR-ready")

        return True

    def get_unified_lineage(self, task_id: str) -> dict | None:
        """
        Retrieve the assembled unified lineage record for DSOR submission.
        Returns None if lineage is not yet complete.
        """
        with self._c2_lock:
            return dict(self._lineage[task_id]) if task_id in self._lineage else None

    # ─────────────────────────────────────────────────────────────────────────
    # MANDATE 4: SINGLE ESCALATION SURFACE
    # ─────────────────────────────────────────────────────────────────────────

    def escalate(self,
                 task_id: str,
                 escalating_agent: str,
                 reason: str,
                 severity: str = "WARN",
                 context: dict | None = None,
                 wait_for_agents: list[str] | None = None) -> dict:
        """
        Route an escalation from any Thifur agent to the single human
        authority surface.

        Immutable Stop 5: C2 waits for context from all active agents
        (within ESCALATION_TIMEOUT) before packaging the escalation.
        Gaps are flagged explicitly — never silently dropped.

        severity: "WARN" | "HALT" | "SUSPEND"
          - WARN    → surfaces to dashboard, human review required
          - HALT    → triggers aureon_state["halt_active"] = True
          - SUSPEND → suspends the specific agent domain only
        """
        ts = datetime.now(timezone.utc).isoformat()

        # Collect context from all active agents within timeout
        additional_context = {}
        if wait_for_agents:
            deadline = time.time() + ESCALATION_TIMEOUT
            for agent in wait_for_agents:
                waited = False
                while time.time() < deadline:
                    with self._c2_lock:
                        task = self._tasks.get(task_id, {})
                        if agent in task.get("telemetry", {}):
                            additional_context[agent] = task["telemetry"][agent]
                            waited = True
                            break
                    time.sleep(0.5)
                if not waited:
                    additional_context[agent] = {
                        "GAP_FLAG": True,
                        "reason":   f"Agent {agent} context not received within {ESCALATION_TIMEOUT}s",
                        "ts":       ts,
                    }
                    print(f"[THIFUR-C2] ESCALATION GAP: {agent} context not received "
                          f"within {ESCALATION_TIMEOUT}s — flagged explicitly")

        escalation = {
            "escalation_id":   f"ESC-{task_id[-6:]}-{escalating_agent[-1]}",
            "task_id":         task_id,
            "ts":              ts,
            "escalating_agent": escalating_agent,
            "reason":          reason,
            "severity":        severity,
            "context":         context or {},
            "additional_agent_context": additional_context,
            "gaps_flagged":    [a for a, v in additional_context.items()
                                if v.get("GAP_FLAG")],
            "human_authority_required": True,
            "resolved":        False,
        }

        with self._c2_lock:
            task = self._tasks.get(task_id)
            if task:
                task["escalations"].append(escalation)
                task["agent_states"][escalating_agent] = HS_ESCALATED

        # Write to aureon_state compliance alerts and authority log
        with self._lock:
            # Compliance alert
            alerts = self._state.setdefault("compliance_alerts", [])
            alert_entry = {
                "id":       escalation["escalation_id"],
                "severity": severity,
                "title":    f"C2 Escalation: {escalating_agent} — {reason[:60]}",
                "detail":   (f"Task {task_id} | Agent: {escalating_agent} | "
                             f"Severity: {severity} | "
                             f"Gaps: {escalation['gaps_flagged'] or 'none'}"),
                "ts":       ts,
                "resolved": False,
                "source":   "THIFUR_C2",
            }
            alerts.insert(0, alert_entry)
            self._state.setdefault("alert_history", []).insert(0, alert_entry)

            # If HALT severity — activate system halt
            if severity == "HALT":
                self._state["halt_active"]    = True
                self._state["halt_ts"]        = ts
                self._state["halt_authority"] = "THIFUR_C2"
                self._state["halt_reason"]    = reason
                print(f"[THIFUR-C2] ⚠ HALT ACTIVATED — {reason}")

        self._authority_log_entry(
            task_id    = task_id,
            event_type = f"C2_ESCALATION_{severity}",
            detail     = (f"Agent: {escalating_agent} | Reason: {reason} | "
                          f"Gaps: {escalation['gaps_flagged'] or 'none'} | "
                          f"Human authority required"),
        )

        print(f"[THIFUR-C2] Escalation routed: {escalating_agent} | "
              f"Severity: {severity} | Task: {task_id}")

        return escalation

    # ─────────────────────────────────────────────────────────────────────────
    # CONVERGENCE GOVERNANCE TABLE
    # ─────────────────────────────────────────────────────────────────────────

    def evaluate_convergence_scenario(self, lifecycle_packet: dict) -> str | None:
        """
        Inspect the lifecycle packet and identify if it triggers a
        TradFi-DeFi convergence scenario requiring special C2 sequencing.

        Returns the convergence scenario type or None for standard flow.

        This implements the Convergence Governance Table from the
        Aureon Agent Specification.
        """
        asset_class    = lifecycle_packet.get("asset_class", "")
        product_type   = lifecycle_packet.get("product_type", "")
        is_tokenized   = lifecycle_packet.get("is_tokenized", False)
        has_smart_contract = lifecycle_packet.get("has_smart_contract", False)
        cross_border   = lifecycle_packet.get("cross_border", False)
        symbol         = lifecycle_packet.get("symbol", "")

        # Crypto assets have DeFi-like settlement characteristics
        # even when traded through traditional channels
        is_defi_adjacent = asset_class == "crypto" or is_tokenized

        if is_tokenized and asset_class in ("equities", "fixed_income", "commodities"):
            return CONV_TOKENIZED_TO_RAIL

        if is_defi_adjacent and lifecycle_packet.get("collateral_optimization"):
            return CONV_AI_CONCURRENT

        if has_smart_contract:
            return CONV_CONTRACT_CONFLICT

        if cross_border and is_defi_adjacent:
            return CONV_JURISDICTIONAL_CONFLICT

        return None

    def get_convergence_sequencing(self, scenario: str) -> dict:
        """
        Return the C2 sequencing rules for a given convergence scenario
        per the Convergence Governance Table.
        """
        TABLE = {
            CONV_TOKENIZED_TO_RAIL: {
                "primary_agent":    AGENT_J,
                "supporting_agents": [AGENT_R],
                "sequence":         [AGENT_J, AGENT_R],
                "rule": ("J prepares settlement instruction package. "
                         "C2 records handoff. R executes deterministically. "
                         "No direct J-to-R transfer."),
                "parallel":         False,
            },
            CONV_AI_CONCURRENT: {
                "primary_agent":    AGENT_J,
                "supporting_agents": [AGENT_H, AGENT_R],
                "sequence":         [AGENT_H, AGENT_J, AGENT_R],
                "rule": ("C2 sequences H advisory output first. "
                         "J validates against doctrine. R executes. "
                         "H never generates a settlement instruction."),
                "parallel":         False,
            },
            CONV_CONTRACT_CONFLICT: {
                "primary_agent":    AGENT_J,
                "supporting_agents": [],
                "sequence":         [AGENT_J],
                "rule": ("J suspends immediately. C2 packages conflict context "
                         "from all active agents. Minimum Tier 2 human authority "
                         "required to proceed."),
                "parallel":         False,
                "requires_escalation": True,
                "min_tier":         2,
            },
            CONV_RAIL_FAILURE: {
                "primary_agent":    AGENT_R,
                "supporting_agents": [AGENT_J],
                "sequence":         [AGENT_R],
                "rule": ("C2 freezes J lifecycle object. R executes Verana fallback "
                         "sequence. J resumes only after C2 confirms fallback rail "
                         "is governed and SLA-compliant."),
                "parallel":         False,
                "requires_escalation": True,
            },
            CONV_CONCENTRATION_BREACH: {
                "primary_agent":    AGENT_C2,
                "supporting_agents": [AGENT_R, AGENT_J, AGENT_H],
                "sequence":         [],
                "rule": ("C2 halts all agents on affected lifecycle. "
                         "Unified escalation to Tier 1 minimum. "
                         "No agent resumes without human authority clearance."),
                "parallel":         False,
                "requires_escalation": True,
                "min_tier":         1,
                "severity":         "HALT",
            },
            CONV_JURISDICTIONAL_CONFLICT: {
                "primary_agent":    AGENT_J,
                "supporting_agents": [],
                "sequence":         [AGENT_J],
                "rule": ("J suspends. C2 packages jurisdictional conflict for Mentat. "
                         "Kaladan holds lifecycle. Minimum Tier 2 human authority "
                         "before J resumes."),
                "parallel":         False,
                "requires_escalation": True,
                "min_tier":         2,
            },
        }
        return TABLE.get(scenario, {
            "primary_agent":    AGENT_J,
            "supporting_agents": [AGENT_R],
            "sequence":         [AGENT_J, AGENT_R],
            "rule":             "Standard pre-trade governance flow.",
            "parallel":         False,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 1 ENTRY POINT — Used by server.py
    # ─────────────────────────────────────────────────────────────────────────

    def process_pretrade_lifecycle(self,
                                   decision: dict,
                                   agent_j,   # ThifurJ instance
                                   agent_r,   # SettlementOps instance
                                   doctrine_version: str | None = None) -> dict:
        """
        Phase 1 governed lifecycle entry point.

        Takes an approved decision from Kaladan, routes it through C2
        coordination, Thifur-J pre-trade structuring, and Thifur-R
        settlement preparation.

        Returns the unified lifecycle result dict — DSOR-ready.

        This is the function server.py calls after a human approves a decision.
        """
        # ── Step 1: Evaluate convergence scenario ────────────────────
        scenario = self.evaluate_convergence_scenario(decision)
        sequencing = self.get_convergence_sequencing(scenario) if scenario else {
            "sequence": [AGENT_J, AGENT_R],
            "rule":     "Standard pre-trade governance flow.",
        }

        # ── Step 2: Issue C2 task ─────────────────────────────────────
        agents  = sequencing["sequence"]
        task_id = self.issue_task(
            lifecycle_packet    = decision,
            agents              = agents,
            doctrine_version    = doctrine_version,
            convergence_scenario = scenario,
        )

        result = {
            "task_id":             task_id,
            "convergence_scenario": scenario,
            "sequencing_rule":     sequencing.get("rule"),
            "agents_activated":    agents,
            "j_result":            None,
            "r_result":            None,
            "unified_lineage":     None,
            "status":              "IN_PROGRESS",
        }

        # ── Step 3: Thifur-J pre-trade structuring ────────────────────
        if AGENT_J in agents:
            j_result = agent_j.structure_pretrade_record(decision, task_id, self)
            result["j_result"] = j_result

            if j_result.get("status") == "BLOCKED":
                # J blocked the lifecycle — escalate
                self.escalate(
                    task_id         = task_id,
                    escalating_agent = AGENT_J,
                    reason          = j_result.get("block_reason", "J blocked lifecycle"),
                    severity        = "WARN",
                    context         = j_result,
                )
                result["status"] = "BLOCKED_BY_J"
                return result

            # Record J telemetry
            self.record_agent_telemetry(task_id, AGENT_J, j_result)

        # ── Step 4: Handoff J → R ─────────────────────────────────────
        if AGENT_J in agents and AGENT_R in agents:
            handoff_record = self.handoff(
                task_id       = task_id,
                from_agent    = AGENT_J,
                to_agent      = AGENT_R,
                object_state  = decision,
                handoff_reason = "Pre-trade structure complete — releasing to settlement preparation",
            )
            confirmed = agent_r.confirm_handoff(handoff_record)
            if not confirmed:
                self.escalate(
                    task_id         = task_id,
                    escalating_agent = AGENT_R,
                    reason          = "R handoff confirmation failed",
                    severity        = "HALT",
                    context         = {"handoff_record": handoff_record},
                )
                result["status"] = "HANDOFF_FAILURE"
                return result

        # ── Step 5: Thifur-R settlement preparation ───────────────────
        if AGENT_R in agents:
            r_result = agent_r.prepare_settlement_package(decision, task_id, self)
            result["r_result"] = r_result

            # Record R telemetry
            self.record_agent_telemetry(task_id, AGENT_R, r_result)

        # ── Step 6: Assemble unified lineage ──────────────────────────
        lineage = self.get_unified_lineage(task_id)
        result["unified_lineage"] = lineage
        result["status"]          = "COMPLETE"

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # DASHBOARD VISIBILITY
    # ─────────────────────────────────────────────────────────────────────────

    def get_c2_status(self) -> dict:
        """
        Return C2 operational status for dashboard display.
        Called by /api/c2/status endpoint.
        """
        with self._c2_lock:
            active_tasks = [
                t for t in self._tasks.values()
                if t["status"] == "ACTIVE"
            ]
            total_tasks     = len(self._tasks)
            total_handoffs  = len(self._handoff_log)
            total_lineages  = len(self._lineage)
            total_escalations = sum(
                len(t["escalations"]) for t in self._tasks.values()
            )

        with self._lock:
            halt_active = self._state.get("halt_active", False)

        return {
            "c2_version":        C2_VERSION,
            "status":            "HALTED" if halt_active else "OPERATIONAL",
            "active_tasks":      len(active_tasks),
            "total_tasks":       total_tasks,
            "total_handoffs":    total_handoffs,
            "total_lineages":    total_lineages,
            "total_escalations": total_escalations,
            "agents": {
                AGENT_R: "ACTIVE",
                AGENT_J: "ACTIVE",
                AGENT_H: "DECLARED",   # not activated in Phase 1
            },
            "convergence_governance": "ACTIVE",
            "trad_fi_defi_boundary":  "GOVERNED",
        }

    def advise(self, intent: Intent) -> Advisory:
        """C2 does not advise — it coordinates."""
        return Advisory(
            timestamp=datetime.now(timezone.utc),
            agent_role_id=self.role_id,
            summary="C2 coordinates agent lifecycle — not an advisory agent",
            recommendation={},
            requires_approval=False,
        )

    def execute(self, tasking: Tasking) -> Result:
        """C2 does not execute — it coordinates."""
        return Result(
            timestamp=datetime.now(timezone.utc),
            agent_role_id=self.role_id,
            outcome="DELEGATED",
            dsor_record_id=tasking.c2_tasking_id,
        )

    def get_status(self) -> dict:
        """AureonAgent ABC — delegates to get_c2_status()."""
        return self.get_c2_status()

    def get_handoff_log(self, limit: int = 50) -> list:
        """Return recent handoff records for dashboard display."""
        with self._c2_lock:
            return list(self._handoff_log[:limit])

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _make_task_id(self, packet: dict) -> str:
        seed = f"C2-{packet.get('id', 'NOID')}-{datetime.now(timezone.utc).isoformat()}"
        return "TSK-" + hashlib.sha256(seed.encode()).hexdigest()[:12].upper()

    def _make_handoff_id(self, task_id: str, from_agent: str, to_agent: str) -> str:
        seed = f"HO-{task_id}-{from_agent}-{to_agent}-{datetime.now(timezone.utc).isoformat()}"
        return "HO-" + hashlib.sha256(seed.encode()).hexdigest()[:10].upper()

    def _make_lineage_hash(self, task: dict) -> str:
        seed = (
            f"{task['task_id']}"
            f"{task['doctrine_version']}"
            f"{sorted(task['agents_tasked'])}"
            f"{len(task['handoff_sequence'])}"
            f"{sorted(task['telemetry'].keys())}"
        )
        return hashlib.sha256(seed.encode()).hexdigest()[:20].upper()

    def _authority_log_entry(self, task_id: str, event_type: str, detail: str) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        entry = {
            "id":        f"HAD-C2-{task_id[-6:]}",
            "ts":        ts,
            "tier":      "Thifur-C2",
            "type":      event_type,
            "authority": "THIFUR_C2",
            "outcome":   detail,
            "hash":      hashlib.sha256(
                             f"{event_type}{task_id}{ts}".encode()
                         ).hexdigest()[:16].upper(),
        }
        with self._lock:
            self._state.setdefault("authority_log", []).insert(0, entry)
