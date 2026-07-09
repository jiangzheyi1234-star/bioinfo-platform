from __future__ import annotations

from typing import Any

from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.runner_stop_state import requires_explicit_runner_start

MANAGED_EXTENSION_LIST_SCHEMA_VERSION = "h2ometa.managed-extension-list.v1"
MANAGED_EXTENSION_MANIFEST_SCHEMA_VERSION = "h2ometa.managed-extension-manifest.v1"
MANAGED_EXTENSION_ACTION_RESULT_SCHEMA_VERSION = "h2ometa.managed-extension-action-result.v1"
REMOTE_EXECUTOR_EXTENSION_ID = "h2ometa-remote-runner"


class ManagedExtensionOperationsMixin:
    def list_managed_extensions(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            profiles = self.list_server_profiles()["data"]
        active_profile = _active_server_profile(profiles)
        queue = self.list_remote_provisioning_job_queue(status="", limit=12, offset=0)["data"]
        active_job = _active_remote_provisioning_job(queue, active_profile)
        items = build_managed_extensions(
            active_server_profile=active_profile,
            active_remote_provisioning_job=active_job,
            remote_provisioning_queue=queue,
        )
        return {
            "data": {
                "schemaVersion": MANAGED_EXTENSION_LIST_SCHEMA_VERSION,
                "items": items,
                "total": len(items),
                "source": "builtin",
                "activeProfileId": str(profiles.get("activeProfileId") or ""),
                "defaultProfileId": str(profiles.get("defaultProfileId") or ""),
            }
        }

    def execute_managed_extension_action(self, extension_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized_extension_id = str(extension_id or "").strip()
        if normalized_extension_id != REMOTE_EXECUTOR_EXTENSION_ID:
            raise RuntimeServiceError(
                f"Managed extension is not executable: {normalized_extension_id}",
                status_code=404,
                detail={
                    "reasonCode": "MANAGED_EXTENSION_NOT_EXECUTABLE",
                    "extensionId": normalized_extension_id,
                },
            )
        action = str((payload or {}).get("action") or "").strip()
        mode = str((payload or {}).get("mode") or "run").strip()
        if not action:
            raise RuntimeServiceError(
                "Managed extension action is required",
                status_code=400,
                detail={"reasonCode": "MANAGED_EXTENSION_ACTION_REQUIRED", "extensionId": normalized_extension_id},
            )
        with self._lock:
            self._ensure_initialized()
            profiles = self.list_server_profiles()["data"]
            active_profile = _active_server_profile(profiles)
            server_id = _select_action_server_id(payload, active_profile)
            if not active_profile or str(active_profile.get("serverId") or "") != server_id:
                raise RuntimeServiceError(
                    f"Server not found: {server_id}",
                    status_code=404,
                    detail={
                        "reasonCode": "MANAGED_EXTENSION_SERVER_NOT_FOUND",
                        "extensionId": normalized_extension_id,
                        "serverId": server_id,
                    },
                )
            if not bool(active_profile.get("connected")):
                raise RuntimeServiceError(
                    "SSH is not connected",
                    status_code=409,
                    detail={
                        "reasonCode": "MANAGED_EXTENSION_REQUIRES_SSH",
                        "extensionId": normalized_extension_id,
                        "serverId": server_id,
                        "nextAction": "CONNECT_SSH",
                    },
                )
            runner = _record(active_profile, "runner")
            server_record = self._get_server_registry_entry(server_id)

        if action in {"install", "repair", "update"}:
            if mode != "run":
                raise RuntimeServiceError(
                    f"Managed extension action does not support preview: {action}",
                    status_code=400,
                    detail={
                        "reasonCode": "MANAGED_EXTENSION_ACTION_MODE_UNSUPPORTED",
                        "extensionId": normalized_extension_id,
                        "action": action,
                        "mode": mode,
                    },
                )
            provisioning_action = _remote_executor_provisioning_action(
                action=action,
                runner=runner,
                server_record=server_record,
            )
            job = self.create_remote_provisioning_job(server_id, {"action": provisioning_action})["data"]
            return _managed_extension_action_result(
                extension_id=normalized_extension_id,
                action=action,
                server_id=server_id,
                status=str(job.get("status") or "queued"),
                message=str(job.get("message") or ""),
                job_kind="remote-provisioning",
                job=job,
            )
        if action == "uninstall":
            if mode == "preview":
                plan = self.preview_runner_uninstall(server_id)
                return _managed_extension_action_result(
                    extension_id=normalized_extension_id,
                    action=action,
                    server_id=server_id,
                    status="preview",
                    message="Runner uninstall preview is ready.",
                    plan=plan,
                )
            if mode == "run":
                confirmation = str((payload or {}).get("confirmation") or "")
                if confirmation != "uninstall-runner-control-plane":
                    raise RuntimeServiceError(
                        "Runner uninstall confirmation is required",
                        status_code=409,
                        detail={
                            "reasonCode": "MANAGED_EXTENSION_CONFIRMATION_REQUIRED",
                            "extensionId": normalized_extension_id,
                            "action": action,
                            "confirmation": "uninstall-runner-control-plane",
                        },
                    )
                plan_hash = str((payload or {}).get("planHash") or "").strip()
                if not plan_hash:
                    raise RuntimeServiceError(
                        "Runner uninstall planHash is required",
                        status_code=400,
                        detail={
                            "reasonCode": "MANAGED_EXTENSION_PLAN_HASH_REQUIRED",
                            "extensionId": normalized_extension_id,
                            "action": action,
                        },
                    )
                result = self.run_runner_uninstall(server_id, plan_hash=plan_hash)["data"]
                return _managed_extension_action_result(
                    extension_id=normalized_extension_id,
                    action=action,
                    server_id=server_id,
                    status="succeeded",
                    message="Runner control plane was uninstalled.",
                    result=result,
                )
        raise RuntimeServiceError(
            f"Unsupported managed extension action: {action}",
            status_code=400,
            detail={
                "reasonCode": "MANAGED_EXTENSION_ACTION_UNSUPPORTED",
                "extensionId": normalized_extension_id,
                "action": action,
            },
        )


def build_managed_extensions(
    *,
    active_server_profile: dict[str, Any] | None,
    active_remote_provisioning_job: dict[str, Any] | None,
    remote_provisioning_queue: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    connected = bool(active_server_profile and active_server_profile.get("connected"))
    runner = _record(active_server_profile, "runner")
    runner_ready = bool(runner.get("ready"))
    runner_version = str(runner.get("installedVersion") or "")
    runner_repair = _runner_needs_diagnostics_repair(runner)
    provisioning_active = bool(active_remote_provisioning_job)
    workflow_runtime = _workflow_runtime_projection(runner)
    provisioning_total = int((remote_provisioning_queue or {}).get("total") or 0)
    server_id = str((active_server_profile or {}).get("serverId") or "")
    display_name = str((active_server_profile or {}).get("displayName") or "")
    detail_target = display_name or str(_record(active_server_profile, "connection").get("host") or "")

    return [
        _extension_item(
            id=REMOTE_EXECUTOR_EXTENSION_ID,
            kind="runtime",
            slug="remote-runner",
            name="远端执行器",
            summary="通过 SSH 安装、复用和升级 H2OMeta remote runner。",
            description=str(runner.get("message") or ""),
            icon="server",
            publisher="H2OMeta",
            source_id="h2ometa-official",
            source_label="由 H2OMeta 提供",
            source_type="official",
            category_ids=["featured", "runtime"],
            tags=["ssh", "runner", "runtime"],
            featured=True,
            installed=bool(runner_version or runner_ready),
            enabled=runner_ready,
            install_state="installing"
            if provisioning_active
            else "enabled"
            if runner_ready
            else "failed"
            if runner_repair
            else "not_installed"
            if connected
            else "disabled",
            installed_version=runner_version,
            requires_runner=False,
            server_id=server_id,
            health="ready" if runner_ready else "failed" if runner_repair else "warning" if connected else "unknown",
            health_label="已就绪" if runner_ready else "需要修复" if runner_repair else "可安装" if connected else "未连接",
            detail_label=detail_target if connected else "需要 SSH",
            primary_action="manage" if runner_ready else "repair" if runner_repair else "install",
            primary_action_label="安装中"
            if provisioning_active
            else "管理"
            if runner_ready
            else "修复"
            if runner_repair
            else "安装"
            if connected
            else "连接",
            actions=["manage", "update", "uninstall"] if runner_ready else ["repair"] if runner_repair else ["install"],
            capabilities=[
                {"id": "remote-bootstrap", "label": "远端 bootstrap", "operation": "ensure-runner"},
                {"id": "runner-diagnostics-repair", "label": "诊断修复", "operation": "repair-runner"},
                {"id": "runner-health", "label": "健康检查", "operation": "diagnostics"},
            ],
            manifest=_remote_executor_manifest(),
        ),
        _extension_item(
            id="h2ometa-workflow-runtime",
            kind="runtime",
            slug="workflow-runtime",
            name="Workflow Runtime",
            summary="托管 Snakemake、conda-pack runtime 和 workflow profile。",
            description=str(workflow_runtime.get("message") or ""),
            icon="boxes",
            publisher="H2OMeta",
            source_id="remote-environment",
            source_label="远端环境",
            source_type="remote",
            category_ids=["runtime"],
            tags=["snakemake", "conda-pack", "profile"],
            featured=False,
            installed=bool(workflow_runtime["ready"] or runner_ready),
            enabled=bool(workflow_runtime["ready"]),
            install_state="enabled" if workflow_runtime["ready"] else "installed" if runner_ready else "disabled",
            installed_version=str(workflow_runtime.get("version") or ""),
            requires_runner=True,
            server_id=server_id,
            health="ready" if workflow_runtime["ready"] else "warning" if runner_ready else "unknown",
            health_label=str(workflow_runtime["label"]),
            detail_label=str(workflow_runtime["detail"]),
            manage_href="/workflows/plugins",
            primary_action="manage",
            primary_action_label="查看",
            actions=["manage"],
            capabilities=[
                {"id": "snakemake-runtime", "label": "Snakemake runtime"},
                {"id": "workflow-profile", "label": "Workflow profile"},
            ],
            manifest=_managed_manifest(
                extension_id="h2ometa-workflow-runtime",
                kind="runtime",
                display_name="Workflow Runtime",
                actions=[{"id": "view", "type": "navigate", "href": "/workflows/plugins"}],
            ),
        ),
        _extension_item(
            id="h2ometa-tool-directory",
            kind="tool",
            slug="tool-directory",
            name="工具插件",
            summary="管理 Bioconda、conda-forge 与 Snakemake wrapper 工具。",
            description="",
            icon="package",
            publisher="H2OMeta",
            source_id="tool-catalog",
            source_label="工具目录",
            source_type="bioconda",
            category_ids=["featured", "workflow-tools"],
            tags=["bioconda", "conda-forge", "snakemake"],
            featured=True,
            installed=runner_ready,
            enabled=runner_ready,
            install_state="enabled" if runner_ready else "disabled",
            requires_runner=True,
            server_id=server_id,
            health="ready" if runner_ready else "unknown",
            health_label="可用" if runner_ready else "等待 runner",
            detail_label="打开工具页管理",
            manage_href="/workflows/tools",
            primary_action="manage",
            primary_action_label="打开",
            actions=["manage", "install"],
            capabilities=[
                {"id": "tool-search", "label": "工具搜索"},
                {"id": "tool-prepare", "label": "合同验证", "operation": "createToolPrepareJob"},
            ],
            manifest=_managed_manifest(
                extension_id="h2ometa-tool-directory",
                kind="tool",
                display_name="工具插件",
                actions=[{"id": "open-tools", "type": "navigate", "href": "/workflows/tools"}],
            ),
        ),
        _extension_item(
            id="h2ometa-tool-packs",
            kind="tool-pack",
            slug="tool-packs",
            name="Tool Packs",
            summary="导入、启用和复用经过验收的工具能力包。",
            description="",
            icon="layers",
            publisher="H2OMeta",
            source_id="local-import",
            source_label="本地导入",
            source_type="tool-pack",
            category_ids=["workflow-tools", "productivity"],
            tags=["tool-pack", "acceptance", "reuse"],
            featured=False,
            installed=False,
            enabled=False,
            install_state="not_installed",
            requires_runner=True,
            health="unknown",
            health_label="待接入",
            detail_label="复用现有 tool-pack API",
            manage_href="/workflows/tools",
            primary_action="manage",
            primary_action_label="管理",
            actions=["manage", "install", "enable"],
            capabilities=[{"id": "tool-pack-import", "label": "能力包导入"}],
            manifest=_managed_manifest(
                extension_id="h2ometa-tool-packs",
                kind="tool-pack",
                display_name="Tool Packs",
                actions=[{"id": "open-tools", "type": "navigate", "href": "/workflows/tools"}],
            ),
        ),
        _extension_item(
            id="h2ometa-database-packs",
            kind="database-pack",
            slug="database-packs",
            name="数据库包",
            summary="管理参考数据库、资源绑定和数据库验收状态。",
            description="",
            icon="database",
            publisher="H2OMeta",
            source_id="h2ometa-official",
            source_label="由 H2OMeta 提供",
            source_type="official",
            category_ids=["data"],
            tags=["database", "resource", "binding"],
            featured=False,
            installed=False,
            enabled=False,
            install_state="not_installed",
            requires_runner=True,
            health="unknown",
            health_label="可配置",
            detail_label="进入数据库页",
            manage_href="/workflows/databases",
            primary_action="manage",
            primary_action_label="打开",
            actions=["manage"],
            capabilities=[{"id": "database-binding", "label": "数据库绑定"}],
            manifest=_managed_manifest(
                extension_id="h2ometa-database-packs",
                kind="database-pack",
                display_name="数据库包",
                actions=[{"id": "open-databases", "type": "navigate", "href": "/workflows/databases"}],
            ),
        ),
        _extension_item(
            id="h2ometa-operator-skill",
            kind="skill",
            slug="operator-skill",
            name="远端运维技能",
            summary="把远端 smoke、bootstrap 和诊断入口暴露给 agent 工作流。",
            description="",
            icon="sparkles",
            publisher="H2OMeta",
            source_id="h2ometa-official",
            source_label="由 H2OMeta 提供",
            source_type="official",
            category_ids=["featured", "governance"],
            tags=["agent", "smoke", "diagnostics"],
            featured=True,
            installed=True,
            enabled=runner_ready,
            install_state="enabled" if runner_ready else "installed",
            requires_runner=True,
            health="ready" if runner_ready else "warning",
            health_label="可用" if runner_ready else "等待 runner",
            detail_label="Try in chat 入口预留",
            primary_action="try_in_chat",
            primary_action_label="Try in chat",
            actions=["try_in_chat", "manage"],
            capabilities=[
                {"id": "remote-smoke", "label": "远端 smoke", "agentSelectable": True},
                {"id": "bootstrap-diagnostics", "label": "Bootstrap 诊断", "agentSelectable": True},
            ],
            try_in_chat={
                "enabled": runner_ready,
                "capabilityId": "remote-smoke",
                "promptTemplate": "检查当前 H2OMeta 远端服务器和 runner 状态。",
            },
            manifest=_managed_manifest(
                extension_id="h2ometa-operator-skill",
                kind="skill",
                display_name="远端运维技能",
                actions=[{"id": "try-in-chat", "type": "agent-capability", "capabilityId": "remote-smoke"}],
            ),
        ),
    ]


def _extension_item(
    *,
    id: str,
    kind: str,
    slug: str,
    name: str,
    summary: str,
    description: str,
    icon: str,
    publisher: str,
    source_id: str,
    source_label: str,
    source_type: str,
    category_ids: list[str],
    tags: list[str],
    featured: bool,
    installed: bool,
    enabled: bool,
    install_state: str,
    requires_runner: bool,
    health: str,
    health_label: str,
    primary_action: str,
    primary_action_label: str,
    actions: list[str],
    capabilities: list[dict[str, Any]],
    manifest: dict[str, Any],
    installed_version: str = "",
    latest_version: str = "",
    update_available: bool = False,
    server_id: str = "",
    detail_label: str = "",
    manage_href: str = "",
    try_in_chat: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item = {
        "id": id,
        "kind": kind,
        "slug": slug,
        "name": name,
        "summary": summary,
        "description": description,
        "icon": icon,
        "publisher": publisher,
        "sourceId": source_id,
        "sourceLabel": source_label,
        "sourceType": source_type,
        "categoryIds": category_ids,
        "tags": tags,
        "featured": featured,
        "installed": installed,
        "enabled": enabled,
        "installState": install_state,
        "installedVersion": installed_version,
        "latestVersion": latest_version,
        "updateAvailable": update_available,
        "requiresRunner": requires_runner,
        "serverId": server_id,
        "health": health,
        "healthLabel": health_label,
        "detailLabel": detail_label,
        "manageHref": manage_href,
        "primaryAction": primary_action,
        "primaryActionLabel": primary_action_label,
        "actions": actions,
        "capabilities": capabilities,
        "manifest": manifest,
    }
    if try_in_chat is not None:
        item["tryInChat"] = try_in_chat
    return item


def _remote_executor_manifest() -> dict[str, Any]:
    return _managed_manifest(
        extension_id=REMOTE_EXECUTOR_EXTENSION_ID,
        kind="managed-runtime",
        display_name="H2OMeta Remote Executor",
        requires_server_profile=True,
        artifact_spec={
            "provider": "remote-runner-release-manifest",
            "artifactKind": "h2ometa-remote-runner",
            "platforms": ["linux-64"],
        },
        actions=[
            {
                "id": "install",
                "label": "安装",
                "type": "managed-extension-action",
                "operation": "ensure-runner",
                "jobKind": "remote-provisioning",
            },
            {
                "id": "repair",
                "label": "修复",
                "type": "managed-extension-action",
                "operation": "repair-runner",
                "jobKind": "remote-provisioning",
            },
            {
                "id": "update",
                "label": "更新",
                "type": "managed-extension-action",
                "operation": "upgrade-runner",
                "jobKind": "remote-provisioning",
            },
            {
                "id": "uninstall",
                "label": "卸载",
                "type": "managed-extension-action",
                "mode": "preview",
                "confirmation": "uninstall-runner-control-plane",
                "requiresPreview": True,
                "requiresConfirmation": True,
                "risk": "destructive",
            },
        ],
        permissions=[
            {"id": "ssh:connect", "risk": "medium"},
            {"id": "runner:install", "risk": "high"},
            {"id": "runner:uninstall", "risk": "destructive", "confirmation": "uninstall-runner-control-plane"},
        ],
        state_projection={
            "source": "server-profile+remote-provisioning",
            "versionField": "runner.installedVersion",
            "readyField": "runner.ready",
        },
    )


def _managed_manifest(
    *,
    extension_id: str,
    kind: str,
    display_name: str,
    actions: list[dict[str, Any]],
    requires_server_profile: bool = False,
    artifact_spec: dict[str, Any] | None = None,
    permissions: list[dict[str, Any]] | None = None,
    state_projection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": MANAGED_EXTENSION_MANIFEST_SCHEMA_VERSION,
        "id": extension_id,
        "kind": kind,
        "displayName": display_name,
        "requiresServerProfile": requires_server_profile,
        "artifactSpec": artifact_spec or {},
        "actions": actions,
        "permissions": permissions or [],
        "stateProjection": state_projection or {},
    }


def _active_server_profile(profiles: dict[str, Any]) -> dict[str, Any] | None:
    items = profiles.get("items")
    if not isinstance(items, list) or not items:
        return None
    active_profile_id = str(profiles.get("activeProfileId") or "")
    for item in items:
        if isinstance(item, dict) and str(item.get("profileId") or "") == active_profile_id:
            return item
    for item in items:
        if isinstance(item, dict) and item.get("isDefault"):
            return item
    return items[0] if isinstance(items[0], dict) else None


def _select_action_server_id(payload: dict[str, Any], active_server_profile: dict[str, Any] | None) -> str:
    server_id = str((payload or {}).get("serverId") or "").strip()
    if server_id:
        return server_id
    return str((active_server_profile or {}).get("serverId") or "").strip()


def _remote_executor_provisioning_action(
    *,
    action: str,
    runner: dict[str, Any],
    server_record: dict[str, Any],
) -> str:
    if action == "update":
        return "upgrade-runner"
    if action == "repair" or _runner_needs_diagnostics_repair(runner):
        return "repair-runner"
    if requires_explicit_runner_start(server_record):
        return "start-runner"
    return "ensure-runner"


def _managed_extension_action_result(
    *,
    extension_id: str,
    action: str,
    server_id: str,
    status: str,
    message: str,
    job_kind: str = "",
    job: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schemaVersion": MANAGED_EXTENSION_ACTION_RESULT_SCHEMA_VERSION,
        "extensionId": extension_id,
        "action": action,
        "serverId": server_id,
        "status": status,
        "message": message,
    }
    if job_kind:
        data["jobKind"] = job_kind
    if job is not None:
        data["job"] = job
    if plan is not None:
        data["plan"] = plan
    if result is not None:
        data["result"] = result
    return {"data": data}


def _active_remote_provisioning_job(
    queue: dict[str, Any],
    active_server_profile: dict[str, Any] | None,
) -> dict[str, Any] | None:
    server_id = str((active_server_profile or {}).get("serverId") or "")
    for job in queue.get("items") or []:
        if not isinstance(job, dict):
            continue
        if str(job.get("status") or "") not in {"queued", "running"}:
            continue
        if server_id and str(job.get("serverId") or "") != server_id:
            continue
        return job
    return None


def _workflow_runtime_projection(runner: dict[str, Any]) -> dict[str, Any]:
    health = runner.get("health") if isinstance(runner.get("health"), dict) else {}
    workflow_runtime = health.get("workflowRuntime") if isinstance(health.get("workflowRuntime"), dict) else {}
    ok = workflow_runtime.get("ok") is True
    version = str(workflow_runtime.get("version") or "")
    snakemake_version = str(workflow_runtime.get("snakemakeVersion") or "")
    message = str(workflow_runtime.get("message") or "")
    return {
        "ready": ok,
        "version": version,
        "message": message,
        "label": "已就绪" if ok else "需检查" if runner.get("ready") else "等待 runner",
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
    next_value = value.get(key)
    return next_value if isinstance(next_value, dict) else {}
