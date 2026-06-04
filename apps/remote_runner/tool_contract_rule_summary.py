from __future__ import annotations

import re
from typing import Any


MOVING_WRAPPER_REFS = {"bio", "master", "main", "latest", "head", "dev"}
WRAPPER_VERSION_RE = re.compile(r"^v?\d+(?:\.\d+){1,}(?:[-+._A-Za-z0-9]*)?$")
WRAPPER_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


def selected_rule_entry(tool: dict[str, Any]) -> dict[str, Any]:
    manifest = tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {}
    if has_rule_template_shape(manifest):
        return {"source": "manifest", "template": manifest}
    return {"source": "", "template": {}}


def summarize_rule_template(template: dict[str, Any]) -> dict[str, Any]:
    actions = _rule_action_fields(template)
    action = actions[0] if len(actions) == 1 else ""
    wrapper = _string(template.get("wrapper"))
    wrapper_locked = _wrapper_ref_locked(wrapper) if action == "wrapper" else False
    inputs = [item for item in template.get("inputs") or [] if isinstance(item, dict)]
    outputs = [item for item in template.get("outputs") or [] if isinstance(item, dict)]
    params = template.get("params") if isinstance(template.get("params"), dict) else {}
    params_ready = isinstance(template.get("params"), dict)
    threads_ready = _threads_ready(template)
    scheduler_resources = _scheduler_resource_count(template)
    log_ready = _log_ready(template.get("log"))
    return {
        "action": action,
        "actionCount": len(actions),
        "hasSingleAction": len(actions) == 1,
        "actionReady": len(actions) == 1 and (action != "wrapper" or wrapper_locked),
        "wrapperLocked": wrapper_locked,
        "inputs": len(inputs),
        "outputs": len(outputs),
        "params": len(params),
        "threads": 1 if threads_ready else 0,
        "schedulerResources": scheduler_resources,
        "log": 1 if log_ready else 0,
        "inputsReady": bool(inputs) and all(_string(item.get("name")) for item in inputs),
        "outputsReady": bool(outputs) and all(_output_ready(item) for item in outputs),
        "paramsReady": params_ready,
        "threadsReady": threads_ready,
        "resourcesReady": scheduler_resources > 0,
        "logReady": log_ready,
    }


def has_rule_template_shape(template: dict[str, Any]) -> bool:
    return bool(
        _rule_action_fields(template)
        or isinstance(template.get("inputs"), list)
        or isinstance(template.get("outputs"), list)
        or isinstance(template.get("params"), dict)
    )


def _rule_action_fields(template: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    for field in ("commandTemplate", "wrapper", "script"):
        if _string(template.get(field)):
            actions.append(field)
    module = template.get("module")
    if isinstance(module, dict) and (_string(module.get("snakefile")) or _string(module.get("rule"))):
        actions.append("module")
    return actions


def _wrapper_ref_locked(wrapper: str) -> bool:
    parts = [part for part in wrapper.split("/") if part]
    if len(parts) < 2:
        return False
    ref = parts[0].strip()
    if not ref or ref.lower() in MOVING_WRAPPER_REFS:
        return False
    return bool(WRAPPER_VERSION_RE.match(ref) or WRAPPER_COMMIT_RE.match(ref))


def _output_ready(item: dict[str, Any]) -> bool:
    return bool(
        _string(item.get("name"))
        and _string(item.get("path"))
    )


def _threads_ready(template: dict[str, Any]) -> bool:
    return _positive_int(template.get("threads")) or _positive_int(_resource_default(template.get("resources"), "threads"))


def _scheduler_resource_count(template: dict[str, Any]) -> int:
    names: set[str] = set()
    for field in ("schedulerResources", "runtimeResources"):
        raw = template.get(field)
        if isinstance(raw, dict):
            names.update(name for name, value in raw.items() if _string(name) and _scheduler_value_ready(value))
    resources = template.get("resources")
    if isinstance(resources, dict):
        for name, value in resources.items():
            if name == "threads":
                continue
            if _scheduler_value_ready(value) and not _workflow_resource_value(value):
                names.add(str(name))
    return len(names)


def _scheduler_value_ready(value: Any) -> bool:
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return bool(str(value).strip())
    if isinstance(value, dict):
        if _workflow_resource_value(value):
            return False
        return any(_scheduler_value_ready(value.get(key)) for key in ("default", "value"))
    return False


def _workflow_resource_value(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(key in value for key in ("acceptedTemplates", "acceptedCapabilities", "configKey")) or str(value.get("type") or "") == "database"


def _resource_default(resources: Any, name: str) -> Any:
    if not isinstance(resources, dict):
        return None
    value = resources.get(name)
    if isinstance(value, dict):
        return value.get("default", value.get("value"))
    return value


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _log_ready(raw: Any) -> bool:
    if isinstance(raw, str):
        return bool(raw.strip())
    if isinstance(raw, dict):
        return bool(raw) and all(_string(name) and _string(path) for name, path in raw.items())
    return False


def _string(raw: Any) -> str:
    return str(raw or "").strip()
