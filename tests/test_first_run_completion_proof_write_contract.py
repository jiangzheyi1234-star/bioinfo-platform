from __future__ import annotations

import asyncio

from apps.api.workflow_first_run_completion_proof_contract import FIRST_RUN_COMPLETION_PROOF_INVALID
from apps.api.workflow_first_run_finalize_service import (
    WorkflowFirstRunFinalizeRequest,
    finalize_first_run_from_request,
)
from apps.api.workflow_first_run_service import build_first_run_validation_card_from_request
from tests.test_first_run_validation_card import _patch_first_run_sources


def test_first_run_finalize_rejects_generated_completion_proof_that_fails_contract(monkeypatch) -> None:
    _patch_first_run_sources(monkeypatch)

    async def fake_card(run_id: str, *_, server_id: str | None = None, **__):
        card = (await build_first_run_validation_card_from_request(run_id, server_id=server_id))["data"]
        card["resultPackage"]["sha256"] = ""
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
        "detail": "FIRST_RUN_COMPLETION_PROOF_INVALID: missing resultPackageSha256",
        "label": "重新生成首跑完成证明",
        "target": "/workflows/first-run#evidence-bundle",
    }
