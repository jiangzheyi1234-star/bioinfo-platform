from __future__ import annotations

from core.app_runtime.managed_extensions import (
    MANAGED_EXTENSION_LIST_SCHEMA_VERSION,
    MANAGED_EXTENSION_MANIFEST_SCHEMA_VERSION,
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
    assert {"install", "start", "repair", "upgrade", "stop", "prune", "uninstall", "tokenRotate"} <= action_ids
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
