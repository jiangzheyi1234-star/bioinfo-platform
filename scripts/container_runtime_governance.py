from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


CONTAINER_RUNTIME_HARDENING_POLICY = ".github/container-runtime-hardening.target.json"
COMPOSE_FILE = "docker-compose.yml"
API_DOCKERFILE = "Dockerfile.api"
WEB_DOCKERFILE = "Dockerfile.web"
REQUIRED_GRADUATION_CONTROLS = {
    "localhost-only-api-bind",
    "authenticated-reverse-proxy-tls",
    "secret-mounts-or-provider-backed-secrets",
    "non-root-containers",
    "no-new-privileges",
    "cap-drop-all",
    "read-only-root-filesystems",
    "cpu-memory-pids-limits",
    "remote-container-smoke-and-image-scan-evidence",
}


@dataclass(frozen=True)
class ContainerRuntimeFinding:
    code: str
    path: str
    line: int
    detail: str


def scan_container_runtime_hardening_policy(
    relative: str,
    policy_source: str,
    compose_source: str,
    api_dockerfile_source: str,
    web_dockerfile_source: str,
) -> list[ContainerRuntimeFinding]:
    if relative != CONTAINER_RUNTIME_HARDENING_POLICY:
        return []
    if not policy_source.strip():
        return [_finding("container-runtime-policy-missing", relative, "runtime hardening target policy is missing")]
    try:
        policy = json.loads(policy_source)
    except json.JSONDecodeError as exc:
        return [_finding("container-runtime-policy-json", relative, f"invalid JSON: {exc.msg}")]

    findings: list[ContainerRuntimeFinding] = []
    _require_equal(findings, relative, policy, "schemaVersion", "h2ometa-container-runtime-hardening-policy.v1")
    _require_equal(findings, relative, policy, "composeFile", COMPOSE_FILE)
    _require_equal(findings, relative, policy, "deploymentMode", "server-single-user")
    _require_equal(findings, relative, _dict(policy.get("dockerfiles")), "api", API_DOCKERFILE)
    _require_equal(findings, relative, _dict(policy.get("dockerfiles")), "web", WEB_DOCKERFILE)
    detected = _detect_runtime_findings(compose_source, api_dockerfile_source, web_dockerfile_source)
    findings.extend(_policy_findings_for_detected_runtime(relative, policy, detected))
    return findings


def _policy_findings_for_detected_runtime(
    relative: str,
    policy: dict[str, Any],
    detected: set[str],
) -> list[ContainerRuntimeFinding]:
    findings: list[ContainerRuntimeFinding] = []
    known = set(_as_string_list(policy.get("knownUnsafeFindings")))
    production_ready = policy.get("productionReadyClaim") is True
    status = str(policy.get("status") or "").strip()
    warning = str(policy.get("unsupportedWarning") or "").strip().lower()
    if detected and production_ready:
        findings.append(
            _finding(
                "container-runtime-production-claim-unsafe",
                relative,
                "policy cannot claim production readiness while runtime hardening blockers are detected",
            )
        )
    if detected and status != "unsupported-draft":
        findings.append(
            _finding(
                "container-runtime-status-unsafe",
                relative,
                "unsafe runtime draft must keep status unsupported-draft",
            )
        )
    if detected and ("unsupported" not in warning or "fail-closed" not in warning):
        findings.append(
            _finding(
                "container-runtime-warning-missing",
                relative,
                "unsafe runtime draft must declare an unsupported fail-closed warning",
            )
        )
    missing_known = detected - known
    if missing_known:
        findings.append(
            _finding(
                "container-runtime-known-unsafe-missing",
                relative,
                "policy must list detected blockers: " + ", ".join(sorted(missing_known)),
            )
        )
    stale_known = known - detected
    if stale_known:
        findings.append(
            _finding(
                "container-runtime-known-unsafe-stale",
                relative,
                "policy lists blockers no longer detected: " + ", ".join(sorted(stale_known)),
            )
        )
    missing_controls = REQUIRED_GRADUATION_CONTROLS - _graduation_control_ids(policy)
    if missing_controls:
        findings.append(
            _finding(
                "container-runtime-graduation-control-missing",
                relative,
                "policy must list graduation controls: " + ", ".join(sorted(missing_controls)),
            )
        )
    return findings


def _detect_runtime_findings(
    compose_source: str,
    api_dockerfile_source: str,
    web_dockerfile_source: str,
) -> set[str]:
    findings: set[str] = set()
    if "H2OMETA_API_HOST=0.0.0.0" in compose_source or "H2OMETA_API_HOST=0.0.0.0" in api_dockerfile_source:
        findings.add("container-runtime-api-bind-all")
    if re.search(r'["\']?8765:8765["\']?', compose_source):
        findings.add("container-runtime-api-host-port")
    if "H2OMETA_RUNNER_TOKEN=${" in compose_source:
        findings.add("container-runtime-env-token-secret")
    if not _has_user_directive(api_dockerfile_source):
        findings.add("container-runtime-api-root-user")
    if not _has_user_directive(web_dockerfile_source):
        findings.add("container-runtime-web-root-user")
    if "no-new-privileges:true" not in compose_source and "no-new-privileges: true" not in compose_source:
        findings.add("container-runtime-no-new-privileges-missing")
    if not re.search(r"(?ms)cap_drop:\s*(?:\n\s*-\s*ALL\b|\[\s*['\"]?ALL['\"]?\s*\])", compose_source):
        findings.add("container-runtime-cap-drop-all-missing")
    if "read_only: true" not in compose_source:
        findings.add("container-runtime-read-only-rootfs-missing")
    if not _has_resource_limits(compose_source):
        findings.add("container-runtime-resource-limits-missing")
    if "H2OMETA_RUNNER_TOKEN=${" in compose_source and not re.search(r"(?m)^secrets:\s*$", compose_source):
        findings.add("container-runtime-secret-mounts-missing")
    return findings


def _has_user_directive(source: str) -> bool:
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if re.match(r"^USER\s+(.+)$", stripped, re.IGNORECASE):
            user = stripped.split(maxsplit=1)[1].strip().lower()
            return user not in {"0", "root"}
    return False


def _has_resource_limits(source: str) -> bool:
    if re.search(r"(?m)^\s*(mem_limit|cpus|pids_limit):\s*.+$", source):
        return True
    return "resources:" in source and "limits:" in source


def _graduation_control_ids(policy: dict[str, Any]) -> set[str]:
    controls = policy.get("graduationControls")
    if not isinstance(controls, list):
        return set()
    return {
        str(item.get("id") or "").strip()
        for item in controls
        if isinstance(item, dict) and item.get("requiredBeforeProduction") is True
    }


def _require_equal(
    findings: list[ContainerRuntimeFinding],
    relative: str,
    payload: dict[str, Any],
    key: str,
    expected: Any,
) -> None:
    if payload.get(key) != expected:
        findings.append(_finding("container-runtime-policy-field", relative, f"{key} must be {expected!r}"))


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _finding(code: str, path: str, detail: str) -> ContainerRuntimeFinding:
    return ContainerRuntimeFinding(code, path, 0, detail)
