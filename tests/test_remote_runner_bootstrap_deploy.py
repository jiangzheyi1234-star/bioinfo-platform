from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


from core.remote_runner.artifact import RemoteRunnerArtifactError
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from core.remote_runner.manager import RemoteRunnerManager, RemoteRunnerManagerError
from tests.helpers.remote_runner_control_plane import (
    _ORIGINAL_ENSURE_WORKFLOW_RUNTIME,
    _default_workflow_runtime,  # noqa: F401
    _is_remote_bundle_cleanup,
    _is_remote_config_atomic_move,
    _is_remote_current_release_read,
    _is_remote_current_release_switch,
    _is_remote_runner_config_read,
    _fake_workflow_artifact,
    _runtime_state_json,
)


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
                        "snakemake_version": "9.19.0",
                    }
                ), ""
            if "workflow-env/bin/snakemake" in cmd and "--version" in cmd:
                return 0, "9.19.0\n", ""
            if _is_remote_current_release_read(cmd):
                return 1, "", "No such file"
            if _is_remote_current_release_switch(cmd):
                return 0, "", ""
            if _is_remote_runner_config_read(cmd):
                return 1, "", "No such file"
            if _is_remote_bundle_cleanup(cmd) or _is_remote_config_atomic_move(cmd):
                return 0, "", ""
            if "rm -rf" in cmd and "/locks/install-" in cmd:
                return 0, "", ""
            if "owner.json" in cmd and "printf %s" in cmd:
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
    assert f"bundle-{REMOTE_RUNNER_VERSION}.tar.gz" in extract_cmd
    assert result["service_port"] == 43127
    assert any("rm -f /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd for cmd in executed)
    assert not any("micromamba" in cmd for cmd in executed)
    assert not any("python3 -m venv" in cmd for cmd in executed)
    assert result["bootstrap_metadata"]["tooling"]["service_runtime"]["provider"] == "bundled"
    assert result["bootstrap_metadata"]["tooling"]["service_runtime"]["source"] == "artifact"


def test_bootstrap_uses_staged_artifact_version_for_release_layout(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    staged_version = "0.1.4-control-plane"
    executed: list[str] = []
    uploaded_config: dict[str, object] = {}

    class FakeArtifact:
        archive_path = Path(__file__)
        version = staged_version
        platform = "linux-64"
        sha256 = "d" * 64

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
            if "tar -xzf" in cmd and f"bundle-{staged_version}.tar.gz" in cmd:
                return 0, "", ""
            if "printf" in cmd and f"releases/{staged_version}/artifact.sha256" in cmd:
                return 0, "", ""
            if "cat /home/tester/.h2ometa/runner/shared/config/runner.json" in cmd:
                return 0, json.dumps(uploaded_config), ""
            if f"releases/{staged_version}/runtime/bin/python" in cmd and "ensure_runtime_layout" in cmd:
                return 0, "", ""
            if "rm -f /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, "", ""
            if "bash /home/tester/.h2ometa/runner/current/start_service.sh" in cmd:
                return 0, "", ""
            if "cat /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, _runtime_state_json(version=staged_version), ""
            if "kill -0 123" in cmd:
                return 0, "", ""
            if "cat /home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256" in cmd:
                return 0, "f" * 64, ""
            if "workflow-env/bin/snakemake" in cmd and "--version" in cmd:
                return 0, "9.19.0\n", ""
            if _is_remote_current_release_read(cmd):
                return 1, "", "No such file"
            if _is_remote_current_release_switch(cmd):
                assert f"releases/{staged_version}" in cmd
                return 0, "", ""
            if _is_remote_runner_config_read(cmd):
                return 1, "", "No such file"
            if _is_remote_bundle_cleanup(cmd) or _is_remote_config_atomic_move(cmd):
                return 0, "", ""
            if "rm -rf" in cmd and f"/locks/install-{staged_version}" in cmd:
                return 0, "", ""
            if "owner.json" in cmd and "printf %s" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            if remote == "/home/tester/.h2ometa/runner/shared/config/runner.json.tmp":
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

    with patch.object(manager, "_artifact_provider", SimpleNamespace(resolve=lambda **kwargs: FakeArtifact())), patch(
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

    assert result["bootstrap_version"] == staged_version
    assert uploaded_config["version"] == staged_version
    assert uploaded_config["runner_python"].endswith(f"/releases/{staged_version}/runtime/bin/python")
    assert any(f"bundle-{staged_version}.tar.gz" in cmd for cmd in executed)
    assert any(f"releases/{staged_version}" in cmd for cmd in executed)


def test_bootstrap_registers_remote_workflow_runtime_when_local_artifact_is_missing(monkeypatch) -> None:
    monkeypatch.setenv("H2OMETA_ALLOW_REMOTE_WORKFLOW_RUNTIME_REGISTRATION", "1")
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
            if "tar -xzf" in cmd and f"bundle-{REMOTE_RUNNER_VERSION}.tar.gz" in cmd:
                return 0, "", ""
            if "workflow-env/bin/snakemake" in cmd and "--version" in cmd:
                return 0, "9.19.0\n", ""
            if "printf" in cmd and "artifact.sha256" in cmd:
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
            if _is_remote_current_release_read(cmd):
                return 1, "", "No such file"
            if _is_remote_current_release_switch(cmd):
                return 0, "", ""
            if _is_remote_runner_config_read(cmd):
                return 1, "", "No such file"
            if _is_remote_bundle_cleanup(cmd) or _is_remote_config_atomic_move(cmd):
                return 0, "", ""
            if "rm -rf" in cmd and "/locks/install-" in cmd:
                return 0, "", ""
            if "owner.json" in cmd and "printf %s" in cmd:
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
    assert "/home/tester/.h2ometa/runner/shared/config/runner.json.tmp" in remote_uploads
    assert "/home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64.tar.gz" not in remote_uploads
    assert any(f"ln -sfn /home/tester/.h2ometa/runner/releases/{REMOTE_RUNNER_VERSION} /home/tester/.h2ometa/runner/current" in cmd for cmd in executed)
    assert any("printf" in cmd and "workflow-runtime-0.1.0-linux-64/artifact.sha256" in cmd for cmd in executed)
    assert result["bootstrap_metadata"]["workflow_runtime"]["action"] == "registered"
    assert result["health"]["ready"]["ok"] is True

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
            if "mkdir -p" in cmd:
                return 0, "", ""
            if "pkill -f '[r]emote_runner.run'" in cmd and "runner-state.json" in cmd:
                return 0, "", ""
            if "tar -xzf" in cmd:
                return 0, "", ""
            if "printf" in cmd and "artifact.sha256" in cmd:
                return 0, "", ""
            if "artifact.sha256" in cmd and "releases" in cmd:
                return 1, "", "No such file"
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
            if _is_remote_current_release_read(cmd):
                return 1, "", "No such file"
            if _is_remote_current_release_switch(cmd):
                return 0, "", ""
            if _is_remote_runner_config_read(cmd):
                return 1, "", "No such file"
            if _is_remote_bundle_cleanup(cmd) or _is_remote_config_atomic_move(cmd):
                return 0, "", ""
            if "rm -rf" in cmd and "/locks/install-" in cmd:
                return 0, "", ""
            if "owner.json" in cmd and "printf %s" in cmd:
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
        ), patch("core.remote_runner.reuse.resolve_runner_token", lambda token_ref: "phase2-token"), patch(
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
    assert any("printf" in cmd and "artifact.sha256" in cmd for cmd in executed)


def test_bootstrap_retries_canary_once_with_fresh_tunnel_after_connection_refused(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    executed: list[str] = []
    tunnel_ports: list[int] = []
    closed_tunnels: list[str] = []
    canary_calls = 0

    class FakeArtifact:
        archive_path = Path(__file__)
        platform = "linux-64"
        sha256 = "c" * 64

    class FakeTunnel:
        def __init__(self, local_port: int) -> None:
            self.local_port = local_port

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
                return 1, "", "No such file"
            if "cat /home/tester/.h2ometa/runner/shared/config/runner.json" in cmd:
                return 1, "", "No such file"
            if "mkdir -p" in cmd:
                return 0, "", ""
            if "pkill -f '[r]emote_runner.run'" in cmd and "runner-state.json" in cmd:
                return 0, "", ""
            if "tar -xzf" in cmd:
                return 0, "", ""
            if "printf" in cmd and "artifact.sha256" in cmd:
                return 0, "", ""
            if "runtime/bin/python -c \"from remote_runner.config import load_remote_runner_config, ensure_runtime_layout; ensure_runtime_layout(load_remote_runner_config())\"" in cmd:
                return 0, "", ""
            if "workflow-env/bin/snakemake" in cmd and "--version" in cmd:
                return 0, "9.19.0\n", ""
            if "rm -f /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, "", ""
            if "bash /home/tester/.h2ometa/runner/current/start_service.sh" in cmd:
                return 0, "", ""
            if "cat /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, _runtime_state_json(), ""
            if "kill -0 123" in cmd:
                return 0, "", ""
            if _is_remote_current_release_switch(cmd):
                return 0, "", ""
            if _is_remote_bundle_cleanup(cmd) or _is_remote_config_atomic_move(cmd):
                return 0, "", ""
            if "rm -rf" in cmd and "/locks/install-" in cmd:
                return 0, "", ""
            if "owner.json" in cmd and "printf %s" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            return None

        def ensure_local_tunnel(self, *args, **kwargs):
            tunnel_ports.append(int(kwargs["remote_port"]))
            return FakeTunnel(18000 + len(tunnel_ports))

        def close_local_tunnel(self, name: str) -> None:
            closed_tunnels.append(name)

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

    def flaky_canary(*, client, server_id, bootstrap_metadata):
        nonlocal canary_calls
        canary_calls += 1
        if canary_calls == 1:
            raise RemoteRunnerManagerError(
                "bootstrap canary failed: [WinError 10054] 远程主机强迫关闭了一个现有的连接。"
            )
        bootstrap_metadata["canary"] = {"ok": True, "status": "passed"}
        return bootstrap_metadata["canary"]

    with patch.object(manager, "_artifact_provider", SimpleNamespace(resolve=lambda **kwargs: FakeArtifact())), patch(
        "core.remote_runner.manager.RemoteRunnerHttpClient", FakeClient
    ), patch.object(manager, "_run_bootstrap_canary", flaky_canary), patch(
        "core.remote_runner.manager.store_runner_token", lambda **kwargs: "runner://srv_test"
    ):
        result = manager.bootstrap(
            server_id="srv_test",
            server={"label": "demo"},
            ssh_service=FakeSSH(),
            server_record={},
        )

    assert canary_calls == 2
    assert tunnel_ports == [43127, 43127]
    assert closed_tunnels == ["runner-srv_test"]
    assert result["health"]["ready"]["ok"] is True
    assert result["bootstrap_metadata"]["canary_retry"]["servicePort"] == 43127
    assert result["bootstrap_metadata"]["canary"] == {"ok": True, "status": "passed"}


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
            if _is_remote_current_release_read(cmd):
                return 1, "", "No such file"
            if _is_remote_current_release_switch(cmd):
                return 0, "", ""
            if _is_remote_runner_config_read(cmd):
                return 1, "", "No such file"
            if _is_remote_bundle_cleanup(cmd) or _is_remote_config_atomic_move(cmd):
                return 0, "", ""
            if "rm -rf" in cmd and "/locks/install-" in cmd:
                return 0, "", ""
            if "owner.json" in cmd and "printf %s" in cmd:
                return 0, "", ""
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
        except RuntimeError as exc:
            assert "remote runner artifact not found" in str(exc)
        else:
            raise AssertionError("bootstrap should fail when artifact cannot be resolved")

def test_bootstrap_does_not_persist_local_token_before_remote_service_is_healthy(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    uploaded_config: dict[str, object] = {}

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
            if "cat /home/tester/.h2ometa/runner/shared/config/runner.json" in cmd:
                return 0, json.dumps(uploaded_config), ""
            if "runtime/bin/python -c \"from remote_runner.config import load_remote_runner_config, ensure_runtime_layout; ensure_runtime_layout(load_remote_runner_config())\"" in cmd:
                return 0, "", ""
            if "bash /home/tester/.h2ometa/runner/current/start_service.sh" in cmd:
                raise RuntimeError("service failed to start")
            return 0, "", ""

        def upload(self, local: str, remote: str) -> None:
            if remote in {"/home/tester/.h2ometa/runner/shared/config/runner.json", "/home/tester/.h2ometa/runner/shared/config/runner.json.tmp"}:
                uploaded_config.update(json.loads(Path(local).read_text(encoding="utf-8")))
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
            if _is_remote_current_release_read(cmd):
                return 1, "", "No such file"
            if _is_remote_current_release_switch(cmd):
                return 0, "", ""
            if _is_remote_runner_config_read(cmd):
                return 1, "", "No such file"
            if _is_remote_bundle_cleanup(cmd) or _is_remote_config_atomic_move(cmd):
                return 0, "", ""
            if "rm -rf" in cmd and "/locks/install-" in cmd:
                return 0, "", ""
            if "owner.json" in cmd and "printf %s" in cmd:
                return 0, "", ""
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
