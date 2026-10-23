"""CATO-D2 primary-source and fail-closed checks for the Aureon twin."""

import io
import json

import server


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_nyfed_sofr_parser_uses_primary_schema(monkeypatch):
    payload = {
        "refRates": [
            {"effectiveDate": "2026-10-22", "percentRate": "3.91"},
            {"effectiveDate": "2026-10-21", "percentRate": 3.90},
        ]
    }
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return _Response(json.dumps(payload).encode())

    monkeypatch.setattr(server.urllib.request, "urlopen", fake_urlopen)
    observations = server._nyfed_reference_rate_recent("sofr", count=2)

    assert seen == {"url": "https://markets.newyorkfed.org/api/rates/secured/sofr/last/2.json", "timeout": 6}
    assert observations == [
        {"date": "2026-10-22", "value": 3.91},
        {"date": "2026-10-21", "value": 3.90},
    ]


def test_nyfed_sofr_parser_refuses_missing_or_malformed_readings(monkeypatch):
    monkeypatch.setattr(
        server.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(json.dumps({"refRates": [{"effectiveDate": "", "percentRate": None}]}).encode()),
    )
    try:
        server._nyfed_reference_rate_recent("sofr", count=2)
    except ValueError as error:
        assert "no usable New York Fed values" in str(error)
    else:
        raise AssertionError("unavailable primary SOFR must refuse rather than return a proxy")


def test_cato_refresh_does_not_substitute_fed_funds_for_missing_sofr(monkeypatch):
    monkeypatch.setattr(server, "_nyfed_reference_rate_recent", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(server, "_log_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "_cato_fetch_coingecko_prices", lambda: {"eth": 1.0, "sol": 1.0})
    monkeypatch.setattr(server, "_cato_build_chain_state", lambda prices: {})
    monkeypatch.setitem(server._fred_cache, "data", {"fed_funds": 99.0})
    monkeypatch.setitem(server._ofr_cache, "data", None)

    server._cato_refresh_inputs()

    assert server._cato_input_cache["sofr_rate"] is None
    assert server._cato_input_cache["sofr_prev"] is None
