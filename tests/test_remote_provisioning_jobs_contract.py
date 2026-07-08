from __future__ import annotations

import pytest

from core.app_runtime import remote_provisioning_jobs as jobs
from core.app_runtime.errors import RuntimeServiceError


def _patch_runtime_config(monkeypatch: pytest.MonkeyPatch) -> dict:
    state: dict = {}

    def get_runtime_config() -> dict:
        return dict(state)

    def save_runtime_config(config: dict) -> None:
        state.clear()
        state.update(config)

    monkeypatch.setattr(jobs.runtime_config, "get_runtime_config", get_runtime_config)
    monkeypatch.setattr(jobs.runtime_config, "save_runtime_config", save_runtime_config)
    return state


def test_remote_provisioning_job_store_records_state_transitions(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _patch_runtime_config(monkeypatch)

    job = jobs._create_remote_provisioning_job_record(
        server_id="server-localhost",
        action="ensure-runner",
        display_target="localhost",
    )
    queued = jobs._list_remote_provisioning_job_queue()

    assert job["status"] == "queued"
    assert queued["items"][0]["jobId"] == job["jobId"]
    assert queued["activeCount"] == 1
    assert state[jobs.REMOTE_PROVISIONING_CONFIG_KEY][0]["displayTarget"] == "localhost"

    running = jobs._start_remote_provisioning_job(job["jobId"])
    assert running is not None
    assert running["status"] == "running"
    assert running["stage"] == "bootstrap"

    finished = jobs._finish_remote_provisioning_job(
        job["jobId"],
        status="succeeded",
        stage="ready",
        message="Remote runner provisioning completed.",
        result={"serverId": "server-localhost", "health": {"ready": True}},
    )
    assert finished is not None
    assert finished["status"] == "succeeded"
    assert finished["finishedAt"]
    assert finished["result"]["serverId"] == "server-localhost"

    queue = jobs._list_remote_provisioning_job_queue()
    assert queue["activeCount"] == 0
    assert queue["statusCounts"]["succeeded"] == 1
    assert len(queue["items"][0]["events"]) == 3


def test_remote_provisioning_cancel_is_explicit_about_running_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime_config(monkeypatch)
    queued = jobs._create_remote_provisioning_job_record(
        server_id="server-localhost",
        action="ensure-runner",
    )
    cancelled = jobs._cancel_remote_provisioning_job(queued["jobId"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancelledAt"]

    running = jobs._create_remote_provisioning_job_record(
        server_id="server-localhost",
        action="ensure-runner",
    )
    jobs._start_remote_provisioning_job(running["jobId"])
    with pytest.raises(RuntimeServiceError) as exc_info:
        jobs._cancel_remote_provisioning_job(running["jobId"])

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["reasonCode"] == "REMOTE_PROVISIONING_RUNNING_CANCEL_UNSUPPORTED"


def test_remote_provisioning_action_validation_fails_loudly() -> None:
    with pytest.raises(RuntimeServiceError) as exc_info:
        jobs._normalize_action("shell-out")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["reasonCode"] == "REMOTE_PROVISIONING_UNSUPPORTED_ACTION"
