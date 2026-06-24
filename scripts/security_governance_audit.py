from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.governance_policy import HIGH_RISK_API_POLICIES, validate_governance_policy  # noqa: E402

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
USES_LINE_RE = re.compile(r"^\s*(?:-\s*)?uses:\s+([^\s#]+)", re.MULTILINE)
WORKFLOW_PERMISSION_KEYS_ALLOWED_AT_TOP = {"actions", "contents"}
WORKFLOW_JOB_WRITE_PERMISSION_ALLOWLIST: dict[str, dict[str, dict[str, str]]] = {
    ".github/workflows/release-remote-runner-artifacts.yml": {
        "build": {
            "attestations": "write",
            "artifact-metadata": "write",
            "id-token": "write",
        },
        "publish": {
            "contents": "write",
        },
    },
}


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    line: int
    detail: str

    def format(self) -> str:
        suffix = f":{self.line}" if self.line else ""
        return f"{self.code}: {self.path}{suffix} {self.detail}".rstrip()


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


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


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
    for workflow in workflow_root.glob("*.yml"):
        source = workflow.read_text(encoding="utf-8")
        relative = workflow.relative_to(ROOT).as_posix()
        findings.extend(scan_workflow_security_contract(relative, source))
    codeowners = ROOT / ".github" / "CODEOWNERS"
    if not codeowners.exists():
        findings.append(Finding("codeowners-missing", ".github/CODEOWNERS", 0, "security-sensitive automation requires CODEOWNERS"))
    else:
        source = codeowners.read_text(encoding="utf-8")
        for marker in ("/.github/workflows/", "/scripts/security_governance_audit.py", "/core/governance_policy.py"):
            if marker not in source:
                findings.append(Finding("codeowners-incomplete", ".github/CODEOWNERS", 0, f"CODEOWNERS missing {marker}"))
    return findings


def scan_workflow_security_contract(relative: str, source: str) -> list[Finding]:
    findings: list[Finding] = []
    if "pull_request_target:" in source:
        findings.append(Finding("dangerous-workflow-trigger", relative, 0, "pull_request_target is not allowed"))
    if "workflow_run:" in source:
        findings.append(Finding("dangerous-workflow-trigger", relative, 0, "workflow_run is not allowed"))
    findings.extend(scan_workflow_action_pinning(relative, source))
    findings.extend(scan_workflow_permissions(relative, source))
    return findings


def scan_workflow_action_pinning(relative: str, source: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in USES_LINE_RE.finditer(source):
        action_ref = match.group(1).strip().strip("'\"")
        if action_ref.startswith("./"):
            continue
        if "@" not in action_ref:
            findings.append(
                Finding(
                    "unpinned-action",
                    relative,
                    line_number(source, match.start()),
                    "third-party actions must include an immutable full commit SHA ref",
                )
            )
            continue
        ref = action_ref.rsplit("@", 1)[1]
        if not re.fullmatch(r"[0-9a-f]{40}", ref):
            findings.append(
                Finding(
                    "unpinned-action",
                    relative,
                    line_number(source, match.start()),
                    "third-party actions must be pinned to a full commit SHA",
                )
            )
    return findings


def scan_workflow_permissions(relative: str, source: str) -> list[Finding]:
    findings: list[Finding] = []
    lines = source.splitlines()
    top_permissions = _simple_yaml_mapping_after_key(lines, "permissions", 0)
    if top_permissions is None:
        return [Finding("workflow-permissions", relative, 0, "workflow must declare explicit top-level permissions")]
    if top_permissions.line_errors:
        findings.extend(
            Finding("workflow-permissions", relative, line, detail)
            for line, detail in top_permissions.line_errors
        )
    if top_permissions.values.get("contents") != "read":
        findings.append(Finding("workflow-permissions", relative, top_permissions.line, "workflow must declare contents: read"))
    for permission, value in sorted(top_permissions.values.items()):
        if permission not in WORKFLOW_PERMISSION_KEYS_ALLOWED_AT_TOP:
            findings.append(
                Finding(
                    "workflow-permission-unapproved",
                    relative,
                    top_permissions.value_lines.get(permission, top_permissions.line),
                    f"top-level workflow permission {permission} is not approved",
                )
            )
        if value != "read":
            findings.append(
                Finding(
                    "workflow-permission-write-unapproved",
                    relative,
                    top_permissions.value_lines.get(permission, top_permissions.line),
                    f"top-level workflow permission {permission}: {value} is not approved",
                )
            )

    for job_id, permission_block in _workflow_job_permission_blocks(lines).items():
        allowed_writes = WORKFLOW_JOB_WRITE_PERMISSION_ALLOWLIST.get(relative, {}).get(job_id, {})
        if permission_block.line_errors:
            findings.extend(
                Finding("workflow-permissions", relative, line, f"job {job_id}: {detail}")
                for line, detail in permission_block.line_errors
            )
        for permission, value in sorted(permission_block.values.items()):
            line = permission_block.value_lines.get(permission, permission_block.line)
            if value == "read":
                continue
            if allowed_writes.get(permission) == value:
                continue
            findings.append(
                Finding(
                    "workflow-permission-write-unapproved",
                    relative,
                    line,
                    f"job {job_id} declares unapproved permission {permission}: {value}",
                )
            )
    if _workflow_has_untrusted_pr_trigger(source) and _workflow_declares_write_permissions(lines):
        findings.append(
            Finding(
                "workflow-write-permission-on-pr",
                relative,
                0,
                "workflow with pull_request or merge_group trigger must not declare write permissions",
            )
        )
    return findings


@dataclass(frozen=True)
class SimpleYamlMapping:
    line: int
    line_errors: tuple[tuple[int, str], ...]
    values: dict[str, str]
    value_lines: dict[str, int]


def _simple_yaml_mapping_after_key(lines: list[str], key: str, indent: int) -> SimpleYamlMapping | None:
    key_re = re.compile(rf"^ {{{indent}}}{re.escape(key)}:\s*(.*?)\s*(?:#.*)?$")
    for index, line in enumerate(lines):
        match = key_re.match(line)
        if not match:
            continue
        inline_value = match.group(1).strip()
        if inline_value:
            return SimpleYamlMapping(
                line=index + 1,
                line_errors=((index + 1, f"{key} must be a mapping block, not {inline_value!r}"),),
                values={},
                value_lines={},
            )
        return _read_simple_yaml_mapping(lines, start=index + 1, parent_indent=indent, parent_line=index + 1)
    return None


def _read_simple_yaml_mapping(
    lines: list[str],
    *,
    start: int,
    parent_indent: int,
    parent_line: int,
) -> SimpleYamlMapping:
    values: dict[str, str] = {}
    value_lines: dict[str, int] = {}
    errors: list[tuple[int, str]] = []
    child_indent = parent_indent + 2
    for index in range(start, len(lines)):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= parent_indent:
            break
        if indent != child_indent:
            errors.append((index + 1, "permission mapping must use one indentation level"))
            continue
        match = re.match(r"^\s*([A-Za-z0-9_-]+):\s*([A-Za-z-]+)\s*(?:#.*)?$", line)
        if not match:
            errors.append((index + 1, "permission entry must be a simple key: value pair"))
            continue
        values[match.group(1)] = match.group(2)
        value_lines[match.group(1)] = index + 1
    return SimpleYamlMapping(line=parent_line, line_errors=tuple(errors), values=values, value_lines=value_lines)


def _workflow_job_permission_blocks(lines: list[str]) -> dict[str, SimpleYamlMapping]:
    blocks: dict[str, SimpleYamlMapping] = {}
    in_jobs = False
    current_job: str | None = None
    for index, line in enumerate(lines):
        if re.match(r"^jobs:\s*(?:#.*)?$", line):
            in_jobs = True
            current_job = None
            continue
        if not in_jobs:
            continue
        if line.strip() and not line.startswith(" "):
            break
        job_match = re.match(r"^  ([A-Za-z0-9_-]+):\s*(?:#.*)?$", line)
        if job_match:
            current_job = job_match.group(1)
            continue
        if current_job and re.match(r"^    permissions:\s*(.*?)\s*(?:#.*)?$", line):
            block = _simple_yaml_mapping_after_key(lines[index:], "permissions", 4)
            if block is not None:
                blocks[current_job] = SimpleYamlMapping(
                    line=block.line + index,
                    line_errors=tuple((line_no + index, detail) for line_no, detail in block.line_errors),
                    values=block.values,
                    value_lines={key: value + index for key, value in block.value_lines.items()},
                )
    return blocks


def _workflow_has_untrusted_pr_trigger(source: str) -> bool:
    return "pull_request:" in source or "merge_group:" in source


def _workflow_declares_write_permissions(lines: list[str]) -> bool:
    for line in lines:
        if re.match(r"^\s*[A-Za-z0-9_-]+:\s*write\s*(?:#.*)?$", line):
            return True
    return False


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
