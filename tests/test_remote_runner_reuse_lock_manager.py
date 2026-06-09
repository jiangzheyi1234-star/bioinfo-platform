from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.remote_runner.config import (
    ensure_runtime_layout,
    get_runtime_state_path,
    inspect_workflow_runtime,
    load_remote_runner_config,
    write_runtime_state,
)
from apps.remote_runner.config import RemoteRunnerConfig
from apps.remote_runner.executor import run_snakemake_execution
from apps.remote_runner.api_models import RunCreateRequest, UploadCreateRequest
from apps.remote_runner.execution_query_routes import (
    get_result_api,
    get_result_preview_api,
    get_run as get_run_api,
    get_run_events_api,
    get_run_logs_api,
    get_run_results_api,
    get_runs as list_runs_api,
    list_results_api,
)
from apps.remote_runner.health_routes import health_live, health_ready, health_startup
from apps.remote_runner.pipeline_routes import get_pipeline_api, get_pipelines
from apps.remote_runner.submission_routes import create_run, create_upload
from config import get_app_cache_dir
from core.remote_runner.artifact import RemoteRunnerArtifactError
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION, RemoteRunnerBundleBuilder
from core.remote_runner.client import RemoteRunnerClientError
from core.remote_runner.manager import RemoteRunnerManager, RemoteRunnerManagerError
from tests.helpers.remote_runner_control_plane import (
    _ORIGINAL_ENSURE_WORKFLOW_RUNTIME,
    _default_workflow_runtime,
    _fake_runtime_dir,
    _is_remote_bundle_cleanup,
    _is_remote_config_atomic_move,
    _fake_workflow_artifact,
    _runtime_state_json,
    _write_file_summary_pipeline,
)

def test_wait_for_runtime_state_rejects_dead_runner_pid() -> None:
    manager = RemoteRunnerManager()

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if "cat /remote/runner-state.json" in cmd:
                return 0, _runtime_state_json(), ""
            if "kill -0 123" in cmd:
                return 1, "", "No such process"
            if _is_remote_bundle_cleanup(cmd) or _is_remote_config_atomic_move(cmd):
                return 0, "", ""
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

def test_bootstrap_reuses_existing_runner_when_artifact_sha_matches(monkeypatch) -> None:
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
                return 0, "systemd_user\n", ""
            if "readlink -f /home/tester/.h2ometa/runner/current" in cmd:
                return 0, f"/home/tester/.h2ometa/runner/releases/{REMOTE_RUNNER_VERSION}\n", ""
            if "bootstrap_manifest.json" in cmd:
                return 0, json.dumps(
                    {
                        "service": "h2ometa-remote",
                        "version": REMOTE_RUNNER_VERSION,
                        "platform": "linux-64",
                        "runtime": {"provider": "bundled", "python": "runtime/bin/python"},
                    }
                ), ""
            if "cat /home/tester/.h2ometa/runner/releases/" in cmd and "artifact.sha256" in cmd:
                return 0, "b" * 64, ""
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
                        "snakemake_version": "9.19.0",
                    }
                ), ""
            if "workflow-env/bin/snakemake" in cmd and "--version" in cmd:
                return 0, "9.19.0\n", ""
            if _is_remote_bundle_cleanup(cmd) or _is_remote_config_atomic_move(cmd):
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

        def get_json(self, path: str) -> dict[str, object]:
            assert path == "/api/v1/database-templates"
            return {
                "data": {
                    "items": [
                        {
                            "id": "kraken2",
                            "category": "taxonomy",
                            "pathKind": "directory",
                            "pathLabel": "数据库目录",
                            "runtimeValue": "目录",
                        }
                    ]
                }
            }

    with patch.object(manager, "_artifact_provider", SimpleNamespace(resolve=lambda **kwargs: FakeArtifact())), patch(
        "core.remote_runner.reuse.RemoteRunnerHttpClient", FakeClient
    ), patch("core.remote_runner.reuse.resolve_runner_token", lambda token_ref: "phase2-token"), patch(
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
                    "canary": {
                        "ok": False,
                        "status": "failed",
                        "message": "stale canary failure",
                    },
                    "rollback": {
                        "attempted": True,
                        "restored": False,
                        "status": "failed",
                        "message": "stale rollback failure",
                    },
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
    assert result["bootstrap_metadata"]["canary"] == {
        "status": "skipped",
        "message": "Existing runner reused; bootstrap canary was not rerun.",
    }
    assert result["bootstrap_metadata"]["rollback"] == {
        "attempted": False,
        "restored": False,
        "status": "skipped",
        "message": "Existing runner reused; rollback was not needed.",
    }
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
            if "cat /home/tester/.h2ometa/runner/releases/0.1.0-control-plane/artifact.sha256" in cmd:
                return 0, "b" * 64, ""
            if "cat /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, _runtime_state_json(), ""
            if "kill -0 123" in cmd:
                return 0, "", ""
            if "cat /home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256" in cmd:
                return 1, "", "No such file"
            if _is_remote_bundle_cleanup(cmd) or _is_remote_config_atomic_move(cmd):
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def ensure_local_tunnel(self, *args, **kwargs):
            raise AssertionError("workflow runtime must be verified before opening a tunnel")

    monkeypatch.setattr("core.remote_runner.reuse.resolve_runner_token", lambda token_ref: "phase2-token")
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
        remote_artifact_sha="/home/tester/.h2ometa/runner/releases/0.1.0-control-plane/artifact.sha256",
        artifact_sha="b" * 64,
        workflow_artifact=_fake_workflow_artifact(),
        workflow_runtime_dir="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64",
        remote_workflow_artifact_sha="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256",
        bootstrap_metadata=metadata,
    )

    assert result is None
    assert metadata["reuse_check"] == {"ok": False, "reason": "No such file"}

def test_fast_reuse_rejects_runner_when_remote_runner_artifact_sha_mismatches(monkeypatch) -> None:
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
            if "cat /home/tester/.h2ometa/runner/releases/0.1.0-control-plane/artifact.sha256" in cmd:
                return 0, "a" * 64, ""
            raise AssertionError(f"unexpected command: {cmd}")

        def ensure_local_tunnel(self, *args, **kwargs):
            raise AssertionError("artifact sha must be verified before opening a tunnel")

    monkeypatch.setattr("core.remote_runner.reuse.resolve_runner_token", lambda token_ref: "phase2-token")
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
        remote_artifact_sha="/home/tester/.h2ometa/runner/releases/0.1.0-control-plane/artifact.sha256",
        artifact_sha="b" * 64,
        workflow_artifact=_fake_workflow_artifact(),
        workflow_runtime_dir="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64",
        remote_workflow_artifact_sha="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256",
        bootstrap_metadata=metadata,
    )

    assert result is None
    assert metadata["reuse_check"] == {"ok": False, "reason": "artifact sha mismatch"}

def test_fast_reuse_does_not_mask_unexpected_ssh_errors(monkeypatch) -> None:
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
            raise RuntimeError("ssh adapter crashed while reading manifest")

    monkeypatch.setattr("core.remote_runner.reuse.resolve_runner_token", lambda token_ref: "phase2-token")
    with pytest.raises(RuntimeError, match="ssh adapter crashed while reading manifest"):
        manager._try_reuse_existing_runner_fast(
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
            remote_artifact_sha="/home/tester/.h2ometa/runner/releases/0.1.0-control-plane/artifact.sha256",
            artifact_sha="b" * 64,
            workflow_artifact=_fake_workflow_artifact(),
            workflow_runtime_dir="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64",
            remote_workflow_artifact_sha="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256",
            bootstrap_metadata=metadata,
        )


def test_reuse_does_not_mask_unexpected_ssh_errors(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    metadata: dict[str, object] = {}

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if "readlink -f /home/tester/.h2ometa/runner/current" in cmd:
                return 0, "/home/tester/.h2ometa/runner/releases/0.1.0-control-plane\n", ""
            raise RuntimeError("ssh adapter crashed while reading manifest")

    monkeypatch.setattr("core.remote_runner.reuse.resolve_runner_token", lambda token_ref: "phase2-token")
    with pytest.raises(RuntimeError, match="ssh adapter crashed while reading manifest"):
        manager._try_reuse_existing_runner(
            server_id="srv_test",
            ssh_service=FakeSSH(),
            server_record={
                "runner_mode": "systemd_user",
                "token_ref": "runner://srv_test",
            },
            version=REMOTE_RUNNER_VERSION,
            mode="systemd_user",
            remote_platform="linux-64",
            remote_release="/home/tester/.h2ometa/runner/releases/0.1.0-control-plane",
            remote_current="/home/tester/.h2ometa/runner/current",
            remote_runtime_state="/home/tester/.h2ometa/runner/shared/runtime/runner-state.json",
            remote_artifact_sha="/home/tester/.h2ometa/runner/releases/0.1.0-control-plane/artifact.sha256",
            artifact_sha="b" * 64,
            remote_config="/home/tester/.h2ometa/runner/shared/config/runner.json",
            workflow_artifact=_fake_workflow_artifact(),
            workflow_runtime_dir="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64",
            remote_workflow_artifact_sha="/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256",
            bootstrap_metadata=metadata,
        )

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
            if "cat /home/tester/.h2ometa/runner/releases/0.1.0-control-plane/artifact.sha256" in cmd:
                return 0, "b" * 64, ""
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
                        "snakemake_version": "9.19.0",
                    }
                ), ""
            if "PATH=" in cmd and "import snakemake" in cmd:
                return 0, "9.19.0\n", ""
            if _is_remote_bundle_cleanup(cmd) or _is_remote_config_atomic_move(cmd):
                return 0, "", ""
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

    monkeypatch.setattr("core.remote_runner.reuse.resolve_runner_token", lambda token_ref: "phase2-token")
    monkeypatch.setattr("core.remote_runner.reuse.RemoteRunnerHttpClient", FakeClient)
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
        remote_artifact_sha="/home/tester/.h2ometa/runner/releases/0.1.0-control-plane/artifact.sha256",
        artifact_sha="b" * 64,
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
            if "H2OMETA_RECLAIM_LOCK" in cmd:
                return 0, "young", ""
            return 0, "acquired", ""

    monkeypatch.setattr("core.remote_runner.install_lock.time.sleep", lambda seconds: sleeps.append(seconds))
    metadata: dict[str, object] = {}

    manager._acquire_remote_install_lock(
        ssh_service=FakeSSH(),
        lock_dir="/home/tester/.h2ometa/runner/locks/install-test.lock",
        remote_root="/home/tester/.h2ometa/runner",
        bootstrap_metadata=metadata,
        attempts=2,
        delay_seconds=0.25,
    )

    assert len(calls) == 4
    assert calls[0].startswith("mkdir -p")
    assert "H2OMETA_RECLAIM_LOCK" in calls[1]
    assert calls[2].startswith("mkdir -p")
    assert calls[3].endswith("/owner.json")
    assert sleeps == [0.25]
    assert metadata["install_lock"] == {
        "path": "/home/tester/.h2ometa/runner/locks/install-test.lock",
        "acquired": True,
        "waited": True,
        "last_reclaim_status": "young",
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

def test_rotate_token_does_not_persist_local_token_before_remote_update_succeeds(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    uploads: list[tuple[str, str]] = []

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            raise RuntimeError("boom")

        def download(self, remote: str, local: str) -> None:
            raise RuntimeError("download failed")

        def upload(self, local: str, remote: str) -> None:
            uploads.append((local, remote))
            raise RuntimeError("upload failed")

    fake_ssh = FakeSSH()

    with patch("core.remote_runner.token_rotation.store_runner_token") as store_token:
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
            assert "download failed" in str(exc)
        else:
            raise AssertionError("rotate_token should fail when remote update fails")

    store_token.assert_not_called()
    assert uploads == []


def test_rotate_token_does_not_restore_on_unexpected_tunnel_adapter_errors(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    uploads: list[str] = []

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if cmd.startswith("test -s ") or cmd.startswith("pkill -f ") or "start_service.sh" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def download(self, _remote: str, local: str) -> None:
            Path(local).write_text('{"token":"old"}', encoding="utf-8")

        def upload(self, local: str, _remote: str) -> None:
            uploads.append(Path(local).read_text(encoding="utf-8"))

        def ensure_local_tunnel(self, *args, **kwargs):
            raise RuntimeError("tunnel adapter crashed")

    with patch("core.remote_runner.token_rotation.store_runner_token") as store_token:
        with pytest.raises(RuntimeError, match="tunnel adapter crashed"):
            manager.rotate_token(
                server_id="srv_test",
                server={},
                ssh_service=FakeSSH(),
                server_record={
                    "bootstrap_version": "0.1.0-control-plane",
                    "runner_mode": "background_process",
                    "service_port": 43127,
                },
            )

    store_token.assert_not_called()
    assert len(uploads) == 1
    assert '"token":"old"' not in uploads[0]


def test_manager_wraps_tunnel_setup_failures(monkeypatch) -> None:
    manager = RemoteRunnerManager()

    class FakeSSH:
        def ensure_local_tunnel(self, *args, **kwargs):
            raise RuntimeError("SSH transport is not active")

    monkeypatch.setattr("core.remote_runner.proxy.resolve_runner_token", lambda _ref: "phase2-token")

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
    monkeypatch.setattr("core.remote_runner.proxy.resolve_runner_token", lambda _ref: "phase2-token")

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
