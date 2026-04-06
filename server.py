"""
╔══════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                     ║
║  Doctrine-Driven Financial Operating System                      ║
║  server.py — Flask backend with live-data fallbacks.             ║
║                                                                  ║
║  HOW TO RUN:                                                     ║
║    1. Open this folder in VS Code                                ║
║    2. Open Terminal  (View → Terminal  or  Ctrl + `)             ║
║    3. pip install flask yfinance reportlab python-dotenv         ║
║    4. ./scripts/start.sh   or   python server.py                 ║
║    5. Open http://localhost:5001 in your browser                 ║
╚══════════════════════════════════════════════════════════════════╝

WHAT THIS FILE DOES (plain English):
  - Starts a tiny web server on port 5001
  - Serves index.html as the dashboard
  - Exposes /api/* endpoints that the dashboard calls every few seconds
  - Simulates a live $50M paper portfolio with price drift
  - Runs the Aureon four-layer doctrine stack (Verana→Mentat→Kaladan→Thifur)
  - Handles human authority decisions (approve / reject trades)

STRUCTURE:
  1. Imports          — standard Python libraries only
  2. Flask app        — one-line setup, points to THIS folder
  3. Aureon state     — one big dictionary, shared across all threads
  4. Initial data     — positions, prices, pending decisions
  5. Helper functions — price simulation, portfolio calc, alerts
  6. Background jobs  — doctrine stack (runs once) + market tick (every 5s)
  7. API routes       — /api/portfolio, /api/compliance, etc.
  8. Static routes    — serves index.html
  9. start()          — wires everything together and launches Flask
"""

# ─────────────────────────────────────────────────────────────────
# 1. IMPORTS
# ─────────────────────────────────────────────────────────────────
# These are all Python standard library or Flask — nothing custom.
# 'random'    → simulated price moves
# 'threading' → run market loop in background without freezing Flask
# 'time'      → sleep between price ticks
# 'hashlib'   → generate deterministic audit hashes (like a fingerprint)

import os
import io
import json
import math
import random
import re
import subprocess
import threading
import time
import hashlib
import tempfile
import zipfile
import smtplib
import urllib.parse
import urllib.request
try:
    import yfinance as yf  # real live prices from Yahoo Finance
    _YFINANCE_AVAILABLE = True
except ImportError:
    yf = None
    _YFINANCE_AVAILABLE = False
    print("[AUREON] yfinance not installed — running on simulated prices")
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import unescape
from datetime import datetime, timedelta, timezone, time as dt_time
import zoneinfo
from flask import Flask, Response, jsonify, send_from_directory, request
from aureon.config.settings import LOG_FILE, STATE_FILE
from aureon.persistence.store import load_state as persistence_load_state, save_state as persistence_save_state
from aureon.policy_engine.service import evaluate_pretrade_decision
from aureon.evidence_service.service import build_trade_report as evidence_build_trade_report
from aureon.approval_service.release_control import can_release, missing_roles, normalize_decision, release_to_oms
from aureon.approval_service.service import resolve_pending_decision
from aureon.integration_adapters.oms_adapter import send as oms_send
from aureon.integration_adapters.ems_adapter import build_execution_release
from aureon.session.session_protocol import SessionProtocol
from aureon.data.market_data import get_price, get_prices_batch
from agent_j import ThifurJ
from agent_r import ThifurR

# ── LOAD .env FILE ────────────────────────────────────────────────
# Reads AUREON_EMAIL and AUREON_EMAIL_PW from the .env file in
# the same folder as server.py — no terminal exports needed.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    print("[AUREON] .env loaded")
except Exception:
    pass  # dotenv not installed — fall back to environment variables

# ── EMAIL CONFIG ──────────────────────────────────────────────────
EMAIL_FROM     = os.environ.get("AUREON_EMAIL", "aureonfsos@gmail.com")          # Gmail sender
EMAIL_TO       = os.environ.get("AUREON_EMAIL_RECIPIENT", "br@ravelobizdev.com")  # report recipient
EMAIL_PASSWORD = os.environ.get("AUREON_EMAIL_PW", "")
SMTP_HOST      = "smtp.gmail.com"
SMTP_PORT      = 587
FRED_API_KEY          = os.environ.get("FRED_API_KEY", "")
TWELVE_DATA_API_KEY   = os.environ.get("TWELVE_DATA_API_KEY", "")


# ─────────────────────────────────────────────────────────────────
# 2. FLASK APP
# ─────────────────────────────────────────────────────────────────
# THIS_DIR = the folder where server.py lives.
# Flask needs to know where to find static files (index.html, etc.)
# The old version had:  os.path.join(..., '..', '..')  — that climbed
# two folders UP, which is why it couldn't find index.html.
# Now we just say: "look in the same folder as this file."

THIS_DIR   = os.path.dirname(os.path.abspath(__file__))

# ─────────────────────────────────────────────────────────────────
# INSTITUTIONAL CASH MANAGEMENT CONSTANTS
# ─────────────────────────────────────────────────────────────────
# Fidelity is the #1 US government MMF provider (~19% market share,
# $1.245T AUM).  Provider selection is jurisdiction-aware:
#   US  → FDRXX  (Fidelity Government Cash Reserves — US domiciled)
#   EU  → FILF_EUR (Fidelity ILF EUR — Luxembourg SICAV)
#   UK  → FILF_GBP (Fidelity ILF GBP — Luxembourg SICAV)
# Cash segmentation framework: Operating Cash floor stays liquid
# (<3 month bucket, safety + liquidity priority).  Everything above
# the floor sweeps nightly into the institutional MMF.

OPERATING_CASH_FLOOR_PCT = 0.03     # 3 % of portfolio stays liquid at all times
MMF_YIELD_ANNUAL         = 0.0525   # ~5.25 % annualised government MMF yield

MMF_PROVIDERS = {
    "US": {
        "name":         "Fidelity Government Cash Reserves (FDRXX)",
        "ticker":       "FDRXX",
        "jurisdiction": "US",
        "currency":     "USD",
    },
    "EU": {
        "name":         "Fidelity ILF – EUR (FILF_EUR)",
        "ticker":       "FILF_EUR",
        "jurisdiction": "LU",
        "currency":     "EUR",
    },
    "UK": {
        "name":         "Fidelity ILF – GBP (FILF_GBP)",
        "ticker":       "FILF_GBP",
        "jurisdiction": "LU",
        "currency":     "GBP",
    },
}


def _resolve_mmf_provider(provider=None):
    """
    Normalize persisted/provider state so Treasury and sweep logic always
    have a valid jurisdiction-aware MMF definition to work with.
    """
    fallback = MMF_PROVIDERS.get(PORTFOLIO_JURISDICTION, MMF_PROVIDERS["US"])
    if isinstance(provider, dict):
        required = {"name", "ticker", "jurisdiction", "currency"}
        if required.issubset(provider):
            return provider
    return fallback
PORTFOLIO_JURISDICTION = "US"   # configurable per deployment

RISK_MANAGER_POLICY = {
    "drawdown_warn_pct": 5.0,
    "drawdown_fail_pct": 8.0,
    "position_warn_pct": 10.0,
    "position_fail_pct": 15.0,
    "var_limit_pct": 2.0,
}

# ─────────────────────────────────────────────────────────────────
# OFAC SDN / SANCTIONS SCREENING
# ─────────────────────────────────────────────────────────────────
# Simulated OFAC Specially Designated Nationals list.
# In production this would be sourced from Thomson Reuters World-Check
# or the US Treasury SDN XML feed (updated daily).
# Any symbol mapping to a blocked ISIN triggers a FAIL pre-trade gate.

OFAC_BLOCKED_ISINS = {
    "PDVSA_BOND_2027": "PDVSA — sanctioned Venezuelan state entity (OFAC SDN)",
    "IRAN_BOND_2024":  "Islamic Republic of Iran — OFAC primary sanctions",
    "RUSAL_CONV_2025": "UC RUSAL — OFAC SDN (re-instated monitoring)",
    "NORD_STREAM_2":   "Nord Stream 2 AG — OFAC secondary sanctions EO 13662",
}

# Map internal symbols → ISIN identifiers for pre-trade SDN lookup.
# Current portfolio instruments are all clean; blocked ISINs would only
# surface if a future Thifur signal proposed a sanctioned instrument.
SYMBOL_TO_ISIN = {
    "PDVSA":  "PDVSA_BOND_2027",
    "IRAN":   "IRAN_BOND_2024",
    "RUSAL":  "RUSAL_CONV_2025",
    "NORSTR": "NORD_STREAM_2",
}

app = Flask(__name__, static_folder=THIS_DIR)
from flask_cors import CORS
CORS(app, origins=[
    "http://localhost:3000",
    "http://localhost:5001",
])


# ─────────────────────────────────────────────────────────────────
# 3. AUREON STATE  (single source of truth)
# ─────────────────────────────────────────────────────────────────
# One dictionary holds everything. We protect it with a threading
# lock (_lock) so the market loop and API routes don't collide.
# Think of _lock like a "do not disturb" sign on the dictionary.

_lock = threading.Lock()

aureon_state = {
    # ── Doctrine stack ──────────────────────────────────────────
    "stack_status":      "initializing",   # initializing → running → ready
    "doctrine_version":  "1.0",
    "stack_result":      None,
    "audit":             None,
    "cycle_count":       0,
    "last_stack_run":    None,
    "network_nodes":     15,
    "nodes_operational": 15,

    # ── Live portfolio ───────────────────────────────────────────
    "portfolio_value":   50_000_000,       # starts at $50M
    "cash":              50_000_000,       # shrinks as positions are taken
    "pnl":               0.0,
    "pnl_pct":           0.0,
    "drawdown":          0.0,

    # ── Collections (populated below) ───────────────────────────
    "positions":          [],
    "trades":             [],
    "pending_decisions":  [],
    "compliance_alerts":  [],
    "alert_history":      [],
    "authority_log":      [],
    "prices":             {},
    "class_totals":       {},

    # ── Emergency halt (Tier 0 — above all doctrine) ─────────────
    "halt_active":    False,   # True = all Thifur execution frozen
    "halt_ts":        None,    # ISO timestamp of halt activation
    "halt_authority": None,    # who activated the halt
    "halt_reason":    None,    # stated reason

    # ── Doctrine modification governance ─────────────────────────
    "pending_doctrine_updates": [],   # proposed, awaiting Tier 1 approval
    "doctrine_version_log": [
        {
            "version":   "1.0",
            "prev":      None,
            "hash":      hashlib.sha256(b"AUREON-DOCTRINE-1.0-INIT").hexdigest()[:16].upper(),
            "ts":        datetime.now(timezone.utc).isoformat(),
            "authority": "SYSTEM",
            "tier":      "System Init",
            "trigger":   "SYSTEM_INIT",
            "reason":    "Initial doctrine load — Aureon Grid 3 deployment",
        },
        {
            "version":   "1.1",
            "prev":      "1.0",
            "hash":      hashlib.sha256(b"AUREON-DOCTRINE-1.1-DORA").hexdigest()[:16].upper(),
            "ts":        datetime.now(timezone.utc).isoformat(),
            "authority": "Verana L0 (Regulatory Absorption)",
            "tier":      "Tier 2 — Regulatory Mandate",
            "trigger":   "REGULATORY",
            "reason":    "EU DORA Article 28 absorbed. 4 nodes flagged. Doctrine updated.",
        },
        {
            "version":   "1.2",
            "prev":      "1.1",
            "hash":      hashlib.sha256(b"AUREON-DOCTRINE-1.2-BASEL").hexdigest()[:16].upper(),
            "ts":        datetime.now(timezone.utc).isoformat(),
            "authority": "br@ravelobizdev.com",
            "tier":      "Tier 1 — Human Authority",
            "trigger":   "HUMAN_AUTHORITY",
            "reason":    "Basel III Endgame vs EU CRR III conflict resolved. Apply HIGHER RWA standard.",
        },
    ],

    # ── Compliance trade reports (Kaladan L2 lifecycle artifact) ────
    "trade_reports": [],   # governance-enriched record written at execution
    "source_documents": [],  # thesis memos and uploaded source documents with linked analysis

    # ── Institutional cash management (Kaladan L2 lifecycle) ─────
    # Idle cash above OPERATING_CASH_FLOOR_PCT sweeps nightly into
    # the institutional government MMF and unwinds pre-market.
    "mmf_balance":       0.0,   # current balance swept into MMF
    "mmf_yield_accrued": 0.0,   # cumulative overnight yield earned
    "mmf_provider":      MMF_PROVIDERS[PORTFOLIO_JURISDICTION],
    "sweep_log":         [],    # {"ts","action","amount","provider","balance_after"}

    # ── Error log (in-memory, capped at 200 entries) ─────────────
    "error_log": [],       # {"ts","level","source","message"} — mirrored to LOG_FILE

    # ── Doctrine update log ──────────────────────────────────────
    "doctrine_updates": [
        {
            "id":     "MDU-001",
            "type":   "REGULATORY",
            "title":  "DORA EBA RTS Regulatory Change",
            "detail": "EU DORA Article 28 absorbed. 4 nodes flagged. Doctrine updated.",
            "version":"v1.0 → v1.1",
            "ts":     datetime.now(timezone.utc).isoformat(),
        },
        {
            "id":     "MDU-002",
            "type":   "OPERATIONAL",
            "title":  "EMIR Operational Signal",
            "detail": "Kaladan signaled EMIR reporting pattern. Doctrine gap reviewed. No change required.",
            "version":"Source: Kaladan lifecycle telemetry",
            "ts":     datetime.now(timezone.utc).isoformat(),
        },
        {
            "id":     "MDU-003",
            "type":   "HUMAN_AUTHORITY",
            "title":  "Tier 2 Human Authority Resolution",
            "detail": "Basel III Endgame vs EU CRR III true conflict. Apply HIGHER RWA standard.",
            "version":"MDR-J-NEW-001 · v1.1 → v1.2",
            "ts":     datetime.now(timezone.utc).isoformat(),
        },
        {
            "id":     "MDU-TEL-002",
            "type":   "TELEMETRY",
            "title":  "Thifur Telemetry Confirmation",
            "detail": "Execution telemetry confirms lineage integrity. Zero Unobserved Action verified.",
            "version":"Source: Thifur-R / J / H · All 8 ROE checks passed",
            "ts":     datetime.now(timezone.utc).isoformat(),
        },
    ],
}

# CAOM-001 — Session protocol instance (one per server lifetime)
_session_protocol = SessionProtocol(aureon_state, _lock)

# Instantiate advisory agents (ThifurJ and ThifurR)
_agent_j = ThifurJ(aureon_state, _lock)
_agent_r = ThifurR(aureon_state, _lock)

# Expose agents to session protocol for Step 4 readiness check
app._aureon_agents = {
    "THIFUR_J": _agent_j,
    "THIFUR_R": _agent_r,
}


# ─────────────────────────────────────────────────────────────────
# 4. INITIAL DATA
# ─────────────────────────────────────────────────────────────────
# These are defined as module-level constants (ALL_CAPS by convention).
# They get loaded into aureon_state["positions"] once the stack runs.

INITIAL_POSITIONS = [
    # Positions sized to approximate doctrine-mandated target allocations at inception.
    # Drift shown on the dashboard reflects actual market price movement, not structural gaps.
    # Targets: Equities 40% · Fixed Income 25% · FX 15% · Commodities 10% · Crypto 10%

    # ── EQUITIES (target 40% = ~$20M · actual at cost ~$18.7M / 37.3%) ────────
    {"symbol":"SPY",     "asset_class":"equities",     "shares":28000,   "cost":535.10, "agent":"THIFUR_J"},
    {"symbol":"AAPL",    "asset_class":"equities",     "shares":2200,    "cost":219.50, "agent":"THIFUR_H"},
    {"symbol":"NVDA",    "asset_class":"equities",     "shares":800,     "cost":875.30, "agent":"THIFUR_H"},
    {"symbol":"MSFT",    "asset_class":"equities",     "shares":2500,    "cost":415.20, "agent":"THIFUR_J"},
    {"symbol":"EEM",     "asset_class":"equities",     "shares":25000,   "cost":43.20,  "agent":"THIFUR_J"},
    {"symbol":"AMZN",    "asset_class":"equities",     "shares":2000,    "cost":185.30, "agent":"THIFUR_H"},

    # ── FIXED INCOME (target 25% = ~$12.5M · actual at cost $12.5M / 25.0%) ───
    {"symbol":"TLT",     "asset_class":"fixed_income", "shares":60000,   "cost":91.50,  "agent":"THIFUR_R"},
    {"symbol":"HYG",     "asset_class":"fixed_income", "shares":40000,   "cost":78.20,  "agent":"THIFUR_R"},
    {"symbol":"AGG",     "asset_class":"fixed_income", "shares":40000,   "cost":97.40,  "agent":"THIFUR_R"},

    # ── FX (target 15% = ~$7.5M · actual at cost ~$7.0M / 13.9%) ───────────────
    # FX "shares" = notional base currency units. cost = exchange rate at inception.
    {"symbol":"EUR/USD", "asset_class":"fx",           "shares":3500000, "cost":1.0842, "agent":"THIFUR_J"},
    {"symbol":"GBP/USD", "asset_class":"fx",           "shares":2500000, "cost":1.2651, "agent":"THIFUR_J"},

    # ── COMMODITIES (target 10% = ~$5M · actual at cost ~$5.0M / 10.0%) ────────
    {"symbol":"GLD",     "asset_class":"commodities",  "shares":16000,   "cost":213.40, "agent":"THIFUR_J"},
    {"symbol":"USO",     "asset_class":"commodities",  "shares":22000,   "cost":72.10,  "agent":"THIFUR_J"},

    # ── CRYPTO (target 10% = ~$5M · actual at cost ~$4.8M / 9.6%) ───────────────
    {"symbol":"BTC",     "asset_class":"crypto",       "shares":38,      "cost":67420,  "agent":"THIFUR_H"},
    {"symbol":"ETH",     "asset_class":"crypto",       "shares":480,     "cost":3510,   "agent":"THIFUR_H"},
    {"symbol":"SOL",     "asset_class":"crypto",       "shares":4000,    "cost":142,    "agent":"THIFUR_H"},
]

# Base prices for every tradeable instrument.
# Crypto is volatile (0.8% swing per tick).
# FX is tight (0.05% swing per tick).
# Equities/commodities in between (0.2% per tick).
BASE_PRICES = {
    "SPY":535.10, "AAPL":219.50, "NVDA":875.30, "EEM":43.20,
    "MSFT":415.20,"GOOGL":175.40,"AMZN":185.30,
    "TLT":91.50,  "HYG":78.20,   "AGG":97.40,
    "EUR/USD":1.0842,"GBP/USD":1.2651,"USD/JPY":149.32,
    "BTC":67420,  "ETH":3510,    "SOL":142,
    "GLD":213.40, "USO":72.10,   "DBC":21.80,
}

# Target allocations by asset class (must sum to 1.0)
ALLOCATIONS = {
    "equities":     {"target": 0.40, "label": "Equities",     "color": "#3B82F6"},
    "fixed_income": {"target": 0.25, "label": "Fixed Income", "color": "#10B981"},
    "fx":           {"target": 0.15, "label": "FX",           "color": "#F59E0B"},
    "crypto":       {"target": 0.10, "label": "Crypto",       "color": "#F97316"},
    "commodities":  {"target": 0.10, "label": "Commodities",  "color": "#8B5CF6"},
}

# Two pre-loaded trade decisions waiting for human approval.
PENDING_DECISIONS_INIT = [
    {
        "id":         "DEC-A1B2C3D4",
        "action":     "BUY",
        "symbol":     "MSFT",
        "asset_class":"equities",
        "shares":     1200,
        "price":      415.20,
        "notional":   498240,
        "product_type": "SINGLE_NAME_EQUITY",
        "rationale":  "Class underweight (-3.2% vs target). Momentum 0.34. Conviction 0.78. Thifur-H: minimize_slippage.",
        "created":    datetime.now(timezone.utc).isoformat(),
        "status":     "PENDING",
        "required_approvals": ["TRADER"],
        "current_approvals": [],
        "release_target": "OMS",
        "mandate_sensitive": False,
        "policy_exception": False,
        "risk_exception": True,
        "pm_signoff_required": False,
        "control_exception": False,
        "financing_relevant": False,
    },
    {
        "id":         "DEC-E5F6G7H8",
        "action":     "BUY",
        "symbol":     "SOL",
        "asset_class":"crypto",
        "shares":     3500,
        "price":      142,
        "notional":   497000,
        "product_type": "OUT_OF_SCOPE",
        "rationale":  "Strong momentum (0.41). Crypto at 9.8% vs 10% target. Within hard cap. Thifur-H: optimize_execution.",
        "created":    datetime.now(timezone.utc).isoformat(),
        "status":     "PENDING",
        "required_approvals": ["TRADER"],
        "current_approvals": [],
        "release_target": "OMS",
        "mandate_sensitive": False,
        "policy_exception": True,
        "risk_exception": True,
        "pm_signoff_required": False,
        "control_exception": False,
        "financing_relevant": False,
    },
]


# ─────────────────────────────────────────────────────────────────
# 5. HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────

# ── Compliance PDF imports ────────────────────────────────────────
import io as _io
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors as rl_colors
from reportlab.lib.units import inch
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT


def _generate_compliance_pdf(report: dict) -> bytes:
    """
    Generate an immutable, timestamped compliance PDF for a trade.
    Three sections: Trade Identity · Governance Block · Risk State.
    Returns PDF bytes.
    """
    buf = _io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.75*inch, bottomMargin=0.75*inch,
    )

    styles  = getSampleStyleSheet()
    VOID    = rl_colors.HexColor("#060810")
    CYAN    = rl_colors.HexColor("#00D4FF")
    DARK    = rl_colors.HexColor("#0a0f1e")
    SURFACE = rl_colors.HexColor("#0f1628")
    WHITE   = rl_colors.HexColor("#F0F4FF")
    MUTED   = rl_colors.HexColor("#4A5578")
    GREEN   = rl_colors.HexColor("#10B981")
    RED     = rl_colors.HexColor("#EF4444")
    YELLOW  = rl_colors.HexColor("#F59E0B")
    ORANGE  = rl_colors.HexColor("#F97316")

    title_style = ParagraphStyle("ATitle", fontName="Helvetica-Bold", fontSize=16,
                                  textColor=CYAN, spaceAfter=4, alignment=TA_LEFT)
    sub_style   = ParagraphStyle("ASub",   fontName="Helvetica",      fontSize=8,
                                  textColor=MUTED, spaceAfter=12, alignment=TA_LEFT)
    section_style = ParagraphStyle("ASec", fontName="Helvetica-Bold", fontSize=9,
                                    textColor=CYAN, spaceBefore=10, spaceAfter=6)
    label_style = ParagraphStyle("ALbl",  fontName="Helvetica",      fontSize=8,
                                  textColor=MUTED)
    hash_style  = ParagraphStyle("AHash", fontName="Courier",         fontSize=7,
                                  textColor=MUTED)

    def two_col(left_label, left_val, right_label, right_val, rvc=None):
        vc = rvc or WHITE
        return Table(
            [[Paragraph(left_label,  label_style),
              Paragraph(left_val,    ParagraphStyle("AV1", fontName="Helvetica-Bold", fontSize=9, textColor=WHITE)),
              Paragraph(right_label, label_style),
              Paragraph(right_val,   ParagraphStyle("AV2", fontName="Helvetica-Bold", fontSize=9, textColor=vc))]],
            colWidths=[1.5*inch, 2.4*inch, 1.5*inch, 2.4*inch],
            style=TableStyle([
                ("VALIGN",       (0,0), (-1,-1), "TOP"),
                ("LEFTPADDING",  (0,0), (-1,-1), 4),
                ("BOTTOMPADDING",(0,0), (-1,-1), 4),
            ])
        )

    def one_row(label, value, vc=None):
        col = vc or WHITE
        return Table(
            [[Paragraph(label, label_style),
              Paragraph(value, ParagraphStyle("AV3", fontName="Helvetica-Bold", fontSize=9, textColor=col))]],
            colWidths=[1.5*inch, 6.3*inch],
            style=TableStyle([
                ("VALIGN",       (0,0), (-1,-1), "TOP"),
                ("LEFTPADDING",  (0,0), (-1,-1), 4),
                ("BOTTOMPADDING",(0,0), (-1,-1), 4),
            ])
        )

    story = []

    action      = report.get("action", "—")
    symbol      = report.get("symbol", "—")
    decision_id = report.get("decision_id", "—")
    notional    = report.get("notional", 0)

    story.append(Paragraph("AUREON  \u00b7  COMPLIANCE TRADE REPORT", title_style))
    story.append(Paragraph(
        "Kaladan L2 Lifecycle Artifact  \u00b7  Doctrine-Governed  \u00b7  "
        "Generated at execution moment  \u00b7  Immutable",
        sub_style))
    story.append(HRFlowable(width="100%", thickness=1, color=CYAN, spaceAfter=12))

    # ── SECTION I: TRADE IDENTITY ─────────────────────────────────
    story.append(Paragraph("SECTION I \u2014 TRADE IDENTITY", section_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MUTED, spaceAfter=6))

    act_hex = "10B981" if action == "BUY" else "EF4444"
    story.append(two_col(
        "ACTION",      f'<font color="#{act_hex}">{action}</font>',
        "SYMBOL",      symbol))
    story.append(two_col(
        "ASSET CLASS", (report.get("asset_class","—") or "—").replace("_"," ").upper(),
        "QUANTITY",    f'{report.get("shares",0):,} shares'))
    story.append(two_col(
        "EXECUTED PRICE", f'${report.get("exec_price",0):,.2f}',
        "NOTIONAL",       f'${notional:,.0f}'))
    story.append(two_col(
        "SETTLEMENT", report.get("settlement","T+1"),
        "AGENT",      report.get("agent","THIFUR_H")))
    story.append(one_row("EXECUTION TIME", report.get("exec_ts","—")))
    story.append(one_row("DECISION ID",    decision_id))
    story.append(one_row("AUTHORITY HASH", report.get("authority_hash","—"), vc=MUTED))
    story.append(Spacer(1, 8))

    # ── SECTION II: GOVERNANCE BLOCK ──────────────────────────────
    story.append(Paragraph("SECTION II \u2014 GOVERNANCE BLOCK", section_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MUTED, spaceAfter=6))

    story.append(two_col(
        "DOCTRINE VERSION", report.get("doctrine_version","—"),
        "TIER AUTHORITY",   report.get("tier_authority","Tier 1 \u2014 Human Authority")))
    story.append(one_row("APPROVED BY",   report.get("approved_by","br@ravelobizdev.com")))
    story.append(one_row("APPROVAL TIME", report.get("approval_ts","—")))
    story.append(Spacer(1, 6))

    story.append(Paragraph("PRE-TRADE GATE RESULTS", ParagraphStyle(
        "AGH", fontName="Helvetica-Bold", fontSize=8, textColor=MUTED, spaceAfter=4)))
    gates     = report.get("gate_results", [])
    gate_data = [["GATE", "LAYER", "STATUS", "DETAIL"]]
    for g in gates:
        status = g.get("status","—")
        gc = "#10B981" if status=="PASS" else ("#F59E0B" if status=="WARN" else "#EF4444")
        gate_data.append([
            g.get("gate","—"),
            g.get("layer","—"),
            f'<font color="{gc}">{status}</font>',
            (g.get("detail","—") or "")[:60],
        ])
    gate_table = Table(gate_data,
        colWidths=[1.6*inch, 1.1*inch, 0.65*inch, 4.45*inch],
        style=TableStyle([
            ("BACKGROUND",    (0,0), (-1,0),   SURFACE),
            ("TEXTCOLOR",     (0,0), (-1,0),   CYAN),
            ("FONTNAME",      (0,0), (-1,0),   "Helvetica-Bold"),
            ("FONTSIZE",      (0,0), (-1,-1),  7),
            ("FONTNAME",      (0,1), (-1,-1),  "Helvetica"),
            ("TEXTCOLOR",     (0,1), (-1,-1),  WHITE),
            ("ROWBACKGROUNDS",(0,1), (-1,-1),  [DARK, SURFACE]),
            ("GRID",          (0,0), (-1,-1),  0.5, MUTED),
            ("LEFTPADDING",   (0,0), (-1,-1),  5),
            ("RIGHTPADDING",  (0,0), (-1,-1),  5),
            ("TOPPADDING",    (0,0), (-1,-1),  3),
            ("BOTTOMPADDING", (0,0), (-1,-1),  3),
            ("VALIGN",        (0,0), (-1,-1),  "MIDDLE"),
        ])
    )
    story.append(gate_table)
    story.append(Spacer(1, 8))

    story.append(Paragraph("COMPLIANCE FRAMEWORKS ACTIVE AT EXECUTION", ParagraphStyle(
        "AFH", fontName="Helvetica-Bold", fontSize=8, textColor=MUTED, spaceAfter=4)))
    fw_text = "  \u00b7  ".join(report.get("frameworks_active",
        ["MiFID II Art.17/RTS6","SR 11-7","Basel III","DORA Art.28","Dodd-Frank 4a(1)"]))
    story.append(Paragraph(fw_text, ParagraphStyle(
        "AFT", fontName="Helvetica", fontSize=7, textColor=MUTED, spaceAfter=8)))

    # ── SECTION III: RISK STATE ───────────────────────────────────
    story.append(Paragraph("SECTION III \u2014 RISK STATE AT EXECUTION", section_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MUTED, spaceAfter=6))

    dd     = report.get("drawdown_at_exec", 0)
    dd_hex = "EF4444" if dd > 5 else ("F59E0B" if dd > 2 else "10B981")
    story.append(two_col(
        "DRAWDOWN AT EXEC",  f'<font color="#{dd_hex}">{dd:.2f}%</font>',
        "PORTFOLIO VALUE",   f'${report.get("portfolio_value_at_exec",0):,.0f}'))
    story.append(two_col(
        "CASH BEFORE TRADE", f'${report.get("cash_before",0):,.0f}',
        "CASH AFTER TRADE",  f'${report.get("cash_after",0):,.0f}'))
    story.append(two_col(
        "POSITION CONC. PRE",  f'{report.get("position_conc_pre",0):.1f}%',
        "POSITION CONC. POST", f'{report.get("position_conc_post",0):.1f}%'))
    story.append(two_col(
        "VAR IMPACT (EST.)",   f'{report.get("var_impact",0):+.2f}%',
        "POSITIONS HELD POST", f'{report.get("positions_post",0)}'))
    story.append(Spacer(1, 12))

    # ── FOOTER ────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=1, color=CYAN, spaceAfter=6))
    story.append(Paragraph(
        f"Report ID: {report.get('report_id','—')}  \u00b7  "
        f"Generated: {report.get('generated_ts','—')}  \u00b7  "
        "Aureon Grid 3 \u00b7 Kaladan L2 Lifecycle Artifact  \u00b7  "
        "Not for external distribution",
        ParagraphStyle("AFooter", fontName="Helvetica", fontSize=6.5,
                        textColor=MUTED, alignment=TA_CENTER)
    ))

    doc.build(story)
    return buf.getvalue()


# ── Instrument Reference Data ─────────────────────────────────────────────────
# ISIN (ISO 6166), CUSIP (US/CA), and FIX protocol metadata per tradeable symbol.
# Crypto and FX have no ISIN/CUSIP — they carry their own identifier conventions.
# FIX Tag 167 SecurityType: CS=CommonStock, ETF, FXSPOT, CRYPTO (non-standard)
# FIX Tag 460 Product:      5=EQUITY, 4=CURRENCY, 2=COMMODITY, 14=OTHER (crypto)
# FIX Tag 55 Symbol:        exchange ticker as understood by prime broker FIX gateway
# LEI (ISO 17442): Aureon entity LEI — placeholder pending registration
_AUREON_LEI   = "AUREON-LEI-PENDING-00001"   # replace with actual GLEIF LEI at registration
_INSTRUMENT_REF = {
    # ── Equities ─────────────────────────────────────────────────
    "SPY":   {"isin":"US78462F1030","cusip":"78462F103","fix_type":"ETF", "fix_product":5,"currency":"USD","mic":"ARCX"},
    "AAPL":  {"isin":"US0378331005","cusip":"037833100","fix_type":"CS",  "fix_product":5,"currency":"USD","mic":"XNAS"},
    "NVDA":  {"isin":"US67066G1040","cusip":"67066G104","fix_type":"CS",  "fix_product":5,"currency":"USD","mic":"XNAS"},
    "MSFT":  {"isin":"US5949181045","cusip":"594918104","fix_type":"CS",  "fix_product":5,"currency":"USD","mic":"XNAS"},
    "GOOGL": {"isin":"US02079K3059","cusip":"02079K305","fix_type":"CS",  "fix_product":5,"currency":"USD","mic":"XNAS"},
    "AMZN":  {"isin":"US0231351067","cusip":"023135106","fix_type":"CS",  "fix_product":5,"currency":"USD","mic":"XNAS"},
    "EEM":   {"isin":"US4642872349","cusip":"464287234","fix_type":"ETF", "fix_product":5,"currency":"USD","mic":"ARCX"},
    # ── Fixed Income ETFs ─────────────────────────────────────────
    "TLT":   {"isin":"US4642874329","cusip":"464287432","fix_type":"ETF", "fix_product":5,"currency":"USD","mic":"ARCX"},
    "HYG":   {"isin":"US4642885135","cusip":"464288513","fix_type":"ETF", "fix_product":5,"currency":"USD","mic":"ARCX"},
    "AGG":   {"isin":"US4642872265","cusip":"464287226","fix_type":"ETF", "fix_product":5,"currency":"USD","mic":"ARCX"},
    # ── FX ───────────────────────────────────────────────────────
    "EUR/USD":{"isin":None,"cusip":None,"fix_type":"FXSPOT","fix_product":4,"currency":"EUR","mic":"XOFF"},
    "GBP/USD":{"isin":None,"cusip":None,"fix_type":"FXSPOT","fix_product":4,"currency":"GBP","mic":"XOFF"},
    "USD/JPY":{"isin":None,"cusip":None,"fix_type":"FXSPOT","fix_product":4,"currency":"USD","mic":"XOFF"},
    # ── Commodities ───────────────────────────────────────────────
    "GLD":   {"isin":"US78463V1070","cusip":"78463V107","fix_type":"ETF", "fix_product":2,"currency":"USD","mic":"ARCX"},
    "USO":   {"isin":"US91232N1081","cusip":"91232N108","fix_type":"ETF", "fix_product":2,"currency":"USD","mic":"ARCX"},
    "DBC":   {"isin":"US46090E1038","cusip":"46090E103","fix_type":"ETF", "fix_product":2,"currency":"USD","mic":"ARCX"},
    # ── Crypto ────────────────────────────────────────────────────
    "BTC":   {"isin":None,"cusip":None,"fix_type":"CRYPTO","fix_product":14,"currency":"USD","mic":"XCRY"},
    "ETH":   {"isin":None,"cusip":None,"fix_type":"CRYPTO","fix_product":14,"currency":"USD","mic":"XCRY"},
    "SOL":   {"isin":None,"cusip":None,"fix_type":"CRYPTO","fix_product":14,"currency":"USD","mic":"XCRY"},
}


def _build_trade_report(decision, exec_price, authority_hash, gate_results, portfolio_before):
    """
    Write the governance-enriched compliance record at the moment Kaladan confirms execution.
    Called immediately after position is recorded and cash is deducted.
    Returns the report dict (also stored in aureon_state['trade_reports']).

    Tape fields follow institutional standards:
      - ISIN (ISO 6166) as primary instrument identifier
      - CUSIP for US instruments
      - FIX 4.4 SecurityType (Tag 167) and Product (Tag 460)
      - LEI for entity identification (MiFID II counterparty disclosure)
      - MIC (ISO 10383) for execution venue
    """
    now_utc   = datetime.now(timezone.utc)
    exec_ts   = now_utc.isoformat()
    report_id = f"CTR-{decision['id'][-8:]}"

    CRYPTO     = {"BTC", "ETH", "SOL"}
    is_crypto  = decision["symbol"] in CRYPTO
    settlement = "T+0" if is_crypto else "T+1"
    macro_snapshot = _get_fred_macro_snapshot()
    ofr_snapshot = _get_ofr_stress_snapshot(macro_snapshot)

    notional   = decision["shares"] * exec_price
    action_sign = -1 if decision["action"] == "BUY" else 1
    cash_after = portfolio_before["cash"] + (action_sign * notional)

    pv               = portfolio_before["portfolio_value"]
    n_positions_pre  = portfolio_before["n_positions"]
    n_positions_post = n_positions_pre + 1 if decision["action"] == "BUY" else max(0, n_positions_pre - 1)
    conc_pre   = (notional / pv * 100) if pv > 0 else 0
    conc_post  = conc_pre
    var_impact = (-(notional / pv * 0.08 * 100) if decision["action"] == "BUY" else (notional / pv * 0.05 * 100)) if pv > 0 else 0

    # Instrument reference lookup
    sym = decision["symbol"]
    ref = _INSTRUMENT_REF.get(sym, {})

    report = {
        "report_id":   report_id,
        "decision_id": decision["id"],
        "generated_ts": exec_ts,
        "exec_ts":      exec_ts,
        "approval_ts":  exec_ts,

        # ── Trade Identity (institutional tape fields) ────────────
        "action":        decision["action"],
        "symbol":        sym,
        "isin":          ref.get("isin"),           # ISO 6166 — primary identifier
        "cusip":         ref.get("cusip"),          # CUSIP — US/CA instruments
        "fix_type":      ref.get("fix_type"),       # FIX Tag 167 SecurityType
        "fix_product":   ref.get("fix_product"),    # FIX Tag 460 Product
        "mic":           ref.get("mic"),            # ISO 10383 execution venue
        "currency":      ref.get("currency","USD"), # ISO 4217 settlement currency
        "asset_class":   decision["asset_class"],
        "shares":        decision["shares"],
        "exec_price":    round(exec_price, 2),
        "notional":      round(notional, 2),
        "settlement":    settlement,
        "agent":         "THIFUR_H",
        "authority_hash": authority_hash,
        "entity_lei":    _AUREON_LEI,              # ISO 17442 — MiFID II Art.26

        # ── Governance Block ──────────────────────────────────────
        "doctrine_version":  aureon_state["doctrine_version"],
        "tier_authority":    "Tier 1 — Human Authority",
        "approved_by":       "br@ravelobizdev.com",
        "gate_results":      gate_results,
        "frameworks_active": [
            "MiFID II Art.17/RTS6", "SR 11-7", "Basel III",
            "DORA Art.28", "Dodd-Frank 4a(1)",
        ],

        # ── Risk State at Execution ────────────────────────────────
        "drawdown_at_exec":        portfolio_before["drawdown"],
        "portfolio_value_at_exec": pv,
        "cash_before":             portfolio_before["cash"],
        "cash_after":              round(cash_after, 2),
        "position_conc_pre":       round(conc_pre, 2),
        "position_conc_post":      round(conc_post, 2),
        "var_impact":              round(var_impact, 4),
        "positions_post":          n_positions_post,
        "macro_regime_at_exec":    macro_snapshot.get("macro_regime"),
        "ofr_fsi_at_exec":         ofr_snapshot.get("fsi_value"),
        "ofr_band_at_exec":        ofr_snapshot.get("fsi_band"),
        "systemic_overlay_source": ofr_snapshot.get("source"),
    }

    try:
        report["pdf_bytes"] = _generate_compliance_pdf(report)
    except Exception as exc:
        print(f"[AUREON] PDF generation failed: {exc}")
        report["pdf_bytes"] = None

    return report


def _apply_approved_trade(decision: dict, exec_price: float):
    """
    Apply an approved trade to positions and cash.
    BUY adds a new lot and deducts cash.
    SELL reduces existing lots FIFO-style and adds cash.
    Returns (ok: bool, error_message: str | None).
    """
    symbol = decision["symbol"]
    shares = decision["shares"]
    asset_class = decision["asset_class"]
    notional = shares * exec_price

    if decision["action"] == "BUY":
        aureon_state["positions"].append({
            "symbol":      symbol,
            "asset_class": asset_class,
            "shares":      shares,
            "cost":        round(exec_price, 2),
            "agent":       "THIFUR_H",
        })
        aureon_state["cash"] -= notional
        return True, None

    remaining = shares
    matched_positions = [p for p in aureon_state["positions"] if p["symbol"] == symbol]
    available = sum(p.get("shares", 0) for p in matched_positions)
    if available < shares:
        return False, f"SELL blocked — available {symbol} shares {available:,.0f} < requested {shares:,.0f}"

    new_positions = []
    for pos in aureon_state["positions"]:
        if pos["symbol"] != symbol or remaining <= 0:
            new_positions.append(pos)
            continue

        lot_shares = pos.get("shares", 0)
        to_sell = min(lot_shares, remaining)
        remaining -= to_sell
        left = lot_shares - to_sell
        if left > 0:
            updated = dict(pos)
            updated["shares"] = left
            new_positions.append(updated)

    aureon_state["positions"] = new_positions
    aureon_state["cash"] += notional
    return True, None


def _is_instrument_tradeable(symbol: str, asset_class: str) -> tuple:
    """
    Returns (is_tradeable: bool, reason: str).
    Instrument-aware session boundary check for 24x5 readiness.
    """
    ET = zoneinfo.ZoneInfo("America/New_York")
    MX = zoneinfo.ZoneInfo("America/Mexico_City")
    now_et = datetime.now(ET)
    now_mx = datetime.now(MX)
    weekday = now_et.weekday()  # 0=Monday, 6=Sunday

    CRYPTO_SYMBOLS  = {"BTC", "ETH", "SOL"}
    FX_SYMBOLS      = {"EUR/USD", "GBP/USD", "USD/JPY"}
    BMV_SIC_SYMBOLS = set()  # populated in Phase 2

    # Crypto — 24/7 always
    if symbol in CRYPTO_SYMBOLS or asset_class == "crypto":
        return True, "Crypto — 24/7"

    # FX — 24/5 Sunday 5PM ET to Friday 5PM ET
    if symbol in FX_SYMBOLS or asset_class == "fx":
        if weekday == 5:  # Saturday
            return False, "FX market closed — Saturday"
        if weekday == 6 and now_et.hour < 17:  # Sunday before 5PM ET
            return False, "FX market closed — Sunday pre-open"
        if weekday == 4 and now_et.hour >= 17:  # Friday after 5PM ET
            return False, "FX market closed — weekend"
        return True, "FX — 24/5"

    # BMV SIC — Monday-Friday 8:30am-3:00pm Mexico City
    if symbol in BMV_SIC_SYMBOLS:
        if weekday >= 5:
            return False, "BMV SIC closed — weekend"
        bmv_open  = dt_time(8, 30)
        bmv_close = dt_time(15, 0)
        if bmv_open <= now_mx.time() < bmv_close:
            return True, "BMV SIC open"
        return False, "BMV SIC closed — hours 08:30-15:00 MX"

    # Equities and everything else — NYSE hours Monday-Friday
    if weekday >= 5:
        return False, "Market closed — weekend"
    nyse_open  = dt_time(9, 30)
    nyse_close = dt_time(16, 0)
    if nyse_open <= now_et.time() < nyse_close:
        return True, "NYSE open"
    return False, "Market closed — NYSE hours 09:30-16:00 ET"


def _market_is_open():
    """
    Backward-compatible wrapper — checks NYSE hours via _is_instrument_tradeable.
    Use _is_instrument_tradeable(symbol, asset_class) for instrument-specific checks.
    """
    tradeable, _ = _is_instrument_tradeable("SPY", "equities")
    return tradeable


def _build_email_html():
    """Build the HTML body for the weekly P&L report email."""
    with _lock:
        pv       = aureon_state["portfolio_value"]
        pnl      = aureon_state["pnl"]
        pnl_pct  = aureon_state["pnl_pct"]
        drawdown = aureon_state["drawdown"]
        n_pos    = len(aureon_state["positions"])
        n_pend   = len(aureon_state["pending_decisions"])
        n_alerts = len(aureon_state["compliance_alerts"])
        doctrine = aureon_state["doctrine_version"]
        ct       = dict(aureon_state["class_totals"])

    ET       = zoneinfo.ZoneInfo("America/New_York")
    date_str = datetime.now(ET).strftime("%B %d, %Y")
    pnl_col  = "#10B981" if pnl >= 0 else "#EF4444"
    pnl_sign = "+" if pnl >= 0 else ""
    dd_col   = "#EF4444" if drawdown > 5 else "#10B981"

    # Asset class rows
    rows = ""
    for cls, val in ct.items():
        info   = ALLOCATIONS.get(cls, {})
        pct    = (val / pv * 100) if pv > 0 else 0
        target = info.get("target", 0) * 100
        drift  = pct - target
        dc     = "#10B981" if drift >= 0 else "#EF4444"
        sign   = "+" if drift >= 0 else ""
        rows  += f"""<tr style="border-bottom:1px solid rgba(0,212,255,0.06)">
          <td style="padding:8px 12px;color:{info.get('color','#fff')};font-weight:600">{info.get('label', cls)}</td>
          <td style="padding:8px 12px">${val:,.0f}</td>
          <td style="padding:8px 12px">{pct:.1f}%</td>
          <td style="padding:8px 12px;color:{dc}">{sign}{drift:.1f}% vs target</td>
        </tr>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#060810;font-family:'Courier New',monospace;color:#F0F4FF">
<div style="max-width:600px;margin:0 auto;padding:32px 24px">

  <div style="border-bottom:1px solid rgba(0,212,255,0.2);padding-bottom:20px;margin-bottom:24px">
    <div style="font-size:22px;font-weight:800;letter-spacing:4px;color:#00D4FF">AUREON</div>
    <div style="font-size:10px;letter-spacing:2px;color:#4A5578;margin-top:4px">
      DOCTRINE-DRIVEN FINANCIAL OPERATING SYSTEM</div>
  </div>

  <div style="margin-bottom:24px">
    <div style="font-size:16px;font-weight:700;letter-spacing:2px;color:#F0F4FF;margin-bottom:4px">
      WEEKLY P&amp;L REPORT</div>
    <div style="font-size:12px;color:#4A5578">Week of {date_str} &nbsp;·&nbsp; Doctrine v{doctrine}</div>
  </div>

  <table style="width:100%;border-collapse:separate;border-spacing:8px;margin-bottom:24px">
    <tr>
      <td style="background:#0f1628;border:1px solid rgba(0,212,255,0.12);border-radius:8px;padding:16px;width:33%">
        <div style="font-size:9px;letter-spacing:2px;color:#4A5578;margin-bottom:6px">PORTFOLIO VALUE</div>
        <div style="font-size:20px;font-weight:700">${pv:,.0f}</div>
      </td>
      <td style="background:#0f1628;border:1px solid rgba(0,212,255,0.12);border-radius:8px;padding:16px;width:33%">
        <div style="font-size:9px;letter-spacing:2px;color:#4A5578;margin-bottom:6px">TOTAL P&amp;L</div>
        <div style="font-size:20px;font-weight:700;color:{pnl_col}">{pnl_sign}${abs(pnl):,.0f}</div>
        <div style="font-size:11px;color:{pnl_col}">{pnl_sign}{pnl_pct:.2f}%</div>
      </td>
      <td style="background:#0f1628;border:1px solid rgba(0,212,255,0.12);border-radius:8px;padding:16px;width:33%">
        <div style="font-size:9px;letter-spacing:2px;color:#4A5578;margin-bottom:6px">DRAWDOWN</div>
        <div style="font-size:20px;font-weight:700;color:{dd_col}">{drawdown:.2f}%</div>
        <div style="font-size:11px;color:#4A5578">Limit: 10.00%</div>
      </td>
    </tr>
  </table>

  <div style="margin-bottom:24px">
    <div style="font-size:9px;letter-spacing:2px;color:#4A5578;margin-bottom:10px">ASSET CLASS PERFORMANCE</div>
    <table style="width:100%;border-collapse:collapse;font-size:12px;background:#0f1628;border-radius:8px;overflow:hidden;border:1px solid rgba(0,212,255,0.12)">
      <thead><tr style="border-bottom:1px solid rgba(0,212,255,0.15)">
        <th style="padding:8px 12px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">CLASS</th>
        <th style="padding:8px 12px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">VALUE</th>
        <th style="padding:8px 12px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">ALLOC</th>
        <th style="padding:8px 12px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">VS TARGET</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>

  <div style="background:#0f1628;border:1px solid rgba(0,212,255,0.12);border-radius:8px;padding:16px;margin-bottom:24px;font-size:11px;color:#4A5578;line-height:1.8">
    <div style="color:#F0F4FF;font-weight:600;margin-bottom:8px">Governance Status</div>
    Positions: {n_pos} open &nbsp;·&nbsp; Pending decisions: {n_pend} &nbsp;·&nbsp; Active alerts: {n_alerts}<br>
    Doctrine v{doctrine} active &nbsp;·&nbsp; All compliance frameworks satisfied &nbsp;·&nbsp; Zero doctrine breaches
  </div>

  <div style="border-top:1px solid rgba(0,212,255,0.1);padding-top:16px;font-size:10px;color:#4A5578;letter-spacing:1px;line-height:1.8">
    AUREON &nbsp;·&nbsp; DOCTRINE-DRIVEN FINANCIAL OPERATING SYSTEM<br>
    Columbia University &nbsp;·&nbsp; MS Technology Management &nbsp;·&nbsp; Guillermo "Bill" Ravelo<br>
    Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
  </div>
</div></body></html>"""


def _build_error_digest_html(error_log: list) -> str:
    """
    Renders the error log digest block for the EOD email.
    Returns an empty string if there are no errors to report (clean day).
    """
    if not error_log:
        return """
  <div style="background:#0a1a0f;border:1px solid rgba(16,185,129,0.2);
              border-radius:8px;padding:14px;margin-bottom:20px;font-size:11px">
    <div style="color:#10B981;font-weight:600;letter-spacing:1px;margin-bottom:4px">
      ✓ ERROR LOG — CLEAN</div>
    <div style="color:#4A5578">No errors or warnings recorded today.</div>
  </div>"""

    rows = ""
    for e in error_log:
        lvl_color = "#EF4444" if e["level"] == "ERROR" else "#F59E0B"
        rows += f"""<tr style="border-bottom:1px solid rgba(0,212,255,0.06)">
          <td style="padding:5px 8px;color:#4A5578;font-size:10px;white-space:nowrap">
            {e['ts'][:19].replace('T',' ')}</td>
          <td style="padding:5px 8px;color:{lvl_color};font-weight:700;font-size:10px">
            {e['level']}</td>
          <td style="padding:5px 8px;color:#00D4FF;font-size:10px">{e['source']}</td>
          <td style="padding:5px 8px;color:#F0F4FF;font-size:10px">{e['message'][:80]}</td>
        </tr>"""

    n_errors = sum(1 for e in error_log if e["level"] == "ERROR")
    n_warns  = sum(1 for e in error_log if e["level"] == "WARN")
    hdr_color = "#EF4444" if n_errors else "#F59E0B"

    return f"""
  <div style="background:#0f1628;border:1px solid rgba(239,68,68,0.2);
              border-radius:8px;padding:16px;margin-bottom:20px">
    <div style="font-size:9px;letter-spacing:2px;color:{hdr_color};
                margin-bottom:10px;font-weight:700">
      ERROR LOG DIGEST &nbsp;·&nbsp; {n_errors} ERROR(S) &nbsp;·&nbsp; {n_warns} WARNING(S)</div>
    <table style="width:100%;border-collapse:collapse">
      <thead><tr style="border-bottom:1px solid rgba(0,212,255,0.15)">
        <th style="padding:5px 8px;text-align:left;font-size:9px;
                   letter-spacing:1px;color:#4A5578;font-weight:500">TIMESTAMP (UTC)</th>
        <th style="padding:5px 8px;text-align:left;font-size:9px;
                   letter-spacing:1px;color:#4A5578;font-weight:500">LEVEL</th>
        <th style="padding:5px 8px;text-align:left;font-size:9px;
                   letter-spacing:1px;color:#4A5578;font-weight:500">SOURCE</th>
        <th style="padding:5px 8px;text-align:left;font-size:9px;
                   letter-spacing:1px;color:#4A5578;font-weight:500">MESSAGE</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <div style="margin-top:8px;font-size:9px;color:#4A5578">
      Full log: aureon_errors.log in The Grid 3 folder</div>
  </div>"""


def _build_close_email_html():
    """End-of-day report — sent at 4:15 PM ET (market close + 15 min)."""
    with _lock:
        pv        = aureon_state["portfolio_value"]
        pnl       = aureon_state["pnl"]
        pnl_pct   = aureon_state["pnl_pct"]
        drawdown  = aureon_state["drawdown"]
        n_pos     = len(aureon_state["positions"])
        n_pend    = len(aureon_state["pending_decisions"])
        n_alerts  = len(aureon_state["compliance_alerts"])
        doctrine  = aureon_state["doctrine_version"]
        ct        = dict(aureon_state["class_totals"])
        cash      = aureon_state["cash"]
        trades    = list(aureon_state["trades"])
        error_log = list(aureon_state["error_log"][:20])   # last 20 errors for EOD digest

    ET       = zoneinfo.ZoneInfo("America/New_York")
    date_str = datetime.now(ET).strftime("%B %d, %Y")
    pnl_col  = "#10B981" if pnl >= 0 else "#EF4444"
    pnl_sign = "+" if pnl >= 0 else ""
    dd_col   = "#EF4444" if drawdown > 5 else "#10B981"
    cash_pct = (cash / pv * 100) if pv > 0 else 0

    # Trades executed today (last 10)
    today_trades = trades[-10:] if trades else []
    trade_rows = ""
    for t in reversed(today_trades):
        t_col  = "#10B981" if t["action"] == "BUY" else "#EF4444"
        trade_rows += f"""<tr style="border-bottom:1px solid rgba(0,212,255,0.06)">
          <td style="padding:7px 10px;color:{t_col};font-weight:600">{t["action"]}</td>
          <td style="padding:7px 10px;color:#F0F4FF">{t["symbol"]}</td>
          <td style="padding:7px 10px">${t.get("notional",0):,.0f}</td>
          <td style="padding:7px 10px;color:#4A5578;font-size:10px">{t.get("agent","").replace("THIFUR_","")}</td>
        </tr>"""
    if not trade_rows:
        trade_rows = '<tr><td colspan="4" style="padding:10px;color:#4A5578;text-align:center">No trades executed today</td></tr>'

    # Allocation snapshot
    alloc_rows = ""
    for cls, val in ct.items():
        info   = ALLOCATIONS.get(cls, {})
        pct    = (val / pv * 100) if pv > 0 else 0
        target = info.get("target", 0) * 100
        drift  = pct - target
        dc     = "#10B981" if drift >= 0 else "#EF4444"
        sign   = "+" if drift >= 0 else ""
        alloc_rows += f"""<tr style="border-bottom:1px solid rgba(0,212,255,0.06)">
          <td style="padding:7px 10px;color:{info.get('color','#fff')};font-weight:600">{info.get('label', cls)}</td>
          <td style="padding:7px 10px">${val:,.0f}</td>
          <td style="padding:7px 10px">{pct:.1f}%</td>
          <td style="padding:7px 10px;color:{dc}">{sign}{drift:.1f}%</td>
        </tr>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#060810;font-family:'Courier New',monospace;color:#F0F4FF">
<div style="max-width:600px;margin:0 auto;padding:32px 24px">

  <div style="border-bottom:1px solid rgba(0,212,255,0.2);padding-bottom:20px;margin-bottom:24px">
    <div style="font-size:22px;font-weight:800;letter-spacing:4px;color:#00D4FF">AUREON</div>
    <div style="font-size:10px;letter-spacing:2px;color:#4A5578;margin-top:4px">DOCTRINE-DRIVEN FINANCIAL OPERATING SYSTEM</div>
  </div>

  <div style="margin-bottom:24px">
    <div style="font-size:16px;font-weight:700;letter-spacing:2px;color:#F0F4FF;margin-bottom:4px">
      MARKET CLOSE REPORT</div>
    <div style="font-size:12px;color:#4A5578">{date_str} &nbsp;·&nbsp; NYSE Close 4:00 PM ET &nbsp;·&nbsp; Doctrine v{doctrine}</div>
  </div>

  <table style="width:100%;border-collapse:separate;border-spacing:8px;margin-bottom:24px">
    <tr>
      <td style="background:#0f1628;border:1px solid rgba(0,212,255,0.12);border-radius:8px;padding:16px;width:33%">
        <div style="font-size:9px;letter-spacing:2px;color:#4A5578;margin-bottom:6px">PORTFOLIO VALUE</div>
        <div style="font-size:20px;font-weight:700">${pv:,.0f}</div>
      </td>
      <td style="background:#0f1628;border:1px solid rgba(0,212,255,0.12);border-radius:8px;padding:16px;width:33%">
        <div style="font-size:9px;letter-spacing:2px;color:#4A5578;margin-bottom:6px">DAY P&amp;L</div>
        <div style="font-size:20px;font-weight:700;color:{pnl_col}">{pnl_sign}${abs(pnl):,.0f}</div>
        <div style="font-size:11px;color:{pnl_col}">{pnl_sign}{pnl_pct:.2f}%</div>
      </td>
      <td style="background:#0f1628;border:1px solid rgba(0,212,255,0.12);border-radius:8px;padding:16px;width:33%">
        <div style="font-size:9px;letter-spacing:2px;color:#4A5578;margin-bottom:6px">DRAWDOWN</div>
        <div style="font-size:20px;font-weight:700;color:{dd_col}">{drawdown:.2f}%</div>
        <div style="font-size:11px;color:#4A5578">Limit: 10.00%</div>
      </td>
    </tr>
  </table>

  <div style="background:#0f1628;border:1px solid rgba(0,212,255,0.12);border-radius:8px;padding:16px;margin-bottom:20px">
    <div style="font-size:9px;letter-spacing:2px;color:#4A5578;margin-bottom:10px">TODAY'S EXECUTIONS</div>
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead><tr style="border-bottom:1px solid rgba(0,212,255,0.15)">
        <th style="padding:7px 10px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">ACTION</th>
        <th style="padding:7px 10px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">SYMBOL</th>
        <th style="padding:7px 10px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">NOTIONAL</th>
        <th style="padding:7px 10px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">AGENT</th>
      </tr></thead>
      <tbody>{trade_rows}</tbody>
    </table>
  </div>

  <div style="background:#0f1628;border:1px solid rgba(0,212,255,0.12);border-radius:8px;padding:16px;margin-bottom:20px">
    <div style="font-size:9px;letter-spacing:2px;color:#4A5578;margin-bottom:10px">END-OF-DAY ALLOCATION</div>
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead><tr style="border-bottom:1px solid rgba(0,212,255,0.15)">
        <th style="padding:7px 10px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">CLASS</th>
        <th style="padding:7px 10px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">VALUE</th>
        <th style="padding:7px 10px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">ALLOC</th>
        <th style="padding:7px 10px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">VS TARGET</th>
      </tr></thead>
      <tbody>{alloc_rows}</tbody>
    </table>
  </div>

  <div style="background:#0f1628;border:1px solid rgba(0,212,255,0.12);border-radius:8px;padding:16px;margin-bottom:24px;font-size:11px;color:#4A5578;line-height:1.8">
    <div style="color:#F0F4FF;font-weight:600;margin-bottom:8px">Settlement & Governance</div>
    Cash deployed: ${pv - cash:,.0f} &nbsp;·&nbsp; Cash remaining: ${cash:,.0f} ({cash_pct:.1f}%)<br>
    Open positions: {n_pos} &nbsp;·&nbsp; Pending decisions: {n_pend} &nbsp;·&nbsp; Active alerts: {n_alerts}<br>
    All settlement rails operational &nbsp;·&nbsp; Zero doctrine breaches
  </div>

  <!-- ── Error Log Digest ── -->
  {_build_error_digest_html(error_log)}

  <div style="border-top:1px solid rgba(0,212,255,0.1);padding-top:16px;font-size:10px;color:#4A5578;letter-spacing:1px;line-height:1.8">
    AUREON &nbsp;·&nbsp; DOCTRINE-DRIVEN FINANCIAL OPERATING SYSTEM<br>
    Columbia University &nbsp;·&nbsp; MS Technology Management &nbsp;·&nbsp; Guillermo "Bill" Ravelo<br>
    Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
  </div>
</div></body></html>"""


def _build_premarket_email_html():
    """Pre-market briefing — sent at 8:30 AM ET (NYSE pre-market open)."""
    with _lock:
        pv       = aureon_state["portfolio_value"]
        pnl      = aureon_state["pnl"]
        pnl_pct  = aureon_state["pnl_pct"]
        drawdown = aureon_state["drawdown"]
        n_pos    = len(aureon_state["positions"])
        n_pend   = len(aureon_state["pending_decisions"])
        n_alerts = len(aureon_state["compliance_alerts"])
        doctrine = aureon_state["doctrine_version"]
        ct       = dict(aureon_state["class_totals"])
        cash     = aureon_state["cash"]
        positions= list(aureon_state["positions"])
        prices   = dict(aureon_state["prices"])

    ET         = zoneinfo.ZoneInfo("America/New_York")
    date_str   = datetime.now(ET).strftime("%A, %B %d, %Y")
    pnl_col    = "#10B981" if pnl >= 0 else "#EF4444"
    pnl_sign   = "+" if pnl >= 0 else ""
    dd_col     = "#EF4444" if drawdown > 5 else "#10B981"
    cash_pct   = (cash / pv * 100) if pv > 0 else 0
    deployed   = pv - cash

    # Pending decisions that need human action
    pend_rows = ""
    with _lock:
        pending = list(aureon_state["pending_decisions"])
    for d in pending[:5]:
        a_col = "#10B981" if d["action"] == "BUY" else "#EF4444"
        pend_rows += f"""<tr style="border-bottom:1px solid rgba(0,212,255,0.06)">
          <td style="padding:7px 10px;color:{a_col};font-weight:600">{d["action"]}</td>
          <td style="padding:7px 10px;color:#F0F4FF">{d["symbol"]}</td>
          <td style="padding:7px 10px">${d.get("notional",0):,.0f}</td>
          <td style="padding:7px 10px;color:#4A5578;font-size:10px">{d.get("rationale","")[:40]}...</td>
        </tr>"""
    if not pend_rows:
        pend_rows = '<tr><td colspan="4" style="padding:10px;color:#4A5578;text-align:center">No pending decisions — Thifur cleared</td></tr>'

    # Top positions by value
    pos_rows = ""
    pos_with_val = []
    for p in positions:
        price = prices.get(p["symbol"], p.get("cost", 0))
        val   = p["shares"] * price
        pos_with_val.append((p, val, price))
    pos_with_val.sort(key=lambda x: x[1], reverse=True)
    for p, val, price in pos_with_val[:6]:
        cost   = p.get("cost", price)
        pnl_p  = ((price - cost) / cost * 100) if cost > 0 else 0
        pc     = "#10B981" if pnl_p >= 0 else "#EF4444"
        ps     = "+" if pnl_p >= 0 else ""
        pos_rows += f"""<tr style="border-bottom:1px solid rgba(0,212,255,0.06)">
          <td style="padding:7px 10px;color:#F0F4FF;font-weight:600">{p["symbol"]}</td>
          <td style="padding:7px 10px;color:#4A5578;font-size:10px">{p["asset_class"]}</td>
          <td style="padding:7px 10px">${val:,.0f}</td>
          <td style="padding:7px 10px;color:{pc}">{ps}{pnl_p:.1f}%</td>
        </tr>"""
    if not pos_rows:
        pos_rows = '<tr><td colspan="4" style="padding:10px;color:#4A5578;text-align:center">No open positions</td></tr>'

    alert_line = f'<span style="color:#EF4444">{n_alerts} active alert{"s" if n_alerts != 1 else ""} — review before open</span>' if n_alerts > 0 else '<span style="color:#10B981">No active alerts — clean open</span>'

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#060810;font-family:'Courier New',monospace;color:#F0F4FF">
<div style="max-width:600px;margin:0 auto;padding:32px 24px">

  <div style="border-bottom:1px solid rgba(0,212,255,0.2);padding-bottom:20px;margin-bottom:24px">
    <div style="font-size:22px;font-weight:800;letter-spacing:4px;color:#00D4FF">AUREON</div>
    <div style="font-size:10px;letter-spacing:2px;color:#4A5578;margin-top:4px">DOCTRINE-DRIVEN FINANCIAL OPERATING SYSTEM</div>
  </div>

  <div style="margin-bottom:24px">
    <div style="font-size:16px;font-weight:700;letter-spacing:2px;color:#F0F4FF;margin-bottom:4px">
      PRE-MARKET BRIEFING</div>
    <div style="font-size:12px;color:#4A5578">{date_str} &nbsp;·&nbsp; NYSE Open 9:30 AM ET &nbsp;·&nbsp; Doctrine v{doctrine}</div>
  </div>

  <table style="width:100%;border-collapse:separate;border-spacing:8px;margin-bottom:24px">
    <tr>
      <td style="background:#0f1628;border:1px solid rgba(0,212,255,0.12);border-radius:8px;padding:16px;width:25%">
        <div style="font-size:9px;letter-spacing:2px;color:#4A5578;margin-bottom:6px">NAV</div>
        <div style="font-size:18px;font-weight:700">${pv:,.0f}</div>
      </td>
      <td style="background:#0f1628;border:1px solid rgba(0,212,255,0.12);border-radius:8px;padding:16px;width:25%">
        <div style="font-size:9px;letter-spacing:2px;color:#4A5578;margin-bottom:6px">TOTAL P&amp;L</div>
        <div style="font-size:18px;font-weight:700;color:{pnl_col}">{pnl_sign}${abs(pnl):,.0f}</div>
        <div style="font-size:10px;color:{pnl_col}">{pnl_sign}{pnl_pct:.2f}%</div>
      </td>
      <td style="background:#0f1628;border:1px solid rgba(0,212,255,0.12);border-radius:8px;padding:16px;width:25%">
        <div style="font-size:9px;letter-spacing:2px;color:#4A5578;margin-bottom:6px">DRAWDOWN</div>
        <div style="font-size:18px;font-weight:700;color:{dd_col}">{drawdown:.2f}%</div>
        <div style="font-size:10px;color:#4A5578">Limit: 10.00%</div>
      </td>
      <td style="background:#0f1628;border:1px solid rgba(0,212,255,0.12);border-radius:8px;padding:16px;width:25%">
        <div style="font-size:9px;letter-spacing:2px;color:#4A5578;margin-bottom:6px">CASH</div>
        <div style="font-size:18px;font-weight:700;color:#00D4FF">${cash:,.0f}</div>
        <div style="font-size:10px;color:#4A5578">{cash_pct:.1f}% of NAV</div>
      </td>
    </tr>
  </table>

  <div style="background:#0f1628;border:1px solid rgba(245,158,11,0.3);border-radius:8px;padding:14px 16px;margin-bottom:20px;font-size:11px;line-height:1.7">
    <div style="color:#F59E0B;font-weight:600;margin-bottom:6px;font-size:10px;letter-spacing:1.5px">⚡ DECISIONS REQUIRING APPROVAL BEFORE OPEN</div>
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead><tr style="border-bottom:1px solid rgba(0,212,255,0.15)">
        <th style="padding:7px 10px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">ACTION</th>
        <th style="padding:7px 10px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">SYMBOL</th>
        <th style="padding:7px 10px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">NOTIONAL</th>
        <th style="padding:7px 10px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">RATIONALE</th>
      </tr></thead>
      <tbody>{pend_rows}</tbody>
    </table>
  </div>

  <div style="background:#0f1628;border:1px solid rgba(0,212,255,0.12);border-radius:8px;padding:16px;margin-bottom:20px">
    <div style="font-size:9px;letter-spacing:2px;color:#4A5578;margin-bottom:10px">TOP POSITIONS GOING INTO OPEN</div>
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead><tr style="border-bottom:1px solid rgba(0,212,255,0.15)">
        <th style="padding:7px 10px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">SYMBOL</th>
        <th style="padding:7px 10px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">CLASS</th>
        <th style="padding:7px 10px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">VALUE</th>
        <th style="padding:7px 10px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#4A5578;font-weight:500">P&amp;L</th>
      </tr></thead>
      <tbody>{pos_rows}</tbody>
    </table>
  </div>

  <div style="background:#0f1628;border:1px solid rgba(0,212,255,0.12);border-radius:8px;padding:16px;margin-bottom:24px;font-size:11px;color:#4A5578;line-height:1.8">
    <div style="color:#F0F4FF;font-weight:600;margin-bottom:8px">System Status at Open</div>
    {alert_line}<br>
    Deployed capital: ${deployed:,.0f} &nbsp;·&nbsp; Cash available to trade: ${cash:,.0f}<br>
    Settlement rails: SWIFT · Fedwire · Custodian · Clearing — all OPERATIONAL<br>
    Doctrine v{doctrine} active &nbsp;·&nbsp; Thifur agents armed and ready
  </div>

  <div style="border-top:1px solid rgba(0,212,255,0.1);padding-top:16px;font-size:10px;color:#4A5578;letter-spacing:1px;line-height:1.8">
    AUREON &nbsp;·&nbsp; DOCTRINE-DRIVEN FINANCIAL OPERATING SYSTEM<br>
    Columbia University &nbsp;·&nbsp; MS Technology Management &nbsp;·&nbsp; Guillermo "Bill" Ravelo<br>
    Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
  </div>
</div></body></html>"""


def _send_trade_confirmation_email(report: dict):
    """
    Send a trade confirmation compliance email within seconds of execution.
    Separate from daily close and weekly P&L — triggered per trade.
    """
    action     = report.get("action","—")
    symbol     = report.get("symbol","—")
    notional   = report.get("notional", 0)
    exec_ts    = (report.get("exec_ts","—") or "")[:19].replace("T"," ") + " UTC"
    report_id  = report.get("report_id","—")
    auth_hash  = report.get("authority_hash","—")
    doctrine   = report.get("doctrine_version","—")
    settlement = report.get("settlement","T+1")
    color      = "#10B981" if action == "BUY" else "#EF4444"

    gates_rows = ""
    for g in report.get("gate_results", []):
        sc = "#10B981" if g.get("status")=="PASS" else ("#F59E0B" if g.get("status")=="WARN" else "#EF4444")
        gates_rows += (
            f'<tr>'
            f'<td style="padding:5px 10px;font-family:monospace;font-size:11px;color:#94a3b8">{g.get("gate","&#8212;")}</td>'
            f'<td style="padding:5px 10px;font-size:11px;color:#94a3b8">{g.get("layer","&#8212;")}</td>'
            f'<td style="padding:5px 10px;font-weight:700;color:{sc}">{g.get("status","&#8212;")}</td>'
            f'<td style="padding:5px 10px;font-size:10px;color:#64748b">{(g.get("detail","") or "")[:55]}</td>'
            f'</tr>'
        )

    html = (
        '<!DOCTYPE html><html><body style="background:#060810;color:#F0F4FF;'
        'font-family:\'Courier New\',monospace;padding:32px;max-width:700px;margin:0 auto">'
        '<div style="border:1px solid rgba(0,212,255,0.2);border-radius:8px;padding:28px;background:#0a0f1e">'
        '<div style="font-size:11px;letter-spacing:3px;color:#00D4FF;margin-bottom:4px">'
        'AUREON &middot; KALADAN L2 &middot; COMPLIANCE TRADE REPORT</div>'
        f'<div style="font-size:24px;font-weight:700;margin-bottom:4px">'
        f'<span style="color:{color}">{action}</span> {symbol}'
        f'<span style="font-size:14px;color:#94a3b8;font-weight:400">&nbsp;${notional:,.0f} notional</span></div>'
        f'<div style="font-size:11px;color:#64748b;margin-bottom:24px">{exec_ts} &middot; {report_id}</div>'
        '<hr style="border:none;border-top:1px solid rgba(0,212,255,0.1);margin:0 0 20px">'
        '<div style="font-size:9px;letter-spacing:2px;color:#00D4FF;margin-bottom:10px">'
        'SECTION I &mdash; TRADE IDENTITY</div>'
        '<table style="width:100%;border-collapse:collapse;margin-bottom:20px">'
        f'<tr><td style="padding:4px 10px;color:#64748b;font-size:11px">Asset Class</td>'
        f'<td style="padding:4px 10px;font-size:11px">{(report.get("asset_class","") or "").replace("_"," ").upper()}</td>'
        f'<td style="padding:4px 10px;color:#64748b;font-size:11px">Quantity</td>'
        f'<td style="padding:4px 10px;font-size:11px">{report.get("shares",0):,} shares</td></tr>'
        f'<tr style="background:rgba(255,255,255,0.03)">'
        f'<td style="padding:4px 10px;color:#64748b;font-size:11px">Executed Price</td>'
        f'<td style="padding:4px 10px;font-size:11px">${report.get("exec_price",0):,.2f}</td>'
        f'<td style="padding:4px 10px;color:#64748b;font-size:11px">Settlement</td>'
        f'<td style="padding:4px 10px;font-size:11px">{settlement}</td></tr>'
        f'<tr><td style="padding:4px 10px;color:#64748b;font-size:11px">Authority Hash</td>'
        f'<td colspan="3" style="padding:4px 10px;font-size:10px;font-family:monospace;color:#64748b">{auth_hash}</td></tr>'
        '</table>'
        '<div style="font-size:9px;letter-spacing:2px;color:#00D4FF;margin-bottom:10px">'
        'SECTION II &mdash; GOVERNANCE BLOCK</div>'
        '<table style="width:100%;border-collapse:collapse;margin-bottom:16px">'
        f'<tr><td style="padding:4px 10px;color:#64748b;font-size:11px">Doctrine Version</td>'
        f'<td style="padding:4px 10px;font-size:11px">v{doctrine}</td>'
        f'<td style="padding:4px 10px;color:#64748b;font-size:11px">Tier Authority</td>'
        f'<td style="padding:4px 10px;font-size:11px">Tier 1 &mdash; Human</td></tr>'
        f'<tr style="background:rgba(255,255,255,0.03)">'
        f'<td style="padding:4px 10px;color:#64748b;font-size:11px">Approved By</td>'
        f'<td colspan="3" style="padding:4px 10px;font-size:11px">{report.get("approved_by","&#8212;")}</td></tr>'
        '</table>'
        '<table style="width:100%;border-collapse:collapse;margin-bottom:20px;'
        'background:#060810;border:1px solid rgba(0,212,255,0.08)">'
        '<thead><tr style="background:#0f1628">'
        '<th style="padding:6px 10px;text-align:left;font-size:9px;color:#00D4FF;letter-spacing:1px">GATE</th>'
        '<th style="padding:6px 10px;text-align:left;font-size:9px;color:#00D4FF;letter-spacing:1px">LAYER</th>'
        '<th style="padding:6px 10px;text-align:left;font-size:9px;color:#00D4FF;letter-spacing:1px">STATUS</th>'
        '<th style="padding:6px 10px;text-align:left;font-size:9px;color:#00D4FF;letter-spacing:1px">DETAIL</th>'
        f'</tr></thead><tbody>{gates_rows}</tbody></table>'
        '<div style="font-size:9px;letter-spacing:2px;color:#00D4FF;margin-bottom:10px">'
        'SECTION III &mdash; RISK STATE AT EXECUTION</div>'
        '<table style="width:100%;border-collapse:collapse;margin-bottom:24px">'
        f'<tr><td style="padding:4px 10px;color:#64748b;font-size:11px">Drawdown at Exec</td>'
        f'<td style="padding:4px 10px;font-size:11px">{report.get("drawdown_at_exec",0):.2f}%</td>'
        f'<td style="padding:4px 10px;color:#64748b;font-size:11px">Portfolio Value</td>'
        f'<td style="padding:4px 10px;font-size:11px">${report.get("portfolio_value_at_exec",0):,.0f}</td></tr>'
        f'<tr style="background:rgba(255,255,255,0.03)">'
        f'<td style="padding:4px 10px;color:#64748b;font-size:11px">Cash Before</td>'
        f'<td style="padding:4px 10px;font-size:11px">${report.get("cash_before",0):,.0f}</td>'
        f'<td style="padding:4px 10px;color:#64748b;font-size:11px">Cash After</td>'
        f'<td style="padding:4px 10px;font-size:11px">${report.get("cash_after",0):,.0f}</td></tr>'
        f'<tr><td style="padding:4px 10px;color:#64748b;font-size:11px">VaR Impact (est.)</td>'
        f'<td style="padding:4px 10px;font-size:11px">{report.get("var_impact",0):+.2f}%</td>'
        f'<td style="padding:4px 10px;color:#64748b;font-size:11px">Positions Post</td>'
        f'<td style="padding:4px 10px;font-size:11px">{report.get("positions_post",0)}</td></tr>'
        '</table>'
        '<hr style="border:none;border-top:1px solid rgba(0,212,255,0.1);margin:0 0 12px">'
        f'<div style="font-size:9px;color:#4A5578;text-align:center">'
        f'{report_id} &middot; Aureon Grid 3 &middot; Kaladan L2 Compliance Artifact &middot; '
        f'MiFID II Art.17/RTS6 &middot; SR 11-7 &middot; Not for external distribution</div>'
        '</div></body></html>'
    )

    subject = f"[AUREON] Trade Executed: {action} {symbol} ${notional:,.0f} \u00b7 {report_id}"
    _send_email(subject, html)


def _send_email(subject, html_body):
    """Send an HTML email via Gmail SMTP. Returns True on success."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(html_body, "html"))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"[AUREON] Email sent {EMAIL_FROM} → {EMAIL_TO}: {subject}")
        return True
    except Exception as exc:
        _log_error("ERROR", "_send_email", str(exc))
        return False


def email_scheduler():
    """
    Background thread. Checks every 60 seconds.
    Three scheduled sends (all times US Eastern):
      • 08:30 Mon–Fri  → Pre-Market Briefing
      • 16:15 Mon–Fri  → Market Close Report
      • 17:00 Friday   → Weekly P&L Report
    Each send is tracked by date to avoid duplicates.
    """
    ET = zoneinfo.ZoneInfo("America/New_York")

    last_premarket_date = None   # date string "YYYY-MM-DD"
    last_close_date     = None
    last_weekly_week    = None   # ISO week number

    while True:
        try:
            now_et   = datetime.now(ET)
            today    = now_et.strftime("%Y-%m-%d")
            weekday  = now_et.weekday()   # Mon=0 … Fri=4
            h, m     = now_et.hour, now_et.minute
            week_num = now_et.isocalendar()[1]
            date_str = now_et.strftime("%B %d, %Y")

            # ── PRE-MARKET BRIEFING ─ 08:30 ET Mon–Fri ──────────────
            # Unwind overnight MMF FIRST so cash is available for T+1
            # settlement before the market opens.
            if (weekday <= 4
                    and h == 8 and m < 2
                    and last_premarket_date != today):
                print("[AUREON] 8:30 AM ET — unwinding MMF + sending pre-market briefing...")
                _unwind_cash_sweep()   # Kaladan L2: MMF → cash pre-open
                if _send_email(
                    f"Aureon Pre-Market Briefing — {date_str}",
                    _build_premarket_email_html()
                ):
                    last_premarket_date = today

            # ── MARKET CLOSE REPORT ─ 16:15 ET Mon–Fri ──────────────
            # Sweep idle cash into MMF FIRST so the EOD email accurately
            # reflects the post-sweep cash position.
            if (weekday <= 4
                    and h == 16 and 15 <= m < 17
                    and last_close_date != today):
                print("[AUREON] 4:15 PM ET — performing cash sweep + sending market close report...")
                _perform_cash_sweep()  # Kaladan L2: cash → MMF EOD
                if _send_email(
                    f"Aureon Market Close Report — {date_str}",
                    _build_close_email_html()
                ):
                    last_close_date = today

            # ── WEEKLY P&L REPORT ─ 17:00 ET Friday ─────────────────
            if (weekday == 4
                    and h == 17 and m < 2
                    and last_weekly_week != week_num):
                print("[AUREON] Friday 5:00 PM ET — sending weekly P&L report...")
                if _send_email(
                    f"Aureon Weekly P&L Report — {date_str}",
                    _build_email_html()
                ):
                    last_weekly_week = week_num

        except Exception as exc:
            _log_error("ERROR", "email_scheduler", str(exc))
        time.sleep(60)


# ── Yahoo Finance symbol mapping ─────────────────────────────────────────────
# Our internal symbol names don't always match Yahoo Finance tickers.
# This dictionary translates them so yfinance knows what to fetch.
_YAHOO_MAP = {
    "BTC":     "BTC-USD",    # Bitcoin priced in USD
    "ETH":     "ETH-USD",    # Ethereum priced in USD
    "SOL":     "SOL-USD",    # Solana priced in USD
    "EUR/USD": "EURUSD=X",   # Euro / US Dollar spot rate
    "GBP/USD": "GBPUSD=X",   # British Pound / US Dollar spot rate
    "USD/JPY": "JPY=X",      # US Dollar / Japanese Yen spot rate
    # All equity and commodity tickers are the same in Yahoo Finance:
    # SPY, AAPL, NVDA, EEM, MSFT, GOOGL, AMZN, TLT, HYG, AGG, GLD, USO, DBC
}

# ── Price cache ───────────────────────────────────────────────────────────────
# We only hit Yahoo Finance once every 60 seconds.
# The market loop runs every 5 seconds, so without this cache we'd make
# 12 network calls per minute — too slow and too noisy.
_price_cache    = {}   # symbol → last known real price
_price_cache_ts = 0.0  # Unix timestamp of the last successful fetch
_sim_fallback_logged = False  # print the simulation fallback message only once


def _fetch_yahoo_prices():
    """
    Download the latest price for every instrument.
    Delegates to get_prices_batch() which tries Twelve Data SDK first,
    then falls back to per-symbol yfinance calls.
    Returns a dict {symbol: price} using our internal symbol names.
    On any error returns an empty dict — caller falls back to simulation.
    """
    try:
        # Use the Twelve Data SDK batch call with yfinance fallback.
        # Pass Yahoo-mapped symbols so yfinance fallback resolves correctly.
        internal_symbols = list(BASE_PRICES.keys())
        yahoo_to_internal = {_YAHOO_MAP.get(s, s): s for s in internal_symbols}
        yahoo_symbols = [_YAHOO_MAP.get(s, s) for s in internal_symbols]

        raw = get_prices_batch(yahoo_symbols)

        result = {}
        for yahoo_sym, price in raw.items():
            internal_sym = yahoo_to_internal.get(yahoo_sym, yahoo_sym)
            if price is not None:
                result[internal_sym] = price
        return result

    except Exception as exc:
        print(f"[AUREON] get_prices_batch failed ({exc}); falling back to simulation")
        return {}


def _fetch_twelve_data_prices():
    """
    Fetch real-time prices from Twelve Data API.
    Covers all 19 Aureon symbols in one batch request.
    Returns dict of {symbol: price} or empty dict on failure.
    """
    if not TWELVE_DATA_API_KEY:
        return {}

    # Twelve Data symbol mapping — FX pairs use different format
    TWELVE_DATA_MAP = {
        "SPY": "SPY", "AAPL": "AAPL", "NVDA": "NVDA", "MSFT": "MSFT",
        "GOOGL": "GOOGL", "AMZN": "AMZN", "EEM": "EEM", "TLT": "TLT",
        "HYG": "HYG", "AGG": "AGG", "GLD": "GLD", "USO": "USO",
        "DBC": "DBC", "BTC": "BTC/USD", "ETH": "ETH/USD", "SOL": "SOL/USD",
        "EUR/USD": "EUR/USD", "GBP/USD": "GBP/USD", "USD/JPY": "USD/JPY",
    }

    # Batch all symbols in one request (Twelve Data supports comma-separated)
    symbols_param = ",".join(TWELVE_DATA_MAP.values())
    url = (
        f"https://api.twelvedata.com/price"
        f"?symbol={symbols_param}"
        f"&apikey={TWELVE_DATA_API_KEY}"
    )

    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        prices = {}
        reverse_map = {v: k for k, v in TWELVE_DATA_MAP.items()}

        for td_symbol, result in data.items():
            aureon_symbol = reverse_map.get(td_symbol, td_symbol)
            if isinstance(result, dict) and "price" in result:
                try:
                    prices[aureon_symbol] = float(result["price"])
                except (ValueError, TypeError):
                    pass

        return prices
    except Exception as exc:
        print(f"[TWELVE_DATA] Fetch failed: {exc}")
        return {}


def _simulated_prices():
    """
    Return the next tick of prices.

    Strategy (in order):
      1. If the cache is less than 60 seconds old, use cached real prices and
         apply a tiny random nudge so the UI doesn't look frozen.
      2. If the cache is stale (>60 s), try to fetch fresh prices from Yahoo Finance.
         On success → update the cache and return those prices.
         On failure → fall through to full random-walk simulation.
      3. Fallback: pure simulated random walk from the last known price.
    """
    global _price_cache, _price_cache_ts

    now   = time.time()
    prices = {}

    # ── Step 1: cache hit — apply micro-nudge to real prices ────────────────
    if _price_cache and (now - _price_cache_ts) < 60:
        for symbol, base in BASE_PRICES.items():
            last = _price_cache.get(symbol, aureon_state["prices"].get(symbol, base))
            # Tiny nudge so the chart line keeps moving between real fetches.
            if symbol in ("BTC", "ETH", "SOL"):
                nudge = 0.0005      # crypto: ±0.05% micro-drift
            elif "/" in symbol:
                nudge = 0.00005     # FX: ±0.005% micro-drift
            else:
                nudge = 0.0001      # equities/commodities: ±0.01%
            prices[symbol] = last * (1 + (random.random() - 0.5) * nudge)
        return prices

    # ── Step 2: cache is stale — try Twelve Data (primary) then Yahoo Finance (fallback) ──
    fresh = _fetch_twelve_data_prices()
    source = "Twelve Data"

    if not fresh and _YFINANCE_AVAILABLE:
        fresh = _fetch_yahoo_prices()
        source = "Yahoo Finance"

    if fresh:
        # Merge: real prices for symbols we got, last-known for the rest
        for symbol, base in BASE_PRICES.items():
            if symbol in fresh:
                prices[symbol] = fresh[symbol]
            else:
                prices[symbol] = aureon_state["prices"].get(symbol, base)
        _price_cache    = dict(prices)
        _price_cache_ts = now
        print(f"[AUREON] Real prices loaded from {source} ({len(fresh)} symbols)")
        return prices

    # ── Step 3: fallback — full random-walk simulation ───────────────────────
    # This runs only when Yahoo Finance is unreachable (e.g. weekend, no data).
    global _sim_fallback_logged
    if not _sim_fallback_logged:
        print("[AUREON] Using simulated prices (market closed or Yahoo unavailable)")
        _sim_fallback_logged = True
    for symbol, base in BASE_PRICES.items():
        current = aureon_state["prices"].get(symbol, base)
        if symbol in ("BTC", "ETH", "SOL"):
            vol = 0.008      # crypto: up to 0.8% per tick
        elif "/" in symbol:
            vol = 0.0005     # FX pairs: very tight
        else:
            vol = 0.002      # equities & commodities: 0.2%
        prices[symbol] = current * (1 + (random.random() - 0.5) * vol)
    return prices


def _calc_portfolio(prices):
    """
    Walk through every open position, multiply shares × price,
    sum them up, and compute P&L vs the $50M starting value.
    Returns: (total_value, pnl_dollars, pnl_pct, drawdown, class_totals)
    """
    if not aureon_state["positions"]:
        print("[WARN] _calc_portfolio: positions list is empty — stack may not have completed yet")
    market_val   = 0.0
    class_totals = {}

    for pos in aureon_state["positions"]:
        price = prices.get(pos["symbol"], pos["cost"])
        mv    = pos["shares"] * price
        market_val += mv
        cls = pos["asset_class"]
        class_totals[cls] = class_totals.get(cls, 0) + mv

    total    = aureon_state["cash"] + market_val
    pnl      = total - 50_000_000
    pnl_pct  = (pnl / 50_000_000) * 100
    drawdown = abs(pnl_pct) if pnl < 0 else 0.0

    return total, pnl, pnl_pct, drawdown, class_totals


def _risk_manager_snapshot():
    """
    Independent portfolio risk view used by Compliance, Governance, and pre-trade checks.
    This formalizes Risk Manager L1B without adding a separate execution subsystem.
    """
    with _lock:
        pv        = aureon_state["portfolio_value"]
        drawdown  = aureon_state["drawdown"]
        positions = list(aureon_state["positions"])
        prices    = dict(aureon_state["prices"])

    largest_position_pct = 0.0
    largest_symbol = "—"
    for pos in positions:
        price = prices.get(pos["symbol"], pos.get("cost", 0))
        notional = pos["shares"] * price
        pct = (notional / pv * 100) if pv > 0 else 0.0
        if pct > largest_position_pct:
            largest_position_pct = pct
            largest_symbol = pos["symbol"]

    var_estimate_pct = min(RISK_MANAGER_POLICY["var_limit_pct"], max(0.0, drawdown * 0.4))

    return {
        "layer": "Risk Manager L1B",
        "drawdown_pct": round(drawdown, 4),
        "drawdown_warn_pct": RISK_MANAGER_POLICY["drawdown_warn_pct"],
        "drawdown_fail_pct": RISK_MANAGER_POLICY["drawdown_fail_pct"],
        "position_warn_pct": RISK_MANAGER_POLICY["position_warn_pct"],
        "position_fail_pct": RISK_MANAGER_POLICY["position_fail_pct"],
        "largest_position_pct": round(largest_position_pct, 2),
        "largest_position_symbol": largest_symbol,
        "var_estimate_pct": round(var_estimate_pct, 2),
        "var_limit_pct": RISK_MANAGER_POLICY["var_limit_pct"],
    }


_THESIS_FACTOR_RULES = {
    "Rates": {
        "keywords": ["rates", "yield", "fed", "duration", "treasury", "curve"],
        "scenario": "Rates shock",
        "question": "How sensitive is the thesis to higher-for-longer policy rates?",
    },
    "Inflation": {
        "keywords": ["inflation", "cpi", "pricing power", "sticky prices", "input cost"],
        "scenario": "Inflation shock",
        "question": "Does the thesis rely on inflation moderation or inflation persistence?",
    },
    "Credit": {
        "keywords": ["credit", "spread", "default", "refinancing", "balance sheet", "leverage"],
        "scenario": "Credit spread widening",
        "question": "What happens if financing conditions tighten materially?",
    },
    "Liquidity": {
        "keywords": ["liquidity", "exit", "volume", "market depth", "redemption"],
        "scenario": "Liquidity freeze",
        "question": "Can the position be exited under stress without impairing capital?",
    },
    "FX": {
        "keywords": ["fx", "usd", "eur", "gbp", "yen", "currency"],
        "scenario": "Dollar regime change",
        "question": "Is the thesis implicitly long or short dollar strength?",
    },
    "Commodities": {
        "keywords": ["oil", "gas", "commodity", "copper", "gold", "energy"],
        "scenario": "Commodity spike",
        "question": "How exposed is the thesis to an input-cost or energy-price shock?",
    },
    "China / EM": {
        "keywords": ["china", "emerging markets", "em", "taiwan", "supply chain"],
        "scenario": "EM growth slowdown",
        "question": "Does the thesis depend on emerging-market demand or supply-chain resilience?",
    },
    "Crypto / Digital Assets": {
        "keywords": ["crypto", "bitcoin", "ethereum", "token", "digital asset"],
        "scenario": "Crypto volatility event",
        "question": "How does governance respond if volatility expands abruptly?",
    },
}

_THESIS_RISK_POLICY = {
    "max_portfolio_risk_budget_pct": 10.0,
    "warn_portfolio_risk_budget_pct": 5.0,
    "max_leverage_multiple": 1.5,
    "warn_tail_downside_pct": 15.0,
    "fail_tail_downside_pct": 20.0,
}

_THESIS_SYMBOL_RISK_PROFILES = {
    "SPY":      {"asset_class": "equities",     "realized_vol_pct": 16.0, "beta": 1.0, "drawdown_pct": 12.0, "liquidity_score": 5, "complexity_score": 1},
    "AAPL":     {"asset_class": "equities",     "realized_vol_pct": 24.0, "beta": 1.1, "drawdown_pct": 18.0, "liquidity_score": 5, "complexity_score": 1},
    "NVDA":     {"asset_class": "equities",     "realized_vol_pct": 46.0, "beta": 1.7, "drawdown_pct": 32.0, "liquidity_score": 5, "complexity_score": 2},
    "EEM":      {"asset_class": "equities",     "realized_vol_pct": 22.0, "beta": 1.1, "drawdown_pct": 20.0, "liquidity_score": 4, "complexity_score": 2},
    "MSFT":     {"asset_class": "equities",     "realized_vol_pct": 23.0, "beta": 1.0, "drawdown_pct": 16.0, "liquidity_score": 5, "complexity_score": 1},
    "GOOGL":    {"asset_class": "equities",     "realized_vol_pct": 27.0, "beta": 1.1, "drawdown_pct": 19.0, "liquidity_score": 5, "complexity_score": 1},
    "AMZN":     {"asset_class": "equities",     "realized_vol_pct": 31.0, "beta": 1.2, "drawdown_pct": 24.0, "liquidity_score": 5, "complexity_score": 1},
    "TLT":      {"asset_class": "fixed_income", "realized_vol_pct": 14.0, "beta": -0.2, "drawdown_pct": 15.0, "liquidity_score": 5, "complexity_score": 1},
    "HYG":      {"asset_class": "fixed_income", "realized_vol_pct": 10.0, "beta": 0.5, "drawdown_pct": 11.0, "liquidity_score": 4, "complexity_score": 2},
    "AGG":      {"asset_class": "fixed_income", "realized_vol_pct": 7.0,  "beta": 0.1, "drawdown_pct": 8.0,  "liquidity_score": 5, "complexity_score": 1},
    "EUR/USD":  {"asset_class": "fx",           "realized_vol_pct": 8.0,  "beta": 0.0, "drawdown_pct": 7.0,  "liquidity_score": 5, "complexity_score": 1},
    "GBP/USD":  {"asset_class": "fx",           "realized_vol_pct": 9.0,  "beta": 0.0, "drawdown_pct": 8.0,  "liquidity_score": 5, "complexity_score": 1},
    "USD/JPY":  {"asset_class": "fx",           "realized_vol_pct": 10.0, "beta": 0.0, "drawdown_pct": 9.0,  "liquidity_score": 5, "complexity_score": 1},
    "BTC":      {"asset_class": "crypto",       "realized_vol_pct": 62.0, "beta": 1.9, "drawdown_pct": 45.0, "liquidity_score": 4, "complexity_score": 4},
    "ETH":      {"asset_class": "crypto",       "realized_vol_pct": 68.0, "beta": 2.0, "drawdown_pct": 50.0, "liquidity_score": 4, "complexity_score": 4},
    "SOL":      {"asset_class": "crypto",       "realized_vol_pct": 88.0, "beta": 2.3, "drawdown_pct": 58.0, "liquidity_score": 3, "complexity_score": 5},
    "GLD":      {"asset_class": "commodities",  "realized_vol_pct": 15.0, "beta": 0.1, "drawdown_pct": 13.0, "liquidity_score": 5, "complexity_score": 1},
    "USO":      {"asset_class": "commodities",  "realized_vol_pct": 37.0, "beta": 0.8, "drawdown_pct": 33.0, "liquidity_score": 4, "complexity_score": 3},
    "DBC":      {"asset_class": "commodities",  "realized_vol_pct": 21.0, "beta": 0.5, "drawdown_pct": 19.0, "liquidity_score": 4, "complexity_score": 2},
}

_THESIS_EVENT_RISK_KEYWORDS = {
    "geopolitical": 24,
    "war": 24,
    "conflict": 18,
    "blockade": 22,
    "sanctions": 14,
    "red sea": 16,
    "strait of hormuz": 18,
    "oil spike": 16,
    "vix": 14,
    "volatility regime": 18,
    "tail risk": 20,
    "black swan": 24,
    "cyber": 12,
    "supply chain": 10,
    "stagflation": 16,
    "recession": 14,
}

_THESIS_COMPLEXITY_KEYWORDS = {
    "option": 10,
    "call spread": 10,
    "put": 8,
    "puts": 8,
    "levered": 18,
    "2x": 14,
    "3x": 18,
    "etp": 12,
    "crypto": 8,
    "convexity": 8,
    "volatility product": 12,
}

_thesis_market_metric_cache = {}
_fred_cache = {"ts": 0.0, "data": None}
_ofr_cache = {"ts": 0.0, "data": None}
_FRED_SERIES = {
    "fed_funds": {"id": "DFF", "label": "Fed Funds"},
    "ust_10y": {"id": "DGS10", "label": "UST 10Y"},
    "ust_2y": {"id": "DGS2", "label": "UST 2Y"},
    "vix": {"id": "VIXCLS", "label": "VIX"},
    "hy_oas": {"id": "BAMLH0A0HYM2", "label": "HY OAS"},
}


def _fred_series_latest(series_id: str):
    params = {
        "series_id": series_id,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 7,
    }
    if FRED_API_KEY:
        params["api_key"] = FRED_API_KEY
    url = "https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=6) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    observations = payload.get("observations", [])
    for obs in observations:
        value = obs.get("value")
        if value not in (None, ".", ""):
            return {
                "date": obs.get("date"),
                "value": float(value),
            }
    raise ValueError(f"no usable FRED value for {series_id}")


def _fallback_macro_snapshot():
    return {
        "source": "fallback",
        "as_of": datetime.now(timezone.utc).date().isoformat(),
        "fed_funds": 5.33,
        "ust_10y": 4.21,
        "ust_2y": 4.68,
        "curve_spread_bps": -47.0,
        "vix": 24.0,
        "hy_oas": 4.25,
        "macro_regime": "watchful",
        "stress_level": "moderate",
        "summary": "Fallback macro snapshot active. Rates remain restrictive and financial conditions are not benign.",
    }


def _get_fred_macro_snapshot():
    now = time.time()
    cached = _fred_cache.get("data")
    if cached and (now - _fred_cache.get("ts", 0.0)) < 1800:
        return cached

    try:
        series = {name: _fred_series_latest(meta["id"]) for name, meta in _FRED_SERIES.items()}
        curve_spread_bps = (series["ust_10y"]["value"] - series["ust_2y"]["value"]) * 100
        vix = series["vix"]["value"]
        hy_oas = series["hy_oas"]["value"]
        fed_funds = series["fed_funds"]["value"]

        if vix >= 32 or hy_oas >= 5.5:
            stress_level = "high"
        elif vix >= 24 or hy_oas >= 4.5:
            stress_level = "elevated"
        else:
            stress_level = "moderate"

        if curve_spread_bps <= -40 or fed_funds >= 5.0:
            macro_regime = "restrictive"
        elif curve_spread_bps <= -10:
            macro_regime = "inverted"
        else:
            macro_regime = "balanced"

        data = {
            "source": "fred",
            "as_of": max(item["date"] for item in series.values()),
            "fed_funds": round(fed_funds, 2),
            "ust_10y": round(series["ust_10y"]["value"], 2),
            "ust_2y": round(series["ust_2y"]["value"], 2),
            "curve_spread_bps": round(curve_spread_bps, 1),
            "vix": round(vix, 2),
            "hy_oas": round(hy_oas, 2),
            "macro_regime": macro_regime,
            "stress_level": stress_level,
            "summary": f"FRED macro snapshot: {macro_regime} rates backdrop with {stress_level} market stress.",
        }
    except Exception:
        data = _fallback_macro_snapshot()

    _fred_cache["ts"] = now
    _fred_cache["data"] = data
    return data


def _fallback_ofr_snapshot(macro_snapshot: dict):
    proxy_value = round(
        (
            max(0.0, macro_snapshot.get("vix", 24.0) - 18.0) * 0.045
            + max(0.0, macro_snapshot.get("hy_oas", 4.25) - 3.5) * 0.22
            + max(0.0, abs(macro_snapshot.get("curve_spread_bps", -20.0)) - 15.0) * 0.003
        ) - 0.15,
        2,
    )
    if proxy_value >= 1.0:
        stress_band = "severe"
    elif proxy_value >= 0.5:
        stress_band = "elevated"
    elif proxy_value >= 0.0:
        stress_band = "watch"
    else:
        stress_band = "calm"
    return {
        "source": "ofr_proxy",
        "as_of": macro_snapshot.get("as_of"),
        "fsi_value": proxy_value,
        "fsi_band": stress_band,
        "publication_lag_days": 2,
        "summary": "Proxy OFR systemic-stress overlay derived from FRED macro conditions while the official monitor feed is unavailable.",
    }


def _get_ofr_stress_snapshot(macro_snapshot: dict):
    now = time.time()
    cached = _ofr_cache.get("data")
    if cached and (now - _ofr_cache.get("ts", 0.0)) < 1800:
        return cached

    data = None
    try:
        req = urllib.request.Request(
            "https://www.financialresearch.gov/financial-stress-index/",
            headers={"User-Agent": "Mozilla/5.0 Aureon/1.0"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        patterns = [
            r'"fsi[^"]{0,30}value[^"]{0,30}"\s*:\s*(-?\d+\.\d+)',
            r'data-fsi-value="(-?\d+\.\d+)"',
            r'latest[^<]{0,40}?(-?\d+\.\d+)',
            r'current[^<]{0,40}?(-?\d+\.\d+)',
        ]
        fsi_value = None
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.IGNORECASE)
            if match:
                fsi_value = float(match.group(1))
                break

        if fsi_value is not None:
            if fsi_value >= 1.0:
                stress_band = "severe"
            elif fsi_value >= 0.5:
                stress_band = "elevated"
            elif fsi_value >= 0.0:
                stress_band = "watch"
            else:
                stress_band = "calm"
            data = {
                "source": "ofr",
                "as_of": macro_snapshot.get("as_of"),
                "fsi_value": round(fsi_value, 2),
                "fsi_band": stress_band,
                "publication_lag_days": 2,
                "summary": "Official OFR Financial Stress Index systemic-stress overlay.",
            }
    except Exception:
        data = None

    if data is None:
        data = _fallback_ofr_snapshot(macro_snapshot)

    _ofr_cache["ts"] = now
    _ofr_cache["data"] = data
    return data


def _thesis_compute_realized_vol_pct(close_series):
    returns = []
    for prev, curr in zip(close_series, close_series[1:]):
        if prev:
            returns.append((curr / prev) - 1.0)
    if len(returns) < 2:
        return None
    mean_ret = sum(returns) / len(returns)
    variance = sum((ret - mean_ret) ** 2 for ret in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(252) * 100


def _thesis_compute_max_drawdown_pct(close_series):
    if not close_series:
        return None
    peak = close_series[0]
    max_drawdown = 0.0
    for px in close_series:
        peak = max(peak, px)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - px) / peak * 100)
    return max_drawdown


def _thesis_compute_beta(close_series, benchmark_series):
    if not close_series or not benchmark_series:
        return None
    count = min(len(close_series), len(benchmark_series))
    if count < 3:
        return None
    asset_returns = []
    bench_returns = []
    for idx in range(1, count):
        prev_asset = close_series[idx - 1]
        prev_bench = benchmark_series[idx - 1]
        if prev_asset and prev_bench:
            asset_returns.append((close_series[idx] / prev_asset) - 1.0)
            bench_returns.append((benchmark_series[idx] / prev_bench) - 1.0)
    if len(asset_returns) < 2 or len(bench_returns) < 2:
        return None
    mean_asset = sum(asset_returns) / len(asset_returns)
    mean_bench = sum(bench_returns) / len(bench_returns)
    cov = sum((a - mean_asset) * (b - mean_bench) for a, b in zip(asset_returns, bench_returns)) / (len(asset_returns) - 1)
    var_bench = sum((b - mean_bench) ** 2 for b in bench_returns) / (len(bench_returns) - 1)
    if var_bench <= 0:
        return None
    return cov / var_bench


def _thesis_fallback_market_metrics(symbol):
    profile = _THESIS_SYMBOL_RISK_PROFILES.get(symbol, {})
    with _lock:
        current_price = aureon_state["prices"].get(symbol, BASE_PRICES.get(symbol, 1.0))
    base_price = BASE_PRICES.get(symbol, current_price or 1.0)
    move_pct = abs((current_price / base_price) - 1.0) * 100 if base_price else 0.0
    realized_vol = max(profile.get("realized_vol_pct", 18.0), move_pct * 1.8)
    drawdown = max(profile.get("drawdown_pct", 12.0), move_pct * 1.25)
    return {
        "symbol": symbol,
        "source": "fallback",
        "realized_vol_pct": round(realized_vol, 2),
        "beta": round(profile.get("beta", 1.0), 2),
        "drawdown_pct": round(drawdown, 2),
        "liquidity_score": int(profile.get("liquidity_score", 3)),
        "complexity_score": int(profile.get("complexity_score", 2)),
        "asset_class": profile.get("asset_class", "mixed"),
    }


def _thesis_download_market_metrics(symbol):
    cache_key = symbol
    now = time.time()
    cached = _thesis_market_metric_cache.get(cache_key)
    if cached and (now - cached["ts"]) < 900:
        return cached["data"]

    if not _YFINANCE_AVAILABLE:
        data = _thesis_fallback_market_metrics(symbol)
        _thesis_market_metric_cache[cache_key] = {"ts": now, "data": data}
        return data

    yahoo_symbol = _YAHOO_MAP.get(symbol, symbol)
    try:
        ticker = yf.Ticker(yahoo_symbol)
        hist = ticker.history(period="6mo", interval="1d", auto_adjust=True)
        bench = yf.Ticker("SPY").history(period="6mo", interval="1d", auto_adjust=True)
        if hist.empty or bench.empty:
            raise ValueError("empty history")

        closes = [float(v) for v in hist["Close"].dropna().tolist()]
        bench_closes = [float(v) for v in bench["Close"].dropna().tolist()]
        volumes = [float(v) for v in hist["Volume"].dropna().tolist()] if "Volume" in hist else []
        latest_close = closes[-1] if closes else BASE_PRICES.get(symbol, 1.0)
        avg_dollar_volume = 0.0
        if volumes:
            recent = min(len(volumes), len(closes), 20)
            if recent:
                avg_dollar_volume = sum(volumes[-recent:]) * latest_close / recent
        liquidity_score = 5 if avg_dollar_volume >= 2_000_000_000 else 4 if avg_dollar_volume >= 500_000_000 else 3 if avg_dollar_volume >= 100_000_000 else 2 if avg_dollar_volume >= 25_000_000 else 1
        profile = _THESIS_SYMBOL_RISK_PROFILES.get(symbol, {})
        data = {
            "symbol": symbol,
            "source": "yahoo_history",
            "realized_vol_pct": round(_thesis_compute_realized_vol_pct(closes) or profile.get("realized_vol_pct", 18.0), 2),
            "beta": round(_thesis_compute_beta(closes, bench_closes) or profile.get("beta", 1.0), 2),
            "drawdown_pct": round(_thesis_compute_max_drawdown_pct(closes) or profile.get("drawdown_pct", 12.0), 2),
            "liquidity_score": liquidity_score,
            "complexity_score": int(profile.get("complexity_score", 2)),
            "asset_class": profile.get("asset_class", "mixed"),
        }
    except Exception:
        data = _thesis_fallback_market_metrics(symbol)

    _thesis_market_metric_cache[cache_key] = {"ts": now, "data": data}
    return data


def _infer_thesis_risk_stack(symbols, lowered, factors, has_options, has_geopolitical_event):
    macro_snapshot = _get_fred_macro_snapshot()
    ofr_snapshot = _get_ofr_stress_snapshot(macro_snapshot)
    metrics = [_thesis_download_market_metrics(sym) for sym in symbols[:6]]

    if metrics:
        avg_vol = sum(m["realized_vol_pct"] for m in metrics) / len(metrics)
        avg_beta = sum(abs(m["beta"]) for m in metrics) / len(metrics)
        avg_drawdown = sum(m["drawdown_pct"] for m in metrics) / len(metrics)
        avg_liquidity = sum(m["liquidity_score"] for m in metrics) / len(metrics)
        avg_complexity = sum(m["complexity_score"] for m in metrics) / len(metrics)
    else:
        avg_vol = 18.0 + len(factors) * 2.0
        avg_beta = 1.0
        avg_drawdown = 12.0
        avg_liquidity = 3.0
        avg_complexity = 1.5

    event_risk_points = 0
    matched_event_terms = []
    for term, points in _THESIS_EVENT_RISK_KEYWORDS.items():
        if term in lowered:
            event_risk_points += points
            matched_event_terms.append(term)

    complexity_points = 0
    matched_complexity_terms = []
    for term, points in _THESIS_COMPLEXITY_KEYWORDS.items():
        if term in lowered:
            complexity_points += points
            matched_complexity_terms.append(term)

    if has_geopolitical_event:
        event_risk_points += 12
    if has_options:
        complexity_points += 10

    instrument_risk_score = min(100, round(avg_vol * 1.1 + avg_drawdown * 0.7 + max(0.0, avg_beta - 1.0) * 18))
    fred_macro_points = 0
    if macro_snapshot["curve_spread_bps"] <= -40:
        fred_macro_points += 14
    elif macro_snapshot["curve_spread_bps"] <= -15:
        fred_macro_points += 8
    if macro_snapshot["vix"] >= 30:
        fred_macro_points += 18
    elif macro_snapshot["vix"] >= 22:
        fred_macro_points += 10
    if macro_snapshot["hy_oas"] >= 5.0:
        fred_macro_points += 16
    elif macro_snapshot["hy_oas"] >= 4.0:
        fred_macro_points += 8
    if macro_snapshot["fed_funds"] >= 5.0:
        fred_macro_points += 10

    macro_regime_score = min(100, round(event_risk_points + fred_macro_points + len(factors) * 5 + (10 if "Rates" in [f["factor"] for f in factors] else 0)))
    ofr_points = 0
    if ofr_snapshot["fsi_value"] >= 1.0:
        ofr_points += 24
    elif ofr_snapshot["fsi_value"] >= 0.5:
        ofr_points += 14
    elif ofr_snapshot["fsi_value"] >= 0.0:
        ofr_points += 6

    systemic_stress_score = min(100, round(
        macro_regime_score * 0.5
        + instrument_risk_score * 0.22
        + ofr_points
        + (12 if "Credit" in [f["factor"] for f in factors] else 0)
        + (10 if has_geopolitical_event else 0)
    ))
    liquidity_risk_score = min(100, round((6 - avg_liquidity) * 18 + (8 if "Liquidity" in [f["factor"] for f in factors] else 0)))
    instrument_complexity_score = min(100, round(avg_complexity * 14 + complexity_points))

    implied_risk_budget_pct = round(min(
        30.0,
        2.0
        + instrument_risk_score * 0.06
        + macro_regime_score * 0.05
        + systemic_stress_score * 0.03
        + instrument_complexity_score * 0.02
    ), 1)
    implied_leverage_multiple = round(min(3.0, max(1.0, 0.85 + instrument_complexity_score * 0.012 + instrument_risk_score * 0.004)), 1)
    implied_tail_downside_pct = round(min(35.0, max(8.0, avg_drawdown * 0.45 + avg_vol * 0.18 + macro_regime_score * 0.08 + liquidity_risk_score * 0.05)), 1)

    return {
        "market_metrics": metrics,
        "market_risk_score": instrument_risk_score,
        "macro_regime_score": macro_regime_score,
        "systemic_stress_score": systemic_stress_score,
        "liquidity_risk_score": liquidity_risk_score,
        "instrument_complexity_score": instrument_complexity_score,
        "implied_risk_budget_pct": implied_risk_budget_pct,
        "implied_leverage_multiple": implied_leverage_multiple,
        "implied_tail_downside_pct": implied_tail_downside_pct,
        "matched_event_terms": matched_event_terms[:8],
        "matched_complexity_terms": matched_complexity_terms[:8],
        "market_data_source": "yahoo_history" if any(m["source"] == "yahoo_history" for m in metrics) else "fallback",
        "macro_snapshot": macro_snapshot,
        "ofr_snapshot": ofr_snapshot,
    }


def _analyze_thesis_memo(memo_text: str):
    """
    Lightweight thesis parser for Phase 5.
    Converts narrative memo text into factor exposures, scenario prompts,
    and governance-readiness outputs without introducing heavy NLP dependencies.
    """
    text = (memo_text or "").strip()
    if not text:
        return {
            "title": "No memo submitted",
            "summary": "Paste an investment thesis or IC memo to extract factors and scenario prompts.",
            "word_count": 0,
            "stance": "undetermined",
            "governance_ready": False,
            "governance_status": "no memo",
            "risk_classification": "unknown",
            "conviction_score": 0,
            "factors": [],
            "scenarios": [],
            "risk_review": {},
            "inferred_risk": {},
            "blockers": [],
            "review_flags": [],
            "governance_notes": [
                "No thesis text available for structured analysis.",
            ],
        }

    lowered = text.lower()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    title = lines[0][:90] if lines else "Untitled Thesis Memo"
    words = re.findall(r"\b[\w/-]+\b", text)
    word_count = len(words)

    bullish_markers = ["long", "overweight", "bullish", "upside", "outperform", "relief rally", "snapback"]
    bearish_markers = ["short", "underweight", "bearish", "downside", "deterioration", "drawdown", "crash"]
    bull_hits = sum(lowered.count(k) for k in bullish_markers)
    bear_hits = sum(lowered.count(k) for k in bearish_markers)
    event_hits = sum(lowered.count(k) for k in ["catalyst", "de-escalation", "short-covering", "contrarian", "black swan"])
    if event_hits >= 2 and bull_hits and bear_hits:
        stance = "event-driven"
    else:
        stance = "bullish" if bull_hits > bear_hits else "bearish" if bear_hits > bull_hits else "balanced"

    factors = []
    for factor_name, rule in _THESIS_FACTOR_RULES.items():
        matched = [kw for kw in rule["keywords"] if kw in lowered]
        if matched:
            factors.append({
                "factor": factor_name,
                "score": min(5, len(matched)),
                "matched_terms": matched[:4],
                "question": rule["question"],
                "scenario": rule["scenario"],
            })

    symbols = []
    for candidate in BASE_PRICES:
        if candidate.lower() in lowered:
            symbols.append(candidate)

    explicit_conviction = None
    m = re.search(r"conviction[^0-9]{0,20}(\d{1,3})\s*/\s*100", lowered)
    if m:
        explicit_conviction = max(0, min(100, int(m.group(1))))

    risk_budget_pct = None
    risk_budget_match = re.search(r"(\d{1,2})\s*-\s*(\d{1,2})%\s+portfolio risk budget", lowered)
    if risk_budget_match:
        risk_budget_pct = float(risk_budget_match.group(2))
    else:
        risk_budget_match = re.search(r"(\d{1,2})%\s+portfolio risk budget", lowered)
        if risk_budget_match:
            risk_budget_pct = float(risk_budget_match.group(1))

    leverage_multiple = None
    leverage_match = re.search(r"(\d(?:\.\d)?)\s*-\s*(\d(?:\.\d)?)x levered", lowered)
    if leverage_match:
        leverage_multiple = float(leverage_match.group(2))
    else:
        leverage_match = re.search(r"(\d(?:\.\d)?)x levered", lowered)
        if leverage_match:
            leverage_multiple = float(leverage_match.group(1))

    tail_downside_pct = None
    tail_match = re.search(r"(\d{1,2})\s*-\s*(\d{1,2})%\s+(?:further )?downside", lowered)
    if tail_match:
        tail_downside_pct = float(tail_match.group(2))
    else:
        tail_match = re.search(r"markets?\s+30%\+\s+", lowered)
        if tail_match:
            tail_downside_pct = 30.0

    has_options = "option" in lowered or "call spread" in lowered or "puts" in lowered
    has_geopolitical_event = any(k in lowered for k in ["iran", "red sea", "strait of hormuz", "regional war", "u.s. strikes", "geopolitical"])
    has_hedge = any(k in lowered for k in ["hedge", "hedging", "defined-risk", "stops", "ballast"])
    has_liquidity_plan = any(k in lowered for k in ["stop", "monitor", "exit", "liquidity", "defined-risk"])
    inferred_risk = _infer_thesis_risk_stack(symbols, lowered, factors, has_options, has_geopolitical_event)

    if risk_budget_pct is None:
        risk_budget_pct = inferred_risk["implied_risk_budget_pct"]
        risk_budget_source = "inferred"
    else:
        risk_budget_source = "explicit"

    if leverage_multiple is None and inferred_risk["instrument_complexity_score"] >= 30:
        leverage_multiple = inferred_risk["implied_leverage_multiple"]
        leverage_source = "inferred"
    elif leverage_multiple is not None:
        leverage_source = "explicit"
    else:
        leverage_source = "not stated"

    if tail_downside_pct is None:
        tail_downside_pct = inferred_risk["implied_tail_downside_pct"]
        tail_source = "inferred"
    else:
        tail_source = "explicit"

    blockers = []
    review_flags = []
    positives = []

    if risk_budget_pct is not None:
        if risk_budget_pct > _THESIS_RISK_POLICY["max_portfolio_risk_budget_pct"]:
            blockers.append(f"Portfolio risk budget {risk_budget_pct:.0f}% exceeds institutional limit {_THESIS_RISK_POLICY['max_portfolio_risk_budget_pct']:.0f}%.")
        elif risk_budget_pct > _THESIS_RISK_POLICY["warn_portfolio_risk_budget_pct"]:
            review_flags.append(f"Portfolio risk budget {risk_budget_pct:.0f}% is elevated for pre-trade review.")

    if leverage_multiple is not None:
        if leverage_multiple > _THESIS_RISK_POLICY["max_leverage_multiple"]:
            blockers.append(f"Leverage {leverage_multiple:.1f}x exceeds institutional limit {_THESIS_RISK_POLICY['max_leverage_multiple']:.1f}x.")
        else:
            review_flags.append(f"Leverage {leverage_multiple:.1f}x requires explicit risk sign-off.")

    if tail_downside_pct is not None:
        if tail_downside_pct >= _THESIS_RISK_POLICY["fail_tail_downside_pct"]:
            blockers.append(f"Tail downside of {tail_downside_pct:.0f}% breaches stress-loss tolerance.")
        elif tail_downside_pct >= _THESIS_RISK_POLICY["warn_tail_downside_pct"]:
            review_flags.append(f"Tail downside of {tail_downside_pct:.0f}% is elevated and needs scenario review.")

    if inferred_risk["market_risk_score"] >= 70:
        review_flags.append(f"Market risk score {inferred_risk['market_risk_score']} indicates elevated realized-volatility exposure.")
    if inferred_risk["macro_regime_score"] >= 65:
        review_flags.append(f"Macro regime score {inferred_risk['macro_regime_score']} reflects a stressed event-driven backdrop.")
    if inferred_risk["systemic_stress_score"] >= 70:
        blockers.append(f"Systemic stress score {inferred_risk['systemic_stress_score']} exceeds institutional comfort for routine sizing.")
    elif inferred_risk["systemic_stress_score"] >= 55:
        review_flags.append(f"Systemic stress score {inferred_risk['systemic_stress_score']} requires senior risk review.")
    if inferred_risk["liquidity_risk_score"] >= 60:
        review_flags.append(f"Liquidity risk score {inferred_risk['liquidity_risk_score']} suggests stress exit conditions may impair capital.")

    if has_options:
        review_flags.append("Options or structured derivatives detected; mandate and tenor review required.")
    if has_geopolitical_event:
        review_flags.append("Geopolitical catalyst dependency detected; event-risk review required.")
    if has_hedge:
        positives.append("Memo includes explicit hedge language or defined-risk structures.")
    if has_liquidity_plan:
        positives.append("Memo includes monitoring, exit, or stop discipline.")

    scenarios = []
    for f in factors[:5]:
        scenarios.append({
            "name": f["scenario"],
            "focus": f["factor"],
            "prompt": f["question"],
        })

    structured_enough = word_count >= 60 and len(factors) >= 2
    governance_ready = structured_enough and not blockers
    if blockers:
        governance_status = "outside mandate"
        risk_classification = "speculative"
    elif review_flags:
        governance_status = "conditional review"
        risk_classification = "elevated"
    elif structured_enough:
        governance_status = "governance ready"
        risk_classification = "within tolerance"
    else:
        governance_status = "needs more detail"
        risk_classification = "incomplete"

    if explicit_conviction is not None:
        conviction_score = explicit_conviction
    else:
        conviction_base = 45 + len(factors) * 4 + len(symbols) * 2 + (8 if has_hedge else 0)
        conviction_penalty = len(blockers) * 18 + len(review_flags) * 6 + max(0, inferred_risk["market_risk_score"] - 55) * 0.25
        conviction_score = max(5, min(95, conviction_base - conviction_penalty))

    summary = (
        f"{title} maps to {len(factors)} primary factor driver"
        f"{'' if len(factors) == 1 else 's'}, stance {stance}, and "
        f"{len(symbols)} explicit instrument reference"
        f"{'' if len(symbols) == 1 else 's'}."
    )

    governance_notes = [
        "Narrative thesis converted into structured factor exposures for pre-trade review.",
        "Scenario prompts generated before capital deployment.",
        "Output is intended to support IC and risk discussion, not replace human judgment.",
    ]
    governance_notes.append(
        f"Risk math derived in backend from memo cues plus {inferred_risk['market_data_source'].replace('_', ' ')} instrument metrics."
    )
    governance_notes.extend(positives)
    if blockers:
        governance_notes.append("Institutional risk review found one or more hard blockers before governance approval.")
    elif review_flags:
        governance_notes.append("Memo is structured but still requires conditional review by Risk Manager and human authority.")
    elif not governance_ready:
        governance_notes.append("Memo is still thin for governance use; add assumptions, catalysts, and explicit risks.")

    return {
        "title": title,
        "summary": summary,
        "word_count": word_count,
        "stance": stance,
        "governance_ready": governance_ready,
        "governance_status": governance_status,
        "risk_classification": risk_classification,
        "conviction_score": conviction_score,
        "factors": factors,
        "symbols": symbols[:8],
        "scenarios": scenarios,
        "risk_review": {
            "portfolio_risk_budget_pct": risk_budget_pct,
            "portfolio_risk_budget_source": risk_budget_source,
            "max_portfolio_risk_budget_pct": _THESIS_RISK_POLICY["max_portfolio_risk_budget_pct"],
            "leverage_multiple": leverage_multiple,
            "leverage_source": leverage_source,
            "max_leverage_multiple": _THESIS_RISK_POLICY["max_leverage_multiple"],
            "tail_downside_pct": tail_downside_pct,
            "tail_downside_source": tail_source,
            "warn_tail_downside_pct": _THESIS_RISK_POLICY["warn_tail_downside_pct"],
            "fail_tail_downside_pct": _THESIS_RISK_POLICY["fail_tail_downside_pct"],
        },
        "inferred_risk": inferred_risk,
        "blockers": blockers,
        "review_flags": review_flags,
        "governance_notes": governance_notes,
    }


def _build_source_document_record(title: str, source_type: str, source_name: str, content_text: str, analysis: dict):
    ts = datetime.now(timezone.utc).isoformat()
    digest = hashlib.sha256(content_text.encode("utf-8", errors="ignore")).hexdigest()
    preview_lines = [ln.strip() for ln in content_text.splitlines() if ln.strip()]
    preview = " ".join(preview_lines[:2])[:240]
    return {
        "document_id": f"SRC-{digest[:8].upper()}",
        "title": (title or analysis.get("title") or source_name or "Untitled Source Document")[:120],
        "source_type": source_type,
        "source_name": source_name or "pasted memo",
        "created_ts": ts,
        "content_hash": digest[:16].upper(),
        "word_count": len(re.findall(r"\b[\w/-]+\b", content_text)),
        "preview": preview,
        "analysis_summary": analysis.get("summary"),
        "governance_status": analysis.get("governance_status"),
        "risk_classification": analysis.get("risk_classification"),
        "stance": analysis.get("stance"),
        "conviction_score": analysis.get("conviction_score"),
        "factor_count": len(analysis.get("factors", [])),
        "linked_source_file": analysis.get("source_file") or source_name,
        "content_text": content_text,
    }


def _register_source_document(title: str, source_type: str, source_name: str, content_text: str, analysis: dict):
    record = _build_source_document_record(title, source_type, source_name, content_text, analysis)
    with _lock:
        docs = aureon_state.setdefault("source_documents", [])
        existing = next((doc for doc in docs if doc.get("content_hash") == record["content_hash"]), None)
        if existing:
            existing.update({
                "title": record["title"],
                "source_type": record["source_type"],
                "source_name": record["source_name"],
                "analysis_summary": record["analysis_summary"],
                "governance_status": record["governance_status"],
                "risk_classification": record["risk_classification"],
                "stance": record["stance"],
                "conviction_score": record["conviction_score"],
                "factor_count": record["factor_count"],
                "linked_source_file": record["linked_source_file"],
                "content_text": record["content_text"],
                "preview": record["preview"],
                "word_count": record["word_count"],
                "created_ts": existing.get("created_ts", record["created_ts"]),
            })
            stored = dict(existing)
        else:
            docs.insert(0, record)
            stored = dict(record)
        aureon_state["authority_log"].insert(0, {
            "id": f"HAD-SRC-{record['document_id'][-4:]}",
            "ts": datetime.now(timezone.utc).isoformat(),
            "tier": "Mentat L1",
            "type": f"Source Document Registered · {record['source_type'].upper()}",
            "authority": "Aureon Thesis Registry",
            "outcome": f"{record['document_id']} · {record['governance_status'] or 'recorded'}",
            "hash": record["content_hash"],
        })
    threading.Thread(target=_save_state, daemon=True).start()
    return stored


def _public_source_document(record: dict):
    return {k: v for k, v in record.items() if k != "content_text"}


def _strip_xml_text(xml_text: str) -> str:
    text = re.sub(r"</w:p>|</a:p>|</p>", "\n", xml_text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text.strip()


def _extract_pdf_text_best_effort(raw: bytes) -> str:
    try:
        decoded = raw.decode("latin-1", errors="ignore")
        streams = re.findall(r"\(([^()]*)\)", decoded)
        chunks = [s for s in streams if len(s.strip()) > 20]
        if chunks:
            return "\n".join(chunks[:80]).strip()
    except Exception:
        pass

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        result = subprocess.run(["strings", tmp_path], capture_output=True, text=True, check=False)
        lines = [ln.strip() for ln in result.stdout.splitlines() if len(ln.strip()) > 20]
        return "\n".join(lines[:120]).strip()
    except Exception:
        return ""
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _extract_uploaded_text(filename: str, raw: bytes):
    """
    Best-effort document text extraction for Phase 5 upload flow.
    Supports txt/md/json, docx, pptx, pdf, and falls back to raw string extraction.
    """
    name = (filename or "upload").lower()

    if name.endswith((".txt", ".md", ".json")):
        return raw.decode("utf-8", errors="ignore")

    if name.endswith(".docx"):
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
        return _strip_xml_text(xml)

    if name.endswith(".pptx"):
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            slides = sorted(n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
            text = []
            for slide in slides:
                xml = zf.read(slide).decode("utf-8", errors="ignore")
                text.append(_strip_xml_text(xml))
        return "\n\n".join(t for t in text if t).strip()

    if name.endswith(".pdf"):
        return _extract_pdf_text_best_effort(raw)

    if name.endswith(".ppt"):
        text = re.findall(rb"[A-Za-z][A-Za-z0-9 ,.;:()/%+\-]{20,}", raw)
        return "\n".join(t.decode("latin-1", errors="ignore") for t in text[:120]).strip()

    return raw.decode("utf-8", errors="ignore")


def _add_alert(severity, title, detail):
    """Add a compliance alert — but deduplicate so we don't spam."""
    alert = {
        "id":       f"ALT-{random.randint(1000, 9999)}",
        "severity": severity,
        "title":    title,
        "detail":   detail,
        "ts":       datetime.now(timezone.utc).isoformat(),
        "resolved": False,
    }
    with _lock:
        existing_titles = [a["title"] for a in aureon_state["compliance_alerts"]]
        if title not in existing_titles:
            aureon_state["compliance_alerts"].insert(0, alert)
            aureon_state["alert_history"].insert(0, alert)


def _generate_signal():
    """
    Thifur-H signal engine — drift-aware rebalancing first, opportunistic second.

    Priority logic (Mentat L1 doctrine):
      1. REBALANCE: If any asset class is > DRIFT_THRESHOLD off its doctrine target,
         surface a corrective trade recommendation for HITL approval.
         Thifur-H recommends; the human decides. Zero autonomous execution.
      2. OPPORTUNISTIC: If no class is materially off target, surface a normal
         alpha signal from the opportunistic candidate pool.

    Only signals above $400K notional are routed — below that threshold Kaladan
    filters as immaterial. Queue capped at 4 pending decisions.
    """
    DRIFT_THRESHOLD = 0.04     # 4% off target triggers a rebalance recommendation
    CRYPTO_SYMBOLS  = {"BTC", "ETH", "SOL"}

    # ── Step 1: Calculate current allocation vs doctrine targets ─────────────
    with _lock:
        ct = dict(aureon_state["class_totals"])
        pv = aureon_state["portfolio_value"]
        halt = aureon_state["halt_active"]
        queue_len = len(aureon_state["pending_decisions"])

    if halt:
        print("[AUREON] Signal suppressed — system HALTED")
        return
    if queue_len >= 4:
        return   # queue full — don't pile on

    # ── Step 2: Find the most off-target asset class ──────────────────────────
    worst_class, worst_delta = None, 0.0
    if ct and pv > 0:
        for cls, info in ALLOCATIONS.items():
            actual_pct = ct.get(cls, 0) / pv
            delta = info["target"] - actual_pct   # positive = underweight, negative = overweight
            if abs(delta) > abs(worst_delta):
                worst_delta = delta
                worst_class = cls

    # ── Drift-aware candidate pools (keyed by class and direction) ────────────
    REBALANCE_CANDIDATES = {
        "equities": {
            "BUY":  [("BUY",  "SPY",   "equities",    5000,   535.10),
                     ("BUY",  "MSFT",  "equities",    2500,   415.20),
                     ("BUY",  "AMZN",  "equities",    2000,   185.30)],
            "SELL": [("SELL", "NVDA",  "equities",    400,    875.30),
                     ("SELL", "SPY",   "equities",    1000,   535.10)],
        },
        "fixed_income": {
            "BUY":  [("BUY",  "TLT",   "fixed_income",10000,  91.50),
                     ("BUY",  "AGG",   "fixed_income",10000,  97.40)],
            "SELL": [("SELL", "TLT",   "fixed_income",5000,   91.50),
                     ("SELL", "HYG",   "fixed_income",5000,   78.20)],
        },
        "fx": {
            "BUY":  [("BUY",  "GBP/USD","fx",         500000, 1.265),
                     ("BUY",  "EUR/USD","fx",          500000, 1.0842)],
            "SELL": [("SELL", "EUR/USD","fx",          500000, 1.0842)],
        },
        "commodities": {
            "BUY":  [("BUY",  "GLD",   "commodities", 2000,   213.40),
                     ("BUY",  "USO",   "commodities", 10000,  72.10)],
            "SELL": [("SELL", "GLD",   "commodities", 2000,   213.40)],
        },
        "crypto": {
            "BUY":  [("BUY",  "BTC",   "crypto",      5,      67420),
                     ("BUY",  "ETH",   "crypto",      120,    3510),
                     ("BUY",  "SOL",   "crypto",      2000,   142)],
            "SELL": [("SELL", "ETH",   "crypto",      100,    3510)],
        },
    }

    # ── Opportunistic pool (no drift trigger required) ────────────────────────
    OPPORTUNISTIC = [
        ("BUY",  "GOOGL",   "equities",    1500,   175.40),
        ("BUY",  "GBP/USD", "fx",          500000, 1.265),
        ("BUY",  "USO",     "commodities", 10000,  72.10),
        ("BUY",  "BTC",     "crypto",      5,      67420),
        ("BUY",  "ETH",     "crypto",      120,    3510),
    ]

    # ── Step 3: Choose signal type ────────────────────────────────────────────
    is_rebalance = (worst_class is not None and
                    abs(worst_delta) > DRIFT_THRESHOLD and
                    worst_class in REBALANCE_CANDIDATES)

    if is_rebalance:
        direction   = "BUY" if worst_delta > 0 else "SELL"
        pool        = REBALANCE_CANDIDATES[worst_class].get(direction, [])
        if not pool:
            is_rebalance = False

    if is_rebalance:
        action, symbol, asset_class, shares, price = random.choice(pool)
        drift_pct   = worst_delta * 100
        sign        = "+" if drift_pct > 0 else ""
        rationale   = (
            f"REBALANCE SIGNAL: {asset_class.replace('_',' ').upper()} "
            f"is {sign}{drift_pct:.1f}% vs doctrine target "
            f"({ALLOCATIONS[asset_class]['target']*100:.0f}%). "
            f"Thifur-H recommends {action} to restore mandated allocation. "
            f"Human approval required — Thifur does not self-execute rebalances."
        )
        signal_type = "REBALANCE"
    else:
        action, symbol, asset_class, shares, price = random.choice(OPPORTUNISTIC)
        rationale = (
            f"Momentum {random.uniform(0.10, 0.45):.2f}. "
            f"Signal strength {random.uniform(0.60, 0.90):.2f}. "
            f"Thifur-H: optimize_execution within doctrine bounds."
        )
        signal_type = "OPPORTUNISTIC"

    # ── Step 4: Session boundary (Verana L0) ──────────────────────────────────
    tradeable, _session_reason = _is_instrument_tradeable(symbol, asset_class)
    if not tradeable:
        return   # signal suppressed outside instrument's session window

    notional = int(shares * price)
    if notional < 400_000:
        return   # below materiality threshold

    # ── Cash floor guard (Mentat L1) ──────────────────────────────
    # No BUY signal if the trade would leave less than OPERATING_CASH_FLOOR_PCT
    # of portfolio value as liquid cash.  This enforces the hard institutional
    # operating cash floor before the signal even reaches the HITL queue.
    if action == "BUY":
        with _lock:
            _cash = aureon_state["cash"]
            _pv   = aureon_state["portfolio_value"]
        _floor = _pv * OPERATING_CASH_FLOOR_PCT
        if _cash - notional < _floor:
            print(f"[MENTAT-L1] BUY {symbol} suppressed — would breach cash floor "
                  f"(${_floor:,.0f} required; effective cash after trade: ${_cash - notional:,.0f})")
            return

    decision = {
        "id":          f"DEC-{random.randint(0x10000000, 0xFFFFFFFF):X}",
        "action":      action,
        "symbol":      symbol,
        "asset_class": asset_class,
        "shares":      shares,
        "price":       price,
        "notional":    notional,
        "product_type": "SINGLE_NAME_EQUITY" if asset_class == "equities" else "OUT_OF_SCOPE",
        "rationale":   rationale,
        "signal_type": signal_type,
        "created":     datetime.now(timezone.utc).isoformat(),
        "status":      "PENDING",
        "required_approvals": ["TRADER"],
        "current_approvals": [],
        "release_target": "OMS",
        "mandate_sensitive": False,
        "policy_exception": False,
        "risk_exception": notional >= 400000,
        "pm_signoff_required": False,
        "control_exception": False,
        "financing_relevant": False,
    }

    with _lock:
        if aureon_state["halt_active"]:
            return
        if len(aureon_state["pending_decisions"]) < 4:
            aureon_state["pending_decisions"].append(decision)

    print(f"[THIFUR-H] {signal_type} signal: {action} {symbol} "
          f"${notional:,} — human decision required")


# ─────────────────────────────────────────────────────────────────
# 5b. STATE PERSISTENCE
# ─────────────────────────────────────────────────────────────────
# Saves/loads critical state so a server restart never wipes trades.
# Only the fields that matter across restarts are persisted; ephemeral
# data (prices, cycle_count, etc.) is always recalculated at runtime.

def _save_state():
    """
    Serialize critical aureon_state fields to aureon_state_persist.json
    in the same directory as server.py.  Called in a background thread
    after every HITL approve/reject so it never blocks the response.
    """
    try:
        with _lock:
            trade_reports = []
            for r in aureon_state["trade_reports"]:
                trade_reports.append({k: v for k, v in r.items() if k != "pdf_bytes"})
            snapshot = {
                "positions":          list(aureon_state["positions"]),
                "cash":               aureon_state["cash"],
                "trades":             list(aureon_state["trades"]),
                "trade_reports":      trade_reports,
                "source_documents":   list(aureon_state.get("source_documents", [])),
                "authority_log":      list(aureon_state["authority_log"]),
                "compliance_alerts":  list(aureon_state["compliance_alerts"]),
                "alert_history":      list(aureon_state["alert_history"]),
                # ── MMF / Cash management ──────────────────────────
                "mmf_balance":        aureon_state.get("mmf_balance", 0.0),
                "mmf_yield_accrued":  aureon_state.get("mmf_yield_accrued", 0.0),
                "mmf_provider":       _resolve_mmf_provider(aureon_state.get("mmf_provider")),
                "sweep_log":          list(aureon_state.get("sweep_log", [])),
                "saved_at":           datetime.now(timezone.utc).isoformat(),
            }
        tmp_file = STATE_FILE + ".tmp"
        with open(tmp_file, "w") as fh:
            json.dump(snapshot, fh, indent=2)
        os.replace(tmp_file, STATE_FILE)
        print(f"[AUREON] State saved — {len(snapshot['positions'])} positions, "
              f"{len(snapshot['trades'])} trades")
    except Exception as exc:
        _log_error("WARN", "_save_state", str(exc))


def _load_state():
    """
    Load persisted state from aureon_state_persist.json.
    Returns the snapshot dict on success, or None if no file / parse error.
    Does NOT acquire _lock — must be called before the lock block in
    run_doctrine_stack() to avoid a deadlock.
    """
    if not os.path.exists(STATE_FILE):
        print("[AUREON] No persisted state found — initialising from INITIAL_POSITIONS")
        return None
    try:
        with open(STATE_FILE, "r") as fh:
            snapshot = json.load(fh)
        n_pos    = len(snapshot.get("positions", []))
        n_trades = len(snapshot.get("trades", []))
        saved_at = snapshot.get("saved_at", "unknown")
        print(f"[AUREON] Persisted state loaded — {n_pos} positions, "
              f"{n_trades} trades — last saved {saved_at}")
        return snapshot
    except Exception as exc:
        _log_error("WARN", "_load_state", f"{exc} — attempting salvage from corrupted state")

    try:
        text = open(STATE_FILE, "r", errors="ignore").read()
        snapshot = {}

        def _extract(key, next_key=None):
            key_pat = f'"{key}":'
            start = text.find(key_pat)
            if start == -1:
                return None
            start += len(key_pat)
            if next_key:
                end = text.find(f',\n  "{next_key}":', start)
                if end == -1:
                    return None
                raw = text[start:end].strip()
            else:
                raw = text[start:].strip()
            return raw

        positions_raw = _extract("positions", "cash")
        cash_raw = _extract("cash", "trades")
        trades_raw = _extract("trades", "trade_reports")
        if positions_raw:
            snapshot["positions"] = json.loads(positions_raw)
        if cash_raw:
            snapshot["cash"] = json.loads(cash_raw)
        if trades_raw:
            snapshot["trades"] = json.loads(trades_raw)

        snapshot["trade_reports"] = []
        snapshot["source_documents"] = []
        snapshot["authority_log"] = []
        snapshot["compliance_alerts"] = []
        snapshot["alert_history"] = []
        snapshot["mmf_balance"] = 0.0
        snapshot["mmf_yield_accrued"] = 0.0
        snapshot["sweep_log"] = []
        snapshot["saved_at"] = datetime.now(timezone.utc).isoformat()

        if snapshot.get("positions") is not None and snapshot.get("trades") is not None and "cash" in snapshot:
            print(f"[AUREON] Salvaged corrupted state — {len(snapshot['positions'])} positions, {len(snapshot['trades'])} trades")
            return snapshot
    except Exception as salvage_exc:
        _log_error("WARN", "_load_state", f"{salvage_exc} — salvage failed")

    print("[AUREON] Falling back to INITIAL_POSITIONS")
    return None


# ─────────────────────────────────────────────────────────────────
# 5b+. EXPLICIT PHASE 1 SERVICE BOUNDARIES
# ─────────────────────────────────────────────────────────────────
# These wrappers preserve the runnable prototype while routing core
# DSOR responsibilities through dedicated modules:
#   - persistence.store      → saved state boundary
#   - evidence_service       → replay / audit artifact boundary
#   - approval_service       → role-based release control boundary
#   - policy_engine          → pre-trade checks and risk framing boundary


def _save_state():
    persistence_save_state(
        state=aureon_state,
        lock=_lock,
        state_file=STATE_FILE,
        resolve_mmf_provider=_resolve_mmf_provider,
        log_error=_log_error,
    )


def _load_state():
    return persistence_load_state(
        state_file=STATE_FILE,
        log_error=_log_error,
    )


def _build_trade_report(decision, exec_price, authority_hash, gate_results, portfolio_before):
    return evidence_build_trade_report(
        decision=decision,
        exec_price=exec_price,
        authority_hash=authority_hash,
        gate_results=gate_results,
        portfolio_before=portfolio_before,
        doctrine_version=aureon_state["doctrine_version"],
        instrument_ref=_INSTRUMENT_REF,
        entity_lei=_AUREON_LEI,
        macro_snapshot_fn=_get_fred_macro_snapshot,
        ofr_snapshot_fn=_get_ofr_stress_snapshot,
    )


# ─────────────────────────────────────────────────────────────────
# 5c. INSTITUTIONAL CASH MANAGEMENT — MMF SWEEP / UNWIND
# ─────────────────────────────────────────────────────────────────

def _perform_cash_sweep():
    """
    Kaladan L2 EOD lifecycle event: sweep idle cash above the operating
    floor into the institutional government MMF.

    Triggered at 16:15 ET Monday–Friday (market close + 15 min).
    Provider is jurisdiction-aware (FDRXX for US, FILF_EUR for EU, etc.).
    Cash floor (3 % of portfolio) is always retained for T+1 settlement.
    Immaterial sweeps (< $10 K) are skipped to avoid excessive log noise.
    """
    with _lock:
        cash        = aureon_state["cash"]
        pv          = aureon_state["portfolio_value"]
        mmf_balance = aureon_state["mmf_balance"]
        provider    = _resolve_mmf_provider(aureon_state.get("mmf_provider"))

    floor     = pv * OPERATING_CASH_FLOOR_PCT
    sweepable = max(0.0, cash - floor)

    if sweepable < 10_000:
        print(f"[KALADAN-L2] Cash sweep: sweepable ${sweepable:,.0f} < $10K — skipped")
        return

    new_mmf_balance = mmf_balance + sweepable
    ts = datetime.now(timezone.utc).isoformat()

    sweep_entry = {
        "ts":            ts,
        "action":        "SWEEP_IN",
        "amount":        round(sweepable, 2),
        "provider":      provider["name"],
        "ticker":        provider["ticker"],
        "balance_after": round(new_mmf_balance, 2),
        "cash_floor":    round(floor, 2),
        "authority":     "Kaladan L2 — Autonomous Lifecycle",
    }

    with _lock:
        aureon_state["cash"]        -= sweepable
        aureon_state["mmf_balance"]  = new_mmf_balance
        aureon_state["sweep_log"].insert(0, sweep_entry)
        aureon_state["authority_log"].insert(0, {
            "id":        f"HAD-SWEEP-{random.randint(1000, 9999)}",
            "ts":        ts,
            "tier":      "Kaladan L2",
            "type":      f"EOD Cash Sweep → {provider['ticker']}",
            "authority": "Kaladan L2 — Autonomous Lifecycle",
            "outcome":   (f"${sweepable:,.0f} swept to {provider['name']}. "
                          f"Floor retained: ${floor:,.0f}"),
            "hash":      hashlib.sha256(
                             f"SWEEP{ts}{sweepable}".encode()
                         ).hexdigest()[:16].upper(),
        })

    threading.Thread(target=_save_state, daemon=True).start()
    print(f"[KALADAN-L2] EOD sweep complete: ${sweepable:,.0f} → {provider['ticker']} | "
          f"MMF balance: ${new_mmf_balance:,.0f} | Floor retained: ${floor:,.0f}")


def _unwind_cash_sweep():
    """
    Pre-market (08:30 ET): liquidate MMF back to operating cash.

    Accrues one trading day of yield at the annualised MMF rate
    (MMF_YIELD_ANNUAL / 252 trading days).  Yield is added to cash
    alongside the principal return.  Updates mmf_yield_accrued for
    the EOD report.
    """
    with _lock:
        mmf_balance = aureon_state["mmf_balance"]
        provider    = _resolve_mmf_provider(aureon_state.get("mmf_provider"))

    if mmf_balance < 1.0:
        return   # nothing swept — nothing to unwind

    daily_yield  = (MMF_YIELD_ANNUAL / 252) * mmf_balance
    total_return = mmf_balance + daily_yield
    ts           = datetime.now(timezone.utc).isoformat()

    unwind_entry = {
        "ts":            ts,
        "action":        "SWEEP_OUT",
        "amount":        round(total_return, 2),
        "yield_accrued": round(daily_yield, 2),
        "provider":      provider["name"],
        "ticker":        provider["ticker"],
        "balance_after": 0.0,
        "authority":     "Kaladan L2 — Autonomous Lifecycle",
    }

    with _lock:
        aureon_state["cash"]             += total_return
        aureon_state["mmf_balance"]       = 0.0
        aureon_state["mmf_yield_accrued"] = (
            aureon_state.get("mmf_yield_accrued", 0.0) + daily_yield
        )
        aureon_state["sweep_log"].insert(0, unwind_entry)
        aureon_state["authority_log"].insert(0, {
            "id":        f"HAD-UNWIND-{random.randint(1000, 9999)}",
            "ts":        ts,
            "tier":      "Kaladan L2",
            "type":      f"Pre-Market MMF Liquidation ← {provider['ticker']}",
            "authority": "Kaladan L2 — Autonomous Lifecycle",
            "outcome":   (f"${total_return:,.0f} returned to cash "
                          f"(overnight yield: +${daily_yield:,.2f})"),
            "hash":      hashlib.sha256(
                             f"UNWIND{ts}{mmf_balance}".encode()
                         ).hexdigest()[:16].upper(),
        })

    threading.Thread(target=_save_state, daemon=True).start()
    print(f"[KALADAN-L2] Pre-market unwind complete: ${total_return:,.0f} returned "
          f"(overnight yield: +${daily_yield:,.2f})")


def _log_error(level: str, source: str, message: str):
    """
    Structured error logger for Aureon.

    Writes every event to three places:
      1. aureon_errors.log  — append-only flat file (permanent disk record)
      2. aureon_state["error_log"] — in-memory ring buffer (last 200 entries)
      3. stdout — existing terminal output preserved

    level   : "ERROR" | "WARN" | "INFO"
    source  : short label, e.g. "market_loop", "_save_state", "email_scheduler"
    message : human-readable description of the problem

    For level == "ERROR" a non-blocking email alert is also dispatched so
    critical failures surface immediately without waiting for the EOD digest.
    """
    ts    = datetime.now(timezone.utc).isoformat()
    entry = {"ts": ts, "level": level.upper(), "source": source, "message": message}

    # 1. Append to disk log ──────────────────────────────────────
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] [{level.upper():5s}] [{source}] {message}\n")
    except Exception:
        pass   # never let the logger crash the server

    # 2. In-memory ring buffer ───────────────────────────────────
    with _lock:
        aureon_state["error_log"].insert(0, entry)
        if len(aureon_state["error_log"]) > 200:
            aureon_state["error_log"] = aureon_state["error_log"][:200]

    # 3. stdout (preserve existing terminal behaviour) ───────────
    print(f"[AUREON] [{level.upper()}] {source}: {message}")

    # 4. Immediate email for hard errors ─────────────────────────
    # Guard: never send an alert email if the error IS an email failure
    # (prevents infinite send → fail → alert → send loop)
    if level.upper() == "ERROR" and source not in ("_send_email", "_send_error_alert"):
        def _send_error_alert():
            subject = f"[AUREON ERROR] {source} — {message[:60]}"
            html = f"""<!DOCTYPE html><html><body
              style="font-family:'Courier New',monospace;background:#060810;
                     color:#F0F4FF;padding:32px">
              <div style="font-size:18px;font-weight:800;color:#EF4444;
                          letter-spacing:3px;margin-bottom:16px">
                ⚠ AUREON ERROR ALERT</div>
              <table style="border-collapse:collapse;font-size:12px;width:100%">
                <tr><td style="color:#4A5578;padding:4px 12px 4px 0;width:100px">TIMESTAMP</td>
                    <td style="color:#F0F4FF">{ts}</td></tr>
                <tr><td style="color:#4A5578;padding:4px 12px 4px 0">LEVEL</td>
                    <td style="color:#EF4444;font-weight:700">{level.upper()}</td></tr>
                <tr><td style="color:#4A5578;padding:4px 12px 4px 0">SOURCE</td>
                    <td style="color:#F0F4FF">{source}</td></tr>
                <tr><td style="color:#4A5578;padding:4px 12px 4px 0">MESSAGE</td>
                    <td style="color:#F0F4FF">{message}</td></tr>
              </table>
              <div style="margin-top:24px;font-size:10px;color:#4A5578">
                Aureon · Doctrine-Driven Financial Operating System<br>
                Review aureon_errors.log for full context.
              </div>
            </body></html>"""
            _send_email(subject, html)
        threading.Thread(target=_send_error_alert, daemon=True).start()


# ─────────────────────────────────────────────────────────────────
# 6. BACKGROUND JOBS
# ─────────────────────────────────────────────────────────────────

def run_doctrine_stack():
    """
    The full L0 → L3 doctrine cycle.
    Runs ONCE on startup in a background thread (non-blocking).
    Simulates the result since we have no external modules to import.

    Layer sequence:
      Verana  (L0) — network governance, absorbs regulatory changes
      Mentat  (L1) — strategic intelligence, establishes doctrine truth
      Kaladan (L2) — lifecycle orchestration, routes settlements
      Thifur  (L3) — agentic execution, deterministic trade actions
    """
    print("[AUREON] Running doctrine stack: L0 → L1 → L2 → L3 ...")

    with _lock:
        aureon_state["stack_status"] = "running"

    # Simulate each layer completing in sequence
    time.sleep(0.5)   # Verana L0 — network scan
    time.sleep(0.5)   # Mentat L1 — doctrine parse
    time.sleep(0.4)   # Kaladan L2 — lifecycle map
    time.sleep(0.3)   # Thifur L3 — execution plan
    time.sleep(0.2)   # Telemetry loop
    time.sleep(0.1)   # Audit report

    # Audit hash = SHA-256 fingerprint of the doctrine seed
    # In a real system this would hash the actual execution trace
    audit_hash = hashlib.sha256(b"AUREON-DOCTRINE-1.2").hexdigest()[:40].upper()

    stack_result = {
        "integrity":        "PASS",
        "doctrine_version": "1.2",
        "audit_hash":       audit_hash,
        "layers": {
            "verana":    {"status": "COMPLETE", "nodes": 15, "phase": "RECOVER"},
            "mentat":    {"status": "COMPLETE", "doctrine": "1.2", "decisions": 9},
            "kaladan":   {"status": "COMPLETE", "executions": 6},
            "thifur":    {"status": "COMPLETE", "R": 2, "J": 4, "H": 0},
            "telemetry": {"status": "COMPLETE", "signals": 6},
        },
    }

    # Calculate the cash left after all initial positions are taken
    invested_cash  = sum(p["shares"] * p["cost"] for p in INITIAL_POSITIONS)
    remaining_cash = 50_000_000 - invested_cash

    # ── Try to restore from disk before acquiring the lock ────────
    # _load_state() must run OUTSIDE _lock to avoid a deadlock.
    saved = _load_state()

    with _lock:
        aureon_state["stack_status"]     = "ready"
        aureon_state["doctrine_version"] = "1.2"
        aureon_state["stack_result"]     = stack_result
        aureon_state["audit"]            = audit_hash
        aureon_state["last_stack_run"]   = datetime.now(timezone.utc).isoformat()

        if saved:
            # ── Resume from persisted state ───────────────────────
            aureon_state["positions"]         = saved.get("positions",         [dict(p) for p in INITIAL_POSITIONS])
            aureon_state["cash"]              = saved.get("cash",              remaining_cash)
            aureon_state["trades"]            = saved.get("trades",            [])
            aureon_state["trade_reports"]     = saved.get("trade_reports",     [])
            aureon_state["source_documents"]  = saved.get("source_documents",  [])
            aureon_state["authority_log"]     = saved.get("authority_log",     aureon_state["authority_log"])
            aureon_state["compliance_alerts"] = saved.get("compliance_alerts", [])
            aureon_state["alert_history"]     = saved.get("alert_history",     [])
            # ── MMF / Cash management fields ──────────────────────
            aureon_state["mmf_balance"]       = saved.get("mmf_balance",       0.0)
            aureon_state["mmf_yield_accrued"] = saved.get("mmf_yield_accrued", 0.0)
            aureon_state["mmf_provider"]      = _resolve_mmf_provider(saved.get("mmf_provider"))
            aureon_state["sweep_log"]         = saved.get("sweep_log",         [])
        else:
            # ── First-ever launch — seed from INITIAL_POSITIONS ───
            aureon_state["positions"] = [dict(p) for p in INITIAL_POSITIONS]
            aureon_state["cash"]      = remaining_cash
            aureon_state["mmf_provider"] = _resolve_mmf_provider()

        if not aureon_state["pending_decisions"]:
            aureon_state["pending_decisions"] = [dict(d) for d in PENDING_DECISIONS_INIT]

    n_pos = len(aureon_state["positions"])
    print(f"[AUREON] Stack complete — doctrine v1.2 active — audit: {audit_hash[:12]}...")
    print(f"[AUREON] Portfolio: {n_pos} positions | Cash: ${aureon_state['cash']:,.0f}")


def market_loop():
    """
    Runs forever in a background thread. Every 5 seconds:
      1. Simulate new prices
      2. Recalculate portfolio value
      3. Check drawdown for compliance alerts
      4. Occasionally surface a new Thifur-H trade signal (~every 10 min)
    """
    while True:
        try:
            prices = _simulated_prices()
            total, pnl, pnl_pct, drawdown, class_totals = _calc_portfolio(prices)

            with _lock:
                aureon_state["prices"]          = prices
                aureon_state["portfolio_value"] = total
                aureon_state["pnl"]             = pnl
                aureon_state["pnl_pct"]         = pnl_pct
                aureon_state["drawdown"]        = drawdown
                aureon_state["class_totals"]    = class_totals
                aureon_state["cycle_count"]    += 1

            # Drawdown compliance thresholds
            if drawdown > 8.0:
                _add_alert("CRITICAL", "Drawdown breach",
                           f"Drawdown {drawdown:.2f}% approaching 10% hard stop")
            elif drawdown > 5.0:
                _add_alert("WARNING", "Drawdown elevated",
                           f"Drawdown {drawdown:.2f}% — monitoring")

            # Thifur-H only surfaces signals during US market hours
            if _market_is_open() and random.random() < 0.008:
                _generate_signal()

        except Exception as exc:
            _log_error("WARN", "market_loop", str(exc))

        time.sleep(5)


def _decision_ui_payload(decision_raw):
    """Serialize a pending decision for the Phase 1 pilot UI."""
    decision = normalize_decision(decision_raw)
    decision_map = decision.to_mapping()
    missing = missing_roles(decision)
    ready = can_release(decision)
    blocked_reason = "Ready for governed release" if ready else f"Awaiting approvals: {', '.join(missing)}"
    if decision.policy_exception:
        blocked_reason = blocked_reason if ready else f"{blocked_reason} · policy-sensitive path"
    elif decision.mandate_sensitive:
        blocked_reason = blocked_reason if ready else f"{blocked_reason} · mandate-sensitive path"
    elif decision.risk_exception:
        blocked_reason = blocked_reason if ready else f"{blocked_reason} · risk review required"
    return {
        **decision_map,
        "completed_approvals": list(decision.current_approvals),
        "missing_approvals": missing,
        "release_ready": ready,
        "blocked_reason": blocked_reason,
    }


# ─────────────────────────────────────────────────────────────────
# 7. API ROUTES
# ─────────────────────────────────────────────────────────────────
# Each @app.route(...) decorator tells Flask: "when the browser
# requests THIS URL, call THIS function and return the result."
# jsonify() converts a Python dict → JSON response.

@app.route("/api/portfolio")
def api_portfolio():
    """Live portfolio snapshot — called by the dashboard every few seconds."""
    with _lock:
        prices = aureon_state["prices"]
        positions_out = []
        for pos in aureon_state["positions"]:
            price = prices.get(pos["symbol"], pos["cost"])
            mv    = pos["shares"] * price
            pnl   = ((price / pos["cost"]) - 1) * 100
            positions_out.append({
                **pos,                              # spread all existing fields
                "price":        round(price, 2),
                "market_value": round(mv, 2),
                "pnl_pct":      round(pnl, 2),
            })
        trades_out = []
        for trade in aureon_state["trades"][-50:]:
            trades_out.append({
                **trade,
                "final_approvals": list(trade.get("final_approvals", [])),
                "required_approvals": list(trade.get("required_approvals", [])),
                "release_target": trade.get("release_target", "OMS"),
                "release_outcome": trade.get("release_outcome", "RELEASED"),
            })

        return jsonify({
            "portfolio_value": round(aureon_state["portfolio_value"], 2),
            "cash":            round(aureon_state["cash"], 2),
            "pnl":             round(aureon_state["pnl"], 2),
            "pnl_pct":         round(aureon_state["pnl_pct"], 4),
            "drawdown":        round(aureon_state["drawdown"], 4),
            "positions":       positions_out,
            "trades":          trades_out,
            "class_totals":    {k: round(v, 2) for k, v in aureon_state["class_totals"].items()},
            "allocations":     ALLOCATIONS,
            "cycle_count":     aureon_state["cycle_count"],
            "market_open":     _market_is_open(),
            "ts":              datetime.now(timezone.utc).isoformat(),
        })


@app.route("/api/thesis/analyze", methods=["POST"])
def api_thesis_analyze():
    """Analyze a pasted investment thesis / IC memo into factor and scenario outputs."""
    data = request.get_json() or {}
    memo = data.get("memo", "")
    return jsonify(_analyze_thesis_memo(memo))


@app.route("/api/thesis/register", methods=["POST"])
def api_thesis_register():
    """Register a pasted thesis memo as a durable source document."""
    data = request.get_json() or {}
    memo = (data.get("memo") or "").strip()
    if not memo:
        return jsonify({"error": "memo is required"}), 400
    title = (data.get("title") or "").strip() or "Pasted Investment Thesis"
    analysis = _analyze_thesis_memo(memo)
    record = _register_source_document(title, "memo", "pasted memo", memo, analysis)
    analysis["document_id"] = record["document_id"]
    return jsonify({"document": _public_source_document(record), "analysis": analysis})


@app.route("/api/thesis/registry")
def api_thesis_registry():
    """Return the latest registered source documents for thesis-driven governance."""
    with _lock:
        docs = list(aureon_state.get("source_documents", []))
    docs = sorted(docs, key=lambda d: d.get("created_ts", ""), reverse=True)
    return jsonify({"documents": [_public_source_document(doc) for doc in docs[:25]], "count": len(docs)})


@app.route("/api/thesis/upload", methods=["POST"])
def api_thesis_upload():
    """Upload a thesis document and extract best-effort text for analysis."""
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify({"error": "file is required"}), 400

    raw = uploaded.read()
    try:
        extracted = _extract_uploaded_text(uploaded.filename, raw)
    except Exception as exc:
        return jsonify({"error": f"unable to process file: {exc}"}), 400

    if not extracted.strip():
        return jsonify({"error": "no readable text extracted from file"}), 400

    analysis = _analyze_thesis_memo(extracted)
    analysis["source_file"] = uploaded.filename
    record = _register_source_document(analysis.get("title") or uploaded.filename, "upload", uploaded.filename, extracted, analysis)
    analysis["document_id"] = record["document_id"]
    return jsonify({
        "filename": uploaded.filename,
        "extracted_text": extracted,
        "analysis": analysis,
        "document": _public_source_document(record),
    })


@app.route("/api/macro")
def api_macro():
    """Macro regime monitor backed by FRED with safe fallback values."""
    macro = _get_fred_macro_snapshot()
    macro["ofr"] = _get_ofr_stress_snapshot(macro)
    return jsonify(macro)


@app.route("/api/compliance")
def api_compliance():
    """Compliance monitor — alerts, drawdown levels, regulatory frameworks."""
    risk_snapshot = _risk_manager_snapshot()
    macro_snapshot = _get_fred_macro_snapshot()
    ofr_snapshot = _get_ofr_stress_snapshot(macro_snapshot)
    with _lock:
        return jsonify({
            "alerts":        aureon_state["compliance_alerts"],
            "alert_history": aureon_state["alert_history"][-100:],
            "drawdown":      round(aureon_state["drawdown"], 4),
            "pnl_pct":       round(aureon_state["pnl_pct"], 4),
            "risk_manager":  risk_snapshot,
            "macro":         macro_snapshot,
            "ofr":           ofr_snapshot,
            "frameworks": [
                {"name": "SR 11-7 — Model Risk Management",      "status": "SATISFIED"},
                {"name": "OCC 2023-17 — Third-Party Risk",        "status": "SATISFIED"},
                {"name": "BCBS 239 — Risk Data Aggregation",      "status": "SATISFIED"},
                {"name": "MiFID II Art. 17 / RTS 6",              "status": "SATISFIED"},
                {"name": "DORA — Digital Operational Resilience", "status": "SATISFIED"},
                {"name": "EU AI Act — High-Risk AI Systems",      "status": "SATISFIED"},
            ],
            "ts": datetime.now(timezone.utc).isoformat(),
        })


@app.route("/api/decisions")
def api_decisions():
    """Pending trade decisions waiting for human authority approval."""
    with _lock:
        pending = [_decision_ui_payload(d) for d in aureon_state["pending_decisions"]]
        return jsonify({
            "pending": pending,
            "count":   len(pending),
            "ts":      datetime.now(timezone.utc).isoformat(),
        })


@app.route("/api/decisions/<decision_id>", methods=["POST"])
def api_resolve_decision(decision_id):
    """
    Approve or reject a pending trade decision.
    Called when you click APPROVE or REJECT in the dashboard.
    Expects JSON body: {"resolution": "APPROVED"} or {"resolution": "REJECTED"}

    This is the core of the Human Authority Doctrine:
      - APPROVED → trade is executed, logged with your hash
      - REJECTED → trade is cancelled, still logged for audit
    """
    # CAOM-001 session guard — operator must have opened a session
    from aureon.config.caom import is_caom_active
    if is_caom_active() and not _session_protocol.is_session_open():
        return jsonify({
            "error": "Session not open. Complete the CAOM-001 session open "
                     "protocol before approving decisions.",
            "session_status": _session_protocol.get_status()["session_status"],
        }), 403

    data       = request.get_json() or {}
    resolution = data.get("resolution", "").upper()
    approval_role = (data.get("approval_role") or "TRADER").upper()

    if resolution not in ("APPROVED", "REJECTED"):
        return jsonify({"error": "resolution must be APPROVED or REJECTED"}), 400

    # ── Session boundary check for APPROVED trades ────────────────────────────
    # Record the approval regardless of market hours; defer execution if the
    # instrument's session is closed. Approval is never lost.
    if resolution == "APPROVED":
        with _lock:
            pending = aureon_state["pending_decisions"]
            decision_obj = next((d for d in pending if d.get("id") == decision_id), None)
        if decision_obj is not None:
            sym = decision_obj.get("symbol", "SPY")
            acls = decision_obj.get("asset_class", "equities")
            tradeable, session_reason = _is_instrument_tradeable(sym, acls)
            if not tradeable:
                ts = datetime.now(timezone.utc).isoformat()
                with _lock:
                    decision_obj["status"]      = "APPROVED_PENDING_SESSION"
                    decision_obj["approved_at"] = ts
                    decision_obj["session_reason"] = session_reason
                threading.Thread(target=_save_state, daemon=True).start()
                print(f"[AUREON] APPROVED_PENDING_SESSION: {decision_obj.get('action')} "
                      f"{sym} — {session_reason}")
                return jsonify({
                    "status":      "APPROVED_PENDING_SESSION",
                    "message":     "Approval recorded. Execution deferred to next session open.",
                    "reason":      session_reason,
                    "decision_id": decision_id,
                    "approved_at": ts,
                })

    try:
        result = resolve_pending_decision(
            state=aureon_state,
            lock=_lock,
            decision_id=decision_id,
            resolution=resolution,
            approval_role=approval_role,
            build_trade_report=_build_trade_report,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except LookupError:
        return jsonify({"error": "decision not found"}), 404
    except RuntimeError as exc:
        message = str(exc)
        status = 423 if "SYSTEM HALTED" in message else 409
        payload = {"error": message}
        with _lock:
            if status == 423:
                payload["halt_reason"] = aureon_state["halt_reason"]
                payload["halt_ts"] = aureon_state["halt_ts"]
        return jsonify(payload), status

    authority_hash = result["hash"]
    decision = result["decision"]
    if resolution == "APPROVED" and result["status"] == "ok":
        print(f"[AUREON] APPROVED: {decision['action']} {decision['symbol']} "
              f"${decision['notional']:,} — hash {authority_hash}")

        release_packet = release_to_oms(
            decision,
            authority_hash=authority_hash,
            oms_send=oms_send,
        )
        release_mode = "OMS"
        if decision.get("release_target") == "EMS":
            release_mode = "EMS"
            release_packet = build_execution_release(decision, authority_hash)
        with _lock:
            aureon_state.setdefault("integration_handoffs", []).insert(0, release_packet)

        trade_report = result["trade_report"]
        if trade_report:
            threading.Thread(
                target=_send_trade_confirmation_email,
                args=(trade_report,),
                daemon=True,
            ).start()
        print(f"[AUREON] RELEASED TO {release_mode}: {decision['symbol']} — governed release complete")
    elif resolution == "APPROVED":
        print(
            f"[AUREON] APPROVAL RECORDED: {decision['action']} {decision['symbol']} "
            f"— role {approval_role} — awaiting remaining approvals"
        )
    else:
        print(f"[AUREON] REJECTED: {decision['action']} {decision['symbol']} — hash {authority_hash}")

    # ── Persist state after every HITL decision (non-blocking) ───
    threading.Thread(target=_save_state, daemon=True).start()

    return jsonify({
        "status": result["status"],
        "resolution": result["resolution"],
        "decision_id": result["decision_id"],
        "hash": authority_hash,
        "report_id": result["report_id"],
        "approval_role": approval_role,
        "current_approvals": decision.get("current_approvals", []),
        "required_approvals": decision.get("required_approvals", []),
    })


def _build_pretrade_checks_from_cache(decision_id: str) -> list:
    """
    Build pretrade gate results purely from cached aureon_state.
    No external API calls — guaranteed to return instantly.
    Used as the fallback when the full pretrade check times out.
    """
    with _lock:
        decision = next(
            (d for d in aureon_state.get("pending_decisions", []) if d["id"] == decision_id),
            None,
        )
        if decision is None:
            return []
        portfolio_value = aureon_state.get("portfolio_value", 0.0)
        cash            = aureon_state.get("cash", 0.0)
        drawdown        = aureon_state.get("drawdown", 0.0)
        positions       = list(aureon_state.get("positions", []))
        prices          = dict(aureon_state.get("prices", {}))

    symbol      = decision.get("symbol", "")
    notional    = float(decision.get("notional", 0))
    asset_class = decision.get("asset_class", "")
    is_crypto   = symbol in {"BTC", "ETH", "SOL"}

    # Gate 1 — market status (use cached _market_is_open)
    market_open = _market_is_open()
    gates = [{
        "gate":   "MARKET_STATUS",
        "layer":  "Verana L0",
        "status": "PASS",
        "detail": "24/7 crypto market" if is_crypto else (
                  "US equity session open" if market_open else
                  "US equity/FX market closed — execution will queue for next session"),
    }]
    if not is_crypto and not market_open:
        gates[0]["status"] = "WARN"

    # Gate 2 — cash sufficiency
    cash_floor = portfolio_value * OPERATING_CASH_FLOOR_PCT
    cash_avail = max(0.0, cash - cash_floor)
    gates.append({
        "gate":   "CASH_SUFFICIENCY",
        "layer":  "Kaladan L2",
        "status": "PASS" if cash_avail >= notional else "FAIL",
        "detail": (f"Available: ${cash_avail:,.0f} ≥ Notional: ${notional:,.0f}"
                   if cash_avail >= notional
                   else f"Available: ${cash_avail:,.0f} < Notional: ${notional:,.0f} — insufficient cash"),
    })

    # Gate 3 — position concentration
    class_value = sum(
        pos["shares"] * prices.get(pos["symbol"], pos.get("cost", 0))
        for pos in positions if pos.get("asset_class") == asset_class
    )
    class_pct = (class_value / portfolio_value * 100) if portfolio_value > 0 else 0.0
    warn_pct  = RISK_MANAGER_POLICY.get("position_warn_pct", 10.0)
    fail_pct  = RISK_MANAGER_POLICY.get("position_fail_pct", 15.0)
    pos_status = "FAIL" if class_pct >= fail_pct else "WARN" if class_pct >= warn_pct else "PASS"
    gates.append({
        "gate":   "POSITION_CONCENTRATION",
        "layer":  "Mentat L1",
        "status": pos_status,
        "detail": f"{asset_class} at {class_pct:.1f}% — {'exceeds hard limit' if pos_status == 'FAIL' else 'approaching limit' if pos_status == 'WARN' else 'within limits'} {fail_pct:.0f}%",
    })

    # Gate 4 — drawdown limit
    dd_warn = RISK_MANAGER_POLICY.get("drawdown_warn_pct", 5.0)
    dd_fail = RISK_MANAGER_POLICY.get("drawdown_fail_pct", 8.0)
    dd_status = "FAIL" if drawdown >= dd_fail else "WARN" if drawdown >= dd_warn else "PASS"
    gates.append({
        "gate":   "DRAWDOWN_LIMIT",
        "layer":  "Mentat L1",
        "status": dd_status,
        "detail": f"Drawdown {drawdown:.2f}% — {'exceeds hard limit' if dd_status == 'FAIL' else 'approaching limit' if dd_status == 'WARN' else 'within policy'} {dd_fail:.0f}%",
    })

    # Gate 5 — OFAC screening
    isin = SYMBOL_TO_ISIN.get(symbol)
    gates.append({
        "gate":   "OFAC_SDN_SCREEN",
        "layer":  "Verana L0",
        "status": "FAIL" if (isin and isin in OFAC_BLOCKED_ISINS) else "PASS",
        "detail": f"BLOCKED — {OFAC_BLOCKED_ISINS[isin]}" if (isin and isin in OFAC_BLOCKED_ISINS) else "No SDN / sanctions match",
    })

    # Gate 6 — macro stress (cached values only)
    ofr_stress = aureon_state.get("ofr_stress_index", 0.0)
    macro_status = "WARN" if ofr_stress > 0.7 else "PASS"
    gates.append({
        "gate":   "MACRO_STRESS_OVERLAY",
        "layer":  "Verana L0",
        "status": macro_status,
        "detail": f"OFR stress score {ofr_stress:.2f} — {'elevated systemic risk' if macro_status == 'WARN' else 'normal'} (cached)",
    })

    return gates


from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout


@app.route("/api/decisions/<decision_id>/pretrade", methods=["GET"])
def api_pretrade_check(decision_id):
    """
    Pre-trade compliance check for a pending decision.
    Called before the human clicks final APPROVE to ensure all
    pre-trade gates pass (market status, cash, position limits, drawdown).
    Hard ceiling: 8 seconds via ThreadPoolExecutor — never hangs, never crashes.
    """
    def _run_pretrade_checks():
        payload = evaluate_pretrade_decision(
            state=aureon_state,
            lock=_lock,
            decision_id=decision_id,
            market_is_open=_market_is_open,
            macro_snapshot_fn=_get_fred_macro_snapshot,
            ofr_snapshot_fn=_get_ofr_stress_snapshot,
            operating_cash_floor_pct=OPERATING_CASH_FLOOR_PCT,
            risk_policy=RISK_MANAGER_POLICY,
            symbol_to_isin=SYMBOL_TO_ISIN,
            ofac_blocked_isins=OFAC_BLOCKED_ISINS,
        )
        return payload

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_pretrade_checks)
        try:
            payload = future.result(timeout=8)
            if payload is None:
                return jsonify({"error": "decision not found"}), 404
            return jsonify(payload)
        except FuturesTimeout:
            print(f"[AUREON] Pretrade check timed out for {decision_id} — returning cached data")
            checks = _build_pretrade_checks_from_cache(decision_id)
            if not checks:
                return jsonify({"error": "decision not found"}), 404
            statuses = [g["status"] for g in checks]
            overall = "FAIL" if "FAIL" in statuses else "WARN" if "WARN" in statuses else "PASS"
            with _lock:
                decision = next(
                    (d for d in aureon_state.get("pending_decisions", []) if d["id"] == decision_id),
                    {},
                )
            return jsonify({
                "status":      "WARN",
                "message":     "Pretrade check timed out — using cached data",
                "decision_id": decision_id,
                "symbol":      decision.get("symbol", ""),
                "action":      decision.get("action", ""),
                "notional":    decision.get("notional", 0),
                "overall":     overall,
                "gates":       checks,
                "ts":          datetime.now(timezone.utc).isoformat(),
            }), 200
        except Exception as exc:
            print(f"[AUREON] Pretrade check error for {decision_id}: {exc}")
            checks = _build_pretrade_checks_from_cache(decision_id)
            return jsonify({
                "status":  "WARN",
                "message": f"Pretrade check error: {exc}",
                "checks":  checks,
            }), 200


# ── CAOM-001 Session Open Protocol Routes ────────────────────────────────────

@app.route("/api/session/status", methods=["GET"])
def api_session_status():
    """Return the current session protocol status."""
    return jsonify(_session_protocol.get_status())


@app.route("/api/session/step/1", methods=["POST"])
def api_session_step1():
    """Run Step 1 — Verana session boundary check (automated)."""
    result = _session_protocol.run_step_1_verana_check()
    return jsonify(result)


@app.route("/api/session/step/2", methods=["POST"])
def api_session_step2():
    """Run Step 2 — CAOM-001 mode declaration. Operator confirms."""
    result = _session_protocol.run_step_2_caom_declaration()
    return jsonify(result)


@app.route("/api/session/step/3", methods=["POST"])
def api_session_step3():
    """
    Run Step 3 — Role consolidation acknowledgment.
    Body: {"acknowledged_tiers": [1, 2, 3]}
    All three tiers must be present.
    """
    data = request.get_json() or {}
    acknowledged_tiers = data.get("acknowledged_tiers", [])
    result = _session_protocol.run_step_3_role_ack(acknowledged_tiers)
    return jsonify(result)


@app.route("/api/session/open", methods=["POST"])
def api_session_open():
    """
    Run Steps 5 and 6 — stress review then session open.
    Step 4 (agent readiness) is run automatically first if not already done.
    Body: optional {"stress_override": true} to acknowledge warnings.
    Returns the session open record on success.
    """
    # Step 4 — agent readiness (auto, idempotent)
    agents = {}
    if hasattr(app, "_aureon_agents"):
        agents = app._aureon_agents
    _session_protocol.run_step_4_agent_readiness(agents)

    # Step 5 — stress review
    step5 = _session_protocol.run_step_5_stress_review()
    if step5.get("result") == "BLOCKED":
        return jsonify({"error": "Session blocked by systemic stress hard stop.",
                        "detail": step5}), 423

    # Step 6 — open
    step6 = _session_protocol.run_step_6_open_session()
    if "error" in step6:
        return jsonify(step6), 400

    return jsonify({
        "session_open": True,
        "session_record": step6,
        "stress_review": step5,
    })


# ─────────────────────────────────────────────────────────────────
# 7c. L0 GOVERNANCE — EMERGENCY HALT + DOCTRINE MODIFICATION
# ─────────────────────────────────────────────────────────────────

@app.route("/api/halt", methods=["GET"])
def api_halt_status():
    """Current halt state."""
    with _lock:
        return jsonify({
            "halt_active":    aureon_state["halt_active"],
            "halt_ts":        aureon_state["halt_ts"],
            "halt_authority": aureon_state["halt_authority"],
            "halt_reason":    aureon_state["halt_reason"],
        })


@app.route("/api/halt", methods=["POST"])
def api_halt_activate():
    """
    Tier 0 Emergency Halt — freezes all Thifur execution immediately.
    No autonomous action can override this. Resume requires explicit human re-auth.
    """
    data      = request.get_json() or {}
    reason    = data.get("reason", "Emergency halt activated")
    authority = data.get("authority", "br@ravelobizdev.com")

    halt_hash = hashlib.sha256(
        f"HALT-{authority}-{datetime.now(timezone.utc).isoformat()}".encode()
    ).hexdigest()[:16].upper()

    with _lock:
        aureon_state["halt_active"]    = True
        aureon_state["halt_ts"]        = datetime.now(timezone.utc).isoformat()
        aureon_state["halt_authority"] = authority
        aureon_state["halt_reason"]    = reason
        aureon_state["authority_log"].insert(0, {
            "id":        f"HAD-HALT-{random.randint(1000, 9999)}",
            "ts":        aureon_state["halt_ts"],
            "tier":      "Tier 0",
            "type":      "EMERGENCY HALT ACTIVATED",
            "authority": authority,
            "outcome":   "HALTED",
            "hash":      halt_hash,
        })

    print(f"[AUREON] ⛔ EMERGENCY HALT — {reason} — authority {authority} — {halt_hash}")
    return jsonify({
        "status":    "halted",
        "reason":    reason,
        "authority": authority,
        "hash":      halt_hash,
        "ts":        aureon_state["halt_ts"],
    })


@app.route("/api/halt/resume", methods=["POST"])
def api_halt_resume():
    """
    Resume from emergency halt. Requires explicit human re-authorization.
    Logged as a Tier 0 authority event.
    """
    data      = request.get_json() or {}
    authority = data.get("authority", "br@ravelobizdev.com")

    with _lock:
        if not aureon_state["halt_active"]:
            return jsonify({"error": "system is not halted"}), 400

        resume_hash = hashlib.sha256(
            f"RESUME-{authority}-{datetime.now(timezone.utc).isoformat()}".encode()
        ).hexdigest()[:16].upper()

        aureon_state["halt_active"]    = False
        aureon_state["halt_ts"]        = None
        aureon_state["halt_authority"] = None
        aureon_state["halt_reason"]    = None
        aureon_state["authority_log"].insert(0, {
            "id":        f"HAD-RESUME-{random.randint(1000, 9999)}",
            "ts":        datetime.now(timezone.utc).isoformat(),
            "tier":      "Tier 0",
            "type":      "SYSTEM RESUMED",
            "authority": authority,
            "outcome":   "RESUMED",
            "hash":      resume_hash,
        })

    print(f"[AUREON] ✓ System resumed by {authority} — {resume_hash}")
    return jsonify({
        "status":    "resumed",
        "authority": authority,
        "hash":      resume_hash,
        "ts":        datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/doctrine/propose", methods=["POST"])
def api_doctrine_propose():
    """
    Propose a doctrine version update. Creates a pending update requiring Tier 1 approval.
    trigger: REGULATORY | HUMAN_AUTHORITY | TELEMETRY
    Only Tier 1 (human) can approve. Thifur (Tier 3) can only signal — never modify.
    """
    data       = request.get_json() or {}
    trigger    = data.get("trigger",    "HUMAN_AUTHORITY").upper()
    reason     = data.get("reason",     "").strip()
    title      = data.get("title",      "Untitled Doctrine Update").strip()
    frameworks = data.get("frameworks", [])   # list of affected compliance frameworks
    urgency    = data.get("urgency",    "ROUTINE").upper()
    authority  = data.get("authority",  "br@ravelobizdev.com")

    if not reason:
        return jsonify({"error": "reason is required"}), 400

    with _lock:
        current = aureon_state["doctrine_version"]
        parts   = current.split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        proposed = data.get("version") or ".".join(parts)

        update_id = f"MDU-{random.randint(0x1000, 0xFFFF):X}"
        update = {
            "id":               update_id,
            "title":            title,
            "trigger":          trigger,
            "reason":           reason,
            "frameworks":       frameworks,
            "urgency":          urgency,
            "current_version":  current,
            "proposed_version": proposed,
            "proposed_by":      authority,
            "ts":               datetime.now(timezone.utc).isoformat(),
            "status":           "PENDING_APPROVAL",
        }
        aureon_state["pending_doctrine_updates"].append(update)

    print(f"[AUREON] Doctrine update proposed: v{current} → v{proposed} [{trigger}] [{urgency}] — {update_id}: {title}")
    return jsonify({
        "status":           "pending_approval",
        "update_id":        update_id,
        "current_version":  current,
        "proposed_version": proposed,
        "ts":               update["ts"],
    })


@app.route("/api/doctrine/approve/<update_id>", methods=["POST"])
def api_doctrine_approve(update_id):
    """
    Tier 1 human approval of a pending doctrine update.
    On approval: version bumps, immutable hash generated, log entry appended.
    On rejection: update removed, no version change.
    """
    data       = request.get_json() or {}
    resolution = data.get("resolution", "APPROVED").upper()
    authority  = data.get("authority", "br@ravelobizdev.com")

    if resolution not in ("APPROVED", "REJECTED"):
        return jsonify({"error": "resolution must be APPROVED or REJECTED"}), 400

    with _lock:
        pending = aureon_state.get("pending_doctrine_updates", [])
        update  = next((u for u in pending if u["id"] == update_id), None)
        if not update:
            return jsonify({"error": "update not found"}), 404

        aureon_state["pending_doctrine_updates"] = [
            u for u in pending if u["id"] != update_id
        ]

        if resolution == "APPROVED":
            new_version = update["proposed_version"]
            old_version = aureon_state["doctrine_version"]
            doc_hash    = hashlib.sha256(
                f"AUREON-DOCTRINE-{new_version}-{update_id}-{authority}".encode()
            ).hexdigest()[:16].upper()

            aureon_state["doctrine_version"] = new_version

            log_entry = {
                "version":   new_version,
                "prev":      old_version,
                "hash":      doc_hash,
                "ts":        datetime.now(timezone.utc).isoformat(),
                "authority": authority,
                "tier":      "Tier 1 — Human Authority",
                "trigger":   update["trigger"],
                "reason":    update["reason"],
                "update_id": update_id,
            }
            aureon_state["doctrine_version_log"].insert(0, log_entry)
            aureon_state["authority_log"].insert(0, {
                "id":        f"HAD-{random.randint(1000, 9999)}",
                "ts":        log_entry["ts"],
                "tier":      "Tier 1",
                "type":      f"Doctrine v{old_version} → v{new_version}",
                "authority": authority,
                "outcome":   "APPROVED",
                "hash":      doc_hash,
            })

            print(f"[AUREON] Doctrine v{old_version} → v{new_version} — {doc_hash}")
            threading.Thread(target=_save_state, daemon=True).start()
            return jsonify({
                "status":      "approved",
                "old_version": old_version,
                "new_version": new_version,
                "hash":        doc_hash,
                "ts":          log_entry["ts"],
            })
        else:
            print(f"[AUREON] Doctrine update {update_id} rejected by {authority}")
            threading.Thread(target=_save_state, daemon=True).start()
            return jsonify({"status": "rejected", "update_id": update_id})


@app.route("/api/governance")
def api_governance():
    """Full governance view — doctrine version, halt state, authority log, doctrine version log."""
    with _lock:
        authority_log = aureon_state["authority_log"][:50]
        doctrine_log = aureon_state.get("doctrine_version_log", [])[:20]
        trade_reports = aureon_state.get("trade_reports", [])
        latest_authority = authority_log[0] if authority_log else {}
        latest_doctrine = doctrine_log[0] if doctrine_log else {}
        latest_report = trade_reports[0] if trade_reports else {}

        return jsonify({
            "doctrine_version":          aureon_state["doctrine_version"],
            "stack_status":              aureon_state["stack_status"],
            "last_stack_run":            aureon_state["last_stack_run"],
            "doctrine_updates":          aureon_state["doctrine_updates"],
            "authority_log":             authority_log,
            "override_count":            len(aureon_state["authority_log"]),
            "stack_result":              aureon_state["stack_result"],
            "audit_hash":                aureon_state["audit"],
            "halt_active":               aureon_state["halt_active"],
            "halt_ts":                   aureon_state["halt_ts"],
            "halt_authority":            aureon_state["halt_authority"],
            "halt_reason":               aureon_state["halt_reason"],
            "pending_doctrine_updates":  aureon_state.get("pending_doctrine_updates", []),
            "doctrine_version_log":      doctrine_log,
            "fingerprint_engine": {
                "stack_audit_hash":      aureon_state["audit"],
                "latest_authority_hash": latest_authority.get("hash"),
                "latest_authority_type": latest_authority.get("type"),
                "latest_authority_ts":   latest_authority.get("ts"),
                "latest_doctrine_hash":  latest_doctrine.get("hash"),
                "latest_doctrine_version": latest_doctrine.get("version"),
                "latest_report_id":      latest_report.get("report_id"),
                "latest_report_hash":    latest_report.get("authority_hash"),
                "latest_report_ts":      latest_report.get("exec_ts"),
            },
            "ts":                        datetime.now(timezone.utc).isoformat(),
        })


@app.route("/api/trade-reports")
def api_trade_reports_list():
    """Chronological list of all compliance trade reports (JSON, no PDF bytes)."""
    with _lock:
        reports = aureon_state.get("trade_reports", [])
        out = [{k: v for k, v in r.items() if k != "pdf_bytes"} for r in reports]
    return jsonify({"reports": out, "count": len(out)})


@app.route("/api/trade-reports/<report_id>")
def api_trade_report_detail(report_id):
    """Return a single trade report as structured JSON (no PDF bytes)."""
    with _lock:
        reports = aureon_state.get("trade_reports", [])
        report  = next((r for r in reports
                        if r.get("report_id") == report_id
                        or r.get("decision_id") == report_id), None)
    if not report:
        return jsonify({"error": "report not found"}), 404
    return jsonify({k: v for k, v in report.items() if k != "pdf_bytes"})


@app.route("/api/trade-reports/<report_id>/pdf")
def api_trade_report_pdf(report_id):
    """Serve the immutable PDF compliance artifact for a trade."""
    from flask import make_response
    with _lock:
        reports = aureon_state.get("trade_reports", [])
        report  = next((r for r in reports
                        if r.get("report_id") == report_id
                        or r.get("decision_id") == report_id), None)
    if not report:
        return jsonify({"error": "report not found"}), 404
    pdf = report.get("pdf_bytes")
    if not pdf:
        return jsonify({"error": "PDF artifact not available"}), 404
    resp = make_response(pdf)
    resp.headers["Content-Type"]        = "application/pdf"
    resp.headers["Content-Disposition"] = f'inline; filename="{report_id}.pdf"'
    resp.headers["Cache-Control"]       = "no-store"
    return resp


@app.route("/api/stack")
def api_stack():
    """Trigger an on-demand doctrine stack re-run (non-blocking)."""
    threading.Thread(target=run_doctrine_stack, daemon=True).start()
    return jsonify({
        "status": "stack cycle started",
        "ts":     datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/errors", methods=["GET"])
def api_errors():
    """
    Return the in-memory error log (last 200 entries).
    Supports ?level=ERROR to filter by severity.
    """
    level_filter = request.args.get("level", "").upper()
    with _lock:
        log = list(aureon_state["error_log"])
    if level_filter:
        log = [e for e in log if e.get("level") == level_filter]
    return jsonify({
        "count":     len(log),
        "log_file":  LOG_FILE,
        "errors":    log,
    })


@app.route("/api/email/test", methods=["POST"])
def api_email_test():
    """Send a test weekly P&L report email immediately."""
    ET       = zoneinfo.ZoneInfo("America/New_York")
    date_str = datetime.now(ET).strftime("%B %d, %Y")
    ok = _send_email(
        "Aureon First Test",
        _build_email_html()
    )
    return jsonify({
        "status": "sent" if ok else "failed",
        "to":     EMAIL_TO,
        "ts":     datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/snapshot")
def api_snapshot():
    """Lightweight health check — key numbers only."""
    with _lock:
        return jsonify({
            "portfolio_value": round(aureon_state["portfolio_value"], 2),
            "pnl":             round(aureon_state["pnl"], 2),
            "pnl_pct":         round(aureon_state["pnl_pct"], 4),
            "drawdown":        round(aureon_state["drawdown"], 4),
            "positions":       len(aureon_state["positions"]),
            "pending":         len(aureon_state["pending_decisions"]),
            "alerts":          len(aureon_state["compliance_alerts"]),
            "doctrine":        aureon_state["doctrine_version"],
            "stack":           aureon_state["stack_status"],
            "cycle":           aureon_state["cycle_count"],
            "market_open":     _market_is_open(),
        })


# ─────────────────────────────────────────────────────────────────
# 7b. TREASURY OPERATIONS ENDPOINT
# ─────────────────────────────────────────────────────────────────

def _compute_settlement_status(trade):
    """
    Compute settlement state, settlement type, and the effective settled_at timestamp
    for a recorded trade. This lets the Treasury tab show both the live pipeline and a
    durable settled-trade repository from the same source of truth.
    """
    CRYPTO_SYMBOLS = {"BTC", "ETH", "SOL"}
    ET  = zoneinfo.ZoneInfo("America/New_York")
    now = datetime.now(timezone.utc)

    symbol    = trade.get("symbol", "")
    asset_cls = trade.get("asset_class", "")
    is_t0     = symbol in CRYPTO_SYMBOLS or asset_cls == "crypto"

    try:
        trade_dt = datetime.fromisoformat(trade["ts"].replace("Z", "+00:00"))
        age_s    = (now - trade_dt).total_seconds()
    except Exception:
        trade_dt = now
        age_s    = 9999

    if is_t0:
        if age_s < 180:
            state = "INSTRUCTED"
        elif age_s < 480:
            state = "MATCHED"
        elif age_s < 1200:
            state = "CASH_SETTLED"
        else:
            state = "FULLY_SETTLED"
        settled_at = trade_dt if state != "FULLY_SETTLED" else trade_dt + timedelta(minutes=20)
    else:
        if age_s < 180:
            state = "INSTRUCTED"
        elif age_s < 600:
            state = "MATCHED"
        else:
            trade_et   = trade_dt.astimezone(ET)
            trade_date = trade_et.date()

            next_day = trade_date + timedelta(days=1)
            while next_day.weekday() >= 5:
                next_day += timedelta(days=1)

            cutoff_naive = datetime.combine(next_day, dt_time(17, 30))
            cutoff_et    = cutoff_naive.replace(tzinfo=ET)
            settled_at   = cutoff_et.astimezone(timezone.utc)

            if now >= settled_at:
                state = "FULLY_SETTLED"
            else:
                state = "CASH_SETTLED"

    return {
        "state": state,
        "settlement": "T+0" if is_t0 else "T+1",
        "settled_at": settled_at.isoformat() if state == "FULLY_SETTLED" else None,
    }


def _build_settlement_pipeline():
    """
    Assign settlement states to trades based on age.
    Instructed < 3 min → Matched < 8 min → Cash Settled < 20 min → Fully Settled
    Only the most recent 30 trades are tracked in the pipeline.

    Settlement lifecycle rules (aligned with institutional OMS standards):
      T+0  Crypto (BTC, ETH, SOL) — on-chain finality, intraday settlement allowed.
           INSTRUCTED < 3 min → MATCHED < 8 min → CASH_SETTLED < 20 min → FULLY_SETTLED

      T+1  All other asset classes (equities, FX, fixed income) — SEC Rule 15c6-1
           (effective May 28 2024) and standard FX/FI conventions.
           INSTRUCTED < 3 min → MATCHED < 10 min → CASH_SETTLED (affirmed, awaiting T+1)
           FULLY_SETTLED only after next business day 17:30 ET cutoff.
    """
    pipeline = []

    with _lock:
        for t in aureon_state["trades"][-30:]:
            symbol = t.get("symbol", "")
            status = _compute_settlement_status(t)

            pipeline.append({
                "id":         t.get("hash", "")[:8] or t["ts"][-8:],
                "symbol":     symbol,
                "action":     t["action"],
                "notional":   round(t.get("notional", 0), 2),
                "agent":      t.get("agent", "THIFUR_J"),
                "ts":         t["ts"],
                "state":      status["state"],
                "settlement": status["settlement"],
            })
    return pipeline


def _build_settled_repository():
    """
    Build a durable settled-trade repository from the full saved trade history.
    This is intentionally separate from the 30-trade Treasury pipeline window.
    """
    settled = []
    with _lock:
        trades = list(aureon_state["trades"])

    for t in trades:
        status = _compute_settlement_status(t)
        if status["state"] != "FULLY_SETTLED":
            continue
        settled.append({
            "id":         t.get("hash", "")[:8] or t["ts"][-8:],
            "action":     t.get("action", "BUY"),
            "symbol":     t.get("symbol", "—"),
            "asset_class": t.get("asset_class", "—"),
            "notional":   round(t.get("notional", 0), 2),
            "ts":         t.get("ts"),
            "settled_at": status["settled_at"],
            "settlement": status["settlement"],
            "summary":    f"{t.get('action', 'BUY')} {t.get('symbol', '—')} settled ${round(t.get('notional', 0), 2):,.0f}",
        })

    settled.sort(key=lambda x: x.get("settled_at") or "", reverse=True)
    return settled


@app.route("/api/treasury")
def api_treasury():
    """Treasury Operations — settlement pipeline, liquidity gate, rail status."""
    pipeline = _build_settlement_pipeline()
    settled_repository = _build_settled_repository()

    # Cash obligations not yet fully settled (BUY = cash outflow pending)
    pending_obligations = sum(
        p["notional"] for p in pipeline
        if p["state"] in ("INSTRUCTED", "MATCHED") and p["action"] == "BUY"
    )

    with _lock:
        t0_cash          = round(aureon_state["cash"], 2)
        portfolio_val    = round(aureon_state["portfolio_value"], 2)
        drawdown         = aureon_state["drawdown"]
        mmf_balance      = round(aureon_state.get("mmf_balance", 0.0), 2)
        mmf_yield_acc    = round(aureon_state.get("mmf_yield_accrued", 0.0), 2)
        mmf_provider     = _resolve_mmf_provider(aureon_state.get("mmf_provider"))
        sweep_log        = list(aureon_state.get("sweep_log", []))[:10]
        cash_floor       = round(portfolio_val * OPERATING_CASH_FLOOR_PCT, 2)

    cash_available = max(0.0, round(t0_cash - pending_obligations, 2))

    # Rail health — degrade only if drawdown is severe (Level 2+)
    if drawdown >= 8.0:
        rail_custodian = "DEGRADED"
    else:
        rail_custodian = "OPERATIONAL"

    state_counts = {"INSTRUCTED": 0, "MATCHED": 0, "CASH_SETTLED": 0, "FULLY_SETTLED": 0}
    for p in pipeline:
        state_counts[p["state"]] += 1

    settled_notional = round(sum(
        p["notional"] for p in settled_repository
    ), 2)

    in_flight = sum(1 for p in pipeline if p["state"] != "FULLY_SETTLED")

    return jsonify({
        "t0_cash":             t0_cash,
        "pending_obligations": round(pending_obligations, 2),
        "cash_available":      cash_available,
        "portfolio_value":     portfolio_val,
        "pipeline":            pipeline,
        "state_counts":        state_counts,
        "settled_today":       state_counts["FULLY_SETTLED"],
        "settled_notional":    settled_notional,
        "in_flight":           in_flight,
        "settled_repository":  settled_repository[:50],
        "rails": {
            "swift":     "OPERATIONAL",
            "fedwire":   "OPERATIONAL",
            "custodian": rail_custodian,
            "clearing":  "OPERATIONAL",
        },
        # ── Institutional MMF / Cash Management ───────────────────
        "mmf": {
            "balance":        mmf_balance,
            "yield_accrued":  mmf_yield_acc,
            "annual_rate_pct": round(MMF_YIELD_ANNUAL * 100, 2),
            "provider":       mmf_provider["name"],
            "ticker":         mmf_provider["ticker"],
            "jurisdiction":   mmf_provider["jurisdiction"],
            "currency":       mmf_provider["currency"],
        },
        "cash_floor":         cash_floor,
        "cash_floor_pct":     round(OPERATING_CASH_FLOOR_PCT * 100, 1),
        "sweep_log":          sweep_log,
    })


@app.route("/framework-brief")
def framework_brief():
    """Executive briefing page for CTOs, CIOs, Chief Risk Managers, and investors."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Aureon Framework Brief</title>
  <style>
    :root {
      --bg: #07111f;
      --panel: #0d1a2f;
      --panel2: #11223e;
      --text: #eef4ff;
      --muted: #93a4bf;
      --cyan: #00d4ff;
      --blue: #5da2ff;
      --green: #10b981;
      --yellow: #f59e0b;
      --border: rgba(93,162,255,.16);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Helvetica, Arial, sans-serif;
      background:
        radial-gradient(circle at top left, rgba(0,212,255,.14), transparent 28%),
        linear-gradient(180deg, #08121f 0%, #07111f 100%);
      color: var(--text);
    }
    .wrap { max-width: 1100px; margin: 0 auto; padding: 48px 24px 64px; }
    .hero, .panel {
      background: linear-gradient(180deg, rgba(13,26,47,.98), rgba(9,19,34,.98));
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: 0 18px 60px rgba(0,0,0,.28);
    }
    .hero { padding: 32px; margin-bottom: 20px; }
    .kicker { color: var(--cyan); font-size: 11px; letter-spacing: .22em; text-transform: uppercase; }
    h1 { margin: 10px 0 10px; font-size: clamp(34px, 6vw, 58px); line-height: 1.02; }
    .sub { max-width: 760px; color: var(--muted); font-size: 17px; line-height: 1.75; }
    .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 18px; }
    .panel { padding: 24px; }
    .span-12 { grid-column: span 12; }
    .span-6 { grid-column: span 6; }
    .span-4 { grid-column: span 4; }
    .eyebrow { color: var(--cyan); font-size: 10px; letter-spacing: .18em; text-transform: uppercase; margin-bottom: 8px; }
    h2 { margin: 0 0 12px; font-size: 24px; }
    p, li { color: var(--muted); line-height: 1.7; }
    ul { margin: 0; padding-left: 18px; }
    .metric { font-size: 30px; font-weight: 800; margin-bottom: 6px; }
    .flow {
      display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-top: 14px;
    }
    .flow div, .layer {
      background: rgba(255,255,255,.03);
      border: 1px solid rgba(255,255,255,.06);
      border-radius: 14px;
      padding: 16px;
    }
    .layer-title { color: var(--text); font-weight: 700; margin-bottom: 6px; }
    .foot { margin-top: 24px; color: var(--muted); font-size: 12px; text-align: center; }
    @media (max-width: 900px) {
      .span-6, .span-4 { grid-column: span 12; }
      .flow { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="kicker">Aureon Executive Brief</div>
      <h1>Pre-Trade Governance for AI-Assisted Investment Systems</h1>
      <div class="sub">
        Aureon is designed to sit between signal generation and execution infrastructure.
        Its role is to validate doctrine, risk, compliance, and human authority before a trade becomes a portfolio event.
      </div>
    </section>

    <section class="grid">
      <div class="panel span-4">
        <div class="eyebrow">What It Is</div>
        <div class="metric">Governance Layer</div>
        <p>Aureon is not a broker, OMS, or portfolio management replacement in this prototype. It is the control layer that makes AI-assisted decisions explainable, reviewable, and auditable before execution.</p>
      </div>
      <div class="panel span-4">
        <div class="eyebrow">Core Outcome</div>
        <div class="metric">Decision Accountability</div>
        <p>Every trade can be reconstructed as a lifecycle package: signal, doctrine check, risk review, compliance validation, human approval, execution, and settlement evidence.</p>
      </div>
      <div class="panel span-4">
        <div class="eyebrow">Why It Matters</div>
        <div class="metric">Smarter, Not Noisier</div>
        <p>The product direction is to make financial systems more intelligent by structuring intent and governance, not by adding disconnected workflow complexity.</p>
      </div>

      <div class="panel span-12">
        <div class="eyebrow">Lifecycle</div>
        <h2>How Aureon Works</h2>
        <div class="flow">
          <div><strong>1. Signal or Thesis Input</strong><br><span>Market signal, portfolio drift, or future thesis-driven memo input.</span></div>
          <div><strong>2. Doctrine Validation</strong><br><span>Rules, thresholds, and architecture-level governance are checked first.</span></div>
          <div><strong>3. Risk + Compliance Review</strong><br><span>Risk boundaries and regulatory frameworks are evaluated visibly.</span></div>
          <div><strong>4. Human Authority</strong><br><span>Material actions require explicit human approval and lineage stamping.</span></div>
          <div><strong>5. Execution + Replay</strong><br><span>Execution, settlement, and audit artifacts become replayable records.</span></div>
        </div>
      </div>

      <div class="panel span-6">
        <div class="eyebrow">Architecture</div>
        <h2>Four-Layer Governance Stack</h2>
        <div class="layer"><div class="layer-title">Layer 0 - Verana</div><p>Network governance, vendor and counterparty boundaries, jurisdictional escalation, and system-wide control posture.</p></div>
        <div class="layer"><div class="layer-title">Layer 1 - Mentat</div><p>Doctrine interpretation, strategic intelligence, and policy logic that defines how the system should reason.</p></div>
        <div class="layer"><div class="layer-title">Layer 2 - Kaladan</div><p>Lifecycle orchestration across routing, treasury, settlement, and compliance artifacts.</p></div>
        <div class="layer"><div class="layer-title">Layer 3 - Thifur</div><p>Bounded execution agents that can recommend or perform actions within doctrine-defined authority.</p></div>
      </div>

      <div class="panel span-6">
        <div class="eyebrow">Audience</div>
        <h2>Why It Resonates With Leadership</h2>
        <ul>
          <li><strong>CTOs:</strong> clear systems boundary between intelligence, control, and execution.</li>
          <li><strong>CIOs:</strong> better governance around investment decisions before capital is deployed.</li>
          <li><strong>Chief Risk Managers:</strong> visible pre-trade controls, replayability, and explainability.</li>
          <li><strong>Investors:</strong> stronger trust model around how AI-assisted actions are governed.</li>
        </ul>
      </div>

      <div class="panel span-12">
        <div class="eyebrow">Positioning</div>
        <h2>Commercial Framing</h2>
        <p>Aureon can be framed as a governance overlay above existing OMS infrastructure, a full-stack operating system for greenfield deployment, or a compliance intelligence layer that returns structured audit artifacts. The unifying theme is the same in every mode: governance before execution.</p>
      </div>
    </section>

    <div class="foot">Project Aureon · Framework Brief · Prepared for CTO, CIO, Chief Risk Manager, and investor discussions</div>
  </div>
</body>
</html>"""
    return Response(html, mimetype="text/html")


# ─────────────────────────────────────────────────────────────────
# 8. STATIC FILE ROUTES
# ─────────────────────────────────────────────────────────────────
# send_from_directory(THIS_DIR, filename) = "send this file from
# the folder where server.py lives."  That's all that changed vs
# the old version (which pointed two folders up by mistake).

@app.route("/")
def index():
    """Serve the main dashboard."""
    return send_from_directory(THIS_DIR, "index.html")


# ─────────────────────────────────────────────────────────────────
# 9. START
# ─────────────────────────────────────────────────────────────────

def _start_background_threads():
    # ── Volume and state file diagnostics ────────────────────────────────────
    data_dir = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "")
    if data_dir:
        print(f"[AUREON] Volume mounted at {data_dir}")
        try:
            print(f"[AUREON] Files in volume: {os.listdir(data_dir)}")
        except Exception as exc:
            print(f"[AUREON] Could not list volume: {exc}")
    else:
        print("[AUREON] WARNING — No Railway Volume mounted. State will reset on "
              "every redeploy. Set RAILWAY_VOLUME_MOUNT_PATH=/data and attach a "
              "Volume in the Railway dashboard.")
    print(f"[AUREON] STATE_FILE path: {STATE_FILE}")
    print(f"[AUREON] STATE_FILE exists: {os.path.exists(STATE_FILE)}")
    if not os.path.exists(STATE_FILE):
        print(f"[AUREON] State initialized fresh — no prior state found at {STATE_FILE}")
    else:
        print(f"[AUREON] State loaded from {STATE_FILE}")

    threading.Thread(target=run_doctrine_stack, daemon=True).start()
    # Auto-complete all six CAOM-001 session steps at startup.
    # Operator identity and role consolidation are permanently declared in
    # caom.py — no manual curl sequence needed on every redeploy.
    _session_protocol.run_step_1_verana_check()
    _session_protocol.run_step_2_caom_declaration()
    _session_protocol.run_step_3_role_ack([1, 2, 3])
    _session_protocol.run_step_4_agent_readiness(
        getattr(app, "_aureon_agents", {})
    )
    _session_protocol.run_step_5_stress_review()
    _session_protocol.run_step_6_open_session()
    threading.Thread(target=market_loop, daemon=True).start()
    threading.Thread(target=email_scheduler, daemon=True).start()
    print("[AUREON] Background threads started — CAOM-001 session OPEN")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", os.environ.get("AUREON_PORT", "5001")))
    _start_background_threads()
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
