from __future__ import annotations

from typing import Any

from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.managed_extension_registry import (
    BUILTIN_MANAGED_EXTENSION_REGISTRY,
    REMOTE_RUNNER_DRIVER_ID,
    ManagedExtensionDriverRegistry,
    ManagedExtensionRegistry,
    _runner_needs_diagnostics_repair,
)
from core.app_runtime.runner_stop_state import requires_explicit_runner_start
from core.contracts.managed_extensions import (
    MANAGED_EXTENSION_ACTION_RESULT_SCHEMA_VERSION,
    MANAGED_EXTENSION_ACTION_TYPE,
    MANAGED_EXTENSION_LIST_SCHEMA_VERSION,
    ManagedExtensionActionNotExecutableError,
    ManagedExtensionActionUnavailableError,
    ManagedExtensionDefinition,
    ManagedExtensionProjectionContext,
    ManagedExtensionResolutionError,
)


class RemoteRunnerManagedExtensionDriver:
    driver_id = REMOTE_RUNNER_DRIVER_ID

    def execute(
        self,
        *,
        runtime: Any,
        definition: ManagedExtensionDefinition,
        action: dict[str, Any],
        payload: dict[str, Any],
        context: ManagedExtensionProjectionContext,
    ) -> dict[str, Any]:
        profile = context.active_server_profile
        server_id = _select_action_server_id(payload, profile)
        if not profile or str(profile.get("serverId") or "") != server_id:
            raise RuntimeServiceError(
                f"Server not found: {server_id}",
                status_code=404,
                detail={
                    "reasonCode": "MANAGED_EXTENSION_SERVER_NOT_FOUND",
                    "extensionId": definition.id,
                    "serverId": server_id,
                },
            )
        if not bool(profile.get("connected")):
            raise RuntimeServiceError(
                "SSH is not connected",
                status_code=409,
                detail={
                    "reasonCode": "MANAGED_EXTENSION_REQUIRES_SSH",
                    "extensionId": definition.id,
                    "serverId": server_id,
                    "nextAction": "CONNECT_SSH",
                },
            )
        if not bool(_record(profile, "hostKeyTrust").get("trusted")):
            raise RuntimeServiceError(
                "SSH host key trust is required",
                status_code=409,
                detail={
                    "reasonCode": "MANAGED_EXTENSION_REQUIRES_HOST_KEY_TRUST",
                    "extensionId": definition.id,
                    "serverId": server_id,
                    "nextAction": "TRUST_SSH_HOST_KEY",
                },
            )
        runner = _record(profile, "runner")
        with runtime._lock:
            server_record = runtime._get_server_registry_entry(server_id)

        operation = str(action.get("operation") or "")
        if operation in {"ensure-runner", "repair-runner", "upgrade-runner"}:
            return self._execute_provisioning(
                runtime=runtime,
                definition=definition,
                action=action,
                payload=payload,
                server_id=server_id,
                runner=runner,
                server_record=server_record,
            )
        if operation == "uninstall-runner":
            return self._execute_uninstall(
                runtime=runtime,
                definition=definition,
                action=action,
                payload=payload,
                server_id=server_id,
            )
        raise RuntimeServiceError(
            f"Remote runner driver does not support operation: {operation}",
            status_code=400,
            detail={
                "reasonCode": "MANAGED_EXTENSION_DRIVER_ACTION_UNSUPPORTED",
                "extensionId": definition.id,
                "action": str(action.get("id") or ""),
                "driver": self.driver_id,
                "operation": operation,
            },
        )

    def _execute_provisioning(
        self,
        *,
        runtime: Any,
        definition: ManagedExtensionDefinition,
        action: dict[str, Any],
        payload: dict[str, Any],
        server_id: str,
        runner: dict[str, Any],
        server_record: dict[str, Any],
    ) -> dict[str, Any]:
        action_id = str(action["id"])
        mode = str(payload.get("mode") or "run").strip()
        if mode != "run":
            raise RuntimeServiceError(
                f"Managed extension action does not support preview: {action_id}",
                status_code=400,
                detail={
                    "reasonCode": "MANAGED_EXTENSION_ACTION_MODE_UNSUPPORTED",
                    "extensionId": definition.id,
                    "action": action_id,
                    "mode": mode,
                },
            )
        provisioning_action = _remote_runner_provisioning_action(
            operation=str(action["operation"]),
            runner=runner,
            server_record=server_record,
        )
        job = runtime.create_remote_provisioning_job(server_id, {"action": provisioning_action})["data"]
        return _managed_extension_action_result(
            extension_id=definition.id,
            action=action_id,
            server_id=server_id,
            status=str(job.get("status") or "queued"),
            message=str(job.get("message") or ""),
            job_kind=str(action.get("jobKind") or "remote-provisioning"),
            job=job,
        )

    def _execute_uninstall(
        self,
        *,
        runtime: Any,
        definition: ManagedExtensionDefinition,
        action: dict[str, Any],
        payload: dict[str, Any],
        server_id: str,
    ) -> dict[str, Any]:
        action_id = str(action["id"])
        mode = str(payload.get("mode") or "run").strip()
        if mode == "preview":
            plan = runtime.preview_runner_uninstall(server_id)
            return _managed_extension_action_result(
                extension_id=definition.id,
                action=action_id,
                server_id=server_id,
                status="preview",
                message="Runner uninstall preview is ready.",
                plan=plan,
            )
        if mode != "run":
            raise RuntimeServiceError(
                f"Managed extension action mode is unsupported: {mode}",
                status_code=400,
                detail={
                    "reasonCode": "MANAGED_EXTENSION_ACTION_MODE_UNSUPPORTED",
                    "extensionId": definition.id,
                    "action": action_id,
                    "mode": mode,
                },
            )
        plan_hash = str(payload.get("planHash") or "").strip()
        if not plan_hash:
            raise RuntimeServiceError(
                "Runner uninstall planHash is required",
                status_code=400,
                detail={
                    "reasonCode": "MANAGED_EXTENSION_PLAN_HASH_REQUIRED",
                    "extensionId": definition.id,
                    "action": action_id,
                },
            )
        result = runtime.run_runner_uninstall(server_id, plan_hash=plan_hash)["data"]
        return _managed_extension_action_result(
            extension_id=definition.id,
            action=action_id,
            server_id=server_id,
            status="succeeded",
            message="Runner control plane was uninstalled.",
            result=result,
        )


MANAGED_EXTENSION_DRIVER_REGISTRY = ManagedExtensionDriverRegistry((RemoteRunnerManagedExtensionDriver(),))


class ManagedExtensionOperationsMixin:
    managed_extension_registry = BUILTIN_MANAGED_EXTENSION_REGISTRY
    managed_extension_driver_registry = MANAGED_EXTENSION_DRIVER_REGISTRY

    def list_managed_extensions(self) -> dict[str, Any]:
        context, profiles = _load_managed_extension_context(self)
        registry = self.managed_extension_registry
        items = registry.project_all(context)
        return {
            "data": {
                "schemaVersion": MANAGED_EXTENSION_LIST_SCHEMA_VERSION,
                "items": items,
                "total": len(items),
                "registries": registry.descriptor_payloads(),
                "activeProfileId": str(profiles.get("activeProfileId") or ""),
                "defaultProfileId": str(profiles.get("defaultProfileId") or ""),
            }
        }

    def execute_managed_extension_action(self, extension_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized_extension_id = str(extension_id or "").strip()
        action_id = str((payload or {}).get("action") or "").strip()
        if not action_id:
            raise RuntimeServiceError(
                "Managed extension action is required",
                status_code=400,
                detail={
                    "reasonCode": "MANAGED_EXTENSION_ACTION_REQUIRED",
                    "extensionId": normalized_extension_id,
                },
            )
        registry = self.managed_extension_registry
        try:
            definition = registry.require_definition(normalized_extension_id)
            action = definition.require_action(action_id)
            if action["type"] != MANAGED_EXTENSION_ACTION_TYPE:
                raise ManagedExtensionActionNotExecutableError(
                    f"Managed extension action is not executable: {action_id}",
                    extensionId=normalized_extension_id,
                    action=action_id,
                )
            driver = self.managed_extension_driver_registry.require(str(action.get("driver") or ""))
        except ManagedExtensionResolutionError as exc:
            raise _runtime_resolution_error(exc) from exc

        context, _ = _load_managed_extension_context(self)
        item = registry.project_definition(definition, context)
        if action_id not in item["actions"]:
            error = ManagedExtensionActionUnavailableError(
                f"Managed extension action is unavailable: {action_id}",
                extensionId=normalized_extension_id,
                action=action_id,
            )
            raise _runtime_resolution_error(error)
        _require_managed_extension_confirmation(
            definition=definition,
            action=action,
            payload=payload,
        )
        return driver.execute(
            runtime=self,
            definition=definition,
            action=action,
            payload=dict(payload or {}),
            context=context,
        )


def build_managed_extensions(
    *,
    active_server_profile: dict[str, Any] | None,
    active_remote_provisioning_job: dict[str, Any] | None,
    remote_provisioning_queue: dict[str, Any] | None,
    registry: ManagedExtensionRegistry | None = None,
) -> list[dict[str, Any]]:
    selected_registry = registry or BUILTIN_MANAGED_EXTENSION_REGISTRY
    context = ManagedExtensionProjectionContext(
        active_server_profile=active_server_profile,
        active_remote_provisioning_job=active_remote_provisioning_job,
        remote_provisioning_queue=dict(remote_provisioning_queue or {}),
    )
    return selected_registry.project_all(context)


def _load_managed_extension_context(runtime: Any) -> tuple[ManagedExtensionProjectionContext, dict[str, Any]]:
    with runtime._lock:
        runtime._ensure_initialized()
        profiles = runtime.list_server_profiles()["data"]
    active_profile = _active_server_profile(profiles)
    queue = runtime.list_remote_provisioning_job_queue(status="", limit=12, offset=0)["data"]
    context = ManagedExtensionProjectionContext(
        active_server_profile=active_profile,
        active_remote_provisioning_job=_active_remote_provisioning_job(queue, active_profile),
        remote_provisioning_queue=queue,
    )
    return context, profiles


def _remote_runner_provisioning_action(
    *,
    operation: str,
    runner: dict[str, Any],
    server_record: dict[str, Any],
) -> str:
    if operation == "upgrade-runner":
        return "upgrade-runner"
    if operation == "repair-runner" or _runner_needs_diagnostics_repair(runner):
        return "repair-runner"
    if operation != "ensure-runner":
        raise RuntimeServiceError(
            f"Unsupported remote runner provisioning operation: {operation}",
            status_code=400,
            detail={"reasonCode": "MANAGED_EXTENSION_DRIVER_ACTION_UNSUPPORTED", "operation": operation},
        )
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


def _runtime_resolution_error(error: ManagedExtensionResolutionError) -> RuntimeServiceError:
    return RuntimeServiceError(
        str(error),
        status_code=error.status_code,
        detail=error.to_detail(),
    )


def _require_managed_extension_confirmation(
    *,
    definition: ManagedExtensionDefinition,
    action: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    mode = str(payload.get("mode") or "run").strip()
    if mode != "run" or action.get("requiresConfirmation") is not True:
        return
    expected = str(action.get("confirmation") or "")
    if str(payload.get("confirmation") or "") == expected:
        return
    raise RuntimeServiceError(
        "Managed extension action confirmation is required",
        status_code=409,
        detail={
            "reasonCode": "MANAGED_EXTENSION_CONFIRMATION_REQUIRED",
            "extensionId": definition.id,
            "action": str(action.get("id") or ""),
            "confirmation": expected,
        },
    )


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


def _select_action_server_id(payload: dict[str, Any], profile: dict[str, Any] | None) -> str:
    return str(payload.get("serverId") or (profile or {}).get("serverId") or "").strip()


def _record(value: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    nested = value.get(key)
    return nested if isinstance(nested, dict) else {}
