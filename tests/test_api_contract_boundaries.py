from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def test_api_package_does_not_import_remote_runner_modules() -> None:
    offenders: dict[str, list[str]] = {}
    for path in sorted((ROOT / "apps" / "api").rglob("*.py")):
        imported = [
            module
            for module in _imported_modules(path)
            if module == "apps.remote_runner" or module.startswith("apps.remote_runner.")
        ]
        if imported:
            offenders[path.relative_to(ROOT).as_posix()] = sorted(set(imported))

    assert offenders == {}


def test_api_models_do_not_import_remote_runner_contracts() -> None:
    sys.modules.pop("apps.api.models", None)
    sys.modules.pop("apps.remote_runner.workflow_design_contract", None)

    imports = _imported_modules(ROOT / "apps/api/models.py")

    assert "apps.remote_runner.workflow_design_contract" not in imports

    import apps.api.models  # noqa: F401

    assert "apps.remote_runner.workflow_design_contract" not in sys.modules
