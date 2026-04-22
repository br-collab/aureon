"""
Aureon MMF — Yield Engine (Phase 1, Sandbox)

PURPOSE:     Provide the daily net-yield inputs the MMF NAV engine uses
             to accrue. Pulls DGS1MO (1-month U.S. Treasury constant
             maturity yield) as the primary rate and SOFR (Secured
             Overnight Financing Rate) as fallback, both from the
             St. Louis Fed FRED API. Computes daily accrual on the
             ACT/360 money-market day-count convention.

INPUTS:      FRED_API_KEY from environment (optional — unauthenticated
             FRED calls work at lower rate limits). Module reads it
             once at import.

OUTPUTS:     get_current_yield_inputs() -> {
                 dgs1mo_pct, sofr_pct, source, fetched_at, stale,
                 dgs1mo_date, sofr_date
             }
             compute_daily_accrual(nav, fee_bps) -> {
                 gross_yield_daily, fee_daily, net_yield_daily,
                 annual_rate_pct, source, stale
             }

ASSUMPTIONS: Both DGS1MO and SOFR are annualized percentages (e.g.,
             4.32 means 4.32%/yr). ACT/360 day-count applies to U.S.
             money-market yields by convention.

             STALENESS (operator decision 2026-04-21, calendar-day
             rule, Option 1): `stale == True` when the FRED observation
             date is neither today (ET) nor yesterday (ET). Tolerates
             FRED's normal 1-2 business day publication lag without
             letting weekend / multi-day gaps slip through. No
             business-day or holiday handling in Phase 1 — deferred
             to Phase 3. The NAV engine halts on `stale == True`.

AUDIT NOTES: Module-level cache, TTL 3600s. Fallback from DGS1MO to
             SOFR is logged. No state persistence — a process restart
             triggers a fresh FRED fetch on next call. Using DGS1MO
             directly as the fund's current yield is a SANDBOX
             SIMPLIFICATION: a real MMF yields the weighted average of
             its portfolio holdings, not a spot reference rate. This
             engine simulates an idealized all-1M-Treasury fund for
             Phase 1 validation only.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

log = logging.getLogger("aureon.mmf.yield_engine")

# --- Constants --------------------------------------------------------------
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

# Money-market day-count convention. DGS1MO and SOFR are quoted ACT/360.
DAYS_PER_YEAR_ACT360 = Decimal("360")

_CACHE_TTL_S = 3600.0              # 1 hour — intra-day yield changes minimally

# Stale rule (calendar-day, operator decision 2026-04-21):
# fresh == FRED observation date is today (ET) or today-minus-one (ET).
# Anything older is stale. No business-day / holiday logic in Phase 1 —
# that's Phase 3 territory. DGS1MO and SOFR have a 1-2 business-day
# publication lag, so a "today or yesterday" window tolerates the normal
# publish cadence without ever letting weekend/multi-day gaps slip by.
_ET = ZoneInfo("America/New_York")

# Module-level cache. Intentionally a single dict so callers can share the
# most recent fetch across threads without duplicated network I/O.
_cache: dict = {"ts": 0.0, "payload": None}


# --- FRED helper ------------------------------------------------------------
def _fred_latest(series_id: str, timeout: float = 6.0) -> Optional[dict]:
    """
    Return the latest non-null observation for a FRED series as
    {"date": "YYYY-MM-DD", "value": float}, or None on any failure.

    Over-fetches (limit=7) to tolerate FRED's missing-value markers
    ('.', '', None) that can appear in the newest slots.
    """
    params = {
        "series_id": series_id,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 7,
    }
    if FRED_API_KEY:
        params["api_key"] = FRED_API_KEY
    url = FRED_BASE + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        log.warning("FRED fetch failed for %s: %s: %s",
                    series_id, type(e).__name__, e)
        return None
    except Exception as e:
        log.warning("FRED fetch unexpected error for %s: %s: %s",
                    series_id, type(e).__name__, e)
        return None

    for obs in payload.get("observations", []):
        value = obs.get("value")
        if value in (None, ".", ""):
            continue
        try:
            return {"date": obs.get("date"), "value": float(value)}
        except (TypeError, ValueError):
            continue
    log.warning("FRED returned no usable value for %s", series_id)
    return None


# --- Public API -------------------------------------------------------------
def get_current_yield_inputs() -> dict:
    """
    Fetch DGS1MO and SOFR from FRED (or return cached values if fresh).

    Returns a dict with:
      dgs1mo_pct   — 1M T-bill rate, annualized %. None if FRED failed.
      sofr_pct     — Secured Overnight Financing Rate, annualized %. Same.
      source       — "DGS1MO" | "SOFR" | "NONE". Which rate the NAV
                     engine should use (primary: DGS1MO; fallback: SOFR).
      fetched_at   — ISO-8601 UTC timestamp of the fetch (or cache hit).
      stale        — True if the newest returned data is older than
                     4 hours. NAV engine halts on True.
      dgs1mo_date  — observation date from FRED for DGS1MO (audit).
      sofr_date    — observation date from FRED for SOFR (audit).
    """
    now = time.time()
    if _cache["payload"] is not None and (now - _cache["ts"]) < _CACHE_TTL_S:
        return _cache["payload"]

    dgs1mo = _fred_latest("DGS1MO")
    sofr = _fred_latest("SOFR")

    if dgs1mo is not None:
        source = "DGS1MO"
    elif sofr is not None:
        source = "SOFR"
        log.info("yield_engine fallback: DGS1MO unavailable, using SOFR")
    else:
        source = "NONE"
        log.error("yield_engine: both DGS1MO and SOFR unavailable")

    fetched_at = datetime.now(timezone.utc).isoformat()

    # Calendar-day stale check. Fresh = obs date is today (ET) or
    # yesterday (ET); anything else is stale. Uses whichever source was
    # chosen — checking the *unused* source's date would flag freshness
    # issues the NAV engine doesn't care about.
    latest_date_str = None
    if source == "DGS1MO":
        latest_date_str = dgs1mo["date"] if dgs1mo else None
    elif source == "SOFR":
        latest_date_str = sofr["date"] if sofr else None

    today_et = datetime.now(_ET).date()
    yesterday_et = today_et - timedelta(days=1)

    stale = True
    if latest_date_str is not None:
        try:
            obs_date = datetime.strptime(latest_date_str, "%Y-%m-%d").date()
            stale = obs_date not in (today_et, yesterday_et)
        except ValueError:
            stale = True

    payload = {
        "dgs1mo_pct":  dgs1mo["value"] if dgs1mo else None,
        "sofr_pct":    sofr["value"]   if sofr   else None,
        "source":      source,
        "fetched_at":  fetched_at,
        "stale":       stale,
        "dgs1mo_date": dgs1mo["date"] if dgs1mo else None,
        "sofr_date":   sofr["date"]   if sofr   else None,
    }
    _cache["ts"] = now
    _cache["payload"] = payload
    return payload


def compute_daily_accrual(nav_per_share, management_fee_bps: int = 15) -> dict:
    """
    Compute the daily accrual amounts given the current yield inputs.

    ACT/360 money-market convention:
        gross_yield_daily = nav × (annual_rate_pct / 100)       × (1 / 360)
        fee_daily         = nav × (management_fee_bps / 10_000) × (1 / 360)
        net_yield_daily   = gross_yield_daily - fee_daily

    Primary rate is DGS1MO; falls back to SOFR. Returns zeros with
    annual_rate_pct=None if both sources are unavailable — the NAV
    engine is responsible for halting in that case.

    `nav_per_share` may be Decimal, str, or numeric; it is coerced to
    Decimal to preserve precision through the division.
    """
    inputs = get_current_yield_inputs()
    source = inputs["source"]

    if source == "DGS1MO":
        annual_rate_pct = inputs["dgs1mo_pct"]
    elif source == "SOFR":
        annual_rate_pct = inputs["sofr_pct"]
    else:
        annual_rate_pct = None

    nav = nav_per_share if isinstance(nav_per_share, Decimal) else Decimal(str(nav_per_share))
    fee_bps = Decimal(int(management_fee_bps))

    if annual_rate_pct is None:
        return {
            "gross_yield_daily": Decimal("0"),
            "fee_daily":         Decimal("0"),
            "net_yield_daily":   Decimal("0"),
            "annual_rate_pct":   None,
            "source":            source,
            "stale":             inputs["stale"],
            "note":              "no yield source available; NAV engine must halt",
        }

    rate = Decimal(str(annual_rate_pct))
    gross_yield_daily = (nav * (rate / Decimal("100"))) / DAYS_PER_YEAR_ACT360
    fee_daily         = (nav * (fee_bps / Decimal("10000"))) / DAYS_PER_YEAR_ACT360
    net_yield_daily   = gross_yield_daily - fee_daily

    return {
        "gross_yield_daily": gross_yield_daily,
        "fee_daily":         fee_daily,
        "net_yield_daily":   net_yield_daily,
        "annual_rate_pct":   float(rate),
        "source":            source,
        "stale":             inputs["stale"],
    }


# --- Standalone smoke test --------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    print("=" * 72)
    print("AUREON MMF — yield_engine smoke test (SYNTHETIC / SANDBOX)")
    print("=" * 72)
    print(f"FRED_API_KEY: {'set' if FRED_API_KEY else 'NOT SET (unauthenticated)'}")
    inputs = get_current_yield_inputs()
    print("\nget_current_yield_inputs():")
    print(json.dumps(inputs, indent=2, default=str))
    accr = compute_daily_accrual(Decimal("1.0000"), 15)
    print("\ncompute_daily_accrual(nav=$1.0000, fee=15bps):")
    print(json.dumps(accr, indent=2, default=str))
    print("=" * 72)
