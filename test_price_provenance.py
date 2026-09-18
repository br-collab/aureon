"""W2-ADD-03: a fill records where its price came from, not only when.

The paper venue books a position at whatever price it observes. Until now the
fill recorded `price_source: "aureon market-data cache"`, which is true of every
price and therefore says nothing: it does not distinguish a Twelve Data reading
from a random walk.

`_simulated_prices` has three strategies — a cached real price with a micro
nudge, a fresh fetch from Twelve Data or Yahoo Finance, and a pure random walk
when both are unreachable — and a single tick can mix them, because a fetch that
returns some symbols carries the rest forward. Railway has no
`TWELVE_DATA_API_KEY`, so the random walk is not hypothetical.

So provenance is recorded **per symbol**, travels into the fill, the booked
trade and the operator's confirmation, and a simulated price says so.

Run: pytest -q test_price_provenance.py
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("RAILWAY_VOLUME_MOUNT_PATH", tempfile.mkdtemp(prefix="aureon-price-test-"))

import server  # noqa: E402


@pytest.fixture
def clean_cache(monkeypatch):  # type: ignore[no-untyped-def]
    """No warm cache, and no network: each test chooses the strategy."""
    monkeypatch.setattr(server, "_price_cache", {}, raising=False)
    monkeypatch.setattr(server, "_price_cache_ts", 0.0, raising=False)
    monkeypatch.setattr(server, "_price_provenance", {}, raising=False)
    monkeypatch.setattr(server, "_fetch_twelve_data_prices", dict)
    monkeypatch.setattr(server, "_fetch_yahoo_prices", dict)
    yield


def test_a_pure_random_walk_is_recorded_as_simulation(clean_cache) -> None:
    prices = server._simulated_prices()
    assert prices, "the tick produced no prices"
    for symbol in prices:
        entry = server._price_provenance[symbol]
        assert entry["source"] == "simulation"
        assert entry["observed_at"] is None, "a random walk is not an observation"


def test_a_fresh_fetch_is_recorded_with_its_publisher(clean_cache, monkeypatch) -> None:
    sample = dict(list(server.BASE_PRICES.items())[:2])
    monkeypatch.setattr(server, "_fetch_twelve_data_prices", lambda: dict(sample))

    server._simulated_prices()

    for symbol in sample:
        entry = server._price_provenance[symbol]
        assert entry["source"] == "twelve_data"
        assert entry["observed_at"] is not None
    carried = [s for s in server.BASE_PRICES if s not in sample]
    assert server._price_provenance[carried[0]]["source"] == "carried_forward", (
        "a symbol the fetch did not return is carried forward, and must say so"
    )


def test_yahoo_is_named_when_twelve_data_returns_nothing(clean_cache, monkeypatch) -> None:
    sample = dict(list(server.BASE_PRICES.items())[:1])
    monkeypatch.setattr(server, "_YFINANCE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(server, "_fetch_yahoo_prices", lambda: dict(sample))

    server._simulated_prices()

    assert server._price_provenance[next(iter(sample))]["source"] == "yfinance"


def test_a_nudged_cache_hit_keeps_the_reading_time(clean_cache, monkeypatch) -> None:
    import time

    filled_at = time.time() - 10
    monkeypatch.setattr(server, "_price_cache", dict(server.BASE_PRICES), raising=False)
    monkeypatch.setattr(server, "_price_cache_ts", filled_at, raising=False)

    server._simulated_prices()

    entry = server._price_provenance[next(iter(server.BASE_PRICES))]
    assert entry["source"] == "cached_nudged"
    observed = datetime.fromisoformat(entry["observed_at"])
    assert abs((observed - datetime.fromtimestamp(filled_at, timezone.utc)).total_seconds()) < 1, (
        "the observation time is when the publisher was read, not when the tick ran"
    )


# ── The venue and the record ────────────────────────────────────────────────────


@pytest.fixture
def state(monkeypatch):  # type: ignore[no-untyped-def]
    now = datetime.now(timezone.utc)
    monkeypatch.setitem(server.aureon_state, "prices", {"TEST": 101.5})
    monkeypatch.setitem(server.aureon_state, "prices_observed_at", now.isoformat())
    return now


def test_the_venue_reports_the_symbols_own_source(state, monkeypatch) -> None:
    reading_at = (state - timedelta(seconds=30)).isoformat()
    monkeypatch.setitem(server.aureon_state, "price_provenance",
                        {"TEST": {"source": "twelve_data", "observed_at": reading_at}})

    observation = server._market_cache_price("TEST")

    assert observation.source == "twelve_data"
    assert observation.observed_at == datetime.fromisoformat(reading_at), (
        "the fill's observation time should be when the publisher was read"
    )


def test_a_simulated_price_is_not_dressed_as_a_market_reading(state, monkeypatch) -> None:
    monkeypatch.setitem(server.aureon_state, "price_provenance",
                        {"TEST": {"source": "simulation", "observed_at": None}})

    observation = server._market_cache_price("TEST")

    assert observation.source == "simulation"
    assert observation.source not in ("aureon market-data cache", "twelve_data", "yfinance")


def test_an_unrecorded_price_says_unrecorded(state, monkeypatch) -> None:
    monkeypatch.setitem(server.aureon_state, "price_provenance", {})
    assert server._market_cache_price("TEST").source == "unrecorded"


def test_the_booked_trade_carries_the_price_source() -> None:
    """The record a person reads later must say what the price was."""
    import pathlib

    consumer = pathlib.Path(server.__file__).parent / "aureon" / "booking" / "consumer.py"
    source = consumer.read_text(encoding="utf-8")
    trade_block = source[source.index("    trade = {"):source.index("state.setdefault(\"trades\"")]
    assert '"price_source":' in trade_block, "the booked trade does not record the price source"


def test_the_operator_is_shown_the_price_source() -> None:
    import pathlib
    import re

    index = pathlib.Path(server.__file__).parent / "index.html"
    modal = index.read_text(encoding="utf-8")
    block = modal[modal.index("function showPosttradeModal("):]
    block = block[: block.index("\n}")]
    assert "Price Source" in block, "the post-trade confirmation does not show the price source"
    assert re.search(r"simulated\s*—\s*not a market price", block), (
        "a simulated price is not called out to the operator"
    )
