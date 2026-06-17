from __future__ import annotations

import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_workflow_provides_required_mainline_gates() -> None:
    source = CI_WORKFLOW.read_text(encoding="utf-8")

    assert '"on":' in source
    assert "pull_request:" in source
    assert "push:" in source
    assert "merge_group:" in source
    assert "workflow_dispatch:" in source
    assert "permissions:\n  contents: read" in source
    assert "name: required / ci-green" in source
    assert "DIFF_HYGIENE_RESULT: ${{ needs.diff_hygiene.result }}" in source
    assert "PYTHON_WINDOWS_RESULT: ${{ needs.python_windows.result }}" in source
    assert "SECURITY_GOVERNANCE_RESULT: ${{ needs.security_governance.result }}" in source
    assert "WEB_WINDOWS_RESULT: ${{ needs.web_windows.result }}" in source
    assert "LINUX_PARITY_SMOKE_RESULT: ${{ needs.linux_parity_smoke.result }}" in source
    assert "- security_governance" in source
    assert "security-governance:${SECURITY_GOVERNANCE_RESULT}" in source


def test_ci_workflow_runs_locked_python_and_web_quality_gates() -> None:
    source = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "uv sync --frozen --group dev" in source
    assert 'Join-Path $env:RUNNER_TEMP "uv-cache"' in source
    assert 'export UV_CACHE_DIR="$RUNNER_TEMP/uv-cache"' in source
    assert "uv run --frozen ruff check apps core scripts tests" in source
    assert "uv run --frozen python -m pytest -q" in source
    assert "npm ci" in source
    assert "npm run lint" in source
    assert "npm run typecheck" in source
    assert "npm run build" in source
    assert "NEXT_TELEMETRY_DISABLED" in source


def test_ci_workflow_runs_security_governance_gate() -> None:
    source = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "name: security / governance" in source
    assert "npm_config_registry: https://registry.npmjs.org" in source
    assert "python scripts/security_governance_audit.py" in source
    assert "npm audit --registry=https://registry.npmjs.org --audit-level=high --package-lock-only --omit=dev" in source
    assert "working-directory: apps/web" in source


def test_ci_workflow_uses_sha_pinned_actions() -> None:
    source = CI_WORKFLOW.read_text(encoding="utf-8")
    uses_lines = re.findall(r"uses:\s+[^@\s]+@([^\s#]+)", source)

    assert uses_lines
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in uses_lines)
