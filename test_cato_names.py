"""Current Aureon surfaces distinguish Cato Sec from Cato Cash."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent


def test_current_surfaces_use_canonical_cato_names() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    server = (ROOT / "server.py").read_text(encoding="utf-8")

    assert "Cato Sec (`cato_sec`)" in readme
    assert "Cato Cash (`cato_cash`)" in readme
    assert "Cato Sec (`cato_sec`)" in claude
    assert "Cato Cash (`cato_cash`)" in claude
    assert "Cato Sec — Verana L0 Settlement Gate" in index
    assert "Cato Cash — the cash settlement-rail gate" in server

    retired_label = "CATO" + "-F"
    for text in (readme, claude, index, server):
        assert retired_label not in text


def test_cato_sec_user_agent_is_token_safe() -> None:
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "Aureon-Cato-Sec/" in server
    assert "Aureon-Cato Sec/" not in server
