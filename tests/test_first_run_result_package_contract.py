from __future__ import annotations

import asyncio
from typing import Any

import pytest

from apps.api.workflow_first_run_finalize_service import (
    WorkflowFirstRunFinalizeRequest,
    finalize_first_run_from_request,
)
from apps.api.workflow_first_run_result_package_contract import (
    evaluate_first_run_result_package,
    is_first_run_result_package_export_required,
    is_first_run_result_package_ledger_mismatch,
)
from tests.test_first_run_validation_card import _exports_for_case, _package, _patch_first_run_sources


@pytest.mark.parametrize(
    ("export_case", "expected_code"),
    [
        ("none", "FIRST_RUN_RESULT_PACKAGE_REQUIRED"),
        ("metadata-only", "FIRST_RUN_FULL_RESULT_PACKAGE_REQUIRED"),
        ("no-download", "FIRST_RUN_RESULT_PACKAGE_DOWNLOAD_REQUIRED"),
        ("no-hash", "FIRST_RUN_RESULT_PACKAGE_HASH_REQUIRED"),
    ],
)
def test_first_run_result_package_gate_classifies_export_required(
    export_case: str,
    expected_code: str,
) -> None:
    gate = evaluate_first_run_result_package(
        _exports_for_case(export_case),
        result_id="res_run_first",
        workflow_revision_id="wfrev_first",
    )

    assert gate.state == "export_required"
    assert gate.code == expected_code
    assert is_first_run_result_package_export_required(gate.code)


@pytest.mark.parametrize(
    ("package_patch", "expected_code"),
    [
        ({"resultId": "res_other"}, "FIRST_RUN_RESULT_PACKAGE_RESULT_MISMATCH"),
        ({"workflowRevisionId": "wfrev_other"}, "FIRST_RUN_RESULT_PACKAGE_REVISION_MISMATCH"),
    ],
)
def test_first_run_result_package_gate_classifies_ledger_mismatch(
    package_patch: dict[str, Any],
    expected_code: str,
) -> None:
    package = _package("rpex_wrong")
    package.update(package_patch)

    gate = evaluate_first_run_result_package(
        [package],
        result_id="res_run_first",
        workflow_revision_id="wfrev_first",
    )

    assert gate.state == "ledger_mismatch"
    assert gate.code == expected_code
    assert is_first_run_result_package_ledger_mismatch(gate.code)
    assert not is_first_run_result_package_export_required(gate.code)


def test_first_run_finalize_does_not_export_on_package_ledger_mismatch(monkeypatch) -> None:
    package = _package("rpex_wrong")
    package["resultId"] = "res_other"
    _patch_first_run_sources(monkeypatch, exports=[package])

    async def fail_export(*_args, **_kwargs):
        raise AssertionError("finalize must not auto-export when package ledger evidence is inconsistent")

    monkeypatch.setattr("apps.api.workflow_first_run_finalize_service.export_result_package_from_request", fail_export)

    result = asyncio.run(
        finalize_first_run_from_request(
            "run_first",
            WorkflowFirstRunFinalizeRequest(serverId="srv_first", actor="operator"),
        )
    )["data"]

    assert result["status"] == "blocked"
    assert result["nextAction"]["code"] == "FIRST_RUN_RESULT_PACKAGE_RESULT_MISMATCH"
    assert result["nextAction"]["label"] == "检查结果包账本"
    assert result["nextAction"]["target"] == "/workflows/first-run#result-package"
