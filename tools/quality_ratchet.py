"""Enforce per-file Ruff and strict mypy quality baselines."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / "quality"
RUFF_BASELINE = QUALITY / "ruff-baseline.json"
MYPY_BASELINE = QUALITY / "mypy-baseline.json"
CHECKSUM = QUALITY / "quality-ratchet.sha256"
ERROR_RE = re.compile(r"^(.+?):\d+(?::\d+)?: error:", re.MULTILINE)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)


def ruff_counts() -> dict[str, int]:
    result = run(["ruff", "check", ".", "--output-format", "json"])
    try:
        rows = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ruff output was not JSON: {exc}") from exc
    counts = Counter(str(Path(row["filename"]).resolve().relative_to(ROOT)) for row in rows)
    return dict(sorted(counts.items()))


def mypy_counts() -> dict[str, int]:
    targets = os.environ.get("QUALITY_MYPY_TARGETS", ".").split()
    result = run(["mypy", "--strict", *targets])
    counts: Counter[str] = Counter()
    for match in ERROR_RE.finditer(result.stdout + result.stderr):
        path = Path(match.group(1))
        if path.is_absolute():
            try:
                name = str(path.resolve().relative_to(ROOT))
            except ValueError:
                name = str(path)
        else:
            name = str(path)
        counts[name] += 1
    return dict(sorted(counts.items()))


def payload(counts: dict[str, int]) -> dict[str, object]:
    return {"files": counts, "total": sum(counts.values())}


def load(path: Path) -> dict[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(name): int(count) for name, count in data["files"].items()}


def base_payload(path: Path) -> dict[str, int] | None:
    base = os.environ.get("QUALITY_BASE_REF", "origin/main")
    result = run(["git", "show", f"{base}:{path.relative_to(ROOT)}"])
    if result.returncode != 0:
        return None
    data = json.loads(result.stdout)
    return {str(name): int(count) for name, count in data["files"].items()}


def verify_checksum() -> None:
    expected = CHECKSUM.read_text(encoding="utf-8").strip()
    actual = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit("quality ratchet script checksum mismatch")


def compare(tool: str, current: dict[str, int], path: Path) -> list[str]:
    baseline = load(path)
    failures: list[str] = []
    for name in sorted(set(current) | set(baseline)):
        now = current.get(name, 0)
        allowed = baseline.get(name, 0)
        if now > allowed:
            failures.append(f"{tool}: {name} has {now} errors, baseline is {allowed}")
        elif now < allowed:
            failures.append(
                f"{tool}: {name} improved from {allowed} to {now}; lower the baseline in this PR"
            )
    previous = base_payload(path)
    if previous is not None:
        for name, allowed in baseline.items():
            if allowed > previous.get(name, 0):
                failures.append(
                    f"{tool}: baseline grew for {name}: {previous.get(name, 0)} to {allowed}"
                )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()
    ruff = ruff_counts()
    mypy = mypy_counts()
    if args.write_baseline:
        QUALITY.mkdir(exist_ok=True)
        RUFF_BASELINE.write_text(json.dumps(payload(ruff), indent=2, sort_keys=True) + "\n")
        MYPY_BASELINE.write_text(json.dumps(payload(mypy), indent=2, sort_keys=True) + "\n")
        return 0
    verify_checksum()
    failures = compare("ruff", ruff, RUFF_BASELINE)
    failures.extend(compare("mypy", mypy, MYPY_BASELINE))
    if failures:
        print("\n".join(failures))
        return 1
    print(f"quality ratchet passed: Ruff {sum(ruff.values())}, mypy {sum(mypy.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

