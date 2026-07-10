from __future__ import annotations

from copy import deepcopy
from threading import RLock

import pytest

from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.managed_extension_registry import (
    BUILTIN_REGISTRY_ID,
    ManagedExtensionDriverRegistry,
    ManagedExtensionRegistry,
    REMOTE_EXECUTOR_EXTENSION_ID,
    is_managed_extension_update_available,
)
from core.app_runtime.managed_extensions import (
    MANAGED_EXTENSION_ACTION_RESULT_SCHEMA_VERSION,
    MANAGED_EXTENSION_LIST_SCHEMA_VERSION,
    ManagedExtensionOperationsMixin,
    build_managed_extensions,
)
from core.contracts.managed_extensions import (
    MANAGED_EXTENSION_ACTION_TYPE,
    MANAGED_EXTENSION_MANIFEST_SCHEMA_VERSION,
    ManagedExtensionContractError,
    ManagedExtensionDefinition,
    ManagedExtensionProjectionContext,
    ManagedExtensionRegistryDescriptor,
    validate_managed_extension_manifest,
)
from core.remote_runner.release_manifest import REMOTE_RUNNER_ARTIFACT, WORKFLOW_RUNTIME_ARTIFACT


def _ready_profile() -> dict:
    return {
        "schemaVersion": "server-profile.v1",
        "profileId": "default",
        "serverId": "srv_test",
        "displayName": "ubuntu@10.10.0.12",
        "connected": True,
        "connection": {"host": "10.10.0.12"},
        "hostKeyTrust": {"trusted": True, "fingerprintSha256": "SHA256:test"},
        "runner": {
            "state": "ready",
            "ready": True,
            "message": "Remote runner control plane is ready.",
            "reasonCode": "",
            "installedVersion": REMOTE_RUNNER_ARTIFACT.version,
            "runnerMode": "systemd_user",
            "deploymentAction": "reused",
            "health": {
                "workflowRuntime": {
                    "ok": True,
                    "version": WORKFLOW_RUNTIME_ARTIFACT.version,
                    "snakemakeVersion": "9.19.0",
                    "message": "Workflow runtime is ready.",
                }
            },
        },
    }


def _installable_profile() -> dict:
    profile = _ready_profile()
    profile["runner"] = {
        "state": "not_installed",
        "ready": False,
        "message": "",
        "reasonCode": "",
        "installedVersion": "",
        "runnerMode": "",
        "deploymentAction": "",
        "health": {},
    }
    return profile


def _outdated_profile() -> dict:
    profile = _ready_profile()
    profile["runner"]["installedVersion"] = "0.1.4-control-plane"
    return profile


def _repair_profile() -> dict:
    profile = _ready_profile()
    profile["runner"].update(
        {
            "ready": False,
            "message": "Remote end closed connection without response",
            "reasonCode": "RUNNER_BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE",
        }
    )
    return profile


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
    assert remote_runner["installedVersion"] == REMOTE_RUNNER_ARTIFACT.version
    assert remote_runner["serverId"] == "srv_test"
    assert remote_runner["manifest"]["schemaVersion"] == MANAGED_EXTENSION_MANIFEST_SCHEMA_VERSION
    assert remote_runner["manifest"]["kind"] == "managed-runtime"
    manifest = remote_runner["manifest"]
    assert manifest["registryId"] == BUILTIN_REGISTRY_ID
    assert manifest["placement"] == "remote-executor"
    assert manifest["installTargets"] == [
        {"kind": "server-profile", "label": "远端服务器", "requiresServerProfile": True}
    ]
    distribution = manifest["distribution"]
    assert distribution["latestVersion"] == REMOTE_RUNNER_ARTIFACT.version
    variant = distribution["variants"][0]
    platform = variant["platform"]
    assert variant["archiveName"] == REMOTE_RUNNER_ARTIFACT.archive_filename(platform)
    assert variant["sizeBytes"] == REMOTE_RUNNER_ARTIFACT.size_bytes[platform]
    assert variant["sha256"] == REMOTE_RUNNER_ARTIFACT.sha256[platform]
    assert variant["sbomAvailable"] is True
    assert variant["provenanceAvailable"] is True
    assert variant["signatureAvailable"] is True
    action_ids = {action["id"] for action in remote_runner["manifest"]["actions"]}
    assert {"manage", "install", "repair", "update", "uninstall"} == action_ids
    executable = [action for action in remote_runner["manifest"]["actions"] if action["id"] != "manage"]
    assert all(action["type"] == MANAGED_EXTENSION_ACTION_TYPE for action in executable)
    assert all(action["driver"] == "remote-runner-control-plane" for action in executable)
    assert all(action["requiresConfirmation"] is True for action in executable)
    assert all(action["confirmation"] for action in executable)
    assert remote_runner["manifest"]["stateProjection"]["source"] == "server-profile+remote-provisioning"
    assert remote_runner["latestVersion"] == REMOTE_RUNNER_ARTIFACT.version
    assert remote_runner["updateAvailable"] is False
    assert "update" not in remote_runner["actions"]


def test_managed_extensions_project_runtime_and_tool_capabilities() -> None:
    items = build_managed_extensions(
        active_server_profile=_ready_profile(),
        active_remote_provisioning_job=None,
        remote_provisioning_queue={"items": [], "total": 0},
    )

    assert MANAGED_EXTENSION_LIST_SCHEMA_VERSION == "h2ometa.managed-extension-list.v2"
    workflow_runtime = next(item for item in items if item["id"] == "h2ometa-workflow-runtime")
    tool_directory = next(item for item in items if item["id"] == "h2ometa-tool-directory")

    assert workflow_runtime["installedVersion"] == WORKFLOW_RUNTIME_ARTIFACT.version
    assert workflow_runtime["latestVersion"] == WORKFLOW_RUNTIME_ARTIFACT.version
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
            "installedVersion": REMOTE_RUNNER_ARTIFACT.version,
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


def test_managed_extensions_keep_recovering_runner_as_an_installed_instance() -> None:
    profile = _ready_profile()
    profile["runner"].update(
        {
            "ready": False,
            "state": "recovering",
            "message": "Remote runner is recovering.",
            "reasonCode": "",
        }
    )

    remote_runner = next(
        item
        for item in build_managed_extensions(
            active_server_profile=profile,
            active_remote_provisioning_job=None,
            remote_provisioning_queue={"items": [], "total": 0},
        )
        if item["id"] == REMOTE_EXECUTOR_EXTENSION_ID
    )

    assert remote_runner["installed"] is True
    assert remote_runner["installState"] == "installed"
    assert remote_runner["healthLabel"] == "正在恢复"
    assert remote_runner["primaryAction"] == "install"
    assert remote_runner["primaryActionLabel"] == "继续准备"
    assert remote_runner["actions"] == ["install", "uninstall"]


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


def test_managed_extension_list_exposes_only_the_v2_registry_contract() -> None:
    payload = _FakeManagedExtensionRuntime().list_managed_extensions()["data"]

    assert payload["schemaVersion"] == MANAGED_EXTENSION_LIST_SCHEMA_VERSION
    assert payload["registries"] == [
        {
            "id": BUILTIN_REGISTRY_ID,
            "label": "H2OMeta 内置目录",
            "type": "builtin",
            "priority": 100,
            "packageImport": False,
        }
    ]
    assert "source" not in payload
    assert all("registryId" in item for item in payload["items"])
    assert all(
        "sourceId" not in item and "sourceLabel" not in item and "sourceType" not in item
        for item in payload["items"]
    )


def test_managed_extension_action_install_dispatches_remote_provisioning_job() -> None:
    runtime = _FakeManagedExtensionRuntime(_installable_profile(), record={})

    result = runtime.execute_managed_extension_action(
        REMOTE_EXECUTOR_EXTENSION_ID,
        {
            "action": "install",
            "serverId": "srv_test",
            "confirmation": "install-runner-control-plane",
        },
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
    repair_runtime = _FakeManagedExtensionRuntime(repair_profile)
    repair = repair_runtime.execute_managed_extension_action(
        REMOTE_EXECUTOR_EXTENSION_ID,
        {"action": "repair", "confirmation": "repair-runner-control-plane"},
    )["data"]

    update_runtime = _FakeManagedExtensionRuntime(_outdated_profile())
    update = update_runtime.execute_managed_extension_action(
        REMOTE_EXECUTOR_EXTENSION_ID,
        {"action": "update", "confirmation": "update-runner-control-plane"},
    )["data"]

    assert repair["job"]["action"] == "repair-runner"
    assert update["job"]["action"] == "upgrade-runner"


def test_managed_extension_high_risk_actions_require_backend_confirmation() -> None:
    cases = [
        ("install", _installable_profile()),
        ("repair", _repair_profile()),
        ("update", _outdated_profile()),
    ]
    for action, profile in cases:
        runtime = _FakeManagedExtensionRuntime(profile, record={})
        with pytest.raises(RuntimeServiceError) as missing_confirmation:
            runtime.execute_managed_extension_action(
                REMOTE_EXECUTOR_EXTENSION_ID,
                {"action": action, "serverId": "srv_test"},
            )
        assert missing_confirmation.value.detail["reasonCode"] == "MANAGED_EXTENSION_CONFIRMATION_REQUIRED"
        assert runtime.created_jobs == []


def test_managed_extension_remote_actions_require_persisted_host_key_trust() -> None:
    profile = _installable_profile()
    profile["hostKeyTrust"]["trusted"] = False
    runtime = _FakeManagedExtensionRuntime(profile, record={})

    with pytest.raises(RuntimeServiceError) as untrusted:
        runtime.execute_managed_extension_action(
            REMOTE_EXECUTOR_EXTENSION_ID,
            {
                "action": "install",
                "serverId": "srv_test",
                "confirmation": "install-runner-control-plane",
            },
        )

    assert untrusted.value.detail["reasonCode"] == "MANAGED_EXTENSION_REQUIRES_HOST_KEY_TRUST"
    assert runtime.created_jobs == []


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
    assert unsupported_extension.value.detail["reasonCode"] == "MANAGED_EXTENSION_ACTION_UNSUPPORTED"

    with pytest.raises(RuntimeServiceError) as navigation_action:
        runtime.execute_managed_extension_action("h2ometa-tool-directory", {"action": "manage"})
    assert navigation_action.value.detail["reasonCode"] == "MANAGED_EXTENSION_ACTION_NOT_EXECUTABLE"

    with pytest.raises(RuntimeServiceError) as unsupported_action:
        runtime.execute_managed_extension_action(REMOTE_EXECUTOR_EXTENSION_ID, {"action": "enable"})
    assert unsupported_action.value.detail["reasonCode"] == "MANAGED_EXTENSION_ACTION_UNSUPPORTED"

    with pytest.raises(RuntimeServiceError) as missing_extension:
        runtime.execute_managed_extension_action("missing-extension", {"action": "install"})
    assert missing_extension.value.detail["reasonCode"] == "MANAGED_EXTENSION_NOT_FOUND"

    install_runtime = _FakeManagedExtensionRuntime(_installable_profile(), record={})
    with pytest.raises(RuntimeServiceError) as mismatched_target:
        install_runtime.execute_managed_extension_action(
            REMOTE_EXECUTOR_EXTENSION_ID,
            {
                "action": "install",
                "serverId": "srv_other",
                "confirmation": "install-runner-control-plane",
            },
        )
    assert mismatched_target.value.detail["reasonCode"] == "MANAGED_EXTENSION_SERVER_NOT_FOUND"


def test_managed_extension_manifest_rejects_v1_and_legacy_fields() -> None:
    manifest = deepcopy(_fake_extension_definition().manifest)
    manifest["schemaVersion"] = "h2ometa.managed-extension-manifest.v1"
    with pytest.raises(ManagedExtensionContractError) as unsupported_schema:
        validate_managed_extension_manifest(manifest)
    assert unsupported_schema.value.reason_code == "MANAGED_EXTENSION_MANIFEST_SCHEMA_UNSUPPORTED"

    manifest = deepcopy(_fake_extension_definition().manifest)
    manifest["sourceId"] = "legacy-source"
    with pytest.raises(ManagedExtensionContractError) as legacy_field:
        validate_managed_extension_manifest(manifest)
    assert legacy_field.value.reason_code == "MANAGED_EXTENSION_FIELDS_UNKNOWN"


def test_managed_extension_update_comparison_never_downgrades_or_relabels_equal_core_versions() -> None:
    assert is_managed_extension_update_available("0.1.4-control-plane", "0.1.5-control-plane") is True
    assert is_managed_extension_update_available("0.1.5-control-plane", "0.1.4-control-plane") is False
    assert is_managed_extension_update_available("0.1.5-dev", "0.1.5-control-plane") is False
    assert is_managed_extension_update_available("custom-a", "custom-b") is False


def _fake_extension_projection(
    _definition: ManagedExtensionDefinition,
    _context: ManagedExtensionProjectionContext,
) -> dict:
    return {
        "installed": False,
        "enabled": False,
        "installState": "not_installed",
        "installedVersion": "",
        "latestVersion": "1.0.0",
        "updateAvailable": False,
        "serverId": "",
        "health": "unknown",
        "healthLabel": "可安装",
        "detailLabel": "测试 driver",
        "primaryAction": "install",
        "primaryActionLabel": "安装",
        "actions": ["install"],
    }


def _fake_extension_definition() -> ManagedExtensionDefinition:
    return ManagedExtensionDefinition(
        registry_id="test-registry",
        catalog={
            "id": "test-extension",
            "kind": "plugin",
            "slug": "test-extension",
            "name": "Test Extension",
            "summary": "Driver registry proof.",
            "description": "",
            "icon": "package",
            "publisher": "Tests",
            "categoryIds": ["featured"],
            "tags": ["test"],
            "featured": True,
            "requiresRunner": False,
        },
        manifest={
            "schemaVersion": MANAGED_EXTENSION_MANIFEST_SCHEMA_VERSION,
            "id": "test-extension",
            "registryId": "test-registry",
            "kind": "plugin",
            "displayName": "Test Extension",
            "placement": "control-plane",
            "installTargets": [
                {"kind": "control-plane", "label": "本地控制面", "requiresServerProfile": False}
            ],
            "distribution": {
                "mode": "release-artifact",
                "channel": "stable",
                "delivery": "test",
                "packageType": "zip",
                "latestVersion": "1.0.0",
                "immutable": True,
                "variants": [
                    {
                        "version": "1.0.0",
                        "platform": "any",
                        "archiveName": "test-extension-1.0.0.zip",
                        "sizeBytes": 1,
                        "sha256": "a" * 64,
                        "downloadAvailable": True,
                        "sbomAvailable": False,
                        "provenanceAvailable": False,
                        "attestationAvailable": False,
                        "signatureAvailable": False,
                        "builderId": "",
                        "sourceCommit": "",
                    }
                ],
            },
            "compatibility": {
                "h2ometaApiRange": ">=1,<2",
                "runnerProtocolRange": "*",
                "platforms": ["any"],
                "operatingSystems": ["any"],
                "architectures": ["any"],
                "libc": [],
                "pythonAbi": [],
                "accelerators": [],
                "dependencies": [],
                "conflicts": [],
            },
            "actions": [
                {
                    "id": "install",
                    "label": "安装",
                    "type": MANAGED_EXTENSION_ACTION_TYPE,
                    "driver": "test-driver",
                    "operation": "install",
                }
            ],
            "permissions": [],
            "capabilities": [],
            "stateProjection": {"source": "test"},
        },
        state_projector=_fake_extension_projection,
    )


class _TestManagedExtensionDriver:
    driver_id = "test-driver"

    def execute(self, *, runtime, definition, action, payload, context) -> dict:
        del runtime, payload, context
        return {"data": {"extensionId": definition.id, "action": action["id"], "driver": self.driver_id}}


def test_managed_extension_mixin_dispatches_a_second_driver_without_extension_id_branch() -> None:
    descriptor = ManagedExtensionRegistryDescriptor(
        id="test-registry",
        label="Test Registry",
        type="test",
        priority=1,
        package_import=False,
    )
    runtime = _FakeManagedExtensionRuntime()
    runtime.managed_extension_registry = ManagedExtensionRegistry(
        descriptors=(descriptor,),
        definitions=(_fake_extension_definition(),),
    )
    runtime.managed_extension_driver_registry = ManagedExtensionDriverRegistry((_TestManagedExtensionDriver(),))

    result = runtime.execute_managed_extension_action("test-extension", {"action": "install"})["data"]

    assert result == {"extensionId": "test-extension", "action": "install", "driver": "test-driver"}


def test_managed_extension_mixin_fails_loudly_for_unknown_driver() -> None:
    descriptor = ManagedExtensionRegistryDescriptor(
        id="test-registry",
        label="Test Registry",
        type="test",
        priority=1,
        package_import=False,
    )
    runtime = _FakeManagedExtensionRuntime()
    runtime.managed_extension_registry = ManagedExtensionRegistry(
        descriptors=(descriptor,),
        definitions=(_fake_extension_definition(),),
    )
    runtime.managed_extension_driver_registry = ManagedExtensionDriverRegistry(())

    with pytest.raises(RuntimeServiceError) as unknown_driver:
        runtime.execute_managed_extension_action("test-extension", {"action": "install"})

    assert unknown_driver.value.detail["reasonCode"] == "MANAGED_EXTENSION_DRIVER_NOT_FOUND"
