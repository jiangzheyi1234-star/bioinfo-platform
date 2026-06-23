from __future__ import annotations

from typing import Any

from core.governance_policy import SUPPORTED_ROLES
from core.remote_runner.artifact import WorkflowRuntimeArtifact


DEFAULT_SNAKEMAKE_WRAPPER_PREFIX = "https://raw.githubusercontent.com/snakemake/snakemake-wrappers/"
MAX_COMPACT_PREVIEW_CONTENT_CHARS = 1024
MAX_COMPACT_PREVIEW_TABLE_COLUMNS = 12
MAX_COMPACT_PREVIEW_TABLE_ROWS = 5
MAX_COMPACT_PREVIEW_TABLE_CELL_CHARS = 128


def build_remote_workflow_profile_content(
    *,
    conda_prefix: str,
    wrapper_prefix: str = DEFAULT_SNAKEMAKE_WRAPPER_PREFIX,
) -> str:
    normalized_wrapper_prefix = _normalize_wrapper_prefix(wrapper_prefix)
    return "\n".join(
        [
            "executor: local",
            "jobs: 1",
            "latency-wait: 60",
            "printshellcmds: true",
            "rerun-incomplete: true",
            "software-deployment-method: conda",
            "conda-frontend: mamba",
            f"wrapper-prefix: {normalized_wrapper_prefix}",
            f"conda-prefix: {conda_prefix}",
            "",
        ]
    )


def _normalize_wrapper_prefix(value: str) -> str:
    prefix = str(value or DEFAULT_SNAKEMAKE_WRAPPER_PREFIX).strip() or DEFAULT_SNAKEMAKE_WRAPPER_PREFIX
    return prefix if prefix.endswith("/") else f"{prefix}/"


def summarize_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifactId": str(artifact.get("artifactId") or ""),
        "kind": str(artifact.get("kind") or ""),
        "mimeType": str(artifact.get("mimeType") or ""),
        "sizeBytes": int(artifact.get("sizeBytes") or 0),
        "path": str(artifact.get("path") or ""),
    }


def compact_preview_payload(preview_payload: Any) -> dict[str, Any]:
    if not isinstance(preview_payload, dict):
        return {"kind": "", "truncated": False}
    data = preview_payload.get("data") if isinstance(preview_payload.get("data"), dict) else preview_payload
    if isinstance(data, dict):
        preview = data.get("preview") if isinstance(data.get("preview"), dict) else data
        artifact = data.get("artifact") if isinstance(data.get("artifact"), dict) else {}
        compact = {
            "artifactId": str(data.get("artifactId") or artifact.get("artifactId") or ""),
            "kind": str(preview.get("kind") or ""),
            "truncated": bool(preview.get("truncated")),
        }
        if compact["kind"] == "table":
            columns, columns_truncated = _compact_preview_cells(preview.get("columns"))
            rows, rows_truncated = _compact_preview_rows(preview.get("rows"))
            compact["columns"] = columns
            compact["rows"] = rows
            compact["truncated"] = bool(compact["truncated"] or columns_truncated or rows_truncated)
        else:
            content, content_truncated = _compact_preview_text(preview.get("content"), MAX_COMPACT_PREVIEW_CONTENT_CHARS)
            compact["content"] = content
            compact["truncated"] = bool(compact["truncated"] or content_truncated)
        return compact
    return {"kind": "", "truncated": False}


def _compact_preview_rows(raw_rows: Any) -> tuple[list[list[str]], bool]:
    if not isinstance(raw_rows, list):
        return [], False
    rows: list[list[str]] = []
    truncated = len(raw_rows) > MAX_COMPACT_PREVIEW_TABLE_ROWS
    for raw_row in raw_rows[:MAX_COMPACT_PREVIEW_TABLE_ROWS]:
        if not isinstance(raw_row, list):
            cell, cell_truncated = _compact_preview_text(raw_row, MAX_COMPACT_PREVIEW_TABLE_CELL_CHARS)
            rows.append([cell])
            truncated = truncated or cell_truncated
            continue
        cells, cells_truncated = _compact_preview_cells(raw_row)
        rows.append(cells)
        truncated = truncated or cells_truncated
    return rows, truncated


def _compact_preview_cells(raw_cells: Any) -> tuple[list[str], bool]:
    if not isinstance(raw_cells, list):
        return [], False
    cells: list[str] = []
    truncated = len(raw_cells) > MAX_COMPACT_PREVIEW_TABLE_COLUMNS
    for raw_cell in raw_cells[:MAX_COMPACT_PREVIEW_TABLE_COLUMNS]:
        cell, cell_truncated = _compact_preview_text(raw_cell, MAX_COMPACT_PREVIEW_TABLE_CELL_CHARS)
        cells.append(cell)
        truncated = truncated or cell_truncated
    return cells, truncated


def _compact_preview_text(value: Any, limit: int) -> tuple[str, bool]:
    text = str(value or "")
    return text[:limit], len(text) > limit


def build_fast_reuse_metadata(
    *,
    server_record: dict[str, Any],
    version: str,
    remote_service_python: str,
) -> dict[str, Any]:
    metadata = dict(server_record.get("bootstrap_metadata") or {})
    preflight = dict(metadata.get("preflight") or {})
    tooling = dict(metadata.get("tooling") or {})
    service_runtime = dict(tooling.get("service_runtime") or {})
    workflow_runtime = dict(tooling.get("workflow_runtime") or {})
    runner_mode = str(server_record.get("runner_mode") or "")
    platform = str(preflight.get("platform") or service_runtime.get("platform") or "")
    if runner_mode:
        preflight["launcher"] = {"mode": runner_mode}
    if platform:
        preflight["platform"] = platform
    service_runtime = {
        **service_runtime,
        "provider": "bundled",
        "source": "artifact",
        "python": str(service_runtime.get("python") or remote_service_python),
    }
    if platform:
        service_runtime["platform"] = platform
    tooling["service_runtime"] = service_runtime
    if workflow_runtime:
        tooling["workflow_runtime"] = workflow_runtime
    metadata["preflight"] = preflight
    metadata["tooling"] = tooling
    return metadata


def platform_from_metadata(server_record: dict[str, Any]) -> str:
    metadata = dict(server_record.get("bootstrap_metadata") or {})
    preflight = dict(metadata.get("preflight") or {})
    tooling = dict(metadata.get("tooling") or {})
    service_runtime = dict(tooling.get("service_runtime") or {})
    return str(preflight.get("platform") or service_runtime.get("platform") or "").strip()


def mark_reuse_bootstrap_phases_skipped(bootstrap_metadata: dict[str, Any]) -> None:
    bootstrap_metadata["canary"] = {
        "status": "skipped",
        "message": "Existing runner reused; bootstrap canary was not rerun.",
    }
    bootstrap_metadata["rollback"] = {
        "attempted": False,
        "restored": False,
        "status": "skipped",
        "message": "Existing runner reused; rollback was not needed.",
    }


def reuse_failed(bootstrap_metadata: dict[str, Any], reason: str) -> None:
    bootstrap_metadata["reuse_check"] = {"ok": False, "reason": reason}
    return None


def build_workflow_runtime_metadata(*, artifact: WorkflowRuntimeArtifact, remote_dir: str) -> dict[str, Any]:
    packages = artifact.manifest.get("packages") if isinstance(artifact.manifest.get("packages"), dict) else {}
    snakemake_version = str(packages.get("snakemake") or "")
    return {
        "provider": "conda-pack",
        "source": "artifact",
        "version": artifact.version,
        "platform": artifact.platform,
        "artifact_sha": artifact.sha256,
        "root": remote_dir,
        "python": f"{remote_dir}/{artifact.python_entrypoint}",
        "command": f"{remote_dir}/{artifact.conda_entrypoint}",
        "root_prefix": f"{remote_dir}/micromamba-root",
        "conda_unpack": f"{remote_dir}/{artifact.conda_unpack_entrypoint}",
        "snakemake_command": f"{remote_dir}/{artifact.snakemake_entrypoint}",
        "snakemake_version": snakemake_version,
    }


def build_install_bootstrap_metadata(
    *,
    mode: str,
    remote_platform: str,
    artifact: Any,
    workflow_runtime: dict[str, Any],
    remote_service_python: str,
    remote_profile_dir: str,
    remote_profile_path: str,
    remote_profile_name: str,
    remote_release: str,
    previous_release: str,
    previous_mode: str,
) -> dict[str, Any]:
    return {
        "preflight": {
            "launcher": {"mode": mode},
            "platform": remote_platform,
        },
        "tooling": {
            "service_runtime": {
                "provider": "bundled",
                "source": "artifact",
                "python": remote_service_python,
                "platform": getattr(artifact, "platform", remote_platform),
            },
            "workflow_runtime": workflow_runtime,
        },
        "workflow_profile": {
            "path": remote_profile_dir,
            "config": remote_profile_path,
            "name": remote_profile_name,
        },
        "deployment_action": "installed",
        "release_switch": {
            "target_release": remote_release,
            "target_mode": mode,
            "previous_release": previous_release,
            "previous_mode": previous_mode,
            "switched": False,
        },
        "rollback": {
            "attempted": False,
            "restored": False,
            "previous_release": previous_release,
            "previous_mode": previous_mode,
            "message": "",
        },
        "canary": {
            "ok": False,
            "status": "pending",
            "message": "",
        },
    }


def build_remote_config_payload(
    *,
    version: str,
    mode: str,
    remote_port: int,
    token: str,
    remote_shared: str,
    remote_release: str,
    remote_runtime_state: str,
    runner_python: str,
    managed_conda_command: str,
    managed_conda_root_prefix: str,
    workflow_runtime_provider: str,
    workflow_runtime_source: str,
    workflow_runtime_version: str,
    snakemake_command: str,
    snakemake_version: str,
    workflow_profile_dir: str,
    workflow_profile_name: str,
) -> dict[str, Any]:
    return {
        "service_name": "h2ometa-remote",
        "version": version,
        "mode": mode,
        "bind_host": "127.0.0.1",
        "bind_port": remote_port,
        "token": token,
        "api_token_actor": "remote-runner-api",
        "api_token_roles": sorted(SUPPORTED_ROLES),
        "data_root": f"{remote_shared}",
        "db_path": f"{remote_shared}/data/runner.db",
        "runtime_state_path": remote_runtime_state,
        "uploads_dir": f"{remote_shared}/uploads",
        "results_dir": f"{remote_shared}/results",
        "work_dir": f"{remote_shared}/work",
        "logs_dir": f"{remote_shared}/logs",
        "release_dir": f"{remote_release}/remote_runner",
        "runner_python": runner_python,
        "managed_conda_command": managed_conda_command,
        "managed_conda_root_prefix": managed_conda_root_prefix,
        "workflow_runtime_provider": workflow_runtime_provider,
        "workflow_runtime_source": workflow_runtime_source,
        "workflow_runtime_version": workflow_runtime_version,
        "snakemake_command": snakemake_command,
        "snakemake_version": snakemake_version,
        "workflow_profile_dir": workflow_profile_dir,
        "workflow_profile_name": workflow_profile_name,
    }
