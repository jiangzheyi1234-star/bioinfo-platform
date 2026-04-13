"""Workflow runtime metadata helpers for plugin descriptors."""

from __future__ import annotations

import re
from typing import Any, Literal

SupportLevel = Literal["Production Ready", "Conda Only", "Legacy"]

WORKFLOW_GOLDEN_PATH_PLUGIN_IDS = frozenset({
    "fastp",
    "hostile",
    "kraken2",
    "bracken",
    "krona",
    "blastn",
    "quast",
    "metaphlan",
    "centrifuge",
    "prokka",
    "rgi",
    "unknown_sample_detection",
})
LEGACY_PLUGIN_FIELDS = ("conda_env", "install_cmd")
LEGACY_CONDA_ENV_MARKER = "/.h2ometa/conda/envs/"
_REQUIRED_RESOURCE_FIELDS = ("cpus", "memory", "time")
_REQUIRED_OUTPUT_FIELDS = ("name", "type", "tier", "pattern")


def runtime_block(descriptor: dict[str, Any]) -> dict[str, Any]:
    runtime = descriptor.get("runtime")
    return runtime if isinstance(runtime, dict) else {}


def runtime_container_ref(descriptor: dict[str, Any]) -> str:
    return str(runtime_block(descriptor).get("container") or "").strip()


def runtime_conda_spec(descriptor: dict[str, Any]) -> str:
    return str(runtime_block(descriptor).get("conda") or "").strip()


def derive_support_level(descriptor: dict[str, Any]) -> SupportLevel:
    if runtime_container_ref(descriptor) and runtime_conda_spec(descriptor):
        return "Production Ready"
    if runtime_conda_spec(descriptor):
        return "Conda Only"
    return "Legacy"


def derive_conda_env_name(descriptor: dict[str, Any]) -> str:
    explicit = str(descriptor.get("conda_env") or "").strip()
    if explicit:
        return explicit
    tool_id = str(descriptor.get("id") or "").strip() or "tool"
    if tool_id not in WORKFLOW_GOLDEN_PATH_PLUGIN_IDS:
        return ""
    conda_spec = runtime_conda_spec(descriptor)
    if not conda_spec:
        return ""
    tokens = [token.strip() for token in re.split(r"\s+", conda_spec) if token.strip()]
    if len(tokens) != 1:
        return f"{_sanitize_identifier(tool_id)}_env"
    package = tokens[0].split("::", 1)[-1].split("=", 1)[0].strip()
    if not package:
        package = tool_id
    return f"{_sanitize_identifier(package)}_env"


def derive_workflow_support(descriptor: dict[str, Any]) -> dict[str, Any]:
    errors = collect_workflow_validation_errors(descriptor)
    return {
        "support_level": derive_support_level(descriptor),
        "workflow_ready": len(errors) == 0,
        "validation_errors": errors,
        "runtime": {
            "container": runtime_container_ref(descriptor),
            "conda": runtime_conda_spec(descriptor),
            "conda_env_name": derive_conda_env_name(descriptor),
        },
    }


def validate_workflow_descriptor(descriptor: dict[str, Any], *, strict: bool) -> None:
    errors = collect_workflow_validation_errors(descriptor)
    if strict and errors:
        plugin_id = str(descriptor.get("id") or "<unknown>")
        raise ValueError(f"插件 {plugin_id} 的 workflow 元数据无效: {'；'.join(errors)}")


def collect_workflow_validation_errors(descriptor: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    plugin_id = str(descriptor.get("id") or "").strip()
    support_level = derive_support_level(descriptor)

    legacy_fields = [field for field in LEGACY_PLUGIN_FIELDS if str(descriptor.get(field) or "").strip()]
    if legacy_fields and plugin_id in WORKFLOW_GOLDEN_PATH_PLUGIN_IDS:
        errors.append(f"仍包含旧字段 {', '.join(legacy_fields)}")

    if LEGACY_CONDA_ENV_MARKER in str(descriptor.get("command_template") or ""):
        errors.append("command_template 仍硬编码旧 conda env 路径")

    runtime = descriptor.get("runtime")
    if runtime is not None and not isinstance(runtime, dict):
        errors.append("runtime 必须是对象")

    if support_level == "Legacy" and plugin_id in WORKFLOW_GOLDEN_PATH_PLUGIN_IDS:
        errors.append("缺少 runtime.conda，无法作为 workflow 插件使用")

    resources = descriptor.get("resources")
    if not isinstance(resources, dict):
        errors.append("resources 缺失或格式无效")
    else:
        missing = [field for field in _REQUIRED_RESOURCE_FIELDS if not str(resources.get(field) or "").strip()]
        if missing:
            errors.append(f"resources 缺少字段 {', '.join(missing)}")

    outputs = descriptor.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        errors.append("outputs 缺失，无法声明 workflow 产物")
    else:
        for index, item in enumerate(outputs, start=1):
            if not isinstance(item, dict):
                errors.append(f"outputs[{index}] 不是对象")
                continue
            missing = [field for field in _REQUIRED_OUTPUT_FIELDS if not str(item.get(field) or "").strip()]
            if missing:
                errors.append(f"outputs[{index}] 缺少字段 {', '.join(missing)}")

    return errors


def _sanitize_identifier(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "").strip()).strip("_")
    return cleaned or "tool"
