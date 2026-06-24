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
    assert "workflow_run is not allowed" in source
    assert "scan_workflow_security_contract" in source
    assert "WORKFLOW_JOB_WRITE_PERMISSION_ALLOWLIST" in source
    assert "workflow-permission-write-unapproved" in source
    assert "DEPENDENCY_REVIEW_ACTION" in source
    assert "scan_dependency_review_workflow_contract" in source
    assert "dependency-review-severity" in source
    assert "dependency-review-pr-comments" in source
    assert "dependency-review-warn-only" in source
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
