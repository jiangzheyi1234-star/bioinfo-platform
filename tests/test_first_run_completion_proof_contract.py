from __future__ import annotations

import asyncio
from typing import Any

import pytest

from apps.api.workflow_first_run_completion_proof_contract import FIRST_RUN_COMPLETION_PROOF_INVALID
from apps.api.workflow_first_run_status_service import build_first_run_status_from_request
from tests.test_first_run_status import _patch_status_sources


@pytest.mark.parametrize(
    ("proof_patch", "detail_fragment"),
    [
        ({"runId": ""}, "runId"),
        ({"resultPackageSha256": ""}, "resultPackageSha256"),
        ({"validationChecksPassed": 9}, "validation checks are incomplete"),
        ({"evidenceBundleReady": False}, "evidence bundle is not ready"),
    ],
)
def test_first_run_status_fails_closed_on_invalid_saved_completion_proof(
    monkeypatch,
    proof_patch: dict[str, Any],
    detail_fragment: str,
) -> None:
    proof = _completion_proof()
    proof.update(proof_patch)

    def fake_latest_completion_proof(*, server_id: str | None = None) -> dict[str, Any]:
        assert server_id == "srv_first"
        return proof

    _patch_status_sources(monkeypatch, runs=[], sample_status="ready")
    monkeypatch.setattr(
        "apps.api.workflow_first_run_status_service.latest_first_run_completion_proof",
        fake_latest_completion_proof,
    )

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["stage"] == "submit_run"
    assert result["nextAction"]["code"] == "SUBMIT_RUN"
    assert result["latestEligibleRun"] is None
    assert result["evidence"]["completionProof"]["ready"] is False
    assert result["evidence"]["completionProof"]["blockedCode"] == FIRST_RUN_COMPLETION_PROOF_INVALID
    assert detail_fragment in result["evidence"]["completionProof"]["detail"]


def _completion_proof() -> dict[str, Any]:
    return {
        "schemaVersion": "h2ometa.first-run.completion-proof.v1",
        "ready": True,
        "serverId": "srv_first",
        "runId": "run_first",
        "resultId": "res_run_first",
        "workflowRevisionId": "wfrev_first",
        "packageExportId": "rpex_full",
        "packageEvidenceId": "ev_export",
        "resultPackageSha256": "d" * 64,
        "resultPackageManifestSha256": "e" * 64,
        "validationCardGeneratedAt": "2026-06-29T00:00:00Z",
        "validationCardJsonSha256": "f" * 64,
        "validationChecksPassed": 10,
        "validationChecksTotal": 10,
        "reportReady": True,
        "reportOutputNames": ["summary.tsv", "qc-summary.tsv", "feature-table.tsv", "run-report.html"],
        "evidenceBundleId": "res_run_first.first-run-evidence",
        "evidenceBundleReady": True,
        "evidenceBundleFileRoles": [
            "result-package",
            "validation-card-json",
            "validation-card-markdown",
            "pilot-handoff",
        ],
        "savedAt": "2026-06-29T00:30:00Z",
    }
