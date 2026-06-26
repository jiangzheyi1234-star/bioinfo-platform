from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts.container_runtime_governance import (
    API_DOCKERFILE,
    COMPOSE_FILE,
    CONTAINER_RUNTIME_HARDENING_POLICY,
    WEB_DOCKERFILE,
    scan_container_runtime_hardening_policy,
)


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _policy() -> dict[str, object]:
    return json.loads(_source(CONTAINER_RUNTIME_HARDENING_POLICY))


def _scan(policy_source: str) -> set[str]:
    findings = scan_container_runtime_hardening_policy(
        CONTAINER_RUNTIME_HARDENING_POLICY,
        policy_source,
        _source(COMPOSE_FILE),
        _source(API_DOCKERFILE),
        _source(WEB_DOCKERFILE),
    )
    return {finding.code for finding in findings}


def test_container_runtime_hardening_policy_truthfully_marks_compose_unsupported() -> None:
    policy = _policy()

    assert scan_container_runtime_hardening_policy(
        CONTAINER_RUNTIME_HARDENING_POLICY,
        _source(CONTAINER_RUNTIME_HARDENING_POLICY),
        _source(COMPOSE_FILE),
        _source(API_DOCKERFILE),
        _source(WEB_DOCKERFILE),
    ) == []
    assert policy["productionReadyClaim"] is False
    assert policy["status"] == "unsupported-draft"
    assert "unsupported" in str(policy["unsupportedWarning"]).lower()
    assert "fail-closed" in str(policy["unsupportedWarning"]).lower()
    assert set(policy["knownUnsafeFindings"]) == {
        "container-runtime-api-bind-all",
        "container-runtime-api-host-port",
        "container-runtime-api-root-user",
        "container-runtime-cap-drop-all-missing",
        "container-runtime-env-token-secret",
        "container-runtime-no-new-privileges-missing",
        "container-runtime-read-only-rootfs-missing",
        "container-runtime-resource-limits-missing",
        "container-runtime-secret-mounts-missing",
        "container-runtime-web-root-user",
    }


def test_container_runtime_policy_rejects_production_claim_with_current_draft() -> None:
    policy = _policy()
    policy["productionReadyClaim"] = True

    assert "container-runtime-production-claim-unsafe" in _scan(json.dumps(policy))


def test_container_runtime_policy_rejects_missing_unsupported_warning() -> None:
    policy = _policy()
    policy["unsupportedWarning"] = ""

    assert "container-runtime-warning-missing" in _scan(json.dumps(policy))


def test_container_runtime_policy_requires_current_blocker_inventory() -> None:
    policy = _policy()
    policy["knownUnsafeFindings"] = [
        item for item in policy["knownUnsafeFindings"] if item != "container-runtime-api-bind-all"
    ]

    assert "container-runtime-known-unsafe-missing" in _scan(json.dumps(policy))


def test_container_runtime_policy_requires_graduation_controls() -> None:
    policy = copy.deepcopy(_policy())
    policy["graduationControls"] = [
        item
        for item in policy["graduationControls"]
        if item["id"] != "no-new-privileges"
    ]

    assert "container-runtime-graduation-control-missing" in _scan(json.dumps(policy))
