from __future__ import annotations

import asyncio

import pytest

from apps.api.workflow_first_run_service import (
    WorkflowFirstRunValidationCardUnavailableError,
    build_first_run_validation_card_from_request,
)
from tests.test_first_run_validation_card import _patch_first_run_sources, _run


def test_first_run_validation_card_requires_selected_server_run(monkeypatch) -> None:
    run = _run()
    run["serverId"] = "srv_other"
    _patch_first_run_sources(monkeypatch, run=run)

    with pytest.raises(WorkflowFirstRunValidationCardUnavailableError, match="FIRST_RUN_RUN_SERVER_MISMATCH"):
        asyncio.run(build_first_run_validation_card_from_request("run_first", server_id="srv_first"))
