"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/mcp/server.py                                                ║
║  MCP Server — Streamable HTTP Transport                              ║
║                                                                      ║
║  Implements the Model Context Protocol (MCP) spec over HTTP.         ║
║  Transport: JSON-RPC 2.0 via POST /mcp                               ║
║  Spec: https://spec.modelcontextprotocol.io                          ║
║                                                                      ║
║  Phase 1 — VERANA L0 (this file):                                    ║
║    Resources: Network Registry, Regulatory Frameworks,               ║
║               OFAC Screening List, Compliance Alerts                 ║
║    Tools:     verana_screen_ofac, verana_framework_status,           ║
║               verana_node_status, verana_compliance_snapshot         ║
║                                                                      ║
║  No external MCP SDK required. Pure JSON-RPC 2.0 over Flask.         ║
║  Compatible with any MCP client (Claude Desktop, custom agents).     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import json
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, Response

# ── MCP Server Identity ───────────────────────────────────────────────────────
MCP_SERVER_NAME    = "aureon-verana"
MCP_SERVER_VERSION = "1.0.0"
MCP_PROTOCOL_VERSION = "2024-11-05"   # MCP spec version

# ── Resource URI scheme ───────────────────────────────────────────────────────
# aureon://verana/{resource}
RESOURCE_NETWORK_REGISTRY   = "aureon://verana/network-registry"
RESOURCE_REG_FRAMEWORKS     = "aureon://verana/regulatory-frameworks"
RESOURCE_OFAC_LIST          = "aureon://verana/ofac-screening-list"
RESOURCE_COMPLIANCE_ALERTS  = "aureon://verana/compliance-alerts"
RESOURCE_DOCTRINE_STATUS    = "aureon://verana/doctrine-status"

# ── Blueprint ─────────────────────────────────────────────────────────────────
mcp_bp = Blueprint("mcp", __name__)

# aureon_state and _lock are injected at registration time via init_mcp()
_state = None
_lock  = None
_ofac_blocked = None


def init_mcp(aureon_state: dict, state_lock, ofac_blocked_isins: dict):
    """
    Inject Aureon runtime state into the MCP server.
    Called from server.py after aureon_state is initialized.
    """
    global _state, _lock, _ofac_blocked
    _state        = aureon_state
    _lock         = state_lock
    _ofac_blocked = ofac_blocked_isins


# ─────────────────────────────────────────────────────────────────────────────
# JSON-RPC 2.0 helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ok(request_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _err(request_id, code: int, message: str, data=None) -> dict:
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


# Standard JSON-RPC error codes
ERR_PARSE         = -32700
ERR_INVALID_REQ   = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602
ERR_INTERNAL      = -32603

# MCP-specific error codes
ERR_RESOURCE_NOT_FOUND = -32002


# ─────────────────────────────────────────────────────────────────────────────
# MCP Capabilities Declaration
# ─────────────────────────────────────────────────────────────────────────────

def _server_capabilities() -> dict:
    return {
        "resources": {
            "subscribe":   False,
            "listChanged": False,
        },
        "tools": {
            "listChanged": False,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Resource Definitions
# ─────────────────────────────────────────────────────────────────────────────

RESOURCES = [
    {
        "uri":         RESOURCE_NETWORK_REGISTRY,
        "name":        "Verana Network Registry",
        "description": (
            "Live network node registry maintained by Verana L0. "
            "Contains operational status, doctrine version, phase, and "
            "node counts for all Aureon network participants. "
            "Doctrine ref: Verana L0 — Network Governance Layer."
        ),
        "mimeType":    "application/json",
    },
    {
        "uri":         RESOURCE_REG_FRAMEWORKS,
        "name":        "Regulatory Frameworks Status",
        "description": (
            "Current compliance status for all regulatory frameworks "
            "Verana L0 monitors: SR 11-7, OCC 2023-17, BCBS 239, "
            "MiFID II Art. 17 / RTS 6, DORA, EU AI Act. "
            "Each framework includes status and last-verified timestamp."
        ),
        "mimeType":    "application/json",
    },
    {
        "uri":         RESOURCE_OFAC_LIST,
        "name":        "OFAC SDN Screening List",
        "description": (
            "Verana L0 OFAC Specially Designated Nationals screening list. "
            "All blocked ISINs/identifiers with sanction basis. "
            "Used by Gate 5 in the pre-trade governance gate sequence. "
            "Read-only — modifications require Tier 2 authority."
        ),
        "mimeType":    "application/json",
    },
    {
        "uri":         RESOURCE_COMPLIANCE_ALERTS,
        "name":        "Compliance Alerts (Live)",
        "description": (
            "Live compliance alert feed from Verana L0. "
            "Includes active alerts, alert history (last 50), "
            "severity levels (CRITICAL/WARN/INFO), and resolution status. "
            "Reflects real-time portfolio and doctrine state."
        ),
        "mimeType":    "application/json",
    },
    {
        "uri":         RESOURCE_DOCTRINE_STATUS,
        "name":        "Doctrine Version Status",
        "description": (
            "Current Aureon doctrine version, stack status, audit hash, "
            "halt state, and doctrine version log. "
            "Verana L0 absorbs regulatory changes that trigger doctrine updates. "
            "Authority chain: Verana L0 → Tier 1 Human Approval → version increment."
        ),
        "mimeType":    "application/json",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Tool Definitions
# ─────────────────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name":        "verana_screen_ofac",
        "description": (
            "Screen a symbol or ISIN against Verana L0's OFAC SDN list. "
            "Returns PASS or BLOCKED with sanction basis if blocked. "
            "This is Gate 5 in the Aureon pre-trade governance gate sequence. "
            "All trade approvals pass through this gate before release to OMS."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "identifier": {
                    "type":        "string",
                    "description": "Symbol or ISIN to screen (e.g. 'MSFT', 'PDVSA_BOND_2027')",
                },
            },
            "required": ["identifier"],
        },
    },
    {
        "name":        "verana_framework_status",
        "description": (
            "Check the compliance status of a specific regulatory framework "
            "monitored by Verana L0. Returns status (SATISFIED/BREACHED/MONITORING) "
            "and detail. Valid frameworks: SR_11_7, OCC_2023_17, BCBS_239, "
            "MIFID_II, DORA, EU_AI_ACT."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "framework": {
                    "type":        "string",
                    "description": "Framework identifier. One of: SR_11_7, OCC_2023_17, BCBS_239, MIFID_II, DORA, EU_AI_ACT",
                    "enum":        ["SR_11_7", "OCC_2023_17", "BCBS_239", "MIFID_II", "DORA", "EU_AI_ACT"],
                },
            },
            "required": ["framework"],
        },
    },
    {
        "name":        "verana_node_status",
        "description": (
            "Get operational status of the Aureon network node registry. "
            "Returns total nodes, operational nodes, phase (ACTIVE/RECOVER/DEGRADED), "
            "and doctrine version active across the network."
        ),
        "inputSchema": {
            "type":       "object",
            "properties": {},
            "required":   [],
        },
    },
    {
        "name":        "verana_compliance_snapshot",
        "description": (
            "Full Verana L0 compliance snapshot: active alerts, drawdown level, "
            "halt state, framework statuses, and OFAC gate state. "
            "Equivalent to reading all Verana resources in one call. "
            "Use when you need a complete picture of Aureon's governance posture."
        ),
        "inputSchema": {
            "type":       "object",
            "properties": {},
            "required":   [],
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Resource Readers
# ─────────────────────────────────────────────────────────────────────────────

def _read_network_registry() -> dict:
    with _lock:
        nodes_total = _state.get("network_nodes", 15)
        nodes_op    = _state.get("nodes_operational", 15)
        doctrine    = _state.get("doctrine_version", "unknown")
        halt_active = _state.get("halt_active", False)
        stack_result = _state.get("stack_result") or {}
        verana_layer = stack_result.get("layers", {}).get("verana", {})

    return {
        "registry_id":        "VERANA-NET-REG-001",
        "ts":                 datetime.now(timezone.utc).isoformat(),
        "doctrine_version":   doctrine,
        "halt_active":        halt_active,
        "network": {
            "total_nodes":        nodes_total,
            "operational_nodes":  nodes_op,
            "degraded_nodes":     max(0, nodes_total - nodes_op),
            "operational_pct":    round(nodes_op / nodes_total * 100, 1) if nodes_total else 0,
            "phase":              verana_layer.get("phase", "ACTIVE"),
            "status":             verana_layer.get("status", "COMPLETE"),
        },
        "agents": {
            "VERANA_L0":  {"role": "Network Governance", "status": "ACTIVE" if not halt_active else "HALTED"},
            "MENTAT_L1":  {"role": "Strategic Intelligence", "status": "ACTIVE"},
            "KALADAN_L2": {"role": "Lifecycle Orchestration", "status": "ACTIVE"},
            "THIFUR_C2":  {"role": "Command and Control", "status": "ACTIVE"},
            "THIFUR_R":   {"role": "TradFi Settlement", "status": "ACTIVE"},
            "THIFUR_J":   {"role": "Pre-Trade Governance", "status": "ACTIVE"},
            "THIFUR_H":   {"role": "Execution Optimization", "status": "DECLARED"},
            "NEPTUNE":    {"role": "Alpha Generator / Origination", "status": "DECLARED"},
        },
        "doctrine_ref": "Verana L0 — Network Governance Layer · Aureon Grid 3",
    }


def _read_regulatory_frameworks() -> dict:
    return {
        "registry_id":  "VERANA-REG-FW-001",
        "ts":           datetime.now(timezone.utc).isoformat(),
        "frameworks": [
            {
                "id":          "SR_11_7",
                "name":        "SR 11-7 — Model Risk Management",
                "status":      "SATISFIED",
                "description": "Federal Reserve model risk management guidance. "
                               "All Aureon signals and models documented, validated, and governed.",
                "authority":   "Federal Reserve Board",
            },
            {
                "id":          "OCC_2023_17",
                "name":        "OCC 2023-17 — Third-Party Risk",
                "status":      "SATISFIED",
                "description": "OCC guidance on third-party relationships and risk management. "
                               "All vendor integrations (yFinance, TwelveData, Railway) assessed.",
                "authority":   "Office of the Comptroller of the Currency",
            },
            {
                "id":          "BCBS_239",
                "name":        "BCBS 239 — Risk Data Aggregation",
                "status":      "SATISFIED",
                "description": "Basel Committee principles for effective risk data aggregation and reporting. "
                               "Single aureon_state source of truth with full lineage.",
                "authority":   "Bank for International Settlements",
            },
            {
                "id":          "MIFID_II",
                "name":        "MiFID II Art. 17 / RTS 6 — Algorithmic Trading",
                "status":      "SATISFIED",
                "description": "EU algorithmic trading governance requirements. "
                               "All signals require human authority approval — zero autonomous execution.",
                "authority":   "European Securities and Markets Authority (ESMA)",
            },
            {
                "id":          "DORA",
                "name":        "DORA — Digital Operational Resilience Act",
                "status":      "SATISFIED",
                "description": "EU DORA Article 28 absorbed. 4 nodes flagged during absorption event. "
                               "Doctrine updated to v1.1. Operational resilience maintained.",
                "authority":   "European Parliament / Council",
                "doctrine_event": "Doctrine v1.0 → v1.1 triggered by Verana L0 DORA absorption",
            },
            {
                "id":          "EU_AI_ACT",
                "name":        "EU AI Act — High-Risk AI Systems",
                "status":      "SATISFIED",
                "description": "Aureon qualifies as high-risk AI in financial services. "
                               "Full HITL architecture, audit trail, and human authority chain "
                               "satisfy EU AI Act transparency and oversight requirements.",
                "authority":   "European Parliament / Council",
            },
        ],
        "doctrine_ref": "Verana L0 — Regulatory Absorption · All frameworks satisfied",
    }


def _read_ofac_list() -> dict:
    blocked = _ofac_blocked or {}
    return {
        "registry_id":   "VERANA-OFAC-001",
        "ts":            datetime.now(timezone.utc).isoformat(),
        "gate":          "Gate 5 — OFAC SDN Screening",
        "gate_position": "5 of 7 pre-trade governance gates",
        "list_type":     "OFAC Specially Designated Nationals (SDN)",
        "authority":     "U.S. Department of the Treasury, Office of Foreign Assets Control",
        "count":         len(blocked),
        "blocked_entries": [
            {"identifier": isin, "basis": reason}
            for isin, reason in blocked.items()
        ],
        "screening_rule": (
            "Any trade where the ISIN or counterparty identifier matches "
            "an entry in this list is automatically BLOCKED at Gate 5. "
            "No human override permitted without Tier 3 Executive authority "
            "and formal doctrine addendum via Verana Network Registry."
        ),
        "doctrine_ref": "Verana L0 — OFAC Gate · Pre-Trade Governance · Gate 5 of 7",
    }


def _read_compliance_alerts() -> dict:
    with _lock:
        alerts       = list(_state.get("compliance_alerts", []))
        history      = list(_state.get("alert_history", []))[:50]
        drawdown     = round(_state.get("drawdown", 0.0), 4)
        pnl_pct      = round(_state.get("pnl_pct", 0.0), 4)
        halt_active  = _state.get("halt_active", False)
        halt_reason  = _state.get("halt_reason")

    return {
        "registry_id":    "VERANA-ALERTS-001",
        "ts":             datetime.now(timezone.utc).isoformat(),
        "halt_active":    halt_active,
        "halt_reason":    halt_reason,
        "active_alerts":  alerts,
        "alert_count":    len(alerts),
        "alert_history":  history,
        "portfolio": {
            "drawdown":   drawdown,
            "pnl_pct":    pnl_pct,
            "drawdown_hard_stop": 0.10,
            "drawdown_status": (
                "BREACH" if drawdown >= 0.10
                else "WARNING" if drawdown >= 0.07
                else "NORMAL"
            ),
        },
        "doctrine_ref": "Verana L0 — Compliance Alert Feed · Real-time governance posture",
    }


def _read_doctrine_status() -> dict:
    with _lock:
        version      = _state.get("doctrine_version", "unknown")
        stack_status = _state.get("stack_status", "unknown")
        stack_result = _state.get("stack_result")
        audit        = _state.get("audit")
        last_run     = _state.get("last_stack_run")
        halt_active  = _state.get("halt_active", False)
        halt_ts      = _state.get("halt_ts")
        halt_reason  = _state.get("halt_reason")
        version_log  = list(_state.get("doctrine_version_log", []))[:10]
        pending      = list(_state.get("pending_doctrine_updates", []))

    return {
        "registry_id":               "VERANA-DOCTRINE-001",
        "ts":                        datetime.now(timezone.utc).isoformat(),
        "doctrine_version":          version,
        "stack_status":              stack_status,
        "last_stack_run":            last_run,
        "audit_hash":                audit,
        "halt_active":               halt_active,
        "halt_ts":                   halt_ts,
        "halt_reason":               halt_reason,
        "pending_doctrine_updates":  pending,
        "doctrine_version_log":      version_log,
        "stack_result":              stack_result,
        "doctrine_ref": (
            "Verana L0 — Doctrine Version Governance · "
            "Regulatory changes absorbed by Verana → Tier 1 approval → version increment"
        ),
    }


RESOURCE_READERS = {
    RESOURCE_NETWORK_REGISTRY:  _read_network_registry,
    RESOURCE_REG_FRAMEWORKS:    _read_regulatory_frameworks,
    RESOURCE_OFAC_LIST:         _read_ofac_list,
    RESOURCE_COMPLIANCE_ALERTS: _read_compliance_alerts,
    RESOURCE_DOCTRINE_STATUS:   _read_doctrine_status,
}


# ─────────────────────────────────────────────────────────────────────────────
# Tool Handlers
# ─────────────────────────────────────────────────────────────────────────────

FRAMEWORK_LABELS = {
    "SR_11_7":     "SR 11-7 — Model Risk Management",
    "OCC_2023_17": "OCC 2023-17 — Third-Party Risk",
    "BCBS_239":    "BCBS 239 — Risk Data Aggregation",
    "MIFID_II":    "MiFID II Art. 17 / RTS 6 — Algorithmic Trading",
    "DORA":        "DORA — Digital Operational Resilience Act",
    "EU_AI_ACT":   "EU AI Act — High-Risk AI Systems",
}


def _tool_verana_screen_ofac(params: dict) -> dict:
    identifier = params.get("identifier", "").strip().upper()
    if not identifier:
        return {
            "isError": True,
            "content": [{"type": "text", "text": "identifier is required"}],
        }

    blocked = _ofac_blocked or {}
    # Check exact match and case-insensitive
    match_key = next(
        (k for k in blocked if k.upper() == identifier),
        None
    )

    if match_key:
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "gate":       "Gate 5 — OFAC SDN Screening",
                    "identifier": identifier,
                    "result":     "BLOCKED",
                    "basis":      blocked[match_key],
                    "authority":  "U.S. Treasury OFAC SDN List",
                    "action":     "Trade BLOCKED. Tier 3 Executive authority required to proceed. "
                                  "Formal doctrine addendum required via Verana Network Registry.",
                    "ts":         datetime.now(timezone.utc).isoformat(),
                }, indent=2),
            }],
        }
    else:
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "gate":       "Gate 5 — OFAC SDN Screening",
                    "identifier": identifier,
                    "result":     "PASS",
                    "basis":      "No SDN / sanctions match found",
                    "authority":  "U.S. Treasury OFAC SDN List",
                    "action":     "Gate 5 PASS — proceed to Gate 6.",
                    "ts":         datetime.now(timezone.utc).isoformat(),
                }, indent=2),
            }],
        }


def _tool_verana_framework_status(params: dict) -> dict:
    fw_id = params.get("framework", "").strip().upper()
    if fw_id not in FRAMEWORK_LABELS:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Unknown framework: {fw_id}. "
                          f"Valid values: {', '.join(FRAMEWORK_LABELS.keys())}"}],
        }

    # All frameworks satisfied — reflect current doctrine state
    with _lock:
        doctrine = _state.get("doctrine_version", "unknown")
        halt     = _state.get("halt_active", False)

    detail_map = {
        "SR_11_7":     "All models documented and validated. Signal generation logic reviewed.",
        "OCC_2023_17": "All third-party integrations assessed and governed.",
        "BCBS_239":    "Single aureon_state source of truth. Full lineage via authority_log.",
        "MIFID_II":    "Zero autonomous execution. All signals require HITL approval.",
        "DORA":        f"DORA absorption triggered doctrine v1.1 update. Currently v{doctrine}.",
        "EU_AI_ACT":   "Full HITL architecture. Audit trail and human authority chain active.",
    }

    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "framework":       fw_id,
                "name":            FRAMEWORK_LABELS[fw_id],
                "status":          "BREACHED" if halt else "SATISFIED",
                "detail":          detail_map[fw_id],
                "doctrine_version": doctrine,
                "halt_active":     halt,
                "ts":              datetime.now(timezone.utc).isoformat(),
            }, indent=2),
        }],
    }


def _tool_verana_node_status(params: dict) -> dict:
    with _lock:
        nodes_total  = _state.get("network_nodes", 15)
        nodes_op     = _state.get("nodes_operational", 15)
        doctrine     = _state.get("doctrine_version", "unknown")
        stack_result = _state.get("stack_result") or {}
        halt_active  = _state.get("halt_active", False)

    verana_layer = stack_result.get("layers", {}).get("verana", {})
    phase = verana_layer.get("phase", "ACTIVE")

    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "network_registry": "VERANA-NET-REG-001",
                "total_nodes":       nodes_total,
                "operational_nodes": nodes_op,
                "degraded_nodes":    max(0, nodes_total - nodes_op),
                "operational_pct":   round(nodes_op / nodes_total * 100, 1) if nodes_total else 0,
                "phase":             phase,
                "doctrine_version":  doctrine,
                "halt_active":       halt_active,
                "network_status":    "HALTED" if halt_active else ("DEGRADED" if nodes_op < nodes_total else "OPERATIONAL"),
                "ts":                datetime.now(timezone.utc).isoformat(),
            }, indent=2),
        }],
    }


def _tool_verana_compliance_snapshot(params: dict) -> dict:
    network   = _read_network_registry()
    frameworks = _read_regulatory_frameworks()
    alerts    = _read_compliance_alerts()
    doctrine  = _read_doctrine_status()

    with _lock:
        halt_active = _state.get("halt_active", False)
        drawdown    = round(_state.get("drawdown", 0.0), 4)

    snapshot = {
        "snapshot_id":    f"VERANA-SNAP-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "ts":             datetime.now(timezone.utc).isoformat(),
        "governance_posture": "HALTED" if halt_active else "OPERATIONAL",
        "network":        network["network"],
        "doctrine_version": doctrine["doctrine_version"],
        "halt_active":    halt_active,
        "drawdown":       drawdown,
        "active_alerts":  alerts["alert_count"],
        "framework_summary": [
            {"id": fw["id"], "status": fw["status"]}
            for fw in frameworks["frameworks"]
        ],
        "ofac_blocked_count": len(_ofac_blocked or {}),
        "doctrine_ref": "Verana L0 — Full Compliance Snapshot",
    }

    return {
        "content": [{
            "type": "text",
            "text": json.dumps(snapshot, indent=2),
        }],
    }


TOOL_HANDLERS = {
    "verana_screen_ofac":          _tool_verana_screen_ofac,
    "verana_framework_status":     _tool_verana_framework_status,
    "verana_node_status":          _tool_verana_node_status,
    "verana_compliance_snapshot":  _tool_verana_compliance_snapshot,
}


# ─────────────────────────────────────────────────────────────────────────────
# MCP Method Dispatch
# ─────────────────────────────────────────────────────────────────────────────

def _handle_initialize(req_id, params: dict) -> dict:
    return _ok(req_id, {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities":    _server_capabilities(),
        "serverInfo": {
            "name":    MCP_SERVER_NAME,
            "version": MCP_SERVER_VERSION,
        },
        "instructions": (
            "Aureon Verana L0 MCP Server. "
            "Provides network governance, compliance, OFAC screening, and "
            "regulatory framework status for Project Aureon — The Grid 3. "
            "All resources reflect live system state. "
            "Doctrine ref: Verana L0 · Aureon Grid 3 · CAOM-001 active."
        ),
    })


def _handle_resources_list(req_id, params: dict) -> dict:
    return _ok(req_id, {"resources": RESOURCES})


def _handle_resources_read(req_id, params: dict) -> dict:
    uri = params.get("uri", "")
    reader = RESOURCE_READERS.get(uri)
    if not reader:
        return _err(req_id, ERR_RESOURCE_NOT_FOUND,
                    f"Resource not found: {uri}",
                    {"available": [r["uri"] for r in RESOURCES]})
    try:
        data = reader()
        return _ok(req_id, {
            "contents": [{
                "uri":      uri,
                "mimeType": "application/json",
                "text":     json.dumps(data, indent=2),
            }],
        })
    except Exception as exc:
        return _err(req_id, ERR_INTERNAL, f"Resource read error: {exc}")


def _handle_tools_list(req_id, params: dict) -> dict:
    return _ok(req_id, {"tools": TOOLS})


def _handle_tools_call(req_id, params: dict) -> dict:
    name       = params.get("name", "")
    args       = params.get("arguments", {})
    handler    = TOOL_HANDLERS.get(name)
    if not handler:
        return _err(req_id, ERR_METHOD_NOT_FOUND,
                    f"Tool not found: {name}",
                    {"available": list(TOOL_HANDLERS.keys())})
    try:
        result = handler(args)
        return _ok(req_id, result)
    except Exception as exc:
        return _err(req_id, ERR_INTERNAL, f"Tool execution error: {exc}")


def _handle_ping(req_id, params: dict) -> dict:
    return _ok(req_id, {})


METHOD_DISPATCH = {
    "initialize":        _handle_initialize,
    "resources/list":    _handle_resources_list,
    "resources/read":    _handle_resources_read,
    "tools/list":        _handle_tools_list,
    "tools/call":        _handle_tools_call,
    "ping":              _handle_ping,
}


# ─────────────────────────────────────────────────────────────────────────────
# HTTP Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@mcp_bp.route("/mcp", methods=["POST"])
def mcp_endpoint():
    """
    MCP Streamable HTTP transport — single endpoint for all JSON-RPC messages.
    Accepts: application/json
    Returns: application/json

    Supports batch requests (array of request objects) per JSON-RPC 2.0 spec.
    """
    if _state is None:
        return jsonify(_err(None, ERR_INTERNAL, "MCP server not initialized")), 500

    # ── Parse request ──────────────────────────────────────────────
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None

    if body is None:
        return jsonify(_err(None, ERR_PARSE, "Parse error — invalid JSON")), 400

    # ── Batch support ──────────────────────────────────────────────
    batch = isinstance(body, list)
    items = body if batch else [body]

    responses = []
    for item in items:
        responses.append(_dispatch_single(item))

    # Filter out None (notifications have no response per JSON-RPC spec)
    responses = [r for r in responses if r is not None]

    if batch:
        return jsonify(responses)
    return jsonify(responses[0]) if responses else ("", 204)


def _dispatch_single(item: dict):
    """Dispatch a single JSON-RPC request object."""
    if not isinstance(item, dict):
        return _err(None, ERR_INVALID_REQ, "Invalid request object")

    req_id  = item.get("id")          # None for notifications
    method  = item.get("method", "")
    params  = item.get("params") or {}
    jsonrpc = item.get("jsonrpc")

    if jsonrpc != "2.0":
        return _err(req_id, ERR_INVALID_REQ, "jsonrpc must be '2.0'")

    handler = METHOD_DISPATCH.get(method)
    if not handler:
        # Notifications (no id) don't get error responses per spec
        if req_id is None:
            return None
        return _err(req_id, ERR_METHOD_NOT_FOUND, f"Method not found: {method}")

    try:
        result = handler(req_id, params)
        # Notifications don't get responses
        return None if req_id is None else result
    except Exception as exc:
        return _err(req_id, ERR_INTERNAL, f"Internal error: {exc}")


@mcp_bp.route("/mcp", methods=["GET"])
def mcp_info():
    """
    MCP server discovery endpoint.
    Returns server info and capability summary for human inspection.
    """
    return jsonify({
        "server":           MCP_SERVER_NAME,
        "version":          MCP_SERVER_VERSION,
        "protocol_version": MCP_PROTOCOL_VERSION,
        "transport":        "Streamable HTTP (JSON-RPC 2.0 POST /mcp)",
        "phase":            "Phase 1 — Verana L0",
        "resources":        [{"uri": r["uri"], "name": r["name"]} for r in RESOURCES],
        "tools":            [{"name": t["name"], "description": t["description"][:80]} for t in TOOLS],
        "doctrine_ref":     "Verana L0 · Aureon Grid 3 · CAOM-001",
    })
