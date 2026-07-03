from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from apps.api.workflow_first_run_completion_proof_contract import (
    FIRST_RUN_COMPLETION_PROOF_INVALID,
    FIRST_RUN_COMPLETION_PROOF_STORE_UNREADABLE,
)
from apps.api.workflow_first_run_completion_store import FirstRunCompletionProofStoreError
from apps.api.workflow_first_run_status_service import build_first_run_status_from_request
from tests.test_first_run_status import _patch_status_sources


@pytest.mark.parametrize(
    ("proof_patch", "detail_fragment"),
    [
        ({"runId": ""}, "runId"),
        ({"resultPackageSha256": ""}, "resultPackageSha256"),
        ({"resultId": "res_other"}, "resultId does not match runId"),
        ({"evidenceBundleId": "res_other.first-run-evidence"}, "evidenceBundleId does not match resultId"),
        ({"resultPackageSha256": "not-a-sha256"}, "invalid sha256 resultPackageSha256"),
        ({"resultPackageManifestSha256": "0" * 63}, "invalid sha256 resultPackageManifestSha256"),
        ({"validationCardJsonSha256": "g" * 64}, "invalid sha256 validationCardJsonSha256"),
        ({"validationChecksPassed": 9}, "validation checks are incomplete"),
        ({"reportReady": False}, "report evidence is not ready"),
        ({"reportOutputNames": ["summary.tsv", "qc-summary.tsv", "run-report.html"]}, "feature-table.tsv"),
        ({"evidenceBundleReady": False}, "evidence bundle is not ready"),
        ({"evidenceBundleFileRoles": ["result-package", "validation-card-json", "pilot-handoff"]}, "validation-card-markdown"),
    ],
)
def test_first_run_status_fails_closed_on_invalid_saved_completion_proof(
    monkeypatch,
    proof_patch: dict[str, Any],
    detail_fragment: str,
) -> None:
    proof = _completion_proof()
    proof.update(proof_patch)

    def fake_latest_completion_proof(*, server_id: str | None = None, run_id: str | None = None) -> dict[str, Any]:
        assert server_id == "srv_first"
        assert run_id == ""
        return proof

    _patch_status_sources(monkeypatch, runs=[], sample_status="ready")
    monkeypatch.setattr(
        "apps.api.workflow_first_run_completion_proof_contract.latest_first_run_completion_proof",
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


def test_first_run_status_fails_closed_when_completion_proof_store_is_unreadable(monkeypatch) -> None:
    def fail_latest_completion_proof(*, server_id: str | None = None, run_id: str | None = None) -> dict[str, Any]:
        assert server_id == "srv_first"
        assert run_id == ""
        raise FirstRunCompletionProofStoreError("FIRST_RUN_COMPLETION_PROOF_STORE_INVALID_JSON")

    _patch_status_sources(monkeypatch, runs=[], sample_status="ready")
    monkeypatch.setattr(
        "apps.api.workflow_first_run_completion_proof_contract.latest_first_run_completion_proof",
        fail_latest_completion_proof,
    )

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["stage"] == "submit_run"
    assert result["nextAction"]["code"] == "SUBMIT_RUN"
    assert result["evidence"]["completionProof"] == {
        "ready": False,
        "blockedCode": FIRST_RUN_COMPLETION_PROOF_STORE_UNREADABLE,
        "detail": (
            "saved first-run completion proof store is unreadable: "
            "FIRST_RUN_COMPLETION_PROOF_STORE_INVALID_JSON"
        ),
    }


def test_first_run_status_fails_closed_when_completion_proof_records_are_malformed(monkeypatch, tmp_path) -> None:
    store_path = tmp_path / "completion-proofs-v1.json"
    store_path.write_text(json.dumps({"version": 1, "records": [_completion_proof(), "not-an-object"]}), encoding="utf-8")

    _patch_status_sources(monkeypatch, runs=[], sample_status="ready")
    monkeypatch.setattr(
        "apps.api.workflow_first_run_completion_store.get_first_run_completion_proof_store_path",
        lambda: store_path,
    )

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["stage"] == "submit_run"
    assert result["nextAction"]["code"] == "SUBMIT_RUN"
    assert result["evidence"]["completionProof"]["ready"] is False
    assert result["evidence"]["completionProof"]["blockedCode"] == FIRST_RUN_COMPLETION_PROOF_STORE_UNREADABLE
    assert "FIRST_RUN_COMPLETION_PROOF_STORE_RECORD_INVALID" in result["evidence"]["completionProof"]["detail"]


def test_first_run_status_uses_requested_saved_completion_proof_when_newer_proof_exists(
    monkeypatch,
    tmp_path,
) -> None:
    older_proof = _completion_proof()
    newer_proof = _completion_proof()
    newer_proof.update(
        {
            "runId": "run_second",
            "resultId": "res_run_second",
            "packageExportId": "rpex_second",
            "evidenceBundleId": "res_run_second.first-run-evidence",
            "savedAt": "2026-06-29T00:45:00Z",
        }
    )
    store_path = tmp_path / "completion-proofs-v1.json"
    store_path.write_text(json.dumps({"version": 1, "records": [older_proof, newer_proof]}), encoding="utf-8")

    _patch_status_sources(monkeypatch, runs=[], sample_status="ready")
    monkeypatch.setattr(
        "apps.api.workflow_first_run_completion_store.get_first_run_completion_proof_store_path",
        lambda: store_path,
    )

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first", run_id="run_first"))["data"]

    assert result["status"] == "ready"
    assert result["evidence"]["completionProof"]["runId"] == "run_first"
    assert result["evidence"]["completionProof"]["packageExportId"] == "rpex_full"
    assert result["latestEligibleRun"]["runId"] == "run_first"


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
