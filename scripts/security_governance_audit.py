from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core.governance_policy import HIGH_RISK_API_POLICIES, validate_governance_policy  # noqa: E402
from scripts.container_image_scan_governance import CONTAINER_IMAGE_SCAN_POLICY, CONTAINER_IMAGE_SCAN_WORKFLOW, scan_container_image_scan_policy as _scan_container_image_scan_policy  # noqa: E402
from scripts.container_runtime_governance import (  # noqa: E402
    API_DOCKERFILE,
    COMPOSE_FILE,
    CONTAINER_RUNTIME_HARDENING_POLICY,
    WEB_DOCKERFILE,
    scan_container_runtime_hardening_policy as _scan_container_runtime_hardening_policy,
)
from scripts.dependabot_governance import scan_dependabot_version_updates_contract as _scan_dependabot_version_updates_contract  # noqa: E402
from scripts.github_ruleset_governance import GITHUB_MAIN_BRANCH_RULESET, scan_github_main_branch_ruleset_contract as _scan_github_main_branch_ruleset_contract  # noqa: E402
from scripts.security_analysis_governance import SECURITY_ANALYSIS_WORKFLOW  # noqa: E402
from scripts.security_governance_common import Finding, line_number  # noqa: E402
from scripts.security_workflow_governance import scan_workflow_security_contract as _scan_workflow_security_contract  # noqa: E402
MAX_TEXT_BYTES = 2_000_000

SECRET_PATH_RE = re.compile(
    r"(^|/)(\.env($|\.)|id_rsa$|id_dsa$|id_ecdsa$|id_ed25519$|.*\.(pem|p12|pfx|key)$)",
    re.IGNORECASE,
)
SKIP_PATH_PARTS = {
    ".git",
    ".next",
    ".venv",
    ".venv-win",
    "node_modules",
    "__pycache__",
}
PLACEHOLDER_RE = re.compile(
    r"(example|placeholder|dummy|sample|test|phase|canary|redacted|"
    r"runner://|\$\{\{|<[^>]+>|your-|changeme|not-a-secret)",
    re.IGNORECASE,
)
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private-key-block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("aws-access-key-id", re.compile(r"\bA[KS]IA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{30,}\b")),
    ("github-fine-grained-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{80,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    (
        "quoted-secret-assignment",
        re.compile(
            r"(?i)\b(secret|token|password|api[_-]?key|auth[_-]?secret|private[_-]?key)\b"
            r"\s*[:=]\s*[\"']([^\"'\n]{16,})[\"']"
        ),
    ),
)
FORBIDDEN_SECURITY_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "ssh-strict-host-key-checking-disabled",
        re.compile(r"StrictHostKeyChecking\s*=\s*n[oO]\b", re.IGNORECASE),
        "docs and source must not instruct operators to disable SSH host-key checking",
    ),
    (
        "ssh-known-hosts-file-disabled",
        re.compile(r"UserKnownHostsFile\s*=\s*/dev/null\b", re.IGNORECASE),
        "docs and source must not bypass SSH known_hosts verification",
    ),
)
CODEOWNERS_REQUIRED_MARKERS = (
    "/.github/container-image-scan.target.json",
    "/.github/container-runtime-hardening.target.json",
    "/.github/rulesets/",
    "/.github/workflows/",
    "/.github/dependabot.yml",
    "/scripts/container_image_scan_governance.py",
    "/scripts/container_runtime_governance.py",
    "/scripts/dependabot_governance.py",
    "/scripts/github_ruleset_governance.py",
    "/scripts/security_governance_audit.py",
    "/scripts/security_governance_common.py",
    "/scripts/security_workflow_governance.py",
    "/scripts/security_analysis_governance.py",
    "/core/governance_policy.py",
)

def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=False,
    )
    paths: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8")
        path = ROOT / relative
        if any(part in SKIP_PATH_PARTS for part in Path(relative).parts):
            continue
        paths.append(path)
    return paths


def read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def is_placeholder(value: str, path: str) -> bool:
    if PLACEHOLDER_RE.search(value):
        return True
    if path.startswith("tests/") and re.search(r"(token|secret|password|key)", value, re.IGNORECASE):
        return True
    return False


def scan_secrets(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        if SECRET_PATH_RE.search(relative) and not relative.endswith((".env.example", ".example")):
            findings.append(Finding("tracked-secret-path", relative, 0, "tracked secret-like file path"))

        text = read_text(path)
        if text is None:
            continue
        for code, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(2) if code == "quoted-secret-assignment" else match.group(0)
                if is_placeholder(value, relative):
                    continue
                findings.append(
                    Finding(
                        code,
                        relative,
                        line_number(text, match.start()),
                        "potential committed secret; use a placeholder or secret store",
                    )
                )
    return findings


def scan_security_contracts() -> list[Finding]:
    findings: list[Finding] = []
    api_main = (ROOT / "apps" / "api" / "main.py").read_text(encoding="utf-8")
    if 'allow_origins=["*"]' in api_main or "allow_origin_regex" in api_main:
        findings.append(Finding("cors-wildcard", "apps/api/main.py", 0, "local API CORS must use explicit origins"))
    if 'allow_methods=["*"]' in api_main:
        findings.append(Finding("cors-method-wildcard", "apps/api/main.py", 0, "CORS methods must be explicit"))
    if 'allow_headers=["*"]' in api_main:
        findings.append(Finding("cors-header-wildcard", "apps/api/main.py", 0, "CORS headers must be explicit"))

    ssh_connector = (ROOT / "core" / "remote" / "ssh_connector.py").read_text(encoding="utf-8")
    if "AutoAddPolicy" in ssh_connector:
        findings.append(
            Finding(
                "ssh-auto-add-host-key",
                "core/remote/ssh_connector.py",
                0,
                "SSH must not auto-trust unknown host keys",
            )
        )
    if "RejectPolicy" not in ssh_connector:
        findings.append(
            Finding(
                "ssh-host-key-reject-policy",
                "core/remote/ssh_connector.py",
                0,
                "SSH clients must reject unknown host keys by default",
            )
        )
    if "SSH_SHA1_DISABLED_ALGORITHMS" not in ssh_connector or '"ssh-rsa"' not in ssh_connector:
        findings.append(
            Finding(
                "ssh-sha1-rsa-enabled",
                "core/remote/ssh_connector.py",
                0,
                "Paramiko must disable SHA1 RSA ssh-rsa host/user key algorithms",
            )
        )

    workflow_root = ROOT / ".github" / "workflows"
    security_analysis = workflow_root / "security-analysis.yml"
    if not security_analysis.exists():
        findings.append(
            Finding(
                "security-analysis-workflow-missing",
                SECURITY_ANALYSIS_WORKFLOW,
                0,
                "CodeQL and Scorecard optional analysis workflow must be present and governed",
            )
        )
    for workflow in workflow_root.glob("*.yml"):
        source = workflow.read_text(encoding="utf-8")
        relative = workflow.relative_to(ROOT).as_posix()
        findings.extend(_scan_workflow_security_contract(relative, source))
    ruleset_path = ROOT / GITHUB_MAIN_BRANCH_RULESET
    ruleset_source = ruleset_path.read_text(encoding="utf-8") if ruleset_path.exists() else ""
    for item in _scan_github_main_branch_ruleset_contract(GITHUB_MAIN_BRANCH_RULESET, ruleset_source):
        findings.append(Finding(item.code, item.path, item.line, item.detail))
    policy_path = ROOT / CONTAINER_IMAGE_SCAN_POLICY
    policy_source = policy_path.read_text(encoding="utf-8") if policy_path.exists() else ""
    workflow_source = (ROOT / CONTAINER_IMAGE_SCAN_WORKFLOW).read_text(encoding="utf-8") if (ROOT / CONTAINER_IMAGE_SCAN_WORKFLOW).exists() else ""
    for item in _scan_container_image_scan_policy(CONTAINER_IMAGE_SCAN_POLICY, policy_source, workflow_source):
        findings.append(Finding(item.code, item.path, item.line, item.detail))
    runtime_policy_path = ROOT / CONTAINER_RUNTIME_HARDENING_POLICY
    runtime_policy_source = runtime_policy_path.read_text(encoding="utf-8") if runtime_policy_path.exists() else ""
    compose_source = (ROOT / COMPOSE_FILE).read_text(encoding="utf-8") if (ROOT / COMPOSE_FILE).exists() else ""
    api_dockerfile_source = (ROOT / API_DOCKERFILE).read_text(encoding="utf-8") if (ROOT / API_DOCKERFILE).exists() else ""
    web_dockerfile_source = (ROOT / WEB_DOCKERFILE).read_text(encoding="utf-8") if (ROOT / WEB_DOCKERFILE).exists() else ""
    for item in _scan_container_runtime_hardening_policy(
        CONTAINER_RUNTIME_HARDENING_POLICY,
        runtime_policy_source,
        compose_source,
        api_dockerfile_source,
        web_dockerfile_source,
    ):
        findings.append(Finding(item.code, item.path, item.line, item.detail))
    codeowners = ROOT / ".github" / "CODEOWNERS"
    if not codeowners.exists():
        findings.append(Finding("codeowners-missing", ".github/CODEOWNERS", 0, "security-sensitive automation requires CODEOWNERS"))
    else:
        source = codeowners.read_text(encoding="utf-8")
        for marker in CODEOWNERS_REQUIRED_MARKERS:
            if marker not in source:
                findings.append(Finding("codeowners-incomplete", ".github/CODEOWNERS", 0, f"CODEOWNERS missing {marker}"))

    dependabot = ROOT / ".github" / "dependabot.yml"
    if not dependabot.exists():
        findings.append(
            Finding(
                "dependabot-version-updates-missing",
                ".github/dependabot.yml",
                0,
                "Dependabot version updates must cover managed dependency surfaces",
            )
        )
    else:
        findings.extend(
            scan_dependabot_version_updates_contract(
                dependabot.relative_to(ROOT).as_posix(),
                dependabot.read_text(encoding="utf-8"),
            )
        )
    return findings


def scan_dependabot_version_updates_contract(relative: str, source: str) -> list[Finding]:
    return [
        Finding(item.code, item.path, item.line, item.detail)
        for item in _scan_dependabot_version_updates_contract(relative, source)
    ]


def scan_governance_policy_contracts(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for error in validate_governance_policy():
        findings.append(Finding("governance-policy-invalid", "core/governance_policy.py", 0, error))

    tracked_texts: dict[str, str] = {}
    for path in paths:
        text = read_text(path)
        if text is None:
            continue
        tracked_texts[path.relative_to(ROOT).as_posix()] = text

    implementation_text = "\n".join(
        text for relative, text in tracked_texts.items() if relative.startswith("apps/remote_runner/")
    )
    for policy in HIGH_RISK_API_POLICIES:
        route_source = tracked_texts.get(policy.route_source)
        if route_source is None:
            findings.append(
                Finding(
                    "governance-policy-route-source-missing",
                    policy.route_source,
                    0,
                    f"{policy.key} references a missing or unreadable route source",
                )
            )
            continue
        if f'"{policy.route}"' not in route_source:
            findings.append(
                Finding(
                    "governance-policy-route-missing",
                    policy.route_source,
                    0,
                    f"{policy.key} route is not declared in its source file",
                )
            )
        route_decorator = "websocket" if policy.method == "WEBSOCKET" else policy.method.lower()
        if f"@router.{route_decorator}(" not in route_source:
            findings.append(
                Finding(
                    "governance-policy-route-method-missing",
                    policy.route_source,
                    0,
                    f"{policy.key} method decorator is not present",
                )
            )
        if policy.audit_status == "implemented" and f'action="{policy.action}"' not in implementation_text:
            findings.append(
                Finding(
                    "governance-policy-audit-action-missing",
                    "core/governance_policy.py",
                    0,
                    f"{policy.key} is marked implemented but {policy.action} is not recorded",
                )
            )
        if (
            policy.surface == "remote-runner-api"
            and policy.audit_status == "implemented"
            and not re.search(
                rf"(?:authorized_config|_authorized_config_from_request)\([^)]*action=\"{re.escape(policy.action)}\"",
                implementation_text,
            )
        ):
            findings.append(
                Finding(
                    "governance-policy-authz-action-missing",
                    "core/governance_policy.py",
                    0,
                    f"{policy.key} is marked implemented but {policy.action} is not enforced",
                )
            )
    return findings


def scan_forbidden_security_text(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        text = read_text(path)
        if text is None:
            continue
        for code, pattern, detail in FORBIDDEN_SECURITY_TEXT_PATTERNS:
            for match in pattern.finditer(text):
                findings.append(Finding(code, relative, line_number(text, match.start()), detail))
    return findings


def main() -> int:
    paths = tracked_files()
    findings = [
        *scan_secrets(paths),
        *scan_forbidden_security_text(paths),
        *scan_security_contracts(),
        *scan_governance_policy_contracts(paths),
    ]
    if findings:
        print("Security governance audit failed:", file=sys.stderr)
        for finding in findings:
            print(f"  - {finding.format()}", file=sys.stderr)
        return 1
    print("Security governance audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
