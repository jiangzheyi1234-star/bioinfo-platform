from __future__ import annotations

from pathlib import Path

from .config import RemoteRunnerConfig
from .storage import persist_artifact
from .tool_contract_validation import _validate_outputs


def _collect_artifacts(
    cfg: RemoteRunnerConfig,
    run_id: str,
    *,
    output_schema: dict | None,
    outputs: dict[str, str] | None,
    attempt_id: str | None = None,
    lease_generation: int | None = None,
) -> list[dict]:
    if not isinstance(output_schema, dict) or not isinstance(outputs, dict) or not outputs:
        raise ValueError("MANIFEST_OUTPUTS_REQUIRED")
    raw_artifacts = output_schema.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise ValueError("OUTPUT_ARTIFACTS_REQUIRED")
    output_error = _validate_outputs(output_schema=output_schema, outputs=outputs)
    if output_error:
        raise ValueError(f"{output_error['code']}: {output_error['message']}")
    artifacts = []
    for artifact in raw_artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("OUTPUT_ARTIFACT_INVALID")
        key = str(artifact.get("key") or "").strip()
        if key not in outputs:
            raise ValueError(f"OUTPUT_ARTIFACT_KEY_UNKNOWN: {key}")
        path = Path(outputs[key])
        kind = str(artifact.get("kind") or "").strip()
        mime_type = str(artifact.get("mimeType") or "").strip()
        if not kind or not mime_type:
            raise ValueError(f"OUTPUT_ARTIFACT_METADATA_REQUIRED: {key}")
        directory = bool(artifact.get("directory")) or kind == "directory" or mime_type == "inode/directory"
        if not path.exists() or (directory and not path.is_dir()) or (not directory and not path.is_file()):
            raise ValueError(f"OUTPUT_ARTIFACT_MISSING: {key}")
        artifacts.append(
            persist_artifact(
                cfg,
                run_id=run_id,
                kind=kind,
                path=path,
                mime_type=mime_type,
                attempt_id=attempt_id,
                lease_generation=lease_generation,
                artifact_key=key,
                step_id=str(artifact.get("stepId") or "").strip() or None,
            )
        )
    return artifacts
