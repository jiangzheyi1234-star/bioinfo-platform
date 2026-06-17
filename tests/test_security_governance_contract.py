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
        "Release Checklist",
        "Accepted P0-10 Risks",
        "SSH host-key trust",
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

    result = subprocess.run(
        [sys.executable, "scripts/security_governance_audit.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Security governance audit passed." in result.stdout


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

    assert "import hmac" in route_utils
    assert 'scheme.lower() != "bearer"' in route_utils
    assert "hmac.compare_digest(" in route_utils
    assert "Desktop mode does not allow binding to 0.0.0.0" in deployment
    assert "trusted intranet" in deployment
