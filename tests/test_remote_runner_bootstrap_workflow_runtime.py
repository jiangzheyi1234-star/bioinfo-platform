from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from core.remote_runner.client import RemoteRunnerClientError
from core.remote_runner.manager import RemoteRunnerManager
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


def test_bootstrap_workflow_runtime_installs_artifact_and_verifies_snakemake(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.remote_runner.manager.RemoteRunnerManager._ensure_workflow_runtime",
        _ORIGINAL_ENSURE_WORKFLOW_RUNTIME,
    )
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
                return 1, "", "missing"
            if "workflow-env/bin/snakemake" in cmd and "--version" in cmd:
                self._snakemake_checks += 1
                if self._snakemake_checks <= 4:
                    return 127, "", "missing"
                return 0, "9.19.0\n", ""
            if "sha256sum /home/tester/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64.tar.gz" in cmd:
                return 1, "", "missing"
            if "tar -xzf" in cmd:
                return 0, "", ""
            if "conda-unpack" in cmd:
                return 0, "", ""
            if "printf" in cmd and "artifact.sha256" in cmd:
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
    monkeypatch.setenv("H2OMETA_ALLOW_REMOTE_WORKFLOW_RUNTIME_REGISTRATION", "1")
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
            if "printf" in cmd and "artifact.sha256" in cmd:
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
    assert metadata["tooling"]["service_runtime"]["python"] == f"/home/tester/.h2ometa/runner/releases/{REMOTE_RUNNER_VERSION}/runtime/bin/python"
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

    monkeypatch.setattr("core.remote_runner.readiness.time.sleep", lambda *_args, **_kwargs: None)

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
