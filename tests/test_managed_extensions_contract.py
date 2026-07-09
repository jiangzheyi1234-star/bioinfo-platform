from __future__ import annotations

from threading import RLock

import pytest

from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.managed_extensions import (
    MANAGED_EXTENSION_ACTION_RESULT_SCHEMA_VERSION,
    MANAGED_EXTENSION_LIST_SCHEMA_VERSION,
    MANAGED_EXTENSION_MANIFEST_SCHEMA_VERSION,
    ManagedExtensionOperationsMixin,
    REMOTE_EXECUTOR_EXTENSION_ID,
    build_managed_extensions,
)


def _ready_profile() -> dict:
    return {
        "schemaVersion": "server-profile.v1",
        "profileId": "default",
        "serverId": "srv_test",
        "displayName": "ubuntu@10.10.0.12",
        "connected": True,
        "connection": {"host": "10.10.0.12"},
        "runner": {
            "state": "ready",
            "ready": True,
            "message": "Remote runner control plane is ready.",
            "reasonCode": "",
            "installedVersion": "0.1.5-control-plane",
            "runnerMode": "systemd_user",
            "deploymentAction": "reused",
            "health": {
                "workflowRuntime": {
                    "ok": True,
                    "version": "0.1.4",
                    "snakemakeVersion": "9.19.0",
                    "message": "Workflow runtime is ready.",
                }
            },
        },
    }


def test_managed_extensions_project_remote_runner_as_backend_manifest_item() -> None:
    items = build_managed_extensions(
        active_server_profile=_ready_profile(),
        active_remote_provisioning_job=None,
        remote_provisioning_queue={"items": [], "total": 0},
    )

    remote_runner = next(item for item in items if item["id"] == REMOTE_EXECUTOR_EXTENSION_ID)

    assert remote_runner["kind"] == "runtime"
    assert remote_runner["installState"] == "enabled"
    assert remote_runner["health"] == "ready"
    assert remote_runner["installedVersion"] == "0.1.5-control-plane"
    assert remote_runner["serverId"] == "srv_test"
    assert remote_runner["manifest"]["schemaVersion"] == MANAGED_EXTENSION_MANIFEST_SCHEMA_VERSION
    assert remote_runner["manifest"]["kind"] == "managed-runtime"
    assert remote_runner["manifest"]["requiresServerProfile"] is True
    assert remote_runner["manifest"]["artifactSpec"]["provider"] == "remote-runner-release-manifest"
    action_ids = {action["id"] for action in remote_runner["manifest"]["actions"]}
    assert {"install", "repair", "update", "uninstall"} == action_ids
    assert all(action["type"] == "managed-extension-action" for action in remote_runner["manifest"]["actions"])
    assert remote_runner["manifest"]["stateProjection"]["source"] == "server-profile+remote-provisioning"


def test_managed_extensions_project_runtime_and_tool_capabilities() -> None:
    items = build_managed_extensions(
        active_server_profile=_ready_profile(),
        active_remote_provisioning_job=None,
        remote_provisioning_queue={"items": [], "total": 0},
    )

    assert MANAGED_EXTENSION_LIST_SCHEMA_VERSION == "h2ometa.managed-extension-list.v1"
    workflow_runtime = next(item for item in items if item["id"] == "h2ometa-workflow-runtime")
    tool_directory = next(item for item in items if item["id"] == "h2ometa-tool-directory")

    assert workflow_runtime["installedVersion"] == "0.1.4"
    assert workflow_runtime["detailLabel"] == "Snakemake 9.19.0"
    assert workflow_runtime["manifest"]["schemaVersion"] == MANAGED_EXTENSION_MANIFEST_SCHEMA_VERSION
    assert tool_directory["enabled"] is True
    assert any(capability["id"] == "tool-prepare" for capability in tool_directory["capabilities"])


def test_managed_extensions_project_repair_state_from_runner_diagnostics() -> None:
    profile = _ready_profile()
    profile["runner"].update(
        {
            "ready": False,
            "state": "repair_needed",
            "message": "Remote end closed connection without response",
            "reasonCode": "RUNNER_STOP_DIAGNOSTICS_UNAVAILABLE",
            "installedVersion": "0.1.5-control-plane",
        }
    )

    items = build_managed_extensions(
        active_server_profile=profile,
        active_remote_provisioning_job=None,
        remote_provisioning_queue={"items": [], "total": 0},
    )
    remote_runner = next(item for item in items if item["id"] == REMOTE_EXECUTOR_EXTENSION_ID)

    assert remote_runner["installState"] == "failed"
    assert remote_runner["healthLabel"] == "需要修复"
    assert remote_runner["primaryActionLabel"] == "修复"


class _FakeManagedExtensionRuntime(ManagedExtensionOperationsMixin):
    def __init__(self, profile: dict | None = None, record: dict | None = None) -> None:
        self._lock = RLock()
        self._profile = profile or _ready_profile()
        self._record = record or {"bootstrap_version": "0.1.5-control-plane"}
        self.created_jobs: list[tuple[str, dict]] = []
        self.previewed_server_id = ""
        self.uninstalled: tuple[str, str] | None = None

    def _ensure_initialized(self) -> None:
        return None

    def list_server_profiles(self) -> dict:
        return {
            "data": {
                "items": [self._profile],
                "total": 1,
                "activeProfileId": self._profile["profileId"],
                "defaultProfileId": self._profile["profileId"],
            }
        }

    def list_remote_provisioning_job_queue(self, *, status: str = "", limit: int = 12, offset: int = 0) -> dict:
        return {"data": {"items": [], "total": 0, "limit": limit, "offset": offset, "status": status}}

    def _get_server_registry_entry(self, server_id: str) -> dict:
        assert server_id == self._profile["serverId"]
        return self._record

    def create_remote_provisioning_job(self, server_id: str, payload: dict) -> dict:
        self.created_jobs.append((server_id, payload))
        return {
            "data": {
                "jobId": "remote-provisioning-test",
                "serverId": server_id,
                "action": payload["action"],
                "status": "queued",
                "stage": "queued",
                "message": "queued",
                "createdAt": "2026-07-09T00:00:00Z",
                "updatedAt": "2026-07-09T00:00:00Z",
            }
        }

    def preview_runner_uninstall(self, server_id: str) -> dict:
        self.previewed_server_id = server_id
        return {
            "schemaVersion": "h2ometa.runner-uninstall-plan.v1",
            "planHash": "a" * 64,
            "targetCount": 2,
            "preservedPaths": [{"path": "shared"}],
        }

    def run_runner_uninstall(self, server_id: str, *, plan_hash: str) -> dict:
        self.uninstalled = (server_id, plan_hash)
        return {
            "data": {
                "schemaVersion": "h2ometa.runner-uninstall-result.v1",
                "planHash": plan_hash,
                "removedTargetCount": 2,
            }
        }


def test_managed_extension_action_install_dispatches_remote_provisioning_job() -> None:
    runtime = _FakeManagedExtensionRuntime()

    result = runtime.execute_managed_extension_action(
        REMOTE_EXECUTOR_EXTENSION_ID,
        {"action": "install", "serverId": "srv_test"},
    )["data"]

    assert result["schemaVersion"] == MANAGED_EXTENSION_ACTION_RESULT_SCHEMA_VERSION
    assert result["jobKind"] == "remote-provisioning"
    assert result["job"]["action"] == "ensure-runner"
    assert runtime.created_jobs == [("srv_test", {"action": "ensure-runner"})]


def test_managed_extension_action_update_and_repair_map_to_runner_lifecycle_jobs() -> None:
    repair_profile = _ready_profile()
    repair_profile["runner"].update(
        {
            "ready": False,
            "message": "Remote end closed connection without response",
            "reasonCode": "RUNNER_BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE",
        }
    )
    runtime = _FakeManagedExtensionRuntime(repair_profile)

    repair = runtime.execute_managed_extension_action(REMOTE_EXECUTOR_EXTENSION_ID, {"action": "install"})["data"]
    update = runtime.execute_managed_extension_action(REMOTE_EXECUTOR_EXTENSION_ID, {"action": "update"})["data"]

    assert repair["job"]["action"] == "repair-runner"
    assert update["job"]["action"] == "upgrade-runner"


def test_managed_extension_action_uninstall_requires_preview_and_confirmation() -> None:
    runtime = _FakeManagedExtensionRuntime()

    preview = runtime.execute_managed_extension_action(
        REMOTE_EXECUTOR_EXTENSION_ID,
        {"action": "uninstall", "mode": "preview"},
    )["data"]

    assert preview["status"] == "preview"
    assert preview["plan"]["planHash"] == "a" * 64
    assert runtime.previewed_server_id == "srv_test"

    with pytest.raises(RuntimeServiceError) as missing_confirmation:
        runtime.execute_managed_extension_action(
            REMOTE_EXECUTOR_EXTENSION_ID,
            {"action": "uninstall", "mode": "run", "planHash": "a" * 64},
        )
    assert missing_confirmation.value.detail["reasonCode"] == "MANAGED_EXTENSION_CONFIRMATION_REQUIRED"

    run = runtime.execute_managed_extension_action(
        REMOTE_EXECUTOR_EXTENSION_ID,
        {
            "action": "uninstall",
            "mode": "run",
            "confirmation": "uninstall-runner-control-plane",
            "planHash": "a" * 64,
        },
    )["data"]

    assert run["status"] == "succeeded"
    assert run["result"]["removedTargetCount"] == 2
    assert runtime.uninstalled == ("srv_test", "a" * 64)


def test_managed_extension_action_fails_loudly_for_unsupported_targets() -> None:
    runtime = _FakeManagedExtensionRuntime()

    with pytest.raises(RuntimeServiceError) as unsupported_extension:
        runtime.execute_managed_extension_action("h2ometa-tool-directory", {"action": "install"})
    assert unsupported_extension.value.detail["reasonCode"] == "MANAGED_EXTENSION_NOT_EXECUTABLE"

    with pytest.raises(RuntimeServiceError) as unsupported_action:
        runtime.execute_managed_extension_action(REMOTE_EXECUTOR_EXTENSION_ID, {"action": "enable"})
    assert unsupported_action.value.detail["reasonCode"] == "MANAGED_EXTENSION_ACTION_UNSUPPORTED"
