from __future__ import annotations

import asyncio
import threading
from typing import Any

from apps.api.models import (
    UploadSubmitRequest,
    WorkflowDesignDraftCompileRequest,
    WorkflowDesignDraftCreateRequest,
    WorkflowDesignDraftForkRequest,
    WorkflowDesignDraftUpdateRequest,
)
from apps.api.submission_routes import upload_file
from apps.api.workflow_design_routes import (
    compile_workflow_design_draft_api,
    create_workflow_design_draft_api,
    delete_workflow_design_draft_api,
    fork_workflow_design_draft_api,
    get_workflow_design_draft_api,
    list_workflow_design_drafts_api,
    update_workflow_design_draft_api,
)
from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.managers.workflow import WorkflowManager
from core.app_runtime.runner_ops import RunnerOperationsMixin
from core.contracts.workflow_design_remote_endpoints import (
    WORKFLOW_DESIGN_DRAFT_COMPILE,
    WORKFLOW_DESIGN_DRAFT_CREATE,
    WORKFLOW_DESIGN_DRAFT_FORK,
    WORKFLOW_DESIGN_DRAFT_DELETE,
    WORKFLOW_DESIGN_DRAFT_LIST,
    WORKFLOW_DESIGN_DRAFT_PLAN,
    WORKFLOW_DESIGN_DRAFT_READ,
    WORKFLOW_DESIGN_DRAFT_UPDATE,
)


class FakeRemoteRunnerManager:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def call_remote_endpoint(self, **kwargs) -> dict[str, Any]:
        self.calls.append(kwargs)
        endpoint_id = kwargs["endpoint_id"]
        if endpoint_id == WORKFLOW_DESIGN_DRAFT_PLAN:
            return {"valid": True}
        if endpoint_id == WORKFLOW_DESIGN_DRAFT_COMPILE:
            return {"layout": {"snakefile": "workflow/Snakefile"}}
        if endpoint_id == WORKFLOW_DESIGN_DRAFT_CREATE:
            return {"draftId": "wfd_created"}
        if endpoint_id == WORKFLOW_DESIGN_DRAFT_UPDATE:
            return {"draftId": kwargs["path_values"]["draft_id"], "revision": 2}
        if endpoint_id == WORKFLOW_DESIGN_DRAFT_FORK:
            return {"draftId": "wfd_forked", "parentDraftId": kwargs["path_values"]["draft_id"]}
        if endpoint_id == WORKFLOW_DESIGN_DRAFT_LIST:
            return [{"draftId": "wfd_listed"}]
        if endpoint_id == WORKFLOW_DESIGN_DRAFT_READ:
            return {"draftId": kwargs["path_values"]["draft_id"]}
        if endpoint_id == WORKFLOW_DESIGN_DRAFT_DELETE:
            return {"draftId": kwargs["path_values"]["draft_id"], "deleted": True}
        raise AssertionError(f"unexpected endpoint: {endpoint_id}")


class FakeRunnerOps(RunnerOperationsMixin):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.manager = FakeRemoteRunnerManager()
        self._service_locator = type("ServiceLocator", (), {"remote_runner_manager": self.manager})()
        self.selected_server_id = ""
        self.workflows = WorkflowManager(self)

    def _ensure_initialized(self) -> None:
        return None

    def _require_existing_runner_ready(self, *, preferred_server_id: str | None = None):
        self.selected_server_id = preferred_server_id or "default"
        return "srv_demo", object(), {"ready": True}


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def compile_workflow_design_draft(self, draft_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((draft_id, payload))
        return {"data": {"layout": {"snakefile": "workflow/Snakefile"}}}

    def create_workflow_design_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create", payload))
        return {"data": {"draftId": "wfd_created"}}

    def update_workflow_design_draft(self, draft_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((draft_id, payload))
        return {"data": {"draftId": draft_id, "revision": 2}}

    def fork_workflow_design_draft(self, draft_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((draft_id, payload))
        return {"data": {"draftId": "wfd_forked", "parentDraftId": draft_id}}

    def upload_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("upload", payload))
        return {"uploadId": "upl_demo", "filename": payload["filename"]}

    def list_workflow_design_drafts(self, *, server_id: str | None = None) -> dict[str, Any]:
        self.calls.append(("list", {"serverId": server_id}))
        return {"data": {"items": []}}

    def get_workflow_design_draft(self, draft_id: str, *, server_id: str | None = None) -> dict[str, Any]:
        self.calls.append((draft_id, {"serverId": server_id}))
        return {"data": {"draftId": draft_id}}

    def delete_workflow_design_draft(self, draft_id: str, *, server_id: str | None = None) -> dict[str, Any]:
        self.calls.append((draft_id, {"serverId": server_id}))
        return {"data": {"draftId": draft_id, "deleted": True}}


def _workflow_design_draft() -> dict[str, Any]:
    return {
        "contractVersion": "workflow-design-draft-v1",
        "engine": "snakemake",
        "metadata": {
            "name": "Local selected runner draft",
            "description": "",
            "projectId": "proj_local",
            "tags": [],
        },
        "inputs": [
            {
                "id": "reads",
                "role": "input",
                "path": "inputs/reads.fastq",
            }
        ],
        "nodes": [
            {
                "id": "qc",
                "toolRevisionId": "bioconda::qc=1.0#fixture",
                "inputs": {"reads": {"fromInput": "input"}},
                "params": {},
                "runtime": {},
                "resources": {},
                "outputs": {},
                "metadata": {},
                "provenance": {},
            }
        ],
        "edges": [],
        "resources": {"bindings": {}, "metadata": {}},
        "outputs": [],
        "provenance": {},
    }


def test_local_compile_route_passes_selected_server_id(monkeypatch) -> None:
    runtime = FakeRuntime()
    monkeypatch.setattr("apps.api.workflow_design_service.runtime_service", lambda: runtime)

    result = asyncio.run(
        compile_workflow_design_draft_api(
            "wfd_demo",
            WorkflowDesignDraftCompileRequest(serverId="srv_demo"),
        )
    )

    assert result["data"]["layout"]["snakefile"] == "workflow/Snakefile"
    assert runtime.calls == [("wfd_demo", {"serverId": "srv_demo"})]


def test_local_write_routes_pass_selected_server_id(monkeypatch) -> None:
    runtime = FakeRuntime()
    monkeypatch.setattr("apps.api.workflow_design_service.runtime_service", lambda: runtime)

    draft = _workflow_design_draft()
    created = asyncio.run(
        create_workflow_design_draft_api(
            WorkflowDesignDraftCreateRequest(serverId="srv_demo", draft=draft),
        )
    )
    updated = asyncio.run(
        update_workflow_design_draft_api(
            "wfd_demo",
            WorkflowDesignDraftUpdateRequest(serverId="srv_demo", draft=draft, expectedRevision=1),
        )
    )
    forked = asyncio.run(
        fork_workflow_design_draft_api(
            "wfd_demo",
            WorkflowDesignDraftForkRequest(serverId="srv_demo", name="Forked local draft"),
        )
    )

    assert created["data"]["draftId"] == "wfd_created"
    assert updated["data"] == {"draftId": "wfd_demo", "revision": 2}
    assert forked["data"] == {"draftId": "wfd_forked", "parentDraftId": "wfd_demo"}
    assert runtime.calls[0][0] == "create"
    assert runtime.calls[0][1]["serverId"] == "srv_demo"
    assert runtime.calls[1][0] == "wfd_demo"
    assert runtime.calls[1][1]["serverId"] == "srv_demo"
    assert runtime.calls[1][1]["expectedRevision"] == 1
    assert runtime.calls[2] == ("wfd_demo", {"serverId": "srv_demo", "name": "Forked local draft"})


def test_runtime_write_routes_strip_local_server_id_before_remote_forwarding() -> None:
    runner = FakeRunnerOps()

    created = runner.create_workflow_design_draft(
        {"serverId": "srv_demo", "draft": {"contractVersion": "workflow-design-draft-v1"}}
    )
    updated = runner.update_workflow_design_draft(
        "wfd_demo",
        {
            "serverId": "srv_demo",
            "draft": {"contractVersion": "workflow-design-draft-v1"},
            "expectedRevision": 1,
        },
    )
    forked = runner.fork_workflow_design_draft(
        "wfd_demo",
        {"serverId": "srv_demo", "name": "Forked local draft"},
    )

    assert created["data"] == {"draftId": "wfd_created"}
    assert updated["data"] == {"draftId": "wfd_demo", "revision": 2}
    assert forked["data"] == {"draftId": "wfd_forked", "parentDraftId": "wfd_demo"}
    assert runner.selected_server_id == "srv_demo"
    assert runner.manager.calls[0]["payload"] == {"draft": {"contractVersion": "workflow-design-draft-v1"}}
    assert runner.manager.calls[1]["payload"] == {
        "draft": {"contractVersion": "workflow-design-draft-v1"},
        "expectedRevision": 1,
    }
    assert runner.manager.calls[2]["payload"] == {"name": "Forked local draft"}


def test_runtime_read_routes_call_workflow_design_endpoints() -> None:
    runner = FakeRunnerOps()

    listed = runner.list_workflow_design_drafts(server_id="srv_demo")
    fetched = runner.get_workflow_design_draft("wfd_demo", server_id="srv_demo")
    deleted = runner.delete_workflow_design_draft("wfd_demo", server_id="srv_demo")

    assert listed == {"data": {"items": [{"draftId": "wfd_listed"}]}}
    assert fetched == {"data": {"draftId": "wfd_demo"}}
    assert deleted == {"data": {"draftId": "wfd_demo", "deleted": True}}
    assert runner.selected_server_id == "srv_demo"
    assert runner.manager.calls == [
        {
            "server_id": "srv_demo",
            "ssh_service": runner.manager.calls[0]["ssh_service"],
            "server_record": {"ready": True},
            "endpoint_id": WORKFLOW_DESIGN_DRAFT_LIST,
            "path_values": {},
            "query_values": {},
        },
        {
            "server_id": "srv_demo",
            "ssh_service": runner.manager.calls[1]["ssh_service"],
            "server_record": {"ready": True},
            "endpoint_id": WORKFLOW_DESIGN_DRAFT_READ,
            "path_values": {"draft_id": "wfd_demo"},
            "query_values": {},
        },
        {
            "server_id": "srv_demo",
            "ssh_service": runner.manager.calls[2]["ssh_service"],
            "server_record": {"ready": True},
            "endpoint_id": WORKFLOW_DESIGN_DRAFT_DELETE,
            "path_values": {"draft_id": "wfd_demo"},
            "query_values": {},
        },
    ]


def test_runtime_plan_rejects_unsupported_local_body_fields() -> None:
    runner = FakeRunnerOps()

    result = runner.plan_workflow_design_draft("wfd_demo", {"serverId": "srv_demo"})

    assert result == {"data": {"valid": True}}
    assert runner.selected_server_id == "srv_demo"
    assert runner.manager.calls[0]["payload"] == {}

    try:
        runner.plan_workflow_design_draft("wfd_demo", {"serverId": "srv_demo", "legacyRunSpec": {}})
    except RuntimeServiceError as exc:
        assert str(exc) == "WORKFLOW_DESIGN_PLAN_UNSUPPORTED_FIELD: legacyRunSpec"
    else:
        raise AssertionError("unsupported plan body fields should fail before remote forwarding")
    assert len(runner.manager.calls) == 1

    uninitialized_runner = FakeRunnerOps()
    uninitialized_runner._ensure_initialized = lambda: (_ for _ in ()).throw(RuntimeServiceError("not initialized"))
    try:
        uninitialized_runner.plan_workflow_design_draft("wfd_demo", {"legacyRunSpec": {}})
    except RuntimeServiceError as exc:
        assert str(exc) == "WORKFLOW_DESIGN_PLAN_UNSUPPORTED_FIELD: legacyRunSpec"
    else:
        raise AssertionError("unsupported plan body fields should fail before initialization checks")
    assert uninitialized_runner.manager.calls == []


def test_runtime_compile_rejects_unsupported_local_body_fields() -> None:
    runner = FakeRunnerOps()

    result = runner.compile_workflow_design_draft("wfd_demo", {"serverId": "srv_demo"})

    assert result == {"data": {"layout": {"snakefile": "workflow/Snakefile"}}}
    assert runner.selected_server_id == "srv_demo"
    assert "payload" not in runner.manager.calls[0]

    try:
        runner.compile_workflow_design_draft("wfd_demo", {"serverId": "srv_demo", "legacyRunSpec": {}})
    except RuntimeServiceError as exc:
        assert str(exc) == "WORKFLOW_DESIGN_COMPILE_UNSUPPORTED_FIELD: legacyRunSpec"
    else:
        raise AssertionError("unsupported compile body fields should fail before remote forwarding")
    assert len(runner.manager.calls) == 1

    uninitialized_runner = FakeRunnerOps()
    uninitialized_runner._ensure_initialized = lambda: (_ for _ in ()).throw(RuntimeServiceError("not initialized"))
    try:
        uninitialized_runner.compile_workflow_design_draft("wfd_demo", {"legacyRunSpec": {}})
    except RuntimeServiceError as exc:
        assert str(exc) == "WORKFLOW_DESIGN_COMPILE_UNSUPPORTED_FIELD: legacyRunSpec"
    else:
        raise AssertionError("unsupported compile body fields should fail before initialization checks")
    assert uninitialized_runner.manager.calls == []


def test_local_upload_route_passes_selected_server_id(monkeypatch) -> None:
    runtime = FakeRuntime()
    monkeypatch.setattr("apps.api.submission_service.runtime_service", lambda: runtime)

    result = asyncio.run(
        upload_file(
            UploadSubmitRequest(
                serverId="srv_demo",
                filename="reads.fastq",
                contentBase64="UkVBRFM=",
                mimeType="text/plain",
            )
        )
    )

    assert result["data"] == {"uploadId": "upl_demo", "filename": "reads.fastq"}
    assert runtime.calls == [
        (
            "upload",
            {
                "serverId": "srv_demo",
                "filename": "reads.fastq",
                "contentBase64": "UkVBRFM=",
                "mimeType": "text/plain",
            },
        )
    ]


def test_local_read_routes_pass_selected_server_id(monkeypatch) -> None:
    runtime = FakeRuntime()
    monkeypatch.setattr("apps.api.workflow_design_service.runtime_service", lambda: runtime)

    listed = asyncio.run(list_workflow_design_drafts_api(refresh=True, serverId="srv_demo"))
    fetched = asyncio.run(get_workflow_design_draft_api("wfd_demo", serverId="srv_demo"))
    deleted = asyncio.run(delete_workflow_design_draft_api("wfd_demo", serverId="srv_demo"))

    assert listed["data"]["items"] == []
    assert fetched["data"]["draftId"] == "wfd_demo"
    assert deleted["data"] == {"draftId": "wfd_demo", "deleted": True}
    assert runtime.calls == [
        ("list", {"serverId": "srv_demo"}),
        ("wfd_demo", {"serverId": "srv_demo"}),
        ("wfd_demo", {"serverId": "srv_demo"}),
    ]
