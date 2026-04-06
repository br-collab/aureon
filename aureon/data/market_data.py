"""
aureon/data/market_data.py
Twelve Data market data adapter with yfinance fallback.
Reads TWELVE_DATA_API_KEY from environment.
"""

import os
import time
import threading
from datetime import datetime, timezone
from typing import Optional

TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")
_cache: dict = {}
_cache_lock = threading.Lock()
CACHE_TTL_SECONDS = 60  # refresh prices at most once per minute per symbol


def get_price(symbol: str, asset_class: str = "equities") -> Optional[float]:
    """
    Fetch the latest price for a symbol.
    Primary: Twelve Data REST API.
    Fallback: yfinance.
    Returns None if both fail — caller must handle gracefully.
    """
    # Check cache first
    with _cache_lock:
        entry = _cache.get(symbol)
        if entry and (time.time() - entry["ts"]) < CACHE_TTL_SECONDS:
            return entry["price"]

    price = None

    # ── Primary: Twelve Data ──────────────────────────────────────────
    if TWELVE_DATA_API_KEY:
        try:
            from twelvedata import TDClient
            td = TDClient(apikey=TWELVE_DATA_API_KEY)
            data = td.price(symbol=symbol).as_json()
            price = float(data.get("price", 0)) or None
        except Exception as exc:
            print(f"[MARKET_DATA] Twelve Data failed for {symbol}: {exc} — trying fallback")

    # ── Fallback: yfinance ────────────────────────────────────────────
    if price is None:
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        except Exception as exc:
            print(f"[MARKET_DATA] yfinance fallback failed for {symbol}: {exc}")

    # Cache result (even None avoids hammering the API on repeated failures)
    with _cache_lock:
        _cache[symbol] = {"price": price, "ts": time.time()}

    return price


def get_prices_batch(symbols: list) -> dict:
    """
    Fetch prices for multiple symbols in one Twelve Data call.
    Falls back to per-symbol yfinance calls if batch fails.
    Free tier limit: 800 calls/day. Batch counts as one call.
    """
    if not symbols:
        return {}

    results: dict = {}

    # ── Primary: Twelve Data batch ────────────────────────────────────
    if TWELVE_DATA_API_KEY:
        try:
            from twelvedata import TDClient
            td = TDClient(apikey=TWELVE_DATA_API_KEY)
            symbol_str = ",".join(symbols)
            data = td.price(symbol=symbol_str).as_json()
            # Batch response is a dict keyed by symbol
            if isinstance(data, dict):
                for sym, val in data.items():
                    try:
                        results[sym] = float(val.get("price", 0)) or None
                    except Exception:
                        results[sym] = None
            print(f"[MARKET_DATA] Twelve Data batch: {len(results)} prices fetched")
        except Exception as exc:
            print(f"[MARKET_DATA] Twelve Data batch failed: {exc} — falling back per symbol")

    # Fill any missing symbols with yfinance fallback
    missing = [s for s in symbols if s not in results or results[s] is None]
    for sym in missing:
        results[sym] = get_price(sym)

    # Update cache
    ts = time.time()
    with _cache_lock:
        for sym, price in results.items():
            _cache[sym] = {"price": price, "ts": ts}

    return results


def get_data_source_status() -> dict:
    """Return current data source health for dashboard."""
    twelve_ok = bool(TWELVE_DATA_API_KEY)
    return {
        "primary":       "Twelve Data" if twelve_ok else "yfinance (no API key)",
        "fallback":      "yfinance",
        "api_key_set":   twelve_ok,
        "cache_entries": len(_cache),
        "cache_ttl_s":   CACHE_TTL_SECONDS,
    }
