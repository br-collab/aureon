import importlib.metadata
import re
from pathlib import Path

from server import CANONICAL_DOCTRINE_VERSION, app


ROOT = Path(__file__).resolve().parents[1]


def test_versions_endpoint_reports_installed_and_canonical_versions():
    response = app.test_client().get("/api/versions")

    assert response.status_code == 200
    assert response.content_type == "application/json"
    payload = response.get_json()
    assert payload["atreides"] == importlib.metadata.version("atreides")
    assert payload["doctrine"] == CANONICAL_DOCTRINE_VERSION


def test_pages_do_not_embed_stale_atreides_or_doctrine_fallbacks():
    for filename in ("index.html", "atreides-settlement-dashboard.html"):
        page = (ROOT / filename).read_text(encoding="utf-8")
        assert not re.search(r"Atreides.{0,120}v0\.\d+\.\d+", page, re.IGNORECASE)
        assert "'1.2'" not in page
        assert "'1.3'" not in page


def test_readme_atreides_pin_matches_requirements():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    pin_pattern = r"atreides\s*@\s*git\+https://github\.com/br-collab/Project-Atreides\.git@(v\d+\.\d+\.\d+)"

    readme_pin = re.search(pin_pattern, readme)
    requirements_pin = re.search(pin_pattern, requirements)
    assert readme_pin is not None
    assert requirements_pin is not None
    assert readme_pin.group(1) == requirements_pin.group(1)


def test_readme_uses_canonical_cato_repository_name():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Cato---FICC-MCP" not in readme


def test_documented_cato_version_is_read_from_the_python_twin_source():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    doctrine_stack = readme.splitlines()[2]
    source = (ROOT / "aureon/mcp/cato_client.py").read_text(encoding="utf-8")
    source_version = re.search(r'^CATO_DOCTRINE_VERSION = "([^"]+)"$', source, re.MULTILINE)

    assert source_version is not None
    assert f"Cato Sec v{source_version.group(1)}" in doctrine_stack
    assert "XRPL divergence retired" in doctrine_stack
