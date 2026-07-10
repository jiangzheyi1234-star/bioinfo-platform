from __future__ import annotations

import re
from collections.abc import Iterable
from copy import deepcopy
from typing import Any, Protocol

from core.contracts.managed_extensions import (
    MANAGED_EXTENSION_ACTION_TYPE,
    MANAGED_EXTENSION_MANIFEST_SCHEMA_VERSION,
    ManagedExtensionContractError,
    ManagedExtensionDefinition,
    ManagedExtensionDriverNotFoundError,
    ManagedExtensionNotFoundError,
    ManagedExtensionProjectionContext,
    ManagedExtensionRegistryDescriptor,
)
from core.remote_runner.release_manifest import (
    REMOTE_RUNNER_ARTIFACT,
    WORKFLOW_RUNTIME_ARTIFACT,
    ReleaseArtifactSpec,
)
BUILTIN_REGISTRY_ID = "h2ometa-official"
REMOTE_EXECUTOR_EXTENSION_ID = "h2ometa-remote-runner"
WORKFLOW_RUNTIME_EXTENSION_ID = "h2ometa-workflow-runtime"
REMOTE_RUNNER_DRIVER_ID = "remote-runner-control-plane"

_PROJECTED_STATE_FIELDS = {
    "installed",
    "enabled",
    "installState",
    "installedVersion",
    "latestVersion",
    "updateAvailable",
    "serverId",
    "health",
    "healthLabel",
    "detailLabel",
    "primaryAction",
    "primaryActionLabel",
    "actions",
}
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)(?:[-+][0-9A-Za-z.-]+)?$")
class ManagedExtensionDriver(Protocol):
    driver_id: str

    def execute(
        self,
        *,
        runtime: Any, definition: ManagedExtensionDefinition,
        action: dict[str, Any], payload: dict[str, Any],
        context: ManagedExtensionProjectionContext,
    ) -> dict[str, Any]: ...


class ManagedExtensionRegistry:
    def __init__(
        self, *, descriptors: Iterable[ManagedExtensionRegistryDescriptor],
        definitions: Iterable[ManagedExtensionDefinition],
    ) -> None:
        descriptor_items = tuple(descriptors)
        definition_items = tuple(definitions)
        self._descriptors = _unique_by_id(descriptor_items, kind="registry descriptor")
        self._definitions = _unique_by_id(definition_items, kind="managed extension")
        for definition in definition_items:
            if definition.registry_id not in self._descriptors:
                raise ManagedExtensionContractError(
                    "MANAGED_EXTENSION_REGISTRY_NOT_FOUND",
                    path=f"definition[{definition.id}].registryId",
                    message=f"unknown registry: {definition.registry_id}",
                )

    @property
    def descriptors(self) -> tuple[ManagedExtensionRegistryDescriptor, ...]:
        return tuple(
            sorted(
                self._descriptors.values(),
                key=lambda descriptor: (-descriptor.priority, descriptor.id),
            )
        )

    @property
    def definitions(self) -> tuple[ManagedExtensionDefinition, ...]:
        return tuple(self._definitions.values())

    def descriptor_payloads(self) -> list[dict[str, Any]]:
        return [descriptor.to_payload() for descriptor in self.descriptors]

    def require_definition(self, extension_id: str) -> ManagedExtensionDefinition:
        try:
            return self._definitions[extension_id]
        except KeyError as exc:
            raise ManagedExtensionNotFoundError(
                f"Managed extension not found: {extension_id}",
                extensionId=extension_id,
            ) from exc

    def project_definition(
        self, definition: ManagedExtensionDefinition, context: ManagedExtensionProjectionContext,
    ) -> dict[str, Any]:
        item = definition.catalog_payload()
        state = definition.state_projector(definition, context)
        missing = _PROJECTED_STATE_FIELDS - set(state)
        if missing:
            raise ManagedExtensionContractError(
                "MANAGED_EXTENSION_STATE_FIELDS_MISSING",
                path=f"definition[{definition.id}].stateProjection",
                message=f"missing fields: {', '.join(sorted(missing))}",
            )
        item.update(deepcopy(state))
        manifest_action_ids = {str(action["id"]) for action in definition.manifest["actions"]}
        actions = item.get("actions")
        if not isinstance(actions, list) or not actions or any(not isinstance(action, str) for action in actions):
            raise ManagedExtensionContractError(
                "MANAGED_EXTENSION_AVAILABLE_ACTIONS_INVALID",
                path=f"definition[{definition.id}].stateProjection.actions",
                message="available actions must be a non-empty string list",
            )
        unknown_actions = set(actions) - manifest_action_ids
        if unknown_actions:
            raise ManagedExtensionContractError(
                "MANAGED_EXTENSION_AVAILABLE_ACTION_UNDECLARED",
                path=f"definition[{definition.id}].stateProjection.actions",
                message=f"undeclared actions: {', '.join(sorted(unknown_actions))}",
            )
        if item["primaryAction"] not in actions:
            raise ManagedExtensionContractError(
                "MANAGED_EXTENSION_PRIMARY_ACTION_UNAVAILABLE",
                path=f"definition[{definition.id}].stateProjection.primaryAction",
                message="primaryAction must be present in available actions",
            )
        return item

    def project_all(self, context: ManagedExtensionProjectionContext) -> list[dict[str, Any]]:
        return [self.project_definition(definition, context) for definition in self.definitions]


class ManagedExtensionDriverRegistry:
    def __init__(self, drivers: Iterable[ManagedExtensionDriver]) -> None:
        self._drivers: dict[str, ManagedExtensionDriver] = {}
        for driver in drivers:
            driver_id = str(getattr(driver, "driver_id", "") or "").strip()
            if not driver_id or not callable(getattr(driver, "execute", None)):
                raise ManagedExtensionContractError(
                    "MANAGED_EXTENSION_DRIVER_INVALID",
                    path="driverRegistry",
                    message="drivers require a non-empty driver_id and execute method",
                )
            if driver_id in self._drivers:
                raise ManagedExtensionContractError(
                    "MANAGED_EXTENSION_DRIVER_DUPLICATE",
                    path=f"driverRegistry.{driver_id}",
                    message="driver ids must be unique",
                )
            self._drivers[driver_id] = driver

    @property
    def driver_ids(self) -> tuple[str, ...]:
        return tuple(self._drivers)

    def require(self, driver_id: str) -> ManagedExtensionDriver:
        try:
            return self._drivers[driver_id]
        except KeyError as exc:
            raise ManagedExtensionDriverNotFoundError(
                f"Managed extension driver not found: {driver_id}",
                driver=driver_id,
            ) from exc


def release_artifact_distribution(spec: ReleaseArtifactSpec) -> dict[str, Any]:
    platforms = _release_artifact_platforms(spec)
    variants = []
    for platform in platforms:
        variants.append(
            {
                "version": spec.version,
                "platform": platform,
                "archiveName": spec.archive_filename(platform),
                "sizeBytes": int(spec.size_bytes.get(platform) or 0),
                "sha256": str(spec.sha256.get(platform) or ""),
                "downloadAvailable": bool(spec.download_urls.get(platform)),
                "sbomAvailable": bool(spec.sbom_urls.get(platform)),
                "provenanceAvailable": bool(spec.provenance_urls.get(platform)),
                "attestationAvailable": bool(spec.attestation_urls.get(platform)),
                "signatureAvailable": bool(spec.signature_urls.get(platform)),
                "builderId": str(spec.builder_ids.get(platform) or ""),
                "sourceCommit": str(spec.source_commits.get(platform) or ""),
            }
        )
    return {
        "mode": "github-release-asset",
        "channel": "stable",
        "delivery": "control-plane-download+ssh-upload",
        "packageType": "tar.gz",
        "latestVersion": spec.version,
        "immutable": True,
        "variants": variants,
    }


def is_managed_extension_update_available(installed_version: str, latest_version: str) -> bool:
    installed = str(installed_version or "").strip()
    latest = str(latest_version or "").strip()
    if not installed or not latest or installed == latest:
        return False
    installed_match = _VERSION_RE.fullmatch(installed)
    latest_match = _VERSION_RE.fullmatch(latest)
    if not installed_match or not latest_match:
        return False
    installed_parts = tuple(int(part) for part in installed_match.group(1).split("."))
    latest_parts = tuple(int(part) for part in latest_match.group(1).split("."))
    width = max(len(installed_parts), len(latest_parts))
    installed_key = installed_parts + (0,) * (width - len(installed_parts))
    latest_key = latest_parts + (0,) * (width - len(latest_parts))
    return installed_key < latest_key


def build_builtin_managed_extension_registry(
    *, remote_runner_artifact: ReleaseArtifactSpec | None = None,
    workflow_runtime_artifact: ReleaseArtifactSpec | None = None,
) -> ManagedExtensionRegistry:
    runner_spec = remote_runner_artifact or REMOTE_RUNNER_ARTIFACT
    workflow_spec = workflow_runtime_artifact or WORKFLOW_RUNTIME_ARTIFACT
    descriptor = ManagedExtensionRegistryDescriptor(
        id=BUILTIN_REGISTRY_ID,
        label="H2OMeta 内置目录",
        type="builtin",
        priority=100,
        package_import=False,
    )
    definitions = (
        _remote_runner_definition(runner_spec), _workflow_runtime_definition(workflow_spec),
        _tool_directory_definition(), _tool_packs_definition(),
        _database_packs_definition(), _operator_skill_definition(),
    )
    return ManagedExtensionRegistry(descriptors=(descriptor,), definitions=definitions)


def _remote_runner_definition(spec: ReleaseArtifactSpec) -> ManagedExtensionDefinition:
    return _definition(
        extension_id=REMOTE_EXECUTOR_EXTENSION_ID,
        kind="runtime",
        manifest_kind="managed-runtime",
        slug="remote-runner",
        name="远端执行器",
        summary="通过 SSH 安装、复用和升级 H2OMeta remote runner。",
        icon="server",
        categories=["featured", "runtime"],
        tags=["ssh", "runner", "runtime"],
        featured=True,
        requires_runner=False,
        placement="remote-executor",
        install_targets=[{"kind": "server-profile", "label": "远端服务器", "requiresServerProfile": True}],
        distribution=release_artifact_distribution(spec),
        compatibility=_compatibility(_release_artifact_platforms(spec)),
        actions=[
            {"id": "manage", "label": "管理", "type": "navigate", "href": "#remote-runner-detail"},
            _remote_runner_action(
                "install", "安装", "ensure-runner", mode="run", risk="high", confirmation="install-runner-control-plane",
                requiresConfirmation=True,
            ),
            _remote_runner_action(
                "repair", "修复", "repair-runner", mode="run", risk="high", confirmation="repair-runner-control-plane",
                requiresConfirmation=True,
            ),
            _remote_runner_action(
                "update", "更新", "upgrade-runner", mode="run", risk="high", confirmation="update-runner-control-plane",
                requiresConfirmation=True,
            ),
            _remote_runner_action(
                "uninstall", "卸载", "uninstall-runner", job_kind=False, mode="preview",
                confirmation="uninstall-runner-control-plane",
                requiresPreview=True, requiresConfirmation=True, risk="destructive",
            ),
        ],
        permissions=[
            {"id": "ssh:connect", "risk": "medium"},
            {"id": "runner:install", "risk": "high"},
            {"id": "runner:uninstall", "risk": "destructive", "confirmation": "uninstall-runner-control-plane"},
        ],
        capabilities=[
            {"id": "remote-bootstrap", "label": "远端 bootstrap", "operation": "ensure-runner"},
            {"id": "runner-diagnostics-repair", "label": "诊断修复", "operation": "repair-runner"},
            {"id": "runner-health", "label": "健康检查", "operation": "diagnostics"},
        ],
        state_projection={
            "source": "server-profile+remote-provisioning",
            "versionField": "runner.installedVersion",
            "readyField": "runner.ready",
        },
        state_projector=_project_remote_runner,
        catalog_extra={"manageHref": "#remote-runner-detail"},
    )


def _remote_runner_action(
    action_id: str, label: str, operation: str, *, job_kind: bool = True, **extra: Any,
) -> dict[str, Any]:
    action = {
        "id": action_id,
        "label": label,
        "type": MANAGED_EXTENSION_ACTION_TYPE,
        "driver": REMOTE_RUNNER_DRIVER_ID,
        "operation": operation,
        **extra,
    }
    if job_kind:
        action["jobKind"] = "remote-provisioning"
    return action


def _workflow_runtime_definition(spec: ReleaseArtifactSpec) -> ManagedExtensionDefinition:
    return _definition(
        extension_id=WORKFLOW_RUNTIME_EXTENSION_ID,
        kind="runtime",
        slug="workflow-runtime",
        name="Workflow Runtime",
        summary="托管 Snakemake、conda-pack runtime 和 workflow profile。",
        icon="boxes",
        categories=["runtime"],
        tags=["snakemake", "conda-pack", "profile"],
        featured=False,
        requires_runner=True,
        placement="remote-executor",
        install_targets=[{"kind": "server-profile", "label": "远端服务器", "requiresServerProfile": True}],
        distribution=release_artifact_distribution(spec),
        compatibility=_compatibility(_release_artifact_platforms(spec), dependencies=[REMOTE_EXECUTOR_EXTENSION_ID]),
        actions=[{"id": "manage", "label": "查看", "type": "navigate", "href": "/workflows/plugins"}],
        permissions=[],
        capabilities=[
            {"id": "snakemake-runtime", "label": "Snakemake runtime"},
            {"id": "workflow-profile", "label": "Workflow profile"},
        ],
        state_projection={
            "source": "server-profile.runner.health.workflowRuntime",
            "versionField": "runner.health.workflowRuntime.version",
            "readyField": "runner.health.workflowRuntime.ok",
        },
        state_projector=_project_workflow_runtime,
        catalog_extra={"manageHref": "/workflows/plugins"},
    )


def _tool_directory_definition() -> ManagedExtensionDefinition:
    return _definition(
        extension_id="h2ometa-tool-directory",
        kind="tool",
        slug="tool-directory",
        name="工具插件",
        summary="管理 Bioconda、conda-forge 与 Snakemake wrapper 工具。",
        icon="package",
        categories=["featured", "workflow-tools"],
        tags=["bioconda", "conda-forge", "snakemake"],
        featured=True,
        requires_runner=True,
        placement="both",
        install_targets=[{"kind": "server-profile", "label": "远端服务器", "requiresServerProfile": True}],
        distribution=_builtin_distribution("catalog"),
        compatibility=_compatibility(["any"], dependencies=[REMOTE_EXECUTOR_EXTENSION_ID]),
        actions=[{"id": "manage", "label": "打开", "type": "navigate", "href": "/workflows/tools"}],
        permissions=[],
        capabilities=[
            {"id": "tool-search", "label": "工具搜索"},
            {"id": "tool-prepare", "label": "合同验证", "operation": "createToolPrepareJob"},
        ],
        state_projection={"source": "server-profile.runner.ready"},
        state_projector=_project_tool_directory,
        catalog_extra={"manageHref": "/workflows/tools"},
    )


def _tool_packs_definition() -> ManagedExtensionDefinition:
    return _definition(
        extension_id="h2ometa-tool-packs",
        kind="tool-pack",
        slug="tool-packs",
        name="Tool Packs",
        summary="导入、启用和复用经过验收的工具能力包。",
        icon="layers",
        categories=["workflow-tools", "productivity"],
        tags=["tool-pack", "acceptance", "reuse"],
        featured=False,
        requires_runner=True,
        placement="remote-executor",
        install_targets=[{"kind": "server-profile", "label": "远端服务器", "requiresServerProfile": True}],
        distribution=_builtin_distribution("catalog"),
        compatibility=_compatibility(["any"], dependencies=[REMOTE_EXECUTOR_EXTENSION_ID]),
        actions=[{"id": "manage", "label": "管理", "type": "navigate", "href": "/workflows/tools"}],
        permissions=[],
        capabilities=[{"id": "tool-pack-import", "label": "能力包导入"}],
        state_projection={"source": "unmanaged"},
        state_projector=_project_unmanaged_tool_packs,
        catalog_extra={"manageHref": "/workflows/tools"},
    )


def _database_packs_definition() -> ManagedExtensionDefinition:
    return _definition(
        extension_id="h2ometa-database-packs",
        kind="database-pack",
        slug="database-packs",
        name="数据库包",
        summary="管理参考数据库、资源绑定和数据库验收状态。",
        icon="database",
        categories=["data"],
        tags=["database", "resource", "binding"],
        featured=False,
        requires_runner=True,
        placement="data-only",
        install_targets=[{"kind": "server-profile", "label": "远端数据目录", "requiresServerProfile": True}],
        distribution=_builtin_distribution("catalog"),
        compatibility=_compatibility(["any"], dependencies=[REMOTE_EXECUTOR_EXTENSION_ID]),
        actions=[
            {"id": "manage", "label": "打开", "type": "navigate", "href": "/workflows/databases"}
        ],
        permissions=[],
        capabilities=[{"id": "database-binding", "label": "数据库绑定"}],
        state_projection={"source": "unmanaged"},
        state_projector=_project_unmanaged_database_packs,
        catalog_extra={"manageHref": "/workflows/databases"},
    )


def _operator_skill_definition() -> ManagedExtensionDefinition:
    return _definition(
        extension_id="h2ometa-operator-skill",
        kind="skill",
        slug="operator-skill",
        name="远端运维技能",
        summary="把远端 smoke、bootstrap 和诊断入口暴露给 agent 工作流。",
        icon="sparkles",
        categories=["featured", "governance"],
        tags=["agent", "smoke", "diagnostics"],
        featured=True,
        requires_runner=True,
        placement="control-plane",
        install_targets=[{"kind": "control-plane", "label": "本地控制面", "requiresServerProfile": False}],
        distribution=_builtin_distribution("builtin"),
        compatibility=_compatibility(["any"], dependencies=[REMOTE_EXECUTOR_EXTENSION_ID]),
        actions=[
            {"id": "manage", "label": "查看", "type": "navigate", "href": "/workflows/plugins"},
            {"id": "try_in_chat", "label": "Try in chat", "type": "agent-capability", "capabilityId": "remote-smoke"}
        ],
        permissions=[],
        capabilities=[
            {"id": "remote-smoke", "label": "远端 smoke", "agentSelectable": True},
            {"id": "bootstrap-diagnostics", "label": "Bootstrap 诊断", "agentSelectable": True},
        ],
        state_projection={"source": "server-profile.runner.ready"},
        state_projector=_project_operator_skill,
        catalog_extra={"manageHref": "/workflows/plugins"},
    )


def _definition(
    *,
    extension_id: str, kind: str, slug: str,
    name: str, summary: str, icon: str,
    categories: list[str], tags: list[str],
    featured: bool, requires_runner: bool, placement: str,
    install_targets: list[dict[str, Any]],
    distribution: dict[str, Any], compatibility: dict[str, Any],
    actions: list[dict[str, Any]], permissions: list[dict[str, Any]],
    capabilities: list[dict[str, Any]],
    state_projection: dict[str, Any], state_projector: Any,
    manifest_kind: str | None = None,
    catalog_extra: dict[str, Any] | None = None,
) -> ManagedExtensionDefinition:
    catalog = {
        "id": extension_id,
        "kind": kind,
        "slug": slug,
        "name": name,
        "summary": summary,
        "description": "",
        "icon": icon,
        "publisher": "H2OMeta",
        "categoryIds": categories,
        "tags": tags,
        "featured": featured,
        "requiresRunner": requires_runner,
        **(catalog_extra or {}),
    }
    manifest = {
        "schemaVersion": MANAGED_EXTENSION_MANIFEST_SCHEMA_VERSION,
        "id": extension_id,
        "registryId": BUILTIN_REGISTRY_ID,
        "kind": manifest_kind or kind,
        "displayName": name,
        "placement": placement,
        "installTargets": install_targets,
        "distribution": distribution,
        "compatibility": compatibility,
        "actions": actions,
        "permissions": permissions,
        "capabilities": capabilities,
        "stateProjection": state_projection,
    }
    return ManagedExtensionDefinition(
        registry_id=BUILTIN_REGISTRY_ID,
        catalog=catalog,
        manifest=manifest,
        state_projector=state_projector,
    )


def _project_remote_runner(
    definition: ManagedExtensionDefinition, context: ManagedExtensionProjectionContext,
) -> dict[str, Any]:
    profile = context.active_server_profile
    connected = bool(profile and profile.get("connected"))
    runner = _record(profile, "runner")
    ready = bool(runner.get("ready"))
    runner_state = str(runner.get("state") or "")
    installed_version = str(runner.get("installedVersion") or "")
    latest_version = str(definition.manifest["distribution"]["latestVersion"])
    update_available = is_managed_extension_update_available(installed_version, latest_version)
    needs_repair = _runner_needs_diagnostics_repair(runner)
    provisioning = context.active_remote_provisioning_job
    provisioning_active = bool(provisioning)
    if provisioning_active:
        install_state = "updating" if str(provisioning.get("action") or "") == "upgrade-runner" else "installing"
        actions = ["manage"]
        primary_action = "manage"
        primary_label = "更新中" if install_state == "updating" else "安装中"
    elif ready:
        install_state = "enabled"
        actions = ["manage", *(["update"] if update_available else []), "uninstall"]
        primary_action = "update" if update_available else "manage"
        primary_label = "更新" if update_available else "管理"
    elif needs_repair:
        install_state = "failed"
        actions = ["repair", "uninstall"]
        primary_action = "repair"
        primary_label = "修复"
    elif installed_version:
        install_state = "installed"
        actions = ["install", "uninstall"]
        primary_action = "install"
        primary_label = "继续准备" if connected else "连接"
    else:
        install_state = "not_installed" if connected else "disabled"
        actions = ["install"]
        primary_action = "install"
        primary_label = "安装" if connected else "连接"
    detail_target = str((profile or {}).get("displayName") or _record(profile, "connection").get("host") or "")
    return {
        "description": str(runner.get("message") or ""),
        "installed": bool(installed_version or ready),
        "enabled": ready,
        "installState": install_state,
        "installedVersion": installed_version,
        "latestVersion": latest_version,
        "updateAvailable": update_available,
        "serverId": str((profile or {}).get("serverId") or ""),
        "health": "ready" if ready else "failed" if needs_repair else "warning" if connected else "unknown",
        "healthLabel": "已就绪"
        if ready
        else "需要修复"
        if needs_repair
        else "正在恢复"
        if installed_version and runner_state == "recovering"
        else "已安装"
        if installed_version
        else "可安装"
        if connected
        else "未连接",
        "detailLabel": detail_target if connected else "需要 SSH",
        "primaryAction": primary_action,
        "primaryActionLabel": primary_label,
        "actions": actions,
    }


def _project_workflow_runtime(
    definition: ManagedExtensionDefinition, context: ManagedExtensionProjectionContext,
) -> dict[str, Any]:
    profile = context.active_server_profile
    runner = _record(profile, "runner")
    runtime = _workflow_runtime_projection(runner)
    installed_version = str(runtime.get("version") or "")
    latest_version = str(definition.manifest["distribution"]["latestVersion"])
    runner_ready = bool(runner.get("ready"))
    return {
        "description": str(runtime.get("message") or ""),
        "installed": bool(runtime["ready"] or runner_ready),
        "enabled": bool(runtime["ready"]),
        "installState": "enabled" if runtime["ready"] else "installed" if runner_ready else "disabled",
        "installedVersion": installed_version,
        "latestVersion": latest_version,
        "updateAvailable": is_managed_extension_update_available(installed_version, latest_version),
        "serverId": str((profile or {}).get("serverId") or ""),
        "health": "ready" if runtime["ready"] else "warning" if runner_ready else "unknown",
        "healthLabel": str(runtime["label"]),
        "detailLabel": str(runtime["detail"]),
        "primaryAction": "manage",
        "primaryActionLabel": "查看",
        "actions": ["manage"],
    }


def _project_tool_directory(
    definition: ManagedExtensionDefinition, context: ManagedExtensionProjectionContext,
) -> dict[str, Any]:
    del definition
    profile = context.active_server_profile
    ready = bool(_record(profile, "runner").get("ready"))
    return _simple_projection(
        installed=ready,
        enabled=ready,
        install_state="enabled" if ready else "disabled",
        server_id=str((profile or {}).get("serverId") or ""),
        health="ready" if ready else "unknown",
        health_label="可用" if ready else "等待 runner",
        detail_label="打开工具页管理",
        primary_label="打开",
    )


def _project_unmanaged_tool_packs(
    definition: ManagedExtensionDefinition, context: ManagedExtensionProjectionContext,
) -> dict[str, Any]:
    del definition
    return _simple_projection(
        installed=False,
        enabled=False,
        install_state="not_installed",
        server_id=str((context.active_server_profile or {}).get("serverId") or ""),
        health="unknown",
        health_label="待接入",
        detail_label="复用现有 tool-pack API",
        primary_label="管理",
    )


def _project_unmanaged_database_packs(
    definition: ManagedExtensionDefinition, context: ManagedExtensionProjectionContext,
) -> dict[str, Any]:
    del definition
    return _simple_projection(
        installed=False,
        enabled=False,
        install_state="not_installed",
        server_id=str((context.active_server_profile or {}).get("serverId") or ""),
        health="unknown",
        health_label="可配置",
        detail_label="进入数据库页",
        primary_label="打开",
    )


def _project_operator_skill(
    definition: ManagedExtensionDefinition, context: ManagedExtensionProjectionContext,
) -> dict[str, Any]:
    del definition
    profile = context.active_server_profile
    ready = bool(_record(profile, "runner").get("ready"))
    return _simple_projection(
        installed=True,
        enabled=ready,
        install_state="enabled" if ready else "installed",
        server_id=str((profile or {}).get("serverId") or ""),
        health="ready" if ready else "warning",
        health_label="可用" if ready else "等待 runner",
        detail_label="Agent capability",
        primary_label="查看",
    )


def _simple_projection(
    *,
    installed: bool, enabled: bool, install_state: str,
    server_id: str, health: str, health_label: str,
    detail_label: str, primary_label: str,
    primary_action: str = "manage",
    actions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "installed": installed,
        "enabled": enabled,
        "installState": install_state,
        "installedVersion": "",
        "latestVersion": "",
        "updateAvailable": False,
        "serverId": server_id,
        "health": health,
        "healthLabel": health_label,
        "detailLabel": detail_label,
        "primaryAction": primary_action,
        "primaryActionLabel": primary_label,
        "actions": actions or [primary_action],
    }


def _compatibility(platforms: list[str], *, dependencies: list[str] | None = None) -> dict[str, Any]:
    operating_systems: list[str] = []
    architectures: list[str] = []
    for platform in platforms:
        os_name, _, architecture = platform.partition("-")
        operating_systems.append(os_name or platform)
        architectures.append("x86_64" if architecture == "64" else architecture or "any")
    return {
        "h2ometaApiRange": "*",
        "runnerProtocolRange": "*",
        "platforms": list(dict.fromkeys(platforms)),
        "operatingSystems": list(dict.fromkeys(operating_systems)),
        "architectures": list(dict.fromkeys(architectures)),
        "libc": [],
        "pythonAbi": [],
        "accelerators": [],
        "dependencies": dependencies or [],
        "conflicts": [],
    }


def _builtin_distribution(mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "channel": "bundled",
        "delivery": "control-plane",
        "packageType": "none",
        "latestVersion": "",
        "immutable": True,
        "variants": [],
    }


def _release_artifact_platforms(spec: ReleaseArtifactSpec) -> list[str]:
    platforms = {
        spec.default_platform,
        *spec.sha256,
        *spec.size_bytes,
        *spec.download_urls,
        *spec.sbom_urls,
        *spec.provenance_urls,
        *spec.attestation_urls,
        *spec.signature_urls,
        *spec.builder_ids,
        *spec.source_commits,
    }
    return sorted(platform for platform in platforms if platform)


def _workflow_runtime_projection(runner: dict[str, Any]) -> dict[str, Any]:
    health = runner.get("health") if isinstance(runner.get("health"), dict) else {}
    runtime = health.get("workflowRuntime") if isinstance(health.get("workflowRuntime"), dict) else {}
    ready = runtime.get("ok") is True
    message = str(runtime.get("message") or "")
    snakemake_version = str(runtime.get("snakemakeVersion") or "")
    return {
        "ready": ready,
        "version": str(runtime.get("version") or ""),
        "message": message,
        "label": "已就绪" if ready else "需检查" if runner.get("ready") else "等待 runner",
        "detail": f"Snakemake {snakemake_version}" if snakemake_version else message or "未记录",
    }


def _runner_needs_diagnostics_repair(runner: dict[str, Any]) -> bool:
    if not runner or runner.get("ready") is True:
        return False
    reason = str(runner.get("reasonCode") or "")
    message = str(runner.get("message") or "")
    return reason in {
        "RUNNER_BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE",
        "RUNNER_STOP_DIAGNOSTICS_UNAVAILABLE",
        "RUNNER_UPGRADE_DIAGNOSTICS_UNAVAILABLE",
    } or "Remote end closed connection" in message or "execution diagnostics are unavailable" in message


def _record(value: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    nested = value.get(key)
    return nested if isinstance(nested, dict) else {}


def _unique_by_id(items: Iterable[Any], *, kind: str) -> dict[str, Any]:
    indexed: dict[str, Any] = {}
    for item in items:
        item_id = str(getattr(item, "id", "") or "").strip()
        if not item_id:
            raise ManagedExtensionContractError(
                "MANAGED_EXTENSION_REGISTRY_ENTRY_INVALID",
                path=kind,
                message="registry entries require a non-empty id",
            )
        if item_id in indexed:
            raise ManagedExtensionContractError(
                "MANAGED_EXTENSION_REGISTRY_ENTRY_DUPLICATE",
                path=f"{kind}.{item_id}",
                message="registry entry ids must be unique",
            )
        indexed[item_id] = item
    return indexed


BUILTIN_MANAGED_EXTENSION_REGISTRY = build_builtin_managed_extension_registry()
