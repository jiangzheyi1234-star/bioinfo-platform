from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from apps.remote_runner.config import (
    ensure_runtime_layout,
    get_runtime_state_path,
    inspect_workflow_runtime,
    load_remote_runner_config,
    write_runtime_state,
)
from apps.remote_runner.main import (
    UploadCreateRequest,
    RunCreateRequest,
    create_upload,
    create_run,
    get_pipeline_api,
    get_pipelines,
    get_result_api,
    get_result_preview_api,
    get_run as get_run_api,
    get_run_events_api,
    get_run_logs_api,
    get_run_results_api,
    list_results_api,
    get_runs as list_runs_api,
    health_live,
    health_ready,
    health_startup,
)
from apps.remote_runner.config import RemoteRunnerConfig
from apps.remote_runner.executor import run_snakemake_execution
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION, RemoteRunnerBundleBuilder
from core.remote_runner.client import RemoteRunnerClientError
from core.remote_runner.manager import RemoteRunnerManager, RemoteRunnerManagerError
from core.remote_runner.artifact import RemoteRunnerArtifactError, WorkflowRuntimeArtifact
from config import get_app_cache_dir

_ORIGINAL_ENSURE_WORKFLOW_RUNTIME = RemoteRunnerManager._ensure_workflow_runtime


def _runtime_state_json(port: int = 43127) -> str:
    return json.dumps(
        {
            "service": "h2ometa-remote",
            "version": REMOTE_RUNNER_VERSION,
            "pid": 123,
            "bindHost": "127.0.0.1",
            "bindPort": port,
            "startedAt": "2026-04-22T00:00:00Z",
        }
    )


def _fake_runtime_dir(tmp_path: Path) -> Path:
    runtime = tmp_path / "runtime"
    bin_dir = runtime / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    python = bin_dir / "python"
    python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
    python.chmod(0o755)
    return runtime


def _write_file_summary_pipeline(release_dir: Path) -> None:
    pipeline_dir = release_dir / "pipelines" / "file-summary-v1"
    (pipeline_dir / "envs").mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "pipeline.json").write_text(
        json.dumps(
            {
                "pipelineId": "file-summary-v1",
                "name": "File Summary",
                "version": "1.0.0",
                "category": "Sequence Utilities",
                "icon": "file-text",
                "tags": ["fastq", "summary"],
                "author": "H2OMeta",
                "license": "internal",
                "status": "installed",
                "enabled": True,
                "snakefile": "Snakefile",
                "inputsSchema": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["uploadId"],
                        "properties": {
                            "uploadId": {"type": "string", "minLength": 1},
                            "filename": {"type": "string"},
                            "role": {"type": "string"},
                        },
                    },
                },
                "paramsSchema": {
                    "type": "object",
                    "properties": {"threads": {"type": "integer", "minimum": 1, "maximum": 64}},
                    "additionalProperties": True,
                },
                "outputSchema": {"type": "object"},
                "uiSchema": {"inputs": {"widget": "file-upload"}},
            }
        ),
        encoding="utf-8",
    )
    (pipeline_dir / "Snakefile").write_text("rule all:\n  input: 'done.txt'\n", encoding="utf-8")
    (pipeline_dir / "envs" / "base.yaml").write_text(
        "channels: [conda-forge]\ndependencies: [python=3.12]\n",
        encoding="utf-8",
    )


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


@pytest.fixture(autouse=True)
def _default_workflow_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.remote_runner.manager.WorkflowRuntimeArtifactProvider.resolve",
        lambda self, **kwargs: _fake_workflow_artifact(),
    )
    monkeypatch.setattr(
        "core.remote_runner.manager.RemoteRunnerManager._ensure_workflow_runtime",
        lambda self, **kwargs: self._build_workflow_runtime_metadata(
            artifact=kwargs["artifact"],
            remote_dir=kwargs["remote_dir"],
        ),
    )


def test_get_app_cache_dir_prefers_platform_cache_locations(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("config.os.name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-appdata"))
    assert get_app_cache_dir() == tmp_path / "local-appdata" / "H2OMeta" / "Cache"


def test_remote_runner_config_defaults_to_dynamic_loopback_port() -> None:
    cfg = RemoteRunnerConfig()

    assert cfg.bind_host == "127.0.0.1"
    assert cfg.bind_port == 0
    assert Path(cfg.runtime_state_path).parts[-2:] == ("runtime", "runner-state.json")


def test_write_runtime_state_records_assigned_port(tmp_path: Path) -> None:
    cfg = RemoteRunnerConfig(
        version="test-version",
        data_root=str(tmp_path / "shared"),
        runtime_state_path=str(tmp_path / "shared" / "runtime" / "runner-state.json"),
    )

    state = write_runtime_state(cfg, bind_host="127.0.0.1", bind_port=43127, pid=123)
    payload = json.loads(get_runtime_state_path(cfg).read_text(encoding="utf-8"))

    assert state["bindPort"] == 43127
    assert payload["service"] == "h2ometa-remote"
    assert payload["version"] == "test-version"
    assert payload["bindHost"] == "127.0.0.1"
    assert payload["bindPort"] == 43127
    assert payload["pid"] == 123


def test_remote_runner_bundle_contains_expected_phase1_files(tmp_path: Path) -> None:
    builder = RemoteRunnerBundleBuilder()
    bundle = builder.build(version=REMOTE_RUNNER_VERSION, platform="linux-64", runtime_dir=_fake_runtime_dir(tmp_path))

    assert (bundle.bundle_dir / "remote_runner" / "main.py").exists()
    assert (bundle.bundle_dir / "remote_runner" / "run.py").exists()
    assert (bundle.bundle_dir / "remote_runner" / "requirements.txt").exists()
    assert (bundle.bundle_dir / "remote_runner" / "pipelines" / "file-summary-v1" / "pipeline.json").exists()
    assert (bundle.bundle_dir / "remote_runner" / "pipelines" / "file-summary-v1" / "Snakefile").exists()
    assert (bundle.bundle_dir / "remote_runner" / "pipelines" / "file-summary-v1" / "envs" / "base.yaml").exists()
    assert (
        bundle.bundle_dir
        / "remote_runner"
        / "pipelines"
        / "file-summary-v1"
        / "scripts"
        / "generate_outputs.py"
    ).exists()
    assert (bundle.bundle_dir / "runtime" / "bin" / "python").exists()
    assert (bundle.bundle_dir / "h2ometa-remote.service").exists()
    assert (bundle.bundle_dir / "start_service.sh").exists()
    assert (bundle.bundle_dir / "launch_remote_runner.sh").exists()
    assert (bundle.bundle_dir / "check_service.sh").exists()
    assert (bundle.bundle_dir / "run_workflow.sh").exists()
    assert "launch_remote_runner.sh" in (bundle.bundle_dir / "start_service.sh").read_text(encoding="utf-8")
    assert "launch_remote_runner.sh" in (bundle.bundle_dir / "h2ometa-remote.service").read_text(encoding="utf-8")
    launch_script_path = bundle.bundle_dir / "launch_remote_runner.sh"
    launch_script = launch_script_path.read_text(encoding="utf-8")
    assert "RUNNER_PYTHON" in launch_script
    assert 'runtime/bin/python' in launch_script
    assert "conda-unpack" in launch_script
    assert 'cd "$RUN_DIR"' in launch_script
    assert b"\r\n" not in launch_script_path.read_bytes()
    assert bundle.archive_path.exists()
    assert bundle.platform == "linux-64"
    requirements = (bundle.bundle_dir / "remote_runner" / "requirements.txt").read_text(encoding="utf-8")
    assert "snakemake" not in requirements


def test_bootstrap_extract_step_marks_remote_scripts_executable(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    executed: list[str] = []

    class FakeBundle:
        archive_path = Path(__file__)

    class FakeTunnel:
        local_port = 18765

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            executed.append(cmd)
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if 'printf "%s:%s" "$(uname -s)" "$(uname -m)"' in cmd:
                return 0, "Linux:x86_64", ""
            if "systemctl --user show-environment" in cmd:
                return 0, "background_process\n", ""
            if "mkdir -p" in cmd:
                return 0, "", ""
            if "pkill -f '[r]emote_runner.run'" in cmd and "runner-state.json" in cmd:
                return 0, "", ""
            if "tar -xzf" in cmd:
                return 0, "", ""
            if "runtime/bin/python -c \"from remote_runner.config import load_remote_runner_config, ensure_runtime_layout; ensure_runtime_layout(load_remote_runner_config())\"" in cmd:
                return 0, "", ""
            if "rm -f /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, "", ""
            if "bash /home/tester/.h2ometa/runner/current/start_service.sh" in cmd:
                return 0, "", ""
            if "cat /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, _runtime_state_json(), ""
            if "kill -0 123" in cmd:
                return 0, "", ""
            if "cat /home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256" in cmd:
                return 0, "f" * 64, ""
            if "cat /home/tester/.h2ometa/runner/shared/config/runner.json" in cmd:
                return 0, json.dumps(
                    {
                        "managed_conda_command": "/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/conda",
                        "managed_conda_root_prefix": "/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/micromamba-root",
                        "workflow_runtime_provider": "conda-pack",
                        "workflow_runtime_source": "artifact",
                        "workflow_runtime_version": "0.1.0",
                        "snakemake_command": "/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/snakemake",
                    }
                ), ""
            if "workflow-env/bin/snakemake" in cmd and "--version" in cmd:
                return 0, "9.19.0\n", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            return None

        def ensure_local_tunnel(self, *args, **kwargs):
            assert kwargs["remote_port"] == 43127
            return FakeTunnel()

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def get_health(self) -> dict[str, object]:
            return {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-04-22T00:00:00Z",
            }

        def get_json(self, path: str) -> dict[str, object]:
            assert path == "/api/v1/database-templates"
            return {"data": {"items": [{"id": "kraken2"}]}}

    with patch.object(manager, "_artifact_provider", SimpleNamespace(resolve=lambda **kwargs: FakeBundle())), patch(
        "core.remote_runner.manager.RemoteRunnerHttpClient", FakeClient
    ), patch(
        "core.remote_runner.manager.store_runner_token", lambda **kwargs: "runner://srv_test"
    ):
        result = manager.bootstrap(
            server_id="srv_test",
            server={"label": "demo"},
            ssh_service=FakeSSH(),
            server_record={},
        )

    extract_cmd = next(cmd for cmd in executed if "tar -xzf" in cmd)
    assert "chmod 0755" in extract_cmd
    assert "bundle-0.1.0-control-plane.tar.gz" in extract_cmd
    assert result["service_port"] == 43127
    assert any("rm -f /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd for cmd in executed)
    assert not any("micromamba" in cmd for cmd in executed)
    assert not any("python3 -m venv" in cmd for cmd in executed)
    assert result["bootstrap_metadata"]["tooling"]["service_runtime"]["provider"] == "bundled"
    assert result["bootstrap_metadata"]["tooling"]["service_runtime"]["source"] == "artifact"


def test_bootstrap_registers_remote_workflow_runtime_when_local_artifact_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.remote_runner.manager.RemoteRunnerManager._ensure_workflow_runtime",
        _ORIGINAL_ENSURE_WORKFLOW_RUNTIME,
    )
    manager = RemoteRunnerManager()
    executed: list[str] = []
    uploads: list[tuple[str, str]] = []
    uploaded_config: dict[str, object] = {}

    class FakeBundle:
        archive_path = Path(__file__)
        sha256 = "e" * 64
        platform = "linux-64"

    class FakeTunnel:
        local_port = 18765

    def missing_workflow_artifact(**kwargs):
        raise RemoteRunnerArtifactError("local workflow runtime artifact missing")

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            executed.append(cmd)
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if "cat /home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/bootstrap_manifest.json" in cmd:
                return 0, json.dumps(_fake_workflow_artifact().manifest), ""
            if "cat /home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256" in cmd:
                return 1, "", "missing"
            if "sha256sum /home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64.tar.gz" in cmd:
                return 0, "f" * 64 + "  /home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64.tar.gz\n", ""
            if 'printf "%s:%s" "$(uname -s)" "$(uname -m)"' in cmd:
                return 0, "Linux:x86_64", ""
            if "systemctl --user show-environment" in cmd:
                return 0, "background_process\n", ""
            if "mkdir -p" in cmd:
                return 0, "", ""
            if "pkill -f '[r]emote_runner.run'" in cmd and "runner-state.json" in cmd:
                return 0, "", ""
            if "tar -xzf" in cmd and "bundle-0.1.0-control-plane.tar.gz" in cmd:
                return 0, "", ""
            if "workflow-env/bin/snakemake" in cmd and "--version" in cmd:
                return 0, "9.19.0\n", ""
            if "printf %s" in cmd and "artifact.sha256" in cmd:
                return 0, "", ""
            if "cat /home/tester/.h2ometa/runner/shared/config/runner.json" in cmd:
                return 0, json.dumps(uploaded_config), ""
            if "runtime/bin/python -c \"from remote_runner.config import load_remote_runner_config, ensure_runtime_layout; ensure_runtime_layout(load_remote_runner_config())\"" in cmd:
                return 0, "", ""
            if "rm -f /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, "", ""
            if "bash /home/tester/.h2ometa/runner/current/start_service.sh" in cmd:
                return 0, "", ""
            if "cat /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, _runtime_state_json(), ""
            if "kill -0 123" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            uploads.append((local, remote))
            if remote in {"/home/tester/.h2ometa/runner/shared/config/runner.json", "/home/tester/.h2ometa/runner/shared/config/runner.json.tmp"}:
                uploaded_config.update(json.loads(Path(local).read_text(encoding="utf-8")))

        def ensure_local_tunnel(self, *args, **kwargs):
            assert kwargs["remote_port"] == 43127
            return FakeTunnel()

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def get_health(self) -> dict[str, object]:
            return {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-04-22T00:00:00Z",
            }

    with patch.object(manager, "_artifact_provider", SimpleNamespace(resolve=lambda **kwargs: FakeBundle())), patch.object(
        manager, "_workflow_artifact_provider", SimpleNamespace(resolve=missing_workflow_artifact)
    ), patch("core.remote_runner.manager.RemoteRunnerHttpClient", FakeClient), patch(
        "core.remote_runner.manager.store_runner_token", lambda **kwargs: "runner://srv_test"
    ):
        result = manager.bootstrap(
            server_id="srv_test",
            server={"label": "demo"},
            ssh_service=FakeSSH(),
            server_record={},
        )

    remote_uploads = [remote for _local, remote in uploads]
    assert "/home/tester/.h2ometa/runner/shared/config/runner.json" in remote_uploads
    assert "/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64.tar.gz" not in remote_uploads
    assert any("ln -sfn /home/tester/.h2ometa/runner/releases/0.1.0-control-plane /home/tester/.h2ometa/runner/current" in cmd for cmd in executed)
    assert any("printf %s" in cmd and "workflow-runtime-0.1.0-linux-64/artifact.sha256" in cmd for cmd in executed)
    assert result["bootstrap_metadata"]["workflow_runtime"]["action"] == "registered"
    assert result["health"]["ready"]["ok"] is True


def test_wait_for_runtime_state_rejects_dead_runner_pid() -> None:
    manager = RemoteRunnerManager()

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if "cat /remote/runner-state.json" in cmd:
                return 0, _runtime_state_json(), ""
            if "kill -0 123" in cmd:
                return 1, "", "No such process"
            raise AssertionError(f"unexpected command: {cmd}")

    try:
        manager._wait_for_runtime_state(
            ssh_service=FakeSSH(),
            remote_runtime_state="/remote/runner-state.json",
            version=REMOTE_RUNNER_VERSION,
            attempts=1,
            delay_seconds=0,
        )
    except RemoteRunnerManagerError as exc:
        assert "not running" in str(exc)
    else:
        raise AssertionError("dead runner pid should be rejected")


def test_bootstrap_reuses_existing_runner_without_resolving_local_artifact(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    executed: list[str] = []
    uploads: list[tuple[str, str]] = []

    class FakeTunnel:
        local_port = 18765

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            executed.append(cmd)
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if "readlink -f /home/tester/.h2ometa/runner/current" in cmd:
                return 0, "/home/tester/.h2ometa/runner/releases/0.1.0-control-plane\n", ""
            if "cat /home/tester/.h2ometa/runner/releases/0.1.0-control-plane/bootstrap_manifest.json" in cmd:
                return 0, json.dumps(
                    {
                        "service": "h2ometa-remote",
                        "version": REMOTE_RUNNER_VERSION,
                        "platform": "linux-64",
                        "runtime": {"provider": "bundled", "python": "runtime/bin/python"},
                    }
                ), ""
            if "cat /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, _runtime_state_json(), ""
            if "kill -0 123" in cmd:
                return 0, "", ""
            if "cat /home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256" in cmd:
                return 0, "f" * 64, ""
            if "cat /home/tester/.h2ometa/runner/shared/config/runner.json" in cmd:
                return 0, json.dumps(
                    {
                        "managed_conda_command": "/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/conda",
                        "managed_conda_root_prefix": "/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/micromamba-root",
                        "workflow_runtime_provider": "conda-pack",
                        "workflow_runtime_source": "artifact",
                        "workflow_runtime_version": "0.1.0",
                        "snakemake_command": "/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/snakemake",
                    }
                ), ""
            if "workflow-env/bin/snakemake" in cmd and "--version" in cmd:
                return 0, "9.19.0\n", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            uploads.append((local, remote))

        def ensure_local_tunnel(self, *args, **kwargs):
            assert kwargs["remote_port"] == 43127
            return FakeTunnel()

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def get_health(self) -> dict[str, object]:
            return {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-04-22T00:00:00Z",
            }

    def fail_if_artifact_resolves(**_kwargs):
        raise AssertionError("reuse path should not resolve the local runner artifact")

    with patch.object(manager, "_artifact_provider", SimpleNamespace(resolve=fail_if_artifact_resolves)), patch(
        "core.remote_runner.manager.RemoteRunnerHttpClient", FakeClient
    ), patch("core.remote_runner.manager.resolve_runner_token", lambda token_ref: "phase2-token"), patch(
        "core.remote_runner.manager.store_runner_token"
    ) as store_token:
        result = manager.bootstrap(
            server_id="srv_test",
            server={"label": "demo"},
            ssh_service=FakeSSH(),
            server_record={
                "bootstrap_version": REMOTE_RUNNER_VERSION,
                "runner_mode": "systemd_user",
                "token_ref": "runner://srv_test",
                "bootstrap_metadata": {
                    "preflight": {"platform": "linux-64"},
                    "tooling": {
                        "workflow_runtime": {
                            "artifact_sha": "f" * 64,
                            "snakemake_command": "/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/snakemake",
                        }
                    },
                },
            },
        )

    assert result["service_port"] == 43127
    assert result["token_ref"] == "runner://srv_test"
    assert result["bootstrap_metadata"]["deployment_action"] == "reused"
    assert result["bootstrap_metadata"]["reuse_check"]["ok"] is True
    assert uploads == []
    assert not any("tar -xzf" in cmd for cmd in executed)
    assert not any("pkill -f" in cmd for cmd in executed)
    store_token.assert_not_called()


def test_fast_reuse_rejects_runner_when_workflow_runtime_marker_is_missing(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    metadata = {
        "tooling": {
            "workflow_runtime": {
                "artifact_sha": "f" * 64,
                "snakemake_command": "/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/snakemake",
            }
        }
    }

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if "readlink -f /home/tester/.h2ometa/runner/current" in cmd:
                return 0, "/home/tester/.h2ometa/runner/releases/0.1.0-control-plane\n", ""
            if "cat /home/tester/.h2ometa/runner/releases/0.1.0-control-plane/bootstrap_manifest.json" in cmd:
                return 0, json.dumps(
                    {
                        "service": "h2ometa-remote",
                        "version": REMOTE_RUNNER_VERSION,
                        "platform": "linux-64",
                        "runtime": {"provider": "bundled", "python": "runtime/bin/python"},
                    }
                ), ""
            if "cat /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, _runtime_state_json(), ""
            if "kill -0 123" in cmd:
                return 0, "", ""
            if "cat /home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256" in cmd:
                return 1, "", "No such file"
            raise AssertionError(f"unexpected command: {cmd}")

        def ensure_local_tunnel(self, *args, **kwargs):
            raise AssertionError("workflow runtime must be verified before opening a tunnel")

    monkeypatch.setattr("core.remote_runner.manager.resolve_runner_token", lambda token_ref: "phase2-token")
    result = manager._try_reuse_existing_runner_fast(
        server_id="srv_test",
        ssh_service=FakeSSH(),
        server_record={
            "bootstrap_version": REMOTE_RUNNER_VERSION,
            "runner_mode": "systemd_user",
            "token_ref": "runner://srv_test",
        },
        version=REMOTE_RUNNER_VERSION,
        remote_release="/home/tester/.h2ometa/runner/releases/0.1.0-control-plane",
        remote_current="/home/tester/.h2ometa/runner/current",
        remote_runtime_state="/home/tester/.h2ometa/runner/shared/runtime/runner-state.json",
        remote_config="/home/tester/.h2ometa/runner/shared/config/runner.json",
        workflow_artifact=_fake_workflow_artifact(),
        workflow_runtime_dir="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64",
        remote_workflow_artifact_sha="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256",
        bootstrap_metadata=metadata,
    )

    assert result is None
    assert metadata["reuse_check"] == {"ok": False, "reason": "No such file"}


def test_fast_reuse_rejects_runner_when_database_template_route_is_missing(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    metadata = {
        "tooling": {
            "workflow_runtime": {
                "artifact_sha": "f" * 64,
                "snakemake_command": "/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/snakemake",
            }
        }
    }

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if "readlink -f /home/tester/.h2ometa/runner/current" in cmd:
                return 0, "/home/tester/.h2ometa/runner/releases/0.1.0-control-plane\n", ""
            if "cat /home/tester/.h2ometa/runner/releases/0.1.0-control-plane/bootstrap_manifest.json" in cmd:
                return 0, json.dumps(
                    {
                        "service": "h2ometa-remote",
                        "version": REMOTE_RUNNER_VERSION,
                        "platform": "linux-64",
                        "runtime": {"provider": "bundled", "python": "runtime/bin/python"},
                    }
                ), ""
            if "cat /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, _runtime_state_json(), ""
            if "kill -0 123" in cmd:
                return 0, "", ""
            if "cat /home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256" in cmd:
                return 0, "f" * 64, ""
            if "cat /home/tester/.h2ometa/runner/shared/config/runner.json" in cmd:
                return 0, json.dumps(
                    {
                        "managed_conda_command": "/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/conda",
                        "managed_conda_root_prefix": "/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/micromamba-root",
                        "workflow_runtime_provider": "conda-pack",
                        "workflow_runtime_source": "artifact",
                        "workflow_runtime_version": "0.1.0",
                        "snakemake_command": "/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/snakemake",
                    }
                ), ""
            if "PATH=" in cmd and "import snakemake" in cmd:
                return 0, "9.19.0\n", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def ensure_local_tunnel(self, *args, **kwargs):
            class FakeTunnel:
                local_port = 18765

            return FakeTunnel()

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def get_health(self) -> dict[str, object]:
            return {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-04-22T00:00:00Z",
            }

        def get_json(self, path: str) -> dict[str, object]:
            raise RemoteRunnerClientError("runner http error 404: Not Found")

    monkeypatch.setattr("core.remote_runner.manager.resolve_runner_token", lambda token_ref: "phase2-token")
    monkeypatch.setattr("core.remote_runner.manager.RemoteRunnerHttpClient", FakeClient)
    result = manager._try_reuse_existing_runner_fast(
        server_id="srv_test",
        ssh_service=FakeSSH(),
        server_record={
            "bootstrap_version": REMOTE_RUNNER_VERSION,
            "runner_mode": "systemd_user",
            "token_ref": "runner://srv_test",
        },
        version=REMOTE_RUNNER_VERSION,
        remote_release="/home/tester/.h2ometa/runner/releases/0.1.0-control-plane",
        remote_current="/home/tester/.h2ometa/runner/current",
        remote_runtime_state="/home/tester/.h2ometa/runner/shared/runtime/runner-state.json",
        remote_config="/home/tester/.h2ometa/runner/shared/config/runner.json",
        workflow_artifact=_fake_workflow_artifact(),
        workflow_runtime_dir="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64",
        remote_workflow_artifact_sha="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256",
        bootstrap_metadata=metadata,
    )

    assert result is None
    assert metadata["reuse_check"] == {"ok": False, "reason": "runner http error 404: Not Found"}


def test_remote_install_lock_waits_until_atomic_mkdir_succeeds(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    calls: list[str] = []
    sleeps: list[float] = []

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            calls.append(cmd)
            if len(calls) == 1:
                return 0, "busy", ""
            return 0, "acquired", ""

    monkeypatch.setattr("core.remote_runner.manager.time.sleep", lambda seconds: sleeps.append(seconds))
    metadata: dict[str, object] = {}

    manager._acquire_remote_install_lock(
        ssh_service=FakeSSH(),
        lock_dir="/home/tester/.h2ometa/runner/locks/install-test.lock",
        remote_root="/home/tester/.h2ometa/runner",
        bootstrap_metadata=metadata,
        attempts=2,
        delay_seconds=0.25,
    )

    assert len(calls) == 2
    assert sleeps == [0.25]
    assert metadata["install_lock"] == {
        "path": "/home/tester/.h2ometa/runner/locks/install-test.lock",
        "acquired": True,
        "waited": True,
    }


def test_remote_install_lock_fails_when_busy() -> None:
    manager = RemoteRunnerManager()

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            return 0, "busy", ""

    try:
        manager._acquire_remote_install_lock(
            ssh_service=FakeSSH(),
            lock_dir="/home/tester/.h2ometa/runner/locks/install-test.lock",
            remote_root="/home/tester/.h2ometa/runner",
            bootstrap_metadata={},
            attempts=1,
            delay_seconds=0,
        )
    except RemoteRunnerManagerError as exc:
        assert "install lock is busy" in str(exc)
    else:
        raise AssertionError("busy install lock should fail after attempts are exhausted")


def test_bootstrap_installs_when_artifact_sha_marker_is_missing(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    executed: list[str] = []
    uploads: list[tuple[str, str]] = []

    class FakeArtifact:
        archive_path = Path(__file__)
        platform = "linux-64"
        sha256 = "b" * 64

    class FakeTunnel:
        local_port = 18765

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            executed.append(cmd)
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if 'printf "%s:%s" "$(uname -s)" "$(uname -m)"' in cmd:
                return 0, "Linux:x86_64", ""
            if "systemctl --user show-environment" in cmd:
                return 0, "background_process\n", ""
            if "readlink -f /home/tester/.h2ometa/runner/current" in cmd:
                return 0, "/home/tester/.h2ometa/runner/releases/0.1.0-control-plane\n", ""
            if "cat /home/tester/.h2ometa/runner/releases/0.1.0-control-plane/bootstrap_manifest.json" in cmd:
                return 0, json.dumps(
                    {
                        "service": "h2ometa-remote",
                        "version": REMOTE_RUNNER_VERSION,
                        "platform": "linux-64",
                        "runtime": {"provider": "bundled", "python": "runtime/bin/python"},
                    }
                ), ""
            if "cat /home/tester/.h2ometa/runner/releases/0.1.0-control-plane/artifact.sha256" in cmd:
                return 1, "", "No such file"
            if "mkdir -p" in cmd:
                return 0, "", ""
            if "pkill -f '[r]emote_runner.run'" in cmd and "runner-state.json" in cmd:
                return 0, "", ""
            if "tar -xzf" in cmd:
                return 0, "", ""
            if "printf %s" in cmd and "artifact.sha256" in cmd:
                return 0, "", ""
            if "runtime/bin/python -c \"from remote_runner.config import load_remote_runner_config, ensure_runtime_layout; ensure_runtime_layout(load_remote_runner_config())\"" in cmd:
                return 0, "", ""
            if "rm -f /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, "", ""
            if "bash /home/tester/.h2ometa/runner/current/start_service.sh" in cmd:
                return 0, "", ""
            if "cat /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, _runtime_state_json(), ""
            if "kill -0 123" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            uploads.append((local, remote))

        def ensure_local_tunnel(self, *args, **kwargs):
            assert kwargs["remote_port"] == 43127
            return FakeTunnel()

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def get_health(self) -> dict[str, object]:
            return {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-04-22T00:00:00Z",
            }

    with patch.object(manager, "_artifact_provider", SimpleNamespace(resolve=lambda **kwargs: FakeArtifact())), patch(
        "core.remote_runner.manager.RemoteRunnerHttpClient", FakeClient
    ), patch("core.remote_runner.manager.resolve_runner_token", lambda token_ref: "phase2-token"), patch(
        "core.remote_runner.manager.store_runner_token", lambda **kwargs: "runner://srv_test"
    ):
        result = manager.bootstrap(
            server_id="srv_test",
            server={"label": "demo"},
            ssh_service=FakeSSH(),
            server_record={"token_ref": "runner://srv_test"},
        )

    assert result["bootstrap_metadata"]["deployment_action"] == "installed"
    assert result["bootstrap_metadata"]["reuse_check"]["ok"] is False
    assert result["bootstrap_metadata"]["reuse_check"]["reason"] == "artifact sha marker missing"
    assert uploads
    assert any("tar -xzf" in cmd for cmd in executed)
    assert any("printf %s" in cmd and "artifact.sha256" in cmd for cmd in executed)


def test_bootstrap_fails_fast_when_artifact_cannot_be_resolved() -> None:
    manager = RemoteRunnerManager()

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if 'printf "%s:%s" "$(uname -s)" "$(uname -m)"' in cmd:
                return 0, "Linux:x86_64", ""
            if "systemctl --user show-environment" in cmd:
                return 0, "background_process\n", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            return None

        def ensure_local_tunnel(self, *args, **kwargs):
            raise AssertionError("bootstrap should fail before tunnel setup")

    def fail_resolve(**_kwargs):
        raise RuntimeError("remote runner artifact not found")

    with patch.object(manager, "_artifact_provider", SimpleNamespace(resolve=fail_resolve)):
        try:
            manager.bootstrap(
                server_id="srv_test",
                server={"label": "demo"},
                ssh_service=FakeSSH(),
                server_record={},
            )
        except RemoteRunnerManagerError as exc:
            assert "remote runner artifact not found" in str(exc)
        else:
            raise AssertionError("bootstrap should fail when artifact cannot be resolved")


def test_remote_runner_health_endpoints_require_auth_and_do_not_mutate_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "token": "phase1-token",
                "data_root": str(tmp_path / "shared"),
                "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
                "uploads_dir": str(tmp_path / "shared" / "uploads"),
                "results_dir": str(tmp_path / "shared" / "results"),
                "work_dir": str(tmp_path / "shared" / "work"),
                "logs_dir": str(tmp_path / "shared" / "logs"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    try:
        asyncio.run(health_startup(authorization=None))
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("health_startup should require authorization")

    cfg = load_remote_runner_config()
    ensure_runtime_layout(cfg)
    startup = asyncio.run(health_startup(authorization="Bearer phase1-token"))
    live = asyncio.run(health_live(authorization="Bearer phase1-token"))
    ready = asyncio.run(health_ready(authorization="Bearer phase1-token"))

    assert startup["status"] == "ok"
    assert live["status"] == "ok"
    assert ready["status"] == "failed"
    assert ready["checks"]["workflow_runtime"] is False
    assert ready["workflowRuntime"]["ok"] is False
    assert Path(tmp_path / "shared" / "data" / "runner.db").exists()


def test_remote_runner_health_does_not_create_runtime_layout(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "token": "phase1-token",
                "data_root": str(tmp_path / "shared"),
                "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
                "uploads_dir": str(tmp_path / "shared" / "uploads"),
                "results_dir": str(tmp_path / "shared" / "results"),
                "work_dir": str(tmp_path / "shared" / "work"),
                "logs_dir": str(tmp_path / "shared" / "logs"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    startup = asyncio.run(health_startup(authorization="Bearer phase1-token"))
    ready = asyncio.run(health_ready(authorization="Bearer phase1-token"))

    assert startup["status"] == "failed"
    assert ready["status"] == "failed"
    assert not Path(tmp_path / "shared" / "data" / "runner.db").exists()


def test_load_remote_runner_config_preserves_workflow_runtime_metadata(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
    managed_conda_command = tmp_path / "tooling" / "bin" / "micromamba"
    managed_conda_root_prefix = tmp_path / "tooling" / "micromamba-root"
    snakemake_command = tmp_path / "tooling" / "workflow-env" / "bin" / "snakemake"
    config_path.write_text(
        json.dumps(
            {
                "token": "phase2-token",
                "data_root": str(tmp_path / "shared"),
                "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
                "uploads_dir": str(tmp_path / "shared" / "uploads"),
                "results_dir": str(tmp_path / "shared" / "results"),
                "work_dir": str(tmp_path / "shared" / "work"),
                "logs_dir": str(tmp_path / "shared" / "logs"),
                "managed_conda_command": str(managed_conda_command),
                "managed_conda_root_prefix": str(managed_conda_root_prefix),
                "workflow_runtime_provider": "micromamba",
                "workflow_runtime_source": "managed",
                "snakemake_command": str(snakemake_command),
                "snakemake_version": "9.1.0",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    cfg = load_remote_runner_config()

    assert cfg.managed_conda_command == str(managed_conda_command)
    assert cfg.managed_conda_root_prefix == str(managed_conda_root_prefix)
    assert cfg.workflow_runtime_provider == "micromamba"
    assert cfg.workflow_runtime_source == "managed"
    assert cfg.snakemake_command == str(snakemake_command)
    assert cfg.snakemake_version == "9.1.0"


def test_inspect_workflow_runtime_runs_snakemake_with_workflow_bin_on_path(tmp_path: Path, monkeypatch) -> None:
    managed_conda_command = tmp_path / "tooling" / "workflow-env" / "bin" / "conda"
    snakemake_command = tmp_path / "tooling" / "workflow-env" / "bin" / "snakemake"
    managed_conda_command.parent.mkdir(parents=True, exist_ok=True)
    managed_conda_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    managed_conda_command.chmod(0o755)
    snakemake_command.write_text("#!/usr/bin/env python3.12\n", encoding="utf-8")
    snakemake_command.chmod(0o755)
    cfg = RemoteRunnerConfig(
        managed_conda_command=str(managed_conda_command),
        snakemake_command=str(snakemake_command),
    )
    calls: list[dict[str, object]] = []

    class Result:
        returncode = 0
        stdout = "9.19.0\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, "env": kwargs.get("env")})
        return Result()

    monkeypatch.setattr("apps.remote_runner.config.subprocess.run", fake_run)

    result = inspect_workflow_runtime(cfg)

    assert result["ok"] is True
    assert calls[0]["cmd"] == [str(snakemake_command), "--version"]
    env = calls[0]["env"]
    assert isinstance(env, dict)
    assert env["PATH"].split(os.pathsep)[0] == str(snakemake_command.parent)


def test_bootstrap_workflow_runtime_installs_artifact_and_verifies_snakemake(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.remote_runner.manager.RemoteRunnerManager._ensure_workflow_runtime",
        _ORIGINAL_ENSURE_WORKFLOW_RUNTIME,
    )
    monkeypatch.setattr("core.remote_runner.manager.time.sleep", lambda _seconds: None)
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
                return 1, "", "missing"
            if "workflow-env/bin/snakemake" in cmd and "--version" in cmd:
                self._snakemake_checks += 1
                if self._snakemake_checks <= 5:
                    return 127, "", "missing"
                return 0, "9.19.0\n", ""
            if "sha256sum /home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64.tar.gz" in cmd:
                return 1, "", "missing"
            if "tar -xzf" in cmd:
                return 0, "", ""
            if "conda-unpack" in cmd:
                return 0, "", ""
            if "printf %s" in cmd and "artifact.sha256" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            uploads.append((local, remote))

    runtime = manager._ensure_workflow_runtime(
        ssh_service=FakeSSH(),
        artifact=artifact,
        remote_bundle="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64.tar.gz",
        remote_dir="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64",
        remote_artifact_sha="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256",
        bootstrap_metadata={},
    )

    assert uploads
    assert runtime["provider"] == "conda-pack"
    assert runtime["source"] == "artifact"
    assert runtime["snakemake_command"].endswith("/workflow-env/bin/snakemake")
    assert any("conda-unpack" in cmd for cmd in executed)
    assert any("PATH=" in cmd and "workflow-env/bin/snakemake" in cmd and "--version" in cmd for cmd in executed)


def test_bootstrap_workflow_runtime_registers_existing_remote_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.remote_runner.manager.RemoteRunnerManager._ensure_workflow_runtime",
        _ORIGINAL_ENSURE_WORKFLOW_RUNTIME,
    )
    manager = RemoteRunnerManager()
    artifact = _fake_workflow_artifact()
    executed: list[str] = []
    uploads: list[tuple[str, str]] = []

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            executed.append(cmd)
            if "cat /home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256" in cmd:
                return 1, "", "missing"
            if "workflow-env/bin/snakemake" in cmd and "--version" in cmd:
                return 0, "9.19.0\n", ""
            if "printf %s" in cmd and "artifact.sha256" in cmd:
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

    assert uploads == []
    assert runtime["provider"] == "conda-pack"
    assert metadata["workflow_runtime"]["action"] == "registered"
    assert any("PATH=" in cmd and "workflow-env/bin/snakemake" in cmd and "--version" in cmd for cmd in executed)
    assert sum(1 for cmd in executed if "workflow-env/bin/snakemake" in cmd and "--version" in cmd) == 1
    assert not any("tar -xzf" in cmd for cmd in executed)


def test_rotate_token_does_not_persist_local_token_before_remote_update_succeeds(monkeypatch) -> None:
    manager = RemoteRunnerManager()

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            raise RuntimeError("boom")

        def upload(self, local: str, remote: str) -> None:
            raise RuntimeError("upload failed")

    fake_ssh = FakeSSH()

    with patch("core.remote_runner.manager.store_runner_token") as store_token:
        try:
            manager.rotate_token(
                server_id="srv_test",
                server={},
                ssh_service=fake_ssh,
                server_record={
                    "bootstrap_version": "0.1.0-control-plane",
                    "runner_mode": "background_process",
                    "service_port": 43127,
                },
            )
        except Exception as exc:
            assert "upload failed" in str(exc)
        else:
            raise AssertionError("rotate_token should fail when remote update fails")

    store_token.assert_not_called()


def test_remote_runner_upload_persists_file_and_metadata(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "token": "phase2-token",
                "data_root": str(tmp_path / "shared"),
                "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
                "uploads_dir": str(tmp_path / "shared" / "uploads"),
                "results_dir": str(tmp_path / "shared" / "results"),
                "work_dir": str(tmp_path / "shared" / "work"),
                "logs_dir": str(tmp_path / "shared" / "logs"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    ensure_runtime_layout(load_remote_runner_config())

    payload = UploadCreateRequest(
        filename="reads.fastq",
        contentBase64="QEdPQgo=",
        mimeType="text/plain",
    )
    response = asyncio.run(create_upload(payload, authorization="Bearer phase2-token"))

    assert response["data"]["uploadId"].startswith("upl_")
    assert response["data"]["sha256"]
    assert Path(response["data"]["path"]).exists()


def test_remote_runner_pipeline_api_lists_registered_pipelines(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "token": "phase2-token",
                "data_root": str(tmp_path / "shared"),
                "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
                "uploads_dir": str(tmp_path / "shared" / "uploads"),
                "results_dir": str(tmp_path / "shared" / "results"),
                "work_dir": str(tmp_path / "shared" / "work"),
                "logs_dir": str(tmp_path / "shared" / "logs"),
                "release_dir": str(tmp_path / "release"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    _write_file_summary_pipeline(tmp_path / "release")

    items = asyncio.run(get_pipelines(authorization="Bearer phase2-token"))["data"]["items"]
    detail = asyncio.run(get_pipeline_api("file-summary-v1", authorization="Bearer phase2-token"))["data"]

    assert items[0]["pipelineId"] == "file-summary-v1"
    assert items[0]["category"] == "Sequence Utilities"
    assert items[0]["status"] == "installed"
    assert items[0]["enabled"] is True
    assert detail["pipelineId"] == "file-summary-v1"
    assert detail["paramsSchema"]["type"] == "object"
    assert detail["uiSchema"]["inputs"]["widget"] == "file-upload"


def test_remote_runner_create_run_rejects_unknown_pipeline(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "token": "phase2-token",
                "data_root": str(tmp_path / "shared"),
                "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
                "uploads_dir": str(tmp_path / "shared" / "uploads"),
                "results_dir": str(tmp_path / "shared" / "results"),
                "work_dir": str(tmp_path / "shared" / "work"),
                "logs_dir": str(tmp_path / "shared" / "logs"),
                "release_dir": str(tmp_path / "release"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    _write_file_summary_pipeline(tmp_path / "release")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            create_run(
                RunCreateRequest(
                    serverId="srv_demo",
                    requestId="req_unknown_pipeline",
                    runSpec={"projectId": "proj_demo", "pipelineId": "unknown-v1", "inputs": []},
                ),
                authorization="Bearer phase2-token",
                idempotency_key="idem-unknown-pipeline",
                x_request_id="req_unknown_pipeline",
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "PIPELINE_NOT_FOUND"


def test_remote_runner_create_run_rejects_invalid_pipeline_params(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "token": "phase2-token",
                "data_root": str(tmp_path / "shared"),
                "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
                "uploads_dir": str(tmp_path / "shared" / "uploads"),
                "results_dir": str(tmp_path / "shared" / "results"),
                "work_dir": str(tmp_path / "shared" / "work"),
                "logs_dir": str(tmp_path / "shared" / "logs"),
                "release_dir": str(tmp_path / "release"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    _write_file_summary_pipeline(tmp_path / "release")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            create_run(
                RunCreateRequest(
                    serverId="srv_demo",
                    requestId="req_bad_params",
                    runSpec={
                        "projectId": "proj_demo",
                        "pipelineId": "file-summary-v1",
                        "inputs": [{"uploadId": "upl_demo"}],
                        "params": {"threads": 0},
                    },
                ),
                authorization="Bearer phase2-token",
                idempotency_key="idem-bad-params",
                x_request_id="req_bad_params",
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "PARAM_SCHEMA_INVALID"


def test_remote_runner_run_lifecycle_produces_events_logs_and_results(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "token": "phase2-token",
                "data_root": str(tmp_path / "shared"),
                "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
                "uploads_dir": str(tmp_path / "shared" / "uploads"),
                "results_dir": str(tmp_path / "shared" / "results"),
                "work_dir": str(tmp_path / "shared" / "work"),
                "logs_dir": str(tmp_path / "shared" / "logs"),
                "release_dir": str(tmp_path / "release"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    ensure_runtime_layout(load_remote_runner_config())
    _write_file_summary_pipeline(tmp_path / "release")
    monkeypatch.setattr("apps.remote_runner.main.start_run_execution", lambda cfg, run_id, request_id, run_spec: None)

    submit = asyncio.run(
        create_run(
            RunCreateRequest(
                serverId="srv_demo",
                requestId="req_phase2",
                runSpec={"projectId": "proj_demo", "pipelineId": "file-summary-v1", "inputs": []},
            ),
            authorization="Bearer phase2-token",
            idempotency_key="idem-phase2",
            x_request_id="req_phase2",
        )
    )
    run_id = submit["data"]["runId"]

    cfg = load_remote_runner_config()
    result_dir = Path(cfg.results_dir) / run_id
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "run-report.html").write_text("<h1>done</h1>", encoding="utf-8")
    (result_dir / "summary.tsv").write_text("sample\tabundance\ttaxonomy\nsample_alpha\t0.42\tBacteroides\n", encoding="utf-8")
    (result_dir / "raw-log.txt").write_text("done\n", encoding="utf-8")
    from apps.remote_runner.storage import append_log_lines, persist_artifact, update_run_state
    append_log_lines(cfg, run_id, "stdout", ["snakemake completed"])
    persist_artifact(cfg, run_id=run_id, kind="report", path=result_dir / "run-report.html", mime_type="text/html")
    persist_artifact(cfg, run_id=run_id, kind="table", path=result_dir / "summary.tsv", mime_type="text/tab-separated-values")
    persist_artifact(cfg, run_id=run_id, kind="log", path=result_dir / "raw-log.txt", mime_type="text/plain")
    update_run_state(
        cfg,
        run_id=run_id,
        status="completed",
        stage="finalize",
        message="Execution completed.",
        request_id="req_phase2",
        result_dir=str(result_dir),
    )

    final_run = None
    for _ in range(40):
        current = asyncio.run(get_run_api(run_id, authorization="Bearer phase2-token"))["data"]
        if current["status"] in {"completed", "failed"}:
            final_run = current
            break
        asyncio.run(asyncio.sleep(0.05))

    assert final_run is not None
    assert final_run["status"] == "completed"

    runs = asyncio.run(list_runs_api(authorization="Bearer phase2-token"))["data"]["items"]
    assert any(item["runId"] == run_id for item in runs)

    events = asyncio.run(get_run_events_api(run_id, authorization="Bearer phase2-token"))["data"]["items"]
    assert len(events) >= 2

    logs = asyncio.run(get_run_logs_api(run_id, authorization="Bearer phase2-token"))["data"]
    assert any("completed" in line for line in logs["lines"])

    results = asyncio.run(get_run_results_api(run_id, authorization="Bearer phase2-token"))["data"]
    assert results["artifacts"]

    result_list = asyncio.run(list_results_api(authorization="Bearer phase2-token"))["data"]["items"]
    result_id = next(item["resultId"] for item in result_list if item["runId"] == run_id)
    result_detail = asyncio.run(get_result_api(result_id, authorization="Bearer phase2-token"))["data"]
    assert result_detail["artifactCount"] >= 1

    preview = asyncio.run(get_result_preview_api(result_id, authorization="Bearer phase2-token"))["data"]
    assert preview["artifactId"]


def test_executor_invokes_snakemake_cli_with_use_conda(tmp_path: Path, monkeypatch) -> None:
    snakemake_command = tmp_path / "tooling" / "workflow-env" / "bin" / "snakemake"
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        snakemake_command=str(snakemake_command),
    )
    ensure_runtime_layout(cfg)
    snakemake_command.parent.mkdir(parents=True, exist_ok=True)
    snakemake_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    _write_file_summary_pipeline(Path(cfg.release_dir))

    calls: list[list[str]] = []

    class Result:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "ok"
            self.stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", fake_run)
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda cfg, run_id, result_dir: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    from apps.remote_runner.storage import persist_upload

    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHJlYWQxCkFDR1QKKwohISEhCg==",
        mime_type="text/plain",
    )

    run_snakemake_execution(
        cfg,
        run_id="run_phase2",
        request_id="req_phase2",
        run_spec={
            "pipelineId": "file-summary-v1",
            "projectId": "proj_demo",
            "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.fastq", "role": "reads"}],
        },
    )

    assert len(calls) == 2
    assert calls[0][0] == str(snakemake_command)
    assert "--use-conda" in calls[0]
    assert "-n" in calls[0]
    assert "--use-conda" in calls[1]
    run_config = json.loads((Path(cfg.work_dir) / "run_phase2" / "run-config.json").read_text(encoding="utf-8"))
    assert run_config["pipeline_id"] == "file-summary-v1"
    assert run_config["inputs"][0]["path"] == upload["path"]
    assert run_config["inputs"][0]["sha256"] == upload["sha256"]


def test_executor_fails_when_upload_input_is_missing(tmp_path: Path, monkeypatch) -> None:
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        snakemake_command=str(tmp_path / "snakemake"),
    )
    ensure_runtime_layout(cfg)
    _write_file_summary_pipeline(Path(cfg.release_dir))
    from apps.remote_runner.storage import create_run_record, fetch_run

    create_run_record(
        cfg,
        server_id="srv_demo",
        request_id="req_missing_input",
        run_spec={
            "runId": "run_missing_input",
            "projectId": "proj_demo",
            "pipelineId": "file-summary-v1",
            "inputs": [{"uploadId": "upl_missing", "filename": "missing.fastq", "role": "reads"}],
        },
        idempotency_key="idem_missing_input",
        payload_hash="h" * 64,
    )

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", lambda *args, **kwargs: None)
    run_snakemake_execution(
        cfg,
        run_id="run_missing_input",
        request_id="req_missing_input",
        run_spec={
            "projectId": "proj_demo",
            "pipelineId": "file-summary-v1",
            "inputs": [{"uploadId": "upl_missing", "filename": "missing.fastq", "role": "reads"}],
        },
    )

    run = fetch_run(cfg, "run_missing_input")
    assert run["status"] == "failed"
    assert run["stage"] == "validate"
    assert run["lastError"]["code"] == "INPUT_NOT_FOUND"


def test_executor_exports_managed_conda_runtime_when_configured(tmp_path: Path, monkeypatch) -> None:
    managed_conda_command = tmp_path / "tooling" / "bin" / "micromamba"
    managed_conda_root_prefix = tmp_path / "tooling" / "micromamba-root"
    snakemake_command = tmp_path / "tooling" / "workflow-env" / "bin" / "snakemake"
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        managed_conda_command=str(managed_conda_command),
        managed_conda_root_prefix=str(managed_conda_root_prefix),
        snakemake_command=str(snakemake_command),
    )
    ensure_runtime_layout(cfg)
    managed_conda_command.parent.mkdir(parents=True, exist_ok=True)
    managed_conda_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    snakemake_command.parent.mkdir(parents=True, exist_ok=True)
    snakemake_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    _write_file_summary_pipeline(Path(cfg.release_dir))

    calls: list[dict[str, object]] = []

    class Result:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "ok"
            self.stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, "env": kwargs.get("env")})
        return Result()

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", fake_run)
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda cfg, run_id, result_dir: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    from apps.remote_runner.storage import persist_upload

    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHJlYWQxCkFDR1QKKwohISEhCg==",
        mime_type="text/plain",
    )

    run_snakemake_execution(
        cfg,
        run_id="run_phase2_managed_conda",
        request_id="req_phase2_managed_conda",
        run_spec={
            "pipelineId": "file-summary-v1",
            "projectId": "proj_demo",
            "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.fastq", "role": "reads"}],
        },
    )

    assert len(calls) == 2
    for call in calls:
        env = call["env"]
        assert isinstance(env, dict)
        assert env["H2OMETA_MANAGED_CONDA_COMMAND"] == str(managed_conda_command)
        assert env["MAMBA_ROOT_PREFIX"] == str(managed_conda_root_prefix)
        path_entries = env["PATH"].split(os.pathsep)
        assert path_entries[0] == str(snakemake_command.parent)
        assert path_entries[1] == str(managed_conda_command.parent)


def test_remote_runner_upload_rejects_oversized_payload(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "token": "phase2-token",
                "data_root": str(tmp_path / "shared"),
                "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
                "uploads_dir": str(tmp_path / "shared" / "uploads"),
                "results_dir": str(tmp_path / "shared" / "results"),
                "work_dir": str(tmp_path / "shared" / "work"),
                "logs_dir": str(tmp_path / "shared" / "logs"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    monkeypatch.setattr("apps.remote_runner.storage.MAX_UPLOAD_BYTES", 8)
    payload = UploadCreateRequest(
        filename="reads.fastq",
        contentBase64="QUJDREVGR0hJSg==",
        mimeType="text/plain",
    )

    try:
        asyncio.run(create_upload(payload, authorization="Bearer phase2-token"))
    except HTTPException as exc:
        assert exc.status_code == 413
        assert exc.detail == "UPLOAD_TOO_LARGE"
    else:
        raise AssertionError("oversized upload should be rejected")


def test_result_preview_truncates_large_text_payload(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "token": "phase2-token",
                "data_root": str(tmp_path / "shared"),
                "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
                "uploads_dir": str(tmp_path / "shared" / "uploads"),
                "results_dir": str(tmp_path / "shared" / "results"),
                "work_dir": str(tmp_path / "shared" / "work"),
                "logs_dir": str(tmp_path / "shared" / "logs"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    ensure_runtime_layout(load_remote_runner_config())

    cfg = load_remote_runner_config()
    run_id = "run_preview_large"
    result_dir = Path(cfg.results_dir) / run_id
    result_dir.mkdir(parents=True, exist_ok=True)
    large_text = "x" * (300 * 1024)
    artifact_path = result_dir / "raw-log.txt"
    artifact_path.write_text(large_text, encoding="utf-8")

    from apps.remote_runner.storage import (
        fetch_result,
        get_connection,
        persist_artifact,
        update_run_state,
    )

    with get_connection(cfg) as connection:
        connection.execute(
            """
            INSERT INTO runs (
                run_id, server_id, project_id, pipeline_id, pipeline_version, run_spec_version,
                status, stage, state_version, message, started_at, finished_at, result_dir,
                last_error_json, last_updated_at, request_id, submitted_at, run_spec_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "srv_demo",
                "proj_demo",
                "taxonomy-v1",
                "0.1.0",
                "2026-04-21",
                "running",
                "submitted",
                1,
                "Run accepted",
                None,
                None,
                "",
                None,
                "2026-04-21T12:00:00Z",
                "req_preview_large",
                "2026-04-21T12:00:00Z",
                "{}",
            ),
        )
        connection.commit()

    update_run_state(
        cfg,
        run_id=run_id,
        status="completed",
        stage="finalize",
        message="done",
        request_id="req_preview_large",
        result_dir=str(result_dir),
    )
    artifact = persist_artifact(
        cfg,
        run_id=run_id,
        kind="log",
        path=artifact_path,
        mime_type="text/plain",
    )
    result_id = fetch_result(cfg, f"res_{run_id}")["resultId"]

    preview = asyncio.run(
        get_result_preview_api(
            result_id,
            artifact_id=artifact["artifactId"],
            authorization="Bearer phase2-token",
        )
    )["data"]["preview"]

    assert preview["kind"] == "text"
    assert preview["truncated"] is True
    assert len(preview["content"]) <= 256 * 1024


def test_manager_wraps_tunnel_setup_failures(monkeypatch) -> None:
    manager = RemoteRunnerManager()

    class FakeSSH:
        def ensure_local_tunnel(self, *args, **kwargs):
            raise RuntimeError("SSH transport is not active")

    monkeypatch.setattr("core.remote_runner.manager.resolve_runner_token", lambda _ref: "phase2-token")

    try:
        manager.list_results(
            server_id="srv_demo",
            ssh_service=FakeSSH(),
            server_record={"token_ref": "runner://srv_demo", "service_port": 43127},
        )
    except RemoteRunnerManagerError as exc:
        assert "SSH transport is not active" in str(exc)
    else:
        raise AssertionError("tunnel setup errors should be normalized")


def test_manager_fails_loudly_when_service_port_is_missing(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    monkeypatch.setattr("core.remote_runner.manager.resolve_runner_token", lambda _ref: "phase2-token")

    try:
        manager.list_results(
            server_id="srv_demo",
            ssh_service=SimpleNamespace(),
            server_record={"token_ref": "runner://srv_demo"},
        )
    except RemoteRunnerManagerError as exc:
        assert "service_port is missing" in str(exc)
    else:
        raise AssertionError("missing service_port should fail instead of falling back to a fixed port")


def test_bootstrap_does_not_persist_local_token_before_remote_service_is_healthy(monkeypatch) -> None:
    manager = RemoteRunnerManager()

    class FakeBundle:
        archive_path = Path(__file__)

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if 'printf "%s:%s" "$(uname -s)" "$(uname -m)"' in cmd:
                return 0, "Linux:x86_64", ""
            if "systemctl --user show-environment" in cmd:
                return 0, "background_process\n", ""
            if "mkdir -p" in cmd:
                return 0, "", ""
            if "pkill -f '[r]emote_runner.run'" in cmd and "runner-state.json" in cmd:
                return 0, "", ""
            if "tar -xzf" in cmd:
                return 0, "", ""
            if "runtime/bin/python -c \"from remote_runner.config import load_remote_runner_config, ensure_runtime_layout; ensure_runtime_layout(load_remote_runner_config())\"" in cmd:
                return 0, "", ""
            if "bash /home/tester/.h2ometa/runner/current/start_service.sh" in cmd:
                raise RuntimeError("service failed to start")
            return 0, "", ""

        def upload(self, local: str, remote: str) -> None:
            return None

    fake_ssh = FakeSSH()

    with patch.object(manager, "_artifact_provider", SimpleNamespace(resolve=lambda **kwargs: FakeBundle())), patch(
        "core.remote_runner.manager.store_runner_token"
    ) as store_token:
        try:
            manager.bootstrap(
                server_id="srv_test",
                server={"label": "demo"},
                ssh_service=fake_ssh,
                server_record={},
            )
        except Exception as exc:
            assert "service failed to start" in str(exc)
        else:
            raise AssertionError("bootstrap should fail when service startup fails")

    store_token.assert_not_called()


def test_bootstrap_fails_fast_when_bundled_runtime_initialization_returns_nonzero(monkeypatch) -> None:
    manager = RemoteRunnerManager()

    class FakeBundle:
        archive_path = Path(__file__)

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if 'printf "%s:%s" "$(uname -s)" "$(uname -m)"' in cmd:
                return 0, "Linux:x86_64", ""
            if "systemctl --user show-environment" in cmd:
                return 0, "background_process\n", ""
            if "mkdir -p" in cmd:
                return 0, "", ""
            if "pkill -f '[r]emote_runner.run'" in cmd and "runner-state.json" in cmd:
                return 0, "", ""
            if "tar -xzf" in cmd:
                return 0, "", ""
            if "runtime/bin/python -c \"from remote_runner.config import load_remote_runner_config, ensure_runtime_layout; ensure_runtime_layout(load_remote_runner_config())\"" in cmd:
                return 1, "", "bundled runtime failed"
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            return None

    fake_ssh = FakeSSH()

    with patch.object(manager, "_artifact_provider", SimpleNamespace(resolve=lambda **kwargs: FakeBundle())), patch(
        "core.remote_runner.manager.store_runner_token"
    ) as store_token:
        try:
            manager.bootstrap(
                server_id="srv_test",
                server={"label": "demo"},
                ssh_service=fake_ssh,
                server_record={},
            )
        except RemoteRunnerManagerError as exc:
            assert "bundled runtime failed" in str(exc)
            assert "initialize remote runner layout" in str(exc)
        else:
            raise AssertionError("bootstrap should fail when bundled runtime initialization exits non-zero")

    store_token.assert_not_called()


def test_bootstrap_uses_bundled_service_runtime_without_remote_installer(monkeypatch) -> None:
    manager = RemoteRunnerManager()

    class FakeBundle:
        archive_path = Path(__file__)

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if 'printf "%s:%s" "$(uname -s)" "$(uname -m)"' in cmd:
                return 0, "Linux:x86_64", ""
            if "systemctl --user show-environment" in cmd:
                return 0, "background_process\n", ""
            if "mkdir -p" in cmd:
                return 0, "", ""
            if "tar -xzf" in cmd:
                return 0, "", ""
            if "runtime/bin/python -c \"from remote_runner.config import load_remote_runner_config, ensure_runtime_layout; ensure_runtime_layout(load_remote_runner_config())\"" in cmd:
                return 0, "", ""
            if "rm -f /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, "", ""
            if "bash /home/tester/.h2ometa/runner/current/start_service.sh" in cmd:
                return 0, "", ""
            if "cat /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, _runtime_state_json(), ""
            if "kill -0 123" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            return None

        def ensure_local_tunnel(self, *args, **kwargs):
            assert kwargs["remote_port"] == 43127
            return SimpleNamespace(local_port=18765)

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def get_health(self) -> dict[str, object]:
            return {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-04-22T00:00:00Z",
            }

    fake_ssh = FakeSSH()
    with patch.object(manager, "_artifact_provider", SimpleNamespace(resolve=lambda **kwargs: FakeBundle())), patch(
        "core.remote_runner.manager.RemoteRunnerHttpClient", FakeClient
    ), patch(
        "core.remote_runner.manager.store_runner_token", lambda **kwargs: "runner://srv_test"
    ):
        result = manager.bootstrap(
            server_id="srv_test",
            server={"label": "demo"},
            ssh_service=fake_ssh,
            server_record={},
        )

    tooling = result["bootstrap_metadata"]["tooling"]
    assert tooling["workflow_runtime"]["provider"] == "conda-pack"
    assert tooling["workflow_runtime"]["source"] == "artifact"
    assert tooling["service_runtime"]["provider"] == "bundled"
    assert tooling["service_runtime"]["source"] == "artifact"


def test_bootstrap_does_not_install_runtime_on_remote_host(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    executed: list[str] = []

    class FakeBundle:
        archive_path = Path(__file__)

    class FakeTunnel:
        local_port = 18765

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            executed.append(cmd)
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if 'printf "%s:%s" "$(uname -s)" "$(uname -m)"' in cmd:
                return 0, "Linux:x86_64", ""
            if "systemctl --user show-environment" in cmd:
                return 0, "background_process\n", ""
            if "mkdir -p" in cmd:
                return 0, "", ""
            if "tar -xzf" in cmd:
                return 0, "", ""
            if "runtime/bin/python -c \"from remote_runner.config import load_remote_runner_config, ensure_runtime_layout; ensure_runtime_layout(load_remote_runner_config())\"" in cmd:
                return 0, "", ""
            if "rm -f /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, "", ""
            if "bash /home/tester/.h2ometa/runner/current/start_service.sh" in cmd:
                return 0, "", ""
            if "cat /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, _runtime_state_json(), ""
            if "kill -0 123" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            return None

        def ensure_local_tunnel(self, *args, **kwargs):
            assert kwargs["remote_port"] == 43127
            return FakeTunnel()

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def get_health(self) -> dict[str, object]:
            return {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-04-22T00:00:00Z",
            }

    with patch.object(manager, "_artifact_provider", SimpleNamespace(resolve=lambda **kwargs: FakeBundle())), patch(
        "core.remote_runner.manager.RemoteRunnerHttpClient", FakeClient
    ), patch(
        "core.remote_runner.manager.store_runner_token", lambda **kwargs: "runner://srv_test"
    ):
        result = manager.bootstrap(
            server_id="srv_test",
            server={"label": "demo"},
            ssh_service=FakeSSH(),
            server_record={},
        )

    metadata = result["bootstrap_metadata"]
    assert metadata["tooling"]["workflow_runtime"]["provider"] == "conda-pack"
    assert metadata["tooling"]["workflow_runtime"]["source"] == "artifact"
    assert metadata["tooling"]["service_runtime"]["provider"] == "bundled"
    assert metadata["tooling"]["service_runtime"]["source"] == "artifact"
    assert metadata["tooling"]["service_runtime"]["python"] == "/home/tester/.h2ometa/runner/releases/0.1.0-control-plane/runtime/bin/python"
    assert metadata["tooling"]["service_runtime"]["platform"] == "linux-64"
    assert not any("micromamba" in cmd for cmd in executed)
    assert not any("service-env" in cmd for cmd in executed)
    assert not any("pip install" in cmd for cmd in executed)
    assert not any("python3 -m venv" in cmd for cmd in executed)


def test_bootstrap_waits_for_remote_runner_health_after_startup(monkeypatch) -> None:
    manager = RemoteRunnerManager()

    class FakeBundle:
        archive_path = Path(__file__)

    class FakeTunnel:
        local_port = 18765

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if 'printf "%s:%s" "$(uname -s)" "$(uname -m)"' in cmd:
                return 0, "Linux:x86_64", ""
            if "systemctl --user show-environment" in cmd:
                return 0, "systemd_user\n", ""
            if "mkdir -p" in cmd:
                return 0, "", ""
            if "tar -xzf" in cmd:
                return 0, "", ""
            if "runtime/bin/python -c \"from remote_runner.config import load_remote_runner_config, ensure_runtime_layout; ensure_runtime_layout(load_remote_runner_config())\"" in cmd:
                return 0, "", ""
            if "rm -f /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, "", ""
            if "systemctl --user restart h2ometa-remote.service" in cmd:
                return 0, "", ""
            if "cat /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, _runtime_state_json(), ""
            if "kill -0 123" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            return None

        def ensure_local_tunnel(self, *args, **kwargs):
            assert kwargs["remote_port"] == 43127
            return FakeTunnel()

    health_calls = {"count": 0}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def get_health(self) -> dict[str, object]:
            health_calls["count"] += 1
            if health_calls["count"] < 3:
                raise RemoteRunnerClientError("runner unreachable")
            return {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-04-22T00:00:00Z",
            }

    monkeypatch.setattr("core.remote_runner.manager.time.sleep", lambda *_args, **_kwargs: None)

    with patch.object(manager, "_artifact_provider", SimpleNamespace(resolve=lambda **kwargs: FakeBundle())), patch(
        "core.remote_runner.manager.RemoteRunnerHttpClient", FakeClient
    ), patch(
        "core.remote_runner.manager.store_runner_token", lambda **kwargs: "runner://srv_test"
    ):
        result = manager.bootstrap(
            server_id="srv_test",
            server={"label": "demo"},
            ssh_service=FakeSSH(),
            server_record={},
        )

    assert health_calls["count"] == 3
    assert result["health"]["ready"]["ok"] is True


def test_bootstrap_does_not_require_system_python3_for_bundled_runtime(monkeypatch) -> None:
    manager = RemoteRunnerManager()

    class FakeBundle:
        archive_path = Path(__file__)

    class FakeTunnel:
        local_port = 18765

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if 'printf "%s:%s" "$(uname -s)" "$(uname -m)"' in cmd:
                return 0, "Linux:x86_64", ""
            if "systemctl --user show-environment" in cmd:
                return 0, "background_process\n", ""
            if "mkdir -p" in cmd:
                return 0, "", ""
            if "tar -xzf" in cmd:
                return 0, "", ""
            if "runtime/bin/python -c \"from remote_runner.config import load_remote_runner_config, ensure_runtime_layout; ensure_runtime_layout(load_remote_runner_config())\"" in cmd:
                return 0, "", ""
            if "rm -f /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, "", ""
            if "bash /home/tester/.h2ometa/runner/current/start_service.sh" in cmd:
                return 0, "", ""
            if "cat /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, _runtime_state_json(), ""
            if "kill -0 123" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            return None

        def ensure_local_tunnel(self, *args, **kwargs):
            return FakeTunnel()

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def get_health(self) -> dict[str, object]:
            return {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-04-22T00:00:00Z",
            }

    with patch.object(manager, "_artifact_provider", SimpleNamespace(resolve=lambda **kwargs: FakeBundle())), patch(
        "core.remote_runner.manager.RemoteRunnerHttpClient", FakeClient
    ), patch("core.remote_runner.manager.store_runner_token", lambda **kwargs: "runner://srv_test"):
        result = manager.bootstrap(
            server_id="srv_test",
            server={"label": "demo"},
            ssh_service=FakeSSH(),
            server_record={},
        )

    assert result["bootstrap_metadata"]["tooling"]["service_runtime"]["provider"] == "bundled"
