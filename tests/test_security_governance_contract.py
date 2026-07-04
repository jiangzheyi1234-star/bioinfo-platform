from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from scripts import security_governance_audit as audit
from scripts.security_governance_common import Finding


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _module_ast(path: str) -> ast.Module:
    return ast.parse(_source(path), filename=path)


def _defined_functions(tree: ast.Module) -> set[str]:
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


def _defined_classes(tree: ast.Module) -> set[str]:
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def _from_import_aliases(tree: ast.Module, module: str) -> dict[str, str | None]:
    aliases: dict[str, str | None] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == module:
            aliases.update({alias.name: alias.asname for alias in node.names})
    return aliases


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
    audit_tree = _module_ast("scripts/security_governance_audit.py")
    common_source = _source("scripts/security_governance_common.py")
    workflow_governance_source = _source("scripts/security_workflow_governance.py")
    workflow_governance_tree = _module_ast("scripts/security_workflow_governance.py")
    security_analysis_source = _source("scripts/security_analysis_governance.py")
    github_ruleset_source = _source("scripts/github_ruleset_governance.py")
    image_scan_source = _source("scripts/container_image_scan_governance.py")
    runtime_governance_source = _source("scripts/container_runtime_governance.py")
    dependabot_source = _source("scripts/dependabot_governance.py")
    combined_source = (
        source
        + "\n"
        + security_analysis_source
        + "\n"
        + github_ruleset_source
        + "\n"
        + image_scan_source
        + "\n"
        + runtime_governance_source
        + "\n"
        + common_source
        + "\n"
        + workflow_governance_source
    )

    assert "git" in source and "ls-files" in source
    assert "private-key-block" in source
    assert "aws-access-key-id" in source
    assert "github-token" in source
    assert "slack-token" in source
    assert "quoted-secret-assignment" in source
    assert "cors-wildcard" in source

    audit_functions = _defined_functions(audit_tree)
    audit_classes = _defined_classes(audit_tree)
    workflow_functions = _defined_functions(workflow_governance_tree)
    workflow_classes = _defined_classes(workflow_governance_tree)
    assert _from_import_aliases(audit_tree, "scripts.security_governance_common") == {
        "Finding": None,
        "line_number": None,
    }
    assert _from_import_aliases(audit_tree, "scripts.security_workflow_governance") == {
        "scan_workflow_security_contract": "_scan_workflow_security_contract",
    }
    assert {
        "scan_workflow_security_contract",
        "scan_workflow_artifact_retention",
        "scan_workflow_checkout_credentials",
        "scan_workflow_permissions",
        "scan_dependency_review_workflow_contract",
    }.isdisjoint(audit_functions)
    assert {
        "scan_workflow_security_contract",
        "scan_workflow_artifact_retention",
        "scan_workflow_checkout_credentials",
        "scan_workflow_permissions",
        "scan_dependency_review_workflow_contract",
    } <= workflow_functions
    assert "SimpleYamlMapping" not in audit_classes
    assert "SimpleYamlMapping" in workflow_classes

    assert "dangerous-workflow-trigger" in workflow_governance_source
    assert "unpinned-action" in workflow_governance_source
    assert "MAX_WORKFLOW_ARTIFACT_RETENTION_DAYS = 2" in workflow_governance_source
    assert "workflow-artifact-retention-missing" in workflow_governance_source
    assert "workflow-artifact-retention-too-long" in workflow_governance_source
    assert "workflow-checkout-persist-credentials" in workflow_governance_source
    assert "workflow_run is not allowed" in workflow_governance_source
    assert "WORKFLOW_JOB_WRITE_PERMISSION_ALLOWLIST" in workflow_governance_source
    assert "workflow-permission-write-unapproved" in workflow_governance_source
    assert "DEPENDENCY_REVIEW_ACTION" in workflow_governance_source
    assert "SECURITY_ANALYSIS_WORKFLOW" in combined_source
    assert "CODEQL_ACTION_SHA" in combined_source
    assert "SCORECARD_ACTION_SHA" in combined_source
    assert "scan_security_analysis_workflow_contract" in combined_source
    assert "dependency-review-severity" in workflow_governance_source
    assert "dependency-review-pr-comments" in workflow_governance_source
    assert "dependency-review-warn-only" in workflow_governance_source
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
    assert "container_runtime_governance" in source
    assert "CONTAINER_RUNTIME_HARDENING_POLICY" in combined_source
    assert "scan_container_runtime_hardening_policy" in combined_source
    assert "container-runtime-production-claim-unsafe" in combined_source
    assert "container-runtime-known-unsafe-missing" in combined_source
    assert "container-runtime-graduation-control-missing" in combined_source
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


def test_direct_governance_audit_append_paths_pass_actor_roles() -> None:
    remote_runner_root = ROOT / "apps" / "remote_runner"
    for path in remote_runner_root.rglob("*.py"):
        if path.name == "governance_audit.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "append_governance_audit_event(" not in source:
            continue
        assert "actor_roles=" in source, f"{path.relative_to(ROOT)} must pass actor_roles to direct audit append"


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
    assert "production-governance-readiness.v1" in deployment
    assert "databaseUrlSignalPresent" in deployment
    assert "credentialPairConfigured" in deployment
    assert "server-multi-user is not implemented" in deployment
    assert "require_supported_deployment_mode()" in _source("apps/api/lifespan.py")
    assert "validate_deployment_security()" in _source("apps/api/lifespan.py")
    assert "build_production_governance_readiness()" in _source("apps/api/system_service.py")
    assert "trusted intranet" not in deployment
    assert "AutoAddPolicy" not in ssh_connector
    assert "RejectPolicy" in ssh_connector
    assert "SSH_SHA1_DISABLED_ALGORITHMS" in ssh_connector
    assert "SSH_HOST_KEY_UNTRUSTED" in ssh_connector


def _finding_codes(findings: list[Finding]) -> set[str]:
    return {finding.code for finding in findings}
