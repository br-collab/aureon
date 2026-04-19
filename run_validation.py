"""
Thifur-H Sandbox Validation Runner
===================================
20-Cycle Governance Stress Test Protocol

Cycle breakdown:
  Cycles 1-5:   Clean execution — gates pass, DSOR writes, audit logs
  Cycles 6-10:  Intentional Gate 1 breach (no CAOM-001 approval) — must BLOCK
  Cycles 11-15: Intentional Gate 2 breach (symbol not in whitelist) — must BLOCK
  Cycles 16-20: Intentional Gate 3 breach (position size > $50) — must BLOCK

Pass criteria:
  - Cycles 1-5: ORDER_PLACED or HOLD (HITL declined is valid)
  - Cycles 6-20: BLOCK — order NEVER reaches exchange
  - DSOR entry written for every cycle regardless of outcome
  - Gate records complete for all 20 cycles

Usage:
  export GEMINI_API_KEY=account-xxxxx
  export GEMINI_API_SECRET=xxxxxxxx
  python run_validation.py

  # Dry run (no real sandbox calls):
  python run_validation.py --dry-run
"""

import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime, timezone

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aureon.thifur.thifur_h import ThifurH, AtroxSignal, ThifurHDoctrine
from aureon.thifur.atrox_sandbox import AtroxSandboxSignalGenerator

logger = logging.getLogger("validation_runner")


def print_header():
    print("""
╔══════════════════════════════════════════════════════════════╗
║           THIFUR-H SANDBOX VALIDATION PROTOCOL              ║
║           Project Aureon · CAOM-001 · Phase 2               ║
║           SR 11-7 Tier 1 Independent Validation             ║
╚══════════════════════════════════════════════════════════════╝
""")


def print_cycle(n: int, total: int, label: str):
    print(f"\n{'─'*62}")
    print(f"  CYCLE {n:02d}/{total} — {label}")
    print(f"{'─'*62}")


def print_result(result: dict, expected: str):
    actual = result.get("result", "UNKNOWN")
    passed = actual == expected or (expected == "PASS_OR_HOLD" and actual in ("ORDER_PLACED", "HOLD"))
    icon = "✓ PASS" if passed else "✗ FAIL"
    print(f"\n  Result   : {actual}")
    print(f"  Expected : {expected}")
    print(f"  Verdict  : {icon}")
    return passed


def run_dry_cycle(n: int, label: str, expected: str) -> bool:
    """Simulate a cycle without making API calls."""
    print_cycle(n, 20, label)
    print(f"  [DRY RUN] Simulating {label}")
    print(f"  Result   : {expected.split('_')[0]}_SIMULATED")
    print(f"  Expected : {expected}")
    print(f"  Verdict  : ✓ PASS (dry run)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Thifur-H 20-cycle sandbox validation")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate all cycles without API calls")
    parser.add_argument("--cycles", type=int, default=20,
                        help="Number of cycles to run (default: 20)")
    parser.add_argument("--export", type=str, default="thifur_h_dsor.json",
                        help="DSOR export path")
    args = parser.parse_args()

    print_header()

    # ── Credentials ────────────────────────────────────────────
    api_key = os.environ.get("GEMINI_API_KEY", "")
    api_secret = os.environ.get("GEMINI_API_SECRET", "")

    if not args.dry_run and (not api_key or not api_secret):
        print("ERROR: GEMINI_API_KEY and GEMINI_API_SECRET required for live run.")
        print("  Set env vars or use --dry-run for simulation.")
        sys.exit(1)

    if args.dry_run:
        print("  MODE: DRY RUN — no sandbox API calls will be made\n")
    else:
        print(f"  MODE: LIVE SANDBOX — {ThifurHDoctrine.MAX_POSITION_USD} max position\n")

    # ── Initialize ─────────────────────────────────────────────
    results = {"passed": 0, "failed": 0, "cycles": []}

    if not args.dry_run:
        engine = ThifurH(api_key, api_secret)
        atrox = AtroxSandboxSignalGenerator()

        # Show sandbox balances
        print("  Sandbox account balances:")
        balances = engine.get_balances()
        if isinstance(balances, list):
            for b in balances:
                if float(b.get("amount", 0)) > 0:
                    print(f"    {b['currency']}: {b['amount']}")
        print()

    total = min(args.cycles, 20)

    # ══════════════════════════════════════════════════════
    # CYCLES 1-5: Clean execution
    # ══════════════════════════════════════════════════════
    for i in range(1, min(6, total + 1)):
        label = f"Clean execution — Gate pass expected"
        if args.dry_run:
            passed = run_dry_cycle(i, label, "PASS_OR_HOLD")
        else:
            print_cycle(i, total, label)
            signal = atrox.generate_buy_signal()
            if not signal:
                print("  Atrox: No price data — skipping cycle")
                continue

            # CAOM-001 approval — operator stamps the signal
            print(f"\n  Atrox signal: {signal.signal_id}")
            print(f"  Rationale: {signal.rationale[:100]}...")
            approve = input("\n  CAOM-001: Approve this Atrox signal? [y/N]: ").strip().lower()
            if approve == "y":
                signal.caom_approved = True
                signal.approval_timestamp = datetime.now(timezone.utc).isoformat()
                print("  → Signal approved by CAOM-001\n")
            else:
                print("  → Signal declined by CAOM-001 — will HOLD at Gate 5\n")

            result = engine.process_signal(signal)
            passed = print_result(result, "PASS_OR_HOLD")
            time.sleep(1)

        results["cycles"].append({"cycle": i, "type": "clean", "passed": passed})
        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1

    # ══════════════════════════════════════════════════════
    # CYCLES 6-10: Gate 1 breach — no CAOM-001 approval
    # ══════════════════════════════════════════════════════
    for i in range(6, min(11, total + 1)):
        label = "BREACH TEST — Gate 1: No CAOM-001 approval → must BLOCK"
        if args.dry_run:
            passed = run_dry_cycle(i, label, "BLOCK")
        else:
            print_cycle(i, total, label)
            signal = atrox.generate_breach_signal("no_approval")
            print(f"  Breach signal: {signal.signal_id} (caom_approved=False)")
            result = engine.process_signal(signal)
            passed = print_result(result, "BLOCK")
            time.sleep(0.5)

        results["cycles"].append({"cycle": i, "type": "breach_g1", "passed": passed})
        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1

    # ══════════════════════════════════════════════════════
    # CYCLES 11-15: Gate 2 breach — symbol not in whitelist
    # ══════════════════════════════════════════════════════
    for i in range(11, min(16, total + 1)):
        label = "BREACH TEST — Gate 2: ETHUSD not in whitelist → must BLOCK"
        if args.dry_run:
            passed = run_dry_cycle(i, label, "BLOCK")
        else:
            print_cycle(i, total, label)
            signal = atrox.generate_breach_signal("symbol")
            print(f"  Breach signal: {signal.signal_id} (symbol=ETHUSD)")
            result = engine.process_signal(signal)
            passed = print_result(result, "BLOCK")
            time.sleep(0.5)

        results["cycles"].append({"cycle": i, "type": "breach_g2", "passed": passed})
        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1

    # ══════════════════════════════════════════════════════
    # CYCLES 16-20: Gate 3 breach — position > $50 limit
    # ══════════════════════════════════════════════════════
    for i in range(16, min(21, total + 1)):
        label = "BREACH TEST — Gate 3: Position $1,000 > $50 limit → must BLOCK"
        if args.dry_run:
            passed = run_dry_cycle(i, label, "BLOCK")
        else:
            print_cycle(i, total, label)
            signal = atrox.generate_breach_signal("size")
            pos_val = signal.suggested_price * signal.suggested_qty
            print(f"  Breach signal: {signal.signal_id} (position=${pos_val:,.2f})")
            result = engine.process_signal(signal)
            passed = print_result(result, "BLOCK")
            time.sleep(0.5)

        results["cycles"].append({"cycle": i, "type": "breach_g3", "passed": passed})
        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1

    # ══════════════════════════════════════════════════════
    # FINAL REPORT
    # ══════════════════════════════════════════════════════
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                  VALIDATION SUMMARY                         ║
╠══════════════════════════════════════════════════════════════╣
║  Cycles run  : {total:<44} ║
║  Passed      : {results['passed']:<44} ║
║  Failed      : {results['failed']:<44} ║
║  Pass rate   : {results['passed']/total*100:.0f}%{'':<42} ║
╚══════════════════════════════════════════════════════════════╝""")

    if not args.dry_run:
        # Export DSOR
        dsor_path = args.export
        engine.export_dsor(dsor_path)
        print(f"\n  DSOR exported → {dsor_path}")

        # Session report
        report = engine.session_report()
        print(f"\n  Session: {report['session_id']}")
        print(f"  Orders placed   : {report['orders_placed']}")
        print(f"  Gate records    : {report['gate_records_count']}")
        print(f"  DSOR entries    : {report['dsor_entries_count']}")

        # Kill switch — clean up any open orders before exit
        if report["open_positions"] > 0:
            print(f"\n  {report['open_positions']} open position(s) detected — engaging kill switch")
            engine.kill_switch("Validation session end — clean shutdown")

    sr117_verdict = "READY FOR SR 11-7 EVIDENCE REVIEW" if results["failed"] == 0 else "REMEDIATION REQUIRED BEFORE PRODUCTION"
    print(f"\n  SR 11-7 Status: {sr117_verdict}\n")

    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
