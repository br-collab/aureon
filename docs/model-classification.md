# Aureon component classification

Every result below is an Aureon voluntary classification, not a regulatory determination.

The four classes are `EXCLUDED_DETERMINISTIC_SOFTWARE`,
`THEORY_BASED_QUANTITATIVE_METHOD`, `NON_GENERATIVE_NON_AGENTIC_AI`, and
`GENERATIVE_OR_AGENTIC_AI`. SR 26-2 and OCC Bulletin 2026-13 exclude simple arithmetic and
deterministic rule-based software only where no statistical, economic, or financial theories
underpin design or use. Determinism alone is not the test. Generative and agentic artificial
intelligence are outside the guidance, and the banking organization's own governance determines
their controls.

| Component | Class | Code reference |
|---|---|---|
| Thifur-R operational agents | `EXCLUDED_DETERMINISTIC_SOFTWARE` | `aureon/agents/ranger/` |
| Thifur-J bounded path selectors | `EXCLUDED_DETERMINISTIC_SOFTWARE` | `aureon/agents/jtac/` |
| Thifur-H advisory agent | `GENERATIVE_OR_AGENTIC_AI` | `aureon/thifur/agent_h.py` |
| Cato pricing and stress gate | `THEORY_BASED_QUANTITATIVE_METHOD` candidate | `aureon/mcp/cato_client.py` |
| Margin, netting, and haircut logic | `THEORY_BASED_QUANTITATIVE_METHOD` candidate | Atreides margin and netting modules |

The guidance is expected to be most relevant to banking organizations above $30 billion in total
assets, but may matter to smaller banks with significant model risk. It creates no enforceable
standards. Footnote 1 preserves supervisory action for violations of law or unsafe or unsound
practices tied to poor model risk management. Whether it reaches a broker-dealer in a banking
group is an open question for counsel.

OCC Bulletin 2026-54, dated 4 November 2026, describes the Super Intelligence Supervisory
Framework as an examiner resource and states that it does not establish supervisory expectations
for banks.

Sources: Federal Reserve SR 26-2, OCC Bulletin 2026-13, and OCC Bulletin 2026-54.
