"""The deterministic core imports nothing from the probabilistic / LLM layer.

Enforced statically by parsing every module under bazaar/verifier/ and rejecting
any import of the agent or intent packages. If someone ever blurs the boundary,
the build fails here.
"""
from __future__ import annotations

import ast
import pathlib

import bazaar

PKG_ROOT = pathlib.Path(bazaar.__file__).resolve().parent
FORBIDDEN_PREFIXES = ("bazaar.intent", "bazaar.agents", "bazaar.redteam")


def _imports_of(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_verifier_does_not_import_llm_layer():
    verifier_dir = PKG_ROOT / "verifier"
    offenders: list[str] = []
    for py in verifier_dir.rglob("*.py"):
        for imported in _imports_of(py):
            if imported.startswith(FORBIDDEN_PREFIXES):
                offenders.append(f"{py.name} imports {imported}")
    assert not offenders, f"deterministic core imports the LLM layer: {offenders}"


def test_risk_signal_cannot_be_the_authorizer():
    """The risk module must not import the gate (signals inform, they don't decide)."""
    risk_dir = PKG_ROOT / "risk"
    offenders: list[str] = []
    for py in risk_dir.rglob("*.py"):
        for imported in _imports_of(py):
            if imported.startswith("bazaar.verifier"):
                offenders.append(f"{py.name} imports {imported}")
    assert not offenders, f"risk layer imports the verifier: {offenders}"
