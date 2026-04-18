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
║    Receive Atrox outputs post-operator-approval via Kaladan. ║
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
from aureon.agents.ranger import RANGER_AGENTS
from aureon.agents.jtac import JTAC_AGENTS
from aureon.agents.payloads import (
    ExecutionConfirmation, DSORIntent, BreachEvent, ReportingContext,
    CounterpartyScreeningRequest, PreTradePolicyCheckRequest,
)

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
AGENT_ATROX = "THIFUR_ATROX"   # origination tier — above execution triplet

# ── Authority Chain (Atrox → Operator → Kaladan → C2 → R/J/H) ──────────────
# Atrox originates. Operator approves. Kaladan packages.
# C2 receives from Kaladan and is the first execution-tier downstream point.
# Doctrine ref: Thifur-Atrox · Draft 1.0 — Atrox-to-C2 Handoff Protocol
AUTHORITY_CHAIN = [
    AGENT_ATROX,   # origination — recommendation with full analytical lineage
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
                                   doctrine_version: str | None = None) -> dict:
        """
        Phase 1 governed lifecycle entry point.

        Takes an approved decision from Kaladan, routes it through:
          Step 2.5 (Phase 4, NEW): Compliance counterparty OFAC screening
                                    (AUR-J-COMP-001, runs BEFORE ThifurJ)
          Step 3: Thifur-J pre-trade structuring
          Steps 4–10: Existing Phase 3 Ranger lifecycle.

        Compliance may halt-and-pend the lifecycle:
          - APPROVAL_REQUIRED        — single-authority operator approval
          - CONFLICT_RESOLUTION_REQUIRED — dual-authority (Compliance + Legal)

        On halt, the lifecycle is persisted to
        aureon_state["paused_lifecycles"][task_id] and downstream agents
        are NOT invoked. Resume via resume_paused_lifecycle().

        Returns the unified lifecycle result dict — DSOR-ready on COMPLETE,
        or a PAUSED dict when a halt fires.
        """
        # ── Resolve Compliance via JTAC_AGENTS registry ──────────────
        if "AUR-J-COMP-001" not in JTAC_AGENTS:
            raise RuntimeError(
                "[THIFUR-C2] Registry missing AUR-J-COMP-001 (Compliance). "
                "Cannot proceed with pre-trade lifecycle."
            )
        agent_compliance = JTAC_AGENTS["AUR-J-COMP-001"](self._state, self._lock)

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

        # ── Step 2.5 (Phase 4 NEW): Compliance counterparty screening ─
        screening_request = CounterpartyScreeningRequest(
            task_id=task_id,
            counterparty_name=decision.get("counterparty_name", "") or "",
            counterparty_jurisdiction=decision.get("counterparty_jurisdiction", "") or "",
            counterparty_lei=decision.get("counterparty_lei"),
        )
        path_selection = agent_compliance.screen_ofac(screening_request)
        self.record_agent_telemetry(
            task_id,
            "AUR-J-COMP-001",
            {
                "selected_path_id": path_selection.selected_path_id,
                "requires_approval": path_selection.requires_approval,
                "requires_authority_resolution": path_selection.requires_authority_resolution,
                "conflict_id": path_selection.conflict_id,
            },
        )

        if path_selection.requires_authority_resolution:
            # Dual-authority conflict halt — Compliance + Legal required
            conflict = agent_compliance.escalate_for_conflict_resolution(path_selection)
            lineage = agent_compliance.determine_approval_lineage(
                pause_reason="CONFLICT_RESOLUTION_REQUIRED", task_id=task_id,
            )
            self._persist_paused_lifecycle(
                task_id=task_id,
                pause_reason="CONFLICT_RESOLUTION_REQUIRED",
                decision=decision,
                path_selection=path_selection,
                doctrine_version=path_selection.doctrine_version,
                gate_context=None,
                conflict=conflict,
                convergence_scenario=scenario,
                sequencing_rule=sequencing.get("rule"),
                agents_activated=agents,
                approval_lineage=lineage,
            )
            return self._lifecycle_paused_response(
                task_id=task_id,
                pause_reason="CONFLICT_RESOLUTION_REQUIRED",
                path_selection=path_selection,
                gate_context=None,
                conflict=conflict,
                convergence_scenario=scenario,
                sequencing_rule=sequencing.get("rule"),
                agents_activated=agents,
                approval_lineage=lineage,
            )

        if path_selection.requires_approval:
            # Single-authority approval halt
            intent_summary = {
                "decision_id":               decision.get("id"),
                "symbol":                    decision.get("symbol"),
                "action":                    decision.get("action"),
                "notional":                  decision.get("notional"),
                "counterparty_name":         decision.get("counterparty_name"),
                "counterparty_jurisdiction": decision.get("counterparty_jurisdiction"),
            }
            risk_summary = {
                "path_id":   path_selection.selected_path_id,
                "rationale": path_selection.selection_rationale,
            }
            gate_context = agent_compliance.escalate_for_approval(
                path_selection=path_selection,
                intent_summary=intent_summary,
                risk_summary=risk_summary,
            )
            lineage = agent_compliance.determine_approval_lineage(
                pause_reason="APPROVAL_REQUIRED", task_id=task_id,
            )
            self._persist_paused_lifecycle(
                task_id=task_id,
                pause_reason="APPROVAL_REQUIRED",
                decision=decision,
                path_selection=path_selection,
                doctrine_version=path_selection.doctrine_version,
                gate_context=gate_context,
                conflict=None,
                convergence_scenario=scenario,
                sequencing_rule=sequencing.get("rule"),
                agents_activated=agents,
                approval_lineage=lineage,
            )
            return self._lifecycle_paused_response(
                task_id=task_id,
                pause_reason="APPROVAL_REQUIRED",
                path_selection=path_selection,
                gate_context=gate_context,
                conflict=None,
                convergence_scenario=scenario,
                sequencing_rule=sequencing.get("rule"),
                agents_activated=agents,
                approval_lineage=lineage,
            )

        # ── Compliance cleared — continue to post-Compliance tail ────
        return self._execute_post_compliance_lifecycle(
            decision=decision,
            task_id=task_id,
            agent_j=agent_j,
            agents_activated=agents,
            sequencing_rule=sequencing.get("rule"),
            doctrine_version=doctrine_version,
            convergence_scenario=scenario,
            compliance_clearance={
                "path_id": path_selection.selected_path_id,
                "rationale": path_selection.selection_rationale,
            },
        )

    # ─────────────────────────────────────────────────────────────────────────
    # POST-COMPLIANCE LIFECYCLE TAIL — Steps 3–10
    # ─────────────────────────────────────────────────────────────────────────
    # Extracted from process_pretrade_lifecycle so resume_paused_lifecycle can
    # re-enter at the same point after an approval. Behavior identical to the
    # previous monolithic method; only call-site restructuring.

    def _execute_post_compliance_lifecycle(self,
                                           decision: dict,
                                           task_id: str,
                                           agent_j,
                                           agents_activated: list,
                                           sequencing_rule: str | None,
                                           doctrine_version: str | None,
                                           convergence_scenario: str | None = None,
                                           compliance_clearance: dict | None = None,
                                           resume_attribution: dict | None = None,
                                           skip_policy_check: bool = False,
                                           ) -> dict:
        """Execute Phase 3 lifecycle (ThifurJ → TradeSupport → Reconciliation
        → SettlementOps → RegReporting → unified lineage) given a task_id
        that has already cleared Compliance OFAC screening.

        Phase 4.5 adds the pre-trade policy gate BEFORE ThifurJ. On HOLD,
        the lifecycle halts-and-pends with pause_reason=POLICY_HOLD; on
        BLOCK, the lifecycle terminally halts with no resume. On PASS,
        control continues to ThifurJ as before.

        skip_policy_check: set True on resume from a POLICY_HOLD pause —
        the policy check already ran and was operator-overridden; do not
        re-run it. Fresh entry (after OFAC clear) and OFAC-pause resumes
        leave this False so the gate runs.

        doctrine_version is honored for downstream agents — on resume, pass
        the doctrine_version that was active at pause so the entire lifecycle
        runs under one version regardless of whether doctrine changed during
        the pause.
        """
        # ── Resolve Ranger roles from registry ────────────────────────
        for required_role in ("AUR-R-SETTLEMENT-001", "AUR-R-TRADESUPPORT-001",
                              "AUR-R-RECON-001", "AUR-R-REGREP-001"):
            if required_role not in RANGER_AGENTS:
                raise RuntimeError(
                    f"[THIFUR-C2] Registry missing {required_role}. "
                    "Cannot proceed with pre-trade lifecycle."
                )
        agent_settlement = RANGER_AGENTS["AUR-R-SETTLEMENT-001"](self._state, self._lock)
        agent_ts = RANGER_AGENTS["AUR-R-TRADESUPPORT-001"](self._state, self._lock)
        agent_recon = RANGER_AGENTS["AUR-R-RECON-001"](self._state, self._lock)
        agent_regrep = RANGER_AGENTS["AUR-R-REGREP-001"](self._state, self._lock)

        agents = agents_activated

        result = {
            "task_id":             task_id,
            "convergence_scenario": convergence_scenario,
            "sequencing_rule":     sequencing_rule,
            "agents_activated":    agents,
            "j_result":            None,
            "r_result":            None,
            "unified_lineage":     None,
            "status":              "IN_PROGRESS",
            "compliance_clearance": compliance_clearance,
        }
        if resume_attribution is not None:
            result["resume_attribution"] = resume_attribution

        # ── Step 2.7 (Phase 4.5 NEW): Pre-trade policy gate ───────────
        # Runs AFTER OFAC clearance and BEFORE ThifurJ. Skipped when
        # resuming from a prior POLICY_HOLD pause (operator already
        # overrode the HOLD). On BLOCK: terminal halt. On HOLD:
        # halt-and-pend single-authority.
        if not skip_policy_check:
            agent_compliance = JTAC_AGENTS["AUR-J-COMP-001"](self._state, self._lock)
            policy_request = PreTradePolicyCheckRequest(
                task_id=task_id,
                decision_id=decision.get("id") or f"UNKNOWN-{task_id}",
                intent_summary={
                    "asset_class":       decision.get("asset_class"),
                    "side":              decision.get("action"),
                    "notional":          decision.get("notional"),
                    "instrument":        decision.get("symbol"),
                    "counterparty":      decision.get("counterparty_name"),
                    "counterparty_type": decision.get("counterparty_type"),
                    "jurisdiction":      decision.get("counterparty_jurisdiction") or decision.get("jurisdiction"),
                    "currency":          decision.get("currency"),
                    "duration_years":    decision.get("duration_years"),
                    "credit_rating":     decision.get("credit_rating"),
                    "sector":            decision.get("sector"),
                    "issuer_concentration_pct": decision.get("issuer_concentration_pct"),
                },
                mandate_version=self._state.get("active_mandate_version", "ARCADIA-MANDATE-v1.0"),
                ips_version=self._state.get("active_ips_version", "ENDOWMENT-SERIES-I-IPS-v1.0"),
            )
            policy_result = agent_compliance.check_pretrade_policy(policy_request)
            self.record_agent_telemetry(
                task_id,
                "AUR-J-COMP-001",
                {"event_type": "PRETRADE_POLICY", "status": policy_result.status,
                 "selected_path_id": policy_result.selected_path_id,
                 "failures_count": len(policy_result.failures)},
            )
            result["policy_result"] = policy_result.to_dict()

            if policy_result.status == "BLOCK":
                # Terminal halt — no pend, no resume
                return self._lifecycle_blocked_response(
                    task_id=task_id,
                    block_reason="PRETRADE_POLICY_BLOCK",
                    failures=policy_result.failures,
                    policy_result=policy_result,
                    convergence_scenario=convergence_scenario,
                    sequencing_rule=sequencing_rule,
                    agents_activated=agents,
                    compliance_clearance=compliance_clearance,
                )

            if policy_result.status == "HOLD":
                path_selection = agent_compliance.get_pending_policy_selection(task_id)
                intent_summary = dict(policy_request.intent_summary)
                risk_summary = {
                    "path_id":  policy_result.selected_path_id,
                    "failures": list(policy_result.failures),
                    "rationale": "Pre-trade policy threshold approach or IPS ineligibility",
                }
                gate_context = agent_compliance.escalate_for_approval(
                    path_selection=path_selection,
                    intent_summary=intent_summary,
                    risk_summary=risk_summary,
                )
                lineage = agent_compliance.determine_approval_lineage(
                    pause_reason="POLICY_HOLD", task_id=task_id,
                )
                self._persist_paused_lifecycle(
                    task_id=task_id,
                    pause_reason="POLICY_HOLD",
                    decision=decision,
                    path_selection=path_selection,
                    doctrine_version=doctrine_version,
                    gate_context=gate_context,
                    conflict=None,
                    convergence_scenario=convergence_scenario,
                    sequencing_rule=sequencing_rule,
                    agents_activated=agents,
                    approval_lineage=lineage,
                )
                return self._lifecycle_paused_response(
                    task_id=task_id,
                    pause_reason="POLICY_HOLD",
                    path_selection=path_selection,
                    gate_context=gate_context,
                    conflict=None,
                    convergence_scenario=convergence_scenario,
                    sequencing_rule=sequencing_rule,
                    agents_activated=agents,
                    approval_lineage=lineage,
                )

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

        # ── Step 4: TradeSupport OMS release package ──────────────────
        ts_handoff = self.handoff(
            task_id        = task_id,
            from_agent     = AGENT_J if AGENT_J in agents else AGENT_C2,
            to_agent       = "AUR-R-TRADESUPPORT-001",
            object_state   = decision,
            handoff_reason = "Pre-trade complete — releasing to TradeSupport for OMS package",
        )
        ts_confirmed = agent_ts.confirm_handoff(ts_handoff)
        if not ts_confirmed:
            self.escalate(
                task_id          = task_id,
                escalating_agent = "AUR-R-TRADESUPPORT-001",
                reason           = "TradeSupport handoff confirmation failed",
                severity         = "HALT",
                context          = {"handoff_record": ts_handoff},
            )
            result["status"] = "HANDOFF_FAILURE"
            return result

        ts_result = agent_ts.prepare_execution_package(decision, task_id, self)
        result["ts_result"] = ts_result
        self.record_agent_telemetry(task_id, "AUR-R-TRADESUPPORT-001", ts_result)

        if ts_result.get("status") == "BLOCKED":
            result["status"] = "BLOCKED_BY_TRADESUPPORT"
            return result

        # ── Step 5: Post-execution reconciliation ─────────────────────
        # Build execution confirmation from the OMS release result.
        # In production this comes from the OMS; here we derive it from
        # the approved decision — the lifecycle is paper-trading.
        execution_confirmation = ExecutionConfirmation(
            task_id=task_id,
            decision_id=decision.get("id"),
            symbol=decision.get("symbol"),
            action=decision.get("action"),
            shares=decision.get("shares", 0),
            notional=decision.get("notional", 0),
        )
        dsor_intent = DSORIntent(
            task_id=task_id,
            decision_id=decision.get("id"),
            symbol=decision.get("symbol"),
            action=decision.get("action"),
            shares=decision.get("shares", 0),
            notional=decision.get("notional", 0),
        )

        recon_result = agent_ts.reconcile_execution(execution_confirmation, dsor_intent)
        result["ts_recon_result"] = recon_result

        if recon_result.get("status") == "DISCREPANCY":
            # RTS6 alert on trade-level discrepancy
            rts6_alert = agent_regrep.generate_rts6_alert(BreachEvent(
                task_id=task_id,
                breach_ts=datetime.now(timezone.utc).isoformat(),
                breach_source_role_id="AUR-R-TRADESUPPORT-001",
                breach_type="TRADE_LEVEL_DISCREPANCY",
                symbol=decision.get("symbol", ""),
                detail=str(recon_result.get("mismatches", [])),
                decision_id=decision.get("id", ""),
            ))
            result["rts6_alert"] = rts6_alert

            escalation = agent_ts.escalate_discrepancy(recon_result)
            self.escalate(
                task_id          = task_id,
                escalating_agent = "AUR-R-TRADESUPPORT-001",
                reason           = f"Execution discrepancy: {recon_result.get('mismatches')}",
                severity         = "WARN",
                context          = recon_result,
            )
            result["status"]     = "DISCREPANCY_HALTED"
            result["escalation"] = {
                "agent":    escalation.agent_role_id,
                "reason":   escalation.reason,
                "tier":     escalation.requires_authority_tier,
            }
            return result

        # ── Step 6: Reconciliation cross-system lineage check ─────────
        recon_handoff = self.handoff(
            task_id        = task_id,
            from_agent     = "AUR-R-TRADESUPPORT-001",
            to_agent       = "AUR-R-RECON-001",
            object_state   = decision,
            handoff_reason = "Trade-level reconciliation matched — cross-system lineage check",
        )
        recon_confirmed = agent_recon.confirm_handoff(recon_handoff)
        if not recon_confirmed:
            self.escalate(
                task_id          = task_id,
                escalating_agent = "AUR-R-RECON-001",
                reason           = "Reconciliation handoff confirmation failed",
                severity         = "HALT",
                context          = {"handoff_record": recon_handoff},
            )
            result["status"] = "HANDOFF_FAILURE"
            return result

        lineage_check = agent_recon.match_intent_vs_execution(
            dsor_intent      = dsor_intent,
            execution_record = execution_confirmation,
        )
        result["recon_lineage_result"] = lineage_check
        self.record_agent_telemetry(task_id, "AUR-R-RECON-001", lineage_check)

        if lineage_check.get("status") == "UNMATCHED":
            # RTS6 alert on cross-system lineage break
            rts6_alert = agent_regrep.generate_rts6_alert(BreachEvent(
                task_id=task_id,
                breach_ts=datetime.now(timezone.utc).isoformat(),
                breach_source_role_id="AUR-R-RECON-001",
                breach_type="CROSS_SYSTEM_LINEAGE_UNMATCHED",
                symbol=decision.get("symbol", ""),
                detail=str(lineage_check.get("unmatched", [])),
                decision_id=decision.get("id", ""),
            ))
            result["rts6_alert"] = rts6_alert

            lineage_package = agent_recon.assemble_root_cause_lineage(task_id)
            escalation = agent_recon.escalate_break({
                "type":            "LINEAGE_UNMATCHED",
                "symbol":          decision.get("symbol"),
                "delta":           lineage_check.get("unmatched"),
                "task_id":         task_id,
                "lineage_package": lineage_package,
            })
            self.escalate(
                task_id          = task_id,
                escalating_agent = "AUR-R-RECON-001",
                reason           = f"Cross-system lineage unmatched: {lineage_check.get('unmatched')}",
                severity         = "WARN",
                context          = lineage_check,
            )
            result["status"]     = "LINEAGE_UNMATCHED_HALTED"
            result["escalation"] = {
                "agent":    escalation.agent_role_id,
                "reason":   escalation.reason,
                "tier":     escalation.requires_authority_tier,
            }
            return result

        # ── Step 7: Handoff to SettlementOps ──────────────────────────
        if AGENT_R in agents:
            settle_handoff = self.handoff(
                task_id        = task_id,
                from_agent     = "AUR-R-RECON-001",
                to_agent       = AGENT_R,
                object_state   = decision,
                handoff_reason = "Cross-system lineage verified — releasing to settlement",
            )
            confirmed = agent_settlement.confirm_handoff(settle_handoff)
            if not confirmed:
                self.escalate(
                    task_id          = task_id,
                    escalating_agent = AGENT_R,
                    reason           = "SettlementOps handoff confirmation failed",
                    severity         = "HALT",
                    context          = {"handoff_record": settle_handoff},
                )
                result["status"] = "HANDOFF_FAILURE"
                return result

        # ── Step 7: SettlementOps settlement preparation ──────────────
        if AGENT_R in agents:
            r_result = agent_settlement.prepare_execution_package(decision, task_id, self)
            result["r_result"] = r_result
            self.record_agent_telemetry(task_id, AGENT_R, r_result)

        # ── Step 9: RegReporting lifecycle-close package ────────────────
        regrep_handoff = self.handoff(
            task_id        = task_id,
            from_agent     = AGENT_R,
            to_agent       = "AUR-R-REGREP-001",
            object_state   = decision,
            handoff_reason = "Settlement complete — regulatory reporting lifecycle close",
        )
        regrep_confirmed = agent_regrep.confirm_handoff(regrep_handoff)
        if not regrep_confirmed:
            self.escalate(
                task_id          = task_id,
                escalating_agent = "AUR-R-REGREP-001",
                reason           = "RegReporting handoff confirmation failed",
                severity         = "HALT",
                context          = {"handoff_record": regrep_handoff},
            )
            result["status"] = "HANDOFF_FAILURE"
            return result

        # Build lifecycle-close reporting context
        reporting_context = ReportingContext(
            task_id=task_id,
            decision_id=decision.get("id"),
            symbol=decision.get("symbol", ""),
            action=decision.get("action", ""),
            notional=decision.get("notional", 0),
            asset_class=decision.get("asset_class", ""),
            counterparty_lei=decision.get("counterparty_lei", "N/A_PAPER_TRADING"),
            authority_hash=r_result.get("lineage_stamp", {}).get("authority_hash", "") if r_result else "",
            doctrine_version=doctrine_version or "unknown",
            release_target=decision.get("release_target", "OMS"),
        )

        regrep_result = agent_regrep.prepare_execution_package(reporting_context, task_id, self)
        result["regrep_result"] = regrep_result
        self.record_agent_telemetry(task_id, "AUR-R-REGREP-001", regrep_result)

        # Generate individual reports for BCBS 239 P3 validation
        emir_report = agent_regrep.generate_emir_report(reporting_context)
        result["emir_report"] = emir_report

        # BCBS 239 P3 validation gate
        p3_result = agent_regrep.validate_bcbs239_p3_accuracy(
            report=emir_report,
            dsor_source=dsor_intent,
        )
        result["bcbs239_p3_result"] = p3_result

        if p3_result.get("status") == "BLOCKED":
            escalation = agent_regrep.escalate_reporting_failure({
                "failure_type":      "BCBS239_P3_VALIDATION_BLOCKED",
                "report_type":       "EMIR",
                "detail":            str(p3_result.get("mismatches", [])),
                "task_id":           task_id,
            })
            self.escalate(
                task_id          = task_id,
                escalating_agent = "AUR-R-REGREP-001",
                reason           = f"BCBS 239 P3 validation blocked: {p3_result.get('mismatches')}",
                severity         = "WARN",
                context          = p3_result,
            )
            result["status"]     = "BCBS239_P3_VALIDATION_BLOCKED"
            result["escalation"] = {
                "agent":    escalation.agent_role_id,
                "reason":   escalation.reason,
                "tier":     escalation.requires_authority_tier,
            }
            return result

        # ── Step 10: Assemble unified lineage ─────────────────────────
        lineage = self.get_unified_lineage(task_id)
        result["unified_lineage"] = lineage
        result["status"]          = "COMPLETE"

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # HALT-AND-PEND / RESUME-AFTER-APPROVAL (Phase 4)
    # ─────────────────────────────────────────────────────────────────────────

    def _serialize_selection(self, path_selection) -> dict | None:
        """Best-effort serialization of a JTACPathSelection for persistence."""
        if path_selection is None:
            return None
        to_dict = getattr(path_selection, "to_dict", None)
        if callable(to_dict):
            return to_dict()
        return dict(path_selection.__dict__) if hasattr(path_selection, "__dict__") else None

    def _persist_paused_lifecycle(self,
                                  *,
                                  task_id: str,
                                  pause_reason: str,
                                  decision: dict,
                                  path_selection,
                                  doctrine_version: str | None,
                                  gate_context=None,
                                  conflict=None,
                                  convergence_scenario: str | None,
                                  sequencing_rule: str | None,
                                  agents_activated: list,
                                  approval_lineage=None) -> dict:
        """Write a paused-lifecycle entry to aureon_state["paused_lifecycles"]
        keyed by task_id. Persisted across restarts via save_state().

        approval_lineage (ApprovalLineageRequirement, Phase 4.5) is serialized
        into the paused entry so resume-time validation can look up required
        authorities without re-querying the rules fixture. Backward-compatible:
        entries persisted before Phase 4.5 have approval_lineage=None and
        resume_paused_lifecycle falls back to a live rules lookup.
        """
        ts = datetime.now(timezone.utc).isoformat()
        pinned_doctrine = doctrine_version or self._state.get("doctrine_version", "unknown")
        # Per-pause-reason resume step — skip policy check on POLICY_HOLD
        # resume (it already ran and was overridden).
        resume_step = (
            "POST_POLICY_CONTINUE_TO_JTAC"
            if pause_reason == "POLICY_HOLD"
            else "POST_OFAC_CONTINUE_TO_POLICY"
        )
        entry = {
            "task_id":                   task_id,
            "pause_reason":              pause_reason,
            "paused_at":                 ts,
            "doctrine_version_at_pause": pinned_doctrine,
            "path_selection":            self._serialize_selection(path_selection),
            "gate_context":              gate_context.to_dict() if gate_context is not None else None,
            "conflict":                  conflict.to_dict() if conflict is not None else None,
            "approval_lineage":          approval_lineage.to_dict() if approval_lineage is not None else None,
            "lifecycle_context": {
                "decision":              dict(decision),
                "convergence_scenario":  convergence_scenario,
                "sequencing_rule":       sequencing_rule,
                "agents_activated":      list(agents_activated),
            },
            "resume_step":               resume_step,
        }
        with self._lock:
            paused = self._state.setdefault("paused_lifecycles", {})
            paused[task_id] = entry
        self._authority_log_entry(
            task_id    = task_id,
            event_type = f"C2_LIFECYCLE_PAUSED_{pause_reason}",
            detail     = (f"Task {task_id} paused | Reason: {pause_reason} | "
                          f"Doctrine pinned at: {pinned_doctrine} | "
                          f"Resume via /api/c2/resume/{task_id}"),
        )
        print(f"[THIFUR-C2] Lifecycle paused — {pause_reason} | task {task_id} | "
              f"doctrine pinned: {pinned_doctrine}")
        return entry

    def _lifecycle_paused_response(self,
                                   *,
                                   task_id: str,
                                   pause_reason: str,
                                   path_selection,
                                   gate_context,
                                   conflict,
                                   convergence_scenario: str | None,
                                   sequencing_rule: str | None,
                                   agents_activated: list,
                                   approval_lineage=None) -> dict:
        """Build the response dict returned to the caller when the lifecycle
        has halted. Mirrors the shape of the complete-lifecycle result so
        callers have a consistent field set."""
        return {
            "task_id":              task_id,
            "convergence_scenario": convergence_scenario,
            "sequencing_rule":      sequencing_rule,
            "agents_activated":     agents_activated,
            "j_result":             None,
            "r_result":             None,
            "unified_lineage":      None,
            "status":               "PAUSED",
            "pause_reason":         pause_reason,
            "path_selection":       self._serialize_selection(path_selection),
            "gate_context":         gate_context.to_dict() if gate_context is not None else None,
            "conflict":             conflict.to_dict() if conflict is not None else None,
            "approval_lineage":     approval_lineage.to_dict() if approval_lineage is not None else None,
            "resume_endpoint":      f"/api/c2/resume/{task_id}",
        }

    def _lifecycle_blocked_response(self,
                                    *,
                                    task_id: str,
                                    block_reason: str,
                                    failures: list,
                                    policy_result=None,
                                    convergence_scenario: str | None,
                                    sequencing_rule: str | None,
                                    agents_activated: list,
                                    compliance_clearance: dict | None = None) -> dict:
        """Terminal halt response — no pend, no resume. Used when a
        policy check returns BLOCK (hard violation: prohibited asset
        class, prohibited counterparty type, mandate hard cap breach).
        Writes an authority-log + compliance-alert escalation entry.
        """
        ts = datetime.now(timezone.utc).isoformat()
        self._authority_log_entry(
            task_id    = task_id,
            event_type = f"C2_LIFECYCLE_BLOCKED_{block_reason}",
            detail     = (f"Task {task_id} terminally blocked | Reason: "
                          f"{block_reason} | Failures: "
                          f"{[f.get('check_name') for f in (failures or [])]}"),
        )
        with self._lock:
            alerts = self._state.setdefault("compliance_alerts", [])
            alerts.insert(0, {
                "id":       f"BLOCK-{task_id[-6:]}",
                "severity": "HALT",
                "title":    f"Lifecycle BLOCK: {block_reason}",
                "detail":   f"Task {task_id} | {len(failures or [])} failure(s)",
                "ts":       ts,
                "resolved": False,
                "source":   "THIFUR_C2",
            })
        return {
            "task_id":              task_id,
            "convergence_scenario": convergence_scenario,
            "sequencing_rule":      sequencing_rule,
            "agents_activated":     agents_activated,
            "j_result":             None,
            "r_result":             None,
            "unified_lineage":      None,
            "status":               "BLOCKED",
            "block_reason":         block_reason,
            "failures":             list(failures or []),
            "policy_result":        policy_result.to_dict() if policy_result is not None else None,
            "compliance_clearance": compliance_clearance,
        }

    def resume_paused_lifecycle(self,
                                task_id: str,
                                approval_decision: str,
                                approval_attribution: dict,
                                agent_j) -> dict:
        """Resume a paused lifecycle per operator decision.

        approval_decision: "APPROVE" or "DENY".
        approval_attribution keys required:
          - operator: str
          - rationale: str
          - compliance_authority_decision: dict  (iff CONFLICT_RESOLUTION_REQUIRED)
          - legal_authority_decision: dict       (iff CONFLICT_RESOLUTION_REQUIRED)

        Returns one of:
          - status="NOT_FOUND"         — no paused entry for task_id
          - status="INVALID_APPROVAL"  — missing fields for the pause_reason
          - status="DENIED"            — terminal halt recorded, entry removed
          - status="COMPLETE" / other  — post-compliance lifecycle result

        Doctrine-version pinning: the resumed lifecycle runs under
        doctrine_version_at_pause (not the currently active version).

        Replay safety: Compliance is NOT re-executed on resume — the path
        was already selected. Resumption begins at the post-compliance tail.
        """
        with self._lock:
            paused = self._state.get("paused_lifecycles", {})
            entry = paused.get(task_id)

        if entry is None:
            return {"task_id": task_id, "status": "NOT_FOUND"}

        pause_reason = entry.get("pause_reason")
        attribution = approval_attribution or {}

        # ── Payload completeness validation (Phase 4.5: data-driven) ──
        # Determine required authorities via Compliance.determine_approval_lineage
        # (uses approval_lineage_rules.json). Fallback to the lineage persisted
        # on the entry if it's present and the lookup fails. Backward-compat:
        # operator+rationale alone satisfy single-authority pauses; dual-
        # authority pauses additionally require explicit per-authority
        # decisions.
        agent_compliance = JTAC_AGENTS["AUR-J-COMP-001"](self._state, self._lock) \
            if "AUR-J-COMP-001" in JTAC_AGENTS else None
        lineage = None
        if agent_compliance is not None:
            lineage = agent_compliance.determine_approval_lineage(
                pause_reason=pause_reason, task_id=task_id,
            )
        if lineage is None and entry.get("approval_lineage"):
            # Fall back to persisted lineage if live lookup unavailable
            persisted = entry["approval_lineage"]
            from aureon.agents.payloads import ApprovalLineageRequirement
            lineage = ApprovalLineageRequirement(
                task_id=persisted.get("task_id") or task_id,
                pause_reason=persisted.get("pause_reason") or pause_reason,
                required_authorities=list(persisted.get("required_authorities") or []),
                sla_seconds=persisted.get("sla_seconds"),
                fallback_authorities=list(persisted.get("fallback_authorities") or []),
            )

        required_auths = list(lineage.required_authorities) if lineage else ["compliance"]

        missing = []
        if not attribution.get("operator"):
            missing.append("operator")
        if not attribution.get("rationale"):
            missing.append("rationale")
        # Explicit per-authority decisions required when 2+ authorities mandated.
        # Single-authority pauses (OFAC non-EU, POLICY_HOLD) treat operator +
        # rationale under CAOM-001 as the compliance decision — preserves
        # Phase 4 behavior.
        if len(required_auths) >= 2:
            for auth in required_auths:
                key = f"{auth}_authority_decision"
                if not attribution.get(key):
                    missing.append(key)
        if missing:
            return {
                "task_id": task_id,
                "status":  "INVALID_APPROVAL",
                "missing": missing,
                "reason":  (f"{pause_reason} requires operator+rationale"
                            + (f" and explicit decisions from "
                               f"{required_auths}" if len(required_auths) >= 2 else "")
                            + "."),
                "required_authorities": required_auths,
            }

        # ── DENY branch — terminal halt, remove paused entry ─────────
        if approval_decision == "DENY":
            with self._lock:
                self._state.setdefault("paused_lifecycles", {}).pop(task_id, None)
            self.escalate(
                task_id          = task_id,
                escalating_agent = "AUR-J-COMP-001",
                reason           = f"Lifecycle denied by operator: {attribution.get('rationale', 'no rationale')}",
                severity         = "WARN",
                context          = {"pause_reason": pause_reason, "attribution": attribution},
            )
            self._authority_log_entry(
                task_id    = task_id,
                event_type = "C2_LIFECYCLE_DENIED",
                detail     = (f"Operator={attribution.get('operator', '?')} | "
                              f"Reason={attribution.get('rationale', '?')} | "
                              f"Original pause={pause_reason}"),
            )
            return {
                "task_id":      task_id,
                "status":       "DENIED",
                "pause_reason": pause_reason,
                "attribution":  dict(attribution),
            }

        if approval_decision != "APPROVE":
            return {
                "task_id": task_id,
                "status":  "INVALID_APPROVAL",
                "reason":  f"approval_decision must be APPROVE or DENY (got {approval_decision!r})",
            }

        # ── APPROVE branch — continue post-Compliance tail ───────────
        lifecycle_context = entry.get("lifecycle_context", {})
        decision = dict(lifecycle_context.get("decision", {}))
        agents_activated = list(lifecycle_context.get("agents_activated", [AGENT_J, AGENT_R]))
        sequencing_rule = lifecycle_context.get("sequencing_rule")
        convergence_scenario = lifecycle_context.get("convergence_scenario")
        doctrine_pinned = entry.get("doctrine_version_at_pause")

        resume_attribution = {
            "operator":                       attribution.get("operator"),
            "rationale":                      attribution.get("rationale"),
            "compliance_authority_decision":  attribution.get("compliance_authority_decision"),
            "legal_authority_decision":       attribution.get("legal_authority_decision"),
            "original_pause_reason":          pause_reason,
            "paused_at":                      entry.get("paused_at"),
            "resumed_at":                     datetime.now(timezone.utc).isoformat(),
            "doctrine_version_pinned":        doctrine_pinned,
        }

        self._authority_log_entry(
            task_id    = task_id,
            event_type = "C2_LIFECYCLE_RESUMED",
            detail     = (f"Operator={attribution.get('operator', '?')} | "
                          f"Pause={pause_reason} | Doctrine pinned={doctrine_pinned}"),
        )

        # Reconstitute C2's in-memory task record if this process wasn't the
        # one that issued the task (e.g. Railway restart spanned the pause).
        # No-op when resuming within the same process.
        self._reconstitute_task_on_resume(task_id, entry)

        # Remove paused entry BEFORE continuing so a crash mid-resume leaves
        # the lifecycle in a clean "not-paused" state.
        with self._lock:
            self._state.setdefault("paused_lifecycles", {}).pop(task_id, None)

        # Phase 4.5: ALGO_INVENTORY_MISSING is a session-level (non-trade)
        # halt. Resume just records the authorization — it does NOT trigger
        # a trade lifecycle. Downstream agents (TradeSupport, ThifurJ, etc.)
        # do not run for this pause reason.
        if pause_reason == "ALGO_INVENTORY_MISSING":
            self._authority_log_entry(
                task_id    = task_id,
                event_type = "C2_ALGO_INVENTORY_OVERRIDE_APPROVED",
                detail     = (f"Operator={attribution.get('operator','?')} | "
                              f"Rationale={attribution.get('rationale','?')} | "
                              f"Dual-authority (compliance+legal) approval recorded."),
            )
            return {
                "task_id":              task_id,
                "status":               "ALGO_INVENTORY_OVERRIDE_APPROVED",
                "pause_reason":         pause_reason,
                "resume_attribution":   resume_attribution,
                "doctrine_version_pinned": doctrine_pinned,
                "active_algorithms":    dict(lifecycle_context.get("decision", {})).get("active_algorithms", []),
            }

        # On POLICY_HOLD resume, the policy check already ran and was
        # operator-overridden — do not re-run it. Phase 4 OFAC pauses
        # (APPROVAL_REQUIRED, CONFLICT_RESOLUTION_REQUIRED) resume into
        # the policy gate as normal (operator's OFAC override doesn't
        # skip downstream checks).
        skip_policy = pause_reason == "POLICY_HOLD"

        # Run the post-compliance tail with the pinned doctrine version.
        return self._execute_post_compliance_lifecycle(
            decision             = decision,
            task_id              = task_id,
            agent_j              = agent_j,
            agents_activated     = agents_activated,
            sequencing_rule      = sequencing_rule,
            doctrine_version     = doctrine_pinned,
            convergence_scenario = convergence_scenario,
            compliance_clearance = {
                "path_id":   entry.get("path_selection", {}).get("selected_path_id") if entry.get("path_selection") else None,
                "rationale": "Operator-approved override after compliance halt",
            },
            resume_attribution = resume_attribution,
            skip_policy_check  = skip_policy,
        )

    def list_paused_lifecycles(self) -> list:
        """Return a list of currently paused lifecycles for operator
        inspection. Reads from aureon_state["paused_lifecycles"]."""
        with self._lock:
            paused = self._state.get("paused_lifecycles", {}) or {}
            return list(paused.values())

    def _reconstitute_task_on_resume(self, task_id: str, paused_entry: dict) -> None:
        """Rebuild the in-memory C2 task record for a resumed lifecycle when
        this process is not the one that issued the original task (i.e. after
        a Railway restart crossed the pause). The internal _tasks/_handoff_log/
        _lineage registers are in-memory only by design for Phase 4 — full C2
        state persistence is the deferred "C2 log persistence gap" item in
        TRACKERS.md.

        No-op if the task is already registered (resume within the same process).
        Does NOT emit a C2_TASK_ISSUED authority log — that was already written
        when the task was first issued pre-pause.
        """
        with self._c2_lock:
            if task_id in self._tasks:
                return
            ctx = paused_entry.get("lifecycle_context", {}) or {}
            agents = list(ctx.get("agents_activated", []))
            task = {
                "task_id":              task_id,
                "created_ts":           paused_entry.get("paused_at", datetime.now(timezone.utc).isoformat()),
                "doctrine_version":     paused_entry.get("doctrine_version_at_pause", "unknown"),
                "lifecycle_packet":     dict(ctx.get("decision", {})),
                "agents_tasked":        agents,
                # Compliance already ran, so mark it complete. The others will
                # transition from ISSUED → COMPLETE as the post-compliance
                # tail runs.
                "agent_states":         {a: HS_ISSUED for a in agents},
                "handoff_sequence":     [],
                "telemetry":            {
                    "AUR-J-COMP-001": {
                        "received_ts": paused_entry.get("paused_at"),
                        "agent_id":    "AUR-J-COMP-001",
                        "data":        paused_entry.get("path_selection") or {},
                    }
                },
                "escalations":          [],
                "convergence_scenario": ctx.get("convergence_scenario"),
                "unified_lineage_ready": False,
                "dsor_submitted":       False,
                "status":               "ACTIVE",
                "resumed_from_pause":   True,
            }
            self._tasks[task_id] = task

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
