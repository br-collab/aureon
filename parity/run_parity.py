"""
run_parity.py — Cato Parity Principle harness (WS-0.2, AUR-ROADMAP-001)
========================================================================
PURPOSE:    Prove bit-for-bit decision parity between the external Node
            MCP decision core (cato-mcp/gate_core.js — the exact code the
            v0.2.3 server executes) and the in-process Python twin
            (aureon/mcp/cato_client.py::atomic_settlement_gate), per the
            Parity Principle (AUR-CANONICAL-001 §VIII) and the open
            conflict logged in §X.
INPUTS:     parity/cato_golden_vectors.json (15 vectors: boundary-equal,
            boundary-trip, missing-input, Sept 2019, Mar 2020, combos).
OUTPUTS:    Per-vector PASS/FAIL table on stdout; exit 0 only if every
            vector matches on gate_decision, recommended_rail, AND
            recommended_chain across both implementations and against
            the doctrine-expected values.
ASSUMPTIONS: Run from The Grid 3 repo root; node on PATH; no network
            (both sides run on injected inputs only).
AUDIT NOTES: A FAIL here is a doctrine event — parity is doctrine, not
            test hygiene. Do not "fix" expectations to match code; fix
            whichever implementation drifted, and log it in canonical §X.
RUN:        python3 parity/run_parity.py
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from aureon.mcp.cato_client import atomic_settlement_gate  # noqa: E402


def run_python(spec):
    out = []
    for v in spec["vectors"]:
        chain_state = dict(spec["chain_state"])
        chain_state.pop("_doc", None)
        # Vector-specific gas overrides the shared chain_state's ethereum
        # entry; gas_gwei null means the ethereum observation is absent.
        cs = {k: dict(val) for k, val in chain_state.items()}
        if v["gas_gwei"] is None:
            cs["ethereum"] = {"gas_gwei": None}
        else:
            cs["ethereum"] = {"gas_gwei": v["gas_gwei"]}
        r = atomic_settlement_gate(
            sofr_rate=v["sofr_rate"],
            sofr_prev=v["sofr_prev"],
            ofr_stress=v["ofr_stress"],
            chain_state=cs,
            prices={"eth": 2300.0, "sol": 150.0, "source": "golden_vector"},
        )
        out.append({
            "id": v["id"],
            "gate_decision": r["gate_decision"],
            "recommended_rail": r["recommended_rail"],
            "recommended_chain": r["recommended_chain"],
        })
    return out


class ParityUnavailable(Exception):
    """Raised when the Node decision core this harness compares against
    is not present, so no parity verdict — pass or fail — can be issued."""


def run_node():
    core = os.path.join(ROOT, "cato-mcp", "gate_core.js")
    if not os.path.exists(core):
        raise ParityUnavailable(
            f"the Node decision core is absent ({core} does not exist). "
            "cato-mcp is not vendored into this repository."
        )
    proc = subprocess.run(
        ["node", os.path.join(HERE, "run_gate_core.js")],
        capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


def main():
    with open(os.path.join(HERE, "cato_golden_vectors.json")) as fh:
        spec = json.load(fh)

    py = {r["id"]: r for r in run_python(spec)}
    try:
        nd = {r["id"]: r for r in run_node()}
    except ParityUnavailable as exc:
        print(f"PARITY NOT ASSESSED - {exc}")
        print("The fifteen vectors were not compared. Do not record this as a pass.")
        sys.exit(2)

    fields = ("gate_decision", "recommended_rail", "recommended_chain")
    failures = 0
    print(f"{'vector':<28} {'python':<28} {'node':<28} {'doctrine':<20} verdict")
    print("-" * 112)
    for v in spec["vectors"]:
        vid = v["id"]
        p, n = py[vid], nd[vid]
        expect = dict(v["expect"])
        # recommended_chain expectation only applies to PROCEED vectors
        if expect["gate_decision"] == "PROCEED":
            expect["recommended_chain"] = spec["expected_chain_on_proceed"]
        else:
            expect["recommended_chain"] = None

        impl_match = all(p[f] == n[f] for f in fields)
        doct_match = all(p[f] == expect[f] for f in fields)
        ok = impl_match and doct_match
        failures += 0 if ok else 1

        fmt = lambda r: f"{r['gate_decision']}/{r['recommended_rail']}/{r['recommended_chain']}"
        verdict = "PASS" if ok else ("IMPL-DRIFT" if not impl_match else "DOCTRINE-FAIL")
        print(f"{vid:<28} {fmt(p):<28} {fmt(n):<28} "
              f"{expect['gate_decision'] + '/' + expect['recommended_rail']:<20} {verdict}")

    print("-" * 112)
    if failures:
        print(f"[FAIL] {failures} vector(s) diverged — Parity Principle violated. "
              "This is a doctrine event: fix the drifted implementation, log in canonical §X.")
        sys.exit(1)
    print(f"[PASS] {len(spec['vectors'])} vectors — Node core and Python twin "
          "produce identical decisions; both match doctrine expectations.")


if __name__ == "__main__":
    main()
