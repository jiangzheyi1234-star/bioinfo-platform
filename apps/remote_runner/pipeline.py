from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig


class PipelineRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class PipelineDefinition:
    pipeline_id: str
    name: str
    version: str
    description: str
    category: str
    icon: str
    tags: list[str]
    author: str
    license: str
    status: str
    enabled: bool
    root_dir: Path
    snakefile: Path
    input_schema: dict[str, Any]
    params_schema: dict[str, Any]
    resource_schema: dict[str, Any]
    output_schema: dict[str, Any]
    ui_schema: dict[str, Any]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "pipelineId": self.pipeline_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "tags": self.tags,
            "author": self.author,
            "license": self.license,
            "status": self.status,
            "enabled": self.enabled,
            "inputsSchema": self.input_schema,
            "paramsSchema": self.params_schema,
            "resources": self.resource_schema,
            "outputSchema": self.output_schema,
            "uiSchema": self.ui_schema,
        }


def pipeline_registry_dir(cfg: RemoteRunnerConfig) -> Path:
    return Path(cfg.release_dir) / "pipelines"


def list_pipelines(cfg: RemoteRunnerConfig) -> list[PipelineDefinition]:
    root = pipeline_registry_dir(cfg)
    if not root.exists():
        return []
    pipelines: list[PipelineDefinition] = []
    for manifest_path in sorted(root.glob("*/pipeline.json")):
        pipelines.append(_load_pipeline_manifest(manifest_path))
    return pipelines


def get_pipeline(cfg: RemoteRunnerConfig, pipeline_id: str) -> PipelineDefinition:
    normalized = str(pipeline_id or "").strip()
    if not normalized:
        raise PipelineRegistryError("PIPELINE_ID_REQUIRED")
    manifest_path = pipeline_registry_dir(cfg) / normalized / "pipeline.json"
    if not manifest_path.exists():
        raise PipelineRegistryError("PIPELINE_NOT_FOUND")
    return _load_pipeline_manifest(manifest_path)


def inspect_pipeline_registry(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    try:
        pipelines = list_pipelines(cfg)
    except Exception as exc:
        return {"ok": False, "message": f"Pipeline registry is invalid: {exc}", "count": 0, "items": []}
    if not pipelines:
        return {"ok": False, "message": "No pipelines are registered.", "count": 0, "items": []}
    missing = [item.pipeline_id for item in pipelines if not item.snakefile.exists()]
    if missing:
        return {
            "ok": False,
            "message": f"Registered pipeline Snakefile is missing: {', '.join(missing)}",
            "count": len(pipelines),
            "items": [item.to_public_dict() for item in pipelines],
        }
    return {
        "ok": True,
        "message": "Pipeline registry is ready.",
        "count": len(pipelines),
        "items": [item.to_public_dict() for item in pipelines],
    }


def _load_pipeline_manifest(manifest_path: Path) -> PipelineDefinition:
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PipelineRegistryError("PIPELINE_MANIFEST_INVALID_JSON") from exc
    root_dir = manifest_path.parent
    pipeline_id = str(raw.get("pipelineId") or "").strip()
    if not pipeline_id:
        raise PipelineRegistryError("PIPELINE_ID_REQUIRED")
    if pipeline_id != root_dir.name:
        raise PipelineRegistryError("PIPELINE_ID_PATH_MISMATCH")
    snakefile_name = str(raw.get("snakefile") or "Snakefile").strip()
    if not snakefile_name:
        raise PipelineRegistryError("SNAKEFILE_REQUIRED")
    snakefile = (root_dir / snakefile_name).resolve()
    if root_dir.resolve() not in [snakefile, *snakefile.parents]:
        raise PipelineRegistryError("SNAKEFILE_OUTSIDE_PIPELINE_ROOT")
    if not snakefile.exists():
        raise PipelineRegistryError("SNAKEFILE_MISSING")
    return PipelineDefinition(
        pipeline_id=pipeline_id,
        name=str(raw.get("name") or pipeline_id),
        version=str(raw.get("version") or "0.1.0"),
        description=str(raw.get("description") or ""),
        category=str(raw.get("category") or "General"),
        icon=str(raw.get("icon") or "workflow"),
        tags=[str(item) for item in (raw.get("tags") or []) if str(item).strip()],
        author=str(raw.get("author") or "H2OMeta"),
        license=str(raw.get("license") or "internal"),
        status=str(raw.get("status") or "installed"),
        enabled=bool(raw.get("enabled", True)),
        root_dir=root_dir,
        snakefile=snakefile,
        input_schema=dict(raw.get("inputsSchema") or {}),
        params_schema=dict(raw.get("paramsSchema") or {}),
        resource_schema=dict(raw.get("resources") or {}),
        output_schema=dict(raw.get("outputSchema") or {}),
        ui_schema=dict(raw.get("uiSchema") or {}),
    )


def validate_run_spec_for_pipeline(pipeline: PipelineDefinition, run_spec: dict[str, Any]) -> None:
    if not pipeline.enabled:
        raise PipelineRegistryError("PIPELINE_DISABLED")
    _validate_schema_value(
        run_spec.get("inputs") or [],
        pipeline.input_schema,
        code="INPUT_SCHEMA_INVALID",
        path="inputs",
    )
    _validate_schema_value(
        run_spec.get("params") or {},
        pipeline.params_schema,
        code="PARAM_SCHEMA_INVALID",
        path="params",
    )


def _validate_schema_value(value: Any, schema: dict[str, Any], *, code: str, path: str) -> None:
    if not schema:
        return
    expected_type = schema.get("type")
    if expected_type == "array":
        if not isinstance(value, list):
            raise PipelineRegistryError(code)
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < int(min_items):
            raise PipelineRegistryError(code)
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_schema_value(item, item_schema, code=code, path=f"{path}.{index}")
        return
    if expected_type == "object":
        if not isinstance(value, dict):
            raise PipelineRegistryError(code)
        required = [str(item) for item in schema.get("required") or []]
        if any(key not in value or value[key] in (None, "") for key in required):
            raise PipelineRegistryError(code)
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for key, item_schema in properties.items():
                if key in value and isinstance(item_schema, dict):
                    _validate_schema_value(value[key], item_schema, code=code, path=f"{path}.{key}")
            if schema.get("additionalProperties") is False:
                extra = set(value) - set(properties)
                if extra:
                    raise PipelineRegistryError(code)
        return
    if expected_type == "string":
        if not isinstance(value, str):
            raise PipelineRegistryError(code)
        min_length = schema.get("minLength")
        if min_length is not None and len(value) < int(min_length):
            raise PipelineRegistryError(code)
        return
    if expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise PipelineRegistryError(code)
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < int(minimum):
            raise PipelineRegistryError(code)
        if maximum is not None and value > int(maximum):
            raise PipelineRegistryError(code)
        return
    if expected_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise PipelineRegistryError(code)
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < float(minimum):
            raise PipelineRegistryError(code)
        if maximum is not None and value > float(maximum):
            raise PipelineRegistryError(code)
