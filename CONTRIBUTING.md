# Contributing

Aureon is a research decision system of record. It is not audited, and nothing in this
repository should be described as production-grade financial infrastructure.

## Reporting problems

Report suspected vulnerabilities privately through the GitHub **Security** tab; see
`SECURITY.md`. For other defects, open an issue with expected behavior, observed behavior,
and reproduction steps.

## Pull requests

- Keep one work package per commit and do not mix security, lifecycle semantics, and
  presentation changes.
- Missing required evidence yields `HOLD` or `INDETERMINATE`, never `PASS`.
- Preserve provenance and explain the reason for every absence or refusal.
- Never commit credentials, tokens, private doctrine, or files excluded by the repository's
  protected `Project Atreides - Custody/` rule.
- Aureon deploys automatically when Bill merges to `main`; never push directly to `main`.

## Checks

Continuous integration installs `requirements.lock.txt`, verifies it against
`requirements.txt`, and runs the repository's Python and script checks. Supply-chain jobs
also review dependency changes, run CodeQL and secret scanning, and retain an SPDX software
bill of materials. Read each job's annotations as well as its pass or fail state.

## Licence

By contributing, you agree that your contribution is licensed under this repository's MIT
licence.
