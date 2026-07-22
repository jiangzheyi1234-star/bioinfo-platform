from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.remote_runner.errors import RemoteRunnerManagerError
from core.remote_runner.manager import RemoteRunnerManager
from tests.helpers.remote_runner_control_plane import (
    _default_workflow_runtime,  # noqa: F401
    _is_remote_bundle_cleanup,
    _is_remote_config_atomic_move,
    _is_remote_current_release_read,
    _is_remote_current_release_switch,
    _is_remote_runner_config_read,
    _remote_runner_manifest,
    packaged_remote_runner_sqlite_evidence,
)


def test_canary_retry_covers_remote_end_closed_response() -> None:
    assert RemoteRunnerManager._canary_failure_needs_fresh_tunnel_retry(
        "bootstrap canary failed: Remote end closed connection without response"
    )


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

    with patch.object(
        manager,
        "_artifact_provider",
        SimpleNamespace(resolve=fail_resolve),
    ):
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
            raise AssertionError(
                "bootstrap should fail when artifact cannot be resolved"
            )


def test_bootstrap_does_not_persist_local_token_before_remote_service_is_healthy() -> (
    None
):
    manager = RemoteRunnerManager()
    uploaded_config: dict[str, object] = {}

    class FakeBundle:
        archive_path = Path(__file__)
        manifest = _remote_runner_manifest()
        sqlite_evidence = packaged_remote_runner_sqlite_evidence()

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
            if "runner_protocol_startup" in cmd:
                return 0, "", ""
            if "bash /home/tester/.h2ometa/runner/current/start_service.sh" in cmd:
                raise RuntimeError("service failed to start")
            return 0, "", ""

        def upload(self, local: str, remote: str) -> None:
            if remote in {
                "/home/tester/.h2ometa/runner/shared/config/runner.json",
                "/home/tester/.h2ometa/runner/shared/config/runner.json.tmp",
                "/home/tester/.h2ometa/runner/shared/config/runner.json.candidate.tmp",
            }:
                uploaded_config.update(
                    json.loads(Path(local).read_text(encoding="utf-8"))
                )

    with (
        patch.object(
            manager,
            "_artifact_provider",
            SimpleNamespace(resolve=lambda **kwargs: FakeBundle()),
        ),
        patch("core.remote_runner.manager.store_runner_token") as store_token,
    ):
        try:
            manager.bootstrap(
                server_id="srv_test",
                server={"label": "demo"},
                ssh_service=FakeSSH(),
                server_record={},
            )
        except Exception as exc:
            assert "service failed to start" in str(exc)
        else:
            raise AssertionError("bootstrap should fail when service startup fails")

    store_token.assert_not_called()


def test_bootstrap_fails_fast_when_bundled_runtime_initialization_returns_nonzero() -> (
    None
):
    manager = RemoteRunnerManager()

    class FakeBundle:
        archive_path = Path(__file__)
        manifest = _remote_runner_manifest()
        sqlite_evidence = packaged_remote_runner_sqlite_evidence()

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
            if "initialize_runtime_layout_from_explicit_config" in cmd:
                return 1, "", "bundled runtime failed"
            if "require_runner_protocol_startup_preflight" in cmd:
                return 0, "", ""
            if _is_remote_current_release_read(cmd):
                return 1, "", "No such file"
            if _is_remote_current_release_switch(cmd):
                return 0, "", ""
            if _is_remote_runner_config_read(cmd):
                return 1, "", "No such file"
            if _is_remote_bundle_cleanup(cmd) or _is_remote_config_atomic_move(cmd):
                return 0, "", ""
            if cmd == "rm -f /home/tester/.h2ometa/runner/shared/config/runner.json":
                return 0, "", ""
            if "rm -rf" in cmd and "/locks/install-" in cmd:
                return 0, "", ""
            if "owner.json" in cmd and "printf %s" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            return None

    with (
        patch.object(
            manager,
            "_artifact_provider",
            SimpleNamespace(resolve=lambda **kwargs: FakeBundle()),
        ),
        patch("core.remote_runner.manager.store_runner_token") as store_token,
    ):
        try:
            manager.bootstrap(
                server_id="srv_test",
                server={"label": "demo"},
                ssh_service=FakeSSH(),
                server_record={},
            )
        except RemoteRunnerManagerError as exc:
            assert "bundled runtime failed" in str(exc)
            assert "initialize remote runner layout" in str(exc)
        else:
            raise AssertionError(
                "bootstrap should fail when bundled runtime initialization exits non-zero"
            )

    store_token.assert_not_called()
