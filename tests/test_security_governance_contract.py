from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts import security_governance_audit as audit


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_security_governance_doc_is_current_contract() -> None:
    source = _source("docs/security-governance.md")
    readme = _source("docs/README.md")
    roadmap = _source("docs/roadmaps/maturity-hardening.md")

    required_terms = (
        "Threat Model",
        "Local API And CORS",
        "Remote Runner Auth",
        "Secrets",
        "Diagnostics Redaction",
        "Dependency And Supply-Chain Gates",
        "Remote Operation Audit",
        "machine-readable policy catalog",
        "governance.operator_action.v1",
        "hash-chained governance audit events",
        "Release Checklist",
        "Scoped Runtime Limits",
        "known_hosts",
        "SSH_HOST_KEY_UNTRUSTED",
        "pip-audit",
        "Dependabot",
        "GitHub ruleset target policies",
        "main-branch ruleset",
        "Container Image Scan",
        "Trivy",
        "scripts/remote_exec.py",
        "0.0.0.0",
        "constant-time",
        "official npm registry",
    )
    for term in required_terms:
        assert term in source

    assert "security-governance.md" in readme
    assert "P0-10 Security Governance Criteria" in roadmap


def test_local_api_cors_stays_explicit_and_desktop_scoped() -> None:
    source = _source("apps/api/main.py")

    assert "CORSMiddleware" in source
    assert 'allow_origins=["*"]' not in source
    assert "allow_origin_regex" not in source
    assert 'allow_methods=["*"]' not in source
    assert 'allow_headers=["*"]' not in source
    assert 'allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]' in source
    assert 'allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id"]' in source
    assert '"http://127.0.0.1:3765"' in source
    assert '"tauri://localhost"' in source


def test_security_governance_audit_script_contract() -> None:
    source = _source("scripts/security_governance_audit.py")
    security_analysis_source = _source("scripts/security_analysis_governance.py")
    github_ruleset_source = _source("scripts/github_ruleset_governance.py")
    image_scan_source = _source("scripts/container_image_scan_governance.py")
    dependabot_source = _source("scripts/dependabot_governance.py")
    combined_source = source + "\n" + security_analysis_source + "\n" + github_ruleset_source + "\n" + image_scan_source

    assert "git" in source and "ls-files" in source
    assert "private-key-block" in source
    assert "aws-access-key-id" in source
    assert "github-token" in source
    assert "slack-token" in source
    assert "quoted-secret-assignment" in source
    assert "cors-wildcard" in source
    assert "dangerous-workflow-trigger" in source
    assert "unpinned-action" in source
    assert "MAX_WORKFLOW_ARTIFACT_RETENTION_DAYS = 2" in source
    assert "scan_workflow_artifact_retention" in source
    assert "workflow-artifact-retention-missing" in source
    assert "workflow-artifact-retention-too-long" in source
    assert "scan_workflow_checkout_credentials" in source
    assert "workflow-checkout-persist-credentials" in source
    assert "workflow_run is not allowed" in source
    assert "scan_workflow_security_contract" in source
    assert "WORKFLOW_JOB_WRITE_PERMISSION_ALLOWLIST" in source
    assert "workflow-permission-write-unapproved" in source
    assert "DEPENDENCY_REVIEW_ACTION" in source
    assert "SECURITY_ANALYSIS_WORKFLOW" in combined_source
    assert "CODEQL_ACTION_SHA" in combined_source
    assert "SCORECARD_ACTION_SHA" in combined_source
    assert "scan_dependency_review_workflow_contract" in source
    assert "scan_security_analysis_workflow_contract" in combined_source
    assert "dependency-review-severity" in source
    assert "dependency-review-pr-comments" in source
    assert "dependency-review-warn-only" in source
    assert "security-analysis-soft-fail" in combined_source
    assert "security-analysis-scorecard-permissions" in combined_source
    assert "_scan_scorecard_publish_job_restrictions" in combined_source
    assert "security-analysis-scorecard-job-restriction" in combined_source
    assert "security-analysis-scorecard-action-unapproved" in combined_source
    assert "security-analysis-scorecard-runner" in combined_source
    assert "scan_required_ci_security_analysis_contract" in combined_source
    assert "security-analysis-required-gate" in combined_source
    assert "dependabot_governance" in source
    assert "DEPENDABOT_REQUIRED_UPDATE_GROUPS" in dependabot_source
    assert "scan_dependabot_version_updates_contract" in source
    assert "dependabot-version-updates-missing" in dependabot_source
    assert "dependabot-update-schedule" in dependabot_source
    assert "dependabot-open-pr-limit" in dependabot_source
    assert "dependabot-update-group" in dependabot_source
    assert "dependabot-update-unapproved" in dependabot_source
    assert "github_ruleset_governance" in source
    assert "GITHUB_MAIN_BRANCH_RULESET" in combined_source
    assert "scan_github_main_branch_ruleset_contract" in combined_source
    assert "github-ruleset-status-checks" in combined_source
    assert "github-ruleset-optional-security-required" in combined_source
    assert "container_image_scan_governance" in source
    assert "CONTAINER_IMAGE_SCAN_POLICY" in combined_source
    assert "scan_container_image_scan_policy" in combined_source
    assert "container-image-scan-workflow-trigger" in combined_source
    assert "container-image-scan-policy-runtime-limit" in combined_source
    assert "ssh-auto-add-host-key" in source
    assert "ssh-host-key-reject-policy" in source
    assert "ssh-sha1-rsa-enabled" in source
    assert "scan_forbidden_security_text" in source
    assert "ssh-strict-host-key-checking-disabled" in source
    assert "ssh-known-hosts-file-disabled" in source
    assert "HIGH_RISK_API_POLICIES" in source
    assert "scan_governance_policy_contracts" in source
    assert "governance-policy-audit-action-missing" in source

    result = subprocess.run(
        [sys.executable, "scripts/security_governance_audit.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Security governance audit passed." in result.stdout


def test_security_governance_audit_rejects_unsafe_workflow_fixtures() -> None:
    unversioned_action = """
name: Unsafe
on:
  pull_request:
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout
"""
    write_on_pr = """
name: Unsafe Write
on:
  pull_request:
permissions:
  contents: read
jobs:
  publish:
    runs-on: ubuntu-24.04
    permissions:
      contents: write
    steps:
      - run: echo unsafe
"""
    workflow_run = """
name: Unsafe Trigger
on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]
permissions:
  contents: read
jobs:
  followup:
    runs-on: ubuntu-24.04
    steps:
      - run: echo unsafe
"""
    upload_artifact_missing_retention = """
name: Missing Retention
on:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  collect:
    runs-on: ubuntu-24.04
    steps:
      - name: Upload logs
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: logs
          path: logs/
"""
    upload_artifact_long_retention = """
name: Long Retention
on:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  collect:
    runs-on: ubuntu-24.04
    steps:
      - name: Upload logs
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: logs
          path: logs/
          retention-days: 14
"""
    upload_artifact_expression_retention = """
name: Dynamic Retention
on:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  collect:
    runs-on: ubuntu-24.04
    steps:
      - name: Upload logs
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: logs
          path: logs/
          retention-days: ${{ inputs.retention_days }}
"""
    dependency_review_warn_only = """
name: Dependency Review
"on":
  pull_request:
permissions:
  contents: read
jobs:
  dependency_review:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294
        with:
          fail-on-severity: high
          comment-summary-in-pr: on-failure
          warn-only: true
"""
    checkout_persist_credentials = """
name: Checkout Token
on:
  pull_request:
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
"""
    checkout_persist_credentials_true = """
name: Checkout Token True
on:
  pull_request:
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          persist-credentials: true
"""
    checkout_persist_credentials_env_spoof = """
name: Checkout Token Env Spoof
on:
  pull_request:
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        env:
          persist-credentials: false
"""
    security_analysis_soft_fail = """
name: Security Analysis
"on":
  push:
    branches:
      - main
  schedule:
    - cron: "34 3 * * 2"
  workflow_dispatch:
permissions:
  contents: read
jobs:
  codeql:
    runs-on: ubuntu-24.04
    permissions:
      contents: read
      security-events: write
    steps:
      - uses: github/codeql-action/init@8aad20d150bbac5944a9f9d289da16a4b0d87c1e
      - uses: github/codeql-action/analyze@8aad20d150bbac5944a9f9d289da16a4b0d87c1e
        continue-on-error: true
  scorecard:
    runs-on: ubuntu-24.04
    permissions:
      contents: read
      id-token: write
      security-events: write
    steps:
      - uses: ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a
        with:
          results_file: results.sarif
          results_format: sarif
          publish_results: false
"""
    security_analysis_pr_upload = """
name: Security Analysis
"on":
  pull_request:
permissions:
  contents: read
jobs:
  scorecard:
    runs-on: ubuntu-24.04
    permissions:
      contents: read
      id-token: write
      security-events: write
    steps:
      - uses: ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a
        with:
          results_file: results.sarif
          results_format: sarif
          publish_results: true
"""
    security_analysis_disallowed_scorecard_job = """
name: Security Analysis
"on":
  push:
    branches:
      - main
  schedule:
    - cron: "34 3 * * 2"
  workflow_dispatch:
permissions:
  contents: read
jobs:
  codeql:
    runs-on: ubuntu-24.04
    permissions:
      contents: read
      security-events: write
    steps:
      - uses: github/codeql-action/init@8aad20d150bbac5944a9f9d289da16a4b0d87c1e
        with:
          languages: python
          queries: +security-extended,security-and-quality
      - uses: github/codeql-action/analyze@8aad20d150bbac5944a9f9d289da16a4b0d87c1e
  scorecard:
    runs-on: ubuntu-24.04
    env:
      SCORECARD_EXAMPLE: unsafe
    container: ubuntu:24.04
    permissions:
      contents: read
      id-token: write
      security-events: write
    steps:
      - uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020
      - run: echo unsafe
      - uses: ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a
        with:
          results_file: results.sarif
          results_format: sarif
          publish_results: true
      - uses: github/codeql-action/upload-sarif@8aad20d150bbac5944a9f9d289da16a4b0d87c1e
        with:
          sarif_file: results.sarif
"""
    security_analysis_top_level_inline_env = """
name: Security Analysis
"on":
  push:
    branches:
      - main
  schedule:
    - cron: "34 3 * * 2"
  workflow_dispatch:
permissions:
  contents: read
env: {FOO: bar}
jobs:
  scorecard:
    runs-on: ubuntu-24.04
    permissions:
      contents: read
      id-token: write
      security-events: write
    steps:
      - uses: ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a
        with:
          results_file: results.sarif
          results_format: sarif
          publish_results: true
"""
    security_analysis_windows_scorecard = """
name: Security Analysis
"on":
  push:
    branches:
      - main
  schedule:
    - cron: "34 3 * * 2"
  workflow_dispatch:
permissions:
  contents: read
jobs:
  scorecard:
    runs-on: windows-2022
    permissions:
      contents: read
      id-token: write
      security-events: write
    steps:
      - uses: ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a
        with:
          results_file: results.sarif
          results_format: sarif
          publish_results: true
"""
    ci_with_required_scorecard = """
name: CI
"on":
  pull_request:
permissions:
  contents: read
jobs:
  scorecard:
    runs-on: ubuntu-24.04
    steps:
      - uses: ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a
  ci_green:
    needs: [scorecard]
    runs-on: ubuntu-24.04
    steps:
      - run: echo done
"""

    assert "unpinned-action" in _finding_codes(
        audit.scan_workflow_security_contract(".github/workflows/unsafe.yml", unversioned_action)
    )
    write_codes = _finding_codes(
        audit.scan_workflow_security_contract(".github/workflows/unsafe.yml", write_on_pr)
    )
    assert "workflow-permission-write-unapproved" in write_codes
    assert "workflow-write-permission-on-pr" in write_codes
    assert "dangerous-workflow-trigger" in _finding_codes(
        audit.scan_workflow_security_contract(".github/workflows/unsafe.yml", workflow_run)
    )
    assert "workflow-artifact-retention-missing" in _finding_codes(
        audit.scan_workflow_security_contract(
            ".github/workflows/unsafe.yml",
            upload_artifact_missing_retention,
        )
    )
    assert "workflow-artifact-retention-too-long" in _finding_codes(
        audit.scan_workflow_security_contract(
            ".github/workflows/unsafe.yml",
            upload_artifact_long_retention,
        )
    )
    assert "workflow-artifact-retention-invalid" in _finding_codes(
        audit.scan_workflow_security_contract(
            ".github/workflows/unsafe.yml",
            upload_artifact_expression_retention,
        )
    )
    dependency_review_codes = _finding_codes(
        audit.scan_workflow_security_contract(
            ".github/workflows/unsafe.yml",
            dependency_review_warn_only,
        )
    )
    assert "dependency-review-pr-only" in dependency_review_codes
    assert "dependency-review-severity" in dependency_review_codes
    assert "dependency-review-pr-comments" in dependency_review_codes
    assert "dependency-review-warn-only" in dependency_review_codes
    assert "workflow-checkout-persist-credentials" in _finding_codes(
        audit.scan_workflow_security_contract(
            ".github/workflows/unsafe.yml",
            checkout_persist_credentials,
        )
    )
    assert "workflow-checkout-persist-credentials" in _finding_codes(
        audit.scan_workflow_security_contract(
            ".github/workflows/unsafe.yml",
            checkout_persist_credentials_true,
        )
    )
    assert "workflow-checkout-persist-credentials" in _finding_codes(
        audit.scan_workflow_security_contract(
            ".github/workflows/unsafe.yml",
            checkout_persist_credentials_env_spoof,
        )
    )
    security_analysis_codes = _finding_codes(
        audit.scan_workflow_security_contract(
            ".github/workflows/security-analysis.yml",
            security_analysis_soft_fail,
        )
    )
    assert "security-analysis-soft-fail" in security_analysis_codes
    assert "security-analysis-scorecard-contract" in security_analysis_codes
    assert "security-analysis-codeql-contract" in security_analysis_codes
    assert "security-analysis-scorecard-contract" in _finding_codes(
        audit.scan_workflow_security_contract(
            ".github/workflows/security-analysis.yml",
            security_analysis_pr_upload,
        )
    )
    assert "security-analysis-untrusted-trigger" in _finding_codes(
        audit.scan_workflow_security_contract(
            ".github/workflows/security-analysis.yml",
            security_analysis_pr_upload,
        )
    )
    disallowed_scorecard_codes = _finding_codes(
        audit.scan_workflow_security_contract(
            ".github/workflows/security-analysis.yml",
            security_analysis_disallowed_scorecard_job,
        )
    )
    assert "security-analysis-scorecard-job-restriction" in disallowed_scorecard_codes
    assert "security-analysis-scorecard-action-unapproved" in disallowed_scorecard_codes
    assert any(
        finding.code == "security-analysis-scorecard-job-restriction"
        and "container" in finding.detail
        for finding in audit.scan_workflow_security_contract(
            ".github/workflows/security-analysis.yml",
            security_analysis_disallowed_scorecard_job,
        )
    )
    assert "security-analysis-workflow-restriction" in _finding_codes(
        audit.scan_workflow_security_contract(
            ".github/workflows/security-analysis.yml",
            security_analysis_top_level_inline_env,
        )
    )
    assert "security-analysis-scorecard-runner" in _finding_codes(
        audit.scan_workflow_security_contract(
            ".github/workflows/security-analysis.yml",
            security_analysis_windows_scorecard,
        )
    )
    assert "security-analysis-required-gate" in _finding_codes(
        audit.scan_workflow_security_contract(
            ".github/workflows/ci.yml",
            ci_with_required_scorecard,
        )
    )


def test_security_governance_audit_accepts_release_permission_allowlist() -> None:
    workflow = _source(".github/workflows/release-remote-runner-artifacts.yml")

    findings = audit.scan_workflow_security_contract(
        ".github/workflows/release-remote-runner-artifacts.yml",
        workflow,
    )

    assert [finding.format() for finding in findings] == []


def test_security_governance_audit_accepts_dependency_review_pr_gate() -> None:
    workflow = """
name: Dependency Review
"on":
  pull_request:
permissions:
  contents: read
jobs:
  dependency_review:
    name: security / dependency-review
    if: ${{ github.event_name == 'pull_request' }}
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          persist-credentials: false
      - uses: actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294
        with:
          fail-on-severity: moderate
          comment-summary-in-pr: never
"""

    findings = audit.scan_workflow_security_contract(
        ".github/workflows/dependency-review.yml",
        workflow,
    )

    assert [finding.format() for finding in findings] == []


def test_security_governance_audit_accepts_security_analysis_workflow() -> None:
    workflow = _source(".github/workflows/security-analysis.yml")

    findings = audit.scan_workflow_security_contract(
        ".github/workflows/security-analysis.yml",
        workflow,
    )

    assert [finding.format() for finding in findings] == []


def test_security_governance_audit_accepts_dependabot_version_updates() -> None:
    source = _source(".github/dependabot.yml")

    findings = audit.scan_dependabot_version_updates_contract(
        ".github/dependabot.yml",
        source,
    )

    assert [finding.format() for finding in findings] == []


def test_security_governance_audit_rejects_unsafe_dependabot_fixtures() -> None:
    missing_uv_and_no_group = """
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "daily"
    open-pull-requests-limit: 20
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
    groups:
      root-npm:
        patterns:
          - "*"
  - package-ecosystem: "npm"
    directory: "/apps/web"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
    groups:
      web-npm:
        patterns:
          - "*"
  - package-ecosystem: "npm"
    directory: "/apps/desktop"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
    groups:
      desktop-npm:
        patterns:
          - "*"
  - package-ecosystem: "cargo"
    directory: "/apps/desktop/src-tauri"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
    groups:
      desktop-cargo:
        patterns:
          - "*"
"""

    codes = _finding_codes(
        audit.scan_dependabot_version_updates_contract(
            ".github/dependabot.yml",
            missing_uv_and_no_group,
        )
    )

    assert "dependabot-version-updates-missing" in codes
    assert "dependabot-update-schedule" in codes
    assert "dependabot-open-pr-limit" in codes
    assert "dependabot-update-group" in codes
    assert "dependabot-update-unapproved" in codes


def test_docs_do_not_recommend_disabling_ssh_host_key_checks() -> None:
    docs = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "docs").rglob("*.md"))

    assert "StrictHostKeyChecking=" + "no" not in docs
    assert "UserKnownHostsFile=" + "/dev/null" not in docs


def test_debug_remote_exec_stays_out_of_launchers_and_ci() -> None:
    remote_exec_path = "scripts/remote_exec.py"
    checked_paths = [
        "run.bat",
        ".github/workflows/ci.yml",
        ".github/workflows/release-remote-runner-artifacts.yml",
        "scripts/run-web-dev.bat",
        "scripts/run-local-api-dev.bat",
        "scripts/run-desktop-dev.bat",
    ]

    for path in checked_paths:
        assert remote_exec_path not in _source(path)


def test_remote_runner_auth_and_deployment_security_contracts_are_locked() -> None:
    route_utils = _source("apps/remote_runner/route_utils.py")
    deployment = _source("core/deployment_mode.py")
    ssh_connector = _source("core/remote/ssh_connector.py")

    assert "import hmac" in route_utils
    assert 'scheme.lower() != "bearer"' in route_utils
    assert "hmac.compare_digest(" in route_utils
    assert "Desktop mode does not allow binding to 0.0.0.0" in deployment
    assert "server-single-user mode does not allow binding to 0.0.0.0" in deployment
    assert "H2OMETA_DEPLOYMENT_MODE is required" in deployment
    assert "Invalid H2OMETA_DEPLOYMENT_MODE" in deployment
    assert 'os.environ.get("H2OMETA_DEPLOYMENT_MODE", "desktop")' not in deployment
    assert "server-multi-user is not implemented" in deployment
    assert "require_supported_deployment_mode()" in _source("apps/api/lifespan.py")
    assert "validate_deployment_security()" in _source("apps/api/lifespan.py")
    assert "trusted intranet" not in deployment
    assert "AutoAddPolicy" not in ssh_connector
    assert "RejectPolicy" in ssh_connector
    assert "SSH_SHA1_DISABLED_ALGORITHMS" in ssh_connector
    assert "SSH_HOST_KEY_UNTRUSTED" in ssh_connector


def _finding_codes(findings: list[audit.Finding]) -> set[str]:
    return {finding.code for finding in findings}
