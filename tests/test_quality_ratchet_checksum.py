"""The quality ratchet implementation is pinned byte for byte."""

from hashlib import sha256
from pathlib import Path


def test_quality_ratchet_checksum() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = (root / "quality" / "quality-ratchet.sha256").read_text().strip()
    actual = sha256((root / "tools" / "quality_ratchet.py").read_bytes()).hexdigest()
    assert actual == expected
