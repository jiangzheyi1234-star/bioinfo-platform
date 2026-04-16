from __future__ import annotations

import pytest

from core.workflow.runtime_ops import submit_local_nextflow_run


def test_submit_local_nextflow_run_blocks_when_docker_backend_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.workflow.runtime_ops.ensure_remote_dirs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "core.workflow.runtime_ops.resolve_remote_nextflow",
        lambda *_args, **_kwargs: {
            "usable": True,
            "path": "/usr/local/bin/nextflow",
            "command": "/usr/local/bin/nextflow",
        },
    )
    monkeypatch.setattr(
        "core.workflow.runtime_ops.resolve_remote_java",
        lambda *_args, **_kwargs: {
            "usable": True,
            "home": "/opt/jdk-21",
        },
    )
    monkeypatch.setattr("core.workflow.runtime_ops.write_remote_script", lambda *_args, **_kwargs: "/remote/launch.sh")

    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        if command == "docker ps >/dev/null 2>&1":
            return 1, "", "docker not ready"
        raise AssertionError(f"unexpected command: {command}")

    with pytest.raises(RuntimeError, match="Docker 未就绪"):
        submit_local_nextflow_run(
            ssh_run_fn,
            remote_task_dir="/remote/task",
            remote_bundle_dir="/remote/task/bundle",
            remote_work_dir="/remote/task/work",
            remote_output_dir="/remote/task/output",
            resume=True,
            packaging_mode="container",
            container_runtime="docker",
        )


def test_submit_local_nextflow_run_rejects_non_docker_execution_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.workflow.runtime_ops.ensure_remote_dirs", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="仅支持 Docker 作为后端"):
        submit_local_nextflow_run(
            lambda command, timeout: (0, "", ""),
            remote_task_dir="/remote/task",
            remote_bundle_dir="/remote/task/bundle",
            remote_work_dir="/remote/task/work",
            remote_output_dir="/remote/task/output",
            resume=True,
            packaging_mode="conda",
            container_runtime="",
        )


def test_submit_local_nextflow_run_uses_explicit_bash_lc_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.workflow.runtime_ops.ensure_remote_dirs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "core.workflow.runtime_ops.resolve_remote_nextflow",
        lambda *_args, **_kwargs: {
            "usable": True,
            "path": "/usr/local/bin/nextflow",
            "command": "/usr/local/bin/nextflow",
        },
    )
    monkeypatch.setattr(
        "core.workflow.runtime_ops.resolve_remote_java",
        lambda *_args, **_kwargs: {
            "usable": True,
            "home": "/opt/jdk-21",
        },
    )
    monkeypatch.setattr("core.workflow.runtime_ops.write_remote_script", lambda *_args, **_kwargs: "/remote/launch.sh")

    commands: list[str] = []

    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        commands.append(command)
        if "nohup bash -lc" in command:
            return 0, "12345\n", ""
        raise AssertionError(f"unexpected command: {command}")

    item = submit_local_nextflow_run(
        ssh_run_fn,
        remote_task_dir="/remote/task",
        remote_bundle_dir="/remote/task/bundle",
        remote_work_dir="/remote/task/work",
        remote_output_dir="/remote/task/output",
        resume=True,
    )

    assert item["launcher_pid"] == "12345"
    assert any("nohup bash -lc" in command for command in commands)


def test_submit_local_nextflow_run_uses_verified_saved_runtime_without_path_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.workflow.runtime_ops.ensure_remote_dirs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "core.workflow.runtime_ops.resolve_persisted_runtime_binding",
        lambda *_args, **_kwargs: {
            "nextflow_path": "/opt/nextflow/nextflow",
            "nextflow_command": "/opt/nextflow/nextflow",
            "java_home": "/opt/jdk-21",
            "agent_mode_supported": True,
        },
    )
    monkeypatch.setattr("core.workflow.runtime_ops.write_remote_script", lambda *_args, **_kwargs: "/remote/launch.sh")
    seen_scripts: list[str] = []

    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        if command == "docker ps >/dev/null 2>&1":
            return 0, "", ""
        if "nohup bash -lc" in command:
            return 0, "2468\n", ""
        raise AssertionError(f"unexpected command: {command}")

    def capture_script(_run, _path, script, _timeout, label=""):
        _ = label
        seen_scripts.append(script)
        return "/remote/launch.sh"

    monkeypatch.setattr("core.workflow.runtime_ops.write_remote_script", capture_script)

    item = submit_local_nextflow_run(
        ssh_run_fn,
        remote_task_dir="/remote/task",
        remote_bundle_dir="/remote/task/bundle",
        remote_work_dir="/remote/task/work",
        remote_output_dir="/remote/task/output",
        resume=False,
        packaging_mode="container",
        container_runtime="docker",
        resolved_runtime={
            "verification_status": "verified",
            "nextflow_path": "/opt/nextflow/nextflow",
            "nextflow_command": "/opt/nextflow/nextflow",
            "java_path": "/opt/jdk-21/bin/java",
            "java_home": "/opt/jdk-21",
        },
    )

    assert item["launcher_pid"] == "2468"
    assert seen_scripts
    assert 'NEXTFLOW_BIN=/opt/nextflow/nextflow' in seen_scripts[0]
    assert "export NXF_JAVA_HOME=/opt/jdk-21" in seen_scripts[0]
    assert "export NXF_AGENT_MODE=true" in seen_scripts[0]
