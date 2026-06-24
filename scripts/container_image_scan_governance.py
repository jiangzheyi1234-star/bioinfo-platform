from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


CONTAINER_IMAGE_SCAN_POLICY = ".github/container-image-scan.target.json"
CONTAINER_IMAGE_SCAN_WORKFLOW = ".github/workflows/container-image-scan.yml"
TRIVY_ACTION = "aquasecurity/trivy-action@a9c7b0f06e461e9d4b4d1711f154ee024b8d7ab8"
EXPECTED_IMAGES = {
    "api": {"dockerfile": "Dockerfile.api", "sarif": "scan-results/trivy-api.sarif"},
    "web": {"dockerfile": "Dockerfile.web", "sarif": "scan-results/trivy-web.sarif"},
}


@dataclass(frozen=True)
class ContainerImageScanFinding:
    code: str
    path: str
    line: int
    detail: str


def scan_container_image_scan_policy(
    relative: str,
    policy_source: str,
    workflow_source: str,
) -> list[ContainerImageScanFinding]:
    if relative != CONTAINER_IMAGE_SCAN_POLICY:
        return []
    try:
        policy = json.loads(policy_source)
    except json.JSONDecodeError as exc:
        return [_finding("container-image-scan-policy-json", relative, f"invalid JSON: {exc.msg}")]

    findings: list[ContainerImageScanFinding] = []
    _require_equal(findings, relative, policy, "schemaVersion", "h2ometa-container-image-scan-policy.v1")
    _require_equal(findings, relative, policy, "status", "target-policy")
    _require_equal(findings, relative, policy, "productionReadyClaim", False)
    _require_equal(findings, relative, policy, "requiredStatusCheck", False)
    _require_equal(findings, relative, policy, "workflow", CONTAINER_IMAGE_SCAN_WORKFLOW)
    _require_equal(findings, relative, policy, "composeFile", "docker-compose.yml")
    _require_equal(findings, relative, policy.get("scanner", {}), "action", TRIVY_ACTION)
    if set(policy.get("triggers", [])) != {"push-main", "schedule", "workflow_dispatch"}:
        findings.append(_finding("container-image-scan-policy-trigger", relative, "policy must declare push-main, schedule, and workflow_dispatch triggers"))
    if set(policy.get("failOnSeverity", [])) != {"HIGH", "CRITICAL"}:
        findings.append(_finding("container-image-scan-policy-severity", relative, "policy must fail on HIGH and CRITICAL vulnerabilities"))
    if policy.get("sarifUpload") is not True:
        findings.append(_finding("container-image-scan-policy-sarif", relative, "policy must require SARIF upload"))
    if policy.get("artifactRetentionDaysMax") != 2:
        findings.append(_finding("container-image-scan-policy-retention", relative, "policy must cap artifacts at 2 days"))
    if not str(policy.get("knownRuntimeLimit", "")).strip():
        findings.append(_finding("container-image-scan-policy-runtime-limit", relative, "policy must document the unsupported container runtime limit"))
    findings.extend(_scan_policy_images(policy, relative))
    findings.extend(_scan_workflow(workflow_source))
    return findings


def _scan_policy_images(policy: dict[str, Any], relative: str) -> list[ContainerImageScanFinding]:
    images = {item.get("id"): item for item in policy.get("images", []) if isinstance(item, dict)}
    findings: list[ContainerImageScanFinding] = []
    for image_id, expected in EXPECTED_IMAGES.items():
        image = images.get(image_id)
        if image is None:
            findings.append(_finding("container-image-scan-policy-image", relative, f"missing {image_id} image"))
            continue
        for key, value in expected.items():
            if image.get(key) != value:
                findings.append(_finding("container-image-scan-policy-image", relative, f"{image_id} {key} must be {value}"))
    return findings


def _scan_workflow(source: str) -> list[ContainerImageScanFinding]:
    findings: list[ContainerImageScanFinding] = []
    if not source.strip():
        return [_finding("container-image-scan-workflow-missing", CONTAINER_IMAGE_SCAN_WORKFLOW, "workflow is missing")]
    for forbidden in ("pull_request:", "pull_request_target:", "workflow_run:", "merge_group:"):
        if forbidden in source:
            findings.append(_finding("container-image-scan-workflow-trigger", CONTAINER_IMAGE_SCAN_WORKFLOW, f"{forbidden} is not allowed"))
    required_snippets = (
        "name: Container Image Scan",
        "branches:\n      - main",
        "schedule:",
        "workflow_dispatch:",
        "permissions:\n  contents: read",
        "name: security / container image scan (${{ matrix.image }})",
        "fail-fast: false",
        "dockerfile: Dockerfile.api",
        "dockerfile: Dockerfile.web",
        "docker build --file \"${{ matrix.dockerfile }}\" --tag \"${{ matrix.image_ref }}\" .",
        "mkdir -p scan-results",
        f"uses: {TRIVY_ACTION}",
        "format: sarif",
        "format: table",
        "exit-code: \"1\"",
        "ignore-unfixed: true",
        "vuln-type: os,library",
        "severity: HIGH,CRITICAL",
        "retention-days: 2",
        "github/codeql-action/upload-sarif@",
    )
    for snippet in required_snippets:
        if snippet not in source:
            findings.append(_finding("container-image-scan-workflow-contract", CONTAINER_IMAGE_SCAN_WORKFLOW, f"missing {snippet!r}"))
    if source.count(f"uses: {TRIVY_ACTION}") != 2:
        findings.append(_finding("container-image-scan-workflow-contract", CONTAINER_IMAGE_SCAN_WORKFLOW, "workflow must run Trivy SARIF and enforcing scans"))
    return findings


def _require_equal(
    findings: list[ContainerImageScanFinding],
    relative: str,
    payload: dict[str, Any],
    key: str,
    expected: Any,
) -> None:
    if payload.get(key) != expected:
        findings.append(_finding("container-image-scan-policy-field", relative, f"{key} must be {expected!r}"))


def _finding(code: str, path: str, detail: str) -> ContainerImageScanFinding:
    return ContainerImageScanFinding(code, path, 0, detail)
