#!/usr/bin/env python3
"""Compile requirements.lock.txt, keeping git URLs spelled as requirements.txt spells them.

Why this exists (finding W2B7-V-02).

`uv pip compile` normalises a git dependency to the commit it resolved:

    cannae-kernel @ git+https://github.com/br-collab/cannae-kernel.git@c4cb6c1…

Atreides declares the *same commit* by its tag:

    cannae-kernel @ git+https://github.com/br-collab/cannae-kernel.git@v0.1.1

`v0.1.1^{}` **is** `c4cb6c1`, but pip compares direct URLs as **strings**, so it
sees two different requirements for one package and refuses the whole file:

    ERROR: ResolutionImpossible
    The user requested cannae-kernel 0.1.1 (from git+…@c4cb6c1…)
    atreides 0.4.1 depends on cannae-kernel 0.1.1 (from git+…@v0.1.1)

It did not arise before Atreides v0.4.0, which was the first release to declare
the kernel as its own dependency.

uv 0.11.6 has no option to emit the tag form, so this script restores it after
compiling: for every git requirement that `requirements.txt` declares by ref,
the lock is written with that same ref, and the commit uv resolved is kept
beside it as a comment so nothing is lost.

The trade-off, stated plainly: the lock then pins those packages by tag rather
than by commit, so it is exactly as immutable as the tags are. Both tags here
are release tags on repositories we control, and the resolved commits are in the
comments. The alternative — spelling the SHA in `requirements.txt` — was
rejected: that file is the deploy path and is meant to be read by a person.

Usage:
    python scripts/compile_lock.py            # rewrite requirements.lock.txt
    python scripts/compile_lock.py --check    # fail if the lock is out of date
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"
LOCK = ROOT / "requirements.lock.txt"

#: `name @ git+<url>@<ref>` — the ref may be a tag, a branch or a commit.
GIT_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9._-]+)\s*@\s*git\+(?P<url>[^@\s]+)@(?P<ref>\S+)\s*$"
)
COMMIT = re.compile(r"^[0-9a-f]{40}$")

#: uv records the exact command it was run with, including the output path. That
#: path is a temporary file here, so it is replaced with the canonical command —
#: otherwise the header would differ on every run and --check could never pass.
HEADER_COMMAND = "#    python scripts/compile_lock.py\n"


def declared_refs(requirements: str) -> dict[str, tuple[str, str]]:
    """{package: (url, ref)} for every git requirement declared by a non-commit ref."""
    found = {}
    for line in requirements.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = GIT_REQUIREMENT.match(line)
        if match and not COMMIT.match(match["ref"]):
            found[match["name"].lower()] = (match["url"], match["ref"])
    return found


def canonical_header(lock: str) -> str:
    """Replace uv's recorded command line, which carries a temporary path."""
    return re.sub(r"^#\s+uv pip compile .*$\n", HEADER_COMMAND, lock, count=1, flags=re.M)


def restore_refs(lock: str, refs: dict[str, tuple[str, str]]) -> str:
    """Rewrite resolved commits back to the ref requirements.txt declares."""
    out = []
    for line in lock.splitlines():
        match = GIT_REQUIREMENT.match(line.strip())
        if match:
            declared = refs.get(match["name"].lower())
            if declared and COMMIT.match(match["ref"]):
                url, ref = declared
                if url == match["url"]:
                    out.append(f"{match['name']} @ git+{url}@{ref}")
                    out.append(f"    # resolved to {match['ref']}")
                    continue
        out.append(line)
    return "\n".join(out) + "\n"


def compile_lock() -> str:
    # uv writes a new file at the path rather than into an open handle, so the
    # output is read back from disk after the run, not from a file object.
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "lock.txt"
        subprocess.run(
            ["uv", "pip", "compile", "requirements.txt", "--python-version", "3.11",
             "-o", str(out)],
            check=True, cwd=ROOT, stdout=subprocess.DEVNULL,
        )
        compiled = out.read_text(encoding="utf-8")
    if not compiled.strip():
        raise SystemExit("uv produced an empty lock; refusing to write it")
    return restore_refs(
        canonical_header(compiled), declared_refs(REQUIREMENTS.read_text(encoding="utf-8"))
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="fail if requirements.lock.txt is not what this would write")
    args = parser.parse_args()

    expected = compile_lock()
    if not args.check:
        LOCK.write_text(expected, encoding="utf-8")
        print(f"wrote {LOCK.relative_to(ROOT)}")
        return 0

    current = LOCK.read_text(encoding="utf-8")
    if current == expected:
        print("requirements.lock.txt is up to date")
        return 0
    print("requirements.lock.txt is out of date; run: python scripts/compile_lock.py",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
