from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.remote_runner.catalog import RemoteRunnerCatalogMixin
from core.remote_runner.client import RemoteRunnerClientError
from core.remote_runner.manager import RemoteRunnerManagerError


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_catalog_client_errors_preserve_http_status_on_manager_error() -> None:
    class FailingClient:
        def post_json(self, _path, _payload):
            raise RemoteRunnerClientError(
                "runner http error 422: DATABASE_PATH_REQUIRED",
                status_code=422,
                detail="DATABASE_PATH_REQUIRED",
            )

    class Catalog(RemoteRunnerCatalogMixin):
        def _get_client(self, **_kwargs):
            return FailingClient()

        @staticmethod
        def _manager_error(message: str, *, status_code: int | None = None, detail=None) -> RuntimeError:
            return RemoteRunnerManagerError(message, status_code=status_code, detail=detail)

    with pytest.raises(RemoteRunnerManagerError) as raised:
        Catalog().add_database(server_id="srv_test", ssh_service=object(), server_record={}, payload={})

    assert raised.value.status_code == 422
    assert raised.value.detail == "DATABASE_PATH_REQUIRED"


def test_remote_install_lock_logic_lives_in_install_lock_module() -> None:
    manager_source = _source("core/remote_runner/manager.py")
    install_lock_source = _source("core/remote_runner/install_lock.py")

    assert "from core.remote_runner.install_lock import" in manager_source
    assert "RemoteRunnerInstallLockMixin" in manager_source
    assert "class RemoteRunnerInstallLockMixin" in install_lock_source
    assert "def acquire_remote_install_lock(" in install_lock_source
    assert "def _acquire_remote_install_lock(" in install_lock_source
    assert "def reclaim_stale_install_lock(" in install_lock_source
    assert "def release_remote_install_lock(" in install_lock_source
    assert "def _release_remote_install_lock(" in install_lock_source
    assert "def _acquire_remote_install_lock(" not in manager_source
    assert "def _release_remote_install_lock(" not in manager_source
    assert "def _reclaim_stale_install_lock" not in manager_source
    assert "except Exception" not in install_lock_source


def test_bootstrap_service_runtime_bundle_deployment_lives_outside_manager() -> None:
    manager_source = _source("core/remote_runner/manager.py")
    bundle_path = ROOT / "core/remote_runner/bootstrap_bundle.py"

    assert bundle_path.exists()
    bundle_source = bundle_path.read_text(encoding="utf-8")
    assert "from core.remote_runner.bootstrap_bundle import RemoteRunnerBootstrapBundleMixin" in manager_source
    assert "RemoteRunnerBootstrapBundleMixin" in manager_source
    assert "def _deploy_service_runtime_bundle(" in bundle_source
    assert "_deploy_service_runtime_bundle(" in manager_source
    assert "clear previous remote runner service" not in manager_source
    assert "extract remote runner bundle" not in manager_source
    assert "write remote runner artifact marker" not in manager_source
    assert "cleanup remote runner bundle" not in manager_source
    assert "ssh_service.upload(str(artifact.archive_path), paths.bundle)" not in manager_source


def test_bootstrap_service_runtime_bundle_deployment_runs_expected_remote_steps() -> None:
    from types import SimpleNamespace

    from core.remote_runner.bootstrap_bundle import RemoteRunnerBootstrapBundleMixin

    class FakeSshService:
        def __init__(self) -> None:
            self.uploads: list[tuple[str, str]] = []

        def upload(self, local_path: str, remote_path: str) -> None:
            self.uploads.append((local_path, remote_path))

    class Deployer(RemoteRunnerBootstrapBundleMixin):
        def __init__(self) -> None:
            self.checked_steps: list[tuple[str, str, int]] = []
            self.writes: list[tuple[str, str, str, int]] = []
            self.cleanups: list[tuple[str, str]] = []

        def _run_checked(self, _ssh_service, command: str, *, step: str, timeout: int):
            self.checked_steps.append((step, command, timeout))

        def _write_remote_text_atomic(self, _ssh_service, *, path: str, content: str, step: str, timeout: int):
            self.writes.append((path, content, step, timeout))

        def _cleanup_remote_bundle(self, _ssh_service, remote_bundle: str, *, step: str):
            self.cleanups.append((remote_bundle, step))

    paths = SimpleNamespace(
        bundle="/opt/h2o/current/bundle.tar.gz",
        release="/opt/h2o/releases/v1 with space",
        runtime_state="/opt/h2o/state/runtime.json",
        artifact_sha="/opt/h2o/current/artifact.sha256",
        remote_directories=lambda: ["/opt/h2o/root", "/opt/h2o/releases/v1 with space"],
    )
    artifact = SimpleNamespace(archive_path="C:/tmp/remote-runner.tar.gz", sha256="abc123")
    ssh_service = FakeSshService()
    deployer = Deployer()

    deployer._deploy_service_runtime_bundle(
        ssh_service=ssh_service,
        artifact=artifact,
        paths=paths,
    )

    assert [step for step, _command, _timeout in deployer.checked_steps] == [
        "prepare remote runner directories",
        "clear previous remote runner service",
        "extract remote runner bundle",
    ]
    assert ssh_service.uploads == [("C:/tmp/remote-runner.tar.gz", "/opt/h2o/current/bundle.tar.gz")]
    assert deployer.writes == [
        (
            "/opt/h2o/current/artifact.sha256",
            "abc123",
            "write remote runner artifact marker",
            10,
        )
    ]
    assert deployer.cleanups == [
        ("/opt/h2o/current/bundle.tar.gz", "cleanup remote runner bundle"),
    ]
    assert "'/opt/h2o/releases/v1 with space'" in deployer.checked_steps[0][1]
    assert "tar -xzf /opt/h2o/current/bundle.tar.gz -C '/opt/h2o/releases/v1 with space'" in deployer.checked_steps[2][1]


def test_remote_runner_manager_stays_below_source_line_budget() -> None:
    manager_lines = (ROOT / "core/remote_runner/manager.py").read_text(encoding="utf-8").splitlines()

    assert len(manager_lines) <= 800


def test_remote_runner_manager_error_lives_in_errors_module() -> None:
    manager_source = _source("core/remote_runner/manager.py")
    errors_source = _source("core/remote_runner/errors.py")

    assert "from core.remote_runner.errors import RemoteRunnerManagerError" in manager_source
    assert "class RemoteRunnerManagerError" in errors_source
    assert "class RemoteRunnerManagerError" not in manager_source


def test_bootstrap_outer_error_boundary_only_wraps_declared_domain_errors() -> None:
    manager_source = _source("core/remote_runner/manager.py")

    bootstrap_tail = manager_source.split("except RemoteRunnerArtifactError as exc:", 1)[1]
    assert "except Exception as exc" not in bootstrap_tail
    assert "except RemoteRunnerArtifactError as exc" in manager_source
    assert "locals().get(" not in manager_source
    assert "bootstrap_metadata: dict[str, Any] | None = None" in manager_source


def test_bootstrap_reuse_logic_lives_in_reuse_module() -> None:
    manager_source = _source("core/remote_runner/manager.py")
    reuse_source = _source("core/remote_runner/reuse.py")

    assert "from core.remote_runner.reuse import RemoteRunnerReuseMixin" in manager_source
    assert "RemoteRunnerReuseMixin" in manager_source
    assert "class RemoteRunnerReuseMixin" in reuse_source
    assert "def _try_reuse_existing_runner_fast(" in reuse_source
    assert "def _try_reuse_existing_runner(" in reuse_source
    assert "def _try_reuse_existing_runner_fast(" not in manager_source
    assert "def _try_reuse_existing_runner(" not in manager_source


def test_bootstrap_install_metadata_lives_in_metadata_module() -> None:
    manager_source = _source("core/remote_runner/manager.py")
    metadata_source = _source("core/remote_runner/metadata.py")

    assert len(manager_source.splitlines()) <= 430
    assert "build_install_bootstrap_metadata" in manager_source
    assert "def build_install_bootstrap_metadata(" in metadata_source
    assert "bootstrap_metadata: dict[str, Any] = {" not in manager_source
    assert '"release_switch": {' in metadata_source
    assert '"canary": {' in metadata_source


def test_bootstrap_activation_rollback_only_wraps_declared_runner_failures() -> None:
    manager_source = _source("core/remote_runner/manager.py")

    activation_source = manager_source.split("self._switch_current_release(", 1)[1]
    activation_source = activation_source.split("token_ref = store_runner_token(", 1)[0]
    assert "except Exception as exc" not in activation_source
    assert "except (RemoteRunnerManagerError, RemoteRunnerClientError) as exc" in activation_source


def test_workflow_runtime_logic_lives_in_workflow_runtime_module() -> None:
    manager_source = _source("core/remote_runner/manager.py")
    workflow_runtime_source = _source("core/remote_runner/workflow_runtime.py")

    assert "from core.remote_runner.workflow_runtime import RemoteRunnerWorkflowRuntimeMixin" in manager_source
    assert "RemoteRunnerWorkflowRuntimeMixin" in manager_source
    assert "class RemoteRunnerWorkflowRuntimeMixin" in workflow_runtime_source
    assert "def _ensure_workflow_runtime(" in workflow_runtime_source
    assert "def _resolve_remote_workflow_artifact(" in workflow_runtime_source
    assert "def _verify_workflow_runtime_command(" in workflow_runtime_source
    assert "def _ensure_workflow_runtime(" not in manager_source
    assert "def _verify_workflow_runtime_command(" not in manager_source


def test_bootstrap_activation_logic_lives_in_activation_module() -> None:
    manager_source = _source("core/remote_runner/manager.py")
    activation_source = _source("core/remote_runner/bootstrap_activation.py")

    assert "from core.remote_runner.bootstrap_activation import RemoteRunnerBootstrapActivationMixin" in manager_source
    assert "RemoteRunnerBootstrapActivationMixin" in manager_source
    assert "class RemoteRunnerBootstrapActivationMixin" in activation_source
    assert "def _run_bootstrap_canary(" in activation_source
    assert "def _attempt_release_rollback(" in activation_source
    assert "def _run_bootstrap_canary(" not in manager_source
    assert "def _attempt_release_rollback(" not in manager_source


def test_bootstrap_canary_only_wraps_declared_runner_failures() -> None:
    activation_source = _source("core/remote_runner/bootstrap_activation.py")

    canary_source = activation_source.split("def _run_bootstrap_canary(", 1)[1]
    canary_source = canary_source.split("def _wait_for_terminal_run(", 1)[0]
    assert "except Exception as exc" not in canary_source
    assert "except (self._manager_error, RemoteRunnerClientError) as exc" in canary_source


def test_rollback_failure_record_only_wraps_declared_runner_failures() -> None:
    activation_source = _source("core/remote_runner/bootstrap_activation.py")

    rollback_source = activation_source.split("def _attempt_release_rollback(", 1)[1]
    assert "except Exception as exc" not in rollback_source
    assert "except (cls._manager_error, RemoteRunnerClientError) as exc" in rollback_source


def test_workflow_profile_cleanup_does_not_swallow_unlink_errors() -> None:
    activation_source = _source("core/remote_runner/bootstrap_activation.py")

    profile_source = activation_source.split("def _write_remote_workflow_profile(", 1)[1]
    profile_source = profile_source.split("def _run_bootstrap_canary(", 1)[0]
    cleanup_source = profile_source.split("finally:", 1)[1]
    assert "except OSError" not in cleanup_source
    assert "pass" not in cleanup_source


def test_bootstrap_temp_config_cleanup_does_not_swallow_unlink_errors() -> None:
    manager_source = _source("core/remote_runner/manager.py")
    helper_source = _source("core/remote_runner/bootstrap_config_files.py")

    cleanup_source = helper_source.split("def cleanup_bootstrap_config_temp_files(", 1)[1]
    assert "temp_path.unlink(missing_ok=True)" in cleanup_source
    assert "cleanup_bootstrap_config_temp_files(config_temp_files)" in manager_source
    assert "self._release_remote_install_lock" in manager_source
    assert "except OSError" not in cleanup_source
    assert "pass" not in cleanup_source


def test_bootstrap_config_temp_file_io_lives_outside_manager() -> None:
    manager_source = _source("core/remote_runner/manager.py")
    helper_path = ROOT / "core/remote_runner/bootstrap_config_files.py"

    assert helper_path.exists()
    helper_source = helper_path.read_text(encoding="utf-8")

    assert "from core.remote_runner.bootstrap_config_files import (" in manager_source
    assert "json.dump(" not in manager_source
    assert "tempfile.NamedTemporaryFile(" not in manager_source
    assert "Path(handle.name)" not in manager_source
    assert "write_bootstrap_config_temp_files(" in helper_source
    assert "cleanup_bootstrap_config_temp_files(" in helper_source
    assert "json.dump(" in helper_source
    assert "tempfile.NamedTemporaryFile(" in helper_source
    assert "except OSError" not in helper_source
    assert "pass" not in helper_source


def test_bootstrap_config_temp_files_write_and_cleanup_json_payloads() -> None:
    from core.remote_runner.bootstrap_config_files import (
        cleanup_bootstrap_config_temp_files,
        write_bootstrap_config_temp_files,
    )

    temp_files = write_bootstrap_config_temp_files(
        previous_config_payload={"version": "old"},
        config_payload={"version": "new", "mode": "user"},
    )
    try:
        assert json.loads(temp_files.previous_config_path.read_text(encoding="utf-8")) == {"version": "old"}
        assert json.loads(temp_files.config_path.read_text(encoding="utf-8")) == {"version": "new", "mode": "user"}
    finally:
        cleanup_bootstrap_config_temp_files(temp_files)

    assert not temp_files.config_path.exists()
    assert temp_files.previous_config_path is not None
    assert not temp_files.previous_config_path.exists()


def test_bootstrap_reuse_response_composition_lives_outside_manager() -> None:
    manager_source = _source("core/remote_runner/manager.py")
    response_path = ROOT / "core/remote_runner/bootstrap_response.py"

    assert response_path.exists()
    response_source = response_path.read_text(encoding="utf-8")
    assert "from core.remote_runner.bootstrap_response import (" in manager_source
    assert "build_bootstrap_reuse_response" in manager_source
    assert "**reuse_result" not in manager_source
    assert "def build_bootstrap_reuse_response(" in response_source
    assert '"server_label": str(server.get("label", "") or "")' in response_source


def test_bootstrap_reuse_response_preserves_reuse_payload_without_mutating_input() -> None:
    from core.remote_runner.bootstrap_response import build_bootstrap_reuse_response

    reuse_result = {"bootstrap_version": "phase1-test", "runner_mode": "background_process"}
    response = build_bootstrap_reuse_response(reuse_result, {"label": "prod-box"})

    assert response == {
        "bootstrap_version": "phase1-test",
        "runner_mode": "background_process",
        "server_label": "prod-box",
    }
    assert reuse_result == {"bootstrap_version": "phase1-test", "runner_mode": "background_process"}


def test_bootstrap_install_response_composition_lives_outside_manager() -> None:
    manager_source = _source("core/remote_runner/manager.py")
    response_source = _source("core/remote_runner/bootstrap_response.py")

    install_tail = manager_source.split("token_ref = store_runner_token(", 1)[1]
    install_tail = install_tail.split("finally:", 1)[0]
    assert "build_bootstrap_install_response(" in install_tail
    assert '"bootstrap_version": version' not in install_tail
    assert 'bootstrap_metadata["reuse_check"]' not in manager_source
    assert "def build_bootstrap_install_response(" in response_source
    assert '"reuse_check"' in response_source
    assert '"not reusable"' in response_source


def test_bootstrap_install_response_preserves_metadata_without_mutating_input() -> None:
    from core.remote_runner.bootstrap_response import build_bootstrap_install_response

    metadata = {"deployment_action": "installed"}
    response = build_bootstrap_install_response(
        version="phase1-test",
        mode="background_process",
        tunnel_port=3765,
        token_ref="runner://srv_test",
        health={"ready": {"ok": True}},
        service_port=43127,
        server={"label": "prod-box"},
        bootstrap_metadata=metadata,
    )

    assert response == {
        "bootstrap_version": "phase1-test",
        "runner_mode": "background_process",
        "tunnel_port": 3765,
        "token_ref": "runner://srv_test",
        "health": {"ready": {"ok": True}},
        "service_port": 43127,
        "server_label": "prod-box",
        "bootstrap_metadata": {
            "deployment_action": "installed",
            "reuse_check": {"ok": False, "reason": "not reusable"},
        },
    }
    assert metadata == {"deployment_action": "installed"}


def test_database_catalog_only_handles_domain_specific_client_errors() -> None:
    catalog_source = _source("core/remote_runner/catalog.py")

    assert catalog_source.count("except RemoteRunnerClientError") == 1
    assert "RemoteRunnerConflictError" in catalog_source
    assert "DATABASE_CANDIDATES" not in catalog_source
    assert "json.loads" not in catalog_source
    simple_methods = (
        ("def list_database_templates(", "def list_databases("),
        ("def list_databases(", "def add_database("),
        ("def update_database(", "def delete_database("),
        ("def delete_database(", "def check_database("),
        ("def check_database(", "def _manager_error("),
    )
    for start, end in simple_methods:
        method_source = catalog_source.split(start, 1)[1].split(end, 1)[0]
        assert "except RemoteRunnerClientError" not in method_source
        assert "self._manager_error(str(exc))" not in method_source


def test_remote_runner_proxy_forwarders_do_not_wrap_client_errors() -> None:
    proxy_source = _source("core/remote_runner/proxy.py")

    forwarding_source = proxy_source.split("class RemoteRunnerProxyMixin:", 1)[1]
    forwarding_source = forwarding_source.split("def _open_runner_tunnel(", 1)[0]
    assert "except RemoteRunnerClientError" not in forwarding_source
    assert "self._manager_error(str(exc))" not in forwarding_source


def test_token_rotation_logic_lives_in_token_rotation_module() -> None:
    manager_source = _source("core/remote_runner/manager.py")
    proxy_source = _source("core/remote_runner/proxy.py")
    rotation_path = ROOT / "core/remote_runner/token_rotation.py"

    assert rotation_path.exists()
    rotation_source = rotation_path.read_text(encoding="utf-8")
    assert "from core.remote_runner.token_rotation import RemoteRunnerTokenRotationMixin" in manager_source
    assert "RemoteRunnerTokenRotationMixin" in manager_source
    assert "class RemoteRunnerTokenRotationMixin" in rotation_source
    assert "def rotate_token(" in rotation_source
    assert "def rotate_token(" not in proxy_source
    assert "store_runner_token" not in proxy_source
    assert "secrets.token_urlsafe" in rotation_source
    assert "except Exception as exc" not in rotation_source


def test_rotate_token_does_not_have_outer_defensive_wrapper() -> None:
    rotation_path = ROOT / "core/remote_runner/token_rotation.py"

    assert rotation_path.exists()
    rotation_source = rotation_path.read_text(encoding="utf-8")
    rotate_source = rotation_source.split("def rotate_token(", 1)[1]
    rotate_source = rotate_source.split("def _open_runner_tunnel(", 1)[0]
    outer_tail = rotate_source.split('return {"token_ref": token_ref}', 1)[1]
    assert "except Exception as exc" not in outer_tail
    assert "_is_manager_error(exc)" not in outer_tail


def test_get_client_uses_tunnel_boundary_for_adapter_errors() -> None:
    proxy_source = _source("core/remote_runner/proxy.py")

    tunnel_source = proxy_source.split("def _open_runner_tunnel(", 1)[1]
    tunnel_source = tunnel_source.split("def _get_client(", 1)[0]
    client_source = proxy_source.split("def _get_client(", 1)[1]
    client_source = client_source.split("def _manager_error(", 1)[0]

    assert "ensure_local_tunnel(" in tunnel_source
    assert "except (RuntimeError, OSError, EOFError) as exc:" in tunnel_source
    assert "_is_manager_error(exc)" in tunnel_source
    assert "self._get_client_connection(" in client_source
    assert "ensure_local_tunnel(" not in client_source
    assert "except Exception" not in client_source


def test_runner_health_wait_only_retries_explicit_readiness_failures() -> None:
    readiness_source = _source("core/remote_runner/readiness.py")

    wait_source = readiness_source.split("def _wait_for_runner_health(", 1)[1]
    wait_source = wait_source.split("def _require_ready_health(", 1)[0]
    assert "except Exception" not in wait_source
    assert "RemoteRunnerClientError" in wait_source
    assert "_ready_health_error(" in wait_source
