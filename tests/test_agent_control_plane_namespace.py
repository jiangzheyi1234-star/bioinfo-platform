from __future__ import annotations

import json

import pytest

from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.managers.execution import ExecutionManager
from core.contracts.agent_control_plane_namespace import (
    AGENT_CONTROL_PLANE_NAMESPACE_RESERVED,
    require_public_server_id,
)
from core.problem_status import problem_value_error_status_code
from apps.remote_runner.api_models import (
    RunCreateRequest,
    WorkflowTriggerCreateRequest,
    WorkflowTriggerEventRequest,
)
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.submission_service import create_run_from_request
from apps.remote_runner.trigger_service import (
    create_workflow_trigger_from_request,
    submit_workflow_trigger_event_from_request,
)
from apps.remote_runner.trigger_storage import create_workflow_trigger
from tests.helpers.reference_database import (
    make_configured_remote_runner,
    make_remote_runner_config,
)


@pytest.mark.parametrize(
    "server_id",
    [
        "agent-control-plane.v1",
        "agent-control-plane.future",
        " agent-control-plane.v1 ",
    ],
)
def test_public_server_id_rejects_agent_control_plane_namespace(server_id: str) -> None:
    with pytest.raises(ValueError, match=AGENT_CONTROL_PLANE_NAMESPACE_RESERVED):
        require_public_server_id(server_id)


@pytest.mark.parametrize(
    ("server_id", "expected"),
    [
        ("srv_primary", "srv_primary"),
        (" srv_primary ", "srv_primary"),
        ("agent-control-plane", "agent-control-plane"),
    ],
)
def test_public_server_id_normalizes_non_reserved_identity(
    server_id: str, expected: str
) -> None:
    assert require_public_server_id(server_id) == expected


def test_reserved_namespace_error_is_validation_status_on_remote_boundary() -> None:
    assert (
        problem_value_error_status_code(
            f"{AGENT_CONTROL_PLANE_NAMESPACE_RESERVED}: serverId"
        )
        == 422
    )


@pytest.mark.parametrize(
    ("method_name", "payload"),
    [
        (
            "submit_run",
            {
                "serverId": " agent-control-plane.v1 ",
                "runSpec": {"pipelineId": "pipeline_not_inspected"},
            },
        ),
        (
            "create_workflow_trigger",
            {"serverId": " agent-control-plane.v1 "},
        ),
    ],
)
def test_local_execution_facade_rejects_reserved_namespace_before_routing(
    method_name: str,
    payload: dict[str, object],
) -> None:
    manager = ExecutionManager(object())

    with pytest.raises(RuntimeServiceError) as raised:
        getattr(manager, method_name)(payload)

    assert raised.value.status_code == 422
    assert str(raised.value) == f"{AGENT_CONTROL_PLANE_NAMESPACE_RESERVED}: serverId"


def test_public_run_submission_rejects_reserved_namespace_before_readiness(
    tmp_path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)

    with pytest.raises(
        ValueError,
        match=f"{AGENT_CONTROL_PLANE_NAMESPACE_RESERVED}: serverId",
    ):
        create_run_from_request(
            cfg,
            RunCreateRequest(
                serverId="agent-control-plane.v1",
                requestId="req_reserved_run",
                runSpec={"pipelineId": "pipeline_not_inspected"},
            ),
            idempotency_key="idem_reserved_run",
            x_request_id="req_reserved_run",
        )


def test_public_trigger_creation_rejects_reserved_namespace_before_validation(
    tmp_path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)

    with pytest.raises(
        ValueError,
        match=f"{AGENT_CONTROL_PLANE_NAMESPACE_RESERVED}: serverId",
    ):
        create_workflow_trigger_from_request(
            cfg,
            WorkflowTriggerCreateRequest(
                name="Reserved trigger",
                sourceType="manual",
                serverId="agent-control-plane.v1",
                runSpec={"pipelineId": "pipeline_not_inspected"},
            ),
            actor="pytest",
        )


def test_dispatch_rejects_reserved_namespace_from_stored_trigger_without_run(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr(
        "apps.remote_runner.trigger_service.ensure_submission_ready",
        lambda _cfg: None,
    )
    trigger = create_workflow_trigger(
        cfg,
        name="Injected reserved trigger",
        source_type="manual",
        server_id="agent-control-plane.v1",
        pipeline_id="pipeline_not_inspected",
        run_spec={"pipelineId": "pipeline_not_inspected"},
        trigger_spec={},
        enabled=True,
        actor="pytest",
    )

    with pytest.raises(
        ValueError,
        match=f"{AGENT_CONTROL_PLANE_NAMESPACE_RESERVED}: serverId",
    ):
        submit_workflow_trigger_event_from_request(
            cfg,
            trigger["triggerId"],
            WorkflowTriggerEventRequest(
                eventType="manual",
                idempotencyKey="reserved-trigger-event",
            ),
        )

    with get_connection(cfg) as connection:
        run_count = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        dispatch = connection.execute(
            "SELECT state, error_json FROM workflow_trigger_dispatches",
        ).fetchone()
    assert run_count == 0
    assert dispatch["state"] == "failed"
    assert json.loads(dispatch["error_json"]) == {
        "errorType": "ValueError",
        "message": f"{AGENT_CONTROL_PLANE_NAMESPACE_RESERVED}: serverId",
    }
