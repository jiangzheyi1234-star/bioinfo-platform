from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.remote_runner.artifact import RemoteRunnerArtifactError
from core.remote_runner.manager import RemoteRunnerManager, RemoteRunnerManagerError
from tests.helpers.remote_runner_control_plane import _fake_workflow_artifact


def test_bootstrap_requires_local_workflow_runtime_artifact_by_default() -> None:
    manager = RemoteRunnerManager()

    class FailingProvider:
        def resolve(self, **_kwargs):
            raise RemoteRunnerArtifactError("workflow runtime artifact not found")

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            raise AssertionError(f"unexpected remote command: {cmd}")

    manager._workflow_artifact_provider = FailingProvider()

    with pytest.raises(RemoteRunnerManagerError, match="workflow runtime artifact unavailable locally"):
        manager._resolve_workflow_artifact_for_bootstrap(
            ssh_service=FakeSSH(),
            version="0.1.0",
            platform="linux-64",
            remote_dir="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64",
            remote_bundle="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64.tar.gz",
        )


def test_bootstrap_remote_workflow_runtime_registration_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = RemoteRunnerManager()
    artifact = _fake_workflow_artifact()
    artifact = type(artifact)(
        version=artifact.version,
        platform=artifact.platform,
        archive_path=Path("Z:/missing-workflow-runtime.tar.gz"),
        sha256=artifact.sha256,
        manifest=artifact.manifest,
        snakemake_entrypoint=artifact.snakemake_entrypoint,
        conda_unpack_entrypoint=artifact.conda_unpack_entrypoint,
        python_entrypoint=artifact.python_entrypoint,
        conda_entrypoint=artifact.conda_entrypoint,
    )
    executed: list[str] = []

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            executed.append(cmd)
            if "artifact.sha256" in cmd and cmd.startswith("cat "):
                return 1, "", "missing"
            if "workflow-env/bin/snakemake" in cmd and "--version" in cmd:
                return 0, "9.19.0\n", ""
            if "sha256sum" in cmd:
                return 1, "", "missing"
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            raise AssertionError(f"unexpected upload without local artifact: {local} -> {remote}")

    monkeypatch.delenv("H2OMETA_ALLOW_REMOTE_WORKFLOW_RUNTIME_REGISTRATION", raising=False)
    with pytest.raises(RemoteRunnerManagerError, match="workflow runtime artifact unavailable locally"):
        manager._ensure_workflow_runtime(
            ssh_service=FakeSSH(),
            artifact=artifact,
            remote_bundle="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64.tar.gz",
            remote_dir="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64",
            remote_artifact_sha="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256",
            bootstrap_metadata={},
        )

    assert any("workflow-env/bin/snakemake" in cmd for cmd in executed) is False


def test_remote_workflow_runtime_registration_requires_snakemake_package_version() -> None:
    manifest = {
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
        "packages": {},
    }

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if cmd.startswith("cat ") and cmd.endswith("/bootstrap_manifest.json"):
                return 0, json.dumps(manifest), ""
            raise AssertionError(f"unexpected remote command: {cmd}")

    with pytest.raises(RemoteRunnerManagerError, match="must declare snakemake package version"):
        RemoteRunnerManager._resolve_remote_workflow_artifact(
            ssh_service=FakeSSH(),
            version="0.1.0",
            platform="linux-64",
            remote_dir="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64",
            remote_bundle="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64.tar.gz",
            local_error="workflow runtime artifact not found",
        )


def test_workflow_runtime_reuse_requires_matching_snakemake_version() -> None:
    artifact = _fake_workflow_artifact()

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if cmd.startswith("cat ") and cmd.endswith("/artifact.sha256"):
                return 0, artifact.sha256, ""
            if cmd.startswith("cat ") and cmd.endswith("/runner.json"):
                return 0, json.dumps(
                    {
                        "managed_conda_command": "/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/conda",
                        "managed_conda_root_prefix": "/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/micromamba-root",
                        "workflow_runtime_provider": "conda-pack",
                        "workflow_runtime_source": "artifact",
                        "workflow_runtime_version": "0.1.0",
                        "snakemake_command": "/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/snakemake",
                        "snakemake_version": "",
                    }
                ), ""
            raise AssertionError(f"unexpected remote command: {cmd}")

    with pytest.raises(RemoteRunnerManagerError, match="workflow runtime config mismatch: snakemake_version"):
        RemoteRunnerManager._verify_workflow_runtime_for_reuse(
            ssh_service=FakeSSH(),
            artifact=artifact,
            remote_dir="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64",
            remote_artifact_sha="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256",
            remote_config="/home/tester/.h2ometa/runner/shared/config/runner.json",
        )


def test_diagnostic_service_inspection_does_not_start_second_runner() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "inspect_remote_runner_service.py"
    text = script.read_text(encoding="utf-8")

    assert "MANUAL_LAUNCH" not in text
    assert "./launch_remote_runner.sh" not in text
