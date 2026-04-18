"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/mcp/cboe_client.py                                           ║
║  Atrox — CBOE Market Data Pipe                               ║
║                                                                      ║
║  MANDATE:                                                            ║
║    Systemic fear gauge and market structure data for Thifur stress   ║
║    testing. VIX term structure signals regime shifts before they     ║
║    appear in price.                                                  ║
║                                                                      ║
║  DATA DOMAINS:                                                       ║
║    - VIX history (daily close — complete historical series)          ║
║    - VIX term structure (VIX9D, VIX, VIX3M, VIX6M)                 ║
║    - Equity put/call ratio                                           ║
║    - Index put/call ratio                                            ║
║    - Total put/call ratio                                            ║
║    - CBOE indices daily prices (VIX, SKEW, VVIX, MOVE)              ║
║                                                                      ║
║  API: CBOE public data CDN (no auth required)                        ║
║  Base: https://cdn.cboe.com/api/global/us_indices/daily_prices/      ║
║  P/C:  https://www.cboe.com/publish/scheduledtask/mktdata/datahouse/ ║
║                                                                      ║
║  NO API KEY REQUIRED — completely free public data.                  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import csv
import hashlib
import io
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional, List

# ── CBOE CDN Endpoints ────────────────────────────────────────────────────────
CBOE_CDN_BASE    = "https://cdn.cboe.com/api/global/us_indices/daily_prices"
CBOE_PC_BASE     = "https://www.cboe.com/publish/scheduledtask/mktdata/datahouse"

# VIX family + fear gauges — all CSV, all free
CBOE_INDICES = {
    "VIX":   "VIX_History.csv",      # CBOE Volatility Index (30-day)
    "VIX9D": "VIX9D_History.csv",    # 9-day VIX
    "VIX3M": "VIX3M_History.csv",    # 3-month VIX
    "VIX6M": "VIX6M_History.csv",    # 6-month VIX
    "VVIX":  "VVIX_History.csv",     # Volatility of VIX
    "SKEW":  "SKEW_History.csv",     # CBOE SKEW Index (tail risk)
    "MOVE":  "MOVE_History.csv",     # ICE BofA MOVE (bond vol)
}

# Put/call ratio files
CBOE_PC_FILES = {
    "equity":       "equitypc.csv",   # equity-only p/c ratio
    "index":        "indexpc.csv",    # index options p/c ratio
    "total":        "totalpc.csv",    # total (equity + index) p/c ratio
    "etf":          "etfpc.csv",      # ETF p/c ratio
}

# ── Atrox Pipe Identity ─────────────────────────────────────────────────────
PIPE_ID         = "CBOE-PIPE-001"
PIPE_NAME       = "CBOE — VIX Term Structure + Put/Call Ratios"
PIPE_VERSION    = "1.0"
PIPE_URI_PREFIX = "aureon://atrox/pipe/cboe"

# Module-level client singleton
_client: Optional["CboeClient"] = None


class CboeClient:
    """
    Atrox MCP data pipe client for CBOE public market data.

    No API key required — pulls from CBOE's public CDN.
    All responses are parsed from CSV into structured dicts with provenance.

    Usage:
        client = CboeClient()

        # VIX daily history (last N rows)
        vix = client.get_vix_history(limit=252)

        # Full VIX term structure snapshot
        term = client.get_vix_term_structure()

        # Put/call ratios
        pc = client.get_put_call_ratios()

        # Full Thifur fear gauge packet
        packet = client.get_thifur_fear_packet()
    """

    def __init__(self):
        # No credentials needed — all public data
        self._ready = True

    @property
    def is_ready(self) -> bool:
        return True

    def _fetch_csv(self, url: str, limit: Optional[int] = None) -> dict:
        """
        Fetch a CBOE CSV file and parse into a list of row dicts.
        Returns provenance-wrapped dict.
        """
        ts = datetime.now(timezone.utc).isoformat()
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "aureon-atrox/1.0")
            req.add_header("Accept", "text/csv,text/plain,*/*")

            with urllib.request.urlopen(req, timeout=20) as resp:
                raw  = resp.read()
                text = raw.decode("utf-8", errors="ignore")

                # Some CBOE CSVs have a header row before the column row
                lines = text.strip().splitlines()
                # Find the row that contains "DATE" or "Date" as the column header
                header_idx = 0
                for i, line in enumerate(lines):
                    if "DATE" in line.upper() and ("OPEN" in line.upper() or "RATIO" in line.upper() or "CLOSE" in line.upper()):
                        header_idx = i
                        break

                csv_text = "\n".join(lines[header_idx:])
                reader   = csv.DictReader(io.StringIO(csv_text))
                rows     = [row for row in reader if any(v.strip() for v in row.values())]

                if limit:
                    rows = rows[-limit:]  # most recent N rows

                digest = hashlib.sha256(raw).hexdigest()[:16].upper()
                return {
                    "ok":           True,
                    "pipe_id":      PIPE_ID,
                    "source_uri":   f"{PIPE_URI_PREFIX}/csv/{url.split('/')[-1]}",
                    "url":          url,
                    "ts":           ts,
                    "content_hash": digest,
                    "row_count":    len(rows),
                    "data":         rows,
                }
        except urllib.error.HTTPError as exc:
            return {
                "ok":       False,
                "pipe_id":  PIPE_ID,
                "source_uri": f"{PIPE_URI_PREFIX}/csv/{url.split('/')[-1]}",
                "url":      url,
                "ts":       ts,
                "error":    f"HTTP {exc.code}",
                "data":     None,
            }
        except Exception as exc:
            return {
                "ok":       False,
                "pipe_id":  PIPE_ID,
                "source_uri": f"{PIPE_URI_PREFIX}/csv/{url.split('/')[-1]}",
                "url":      url,
                "ts":       ts,
                "error":    str(exc),
                "data":     None,
            }

    # ─────────────────────────────────────────────────────────────────────────
    # VIX DATA
    # ─────────────────────────────────────────────────────────────────────────

    def get_vix_history(self, limit: int = 252) -> dict:
        """
        VIX daily OHLC — last `limit` trading days.
        Atrox domain: Volatility regime identification.
        """
        url = f"{CBOE_CDN_BASE}/{CBOE_INDICES['VIX']}"
        return self._fetch_csv(url, limit=limit)

    def get_index_history(self, index: str, limit: int = 252) -> dict:
        """
        Daily history for any CBOE index.

        Args:
            index: One of VIX, VIX9D, VIX3M, VIX6M, VVIX, SKEW, MOVE
            limit: Number of most-recent rows to return
        """
        if index not in CBOE_INDICES:
            return {
                "ok":    False,
                "error": f"Unknown index '{index}'. Valid: {list(CBOE_INDICES.keys())}",
                "data":  None,
            }
        url = f"{CBOE_CDN_BASE}/{CBOE_INDICES[index]}"
        return self._fetch_csv(url, limit=limit)

    # ─────────────────────────────────────────────────────────────────────────
    # VIX TERM STRUCTURE
    # ─────────────────────────────────────────────────────────────────────────

    def get_vix_term_structure(self, lookback_days: int = 30) -> dict:
        """
        VIX term structure snapshot — VIX9D, VIX, VIX3M, VIX6M latest closes.

        The shape of the term structure (contango vs backwardation) is a
        primary input to Thifur's volatility regime classification.
        Backwardation (VIX9D > VIX > VIX3M) signals acute stress.

        Atrox domain: Regime classification + drawdown risk escalation.
        """
        ts     = datetime.now(timezone.utc).isoformat()
        term   = {}
        errors = []

        for label in ("VIX9D", "VIX", "VIX3M", "VIX6M"):
            result = self.get_index_history(label, limit=lookback_days)
            if result.get("ok") and result.get("data"):
                rows = result["data"]
                last = rows[-1]
                term[label] = {
                    "close":      last.get("CLOSE") or last.get("VIX Close") or last.get("Close"),
                    "date":       last.get("DATE")  or last.get("Date"),
                    "series":     [{
                        "date":  r.get("DATE") or r.get("Date"),
                        "close": r.get("CLOSE") or r.get("VIX Close") or r.get("Close"),
                    } for r in rows],
                }
            else:
                errors.append(f"{label}: {result.get('error', 'unknown error')}")

        # Compute contango/backwardation signal
        structure_signal = "UNKNOWN"
        try:
            v9  = float(term.get("VIX9D",  {}).get("close") or 0)
            v30 = float(term.get("VIX",    {}).get("close") or 0)
            v90 = float(term.get("VIX3M",  {}).get("close") or 0)
            v180= float(term.get("VIX6M",  {}).get("close") or 0)
            if v9 > v30 > v90:
                structure_signal = "BACKWARDATION"   # acute stress
            elif v9 < v30 < v90:
                structure_signal = "CONTANGO"        # normal / complacency
            else:
                structure_signal = "MIXED"
        except (TypeError, ValueError):
            pass

        raw_bytes = json.dumps(term).encode()
        digest    = hashlib.sha256(raw_bytes).hexdigest()[:16].upper()

        return {
            "ok":              True,
            "pipe_id":         PIPE_ID,
            "source_uri":      f"{PIPE_URI_PREFIX}/vix-term-structure",
            "ts":              ts,
            "content_hash":    digest,
            "structure_signal": structure_signal,
            "errors":          errors,
            "data":            term,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # PUT/CALL RATIOS
    # ─────────────────────────────────────────────────────────────────────────

    def get_put_call_ratio(self, ratio_type: str = "total", limit: int = 30) -> dict:
        """
        Put/call ratio history.

        Args:
            ratio_type: "equity" | "index" | "total" | "etf"
            limit:      Most recent N trading days
        """
        if ratio_type not in CBOE_PC_FILES:
            return {
                "ok":    False,
                "error": f"Unknown ratio type '{ratio_type}'. Valid: {list(CBOE_PC_FILES.keys())}",
                "data":  None,
            }
        url = f"{CBOE_PC_BASE}/{CBOE_PC_FILES[ratio_type]}"
        return self._fetch_csv(url, limit=limit)

    def get_put_call_ratios(self, limit: int = 30) -> dict:
        """
        All put/call ratios in one call — equity, index, total, ETF.
        Atrox domain: Sentiment / hedging demand gauge.
        """
        ts     = datetime.now(timezone.utc).isoformat()
        result = {}
        errors = []

        for rtype in ("equity", "index", "total", "etf"):
            r = self.get_put_call_ratio(rtype, limit=limit)
            if r.get("ok"):
                result[rtype] = r["data"]
            else:
                errors.append(f"{rtype}: {r.get('error', 'unknown')}")

        raw_bytes = json.dumps(result).encode()
        digest    = hashlib.sha256(raw_bytes).hexdigest()[:16].upper()

        return {
            "ok":           True,
            "pipe_id":      PIPE_ID,
            "source_uri":   f"{PIPE_URI_PREFIX}/put-call-ratios",
            "ts":           ts,
            "content_hash": digest,
            "errors":       errors,
            "data":         result,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # THIFUR FEAR GAUGE PACKET
    # ─────────────────────────────────────────────────────────────────────────

    def get_thifur_fear_packet(self, lookback_days: int = 30) -> dict:
        """
        Full Thifur fear gauge packet — VIX term structure + all P/C ratios.

        This is the primary systemic fear signal that feeds Thifur's
        drawdown escalation logic and halt condition assessment.

        Returns a single provenance-stamped record with:
          - VIX term structure + contango/backwardation signal
          - All four put/call ratios (equity, index, total, ETF)
          - SKEW index (tail risk pricing)
          - VVIX (vol-of-vol, second-order fear)
        """
        ts     = datetime.now(timezone.utc).isoformat()
        packet = {}

        packet["vix_term_structure"] = self.get_vix_term_structure(lookback_days)
        packet["put_call_ratios"]    = self.get_put_call_ratios(lookback_days)
        packet["skew"]               = self.get_index_history("SKEW", limit=lookback_days)
        packet["vvix"]               = self.get_index_history("VVIX", limit=lookback_days)

        # Derive composite fear level
        fear_level = "UNKNOWN"
        try:
            ts_signal = packet["vix_term_structure"].get("structure_signal", "UNKNOWN")
            pc_rows   = (packet["put_call_ratios"].get("data", {}).get("total") or [])
            latest_pc = None
            if pc_rows:
                last_row  = pc_rows[-1]
                # CBOE total p/c file columns vary — try common names
                for col in ("TOTAL PUT/CALL RATIO", "Total P/C Ratio", "Ratio"):
                    if col in last_row:
                        latest_pc = float(last_row[col])
                        break

            if ts_signal == "BACKWARDATION" and latest_pc and latest_pc > 1.0:
                fear_level = "ELEVATED"
            elif ts_signal == "BACKWARDATION" or (latest_pc and latest_pc > 1.15):
                fear_level = "HEIGHTENED"
            elif ts_signal == "CONTANGO" and (latest_pc is None or latest_pc < 0.85):
                fear_level = "COMPLACENT"
            else:
                fear_level = "NEUTRAL"
        except (TypeError, ValueError, KeyError):
            pass

        raw_bytes = json.dumps(packet).encode()
        digest    = hashlib.sha256(raw_bytes).hexdigest()[:16].upper()

        return {
            "ok":              True,
            "pipe_id":         PIPE_ID,
            "source_uri":      f"{PIPE_URI_PREFIX}/thifur-fear-packet",
            "ts":              ts,
            "content_hash":    digest,
            "fear_level":      fear_level,
            "structure_signal": packet["vix_term_structure"].get("structure_signal", "UNKNOWN"),
            "data":            packet,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Module-level pipe interface
# ─────────────────────────────────────────────────────────────────────────────

def init_cboe_pipe() -> "CboeClient":
    """Initialize (or re-initialize) the CBOE pipe client."""
    global _client
    _client = CboeClient()
    return _client


def get_client() -> Optional["CboeClient"]:
    return _client


def pipe_status() -> dict:
    """CBOE requires no credentials — always live."""
    return {
        "pipe_id": PIPE_ID,
        "name":    PIPE_NAME,
        "version": PIPE_VERSION,
        "status":  "live",
        "source":  "cdn.cboe.com (public, no auth required)",
        "token":   "none required",
        "docs":    "https://www.cboe.com/tradable_products/vix/vix_historical_data/",
        "ts":      datetime.now(timezone.utc).isoformat(),
    }
