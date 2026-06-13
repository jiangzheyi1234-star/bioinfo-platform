from __future__ import annotations

from pathlib import Path

from core.remote_runner.artifact import WorkflowRuntimeArtifact
from core.remote_runner.manager import RemoteRunnerManager


def _fake_workflow_artifact() -> WorkflowRuntimeArtifact:
    return WorkflowRuntimeArtifact(
        version="0.1.0",
        platform="linux-64",
        archive_path=Path(__file__),
        sha256="f" * 64,
        manifest={
            "service": "h2ometa-workflow-runtime",
            "version": "0.1.0",
            "platform": "linux-64",
            "provider": "conda-pack",
            "entrypoints": {
                "python": "workflow-env/bin/python",
                "conda": "workflow-env/bin/conda",
                "condaUnpack": "workflow-env/bin/conda-unpack",
                "snakemake": "workflow-env/bin/snakemake",
            },
            "packages": {"snakemake": "9.19.0"},
        },
        python_entrypoint="workflow-env/bin/python",
        conda_entrypoint="workflow-env/bin/conda",
        conda_unpack_entrypoint="workflow-env/bin/conda-unpack",
        snakemake_entrypoint="workflow-env/bin/snakemake",
    )


def test_marked_workflow_runtime_is_reinstalled_when_verification_fails(monkeypatch) -> None:
    monkeypatch.setattr("core.remote_runner.workflow_runtime.time.sleep", lambda _seconds: None)
    manager = RemoteRunnerManager()
    artifact = _fake_workflow_artifact()
    executed: list[str] = []
    uploads: list[tuple[str, str]] = []

    class FakeSSH:
        def __init__(self) -> None:
            self._snakemake_checks = 0

        def run(self, cmd: str, timeout: int = 10):
            executed.append(cmd)
            if "cat /home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256" in cmd:
                return 0, artifact.sha256, ""
            if "workflow-env/bin/snakemake" in cmd and "--version" in cmd:
                self._snakemake_checks += 1
                if self._snakemake_checks <= 5:
                    return 127, "", "snakemake: not found"
                return 0, "9.19.0\n", ""
            if "sha256sum /home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64.tar.gz" in cmd:
                return 1, "", "missing"
            if "tar -xzf" in cmd:
                return 0, "", ""
            if "conda-unpack" in cmd:
                return 0, "", ""
            if "printf" in cmd and "artifact.sha256" in cmd:
                return 0, "", ""
            if "rm -f /home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64.tar.gz" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            uploads.append((local, remote))

    metadata: dict[str, object] = {}
    runtime = manager._ensure_workflow_runtime(
        ssh_service=FakeSSH(),
        artifact=artifact,
        remote_bundle="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64.tar.gz",
        remote_dir="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64",
        remote_artifact_sha="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256",
        bootstrap_metadata=metadata,
    )

    assert uploads
    assert runtime["provider"] == "conda-pack"
    assert metadata["workflow_runtime"]["action"] == "reinstalled"
    assert any("tar -xzf" in cmd for cmd in executed)
    verify_index = max(index for index, cmd in enumerate(executed) if "workflow-env/bin/snakemake" in cmd)
    marker_index = max(index for index, cmd in enumerate(executed) if "printf" in cmd and "artifact.sha256" in cmd)
    assert marker_index > verify_index
    assert any("rm -f /home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64.tar.gz" in cmd for cmd in executed)


def test_workflow_runtime_command_keeps_remote_paths_posix_on_windows() -> None:
    cmd = RemoteRunnerManager._workflow_runtime_command(
        python_command="/home/zyserver/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/python",
        conda_command="/home/zyserver/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/conda",
        snakemake_command="/home/zyserver/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/snakemake",
    )

    assert "\\home" not in cmd
    assert (
        "PATH=/home/zyserver/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin:$PATH "
        "/home/zyserver/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/python"
    ) in cmd


def test_remote_atomic_write_helpers_use_temporary_targets(tmp_path: Path) -> None:
    uploaded: list[tuple[str, str]] = []
    commands: list[str] = []

    class FakeSSH:
        def upload(self, local: str, remote: str) -> None:
            uploaded.append((local, remote))

        def run(self, cmd: str, timeout: int = 10):
            commands.append(cmd)
            return 0, "", ""

    local_config = tmp_path / "runner.json"
    local_config.write_text("{}", encoding="utf-8")

    RemoteRunnerManager._upload_remote_file_atomic(
        FakeSSH(),
        local_path=local_config,
        remote_path="/home/tester/.h2ometa/runner/shared/config/runner.json",
        step="write remote runner config",
        timeout=10,
    )
    symlink_command = RemoteRunnerManager._atomic_symlink_command(
        target="/home/tester/.h2ometa/runner/releases/0.1.0-control-plane",
        link_path="/home/tester/.h2ometa/runner/current",
    )

    assert uploaded == [
        (
            str(local_config),
            "/home/tester/.h2ometa/runner/shared/config/runner.json.tmp",
        )
    ]
    assert "test -s /home/tester/.h2ometa/runner/shared/config/runner.json.tmp" in commands[0]
    assert "mv -f /home/tester/.h2ometa/runner/shared/config/runner.json.tmp" in commands[0]
    assert "current.tmp" in symlink_command
    assert "mv -Tf /home/tester/.h2ometa/runner/current.tmp /home/tester/.h2ometa/runner/current" in symlink_command
