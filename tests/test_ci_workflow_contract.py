from __future__ import annotations

import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
SECURITY_ANALYSIS_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "security-analysis.yml"


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
    assert "DEPENDENCY_REVIEW_RESULT: ${{ needs.dependency_review.result }}" in source
    assert "WEB_WINDOWS_RESULT: ${{ needs.web_windows.result }}" in source
    assert "LINUX_PARITY_SMOKE_RESULT: ${{ needs.linux_parity_smoke.result }}" in source
    assert "- security_governance" in source
    assert "- dependency_review" in source
    assert "security-governance:${SECURITY_GOVERNANCE_RESULT}" in source
    assert "dependency-review:${DEPENDENCY_REVIEW_RESULT}" in source
    assert "CODEQL_RESULT" not in source
    assert "SCORECARD_RESULT" not in source
    assert "security / codeql" not in source
    assert "security / scorecard" not in source


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
    assert "uv export --frozen --group dev --format requirements-txt" in source
    assert "uvx pip-audit" in source
    assert re.findall(r"--ignore-vuln\s+([A-Z0-9-]+)", source) == ["CVE-2026-44405"]

    audit_commands = re.findall(
        r"run: (npm audit --registry=https://registry\.npmjs\.org --audit-level=\w+ --package-lock-only(?: --omit=dev)?)",
        source,
    )
    assert audit_commands == [
        "npm audit --registry=https://registry.npmjs.org --audit-level=moderate --package-lock-only",
        "npm audit --registry=https://registry.npmjs.org --audit-level=moderate --package-lock-only",
        "npm audit --registry=https://registry.npmjs.org --audit-level=moderate --package-lock-only",
    ]
    assert "working-directory: apps/web" in source
    assert "working-directory: apps/desktop" in source

    security_doc = (REPOSITORY_ROOT / "docs" / "security-governance.md").read_text(
        encoding="utf-8"
    )
    assert "CVE-2026-44405" in security_doc
    assert "Remove this ignore when" in security_doc


def test_ci_workflow_runs_dependency_review_as_pr_only_gate() -> None:
    source = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "dependency_review:" in source
    assert "name: security / dependency-review" in source
    assert "if: ${{ github.event_name == 'pull_request' }}" in source
    assert (
        "actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294"
        in source
    )
    assert "fail-on-severity: moderate" in source
    assert "comment-summary-in-pr: never" in source
    assert "pull-requests: write" not in source


def test_security_analysis_workflow_is_optional_and_governed() -> None:
    ci_source = CI_WORKFLOW.read_text(encoding="utf-8")
    source = SECURITY_ANALYSIS_WORKFLOW.read_text(encoding="utf-8")

    assert "name: Security Analysis" in source
    assert "push:" in source
    assert "schedule:" in source
    assert "workflow_dispatch:" in source
    assert "pull_request:" not in source
    assert "merge_group:" not in source
    assert "workflow_run:" not in source
    assert "permissions:\n  contents: read" in source
    assert "name: security / codeql" in source
    assert "name: security / scorecard" in source
    assert "github/codeql-action/init@8aad20d150bbac5944a9f9d289da16a4b0d87c1e" in source
    assert "github/codeql-action/analyze@8aad20d150bbac5944a9f9d289da16a4b0d87c1e" in source
    assert "github/codeql-action/upload-sarif@8aad20d150bbac5944a9f9d289da16a4b0d87c1e" in source
    assert "ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a" in source
    assert "queries: +security-extended,security-and-quality" in source
    assert "results_file: results.sarif" in source
    assert "results_format: sarif" in source
    assert "publish_results: true" in source
    assert "security-events: write" in source
    assert "id-token: write" in source
    assert "continue-on-error" not in source
    assert "security-analysis" not in ci_source


def test_ci_workflow_uses_sha_pinned_actions() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((REPOSITORY_ROOT / ".github" / "workflows").glob("*.yml"))
    )
    uses_specs = re.findall(r"^\s*(?:-\s*)?uses:\s+([^\s#]+)", source, flags=re.MULTILINE)
    uses_lines = re.findall(r"uses:\s+[^@\s]+@([^\s#]+)", source)

    assert uses_specs
    assert all(spec.startswith("./") or "@" in spec for spec in uses_specs)
    assert uses_lines
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in uses_lines)


def test_workflow_checkouts_do_not_persist_github_token_credentials() -> None:
    for path in sorted((REPOSITORY_ROOT / ".github" / "workflows").glob("*.yml")):
        source = path.read_text(encoding="utf-8")
        checkout_count = source.count("actions/checkout@")

        assert checkout_count == source.count("persist-credentials: false"), path


def test_dependabot_updates_cover_managed_dependency_surfaces() -> None:
    source = (REPOSITORY_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")

    assert "version: 2" in source
    assert 'package-ecosystem: "github-actions"' in source
    assert 'package-ecosystem: "uv"' in source
    assert source.count('package-ecosystem: "npm"') == 3
    assert 'directory: "/"' in source
    assert 'directory: "/apps/web"' in source
    assert 'directory: "/apps/desktop"' in source
    assert source.count('interval: "weekly"') == 5
    assert source.count("open-pull-requests-limit: 5") == 5
    for group in ("github-actions", "python-uv", "root-npm", "web-npm", "desktop-npm"):
        assert f"      {group}:" in source
    assert source.count('          - "*"') == 5


def test_workflow_upload_artifacts_are_short_lived_handoff_files() -> None:
    for path in sorted((REPOSITORY_ROOT / ".github" / "workflows").glob("*.yml")):
        source = path.read_text(encoding="utf-8")
        upload_count = source.count("actions/upload-artifact@")
        retentions = [int(value) for value in re.findall(r"retention-days:\s*(\d+)", source)]

        assert "retention-days: 14" not in source
        if upload_count:
            assert len(retentions) == upload_count, path
            assert all(1 <= days <= 2 for days in retentions), path


def test_workflows_do_not_use_privileged_untrusted_pr_triggers() -> None:
    for path in sorted((REPOSITORY_ROOT / ".github" / "workflows").glob("*.yml")):
        source = path.read_text(encoding="utf-8")
        assert "pull_request_target:" not in source
        assert "workflow_run:" not in source


def test_release_workflows_keep_write_permissions_explicit_and_narrow() -> None:
    release = (REPOSITORY_ROOT / ".github" / "workflows" / "release-remote-runner-artifacts.yml").read_text(
        encoding="utf-8"
    )
    register = (
        REPOSITORY_ROOT / ".github" / "workflows" / "register-remote-runner-release-gate-evidence.yml"
    ).read_text(encoding="utf-8")
    promote = (REPOSITORY_ROOT / ".github" / "workflows" / "promote-remote-runner-release.yml").read_text(
        encoding="utf-8"
    )

    assert "release_gate_evidence_run_id:" not in release
    assert "release_gate_evidence_artifact:" not in release
    assert "release_gate_evidence_artifact:" in register
    assert "release_gate_evidence_run_id:" in promote

    assert "permissions:\n  contents: read" in release
    assert "      id-token: write" in release
    assert "      attestations: write" in release
    assert "      artifact-metadata: write" in release
    assert "      contents: write" in release
    assert "permissions:\n  contents: read\n  actions: read" in register
    assert "permissions:\n  contents: read\n  actions: read" in promote


def test_codeowners_covers_security_sensitive_automation() -> None:
    source = (REPOSITORY_ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")

    assert "/.github/workflows/ @jiangzheyi1234-star" in source
    assert "/.github/container-image-scan.target.json @jiangzheyi1234-star" in source
    assert "/.github/container-runtime-hardening.target.json @jiangzheyi1234-star" in source
    assert "/.github/rulesets/ @jiangzheyi1234-star" in source
    assert "/.github/dependabot.yml @jiangzheyi1234-star" in source
    assert "/scripts/container_image_scan_governance.py @jiangzheyi1234-star" in source
    assert "/scripts/container_runtime_governance.py @jiangzheyi1234-star" in source
    assert "/scripts/dependabot_governance.py @jiangzheyi1234-star" in source
    assert "/scripts/github_ruleset_governance.py @jiangzheyi1234-star" in source
    assert "/scripts/security_governance_audit.py @jiangzheyi1234-star" in source
    assert "/scripts/security_analysis_governance.py @jiangzheyi1234-star" in source
    assert "/core/governance_policy.py @jiangzheyi1234-star" in source
