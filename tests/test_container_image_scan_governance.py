from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts.container_image_scan_governance import (
    CONTAINER_IMAGE_SCAN_POLICY,
    CONTAINER_IMAGE_SCAN_WORKFLOW,
    scan_container_image_scan_policy,
)


ROOT = Path(__file__).resolve().parents[1]


def _policy_source() -> str:
    return (ROOT / CONTAINER_IMAGE_SCAN_POLICY).read_text(encoding="utf-8")


def _workflow_source() -> str:
    return (ROOT / CONTAINER_IMAGE_SCAN_WORKFLOW).read_text(encoding="utf-8")


def _finding_codes(policy_source: str, workflow_source: str | None = None) -> set[str]:
    findings = scan_container_image_scan_policy(
        CONTAINER_IMAGE_SCAN_POLICY,
        policy_source,
        _workflow_source() if workflow_source is None else workflow_source,
    )
    return {finding.code for finding in findings}


def test_container_image_scan_policy_and_workflow_match_contract() -> None:
    policy = json.loads(_policy_source())
    workflow = _workflow_source()

    assert scan_container_image_scan_policy(CONTAINER_IMAGE_SCAN_POLICY, _policy_source(), workflow) == []
    assert policy["productionReadyClaim"] is False
    assert policy["requiredStatusCheck"] is False
    assert {image["id"] for image in policy["images"]} == {"api", "web"}
    assert "pull_request:" not in workflow
    assert "required / ci-green" not in workflow


def test_container_image_scan_policy_rejects_unsafe_contract_changes() -> None:
    policy = json.loads(_policy_source())

    production_claim = copy.deepcopy(policy)
    production_claim["productionReadyClaim"] = True
    assert "container-image-scan-policy-field" in _finding_codes(json.dumps(production_claim))

    weakened_scan = copy.deepcopy(policy)
    weakened_scan["failOnSeverity"] = ["CRITICAL"]
    assert "container-image-scan-policy-severity" in _finding_codes(json.dumps(weakened_scan))

    missing_web = copy.deepcopy(policy)
    missing_web["images"] = [image for image in missing_web["images"] if image["id"] != "web"]
    assert "container-image-scan-policy-image" in _finding_codes(json.dumps(missing_web))

    pr_workflow = _workflow_source().replace("workflow_dispatch:", "workflow_dispatch:\n  pull_request:")
    assert "container-image-scan-workflow-trigger" in _finding_codes(_policy_source(), pr_workflow)

    unpinned_workflow = _workflow_source().replace(
        "aquasecurity/trivy-action@a9c7b0f06e461e9d4b4d1711f154ee024b8d7ab8",
        "aquasecurity/trivy-action@v0.36.0",
    )
    assert "container-image-scan-workflow-contract" in _finding_codes(_policy_source(), unpinned_workflow)
