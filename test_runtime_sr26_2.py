"""W2-ADD-02 (W2B-6): runtime output cites SR 26-2 / OCC 2026-13 with alignment language.

SR 26-2 / OCC 2026-13 superseded SR 11-7 on 17 April 2026 and excludes agentic
AI. Aureon's runtime output must not report "SR 11-7 — Model Risk Management:
SATISFIED". MCP keeps SR_11_7 as a deprecated alias.

Run: pytest -q test_runtime_sr26_2.py
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile

os.environ.setdefault("RAILWAY_VOLUME_MOUNT_PATH", tempfile.mkdtemp(prefix="aureon-sr262-test-"))

import server  # noqa: E402
from aureon.mcp import server as mcp  # noqa: E402

ROOT = pathlib.Path(__file__).parent


def _framework_tool(framework: str) -> dict:
    mcp.init_mcp(server.aureon_state, server._lock, server.OFAC_BLOCKED_ISINS)
    return json.loads(mcp._tool_verana_framework_status({"framework": framework})["content"][0]["text"])


def test_compliance_endpoint_reports_alignment_not_satisfied() -> None:
    frameworks = server.app.test_client().get("/api/compliance").get_json()["frameworks"]
    by_name = {f["name"]: f["status"] for f in frameworks}
    assert by_name["SR 26-2 / OCC 2026-13 — alignment (quantitative models)"] == "ALIGNMENT"
    assert by_name["NIST AI RMF 1.0 — alignment (agentic components)"] == "ALIGNMENT"
    assert not any("SR 11-7" in name for name in by_name)


def test_mcp_sr_26_2_is_alignment() -> None:
    result = _framework_tool("SR_26_2")
    assert result["framework"] == "SR_26_2"
    assert result["status"] == "ALIGNMENT"
    assert "No row is a compliance determination" in result["note"]
    assert result["basis"], "the alignment claim is published with no basis"
    assert "deprecation" not in result


def test_mcp_sr_11_7_is_a_deprecated_alias() -> None:
    alias = _framework_tool("SR_11_7")
    current = _framework_tool("SR_26_2")
    assert alias["requested"] == "SR_11_7"
    assert "deprecated" in alias["deprecation"]
    assert {k: v for k, v in alias.items() if k not in ("requested", "deprecation", "ts")} == \
        {k: v for k, v in current.items() if k != "ts"}
    enum = next(t for t in mcp.TOOLS if t["name"] == "verana_framework_status")[
        "inputSchema"]["properties"]["framework"]["enum"]
    assert enum[0] == "SR_26_2" and "SR_11_7" in enum


def test_mcp_frameworks_resource_lists_sr_26_2() -> None:
    frameworks = mcp._read_regulatory_frameworks()["frameworks"]
    ids = {f["id"]: f for f in frameworks}
    assert "SR_11_7" not in ids
    assert ids["SR_26_2"]["status"] == "ALIGNMENT"


def test_no_runtime_string_still_cites_sr_11_7_as_current() -> None:
    """Every remaining SR 11-7 mention is historical, a supersession note, or versioned doctrine."""
    allowed = {
        "server.py": ("Historical Backtest", "superseded SR 11-7"),
        "scripts/cato_backtest.py": ("supersedes SR 11-7",),
        "aureon/mcp/server.py": ("SR_11_7", "supersedes SR 11-7", "SR 11-7 was superseded",
                                 "SR 11-7 / OCC 2011-12"),
        "aureon/doctrine/risk_thresholds_fixture.json": ("SR 11-7 risk monitoring",),  # versioned; errata
    }
    out = subprocess.run(
        ["git", "grep", "-n", "-e", "SR 11-7", "-e", "SR_11_7", "--", ":!*.md", ":!CATO DEMO",
         ":!test_*"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    ).stdout
    offenders = []
    for line in out.splitlines():
        path, _, text = line.split(":", 2)
        if not any(marker in text for marker in allowed.get(path, ())):
            offenders.append(line)
    assert offenders == []
