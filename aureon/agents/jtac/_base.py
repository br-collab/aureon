"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/agents/jtac/_base.py                                         ║
║  JTACConcreteBase — Bounded-Autonomy Concrete Base                  ║
║                                                                      ║
║  MANDATE:                                                            ║
║    Provide the machinery every JTAC role inherits: approved-path    ║
║    loading, deterministic path selection, approval-lineage           ║
║    validation, conflict-registry lookup, and handoff confirmation.  ║
║                                                                      ║
║  TIER-SPECIFIC GUARDRAILS:                                           ║
║    - Approved paths only — select_path_by_id raises                  ║
║      UnapprovedPathError if no registered path applies.              ║
║    - No release without approval lineage — a path marked             ║
║      requires_approval=True MUST return a JTACPathSelection with     ║
║      requires_approval=True and MUST NOT proceed to its action       ║
║      callable until C2 re-enters with operator approval.             ║
║    - Eligibility before routing — concrete roles must run their     ║
║      eligibility checks before dispatching to select_path_by_id.    ║
║      For OFAC Screening the sanctions check IS the eligibility     ║
║      check.                                                          ║
║    - Doctrine over regulation conflict — when detect_conflict       ║
║      returns a ConflictResolution, the role DOES NOT proceed.       ║
║      Resolution authority is dual-human (Compliance + Legal).       ║
║    - No self-initiation — JTAC roles only act on C2-issued          ║
║      taskings, confirmed via confirm_handoff.                        ║
║                                                                      ║
║  FILE LAYOUT NOTE:                                                   ║
║    Phase 4 introduces this base. ThifurJ (AUR-J-TRADE-001) still    ║
║    inherits aureon.agents.base.JTACAgent directly — retrofit to     ║
║    this concrete base is deferred to Phase 4.1 per the TRACKERS.md  ║
║    "JTAC base unification" entry. Until Phase 4.1 lands, two JTAC   ║
║    base classes coexist: JTACAgent (ABC) and JTACConcreteBase.      ║
║                                                                      ║
║  LOADER INTERFACE NOTE:                                              ║
║    load_approved_paths and _load_conflict_registry both accept an   ║
║    optional source_path parameter. Phase 4 reads JSON from the      ║
║    doctrine directory. Future (Phase 7+) database-backed loaders    ║
║    can supply their own source without changing the call sites.     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Optional

from aureon.agents.base import JTACAgent, Tasking
from aureon.agents.payloads import (
    ApprovedPath,
    JTACPathSelection,
    ApprovalGateContext,
    ConflictResolution,
)

# ── Doctrine paths ────────────────────────────────────────────────────────────
# Derived from this file's location so the code works both locally and under
# Railway's deploy layout. The doctrine directory is a peer of aureon/agents/.
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
_DOCTRINE_DIR = os.path.join(_REPO_ROOT, "aureon", "doctrine")
_JTAC_PATHS_DIR = os.path.join(_DOCTRINE_DIR, "jtac_paths")
_CONFLICTS_FILE = os.path.join(_DOCTRINE_DIR, "conflicts", "known_conflicts.json")

# YAML note: The prompt specified YAML for doctrine files, but PyYAML is not
# in requirements.txt and this codebase does not add new deps. JSON is used
# instead with identical shape. A future PyYAML-enabled environment can swap
# the loader by overriding source_path (the seam is already here).


class UnapprovedPathError(RuntimeError):
    """Raised when a JTAC role attempts to select a path not in its approved set.

    Enforces the bounded-autonomy guardrail: JTAC chooses among registered paths,
    never invents a new one. Surfacing this as an explicit exception (not a
    silent fallback) makes any attempted out-of-doctrine routing visible.
    """

    def __init__(self, role_id: str, attempted_path_id: str,
                 approved_path_ids: list):
        self.role_id = role_id
        self.attempted_path_id = attempted_path_id
        self.approved_path_ids = list(approved_path_ids)
        super().__init__(
            f"[{role_id}] Unapproved path '{attempted_path_id}'. "
            f"Approved set: {self.approved_path_ids}"
        )


class JTACConcreteBase(JTACAgent):
    """Concrete base for every bounded-autonomy (Thifur-J) role.

    Subclasses (e.g. Compliance at AUR-J-COMP-001) define task methods that:
      1. Run eligibility / screening logic (sanctions check, mandate fit, etc.).
      2. Use self.select_path_by_id(path_id) to resolve the chosen path.
      3. Build a JTACPathSelection via self.build_path_selection(...) — honors
         the path's requires_approval flag and runs self.detect_conflict(...).
      4. Return the JTACPathSelection to C2. C2 inspects it to decide whether
         to continue the lifecycle, halt-and-pend for single-authority approval,
         or halt-and-pend for dual-authority conflict resolution.

    Subclasses do NOT execute the path's action callable when requires_approval
    is True — that's what the Phase 4 halt-and-pend + resume mechanism handles.
    """

    tier = 2
    thifur_class = "J"

    def __init__(self, aureon_state: dict, state_lock: threading.Lock):
        super().__init__(aureon_state, state_lock)
        self._approved_paths: dict[str, ApprovedPath] = {}
        self._conflict_registry: dict[str, dict] = {}
        self._paths_source: Optional[str] = None
        self._conflicts_source: Optional[str] = None

    # ─────────────────────────────────────────────────────────────────────────
    # APPROVED-PATH LOADING
    # ─────────────────────────────────────────────────────────────────────────

    def load_approved_paths(self, role_id: str,
                            source_path: Optional[str] = None) -> dict[str, ApprovedPath]:
        """Load the approved-path set for *role_id*.

        Default source is the doctrine JSON file at
        aureon/doctrine/jtac_paths/<role_id>.json. Callers can pass
        *source_path* to override — the seam for future DB-backed loaders.

        Populates self._approved_paths and returns it for inspection.
        Raises FileNotFoundError if the doctrine file is absent; a missing
        doctrine file is a structural error, not a silent fallback.
        """
        path = source_path or os.path.join(_JTAC_PATHS_DIR, f"{role_id}.json")
        self._paths_source = path
        with open(path, "r") as fh:
            raw = json.load(fh)
        loaded: dict[str, ApprovedPath] = {}
        for entry in raw.get("paths", []):
            ap = ApprovedPath(
                path_id=entry["path_id"],
                role_id=role_id,
                description=entry.get("description", ""),
                callable_ref=entry.get("callable_ref"),
                rule_data=entry.get("rule_data"),
                requires_approval=bool(entry.get("requires_approval", False)),
                approval_predicates=list(entry.get("approval_predicates", [])),
                conflict_keys=list(entry.get("conflict_keys", [])),
            )
            loaded[ap.path_id] = ap
        self._approved_paths = loaded
        return loaded

    # ─────────────────────────────────────────────────────────────────────────
    # PATH SELECTION
    # ─────────────────────────────────────────────────────────────────────────

    def select_path_by_id(self, path_id: str) -> ApprovedPath:
        """Look up an approved path by id. Raises UnapprovedPathError if
        the id is not in the loaded approved set. This is the enforcement
        point for the approved-paths-only guardrail."""
        if path_id not in self._approved_paths:
            raise UnapprovedPathError(
                role_id=self.role_id,
                attempted_path_id=path_id,
                approved_path_ids=list(self._approved_paths.keys()),
            )
        return self._approved_paths[path_id]

    def validate_approval_lineage(self, path_selection: JTACPathSelection) -> bool:
        """Returns True if the selected path requires human approval before
        the lifecycle may proceed. Thin helper over the selection payload —
        present as a named method so callers (including C2) read the
        control-flow intent, not a boolean dereference."""
        return bool(path_selection.requires_approval)

    # ─────────────────────────────────────────────────────────────────────────
    # CONFLICT REGISTRY
    # ─────────────────────────────────────────────────────────────────────────

    def _ensure_conflicts_loaded(self, source_path: Optional[str] = None) -> None:
        """Lazy-load the conflict registry on first detect_conflict call.
        Registry is shared across all JTAC roles so loading is idempotent."""
        if self._conflict_registry:
            return
        path = source_path or _CONFLICTS_FILE
        self._conflicts_source = path
        if not os.path.exists(path):
            self._conflict_registry = {}
            return
        with open(path, "r") as fh:
            raw = json.load(fh)
        for entry in raw.get("conflicts", []):
            self._conflict_registry[entry["id"]] = entry

    def detect_conflict(self,
                        path: ApprovedPath,
                        regulatory_context: dict,
                        task_id: str,
                        source_path: Optional[str] = None
                        ) -> Optional[ConflictResolution]:
        """Return a ConflictResolution if any conflict_key on the selected
        path is triggered by the regulatory_context, else None.

        Applicability rule (Phase 4 scope):
          A conflict applies when its primary_jurisdictions intersects with
          the jurisdictions present in regulatory_context. That is the only
          rule checked here. Richer applicability logic (multi-predicate,
          temporal, product-class, etc.) is deferred to later phases.

        regulatory_context keys read by this base:
          - "jurisdictions": list of jurisdiction codes (e.g. ["EU"])
          - "jurisdiction":  single jurisdiction code (convenience alias)

        The first matching conflict wins — ordering follows the path's
        conflict_keys list.
        """
        if not path.conflict_keys:
            return None
        self._ensure_conflicts_loaded(source_path)
        ctx_jurisdictions = set(regulatory_context.get("jurisdictions") or [])
        single = regulatory_context.get("jurisdiction")
        if single:
            ctx_jurisdictions.add(single)

        for key in path.conflict_keys:
            entry = self._conflict_registry.get(key)
            if not entry:
                continue
            primary = set(entry.get("primary_jurisdictions", []))
            if not primary or (ctx_jurisdictions & primary):
                return ConflictResolution(
                    task_id=task_id,
                    conflict_id=key,
                    conflict_summary=entry.get("summary", "").strip(),
                    requires_compliance_authority=(
                        "compliance" in entry.get("resolution_authority", [])
                    ),
                    requires_legal_authority=(
                        "legal" in entry.get("resolution_authority", [])
                    ),
                )
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # PATH-SELECTION PAYLOAD BUILDER
    # ─────────────────────────────────────────────────────────────────────────

    def build_path_selection(self,
                             task_id: str,
                             path: ApprovedPath,
                             rationale: str,
                             regulatory_context: Optional[dict] = None,
                             doctrine_version: Optional[str] = None,
                             ) -> JTACPathSelection:
        """Assemble a JTACPathSelection for *path*. Honors the path's
        requires_approval flag and runs detect_conflict against the
        regulatory_context (if any). If a conflict applies, the selection
        has both requires_approval=True AND requires_authority_resolution=True,
        with conflict_id populated.
        """
        dv = doctrine_version or self._state.get("doctrine_version", "unknown")
        ctx = regulatory_context or {}
        conflict = self.detect_conflict(path, ctx, task_id=task_id)
        selection = JTACPathSelection(
            task_id=task_id,
            role_id=self.role_id,
            selected_path_id=path.path_id,
            selection_rationale=rationale,
            requires_approval=bool(path.requires_approval or conflict is not None),
            pending_approval_for=list(path.approval_predicates),
            requires_authority_resolution=conflict is not None,
            conflict_id=conflict.conflict_id if conflict else None,
            doctrine_version=dv,
        )
        # Stash the detected conflict on the instance so escalate_for_conflict_resolution
        # can produce the full payload without re-running detection. Keyed by task_id
        # so concurrent taskings don't collide.
        if conflict is not None:
            self._pending_conflicts = getattr(self, "_pending_conflicts", {})
            self._pending_conflicts[task_id] = conflict
        return selection

    # ─────────────────────────────────────────────────────────────────────────
    # HANDOFF + ESCALATION
    # ─────────────────────────────────────────────────────────────────────────

    def confirm_handoff(self, tasking) -> bool:
        """Confirm a C2-issued handoff. Accepts either a Tasking object or
        a dict-shaped handoff record (mirrors the Ranger pattern at
        aureon/agents/ranger/_base.py)."""
        if isinstance(tasking, dict):
            return bool(tasking.get("c2_authorized"))
        if isinstance(tasking, Tasking):
            return bool(tasking.c2_tasking_id)
        return False

    def escalate_for_approval(self,
                              path_selection: JTACPathSelection,
                              intent_summary: Optional[dict] = None,
                              risk_summary: Optional[dict] = None,
                              ) -> ApprovalGateContext:
        """Build the payload C2 receives when the lifecycle must halt pending
        single-authority operator approval. Writes a compliance-log entry on
        the way out so the pause is visible in aureon_state and in the dashboard.
        """
        ctx = ApprovalGateContext(
            task_id=path_selection.task_id,
            role_id=self.role_id,
            path_selection=path_selection,
            intent_summary=intent_summary or {},
            risk_summary=risk_summary or {},
            pending_predicates=list(path_selection.pending_approval_for),
        )
        self._log_escalation(
            task_id=path_selection.task_id,
            event_type="JTAC_APPROVAL_HALT",
            detail=(
                f"path={path_selection.selected_path_id} "
                f"predicates={path_selection.pending_approval_for}"
            ),
        )
        return ctx

    def escalate_for_conflict_resolution(self,
                                         path_selection: JTACPathSelection
                                         ) -> ConflictResolution:
        """Return the ConflictResolution payload for a path selection whose
        requires_authority_resolution is True. Pulled from the pending-conflicts
        cache populated by build_path_selection. Writes a compliance-log entry.
        """
        conflict_id = path_selection.conflict_id
        if conflict_id is None:
            raise RuntimeError(
                f"[{self.role_id}] escalate_for_conflict_resolution called on a "
                f"path_selection with no conflict_id. build_path_selection must "
                f"run before escalation."
            )
        pending = getattr(self, "_pending_conflicts", {}) or {}
        conflict = pending.get(path_selection.task_id)
        if conflict is None:
            # Rebuild from registry if the cache has been lost (e.g. after a
            # pause+resume round trip). detect_conflict is idempotent.
            path = self.select_path_by_id(path_selection.selected_path_id)
            conflict = self.detect_conflict(
                path=path,
                regulatory_context={"conflict_id_hint": conflict_id},
                task_id=path_selection.task_id,
            )
            if conflict is None:
                # Fallback: registry may have changed. Build a minimal ConflictResolution
                # so C2 still gets a payload referencing the original conflict_id.
                self._ensure_conflicts_loaded()
                entry = self._conflict_registry.get(conflict_id, {})
                conflict = ConflictResolution(
                    task_id=path_selection.task_id,
                    conflict_id=conflict_id,
                    conflict_summary=entry.get("summary", "").strip(),
                    requires_compliance_authority=(
                        "compliance" in entry.get("resolution_authority", [])
                    ),
                    requires_legal_authority=(
                        "legal" in entry.get("resolution_authority", [])
                    ),
                )
        self._log_escalation(
            task_id=path_selection.task_id,
            event_type="JTAC_CONFLICT_HALT",
            detail=(
                f"conflict_id={conflict_id} "
                f"path={path_selection.selected_path_id}"
            ),
        )
        return conflict

    # ─────────────────────────────────────────────────────────────────────────
    # INTERNAL LOGGING
    # ─────────────────────────────────────────────────────────────────────────

    def _log_escalation(self, task_id: str, event_type: str, detail: str) -> None:
        """Write a role-scoped compliance-log entry. Each concrete JTAC role's
        log key lives in aureon_state under c2_j_<suffix>_log. Concrete roles
        define self._compliance_log_key at __init__; default is
        c2_j_<role_id>_log if not explicitly set."""
        ts = datetime.now(timezone.utc).isoformat()
        log_key = getattr(self, "_compliance_log_key", None) or (
            "c2_j_" + self.role_id.replace("-", "_").lower() + "_log"
        )
        entry = {
            "ts":                 ts,
            "task_id":            task_id,
            "role_id":            self.role_id,
            "event_type":         event_type,
            "detail":             detail,
            "doctrine_version":   self._state.get("doctrine_version", "unknown"),
        }
        with self._lock:
            log = self._state.setdefault(log_key, [])
            log.insert(0, entry)
            if len(log) > 500:
                self._state[log_key] = log[:500]
