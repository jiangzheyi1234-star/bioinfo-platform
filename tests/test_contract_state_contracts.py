from __future__ import annotations

import pytest

from core.contracts.state_contracts import (
    ACTIVE_TOOL_PREPARE_JOB_STATUSES,
    PUBLISHED_ATTEMPT_TERMINAL_STATES,
    RESULT_EXPORTABLE_RUN_STATUSES,
    RUN_ATTEMPT_RESUMABLE_STATES,
    RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    TERMINAL_TOOL_PREPARE_JOB_STATUSES,
    ensure_known_run_status,
    is_active_tool_prepare_job_status,
    is_result_exportable_run_status,
    is_terminal_run_status,
    is_terminal_tool_prepare_job_status,
    terminal_status_sql,
)


def test_run_status_contract_defines_terminal_and_exportable_sets() -> None:
    assert TERMINAL_RUN_STATUSES <= RUN_STATUSES
    assert RESULT_EXPORTABLE_RUN_STATUSES <= TERMINAL_RUN_STATUSES
    assert is_terminal_run_status(" completed ")
    assert is_result_exportable_run_status("failed")
    assert not is_result_exportable_run_status("cancelled")


def test_run_status_contract_fails_loudly_for_unknown_states() -> None:
    assert ensure_known_run_status("queued") == "queued"
    with pytest.raises(ValueError, match="RUN_STATUS_UNSUPPORTED: paused"):
        ensure_known_run_status("paused")


def test_attempt_and_prepare_contracts_are_centralized() -> None:
    assert "fenced" not in PUBLISHED_ATTEMPT_TERMINAL_STATES
    assert RUN_ATTEMPT_RESUMABLE_STATES == frozenset({"failed", "cancelled", "fenced"})
    assert ACTIVE_TOOL_PREPARE_JOB_STATUSES == frozenset({"queued", "running"})
    assert "waiting_resource" in TERMINAL_TOOL_PREPARE_JOB_STATUSES
    assert is_active_tool_prepare_job_status(" running ")
    assert is_terminal_tool_prepare_job_status("waiting_resource")
    assert not is_terminal_tool_prepare_job_status("queued")


def test_terminal_status_sql_is_deterministic() -> None:
    assert terminal_status_sql(frozenset({"failed", "completed"})) == "('completed', 'failed')"
