from __future__ import annotations

from pathlib import Path

from .candidate_output_storage import (
    adopt_verified_candidate_outputs,
    record_candidate_output,
    verify_candidate_outputs,
)
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
    request_id: str | None = None,
    result_dir: str | None = None,
    finalize_run: bool = False,
) -> list[dict]:
    if not isinstance(output_schema, dict) or not isinstance(outputs, dict) or not outputs:
        raise ValueError("MANIFEST_OUTPUTS_REQUIRED")
    raw_artifacts = output_schema.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise ValueError("OUTPUT_ARTIFACTS_REQUIRED")
    output_error = _validate_outputs(output_schema=output_schema, outputs=outputs)
    if output_error:
        raise ValueError(f"{output_error['code']}: {output_error['message']}")
    has_attempt_context = attempt_id is not None or lease_generation is not None
    if has_attempt_context and (not str(attempt_id or "").strip() or lease_generation is None):
        raise ValueError("RUN_ATTEMPT_CONTEXT_INCOMPLETE")
    artifacts = []
    expected_outputs: dict[str, dict] = {}
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
        if has_attempt_context:
            candidate = record_candidate_output(
                cfg,
                run_id=run_id,
                attempt_id=str(attempt_id),
                lease_generation=int(lease_generation),
                output_key=key,
                path=path,
            )
            expected_outputs[key] = {
                "path": str(path),
                "kind": kind,
                "mimeType": mime_type,
                "sha256": candidate["sha256"],
                **(
                    {"stepId": str(artifact.get("stepId") or "").strip()}
                    if str(artifact.get("stepId") or "").strip()
                    else {}
                ),
            }
            continue
        artifacts.append(
            persist_artifact(
                cfg,
                run_id=run_id,
                kind=kind,
                path=path,
                mime_type=mime_type,
                artifact_key=key,
                step_id=str(artifact.get("stepId") or "").strip() or None,
            )
        )
    if has_attempt_context:
        verification = verify_candidate_outputs(
            cfg,
            run_id=run_id,
            attempt_id=str(attempt_id),
            lease_generation=int(lease_generation),
            expected_outputs=expected_outputs,
        )
        if verification["rejected"] or verification["missing"]:
            raise ValueError("CANDIDATE_OUTPUT_VERIFICATION_FAILED")
        return [
            {
                "artifactId": artifact_id,
                "runId": run_id,
            }
            for artifact_id in adopt_verified_candidate_outputs(
                cfg,
                run_id=run_id,
                attempt_id=str(attempt_id),
                lease_generation=int(lease_generation),
                expected_outputs=expected_outputs,
                finalize_run=finalize_run,
                request_id=request_id,
                result_dir=result_dir,
            )["artifactIds"]
        ]
    return artifacts
