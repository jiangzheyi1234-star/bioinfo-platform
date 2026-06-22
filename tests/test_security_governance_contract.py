from __future__ import annotations

import subprocess
import sys
from pathlib import Path


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
