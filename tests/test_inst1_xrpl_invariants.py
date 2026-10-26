from xrpl.wallet import Wallet

from aureon.mmf import xrpl_integration as xrpl


def _wallets(monkeypatch):
    investor, share, cash = Wallet.create(), Wallet.create(), Wallet.create()
    monkeypatch.setattr(xrpl, "_get_investor_wallet", lambda _investor_id: investor)
    monkeypatch.setattr(xrpl, "_get_fund_wallets", lambda: (share, cash))
    xrpl._reset_operation_registry_for_tests()
    return investor, share, cash


def _step(label, result="tesSUCCESS", sequence=7, outcome=None):
    return {
        "label": label,
        "tx_hash": f"hash-{label}",
        "ledger_index": 1,
        "ledger_close_time_utc": "2026-10-26T12:00:00+00:00",
        "engine_result": result,
        "sequence": sequence,
        "outcome": outcome or ("SUCCESS" if result == "tesSUCCESS" else "FAILED"),
    }


def test_r_l2_nonfinite_zero_and_negative_inputs_are_invalid(monkeypatch):
    for amount in ("NaN", "Infinity", 0, -1):
        assert xrpl.execute_subscription_dvp("I", amount, 1)["status"] == "INVALID"
    for value in ("NaN", "Infinity", 0, -1):
        assert xrpl.execute_redemption_dvp("I", value, 1)["status"] == "INVALID"
        assert xrpl.execute_redemption_dvp("I", 1, value)["status"] == "INVALID"


def test_r_m2_failure_compensates_offer_and_prefund(monkeypatch):
    _wallets(monkeypatch)
    calls = []

    def submit(label, _tx, _signer):
        calls.append(label)
        if "atomic DvP" in label:
            return _step(label, "tecPATH_PARTIAL")
        return _step(label)

    monkeypatch.setattr(xrpl, "_submit", submit)
    result = xrpl.execute_subscription_dvp("I", "100.25", "2.5")
    assert result["status"] == "REJECTED"
    assert [step["label"] for step in result["compensation_steps"]] == [
        "COMPENSATE OfferCancel",
        "COMPENSATE Clawback pre-fund",
    ]
    assert len(calls) == 5


def test_r_m3_timeout_is_unknown_and_retry_looks_up_without_submit(monkeypatch):
    _wallets(monkeypatch)
    calls = []

    def submit(label, _tx, _signer):
        calls.append(label)
        if "atomic DvP" in label:
            return _step(label, "SUBMIT_TIMEOUT", outcome="UNKNOWN")
        return _step(label)

    monkeypatch.setattr(xrpl, "_submit", submit)
    first = xrpl.execute_subscription_dvp("I", 100, 2)
    assert first["status"] == "UNKNOWN"
    count = len(calls)
    looked_up = []
    monkeypatch.setattr(xrpl, "_lookup_prior_attempt", lambda operation_id, prior: looked_up.append(operation_id) or None)
    second = xrpl.execute_subscription_dvp("I", "100.00", "2.0")
    assert second["status"] == "UNKNOWN"
    assert second["lookup_performed"] is True
    assert looked_up == [first["operation_id"]]
    assert len(calls) == count


def test_r_m3_timeout_at_each_subscription_step_is_unknown(monkeypatch):
    for fail_at in range(3):
        _wallets(monkeypatch)
        index = 0

        def submit(label, _tx, _signer):
            nonlocal index
            current = index
            index += 1
            if current == fail_at:
                return _step(label, "SUBMIT_TIMEOUT", outcome="UNKNOWN")
            return _step(label)

        monkeypatch.setattr(xrpl, "_submit", submit)
        result = xrpl.execute_subscription_dvp(f"I-{fail_at}", 100, 2)
        assert result["status"] == "UNKNOWN"


def test_r_l3_duplicate_economic_identity_submits_nothing(monkeypatch):
    _wallets(monkeypatch)
    calls = []
    monkeypatch.setattr(xrpl, "_submit", lambda label, _tx, _signer: calls.append(label) or _step(label))
    first = xrpl.execute_subscription_dvp("I", "100.0", "2.00")
    count = len(calls)
    second = xrpl.execute_subscription_dvp("I", "100.00", "2")
    assert first["status"] == second["status"] == "COMPLETE"
    assert second["deduplicated"] is True
    assert len(calls) == count
