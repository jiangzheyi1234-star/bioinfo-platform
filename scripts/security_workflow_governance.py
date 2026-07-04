from __future__ import annotations

import re
from dataclasses import dataclass

from scripts.container_image_scan_governance import CONTAINER_IMAGE_SCAN_WORKFLOW
from scripts.security_analysis_governance import (
    SECURITY_ANALYSIS_WORKFLOW,
    scan_required_ci_security_analysis_contract as _scan_required_ci_security_analysis_contract,
    scan_security_analysis_workflow_contract as _scan_security_analysis_workflow_contract,
)
from scripts.security_governance_common import Finding, line_number


USES_LINE_RE = re.compile(r"^\s*(?:-\s*)?uses:\s+([^\s#]+)", re.MULTILINE)
UPLOAD_ARTIFACT_USES_RE = re.compile(r"^(?P<indent>\s*)(?:-\s*)?uses:\s+(?P<action>[^\s#]+)")
RETENTION_DAYS_RE = re.compile(r"^\s*retention-days:\s*(.+?)\s*(?:#.*)?$")
MAX_WORKFLOW_ARTIFACT_RETENTION_DAYS = 2
DEPENDENCY_REVIEW_ACTION = (
    "actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294"
)
WORKFLOW_PERMISSION_KEYS_ALLOWED_AT_TOP = {"actions", "contents"}
WORKFLOW_JOB_WRITE_PERMISSION_ALLOWLIST: dict[str, dict[str, dict[str, str]]] = {
    ".github/workflows/release-remote-runner-artifacts.yml": {
        "build": {"attestations": "write", "artifact-metadata": "write", "id-token": "write"},
        "publish": {"contents": "write"},
    },
    SECURITY_ANALYSIS_WORKFLOW: {
        "codeql": {"security-events": "write"},
        "scorecard": {"id-token": "write", "security-events": "write"},
    },
    CONTAINER_IMAGE_SCAN_WORKFLOW: {"scan": {"security-events": "write"}},
}


def scan_workflow_security_contract(relative: str, source: str) -> list[Finding]:
    findings: list[Finding] = []
    if "pull_request_target:" in source:
        findings.append(Finding("dangerous-workflow-trigger", relative, 0, "pull_request_target is not allowed"))
    if "workflow_run:" in source:
        findings.append(Finding("dangerous-workflow-trigger", relative, 0, "workflow_run is not allowed"))
    findings.extend(scan_workflow_action_pinning(relative, source))
    findings.extend(scan_workflow_checkout_credentials(relative, source))
    findings.extend(scan_workflow_artifact_retention(relative, source))
    findings.extend(scan_workflow_permissions(relative, source))
    findings.extend(scan_dependency_review_workflow_contract(relative, source))
    findings.extend(
        Finding(item.code, item.path, item.line, item.detail)
        for item in _scan_security_analysis_workflow_contract(relative, source)
    )
    findings.extend(
        Finding(item.code, item.path, item.line, item.detail)
        for item in _scan_required_ci_security_analysis_contract(relative, source)
    )
    return findings


def scan_workflow_checkout_credentials(relative: str, source: str) -> list[Finding]:
    findings: list[Finding] = []
    lines = source.splitlines()
    for index, line in enumerate(lines):
        match = UPLOAD_ARTIFACT_USES_RE.match(line)
        if not match:
            continue
        action_ref = match.group("action").strip().strip("'\"")
        if not action_ref.lower().startswith("actions/checkout@"):
            continue
        step_indent = _workflow_step_indent(line)
        with_indent = _workflow_step_child_block_indent(lines, index + 1, step_indent, "with")
        setting_line, setting_value = (
            _workflow_mapping_literal_setting(
                lines,
                with_indent[0] + 1,
                with_indent[1],
                "persist-credentials",
            )
            if with_indent is not None
            else (None, None)
        )
        if setting_value != "false":
            findings.append(
                Finding(
                    "workflow-checkout-persist-credentials",
                    relative,
                    setting_line or index + 1,
                    "actions/checkout steps must set persist-credentials: false",
                )
            )
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


def scan_workflow_artifact_retention(relative: str, source: str) -> list[Finding]:
    findings: list[Finding] = []
    lines = source.splitlines()
    for index, line in enumerate(lines):
        match = UPLOAD_ARTIFACT_USES_RE.match(line)
        if not match:
            continue
        action_ref = match.group("action").strip().strip("'\"")
        if not action_ref.lower().startswith("actions/upload-artifact@"):
            continue
        uses_line = index + 1
        step_indent = _workflow_step_indent(line)
        retention_line, retention_value = _upload_artifact_retention(lines, index + 1, step_indent)
        if retention_value is None:
            findings.append(
                Finding(
                    "workflow-artifact-retention-missing",
                    relative,
                    uses_line,
                    f"actions/upload-artifact steps must set retention-days <= {MAX_WORKFLOW_ARTIFACT_RETENTION_DAYS}",
                )
            )
            continue
        try:
            retention_days = int(retention_value.strip("'\""))
        except ValueError:
            findings.append(
                Finding(
                    "workflow-artifact-retention-invalid",
                    relative,
                    retention_line or uses_line,
                    "actions/upload-artifact retention-days must be a literal integer",
                )
            )
            continue
        if retention_days < 1 or retention_days > MAX_WORKFLOW_ARTIFACT_RETENTION_DAYS:
            findings.append(
                Finding(
                    "workflow-artifact-retention-too-long",
                    relative,
                    retention_line or uses_line,
                    (
                        "actions/upload-artifact retention-days must be between 1 and "
                        f"{MAX_WORKFLOW_ARTIFACT_RETENTION_DAYS}; durable deliverables belong in release assets"
                    ),
                )
            )
    return findings


def _workflow_step_indent(line: str) -> int:
    indent = len(line) - len(line.lstrip(" "))
    if line.lstrip(" ").startswith("- "):
        return indent
    return max(0, indent - 2)


def _upload_artifact_retention(
    lines: list[str],
    start: int,
    step_indent: int,
) -> tuple[int | None, str | None]:
    for index in range(start, len(lines)):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= step_indent:
            break
        match = RETENTION_DAYS_RE.match(line)
        if match:
            return index + 1, match.group(1).strip()
    return None, None


def _workflow_step_child_block_indent(
    lines: list[str],
    start: int,
    step_indent: int,
    key: str,
) -> tuple[int, int] | None:
    block_re = re.compile(rf"^\s*{re.escape(key)}:\s*(?:#.*)?$")
    for index in range(start, len(lines)):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= step_indent:
            break
        if block_re.match(line):
            return index, indent
    return None


def _workflow_mapping_literal_setting(
    lines: list[str],
    start: int,
    mapping_indent: int,
    key: str,
) -> tuple[int | None, str | None]:
    setting_re = re.compile(rf"^\s*{re.escape(key)}:\s*(.+?)\s*(?:#.*)?$")
    for index in range(start, len(lines)):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= mapping_indent:
            break
        if indent != mapping_indent + 2:
            continue
        match = setting_re.match(line)
        if match:
            return index + 1, match.group(1).strip().strip("'\"").lower()
    return None, None


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


def scan_dependency_review_workflow_contract(relative: str, source: str) -> list[Finding]:
    if "actions/dependency-review-action@" not in source:
        return []

    findings: list[Finding] = []
    if DEPENDENCY_REVIEW_ACTION not in source:
        findings.append(
            Finding(
                "dependency-review-action-ref",
                relative,
                0,
                "Dependency Review must use the reviewed SHA-pinned action ref",
            )
        )
    if "pull_request:" not in source or "if: ${{ github.event_name == 'pull_request' }}" not in source:
        findings.append(
            Finding(
                "dependency-review-pr-only",
                relative,
                0,
                "Dependency Review must be guarded as a pull_request-only job",
            )
        )
    if not re.search(r"^\s*fail-on-severity:\s*moderate\s*(?:#.*)?$", source, re.MULTILINE):
        findings.append(
            Finding(
                "dependency-review-severity",
                relative,
                0,
                "Dependency Review must fail on moderate-or-higher vulnerabilities",
            )
        )
    if not re.search(r"^\s*comment-summary-in-pr:\s*never\s*(?:#.*)?$", source, re.MULTILINE):
        findings.append(
            Finding(
                "dependency-review-pr-comments",
                relative,
                0,
                "Dependency Review must not request pull request comment permissions",
            )
        )
    if re.search(r"^\s*warn-only:\s*true\s*(?:#.*)?$", source, re.MULTILINE):
        findings.append(
            Finding(
                "dependency-review-warn-only",
                relative,
                0,
                "Dependency Review must block instead of warning only",
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
