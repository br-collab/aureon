"""Tests for the Thifur-H security hardening.

Written because a patch to a live-order path that nobody exercised would be
its own finding. These do not touch Kraken, do not start the server, and do
not require credentials - they test the guard logic and the cash floor
directly.

Run: python3 test_security_hardening.py
"""

from __future__ import annotations

import os
import sys

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}   {detail}")
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# The exposure policy: increases require the key, reductions do not
# ---------------------------------------------------------------------------


def test_route_gating_policy() -> None:
    print("\nexposure policy")
    src = open("server.py", encoding="utf-8").read()

    must_be_gated = {
        "thifur_h_start_session": "builds the live Kraken client",
        "thifur_h_generate_signal": "queries live price, stages an order",
        "thifur_h_approve_signal": "submits a real order",
        "thifur_h_rollback": "cancels a caller-supplied txid",
        "thifur_h_auto_close_arm": "arms autonomous execution",
        "thifur_h_balance": "discloses the live account balance",
    }
    for fn, why in must_be_gated.items():
        idx = src.find(f"def {fn}(")
        body = src[idx:idx + 900]
        check(f"{fn} is gated ({why})", "_thifur_guard(" in body)

    must_stay_open = {
        "thifur_h_kill_switch": "cancels all orders - only reduces exposure",
        "thifur_h_auto_close_disarm": "disarms - only reduces exposure",
    }
    for fn, why in must_stay_open.items():
        idx = src.find(f"def {fn}(")
        body = src[idx:idx + 900]
        check(f"{fn} stays open ({why})", "_thifur_guard(" not in body)


# ---------------------------------------------------------------------------
# The guard itself
# ---------------------------------------------------------------------------


def test_guard_semantics() -> None:
    print("\nguard semantics")
    src = open("server.py", encoding="utf-8").read()
    guard = src[src.find("def _thifur_guard("):]
    guard = guard[:guard.find("\n@app.route")]

    check("guard requires the admin key", "_require_admin_key()" in guard)
    check("guard consults halt_active", 'aureon_state.get("halt_active"' in guard)
    check("unauthorized is 401", "401" in guard)
    check("halted is 423", "423" in guard)
    check(
        "the key is checked before the halt, so an anonymous caller cannot "
        "enumerate halt state",
        guard.find("_require_admin_key") < guard.find("halt_active"),
    )


def test_auto_close_is_bounded() -> None:
    print("\nauto-close bounds")
    src = open("server.py", encoding="utf-8").read()
    check("a minutes ceiling exists", "_AUTO_CLOSE_MAX_MINUTES" in src)
    check("a cycles ceiling exists", "_AUTO_CLOSE_MAX_CYCLES" in src)
    check(
        "the cycles ceiling does not exceed the doctrine's own order cap",
        "_AUTO_CLOSE_MAX_CYCLES: int = 20" in src,
    )
    body = src[src.find("def thifur_h_auto_close_arm("):][:2400]
    check("non-numeric input is caught", "except (TypeError, ValueError)" in body)
    check("bad input is a 400, not a 500", "400" in body)


# ---------------------------------------------------------------------------
# The halt reaches the engine, which is what the loop needs
# ---------------------------------------------------------------------------


def test_halt_reaches_the_engine() -> None:
    print("\nhalt propagation")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from aureon.thifur.thifur_h import ThifurH

    import inspect
    sig = inspect.signature(ThifurH.__init__)
    check("ThifurH accepts halt_check", "halt_check" in sig.parameters)
    check(
        "halt_check defaults to None so existing callers are unchanged",
        sig.parameters["halt_check"].default is None,
    )

    src = inspect.getsource(ThifurH)
    for method in ("process_signal", "process_close_signal"):
        m = src[src.find(f"def {method}("):]
        m = m[:m.find("\n    def ", 10)] if "\n    def " in m[10:] else m
        check(f"{method} checks the halt", "self.halt_check" in m)
        check(
            f"{method} checks the halt before running gates",
            m.find("self.halt_check") < (
                m.find("run_all_gates") if "run_all_gates" in m else len(m)
            ),
        )

    server_src = open("server.py", encoding="utf-8").read()
    check(
        "the live engine is constructed with the halt bound",
        "engine.halt_check = lambda" in server_src,
    )


def test_halt_blocks_a_signal_without_touching_an_exchange() -> None:
    print("\nhalt behaviour (no exchange involved)")
    from aureon.thifur.thifur_h import ThifurH, SessionState

    engine = ThifurH.__new__(ThifurH)
    engine.halt_check = lambda: True

    class _Ledger:
        state = SessionState.ACTIVE
        dsor_entries: list = []
        session_id = "TEST"

    engine.ledger = _Ledger()
    engine.session_id = "TEST"
    engine._dsor = lambda *a, **k: None

    class _Signal:
        signal_id = "SIG-1"
        symbol = "XBTUSD"
        side = "buy"
        suggested_price = 100.0
        suggested_qty = 0.0001

    result = engine.process_signal(_Signal())
    check("a halted engine blocks the signal", result.get("result") == "BLOCKED")
    check(
        "the refusal names the halt rather than the session state",
        "Halt" in result.get("reason", ""),
        result.get("reason", ""),
    )


# ---------------------------------------------------------------------------
# The cash floor
# ---------------------------------------------------------------------------


def test_cash_floor() -> None:
    print("\ncash floor")
    from aureon.approval_service.service import _apply_trade

    state = {"cash": 1000.0, "positions": []}
    ok, err = _apply_trade(
        state, {"symbol": "GLD", "shares": 1.0, "asset_class": "ETF", "action": "BUY"}, 100.0
    )
    check("an affordable buy still executes", ok is True, str(err))
    check("cash is reduced correctly", state["cash"] == 900.0, str(state["cash"]))

    ok, err = _apply_trade(
        state, {"symbol": "GLD", "shares": 100.0, "asset_class": "ETF", "action": "BUY"}, 100.0
    )
    check("an unaffordable buy is refused", ok is False)
    check("the refusal names both figures", err is not None and "900" in err, str(err))
    check("cash is untouched by the refusal", state["cash"] == 900.0)
    check("no position was appended", len(state["positions"]) == 1)

    # The March 2026 shape: sixty buys that should have stopped at the floor.
    state = {"cash": 1000.0, "positions": []}
    executed = 0
    for _ in range(60):
        ok, _err = _apply_trade(
            state, {"symbol": "GLD", "shares": 1.0, "asset_class": "ETF", "action": "BUY"}, 100.0
        )
        if ok:
            executed += 1
    check("a runaway loop stops at the floor", executed == 10, f"executed={executed}")
    check("cash never goes negative", state["cash"] >= 0, str(state["cash"]))


if __name__ == "__main__":
    print("Thifur-H security hardening")
    print("=" * 60)
    test_route_gating_policy()
    test_guard_semantics()
    test_auto_close_is_bounded()
    test_halt_reaches_the_engine()
    test_halt_blocks_a_signal_without_touching_an_exchange()
    test_cash_floor()
    print("=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        sys.exit(1)
    print("all checks passed")
