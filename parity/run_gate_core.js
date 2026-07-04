#!/usr/bin/env node
/**
 * run_gate_core.js — Node side of the Cato parity harness (WS-0.2)
 * =================================================================
 * PURPOSE:    Drive cato-mcp/gate_core.js (the EXACT decision core the
 *             MCP server executes) with the golden vectors and emit
 *             decisions as JSON on stdout for run_parity.py to diff
 *             against the Python twin.
 * INPUTS:     parity/cato_golden_vectors.json
 * OUTPUTS:    JSON array of {id, gate_decision, recommended_rail,
 *             recommended_chain} on stdout.
 * ASSUMPTIONS: Run from The Grid 3 repo root. No network, no deps.
 */

const fs = require("fs");
const path = require("path");

const { computeGateDecision, pickRecommendedChain } = require(
  path.join(__dirname, "..", "cato-mcp", "gate_core.js")
);

const spec = JSON.parse(
  fs.readFileSync(path.join(__dirname, "cato_golden_vectors.json"), "utf8")
);

const results = spec.vectors.map((v) => {
  // SOFR delta computed exactly as the index.js handler computes it
  // from its two FRED observations.
  const sofrDeltaBps =
    v.sofr_rate !== null && v.sofr_prev !== null
      ? Math.abs(v.sofr_rate - v.sofr_prev) * 100
      : null;

  const d = computeGateDecision({
    ofr_stress: v.ofr_stress,
    gas_gwei: v.gas_gwei,
    sofr_delta_bps: sofrDeltaBps,
  });

  return {
    id: v.id,
    gate_decision: d.gate_decision,
    recommended_rail: d.recommended_rail,
    recommended_chain:
      d.gate_decision === "PROCEED" ? pickRecommendedChain(spec.chain_state) : null,
  };
});

process.stdout.write(JSON.stringify(results, null, 2) + "\n");
