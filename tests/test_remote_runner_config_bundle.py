from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from apps.remote_runner.config import (
    dump_public_config,
    ensure_runtime_layout,
    get_runtime_state_path,
    inspect_workflow_runtime,
    load_remote_runner_config,
    write_runtime_state,
)
from apps.remote_runner.config import RemoteRunnerConfig
from apps.remote_runner.worker_resource_config import build_run_worker_resource_plan
from config import get_app_cache_dir
from core.contracts.linux_process_incarnation import (
    build_linux_process_incarnation,
)
from core.contracts.runner_protocol import RUNNER_PROTOCOL_VERSION
from core.contracts.runner_protocol_runtime import (
    CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
)
from core.contracts.runner_process_lifetime import (
    RUNNER_PROCESS_LIFETIME_LOCK_PROFILE,
)
from core.contracts.runner_process_owner import build_runner_process_owner
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION, RemoteRunnerBundleBuilder
from core.remote_runner.protocol_manifest import require_current_runner_protocol_manifest
from tests.helpers.remote_runner_control_plane import (
    _fake_runtime_dir,
)

def test_get_app_cache_dir_prefers_platform_cache_locations(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("config.os.name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-appdata"))
    assert get_app_cache_dir() == tmp_path / "local-appdata" / "H2OMeta" / "Cache"

def test_remote_runner_config_defaults_to_dynamic_loopback_port() -> None:
    cfg = RemoteRunnerConfig()

    assert cfg.bind_host == "127.0.0.1"
    assert cfg.bind_port == 0
    assert cfg.api_token_roles == ()
    assert Path(cfg.runtime_state_path).parts[-2:] == ("runtime", "runner-state.json")

def test_workflow_runtime_config_helpers_live_outside_config_module() -> None:
    root = Path(__file__).resolve().parents[1]
    config_source = (root / "apps" / "remote_runner" / "config.py").read_text(encoding="utf-8")
    workflow_runtime_path = root / "apps" / "remote_runner" / "workflow_runtime_config.py"
    worker_resource_config_path = root / "apps" / "remote_runner" / "worker_resource_config.py"

    assert workflow_runtime_path.exists()
    assert worker_resource_config_path.exists()
    workflow_runtime_source = workflow_runtime_path.read_text(encoding="utf-8")
    worker_resource_config_source = worker_resource_config_path.read_text(encoding="utf-8")
    assert len(config_source.splitlines()) <= 260
    assert "from .workflow_runtime_config import (" in config_source
    assert "from .worker_resource_config import apply_run_worker_env_overrides" in config_source
    for helper in (
        "build_workflow_runtime_environment",
        "get_workflow_profile_dir",
        "get_workflow_profile_name",
        "get_workflow_profile_path",
        "inspect_workflow_profile",
        "inspect_workflow_runtime",
    ):
        assert f"def {helper}(" not in config_source
        assert f"def {helper}(" in workflow_runtime_source
    assert "def build_run_worker_resource_plan(" not in config_source
    assert "def build_run_worker_resource_plan(" in worker_resource_config_source
    assert "subprocess.run(" not in config_source

def test_write_runtime_state_records_assigned_port(tmp_path: Path) -> None:
    cfg = RemoteRunnerConfig(
        version="test-version",
        data_root=str(tmp_path / "shared"),
        runtime_state_path=str(tmp_path / "shared" / "runtime" / "runner-state.json"),
    )

    process_incarnation = build_linux_process_incarnation(
        boot_id="11111111-2222-3333-4444-555555555555",
        pid=123,
        proc_start_ticks=777,
    )
    state = write_runtime_state(
        cfg,
        bind_host="127.0.0.1",
        bind_port=43127,
        process_owner=build_runner_process_owner(
            launch_id="1" * 32,
            process_incarnation=process_incarnation,
            startup_binding={
                "artifactArchiveSha256Path": "/runner/v5/artifact.sha256",
                "bootstrapManifestFingerprint": "sha256:" + "a" * 64,
                "bootstrapManifestPath": "/runner/v5/bootstrap_manifest.json",
                "configPath": "/runner/shared/config/runner.json",
                "configuredMode": "background_process",
                "declaredArtifactArchiveSha256": "sha256:" + "b" * 64,
                "effectiveConfigFingerprint": "sha256:" + "c" * 64,
                "packagePath": "/runner/v5/remote_runner",
                "persistedConfigFingerprint": "sha256:" + "d" * 64,
                "protocolFingerprint": CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
                "protocolVersion": RUNNER_PROTOCOL_VERSION,
                "runnerPythonPath": "/runner/v5/runtime/bin/python",
                "service": "h2ometa-remote",
                "version": "test-version",
            },
            lifetime_lock={
                "device": 17,
                "inode": 91,
                "path": "/runner/shared/runtime/runner.lock",
                "profile": RUNNER_PROCESS_LIFETIME_LOCK_PROFILE,
            },
        ),
        pid=123,
        process_incarnation=process_incarnation,
    )
    payload = json.loads(get_runtime_state_path(cfg).read_text(encoding="utf-8"))

    assert state["bindPort"] == 43127
    assert payload["service"] == "h2ometa-remote"
    assert payload["version"] == "test-version"
    assert payload["bindHost"] == "127.0.0.1"
    assert payload["bindPort"] == 43127
    assert payload["pid"] == 123
    assert payload["processIncarnation"] == process_incarnation
    assert payload["processOwner"]["launchId"] == "1" * 32

def test_remote_runner_bundle_contains_expected_phase1_files(tmp_path: Path) -> None:
    builder = RemoteRunnerBundleBuilder()
    bundle = builder.build(version=REMOTE_RUNNER_VERSION, platform="linux-64", runtime_dir=_fake_runtime_dir(tmp_path))

    assert (bundle.bundle_dir / "remote_runner" / "main.py").exists()
    assert (bundle.bundle_dir / "remote_runner" / "process_incarnation.py").exists()
    assert (
        bundle.bundle_dir / "remote_runner" / "runner_lifetime_launcher.py"
    ).exists()
    assert (bundle.bundle_dir / "remote_runner" / "process_lifetime_lock.py").exists()
    assert (bundle.bundle_dir / "remote_runner" / "process_pid_file.py").exists()
    assert (bundle.bundle_dir / "remote_runner" / "process_owner.py").exists()
    assert (
        bundle.bundle_dir / "remote_runner" / "activation_storage_session.py"
    ).exists()
    assert (
        bundle.bundle_dir / "remote_runner" / "activation_storage_filesystem.py"
    ).exists()
    assert (
        bundle.bundle_dir / "remote_runner" / "activation_storage_root.py"
    ).exists()
    assert (
        bundle.bundle_dir / "remote_runner" / "activation_storage_errors.py"
    ).exists()
    assert (
        bundle.bundle_dir / "remote_runner" / "activation_storage_layout.py"
    ).exists()
    assert (
        bundle.bundle_dir / "remote_runner" / "activation_installation_storage.py"
    ).exists()
    assert (
        bundle.bundle_dir / "remote_runner" / "activation_no_replace_io.py"
    ).exists()
    assert (
        bundle.bundle_dir
        / "remote_runner"
        / "activation_storage_private_directories.py"
    ).exists()
    assert (
        bundle.bundle_dir
        / "remote_runner"
        / "activation_config_integrity_key_layout.py"
    ).exists()
    assert (
        bundle.bundle_dir / "remote_runner" / "activation_secret_no_replace_io.py"
    ).exists()
    assert (
        bundle.bundle_dir
        / "remote_runner"
        / "activation_config_integrity_key_storage.py"
    ).exists()
    assert (
        bundle.bundle_dir / "remote_runner" / "activation_openat2.py"
    ).exists()
    assert (
        bundle.bundle_dir
        / "remote_runner"
        / "activation_release_publication_layout.py"
    ).exists()
    assert (
        bundle.bundle_dir
        / "remote_runner"
        / "activation_generation_registry_storage.py"
    ).exists()
    assert (bundle.bundle_dir / "remote_runner" / "run.py").exists()
    assert (bundle.bundle_dir / "core" / "__init__.py").exists()
    assert (bundle.bundle_dir / "core" / "logging_config.py").exists()
    assert (bundle.bundle_dir / "core" / "contracts" / "__init__.py").exists()
    assert (bundle.bundle_dir / "core" / "contracts" / "runner_protocol.py").exists()
    assert (
        bundle.bundle_dir / "core" / "contracts" / "linux_process_incarnation.py"
    ).exists()
    assert (
        bundle.bundle_dir / "core" / "contracts" / "runner_process_lifetime.py"
    ).exists()
    assert (
        bundle.bundle_dir / "core" / "contracts" / "runner_process_owner.py"
    ).exists()
    assert (
        bundle.bundle_dir
        / "core"
        / "contracts"
        / "runner_activation_release_archive.py"
    ).exists()
    assert (
        bundle.bundle_dir
        / "core"
        / "contracts"
        / "runner_activation_release_archive_graph.py"
    ).exists()
    assert (
        bundle.bundle_dir
        / "core"
        / "contracts"
        / "runner_activation_release_bootstrap_manifest.py"
    ).exists()
    assert (
        bundle.bundle_dir
        / "core"
        / "contracts"
        / "runner_activation_release_tree.py"
    ).exists()
    assert (
        bundle.bundle_dir
        / "core"
        / "contracts"
        / "runner_activation_release_publication.py"
    ).exists()
    assert (bundle.bundle_dir / "core" / "contracts" / "workflow_design.py").exists()
    assert not (bundle.bundle_dir / "remote_runner" / "requirements.txt").exists()
    assert (bundle.bundle_dir / "remote_runner" / "pipelines" / "file-summary-v1" / "pipeline.json").exists()
    assert (bundle.bundle_dir / "remote_runner" / "pipelines" / "file-summary-v1" / "workflow" / "Snakefile").exists()
    assert (bundle.bundle_dir / "remote_runner" / "pipelines" / "file-summary-v1" / "workflow" / "envs" / "base.yaml").exists()
    assert (
        bundle.bundle_dir
        / "remote_runner"
        / "pipelines"
        / "file-summary-v1"
        / "workflow"
        / "scripts"
        / "generate_outputs.py"
    ).exists()
    assert (bundle.bundle_dir / "runtime" / "bin" / "python").exists()
    assert (bundle.bundle_dir / "h2ometa-remote.service").exists()
    assert (bundle.bundle_dir / "start_service.sh").exists()
    assert (bundle.bundle_dir / "stop_service.sh").exists()
    assert (bundle.bundle_dir / "launch_remote_runner.sh").exists()
    assert (bundle.bundle_dir / "check_service.sh").exists()
    assert (bundle.bundle_dir / "run_workflow.sh").exists()
    assert "launch_remote_runner.sh" in (bundle.bundle_dir / "start_service.sh").read_text(encoding="utf-8")
    assert "launch_remote_runner.sh" in (bundle.bundle_dir / "h2ometa-remote.service").read_text(encoding="utf-8")
    launch_script_path = bundle.bundle_dir / "launch_remote_runner.sh"
    launch_script = launch_script_path.read_text(encoding="utf-8")
    start_script = (bundle.bundle_dir / "start_service.sh").read_text(encoding="utf-8")
    service_unit = (bundle.bundle_dir / "h2ometa-remote.service").read_text(
        encoding="utf-8"
    )
    assert "RUNNER_PYTHON" in launch_script
    assert 'runtime/bin/python' in launch_script
    assert (
        'exec "$RUNNER_PYTHON" -B -m remote_runner.runner_lifetime_launcher'
        in launch_script
    )
    assert (
        'exec "$RUNNER_PYTHON" -B -m remote_runner.run'
        not in launch_script.splitlines()
    )
    assert "conda-unpack" not in launch_script
    assert "require_runner_protocol_startup_preflight" not in launch_script
    assert start_script.index("require_runner_protocol_startup_preflight") < start_script.index(
        "nohup"
    )
    assert 'echo $! > "$RUN_DIR/runner.pid"' not in start_script
    assert "Type=simple" in service_unit
    assert "Restart=on-failure" in service_unit
    assert "RestartPreventExitStatus=73 74 75" in service_unit
    assert "H2OMETA_REMOTE_RUNNER_PYTHON" not in launch_script
    assert 'cd "$RUN_DIR"' in launch_script
    assert b"\r\n" not in launch_script_path.read_bytes()
    assert bundle.archive_path.exists()
    assert bundle.platform == "linux-64"
    manifest = json.loads(
        (bundle.bundle_dir / "bootstrap_manifest.json").read_text(encoding="utf-8")
    )
    runner_protocol = require_current_runner_protocol_manifest(manifest)
    assert runner_protocol["protocolVersion"] == RUNNER_PROTOCOL_VERSION
    assert runner_protocol["coverage"]["automaticRecoveryEnabled"] is False

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


def test_remote_runner_config_loads_explicit_api_token_roles_and_redacts_public_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "token": "phase2-token",
                "api_token_actor": "operator-machine",
                "api_token_roles": ["workflow-operator", "data-steward"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    cfg = load_remote_runner_config()
    public = dump_public_config(cfg)

    assert cfg.api_token_actor == "operator-machine"
    assert cfg.api_token_roles == ("workflow-operator", "data-steward")
    assert "token" not in public
    assert "api_token_actor" not in public
    assert "api_token_roles" not in public


def test_remote_runner_config_rejects_unsupported_api_token_roles(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps({"token": "phase2-token", "api_token_roles": ["super-admin"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    with pytest.raises(ValueError, match="REMOTE_RUNNER_TOKEN_ROLE_UNSUPPORTED: super-admin"):
        load_remote_runner_config()


def test_load_remote_runner_config_preserves_and_overrides_worker_capacity(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "token": "phase2-token",
                "run_worker_slot_count": 2,
                "run_worker_total_cpu": 2,
                "run_worker_total_memory_mb": 4096,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    monkeypatch.setenv("H2OMETA_REMOTE_RUN_WORKER_TOTAL_CPU", "4")

    cfg = load_remote_runner_config()
    plan = build_run_worker_resource_plan(cfg)

    assert cfg.run_worker_slot_count == 2
    assert cfg.run_worker_total_cpu == 4
    assert plan.slot_count == 2
    assert plan.resource_capacity.cpu == 4
    assert plan.resource_capacity.memory_mb == 4096
    assert plan.resource_pool_config.max_concurrent_tasks == 2


def test_run_worker_resource_plan_rejects_unsupported_slot_count() -> None:
    cfg = RemoteRunnerConfig(run_worker_slot_count=3, run_worker_total_cpu=3)

    with pytest.raises(ValueError, match="P0_3B_MAX_TWO_SLOTS"):
        build_run_worker_resource_plan(cfg)

def test_inspect_workflow_runtime_runs_snakemake_with_workflow_bin_on_path(tmp_path: Path, monkeypatch) -> None:
    managed_conda_command = tmp_path / "tooling" / "workflow-env" / "bin" / "conda"
    snakemake_command = tmp_path / "tooling" / "workflow-env" / "bin" / "snakemake"
    managed_conda_command.parent.mkdir(parents=True, exist_ok=True)
    managed_conda_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    managed_conda_command.chmod(0o755)
    snakemake_command.write_text("#!/usr/bin/env python3.12\n", encoding="utf-8")
    snakemake_command.chmod(0o755)
    shared_root = tmp_path / "shared"
    cfg = RemoteRunnerConfig(
        data_root=str(shared_root),
        db_path=str(shared_root / "data" / "runner.db"),
        runtime_state_path=str(shared_root / "runtime" / "runner-state.json"),
        uploads_dir=str(shared_root / "uploads"),
        results_dir=str(shared_root / "results"),
        work_dir=str(shared_root / "work"),
        logs_dir=str(shared_root / "logs"),
        managed_conda_command=str(managed_conda_command),
        snakemake_command=str(snakemake_command),
    )
    ensure_runtime_layout(cfg)
    calls: list[dict[str, object]] = []

    class Result:
        returncode = 0
        stdout = "9.19.0\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, "env": kwargs.get("env")})
        return Result()

    monkeypatch.setattr("apps.remote_runner.workflow_runtime_config.subprocess.run", fake_run)

    result = inspect_workflow_runtime(cfg)

    assert result["ok"] is True
    assert calls[0]["cmd"] == [str(snakemake_command), "--version"]
    env = calls[0]["env"]
    assert isinstance(env, dict)
    assert env["PATH"].split(os.pathsep)[0] == str(snakemake_command.parent)


def test_inspect_workflow_runtime_does_not_mask_unexpected_version_check_errors(
    tmp_path: Path, monkeypatch
) -> None:
    managed_conda_command = tmp_path / "tooling" / "workflow-env" / "bin" / "conda"
    snakemake_command = tmp_path / "tooling" / "workflow-env" / "bin" / "snakemake"
    managed_conda_command.parent.mkdir(parents=True, exist_ok=True)
    managed_conda_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    managed_conda_command.chmod(0o755)
    snakemake_command.write_text("#!/usr/bin/env python3.12\n", encoding="utf-8")
    snakemake_command.chmod(0o755)
    shared_root = tmp_path / "shared"
    cfg = RemoteRunnerConfig(
        data_root=str(shared_root),
        db_path=str(shared_root / "data" / "runner.db"),
        runtime_state_path=str(shared_root / "runtime" / "runner-state.json"),
        uploads_dir=str(shared_root / "uploads"),
        results_dir=str(shared_root / "results"),
        work_dir=str(shared_root / "work"),
        logs_dir=str(shared_root / "logs"),
        managed_conda_command=str(managed_conda_command),
        snakemake_command=str(snakemake_command),
    )
    ensure_runtime_layout(cfg)

    def fake_run(*args, **kwargs):
        raise ValueError("unexpected subprocess state")

    monkeypatch.setattr("apps.remote_runner.workflow_runtime_config.subprocess.run", fake_run)

    with pytest.raises(ValueError, match="unexpected subprocess state"):
        inspect_workflow_runtime(cfg)
