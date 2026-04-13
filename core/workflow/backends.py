"""Workflow run backends."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .runtime_ops import (
    cancel_local_nextflow_run,
    download_run_artifacts,
    materialize_bundle,
    query_local_nextflow_run,
    recursive_upload_directory,
    submit_local_nextflow_run,
)


class WorkflowBackend:
    backend_kind = "unknown"

    def submit_run(
        self,
        *,
        ssh_service: Any,
        ssh_run_fn: Any,
        project_dir: Path,
        remote_base: str,
        run_id: str,
        compiled_bundle: dict[str, Any],
        launch: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def query_run(self, *, ssh_run_fn: Any, row: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def cancel_run(self, *, ssh_run_fn: Any, row: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def collect_artifacts(
        self,
        *,
        ssh_service: Any,
        project_dir: Path,
        run_id: str,
        row: dict[str, Any],
    ) -> list[dict[str, Any]]:
        raise NotImplementedError


class LocalSSHBackend(WorkflowBackend):
    backend_kind = "local_ssh"

    def submit_run(
        self,
        *,
        ssh_service: Any,
        ssh_run_fn: Any,
        project_dir: Path,
        remote_base: str,
        run_id: str,
        compiled_bundle: dict[str, Any],
        launch: Any,
    ) -> dict[str, Any]:
        local_layout = materialize_bundle(project_dir, run_id, compiled_bundle)
        remote_task_dir = f"{remote_base}/workflow_runs/{run_id}"
        remote_bundle_dir = f"{remote_task_dir}/bundle"
        remote_work_dir = launch.profile.work_dir or f"{remote_task_dir}/work"
        remote_output_dir = launch.profile.output_dir or f"{remote_task_dir}/output"
        recursive_upload_directory(ssh_service, Path(local_layout["bundle_dir"]), remote_bundle_dir)
        remote_submission = submit_local_nextflow_run(
            ssh_run_fn,
            remote_task_dir=remote_task_dir,
            remote_bundle_dir=remote_bundle_dir,
            remote_work_dir=remote_work_dir,
            remote_output_dir=remote_output_dir,
            resume=bool(launch.resume),
        )
        return {
            "backend_kind": self.backend_kind,
            "local_bundle_dir": local_layout["bundle_dir"],
            "local_run_dir": local_layout["run_dir"],
            "local_record_path": local_layout["record_path"],
            "remote_task_dir": remote_submission["task_dir"],
            "remote_bundle_dir": remote_submission["bundle_dir"],
            "remote_work_dir": remote_submission["work_dir"],
            "remote_output_dir": remote_submission["output_dir"],
            "launcher_pid": remote_submission["launcher_pid"],
            "resolved_config_path": str(Path(local_layout["bundle_dir"]) / "resolved.config"),
        }

    def query_run(self, *, ssh_run_fn: Any, row: dict[str, Any]) -> dict[str, Any]:
        remote_task_dir = str(row.get("remote_task_dir") or "").strip()
        if not remote_task_dir:
            raise RuntimeError("workflow run 缺少 remote_task_dir")
        return query_local_nextflow_run(ssh_run_fn, remote_task_dir=remote_task_dir)

    def cancel_run(self, *, ssh_run_fn: Any, row: dict[str, Any]) -> dict[str, Any]:
        remote_task_dir = str(row.get("remote_task_dir") or "").strip()
        if not remote_task_dir:
            raise RuntimeError("workflow run 缺少 remote_task_dir")
        return cancel_local_nextflow_run(ssh_run_fn, remote_task_dir=remote_task_dir)

    def collect_artifacts(
        self,
        *,
        ssh_service: Any,
        project_dir: Path,
        run_id: str,
        row: dict[str, Any],
    ) -> list[dict[str, Any]]:
        remote_bundle_dir = str(row.get("remote_bundle_dir") or "").strip()
        remote_output_dir = str(row.get("remote_output_dir") or "").strip()
        return download_run_artifacts(
            ssh_service,
            project_dir=project_dir,
            run_id=run_id,
            remote_bundle_dir=remote_bundle_dir,
            remote_output_dir=remote_output_dir,
        )


class SlurmSSHBackend(WorkflowBackend):
    backend_kind = "slurm_ssh"

    def submit_run(
        self,
        *,
        ssh_service: Any,
        ssh_run_fn: Any,
        project_dir: Path,
        remote_base: str,
        run_id: str,
        compiled_bundle: dict[str, Any],
        launch: Any,
    ) -> dict[str, Any]:
        raise RuntimeError("Slurm backend 骨架已保留，但本轮未实现提交流程")

    def query_run(self, *, ssh_run_fn: Any, row: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("Slurm backend 骨架已保留，但本轮未实现状态查询")

    def cancel_run(self, *, ssh_run_fn: Any, row: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("Slurm backend 骨架已保留，但本轮未实现取消逻辑")

    def collect_artifacts(
        self,
        *,
        ssh_service: Any,
        project_dir: Path,
        run_id: str,
        row: dict[str, Any],
    ) -> list[dict[str, Any]]:
        raise RuntimeError("Slurm backend 骨架已保留，但本轮未实现产物收集")


def create_workflow_backend(profile: Any) -> WorkflowBackend:
    executor = str(getattr(profile, "executor", "") or "").strip()
    if executor == "local":
        return LocalSSHBackend()
    if executor == "slurm":
        return SlurmSSHBackend()
    raise RuntimeError(f"不支持的 workflow executor: {executor or '<empty>'}")
