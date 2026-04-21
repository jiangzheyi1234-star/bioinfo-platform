from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from apps.remote_runner.config import ensure_runtime_layout, load_remote_runner_config
from apps.remote_runner.main import (
    UploadCreateRequest,
    RunCreateRequest,
    create_upload,
    create_run,
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


class FakeRuntimeArtifact:
    fingerprint = "runtime1234"
    archive_path = Path(__file__)
    python_relative_path = "runner-env/bin/python"


def test_remote_runner_bundle_contains_expected_phase1_files(tmp_path: Path) -> None:
    builder = RemoteRunnerBundleBuilder()
    bundle = builder.build(version=REMOTE_RUNNER_VERSION)

    assert (bundle.bundle_dir / "remote_runner" / "main.py").exists()
    assert (bundle.bundle_dir / "remote_runner" / "run.py").exists()
    assert (bundle.bundle_dir / "remote_runner" / "requirements.txt").exists()
    assert (bundle.bundle_dir / "remote_runner" / "workflow" / "Snakefile").exists()
    assert (bundle.bundle_dir / "remote_runner" / "workflow" / "envs" / "base.yaml").exists()
    assert (bundle.bundle_dir / "remote_runner" / "workflow" / "scripts" / "generate_outputs.py").exists()
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
    assert "runner_python" in launch_script
    assert 'cd "$RUN_DIR"' in launch_script
    assert b"\r\n" not in launch_script_path.read_bytes()
    assert bundle.archive_path.exists()


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
            if "tar -xzf" in cmd:
                return 0, "", ""
            if "micro.mamba.pm/api/micromamba/linux-64/latest" in cmd:
                return 0, "", ""
            if "ensure_runtime_layout" in cmd:
                return 0, "", ""
            if "bash /home/tester/.h2ometa/runner/current/start_service.sh" in cmd:
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

    with patch.object(manager, "_bundle_builder", SimpleNamespace(build=lambda version: FakeBundle())), patch.object(
        manager, "_runtime_packager", SimpleNamespace(build=lambda *args, **kwargs: FakeRuntimeArtifact())
    ), patch("core.remote_runner.manager.RemoteRunnerHttpClient", FakeClient), patch(
        "core.remote_runner.manager.store_runner_token", lambda **kwargs: "runner://srv_test"
    ):
        manager.bootstrap(
            server_id="srv_test",
            server={"label": "demo"},
            ssh_service=FakeSSH(),
            server_record={},
        )

    extract_cmd = next(cmd for cmd in executed if "tar -xzf" in cmd)
    assert "chmod 0755" in extract_cmd
    assert "runner-runtime-runtime1234.tar.gz" in extract_cmd


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
    assert ready["status"] == "ok"
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


def test_load_remote_runner_config_preserves_managed_conda_metadata(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
    managed_conda_command = tmp_path / "tooling" / "bin" / "micromamba"
    managed_conda_root_prefix = tmp_path / "tooling" / "micromamba-root"
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
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    cfg = load_remote_runner_config()

    assert cfg.managed_conda_command == str(managed_conda_command)
    assert cfg.managed_conda_root_prefix == str(managed_conda_root_prefix)


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
                    "service_port": 8876,
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
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    ensure_runtime_layout(load_remote_runner_config())
    monkeypatch.setattr("apps.remote_runner.main.start_run_execution", lambda cfg, run_id, request_id, run_spec: None)

    submit = asyncio.run(
        create_run(
            RunCreateRequest(
                serverId="srv_demo",
                requestId="req_phase2",
                runSpec={"projectId": "proj_demo", "pipelineId": "taxonomy-v1", "inputs": []},
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
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
    )
    ensure_runtime_layout(cfg)
    (Path(cfg.release_dir) / "workflow" / "envs").mkdir(parents=True, exist_ok=True)
    (Path(cfg.release_dir) / "workflow" / "scripts").mkdir(parents=True, exist_ok=True)
    (Path(cfg.release_dir) / "workflow" / "Snakefile").write_text("rule all:\n  input: 'done.txt'\n", encoding="utf-8")
    (Path(cfg.release_dir) / "workflow" / "envs" / "base.yaml").write_text("channels: [conda-forge]\ndependencies: [python=3.12]\n", encoding="utf-8")

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

    run_snakemake_execution(
        cfg,
        run_id="run_phase2",
        request_id="req_phase2",
        run_spec={"pipelineId": "taxonomy-v1", "projectId": "proj_demo", "inputs": []},
    )

    assert len(calls) == 2
    assert calls[0][:3] == [sys.executable, "-m", "snakemake"]
    assert "--use-conda" in calls[0]
    assert "-n" in calls[0]
    assert "--use-conda" in calls[1]


def test_executor_exports_managed_conda_runtime_when_configured(tmp_path: Path, monkeypatch) -> None:
    managed_conda_command = tmp_path / "tooling" / "bin" / "micromamba"
    managed_conda_root_prefix = tmp_path / "tooling" / "micromamba-root"
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
    )
    ensure_runtime_layout(cfg)
    managed_conda_command.parent.mkdir(parents=True, exist_ok=True)
    managed_conda_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (Path(cfg.release_dir) / "workflow" / "envs").mkdir(parents=True, exist_ok=True)
    (Path(cfg.release_dir) / "workflow" / "scripts").mkdir(parents=True, exist_ok=True)
    (Path(cfg.release_dir) / "workflow" / "Snakefile").write_text("rule all:\n  input: 'done.txt'\n", encoding="utf-8")
    (Path(cfg.release_dir) / "workflow" / "envs" / "base.yaml").write_text("channels: [conda-forge]\ndependencies: [python=3.12]\n", encoding="utf-8")

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

    run_snakemake_execution(
        cfg,
        run_id="run_phase2_managed_conda",
        request_id="req_phase2_managed_conda",
        run_spec={"pipelineId": "taxonomy-v1", "projectId": "proj_demo", "inputs": []},
    )

    assert len(calls) == 2
    for call in calls:
        env = call["env"]
        assert isinstance(env, dict)
        assert env["H2OMETA_MANAGED_CONDA_COMMAND"] == str(managed_conda_command)
        assert env["MAMBA_ROOT_PREFIX"] == str(managed_conda_root_prefix)
        assert env["PATH"].split(os.pathsep)[0] == str(managed_conda_command.parent)


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
            server_record={"token_ref": "runner://srv_demo", "service_port": 8876},
        )
    except RemoteRunnerManagerError as exc:
        assert "SSH transport is not active" in str(exc)
    else:
        raise AssertionError("tunnel setup errors should be normalized")


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
            if "tar -xzf" in cmd:
                return 0, "", ""
            if "ensure_runtime_layout" in cmd:
                return 0, "", ""
            if "bash /home/tester/.h2ometa/runner/current/start_service.sh" in cmd:
                raise RuntimeError("service failed to start")
            return 0, "", ""

        def upload(self, local: str, remote: str) -> None:
            return None

    fake_ssh = FakeSSH()

    with patch.object(manager, "_bundle_builder", SimpleNamespace(build=lambda version: FakeBundle())), patch.object(
        manager, "_runtime_packager", SimpleNamespace(build=lambda *args, **kwargs: FakeRuntimeArtifact())
    ), patch("core.remote_runner.manager.store_runner_token") as store_token:
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


def test_bootstrap_fails_fast_when_remote_dependency_install_returns_nonzero(monkeypatch) -> None:
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
            if "micro.mamba.pm/api/micromamba/linux-64/latest" in cmd:
                return 0, "", ""
            if "mkdir -p" in cmd:
                return 0, "", ""
            if "tar -xzf" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            return None

    fake_ssh = FakeSSH()

    with patch.object(manager, "_bundle_builder", SimpleNamespace(build=lambda version: FakeBundle())), patch.object(
        manager, "_runtime_packager", SimpleNamespace(build=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("build runtime artifact: pip install failed")))
    ), patch("core.remote_runner.manager.store_runner_token") as store_token:
        try:
            manager.bootstrap(
                server_id="srv_test",
                server={"label": "demo"},
                ssh_service=fake_ssh,
                server_record={},
            )
        except RemoteRunnerManagerError as exc:
            assert "pip install failed" in str(exc)
            assert "build runtime artifact" in str(exc)
        else:
            raise AssertionError("bootstrap should fail when local runtime artifact build exits non-zero")

    store_token.assert_not_called()


def test_bootstrap_fails_fast_when_managed_workflow_runtime_install_fails(monkeypatch) -> None:
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
            if "micro.mamba.pm/api/micromamba/linux-64/latest" in cmd:
                return 1, "", "curl or wget is required to install managed micromamba"
            if "mkdir -p" in cmd:
                return 0, "", ""
            if "tar -xzf" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            return None

    with patch.object(manager, "_bundle_builder", SimpleNamespace(build=lambda version: FakeBundle())), patch.object(
        manager, "_runtime_packager", SimpleNamespace(build=lambda *args, **kwargs: FakeRuntimeArtifact())
    ), patch("core.remote_runner.manager.store_runner_token") as store_token:
        try:
            manager.bootstrap(
                server_id="srv_test",
                server={"label": "demo"},
                ssh_service=FakeSSH(),
                server_record={},
            )
        except RemoteRunnerManagerError as exc:
            assert "install managed workflow runtime" in str(exc)
            assert "curl or wget is required" in str(exc)
        else:
            raise AssertionError("bootstrap should fail when managed workflow runtime install fails")

    store_token.assert_not_called()


def test_bootstrap_auto_installs_managed_micromamba_when_host_runtime_is_missing(monkeypatch) -> None:
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
            if "micro.mamba.pm/api/micromamba/linux-64/latest" in cmd:
                return 0, "", ""
            if "ensure_runtime_layout" in cmd:
                return 0, "", ""
            if "bash /home/tester/.h2ometa/runner/current/start_service.sh" in cmd:
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

    with patch.object(manager, "_bundle_builder", SimpleNamespace(build=lambda version: FakeBundle())), patch.object(
        manager, "_runtime_packager", SimpleNamespace(build=lambda *args, **kwargs: FakeRuntimeArtifact())
    ), patch("core.remote_runner.manager.RemoteRunnerHttpClient", FakeClient), patch(
        "core.remote_runner.manager.store_runner_token", lambda **kwargs: "runner://srv_test"
    ):
        result = manager.bootstrap(
            server_id="srv_test",
            server={"label": "demo"},
            ssh_service=FakeSSH(),
            server_record={},
        )

    metadata = result["bootstrap_metadata"]
    assert metadata["tooling"]["workflow_runtime"]["source"] == "managed"
    assert metadata["tooling"]["workflow_runtime"]["provider"] == "micromamba"
    assert metadata["tooling"]["workflow_runtime"]["command"] == "/home/tester/.h2ometa/runner/shared/tools/bin/conda"
    assert metadata["tooling"]["workflow_runtime"]["root_prefix"] == "/home/tester/.h2ometa/runner/shared/tools/micromamba-root"
    assert metadata["tooling"]["runner_runtime"]["source"] == "bundled"
    assert metadata["tooling"]["runner_runtime"]["artifact"] == "runtime1234"
    assert metadata["tooling"]["runner_runtime"]["environment"] == "/home/tester/.h2ometa/runner/releases/0.1.0-control-plane/runner-env"
    assert metadata["tooling"]["runner_runtime"]["python"] == "/home/tester/.h2ometa/runner/releases/0.1.0-control-plane/runner-env/bin/python"
    assert any("micro.mamba.pm/api/micromamba/linux-64/latest" in cmd for cmd in executed)
    assert not any("python3 -m venv" in cmd for cmd in executed)
    assert not any("runner-env/bin/python -m pip install -r" in cmd for cmd in executed)


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
            if "micro.mamba.pm/api/micromamba/linux-64/latest" in cmd:
                return 0, "", ""
            if "ensure_runtime_layout" in cmd:
                return 0, "", ""
            if "systemctl --user restart h2ometa-remote.service" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            return None

        def ensure_local_tunnel(self, *args, **kwargs):
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

    with patch.object(manager, "_bundle_builder", SimpleNamespace(build=lambda version: FakeBundle())), patch.object(
        manager, "_runtime_packager", SimpleNamespace(build=lambda *args, **kwargs: FakeRuntimeArtifact())
    ), patch("core.remote_runner.manager.RemoteRunnerHttpClient", FakeClient), patch(
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


def test_bootstrap_succeeds_without_system_python3_when_managed_runtime_is_available(monkeypatch) -> None:
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
            if "micro.mamba.pm/api/micromamba/linux-64/latest" in cmd:
                return 0, "", ""
            if "ensure_runtime_layout" in cmd:
                return 0, "", ""
            if "bash /home/tester/.h2ometa/runner/current/start_service.sh" in cmd:
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

    with patch.object(manager, "_bundle_builder", SimpleNamespace(build=lambda version: FakeBundle())), patch.object(
        manager, "_runtime_packager", SimpleNamespace(build=lambda *args, **kwargs: FakeRuntimeArtifact())
    ), patch("core.remote_runner.manager.RemoteRunnerHttpClient", FakeClient), patch(
        "core.remote_runner.manager.store_runner_token", lambda **kwargs: "runner://srv_test"
    ):
        result = manager.bootstrap(
            server_id="srv_test",
            server={"label": "demo"},
            ssh_service=FakeSSH(),
            server_record={},
        )

    assert result["bootstrap_metadata"]["tooling"]["runner_runtime"]["python"].endswith("/releases/0.1.0-control-plane/runner-env/bin/python")
