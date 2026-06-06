from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PipelineRegistryError(ValueError):
    status_code = 400


@dataclass(frozen=True)
class PipelineManifestValidation:
    pipeline_id: str
    root_dir: Path
    snakefile: Path
    execution: dict[str, Any]


def validate_pipeline_manifest(raw: dict[str, Any], manifest_path: Path) -> PipelineManifestValidation:
    root_dir = manifest_path.parent
    if (root_dir / "Snakefile").exists():
        raise PipelineRegistryError("ROOT_SNAKEFILE_FORBIDDEN")
    pipeline_id = str(raw.get("pipelineId") or "").strip()
    if not pipeline_id:
        raise PipelineRegistryError("PIPELINE_ID_REQUIRED")
    if pipeline_id != root_dir.name:
        raise PipelineRegistryError("PIPELINE_ID_PATH_MISMATCH")
    snakefile_name = str(raw.get("snakefile") or "").strip()
    if snakefile_name != "workflow/Snakefile":
        raise PipelineRegistryError("STANDARD_SNAKEFILE_REQUIRED")
    snakefile = (root_dir / snakefile_name).resolve()
    if root_dir.resolve() not in [snakefile, *snakefile.parents]:
        raise PipelineRegistryError("SNAKEFILE_OUTSIDE_PIPELINE_ROOT")
    if not snakefile.exists():
        raise PipelineRegistryError("SNAKEFILE_MISSING")
    execution = raw.get("execution")
    outputs = execution.get("outputs") if isinstance(execution, dict) else None
    if not isinstance(outputs, dict) or not outputs:
        raise PipelineRegistryError("EXECUTION_OUTPUTS_REQUIRED")
    output_keys: set[str] = set()
    for key, value in outputs.items():
        output_key = str(key or "").strip()
        output_path = str(value or "").strip()
        if not output_key or not output_path:
            raise PipelineRegistryError("EXECUTION_OUTPUT_INVALID")
        if Path(output_path).is_absolute() or ".." in Path(output_path).parts:
            raise PipelineRegistryError("EXECUTION_OUTPUT_PATH_INVALID")
        output_keys.add(output_key)
    output_schema = raw.get("outputSchema")
    artifacts = output_schema.get("artifacts") if isinstance(output_schema, dict) else None
    if not isinstance(artifacts, list) or not artifacts:
        raise PipelineRegistryError("OUTPUT_ARTIFACTS_REQUIRED")
    artifact_keys: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise PipelineRegistryError("OUTPUT_ARTIFACT_INVALID")
        artifact_key = str(artifact.get("key") or "").strip()
        if not artifact_key:
            raise PipelineRegistryError("OUTPUT_ARTIFACT_KEY_REQUIRED")
        if artifact_key not in output_keys:
            raise PipelineRegistryError("OUTPUT_ARTIFACT_KEY_UNKNOWN")
        if artifact_key in artifact_keys:
            raise PipelineRegistryError("OUTPUT_ARTIFACT_KEY_DUPLICATE")
        for field in ("kind", "mimeType", "name"):
            if not str(artifact.get(field) or "").strip():
                raise PipelineRegistryError("OUTPUT_ARTIFACT_METADATA_REQUIRED")
        artifact_keys.add(artifact_key)
    if artifact_keys != output_keys:
        raise PipelineRegistryError("OUTPUT_ARTIFACT_KEYS_MISMATCH")
    _validate_resource_schema(raw.get("resources"))
    if not (root_dir / ".test" / "run-config.json").exists():
        raise PipelineRegistryError("TEST_RUN_CONFIG_REQUIRED")
    return PipelineManifestValidation(
        pipeline_id=pipeline_id,
        root_dir=root_dir,
        snakefile=snakefile,
        execution=dict(execution),
    )


def _validate_resource_schema(raw: Any) -> None:
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise PipelineRegistryError("RESOURCE_SCHEMA_INVALID")
    for key, value in raw.items():
        resource_key = str(key or "").strip()
        if not resource_key:
            raise PipelineRegistryError("RESOURCE_KEY_REQUIRED")
        if not isinstance(value, dict):
            raise PipelineRegistryError("RESOURCE_SPEC_INVALID")
        resource_type = str(value.get("type") or "database").strip()
        if resource_type != "database":
            raise PipelineRegistryError("RESOURCE_TYPE_UNSUPPORTED")
        config_key = str(value.get("configKey", resource_key)).strip()
        if not config_key:
            raise PipelineRegistryError("RESOURCE_CONFIG_KEY_REQUIRED")
        if "required" in value and not isinstance(value.get("required"), bool):
            raise PipelineRegistryError("RESOURCE_REQUIRED_INVALID")
        for field in ("acceptedTemplates", "acceptedCapabilities"):
            items = value.get(field)
            if items is None:
                continue
            if not isinstance(items, list) or any(not str(item).strip() for item in items):
                raise PipelineRegistryError(f"RESOURCE_{field.upper()}_INVALID")
