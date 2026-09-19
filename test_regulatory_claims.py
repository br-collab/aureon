"""AMD4-1: no surface asserts a regulatory compliance status nothing established.

`GET /api/compliance` and two MCP (Model Context Protocol) surfaces published five
regimes — OCC 2023-17, BCBS 239, MiFID II Art. 17 / RTS 6, DORA, EU AI Act — as
`SATISFIED`, as literal strings, with nothing computing any of them. They sat in
the same array as two rows W2B-6 had deliberately downgraded to `ALIGNMENT` with a
comment explaining why claiming compliance was wrong.

The third surface was the worst of them. `verana_framework_status` computed:

    "status": "ALIGNMENT" if fw_id == "SR_26_2" else "BREACHED" if halt else "SATISFIED"

so the Tier 0 emergency halt decided regulatory compliance. Engaging the halt did
not breach DORA and leaving it disengaged did not satisfy MiFID II.

These tests bind the vocabulary rather than the current wording: a forbidden status
may not appear in any response, and every row must carry a basis. Adding a regime,
or a surface, cannot reintroduce the class without failing here.

Run: pytest -q test_regulatory_claims.py
"""

from __future__ import annotations

import json

import pytest

from aureon.policy_engine.regulatory_register import (
    FORBIDDEN_STATUSES,
    REGULATORY_FRAMEWORKS,
    FrameworkStatus,
    frameworks_registry,
    frameworks_summary,
)


def _statuses(rows) -> set[str]:
    return {row["status"] for row in rows}


# --- the register itself ------------------------------------------------------

def test_the_register_cannot_express_a_compliance_conclusion() -> None:
    """SATISFIED is not a value the type has, so no surface can select it."""
    assert FORBIDDEN_STATUSES.isdisjoint({s.value for s in FrameworkStatus})


@pytest.mark.parametrize("framework", REGULATORY_FRAMEWORKS, ids=lambda f: f.id)
def test_every_row_carries_the_basis_behind_it(framework) -> None:
    """A status with no basis is the same assertion in a different word."""
    assert framework.basis.strip(), f"{framework.id} states a status with no basis"
    assert len(framework.basis) > 60, (
        f"{framework.id}: the basis is too short to say what stands behind the row"
    )


@pytest.mark.parametrize("framework", REGULATORY_FRAMEWORKS, ids=lambda f: f.id)
def test_no_row_claims_to_be_computed_while_nothing_computes_it(framework) -> None:
    """EVALUATED exists for when a row can read a recorded result. None can yet."""
    assert framework.status is not FrameworkStatus.EVALUATED, (
        f"{framework.id} claims to be computed; if that is now true, this test should "
        f"assert the evaluation it reads rather than be deleted"
    )


def test_the_five_regimes_that_read_satisfied_no_longer_do() -> None:
    downgraded = {"OCC_2023_17", "BCBS_239", "MIFID_II", "DORA", "EU_AI_ACT"}
    by_id = {f.id: f for f in REGULATORY_FRAMEWORKS}
    assert downgraded <= set(by_id), "a regime that read SATISFIED has left the register"
    for fw_id in sorted(downgraded):
        assert by_id[fw_id].status in (FrameworkStatus.ALIGNMENT, FrameworkStatus.UNASSESSED)


# --- the surfaces -------------------------------------------------------------

@pytest.mark.parametrize("rows", [frameworks_summary(), frameworks_registry()],
                         ids=["api-compliance", "mcp-registry"])
def test_no_surface_emits_a_forbidden_status(rows) -> None:
    offenders = _statuses(rows) & FORBIDDEN_STATUSES
    assert offenders == set(), f"a surface asserts a compliance conclusion: {offenders}"


@pytest.mark.parametrize("rows", [frameworks_summary(), frameworks_registry()],
                         ids=["api-compliance", "mcp-registry"])
def test_every_surface_row_carries_its_basis(rows) -> None:
    assert rows, "the surface returns no rows"
    for row in rows:
        assert row.get("basis"), f"{row['name']} is published with no basis"


def test_the_halt_flag_does_not_decide_regulatory_status() -> None:
    """The emergency halt is an operating state, not a regulatory finding."""
    source = open("aureon/mcp/server.py", encoding="utf-8").read()
    body = source[source.index("def _tool_verana_framework_status"):]
    body = body[: body.index("\ndef ", 1)]
    code = "\n".join(line for line in body.splitlines() if not line.strip().startswith("#"))
    # The docstring quotes the old expression to explain it; strip it before asserting.
    code = code.replace(body[body.index('"""') : body.index('"""', body.index('"""') + 3)], "")
    assert "if halt else" not in code, (
        "the halt flag still selects the reported regulatory status"
    )


def test_the_register_is_the_only_place_naming_a_regime() -> None:
    """Two copies of a name drift; the MCP labels map used to be the second."""
    source = open("aureon/mcp/server.py", encoding="utf-8").read()
    assert "framework_labels()" in source, "the MCP surface no longer reads the register"
    assert '"OCC_2023_17": "OCC 2023-17' not in source, "a second copy of the names is back"


def test_the_tool_schema_offers_exactly_what_the_register_holds() -> None:
    """A regime the register knows but the schema rejects is invisible to a client."""
    from aureon.mcp import server as mcp

    tool = next(t for t in mcp.TOOLS if t["name"] == "verana_framework_status")
    offered = set(tool["inputSchema"]["properties"]["framework"]["enum"])
    known = {f.id for f in REGULATORY_FRAMEWORKS}
    assert known <= offered, f"the register knows regimes the schema rejects: {known - offered}"
    assert offered - known == {"SR_11_7"}, (
        "the schema offers a regime the register does not hold (SR_11_7 is the "
        f"documented deprecated alias): {offered - known}"
    )


@pytest.fixture()
def mcp_bound():
    """The MCP module takes its state and lock at registration time."""
    import server as flask_server
    from aureon.mcp import server as mcp

    mcp.init_mcp(flask_server.aureon_state, flask_server._lock,
                 flask_server.OFAC_BLOCKED_ISINS)
    return mcp


def test_the_per_framework_tool_reports_the_registers_status(mcp_bound) -> None:
    mcp = mcp_bound

    for framework in REGULATORY_FRAMEWORKS:
        result = mcp._tool_verana_framework_status({"framework": framework.id})
        assert not result.get("isError"), f"{framework.id} is rejected by the tool"
        payload = json.loads(result["content"][0]["text"])
        assert payload["status"] == framework.status.value
        assert payload["basis"] == framework.basis
        assert payload["status"] not in FORBIDDEN_STATUSES
