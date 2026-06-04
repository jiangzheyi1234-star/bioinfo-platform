from __future__ import annotations

from pathlib import Path

from .config import RemoteRunnerConfig
from .storage import fetch_upload


def _build_run_outputs(execution: dict, result_dir: Path) -> dict[str, str]:
    configured = execution.get("outputs") if isinstance(execution, dict) else None
    if not isinstance(configured, dict) or not configured:
        raise ValueError("EXECUTION_OUTPUTS_REQUIRED")
    outputs: dict[str, str] = {}
    for key, value in configured.items():
        name = str(key or "").strip()
        relative = str(value or "").strip()
        if not name or not relative:
            continue
        candidate = (result_dir / relative).resolve()
        if result_dir.resolve() not in [candidate, *candidate.parents]:
            raise ValueError("OUTPUT_PATH_OUTSIDE_RESULT_DIR")
        outputs[name] = str(candidate)
    if not outputs:
        raise ValueError("OUTPUTS_REQUIRED")
    return outputs


def _resolve_run_inputs(cfg: RemoteRunnerConfig, run_spec: dict) -> list[dict]:
    raw_inputs = run_spec.get("inputs") or []
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise ValueError("INPUT_REQUIRED")
    resolved: list[dict] = []
    for index, item in enumerate(raw_inputs):
        if not isinstance(item, dict):
            raise ValueError("INPUT_INVALID")
        upload_id = str(item.get("uploadId") or "").strip()
        if not upload_id:
            raise ValueError("INPUT_UPLOAD_ID_REQUIRED")
        upload = fetch_upload(cfg, upload_id)
        if upload is None:
            raise ValueError("INPUT_NOT_FOUND")
        path = Path(str(upload["path"]))
        if not path.exists():
            raise ValueError("INPUT_FILE_MISSING")
        resolved.append(
            {
                "uploadId": upload["uploadId"],
                "filename": str(item.get("filename") or upload["filename"]),
                "role": str(item.get("role") or "input"),
                "path": str(path),
                "sizeBytes": upload["sizeBytes"],
                "sha256": upload["sha256"],
                "mimeType": upload["mimeType"],
                "index": index,
            }
        )
    return resolved
