from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from apps.api.workflow_first_run_completion_proof_contract import FIRST_RUN_COMPLETION_PROOF_INVALID
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
    ("proof_case", "detail"),
    [
        ("missing-package-sha", "FIRST_RUN_COMPLETION_PROOF_INVALID: missing resultPackageSha256"),
        ("result-mismatch", "FIRST_RUN_COMPLETION_PROOF_INVALID: resultId does not match runId"),
        ("bundle-mismatch", "FIRST_RUN_COMPLETION_PROOF_INVALID: evidenceBundleId does not match resultId"),
    ],
)
def test_first_run_finalize_rejects_generated_completion_proof_that_fails_contract(
    monkeypatch,
    proof_case: str,
    detail: str,
) -> None:
    _patch_first_run_sources(monkeypatch)

    async def fake_card(run_id: str, *_, server_id: str | None = None, **__):
        card = (await build_first_run_validation_card_from_request(run_id, server_id=server_id))["data"]
        if proof_case == "missing-package-sha":
            card["resultPackage"]["sha256"] = ""
        elif proof_case == "result-mismatch":
            card["result"]["resultId"] = "res_other"
        elif proof_case == "bundle-mismatch":
            card["pilotHandoff"]["evidenceBundle"]["bundleId"] = "res_other.first-run-evidence"
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
