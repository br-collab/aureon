"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/mcp/alpaca_client.py                                         ║
║  Atrox — Alpaca Market Data Pipe                             ║
║                                                                      ║
║  MANDATE:                                                            ║
║    Baseline equity data, price history, and news feed for            ║
║    Thifur drawdown modeling and signal calibration.                  ║
║                                                                      ║
║  DATA DOMAINS:                                                       ║
║    - Price bars (OHLCV) — intraday and daily                         ║
║    - Latest quotes and trades                                        ║
║    - News feed (company + macro)                                     ║
║    - Market snapshots (aggregated quote + bar)                       ║
║    - Corporate actions / splits                                      ║
║                                                                      ║
║  API: Alpaca Data API v2                                             ║
║  Base URL: https://data.alpaca.markets/v2                            ║
║  Auth: APCA-API-KEY-ID + APCA-API-SECRET-KEY headers                 ║
║  Free tier: IEX real-time data + 15-min delayed SIP                  ║
║                                                                      ║
║  Env vars:                                                           ║
║    ALPACA_API_KEY    — key ID (starts with "PK" for paper)           ║
║    ALPACA_API_SECRET — secret key                                    ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import hashlib
import json
import os
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta
from typing import Optional, List

# ── Alpaca API Config ─────────────────────────────────────────────────────────
ALPACA_DATA_BASE  = "https://data.alpaca.markets/v2"
ALPACA_NEWS_BASE  = "https://data.alpaca.markets/v1beta1"

# ── Atrox Pipe Identity ─────────────────────────────────────────────────────
PIPE_ID          = "ALPACA-PIPE-001"
PIPE_NAME        = "Alpaca — Price Bars + News + Market Snapshots"
PIPE_VERSION     = "1.0"
PIPE_URI_PREFIX  = "aureon://atrox/pipe/alpaca"

# Module-level client singleton
_client: Optional["AlpacaClient"] = None


class AlpacaClient:
    """
    Atrox MCP data pipe client for Alpaca Data API v2.

    Wraps Alpaca REST API as a structured data pipe with full provenance.
    Free tier supports IEX feed + delayed SIP — sufficient for Thifur
    baseline calibration.

    Usage:
        client = AlpacaClient()

        # Daily bars for drawdown modeling
        bars = client.get_bars(["SPY", "QQQ"], timeframe="1Day", limit=252)

        # Latest snapshot (quote + bar + trade)
        snap = client.get_snapshots(["AAPL", "MSFT"])

        # News feed for a ticker
        news = client.get_news(["NVDA"], limit=20)

        # Full Atrox ingestion packet
        packet = client.get_atrox_ingestion_packet(["SPY", "QQQ", "NVDA"])
    """

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self._key    = api_key    or os.environ.get("ALPACA_API_KEY", "")
        self._secret = api_secret or os.environ.get("ALPACA_API_SECRET", "")
        self._ready  = bool(self._key and self._secret)

    @property
    def is_ready(self) -> bool:
        return self._ready

    def _get(self, base: str, path: str, params: Optional[dict] = None) -> dict:
        """GET request with provenance wrapping."""
        if not self._ready:
            raise RuntimeError(
                "ALPACA_API_KEY / ALPACA_API_SECRET not configured. "
                "Register at alpaca.markets — free paper trading tier available."
            )

        url = f"{base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            )

        req = urllib.request.Request(url)
        req.add_header("APCA-API-KEY-ID",     self._key)
        req.add_header("APCA-API-SECRET-KEY", self._secret)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "aureon-atrox/1.0")

        ts = datetime.now(timezone.utc).isoformat()

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw    = resp.read()
                data   = json.loads(raw)
                digest = hashlib.sha256(raw).hexdigest()[:16].upper()
                return {
                    "ok":           True,
                    "pipe_id":      PIPE_ID,
                    "source_uri":   f"{PIPE_URI_PREFIX}{path}",
                    "endpoint":     path,
                    "params":       params or {},
                    "ts":           ts,
                    "content_hash": digest,
                    "data":         data,
                }
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            return {
                "ok":       False,
                "pipe_id":  PIPE_ID,
                "source_uri": f"{PIPE_URI_PREFIX}{path}",
                "endpoint": path,
                "ts":       ts,
                "error":    f"HTTP {exc.code}: {body[:200]}",
                "data":     None,
            }
        except Exception as exc:
            return {
                "ok":       False,
                "pipe_id":  PIPE_ID,
                "source_uri": f"{PIPE_URI_PREFIX}{path}",
                "endpoint": path,
                "ts":       ts,
                "error":    str(exc),
                "data":     None,
            }

    # ─────────────────────────────────────────────────────────────────────────
    # PRICE BARS
    # ─────────────────────────────────────────────────────────────────────────

    def get_bars(self, symbols: List[str],
                 timeframe: str = "1Day",
                 limit: int = 252,
                 start: Optional[str] = None,
                 end: Optional[str] = None,
                 feed: str = "iex") -> dict:
        """
        OHLCV price bars for one or multiple symbols.
        Endpoint: GET /stocks/bars

        Args:
            timeframe: "1Min" | "5Min" | "15Min" | "1Hour" | "1Day"
            limit:     max bars (252 = 1 trading year)
            feed:      "iex" (free) | "sip" (delayed, requires subscription)
        """
        symbols_param = ",".join(symbols)
        if not start:
            start = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
        return self._get(ALPACA_DATA_BASE, "/stocks/bars", {
            "symbols":   symbols_param,
            "timeframe": timeframe,
            "limit":     limit,
            "start":     start,
            "end":       end,
            "feed":      feed,
            "sort":      "asc",
        })

    def get_bars_single(self, symbol: str,
                        timeframe: str = "1Day",
                        limit: int = 252,
                        feed: str = "iex") -> dict:
        """Single-symbol bars — cleaner response structure for Thifur analysis."""
        start = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
        return self._get(ALPACA_DATA_BASE, f"/stocks/{symbol}/bars", {
            "timeframe": timeframe,
            "limit":     limit,
            "start":     start,
            "feed":      feed,
            "sort":      "asc",
        })

    # ─────────────────────────────────────────────────────────────────────────
    # QUOTES + TRADES
    # ─────────────────────────────────────────────────────────────────────────

    def get_latest_quotes(self, symbols: List[str], feed: str = "iex") -> dict:
        """
        Latest bid/ask quote for each symbol.
        Endpoint: GET /stocks/quotes/latest
        """
        return self._get(ALPACA_DATA_BASE, "/stocks/quotes/latest", {
            "symbols": ",".join(symbols),
            "feed":    feed,
        })

    def get_latest_trades(self, symbols: List[str], feed: str = "iex") -> dict:
        """
        Latest trade print for each symbol.
        Endpoint: GET /stocks/trades/latest
        """
        return self._get(ALPACA_DATA_BASE, "/stocks/trades/latest", {
            "symbols": ",".join(symbols),
            "feed":    feed,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # SNAPSHOTS
    # ─────────────────────────────────────────────────────────────────────────

    def get_snapshots(self, symbols: List[str], feed: str = "iex") -> dict:
        """
        Aggregated snapshot — latest quote, latest trade, daily bar, prev bar.
        Endpoint: GET /stocks/snapshots
        Atrox domain: Pre-trade state picture.
        """
        return self._get(ALPACA_DATA_BASE, "/stocks/snapshots", {
            "symbols": ",".join(symbols),
            "feed":    feed,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # NEWS
    # ─────────────────────────────────────────────────────────────────────────

    def get_news(self, symbols: Optional[List[str]] = None,
                 limit: int = 20,
                 start: Optional[str] = None,
                 end: Optional[str] = None) -> dict:
        """
        News articles — company-specific or broad market.
        Endpoint: GET /news (v1beta1)

        Atrox domain: Macro + company news signal for Thifur H advisory.
        """
        params: dict = {"limit": limit, "sort": "desc"}
        if symbols:
            params["symbols"] = ",".join(symbols)
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        return self._get(ALPACA_NEWS_BASE, "/news", params)

    # ─────────────────────────────────────────────────────────────────────────
    # CORPORATE ACTIONS
    # ─────────────────────────────────────────────────────────────────────────

    def get_corporate_actions(self, symbol: str,
                              ca_types: Optional[List[str]] = None) -> dict:
        """
        Corporate actions: splits, dividends, mergers.
        Endpoint: GET /stocks/{symbol}/corporate_actions
        """
        params: dict = {}
        if ca_types:
            params["types"] = ",".join(ca_types)
        return self._get(ALPACA_DATA_BASE, f"/stocks/{symbol}/corporate_actions", params or None)

    # ─────────────────────────────────────────────────────────────────────────
    # ATROX INGESTION PACKET
    # ─────────────────────────────────────────────────────────────────────────

    def get_atrox_ingestion_packet(self, symbols: List[str],
                                      bar_limit: int = 252,
                                      news_limit: int = 20) -> dict:
        """
        Full Atrox ingestion packet for Thifur calibration.
        Pulls: snapshots, daily bars, and news for all symbols.

        Atrox domain: Baseline equity + macro signal pipeline.
        """
        ts = datetime.now(timezone.utc).isoformat()
        packet: dict = {
            "ok":        True,
            "pipe_id":   PIPE_ID,
            "source_uri": f"{PIPE_URI_PREFIX}/atrox-packet",
            "ts":        ts,
            "symbols":   symbols,
            "data": {},
        }

        packet["data"]["snapshots"] = self.get_snapshots(symbols)
        packet["data"]["bars"]      = self.get_bars(symbols, limit=bar_limit)
        packet["data"]["news"]      = self.get_news(symbols, limit=news_limit)

        raw_bytes = json.dumps(packet["data"]).encode()
        packet["content_hash"] = hashlib.sha256(raw_bytes).hexdigest()[:16].upper()
        return packet


# ─────────────────────────────────────────────────────────────────────────────
# Module-level pipe interface
# ─────────────────────────────────────────────────────────────────────────────

def init_alpaca_pipe(api_key: Optional[str] = None,
                     api_secret: Optional[str] = None) -> "AlpacaClient":
    """Initialize (or re-initialize) the Alpaca pipe client."""
    global _client
    _client = AlpacaClient(api_key=api_key, api_secret=api_secret)
    return _client


def get_client() -> Optional["AlpacaClient"]:
    return _client


def pipe_status() -> dict:
    key_present    = bool(os.environ.get("ALPACA_API_KEY", ""))
    secret_present = bool(os.environ.get("ALPACA_API_SECRET", ""))
    ready          = key_present and secret_present
    return {
        "pipe_id": PIPE_ID,
        "name":    PIPE_NAME,
        "version": PIPE_VERSION,
        "status":  "live" if ready else "degraded",
        "source":  "alpaca.markets",
        "token":   "present" if ready else (
            "ALPACA_API_KEY missing" if not key_present else "ALPACA_API_SECRET missing"
        ),
        "docs":    "https://docs.alpaca.markets/reference/stockbars",
        "ts":      datetime.now(timezone.utc).isoformat(),
    }
