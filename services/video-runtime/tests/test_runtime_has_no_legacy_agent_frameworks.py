from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def _forbidden_packages() -> tuple[str, ...]:
    return ("deep" + "agents", "lang" + "graph", "lang" + "chain")


def test_runtime_has_no_forbidden_python_imports() -> None:
    forbidden = _forbidden_packages()
    violations: list[str] = []
    for path in [*APP.rglob("*.py"), *(ROOT / "prompts").rglob("*.py")]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if any(name == package or name.startswith(package + ".") for package in forbidden):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {name}")
    assert violations == []


def test_runtime_manifest_has_no_forbidden_dependencies_or_research_capability() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8").casefold()
    for package in _forbidden_packages():
        assert package not in project

    capability_id = "research" + ".generate"
    runtime_text = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (APP, ROOT / "plugins", ROOT / "skills")
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".yaml", ".yml", ".md"}
    )
    assert capability_id not in runtime_text
