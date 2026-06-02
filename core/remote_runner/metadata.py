from __future__ import annotations

from typing import Any

from core.remote_runner.artifact import WorkflowRuntimeArtifact


DEFAULT_SNAKEMAKE_WRAPPER_PREFIX = "https://raw.githubusercontent.com/snakemake/snakemake-wrappers/"


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


def compact_preview_payload(preview_payload: dict[str, Any]) -> dict[str, Any]:
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
            compact["columns"] = preview.get("columns") if isinstance(preview.get("columns"), list) else []
            rows = preview.get("rows") if isinstance(preview.get("rows"), list) else []
            compact["rows"] = rows[:5]
        else:
            content = str(preview.get("content") or "")
            compact["content"] = content[:1024]
        return compact
    return {"kind": "", "truncated": False}


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
