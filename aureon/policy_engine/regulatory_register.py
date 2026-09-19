"""
aureon.policy_engine.regulatory_register
========================================
What the system may say about a regulatory regime (W2B7-AMD4 § AMD4-1).

Two surfaces published a regulatory posture: ``GET /api/compliance`` and the
MCP (Model Context Protocol) tool ``_read_regulatory_frameworks``. Both carried
five regimes marked **SATISFIED** as literal strings, with nothing computing
any of them, in the same array as two rows W2B-6 had deliberately downgraded to
``ALIGNMENT`` with a comment explaining why claiming compliance was wrong.

This is the Wave 2 defect class — a surface asserting what the record does not
hold — in its most consequential form, because these are not labels on a
dashboard. They are a machine-readable compliance assertion served over HTTP
and to any MCP client.

Three statuses, and there is deliberately no fourth
---------------------------------------------------
- ``ALIGNMENT`` — a control exists here and was built against this regime. It is
  a statement about **design intent**, made by a person, and it is not a
  compliance conclusion. This is the value W2B-6 established for SR 26-2.
- ``UNASSESSED`` — not even alignment has been established. Nothing here was
  built against this regime, or the evidence that was cited turned out to be a
  fixture.
- ``EVALUATED`` — a status some code computed, carrying the evaluation behind
  it. **Nothing returns this today**, and that is the honest finding: see
  ``MIFID_II`` below.

``SATISFIED`` is not available. A compliance conclusion is a determination made
by people with the standing to make it, recorded somewhere that is not a Python
literal. If one is ever made, it belongs in a record this module reads — not in
a string this module ships.

Why no row computes its status today
------------------------------------
One real evaluator exists: :meth:`Compliance.check_algo_inventory`
(``aureon/agents/jtac/compliance.py``) genuinely tests active algorithms against
the MiFID II RTS 6 inventory fixture, including validation freshness. It cannot
drive the ``MIFID_II`` row, for two reasons found while writing this:

1. its ``active_algorithms`` are supplied by the caller, so it evaluates whatever
   it is handed rather than what is actually running; and
2. a passing result is returned and discarded. Only ``MISSING_REGISTRATION``
   persists anything, as a ``paused_lifecycle`` entry.

So there is no recorded answer for this module to read. Registering the running
algorithms and recording each check result would make ``MIFID_II`` the first row
that can carry ``EVALUATED``. That is real work, it is not a labelling change,
and it is not in this amendment.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FrameworkStatus(StrEnum):
    """What the system is entitled to say about a regime."""

    ALIGNMENT = "ALIGNMENT"
    UNASSESSED = "UNASSESSED"
    EVALUATED = "EVALUATED"


#: Statuses no surface may emit. ``SATISFIED`` and ``COMPLIANT`` are compliance
#: conclusions; ``PARTIAL`` implies a measurement of how much. Tests assert that
#: none of these reaches a response.
FORBIDDEN_STATUSES = frozenset({"SATISFIED", "COMPLIANT", "PARTIAL", "CERTIFIED"})


@dataclass(frozen=True)
class Framework:
    """One regime, and what is actually behind it.

    ``basis`` is not a description of the regime. It is the answer to "what in
    this repository stands behind this row", written so that a reader can go and
    check it. Where the answer is "nothing", it says so.
    """

    id: str
    name: str
    status: FrameworkStatus
    basis: str
    authority: str
    supersedes: str | None = None

    def as_row(self) -> dict[str, str]:
        """The full row, for the MCP registry read."""
        row = {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "basis": self.basis,
            "authority": self.authority,
        }
        if self.supersedes:
            row["supersedes"] = self.supersedes
        return row

    def as_summary(self) -> dict[str, str]:
        """Name, status and basis, for the compliance snapshot."""
        return {"name": self.name, "status": self.status.value, "basis": self.basis}


SR_26_2_NAME = "SR 26-2 / OCC 2026-13 — alignment (quantitative models)"

REGULATORY_FRAMEWORKS: tuple[Framework, ...] = (
    Framework(
        id="SR_26_2",
        name=SR_26_2_NAME,
        status=FrameworkStatus.ALIGNMENT,
        basis="Model documentation, validation and change control were built against SR 26-2 / "
              "OCC 2026-13, which superseded SR 11-7 / OCC 2011-12 on 17 April 2026. The guidance "
              "excludes generative and agentic AI, so it does not reach the Thifur agents "
              "(W2-ADD-02). No independent validation has been performed.",
        authority="Federal Reserve Board · Office of the Comptroller of the Currency · FDIC",
        supersedes="SR 11-7 / OCC 2011-12 (superseded 17 April 2026)",
    ),
    Framework(
        id="NIST_AI_RMF",
        name="NIST AI RMF 1.0 — alignment (agentic components)",
        status=FrameworkStatus.ALIGNMENT,
        basis="The agentic components SR 26-2 excludes are governed here by NIST AI RMF 1.0 plus "
              "Aureon doctrine (W2-ADD-02). A framework, not a certification: NIST AI RMF is "
              "voluntary and confers no compliance status.",
        authority="National Institute of Standards and Technology",
    ),
    Framework(
        id="OCC_2023_17",
        name="OCC 2023-17 — Third-Party Risk",
        status=FrameworkStatus.UNASSESSED,
        basis="No third-party risk assessment exists in this repository and there is no vendor "
              "register. The previous row claimed the vendor integrations (yFinance, TwelveData, "
              "Railway) had been assessed; searching for the assessment found only the claim.",
        authority="Office of the Comptroller of the Currency",
    ),
    Framework(
        id="BCBS_239",
        name="BCBS 239 — Risk Data Aggregation",
        status=FrameworkStatus.ALIGNMENT,
        basis="The Reconciliation Analyst agent (AUR-R-RECON-001) implements depot-versus-ledger "
              "reconciliation, break identification and root-cause lineage, built against "
              "BCBS 239 Principle 3. An implemented control aligned to the principle — not a "
              "supervisory assessment against all fourteen principles, which has not been done.",
        authority="Bank for International Settlements",
    ),
    Framework(
        id="MIFID_II",
        name="MiFID II Art. 17 / RTS 6 — Algorithmic Trading",
        status=FrameworkStatus.ALIGNMENT,
        basis="Three controls exist: the RTS 6 algorithm inventory check "
              "(Compliance.check_algo_inventory, including validation freshness), the RTS 6 kill "
              "switch, and the requirement that every signal carries explicit human approval. The "
              "inventory check is a real evaluator, but it tests the algorithms its caller names "
              "rather than those actually running, and it records nothing when it passes — so no "
              "recorded result stands behind this row.",
        authority="European Securities and Markets Authority",
    ),
    Framework(
        id="DORA",
        name="DORA — Digital Operational Resilience Act",
        status=FrameworkStatus.UNASSESSED,
        basis="The previous row cited a doctrine v1.0 → v1.1 'Article 28 absorption event, 4 nodes "
              "flagged'. That entry is a seeded demonstration row: its hash is a digest of the "
              "constant b'AUREON-DOCTRINE-1.1-DORA' and its timestamp is generated at read time, "
              "so it re-dates itself on every request. No Article 28 register of contractual "
              "arrangements exists, and no resilience testing has been performed.",
        authority="European Parliament / Council",
    ),
    Framework(
        id="EU_AI_ACT",
        name="EU AI Act — High-Risk AI Systems",
        status=FrameworkStatus.UNASSESSED,
        basis="Whether this system is a high-risk AI system, and whether its human-oversight "
              "design meets Articles 13-15, are legal determinations. Nothing here computes them "
              "and no conformity assessment has been carried out. The human-in-the-loop "
              "architecture and audit trail are real and are the substance of the eventual "
              "argument; they are not the conclusion.",
        authority="European Parliament / Council",
    ),
)

#: The registry's own summary line. It used to read "All frameworks satisfied".
REGISTER_NOTE = (
    "Alignment and assessment status, self-reported. No row is a compliance determination, "
    "and no row is computed — see each row's basis."
)


def frameworks_summary() -> list[dict[str, str]]:
    """Rows for ``GET /api/compliance``."""
    return [framework.as_summary() for framework in REGULATORY_FRAMEWORKS]


def frameworks_registry() -> list[dict[str, str]]:
    """Rows for the MCP regulatory-framework registry read."""
    return [framework.as_row() for framework in REGULATORY_FRAMEWORKS]


def framework_labels() -> dict[str, str]:
    """``{id: name}``, for the MCP per-framework tool."""
    return {framework.id: framework.name for framework in REGULATORY_FRAMEWORKS}
