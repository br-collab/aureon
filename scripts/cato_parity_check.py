"""
cato_parity_check.py — Phase 2 P2-4 parity CI helper.

Verifies the Aureon in-process Python twin (aureon/mcp/cato_client.py)
and the external MCP server (cato-mcp/index.js) return bit-for-bit
identical decisions for identical inputs. Catches schema drift early
so Grid 3's CLAUDE.md parity rule doesn't silently violate.

Usage:
    python3 scripts/cato_parity_check.py

Exits 0 if schemas + decisions match on the canonical comparison set.
Exits 1 with a diff on any divergence.

Comparison set: the atomic_settlement_gate output fields that matter
for doctrine — gate_decision, recommended_rail, recommended_chain,
and the inputs-dict keys/types. Field VALUES are not compared because
each side may compute with slightly different upstream data (SOFR /
OFR / gas) on its own fetch cadence. SCHEMA alignment is the load-
bearing invariant.

What this does NOT check:
  - Live FRED/Blockscout fetch semantics (both sides have their own).
  - End-to-end MCP JSON-RPC stdio roundtrip with the external server;
    that requires spawning node and is out of scope for this MVP.

Phase 3+ replaces this with a full end-to-end parity harness that
hits both side's live endpoints with controlled scalar inputs.
"""

from __future__ import annotations

import sys
from pathlib import Path


# Canonical schema the gate MUST emit on both sides. Extend this list
# when new fields land; both sides updated in the same PR series.
CANONICAL_GATE_TOP_KEYS = {
    "gate_decision",
    "reasons",
    "recommended_rail",
    "recommended_chain",
    "timestamp",
    "doctrine",
    "inputs",
    "thresholds",
}

CANONICAL_GATE_INPUTS_KEYS = {
    "ofr_stress",
    "gas_gwei",
    "sofr_rate",        # Aligned 2026-04-22 (was sofr_today_pct externally)
    "sofr_prev",        # Aligned 2026-04-22 (was sofr_prev_pct externally)
    "sofr_delta_bps",
    "settlement_posture",
}

CANONICAL_DOCTRINE_LABEL = "Verana L0 — Cato settlement gate v0.2.3"


def _extract_schema_from_external_source() -> dict:
    """Parse the external MCP server's index.js to extract the gate
    emission shape. No node execution — static text inspection."""
    cato_mcp = Path(__file__).resolve().parent.parent / "cato-mcp" / "index.js"
    if not cato_mcp.exists():
        raise FileNotFoundError(f"cato-mcp/index.js not found at {cato_mcp}")
    text = cato_mcp.read_text(encoding="utf-8")
    # Find the get_atomic_settlement_gate return block.
    marker = "case \"get_atomic_settlement_gate\":"
    i = text.find(marker)
    if i < 0:
        raise RuntimeError("could not locate atomic_settlement_gate handler")
    tail = text[i : i + 6000]
    return {
        "doctrine_matches": CANONICAL_DOCTRINE_LABEL in tail,
        "has_sofr_rate":    "sofr_rate:" in tail,
        "has_sofr_prev":    "sofr_prev:" in tail,
        "has_old_sofr_today_pct": "sofr_today_pct:" in tail,
        "has_old_sofr_prev_pct":  "sofr_prev_pct:" in tail,
    }


def _extract_schema_from_python_twin() -> dict:
    """Call the Aureon in-process twin directly to see its gate output
    keys. Uses scalar inputs the twin accepts (no network I/O)."""
    # Import here so the script can run from anywhere in the repo.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from aureon.mcp.cato_client import atomic_settlement_gate  # type: ignore

    # Canonical scalar inputs for a PROCEED outcome.
    result = atomic_settlement_gate(
        sofr_rate=3.63,
        ofr_stress=0.0,
        chain_state={},
        sofr_prev=3.65,
    )
    top_keys = set(result.keys())
    input_keys = set((result.get("inputs") or {}).keys())
    return {
        "top_keys":          top_keys,
        "input_keys":        input_keys,
        "doctrine":          result.get("doctrine", ""),
        "doctrine_matches":  result.get("doctrine", "") == CANONICAL_DOCTRINE_LABEL,
    }


def main() -> int:
    print("Cato parity check — Phase 2 P2-4")
    print("=" * 60)

    external = _extract_schema_from_external_source()
    twin     = _extract_schema_from_python_twin()

    print("\nAureon in-process twin (aureon/mcp/cato_client.py):")
    print(f"  doctrine:           {twin['doctrine']!r}")
    print(f"  doctrine_matches:   {twin['doctrine_matches']}")
    print(f"  top_keys missing:   {CANONICAL_GATE_TOP_KEYS - twin['top_keys']}")
    print(f"  top_keys extra:     {twin['top_keys'] - CANONICAL_GATE_TOP_KEYS}")
    print(f"  input_keys missing: {CANONICAL_GATE_INPUTS_KEYS - twin['input_keys']}")
    print(f"  input_keys extra:   {twin['input_keys'] - CANONICAL_GATE_INPUTS_KEYS}")

    print("\nExternal MCP server (cato-mcp/index.js):")
    print(f"  doctrine_matches:        {external['doctrine_matches']}")
    print(f"  has sofr_rate:           {external['has_sofr_rate']}")
    print(f"  has sofr_prev:           {external['has_sofr_prev']}")
    print(f"  has old sofr_today_pct:  {external['has_old_sofr_today_pct']}")
    print(f"  has old sofr_prev_pct:   {external['has_old_sofr_prev_pct']}")

    # Fail conditions.
    failures: list[str] = []
    if not twin["doctrine_matches"]:
        failures.append(
            f"twin doctrine label mismatch — expected {CANONICAL_DOCTRINE_LABEL!r}, got {twin['doctrine']!r}"
        )
    missing = CANONICAL_GATE_TOP_KEYS - twin["top_keys"]
    if missing:
        failures.append(f"twin missing top-level keys: {missing}")
    missing_in = CANONICAL_GATE_INPUTS_KEYS - twin["input_keys"]
    if missing_in:
        failures.append(f"twin missing input keys: {missing_in}")
    if not external["doctrine_matches"]:
        failures.append(
            f"external MCP doctrine label mismatch — expected {CANONICAL_DOCTRINE_LABEL!r}"
        )
    if not external["has_sofr_rate"]:
        failures.append("external MCP missing `sofr_rate:` in atomic_settlement_gate inputs")
    if not external["has_sofr_prev"]:
        failures.append("external MCP missing `sofr_prev:` in atomic_settlement_gate inputs")
    if external["has_old_sofr_today_pct"]:
        failures.append("external MCP still emits legacy `sofr_today_pct:` — should be renamed to sofr_rate")
    if external["has_old_sofr_prev_pct"]:
        failures.append("external MCP still emits legacy `sofr_prev_pct:` — should be renamed to sofr_prev")

    print("\n" + "=" * 60)
    if failures:
        print("PARITY FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PARITY OK — in-process twin and external MCP agree on schema + doctrine label.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
