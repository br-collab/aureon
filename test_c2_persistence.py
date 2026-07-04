"""
test_c2_persistence.py — WS-0.1 (AUR-ROADMAP-001)
==================================================
PURPOSE:    Prove that full C2 coordination state — dashboard logs AND the
            internal registers (_tasks / _handoff_log / _lineage) — survives
            a save_state() → process death → load_state() → restore cycle.
            This is the cross-restart replay demonstration named as the
            WS-0.1 exit criterion (TRACKERS "C2 log persistence gap").
INPUTS:     None (synthetic lifecycle packet; tmp state file).
OUTPUTS:    Exit 0 on pass; assertion failure with diagnostics otherwise.
ASSUMPTIONS: Runs from The Grid 3 repo root (aureon package importable).
AUDIT NOTES: Simulated restart = new ThifurC2 instance + fresh state dict.
            No network, no venue, no market action — coordination only.
RUN:        python3 test_c2_persistence.py
"""

import json
import os
import tempfile
import threading

from aureon.agents.c2.coordinator import ThifurC2, AGENT_J, AGENT_R
from aureon.persistence.store import save_state, load_state


def _mk_packet():
    return {
        "id": "DEC-TEST-0001",
        "symbol": "TEST",
        "action": "BUY",
        "notional": 1_000_000,
        "asset_class": "equity",
    }


def main():
    # ── Phase 1: "first boot" — build coordination state ─────────────
    state_a, lock_a = {}, threading.Lock()
    c2a = ThifurC2(state_a, lock_a)

    task_id = c2a.issue_task(_mk_packet(), agents=[AGENT_J, AGENT_R],
                             doctrine_version="1.6-test")
    c2a.handoff(task_id, from_agent=AGENT_J, to_agent=AGENT_R,
                object_state={"stage": "post-approval"},
                handoff_reason="test J→R settlement handoff")

    c2a.mirror_registers_into_state()

    with lock_a:
        assert state_a["c2_task_log"], "dashboard task log empty before save"
        assert state_a["c2_handoff_log"], "dashboard handoff log empty before save"
        regs = state_a["c2_registers"]
        assert task_id in regs["tasks"], "registers missing task before save"
        assert len(regs["handoff_log"]) == 1, "registers missing handoff before save"

    # ── Phase 2: save to disk (as _save_state does) ──────────────────
    tmp = tempfile.mkdtemp()
    state_file = os.path.join(tmp, "aureon_state_test.json")
    save_state(state=state_a, lock=lock_a, state_file=state_file,
               resolve_mmf_provider=lambda p=None: p or "none",
               log_error=lambda lvl, src, msg: print(f"[{lvl}] {src}: {msg}"))
    assert os.path.exists(state_file), "state file not written"

    # JSON round-trip integrity of the persisted keys
    with open(state_file) as fh:
        snap_raw = json.load(fh)
    for key in ("c2_task_log", "c2_handoff_log", "c2_lineage_log", "c2_registers"):
        assert key in snap_raw, f"persisted snapshot missing {key}"

    # ── Phase 3: "restart" — fresh state, fresh C2, restore ──────────
    snapshot = load_state(state_file=state_file,
                          log_error=lambda lvl, src, msg: print(f"[{lvl}] {src}: {msg}"))
    assert snapshot is not None, "load_state returned None"

    state_b, lock_b = {}, threading.Lock()
    # rehydrate dashboard logs exactly as run_doctrine_stack does
    state_b["c2_task_log"]    = snapshot.get("c2_task_log", [])
    state_b["c2_handoff_log"] = snapshot.get("c2_handoff_log", [])
    state_b["c2_lineage_log"] = snapshot.get("c2_lineage_log", [])

    c2b = ThifurC2(state_b, lock_b)
    restored = c2b.restore_registers(snapshot.get("c2_registers"))
    assert restored is True, "restore_registers returned False on valid payload"

    # ── Phase 4: replay assertions across the "deploy boundary" ──────
    with c2b._c2_lock:
        task_b = c2b._tasks.get(task_id)
    assert task_b is not None, "task lost across restart"
    assert task_b["doctrine_version"] == "1.6-test", "doctrine stamp lost"
    assert task_b["agent_states"].get(AGENT_R) == "ISSUED", "agent state lost"
    with c2b._c2_lock:
        assert len(c2b._handoff_log) == 1, "handoff record lost across restart"
        h = c2b._handoff_log[0]
    assert h["task_id"] == task_id and h["from_agent"] == AGENT_J \
        and h["to_agent"] == AGENT_R, "handoff content corrupted"
    assert state_b["c2_task_log"][0]["task_id"] == task_id, "dashboard log lost"

    # empty/legacy payloads must not restore (pre-WS-0.1 snapshots)
    c2c = ThifurC2({}, threading.Lock())
    assert c2c.restore_registers(None) is False
    assert c2c.restore_registers({}) is False

    print("\n[PASS] WS-0.1 — full C2 coordination state survives restart: "
          f"task {task_id}, 1 handoff, dashboard logs intact.")


if __name__ == "__main__":
    main()
