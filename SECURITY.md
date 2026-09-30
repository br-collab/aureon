# Security policy

## Reporting a vulnerability

Please report security problems **privately**. Do not open a public issue, pull request or
discussion for a suspected vulnerability.

1. Open this repository's **Security** tab on GitHub.
2. Choose **Report a vulnerability** to create a private advisory visible only to the
   reporter and maintainer.

Include reproduction steps and the potential impact. The maintainer will acknowledge the
report and coordinate remediation and disclosure through the private advisory.

## Scope

Aureon is a research decision system of record with a live deployment path. It advises and
records governed approvals; it must not execute without operator authority. Reports about
authentication or authorization bypass, secret exposure, forged lineage, unsafe dependency
handling, or missing evidence being treated as approval are especially welcome.

## Supported versions

Only the latest commit on `main` is supported.
