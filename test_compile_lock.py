"""The lock check must fail for changes here, and not for releases elsewhere.

WP-5 added `python scripts/compile_lock.py --check` as a continuous-integration
gate. It went red the next day on a pull request that touched no dependency at
all: `platformdirs` had published 4.11.11, and the script compiled into an empty
temporary directory, so `uv pip compile` had no existing output file to take pins
from and re-resolved every unpinned transitive dependency to whatever the index
held that minute.

That is a gate on the state of PyPI rather than on the commit. It fails on other
people's releases, on unrelated branches, and the only way to make it pass is to
accept an upgrade nobody asked for in a pull request about something else. A gate
that goes red for reasons outside the change trains people to ignore it.

These tests pin the behaviour both ways: an upstream release must not move the
lock, and a change to `requirements.txt` must.

Run: pytest -q test_compile_lock.py
"""

from __future__ import annotations

import pathlib
import shutil
import sys

import pytest

# The script lives in scripts/, which is not a package and not on the path.
sys.path.insert(0, str(pathlib.Path(__file__).parent / "scripts"))

compile_lock_module = pytest.importorskip("compile_lock")

pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None, reason="uv is not installed; the lock gate needs it"
)

ROOT = pathlib.Path(__file__).parent


@pytest.fixture()
def lock_at(tmp_path, monkeypatch):
    """Point the script at a copy of the lock, so tests never rewrite the real one."""

    def _place(content: str) -> pathlib.Path:
        path = tmp_path / "requirements.lock.txt"
        path.write_text(content, encoding="utf-8")
        monkeypatch.setattr(compile_lock_module, "LOCK", path)
        return path

    return _place


def _pin(lock: str, package: str) -> str | None:
    for line in lock.splitlines():
        if line.startswith(f"{package}=="):
            return line.strip()
    return None


def test_an_existing_pin_is_held_rather_than_re_resolved(lock_at) -> None:
    """The regression. A pin already in the lock survives a plain compile.

    Written against a real pin rather than a mock: the failure was a missing file
    on disk, which a mocked resolver would not have reproduced.
    """
    current = (ROOT / "requirements.lock.txt").read_text(encoding="utf-8")
    held = _pin(current, "platformdirs")
    assert held, "platformdirs is no longer in the lock; pick another transitive pin"

    lock_at(current)
    recompiled = compile_lock_module.compile_lock()

    assert _pin(recompiled, "platformdirs") == held, (
        "a transitive pin moved without being asked to; the compile is resolving "
        "against the index rather than against the existing lock"
    )


def test_upgrade_is_available_and_deliberate(lock_at) -> None:
    """Holding pins is only defensible if there is a way to move them."""
    current = (ROOT / "requirements.lock.txt").read_text(encoding="utf-8")
    lock_at(current)
    import inspect

    signature = inspect.signature(compile_lock_module.compile_lock)
    assert "upgrade" in signature.parameters, "there is no way to move a pin on purpose"


def test_a_changed_requirement_still_fails_the_check(lock_at, monkeypatch) -> None:
    """The gate must still do the job it was added for."""
    current = (ROOT / "requirements.lock.txt").read_text(encoding="utf-8")
    lock_at(current)

    requirements = ROOT / "requirements.txt"
    original = requirements.read_text(encoding="utf-8")
    try:
        requirements.write_text(original + "\ntabulate==0.9.0\n", encoding="utf-8")
        recompiled = compile_lock_module.compile_lock()
        assert _pin(recompiled, "tabulate"), (
            "a requirement added to requirements.txt did not reach the lock, so "
            "--check would not have noticed it"
        )
        assert recompiled != current, "--check cannot fail on a real change"
    finally:
        requirements.write_text(original, encoding="utf-8")


def test_the_lock_on_disk_is_what_the_script_would_write(lock_at) -> None:
    """`--check` in a test, so a stale lock is caught before continuous integration."""
    current = (ROOT / "requirements.lock.txt").read_text(encoding="utf-8")
    lock_at(current)
    assert compile_lock_module.compile_lock() == current, (
        "requirements.lock.txt is out of date; run python scripts/compile_lock.py"
    )
