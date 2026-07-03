from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from apps.api import workflow_first_run_completion_store as completion_store
from apps.api.workflow_first_run_completion_proof_contract import (
    FIRST_RUN_COMPLETION_PROOF_INVALID,
    FIRST_RUN_COMPLETION_PROOF_STORE_UNREADABLE,
)
from apps.api.workflow_first_run_completion_proof_validation import (
    FIRST_RUN_COMPLETION_PROOF_SCHEMA_VERSION,
    first_run_completion_proof_invalid_reason,
)
from apps.api.workflow_first_run_finalize_service import (
    WorkflowFirstRunFinalizeRequest,
    finalize_first_run_from_request,
)
from apps.api.workflow_first_run_service import build_first_run_validation_card_from_request
from tests.test_first_run_validation_card import _patch_first_run_sources


ROOT = Path(__file__).resolve().parents[1]


def test_first_run_completion_proof_read_and_write_share_ready_validator() -> None:
    store_source = (ROOT / "apps" / "api" / "workflow_first_run_completion_store.py").read_text(encoding="utf-8")
    contract_source = (ROOT / "apps" / "api" / "workflow_first_run_completion_proof_contract.py").read_text(
        encoding="utf-8"
    )

    assert "first_run_completion_proof_invalid_reason(proof)" in store_source
    assert "saved_first_run_completion_proof_invalid_detail(proof)" in contract_source
    assert "_REQUIRED_READY_FIELDS" not in store_source
    assert "_REQUIRED_READY_FIELDS" not in contract_source


@pytest.mark.parametrize(
    ("proof_patch", "detail"),
    [
        ({"schemaVersion": "h2ometa.first-run.completion-proof.v0"}, "schema is unsupported"),
        ({"ready": False}, "is not ready"),
    ],
)
def test_first_run_completion_proof_validator_rejects_schema_and_ready_contract(
    proof_patch: dict[str, object],
    detail: str,
) -> None:
    proof = _completion_proof_record()
    proof.update(proof_patch)

    assert first_run_completion_proof_invalid_reason(proof) == detail


@pytest.mark.parametrize(
    ("proof_patch", "detail"),
    [
        ({"schemaVersion": "h2ometa.first-run.completion-proof.v0"}, "schema is unsupported"),
        ({"ready": False}, "is not ready"),
    ],
)
def test_record_first_run_completion_proof_rejects_builder_output_that_fails_schema_ready_contract(
    monkeypatch,
    tmp_path,
    proof_patch: dict[str, object],
    detail: str,
) -> None:
    proof = _completion_proof_record()
    proof.update(proof_patch)
    monkeypatch.setattr(completion_store, "build_first_run_completion_proof", lambda *_args, **_kwargs: proof)

    with pytest.raises(completion_store.FirstRunCompletionProofStoreError) as exc_info:
        completion_store.record_first_run_completion_proof(
            {},
            server_id="srv_first",
            store_path=tmp_path / "completion-proofs-v1.json",
        )

    assert str(exc_info.value) == f"{FIRST_RUN_COMPLETION_PROOF_INVALID}: {detail}"


@pytest.mark.parametrize(
    ("proof_case", "detail"),
    [
        ("missing-package-sha", "FIRST_RUN_COMPLETION_PROOF_INVALID: missing resultPackageSha256"),
        ("result-mismatch", "FIRST_RUN_COMPLETION_PROOF_INVALID: resultId does not match runId"),
        ("bundle-mismatch", "FIRST_RUN_COMPLETION_PROOF_INVALID: evidenceBundleId does not match resultId"),
        ("duplicate-bundle-role", "FIRST_RUN_COMPLETION_PROOF_INVALID: duplicate evidence bundle roles result-package"),
        ("unexpected-bundle-role", "FIRST_RUN_COMPLETION_PROOF_INVALID: unexpected evidence bundle roles operator-note"),
        (
            "missing-zip-role",
            "FIRST_RUN_COMPLETION_PROOF_INVALID: missing evidence bundle ZIP roles completion-proof-json",
        ),
        (
            "duplicate-zip-role",
            "FIRST_RUN_COMPLETION_PROOF_INVALID: duplicate evidence bundle ZIP roles completion-proof-json",
        ),
        (
            "unexpected-zip-role",
            "FIRST_RUN_COMPLETION_PROOF_INVALID: unexpected evidence bundle ZIP roles operator-note",
        ),
        ("reduced-check-set", "FIRST_RUN_COMPLETION_PROOF_INVALID: validation checks are incomplete"),
        ("duplicate-report-output", "FIRST_RUN_COMPLETION_PROOF_INVALID: duplicate report outputs summary.tsv"),
        ("unexpected-report-output", "FIRST_RUN_COMPLETION_PROOF_INVALID: unexpected report outputs debug.log"),
    ],
)
def test_first_run_finalize_rejects_generated_completion_proof_that_fails_contract(
    monkeypatch,
    proof_case: str,
    detail: str,
) -> None:
    _patch_first_run_sources(monkeypatch)
    if proof_case == "missing-zip-role":
        monkeypatch.setattr(
            completion_store,
            "FIRST_RUN_COMPLETION_PROOF_EVIDENCE_BUNDLE_ZIP_ROLES",
            (
                "evidence-bundle-json",
                "pilot-handoff",
                "readme",
                "validation-card-json",
                "validation-card-markdown",
            ),
        )
    elif proof_case == "duplicate-zip-role":
        monkeypatch.setattr(
            completion_store,
            "FIRST_RUN_COMPLETION_PROOF_EVIDENCE_BUNDLE_ZIP_ROLES",
            (
                "completion-proof-json",
                "completion-proof-json",
                "evidence-bundle-json",
                "pilot-handoff",
                "readme",
                "validation-card-json",
                "validation-card-markdown",
            ),
        )
    elif proof_case == "unexpected-zip-role":
        monkeypatch.setattr(
            completion_store,
            "FIRST_RUN_COMPLETION_PROOF_EVIDENCE_BUNDLE_ZIP_ROLES",
            (
                "completion-proof-json",
                "evidence-bundle-json",
                "pilot-handoff",
                "readme",
                "validation-card-json",
                "validation-card-markdown",
                "operator-note",
            ),
        )

    async def fake_card(run_id: str, *_, server_id: str | None = None, **__):
        card = (await build_first_run_validation_card_from_request(run_id, server_id=server_id))["data"]
        if proof_case == "missing-package-sha":
            card["resultPackage"]["sha256"] = ""
        elif proof_case == "result-mismatch":
            card["result"]["resultId"] = "res_other"
        elif proof_case == "bundle-mismatch":
            card["pilotHandoff"]["evidenceBundle"]["bundleId"] = "res_other.first-run-evidence"
        elif proof_case == "duplicate-bundle-role":
            card["pilotHandoff"]["evidenceBundle"]["requiredFiles"].append(
                dict(card["pilotHandoff"]["evidenceBundle"]["requiredFiles"][0])
            )
        elif proof_case == "unexpected-bundle-role":
            note_file = dict(card["pilotHandoff"]["evidenceBundle"]["requiredFiles"][0])
            note_file["role"] = "operator-note"
            card["pilotHandoff"]["evidenceBundle"]["requiredFiles"].append(note_file)
        elif proof_case == "reduced-check-set":
            card["checks"] = card["checks"][:1]
        elif proof_case == "duplicate-report-output":
            card["reportInterpretation"]["outputs"].append(dict(card["reportInterpretation"]["outputs"][0]))
        elif proof_case == "unexpected-report-output":
            card["reportInterpretation"]["outputs"].append({"name": "debug.log"})
        elif proof_case in {"missing-zip-role", "duplicate-zip-role", "unexpected-zip-role"}:
            pass
        else:
            raise AssertionError(f"unknown proof case {proof_case}")
        return {"data": card}

    monkeypatch.setattr(
        "apps.api.workflow_first_run_finalize_service.build_first_run_validation_card_from_request",
        fake_card,
    )

    result = asyncio.run(
        finalize_first_run_from_request(
            "run_first",
            WorkflowFirstRunFinalizeRequest(serverId="srv_first", actor="operator"),
        )
    )["data"]

    assert result["status"] == "blocked"
    assert result["nextAction"] == {
        "code": FIRST_RUN_COMPLETION_PROOF_INVALID,
        "detail": detail,
        "label": "重新生成首跑完成证明",
        "target": "/workflows/first-run#evidence-bundle",
    }


def test_first_run_finalize_rejects_completion_proof_without_saved_timestamp(monkeypatch) -> None:
    _patch_first_run_sources(monkeypatch)
    monkeypatch.setattr("apps.api.workflow_first_run_completion_store._now", lambda: "")

    result = asyncio.run(
        finalize_first_run_from_request(
            "run_first",
            WorkflowFirstRunFinalizeRequest(serverId="srv_first", actor="operator"),
        )
    )["data"]

    assert result["status"] == "blocked"
    assert result["nextAction"] == {
        "code": FIRST_RUN_COMPLETION_PROOF_INVALID,
        "detail": "FIRST_RUN_COMPLETION_PROOF_INVALID: missing savedAt",
        "label": "重新生成首跑完成证明",
        "target": "/workflows/first-run#evidence-bundle",
    }


def test_first_run_finalize_rejects_completion_proof_with_invalid_saved_timestamp(monkeypatch) -> None:
    _patch_first_run_sources(monkeypatch)
    monkeypatch.setattr("apps.api.workflow_first_run_completion_store._now", lambda: "not-a-timestamp")

    result = asyncio.run(
        finalize_first_run_from_request(
            "run_first",
            WorkflowFirstRunFinalizeRequest(serverId="srv_first", actor="operator"),
        )
    )["data"]

    assert result["status"] == "blocked"
    assert result["nextAction"] == {
        "code": FIRST_RUN_COMPLETION_PROOF_INVALID,
        "detail": "FIRST_RUN_COMPLETION_PROOF_INVALID: invalid timestamp savedAt",
        "label": "重新生成首跑完成证明",
        "target": "/workflows/first-run#evidence-bundle",
    }


def test_first_run_finalize_rejects_completion_proof_with_stale_saved_timestamp(monkeypatch) -> None:
    _patch_first_run_sources(monkeypatch)
    monkeypatch.setattr("apps.api.workflow_first_run_completion_store._now", lambda: "2026-06-28T23:59:59Z")

    result = asyncio.run(
        finalize_first_run_from_request(
            "run_first",
            WorkflowFirstRunFinalizeRequest(serverId="srv_first", actor="operator"),
        )
    )["data"]

    assert result["status"] == "blocked"
    assert result["nextAction"] == {
        "code": FIRST_RUN_COMPLETION_PROOF_INVALID,
        "detail": "FIRST_RUN_COMPLETION_PROOF_INVALID: savedAt predates validationCardGeneratedAt",
        "label": "重新生成首跑完成证明",
        "target": "/workflows/first-run#evidence-bundle",
    }


def test_first_run_finalize_returns_typed_blocker_when_completion_proof_store_write_fails(
    monkeypatch,
    tmp_path,
) -> None:
    _patch_first_run_sources(monkeypatch)
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("file blocks completion proof directory creation", encoding="utf-8")
    store_path = blocked_parent / "completion-proofs-v1.json"
    monkeypatch.setattr(
        "apps.api.workflow_first_run_completion_store.get_first_run_completion_proof_store_path",
        lambda: store_path,
    )

    result = asyncio.run(
        finalize_first_run_from_request(
            "run_first",
            WorkflowFirstRunFinalizeRequest(serverId="srv_first", actor="operator"),
        )
    )["data"]

    assert result["status"] == "blocked"
    assert result["nextAction"] == {
        "code": FIRST_RUN_COMPLETION_PROOF_STORE_UNREADABLE,
        "detail": (
            "saved first-run completion proof store is unreadable: "
            "FIRST_RUN_COMPLETION_PROOF_STORE_WRITE_FAILED"
        ),
        "label": "修复本地首跑证明索引",
        "target": "/workflows/first-run#evidence-bundle",
    }


def _completion_proof_record() -> dict[str, object]:
    return {
        "schemaVersion": FIRST_RUN_COMPLETION_PROOF_SCHEMA_VERSION,
        "proofKey": "srv_first|run_first|res_run_first|rpex_full",
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
        "evidenceBundleZipFileRoles": [
            "completion-proof-json",
            "evidence-bundle-json",
            "pilot-handoff",
            "readme",
            "validation-card-json",
            "validation-card-markdown",
        ],
        "savedAt": "2026-06-29T00:30:00Z",
    }
