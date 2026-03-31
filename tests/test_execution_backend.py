from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.execution.execution_backend import (
    BackendCapabilityError,
    BackendDispatchResult,
    CommandBackend,
    NextflowBackend,
)
from core.execution.execution_preparer import PreparationRequest, PreparationResult


class _SSH:
    is_connected = True

    def run(self, cmd: str, timeout: int = 10):
        return (0, "", "")


def _request() -> PreparationRequest:
    return PreparationRequest(
        execution_id="exec_demo",
        tool_id="fastp",
        sample_id="smp_1",
        remote_base="/remote/base",
        descriptor={"id": "fastp", "command_template": "echo ok", "outputs": []},
        merged_params={},
        input_paths={},
        database_paths=None,
        conda_executable="",
    )


def test_command_backend_describes_result_location():
    backend = CommandBackend()
    prepared = PreparationResult(
        execution_id="exec_demo",
        command="echo ok",
        descriptor={"id": "fastp"},
        sample_id="smp_1",
        output_dir="/remote/out",
        task_dir="/remote/out",
    )

    location = backend.describe_result_location(prepared)

    assert location.output_dir == "/remote/out"
    assert location.task_dir == "/remote/out"


def test_command_backend_dispatch_wraps_job_dispatcher(monkeypatch):
    backend = CommandBackend()
    ssh = _SSH()
    prepared = PreparationResult(
        execution_id="exec_demo",
        command="echo ok",
        descriptor={"id": "fastp"},
        sample_id="smp_1",
        output_dir="/remote/out",
        task_dir="/remote/task",
    )
    calls = {}

    def fake_submit(*, ssh_service, wrapped_script, execution_id, task_dir):
        calls["ssh_service"] = ssh_service
        calls["wrapped_script"] = wrapped_script
        calls["execution_id"] = execution_id
        calls["task_dir"] = task_dir
        return "h2o_exec_demo"

    monkeypatch.setattr("core.execution.execution_backend.JobDispatcher.submit", fake_submit)

    result = backend.dispatch("exec_demo", prepared, ssh)

    assert result == BackendDispatchResult(
        execution_id="exec_demo",
        job_id="h2o_exec_demo",
        task_dir="/remote/task",
    )
    assert calls["ssh_service"] is ssh
    assert calls["execution_id"] == "exec_demo"
    assert calls["task_dir"] == "/remote/task"
    assert "echo ok" in calls["wrapped_script"]


def test_command_backend_start_waiting_routes_to_dispatcher():
    backend = CommandBackend()
    dispatcher = MagicMock()
    ssh = _SSH()
    dispatch_result = BackendDispatchResult(
        execution_id="exec_demo",
        job_id="h2o_exec_demo",
        task_dir="/remote/task",
    )

    backend.start_waiting("exec_demo", dispatch_result, ssh, dispatcher)

    dispatcher.start_waiting.assert_called_once_with(
        ssh_service=ssh,
        execution_id="exec_demo",
        job_id="h2o_exec_demo",
        task_dir="/remote/task",
    )


def test_nextflow_backend_loudly_rejects_unimplemented_capabilities():
    backend = NextflowBackend()

    with pytest.raises(BackendCapabilityError):
        backend.prepare(_SSH(), _request())
