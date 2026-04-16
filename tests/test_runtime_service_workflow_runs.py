from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.app_runtime.service import RuntimeService, RuntimeServiceError
from core.data.project_manager import ProjectManager


class _DummySSH:
    is_connected = True

    def run(self, cmd: str, timeout: int = 0):  # pragma: no cover - backend fakes do not use this
        return (0, "", "")


class _FakeTerminalSession:
    def __init__(self, session_id: str = "term_test") -> None:
        self.session_id = session_id
        self.closed = False
        self.connected = True
        self.input_enabled = True
        self.message = ""
        self.output = "ready\\n"
        self.resizes: list[tuple[int, int]] = []

    def snapshot(self, cursor: int = 0) -> dict[str, object]:
        safe_cursor = max(0, min(cursor, len(self.output)))
        return {
            "session_id": self.session_id,
            "cursor": len(self.output),
            "output": self.output[safe_cursor:],
            "connected": self.connected,
            "input_enabled": self.input_enabled,
            "closed": self.closed,
            "message": self.message,
            "created_at": 0.0,
            "closed_at": None,
        }

    def send(self, data: str) -> None:
        if self.closed or not self.input_enabled:
            raise RuntimeError("terminal closed")
        self.output += data

    def resize(self, *, cols: int, rows: int) -> None:
        if self.closed or not self.input_enabled:
            raise RuntimeError("terminal closed")
        self.resizes.append((cols, rows))

    def close(self, *, message: str = "终端会话已结束", connected: bool = False) -> None:
        self.closed = True
        self.connected = connected
        self.input_enabled = False
        self.message = message


class _DummySSHWithTerminal(_DummySSH):
    def __init__(self) -> None:
        self.created_sessions: list[_FakeTerminalSession] = []

    def open_terminal_session(self, *, cols: int = 120, rows: int = 28) -> _FakeTerminalSession:
        assert cols == 120
        assert rows == 28
        session = _FakeTerminalSession(session_id=f"term_{len(self.created_sessions) + 1}")
        self.created_sessions.append(session)
        return session


class _FakePluginRegistry:
    def __init__(self) -> None:
        self._descriptors = {
            "fastp": {
                "id": "fastp",
                "name": "fastp",
                "workflow_support": {
                    "support_level": "Production Ready",
                    "workflow_ready": True,
                    "validation_errors": [],
                    "runtime": {
                        "container": "quay.io/biocontainers/fastp:0.23.4",
                        "conda": "bioconda::fastp=0.23.4",
                        "conda_env_name": "fastp_env",
                    },
                },
            },
            "unknown_sample_detection": {
                "id": "unknown_sample_detection",
                "name": "Unknown sample",
                "workflow_support": {
                    "support_level": "Conda Only",
                    "workflow_ready": True,
                    "validation_errors": [],
                    "runtime": {
                        "container": "",
                        "conda": "bioconda::fastp=0.23.4 hostile=1.1.0 centrifuge=1.0.4",
                        "conda_env_name": "unknown_sample_detection_env",
                    },
                },
            },
        }

    def get_descriptor(self, tool_id: str) -> dict[str, object]:
        if tool_id not in self._descriptors:
            raise KeyError(tool_id)
        return self._descriptors[tool_id]


class _FakeBackend:
    def __init__(self) -> None:
        self.submit_calls = 0
        self.query_calls = 0
        self.cancel_calls = 0
        self.artifact_calls = 0
        self.query_stage = "completed"

    def submit_prepared_run(self, **_: object) -> dict[str, str]:
        self.submit_calls += 1
        return {
            "backend_kind": "fake_backend",
            "launcher_pid": "321",
            "scheduler_job_id": "",
        }

    def query_run(self, **_: object) -> dict[str, str]:
        self.query_calls += 1
        return {
            "stage": self.query_stage,
            "log_tail": "remote line",
            "launcher_pid": "321",
            "nextflow_pid": "654",
        }

    def cancel_run(self, **_: object) -> dict[str, str]:
        self.cancel_calls += 1
        return {
            "stage": "cancelled",
            "launcher_pid": "321",
            "nextflow_pid": "654",
        }

    def collect_artifacts(self, **_: object) -> list[dict[str, object]]:
        self.artifact_calls += 1
        return [
            {
                "name": "report.html",
                "remote_path": "/remote/project/workflow_runs/run_fake/output/report.html",
                "local_path": "/tmp/local_run/artifacts/report.html",
                "available": True,
                "kind": "report",
            }
        ]


@pytest.fixture()
def runtime(tmp_path: Path) -> RuntimeService:
    projects_root = tmp_path / "projects"
    index_path = tmp_path / "projects.json"
    pm = ProjectManager(projects_root=projects_root, index_path=index_path)
    service_locator = SimpleNamespace(plugin_registry=_FakePluginRegistry(), ssh_service=_DummySSH())
    runtime = RuntimeService(project_manager=pm, service_locator=service_locator)
    runtime._initialized = True
    project_id = pm.create_project("workflow runtime test")
    pm.open_project(project_id)
    runtime.create_task(project_id=project_id, title="Task A", description="workflow task")
    task_id = runtime.list_tasks(project_id=project_id)[0]["task_id"]
    runtime._test_project_id = project_id  # type: ignore[attr-defined]
    runtime._test_task_id = task_id  # type: ignore[attr-defined]
    yield runtime
    pm.close()


def _workflow_payload() -> dict[str, object]:
    return {
        "workflow_id": "wf_phase1",
        "name": "Phase1 workflow",
        "version": "0.1.0",
        "nodes": [{"node_id": "n1", "tool_id": "fastp", "label": "FastP", "params": {}}],
        "edges": [],
        "params_schema": {},
    }


def _launch_payload() -> dict[str, object]:
    return {
        "profile": {
            "profile_id": "personal_conda",
            "server_id": "current",
            "profile_kind": "personal_conda",
            "executor": "local",
            "packaging_mode": "conda",
            "container_runtime": "",
            "work_dir": "",
            "output_dir": "",
            "cache_dir": "",
        },
        "params": {},
        "data_refs": [],
        "resume": True,
    }


def test_terminal_session_lifecycle_and_disconnect_preserves_history(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    index_path = tmp_path / "projects.json"
    pm = ProjectManager(projects_root=projects_root, index_path=index_path)
    ssh = _DummySSHWithTerminal()
    service_locator = SimpleNamespace(plugin_registry=_FakePluginRegistry(), ssh_service=ssh)
    runtime = RuntimeService(project_manager=pm, service_locator=service_locator)
    runtime._initialized = True

    created = runtime.create_terminal_session(cols=120, rows=28)
    assert created["session_id"] == "term_1"
    assert created["output"] == "ready\\n"

    accepted = runtime.send_terminal_input(session_id="term_1", data="pwd\\n")
    assert accepted == {"session_id": "term_1", "accepted": True}

    resized = runtime.resize_terminal_session(session_id="term_1", cols=132, rows=40)
    assert resized == {"session_id": "term_1", "accepted": True, "cols": 132, "rows": 40}
    assert ssh.created_sessions[0].resizes == [(132, 40)]

    session = runtime.get_terminal_session(session_id="term_1")
    update = session.snapshot(cursor=len("ready\\n"))
    assert update["output"] == "pwd\\n"
    assert update["input_enabled"] is True

    disconnected = runtime.disconnect_ssh()
    assert disconnected["connected"] is False

    snapshot = runtime.get_terminal_session(session_id="term_1").snapshot(cursor=0)
    assert snapshot["output"] == "ready\\npwd\\n"
    assert snapshot["closed"] is True
    assert snapshot["connected"] is False
    assert snapshot["input_enabled"] is False
    assert snapshot["message"] == "SSH 已断开，终端会话已结束"

    pm.close()


def test_create_run_persists_snapshot_execution_and_workflow_run(runtime: RuntimeService, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _FakeBackend()
    monkeypatch.setattr("core.app_runtime.workflow_runtime_ops.compile_workflow_bundle", lambda *args, **kwargs: {"bundle_id": "bundle_1", "files": {"main.nf": "process A"}})
    monkeypatch.setattr("core.app_runtime.workflow_runtime_ops.create_workflow_backend", lambda profile: backend)
    runtime.update_task(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
        patch={"workflow": _workflow_payload()},
    )

    item = runtime.create_run(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
        launch=_launch_payload(),
    )

    assert item["task_id"] == runtime._test_task_id  # type: ignore[attr-defined]
    assert item["execution_id"].startswith("exec_")
    assert item["workflow_snapshot_id"].startswith("wsnap_")
    assert item["snapshot_hash"]
    assert item["snapshot_payload_json"]["workflow_id"] == "wf_phase1"
    execution_row = runtime._project_manager.db.execute(
        "SELECT task_id, status FROM executions WHERE execution_id = ?",
        (item["execution_id"],),
    ).fetchone()
    assert execution_row is not None
    assert execution_row["task_id"] == runtime._test_task_id  # type: ignore[index,attr-defined]
    snapshot_row = runtime._project_manager.db.execute(
        "SELECT task_id, workflow_id FROM workflow_snapshots WHERE workflow_snapshot_id = ?",
        (item["workflow_snapshot_id"],),
    ).fetchone()
    assert snapshot_row is not None
    assert snapshot_row["workflow_id"] == "wf_phase1"
    run_row = runtime._project_manager.db.execute(
        "SELECT execution_id, task_id, workflow_snapshot_id FROM workflow_runs WHERE run_id = ?",
        (item["run_id"],),
    ).fetchone()
    assert run_row is not None
    assert run_row["execution_id"] == item["execution_id"]
    assert backend.submit_calls == 1


def test_list_runs_ignores_legacy_run_record_files(runtime: RuntimeService) -> None:
    project_dir = runtime._project_manager.current_project_dir
    assert project_dir is not None
    legacy_dir = project_dir / "workflow_runs" / "run_legacy"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "run_record.json").write_text(json.dumps({"run_id": "run_legacy", "project_id": runtime._test_project_id}), encoding="utf-8")  # type: ignore[attr-defined]

    rows = runtime.list_runs(project_id=runtime._test_project_id)  # type: ignore[attr-defined]

    assert rows == []


def test_get_run_updates_sqlite_from_remote_status(runtime: RuntimeService, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _FakeBackend()
    monkeypatch.setattr("core.app_runtime.workflow_runtime_ops.compile_workflow_bundle", lambda *args, **kwargs: {"bundle_id": "bundle_2", "files": {"main.nf": "process B"}})
    monkeypatch.setattr("core.app_runtime.workflow_runtime_ops.create_workflow_backend", lambda profile: backend)
    runtime.update_task(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
        patch={"workflow": _workflow_payload()},
    )
    created = runtime.create_run(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
        launch=_launch_payload(),
    )
    runtime._workflow_backend_for_row = lambda row: backend  # type: ignore[method-assign]

    item = runtime.get_run(project_id=runtime._test_project_id, run_id=created["run_id"])  # type: ignore[attr-defined]

    assert item["status"] == "completed"
    execution_row = runtime._project_manager.db.execute(
        "SELECT status FROM executions WHERE execution_id = ?",
        (created["execution_id"],),
    ).fetchone()
    assert execution_row is not None
    assert execution_row["status"] == "completed"


def test_cancel_run_syncs_execution_status(runtime: RuntimeService, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _FakeBackend()
    monkeypatch.setattr("core.app_runtime.workflow_runtime_ops.compile_workflow_bundle", lambda *args, **kwargs: {"bundle_id": "bundle_3", "files": {"main.nf": "process C"}})
    monkeypatch.setattr("core.app_runtime.workflow_runtime_ops.create_workflow_backend", lambda profile: backend)
    runtime.update_task(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
        patch={"workflow": _workflow_payload()},
    )
    created = runtime.create_run(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
        launch=_launch_payload(),
    )
    runtime._workflow_backend_for_row = lambda row: backend  # type: ignore[method-assign]

    item = runtime.cancel_run(project_id=runtime._test_project_id, run_id=created["run_id"])  # type: ignore[attr-defined]

    assert item["status"] == "cancelled"
    execution_row = runtime._project_manager.db.execute(
        "SELECT status, error FROM executions WHERE execution_id = ?",
        (created["execution_id"],),
    ).fetchone()
    assert execution_row is not None
    assert execution_row["status"] == "failed"
    assert "cancelled" in str(execution_row["error"]).lower()


def test_create_run_requires_task_id(runtime: RuntimeService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.app_runtime.workflow_runtime_ops.compile_workflow_bundle", lambda *args, **kwargs: {"bundle_id": "bundle_4", "files": {}})
    monkeypatch.setattr("core.app_runtime.workflow_runtime_ops.create_workflow_backend", lambda profile: _FakeBackend())

    with pytest.raises(RuntimeServiceError, match="task_id is required"):
        runtime.create_run(
            project_id=runtime._test_project_id,  # type: ignore[attr-defined]
            task_id="",
            launch=_launch_payload(),
        )


def test_create_run_requires_current_snapshot(runtime: RuntimeService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.app_runtime.workflow_runtime_ops.compile_workflow_bundle", lambda *args, **kwargs: {"bundle_id": "bundle_5", "files": {}})
    monkeypatch.setattr("core.app_runtime.workflow_runtime_ops.create_workflow_backend", lambda profile: _FakeBackend())

    with pytest.raises(RuntimeServiceError, match="missing current workflow snapshot"):
        runtime.create_run(
            project_id=runtime._test_project_id,  # type: ignore[attr-defined]
            task_id=runtime._test_task_id,  # type: ignore[attr-defined]
            launch=_launch_payload(),
        )


def test_put_and_get_task_workflow_round_trip(runtime: RuntimeService) -> None:
    runtime.put_task_workflow(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
        workflow=_workflow_payload(),
    )

    item = runtime.get_task_workflow(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
    )

    assert item["task_id"] == runtime._test_task_id  # type: ignore[attr-defined]
    assert item["workflow"]["workflow_id"] == "wf_phase1"
    assert item["workflow_hash"]


def test_task_scoped_runs_results_and_workspace(runtime: RuntimeService, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _FakeBackend()
    monkeypatch.setattr("core.app_runtime.workflow_runtime_ops.compile_workflow_bundle", lambda *args, **kwargs: {"bundle_id": "bundle_6", "files": {"main.nf": "process D"}})
    monkeypatch.setattr("core.app_runtime.workflow_runtime_ops.create_workflow_backend", lambda profile: backend)
    monkeypatch.setattr(
        runtime,
        "get_ssh_preflight",
        lambda: {
            "ok": True,
            "recommended_profile": "personal_conda",
            "recommended_profile_details": {"profile_id": "personal_conda"},
            "runtime_capabilities": {"nextflow": {"status": "ok"}},
            "checks": [],
            "failures": [],
            "warnings": [],
        },
    )
    runtime.put_task_workflow(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
        workflow=_workflow_payload(),
    )
    created = runtime.create_task_run(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
        launch=_launch_payload(),
    )
    runtime._workflow_backend_for_row = lambda row: backend  # type: ignore[method-assign]

    task_runs = runtime.list_task_runs(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
    )
    assert len(task_runs) == 1
    assert task_runs[0]["run_id"] == created["run_id"]

    fetched = runtime.get_task_run(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
        run_id=created["run_id"],
    )
    assert fetched["task_id"] == runtime._test_task_id  # type: ignore[attr-defined]

    artifacts = runtime.get_run_artifacts(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        run_id=created["run_id"],
    )
    assert len(artifacts) == 1

    results = runtime.list_task_results(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
    )
    assert len(results) == 1
    assert results[0]["run_id"] == created["run_id"]
    assert results[0]["content_url"].endswith(f"/results/{results[0]['result_id']}/content")

    summary = runtime.get_task_results_summary(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
    )
    assert summary["total"] == 1
    assert summary["latest_run_id"] == created["run_id"]
    assert summary["viewer_kinds"] == ["html"]
    assert summary["artifact_groups"]["Reports"] == 1

    result_item = runtime.get_task_result(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
        result_id=results[0]["result_id"],
    )
    assert result_item["result_id"] == results[0]["result_id"]

    result_content = runtime.get_task_result_content(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
        result_id=results[0]["result_id"],
    )
    assert result_content["result_id"] == results[0]["result_id"]

    workspace = runtime.get_task_workspace(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
    )
    assert workspace["task"]["task_id"] == runtime._test_task_id  # type: ignore[attr-defined]
    assert workspace["workflow_snapshot"]["task_id"] == runtime._test_task_id  # type: ignore[attr-defined]
    assert workspace["runs_summary"]["total"] == 1
    assert workspace["results_summary"]["total"] == 1
    assert workspace["compatibility"]["selected_profile"]["profile_id"] == "personal_conda"


def test_task_workflow_compatibility_uses_backend_selection_and_falls_back_to_conda(runtime: RuntimeService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runtime,
        "get_ssh_preflight",
        lambda: {
            "ok": True,
            "recommended_profile": "personal_docker",
            "recommended_profile_details": {
                "profile_id": "personal_docker",
                "server_id": "current",
                "profile_kind": "personal_docker",
                "executor": "local",
                "packaging_mode": "container",
                "container_runtime": "docker",
                "work_dir": "~/.bioflow/runs/work",
                "output_dir": "~/.bioflow/runs/output",
                "cache_dir": "~/.bioflow/cache/containers",
            },
            "supported_profile_kinds": ["personal_docker", "personal_conda"],
            "runtime_capabilities": {
                "docker": {"available": True},
                "podman": {"available": False},
                "apptainer": {"available": False},
                "micromamba": {"available": False},
                "conda": {"available": True},
                "sbatch": {"available": False},
                "java": {"available": True, "version": "21"},
                "nextflow": {"available": True, "version": "24.10.0"},
            },
            "checks": [],
            "failures": [],
            "warnings": [],
        },
    )
    runtime.put_task_workflow(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
        workflow={
            "workflow_id": "wf_conda_fallback",
            "name": "Conda fallback workflow",
            "version": "0.1.0",
            "nodes": [{"node_id": "n1", "tool_id": "unknown_sample_detection", "label": "Unknown sample", "params": {}}],
            "edges": [],
            "params_schema": {},
        },
    )

    item = runtime.get_task_workflow_compatibility(
        project_id=runtime._test_project_id,  # type: ignore[attr-defined]
        task_id=runtime._test_task_id,  # type: ignore[attr-defined]
    )

    assert item["compatible"] is True
    assert item["selected_profile"]["profile_id"] == "personal_conda"
    assert "改用 personal_conda" in item["selection_reason"]
    assert len(item["server_profiles"]) == 2
    assert any(reason.endswith("缺少 runtime.container") for reason in item["workflow_profiles"][0]["incompatibility_reasons"])


def test_get_ssh_preflight_distinguishes_installed_vs_usable_container_runtime(runtime: RuntimeService, monkeypatch: pytest.MonkeyPatch) -> None:
    caps = SimpleNamespace(
        arch="x86_64",
        has_bash=True,
        has_curl=True,
        has_wget=False,
        has_screen=True,
        has_sha256sum=True,
        has_java=True,
        java_version="openjdk 17",
        has_nextflow=True,
        nextflow_version="24.10.0",
        has_docker=True,
        has_podman=False,
        has_apptainer=False,
        has_micromamba=True,
        has_conda=False,
        has_sbatch=False,
        free_disk_gb=42.0,
        home_writable=True,
        bootstrap_failures=lambda min_free_disk_gb=5.0: [],
        warnings=lambda: [],
    )

    monkeypatch.setattr("core.app_runtime.service.probe_preflight", lambda _run: caps)
    monkeypatch.setattr(
        "core.app_runtime.service.resolve_remote_java",
        lambda _run: {
            "available": True,
            "usable": True,
            "supported": True,
            "version": "openjdk 17",
            "path": "/usr/bin/java",
            "home": "/usr/lib/jvm/java-17-openjdk-amd64",
            "message": "已检测到 Java，可用于运行 Nextflow",
        },
    )
    monkeypatch.setattr(
        "core.app_runtime.service.resolve_remote_nextflow",
        lambda _run: {
            "available": True,
            "usable": False,
            "version": "24.10.0",
            "path": "/home/tester/.local/bin/nextflow",
            "command": "/home/tester/.local/bin/nextflow",
            "message": "已检测到 Nextflow，但当前不可正常调用：health check failed",
        },
    )

    def fake_runtime_ok(command: str) -> bool:
        if "docker ps" in command:
            return False
        return True

    monkeypatch.setattr(runtime, "_remote_runtime_ok", fake_runtime_ok)

    item = runtime.get_ssh_preflight()

    docker_cap = item["runtime_capabilities"]["docker"]
    assert docker_cap["available"] is True
    assert docker_cap["usable"] is False
    assert item["recommended_profile"] == "personal_conda"
    assert "personal_docker" not in item["supported_profile_kinds"]
    docker_check = next(check for check in item["checks"] if check["key"] == "docker")
    assert docker_check["status"] == "warn"
    assert "当前用户不可直接使用" in docker_check["message"]
    nextflow_check = next(check for check in item["checks"] if check["key"] == "nextflow")
    assert nextflow_check["status"] == "warn"
    assert "当前不可正常调用" in nextflow_check["message"]


def test_get_ssh_preflight_blocks_when_java_is_missing_even_if_docker_and_nextflow_are_usable(
    runtime: RuntimeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    caps = SimpleNamespace(
        arch="x86_64",
        has_bash=True,
        has_curl=True,
        has_wget=False,
        has_screen=True,
        has_sha256sum=True,
        has_java=False,
        java_version="",
        has_nextflow=True,
        nextflow_version="24.10.0",
        has_docker=True,
        has_podman=False,
        has_apptainer=False,
        has_micromamba=False,
        has_conda=False,
        has_sbatch=False,
        free_disk_gb=42.0,
        home_writable=True,
        bootstrap_failures=lambda min_free_disk_gb=5.0: [],
        runtime_failures=lambda: ["远端缺少 Java，无法运行 Nextflow"],
        warnings=lambda: [],
    )

    monkeypatch.setattr("core.app_runtime.service.probe_preflight", lambda _run: caps)
    monkeypatch.setattr(
        "core.app_runtime.service.resolve_remote_java",
        lambda _run: {
            "available": False,
            "usable": False,
            "supported": False,
            "version": "",
            "path": "",
            "home": "",
            "message": "未检测到 Java，无法运行 Nextflow",
        },
    )
    monkeypatch.setattr(
        "core.app_runtime.service.resolve_remote_nextflow",
        lambda _run: {
            "available": True,
            "usable": True,
            "version": "24.10.0",
            "path": "/home/zyserver/bin/nextflow",
            "command": "/home/zyserver/bin/nextflow",
            "source": "path",
            "message": "已检测到 Nextflow，可直接使用",
        },
    )
    monkeypatch.setattr(runtime, "_remote_runtime_ok", lambda command: "docker ps" in command)

    item = runtime.get_ssh_preflight()

    assert item["ok"] is False
    assert item["recommended_profile"] == "personal_docker"
    assert item["supported_profile_kinds"] == ["personal_docker"]
    assert "远端缺少 Java，无法运行 Nextflow" in item["failures"]
    java_check = next(check for check in item["checks"] if check["key"] == "java")
    assert java_check["status"] == "fail"


def test_get_ssh_preflight_blocks_when_probe_and_resolved_java_disagree(
    runtime: RuntimeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    caps = SimpleNamespace(
        arch="x86_64",
        has_bash=True,
        has_curl=True,
        has_wget=False,
        has_screen=True,
        has_sha256sum=True,
        has_java=True,
        java_version="openjdk version \"17.0.14\" 2025-10-15",
        has_nextflow=True,
        nextflow_version="24.10.0",
        has_docker=True,
        has_podman=False,
        has_apptainer=False,
        has_micromamba=False,
        has_conda=False,
        has_sbatch=False,
        free_disk_gb=42.0,
        home_writable=True,
        bootstrap_failures=lambda min_free_disk_gb=5.0: [],
        runtime_failures=lambda: [],
        warnings=lambda: [],
    )

    monkeypatch.setattr("core.app_runtime.service.probe_preflight", lambda _run: caps)
    monkeypatch.setattr(
        "core.app_runtime.service.resolve_remote_java",
        lambda _run: {
            "available": False,
            "usable": False,
            "supported": False,
            "version": "",
            "path": "",
            "home": "",
            "message": "未检测到 Java，无法运行 Nextflow",
        },
    )
    monkeypatch.setattr(
        "core.app_runtime.service.resolve_remote_nextflow",
        lambda _run: {
            "available": True,
            "usable": True,
            "version": "24.10.0",
            "path": "/home/zyserver/bin/nextflow",
            "command": "/home/zyserver/bin/nextflow",
            "source": "path",
            "message": "已检测到 Nextflow，可直接使用",
        },
    )
    monkeypatch.setattr(runtime, "_remote_runtime_ok", lambda command: "docker ps" in command)

    item = runtime.get_ssh_preflight()

    assert item["ok"] is False
    assert "未检测到 Java，无法运行 Nextflow" in item["failures"]


def test_install_remote_env_supports_docker_runtime_assist(runtime: RuntimeService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.app_runtime.service.probe_preflight",
        lambda _run: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "core.app_runtime.service.submit_docker_runtime_bootstrap",
        lambda _run: {"job_id": "h2o_docker_runtime_bootstrap", "task_dir": "~/.bioflow/docker_runtime_bootstrap"},
    )

    item = runtime.install_remote_env(target="docker_runtime")

    assert item["target"] == "docker_runtime"
    assert item["job_id"] == "h2o_docker_runtime_bootstrap"
    assert "Docker 协助安装任务" in item["message"]


def test_install_remote_env_rejects_workflow_runtime_when_java_is_unsupported(
    runtime: RuntimeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "core.app_runtime.service.probe_preflight",
        lambda _run: SimpleNamespace(
            has_java=True,
            has_supported_java=False,
            java_version="11.0.22",
            has_nextflow=False,
            nextflow_version="",
            has_docker=False,
            has_podman=False,
            has_apptainer=False,
            has_micromamba=False,
            has_conda=False,
            has_sbatch=False,
        ),
    )

    with pytest.raises(RuntimeServiceError, match="Java .*17-25"):
        runtime.install_remote_env(target="workflow_runtime", profile_kind="personal_conda")


def test_install_remote_env_rejects_docker_runtime_assist_when_java_is_unsupported(
    runtime: RuntimeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "core.app_runtime.service.probe_preflight",
        lambda _run: SimpleNamespace(
            has_java=True,
            has_supported_java=False,
            java_version="11.0.22",
            has_nextflow=False,
            nextflow_version="",
            has_docker=False,
            has_podman=False,
            has_apptainer=False,
            has_micromamba=False,
            has_conda=False,
            has_sbatch=False,
        ),
    )

    with pytest.raises(RuntimeServiceError, match="Java .*17-25"):
        runtime.install_remote_env(target="docker_runtime")


def test_get_remote_env_install_status_supports_docker_runtime_assist(runtime: RuntimeService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.app_runtime.service.read_docker_bootstrap_status",
        lambda _run, task_dir: (
            {"status": "DONE", "exit_code": "0", "heartbeat": "123", "pid": "456", "log_preview": "Docker 已安装"},
            False,
            "Docker 已安装",
        ),
    )

    item = runtime.get_remote_env_install_status(job_id="h2o_docker_runtime_bootstrap")

    assert item["status"] == "done"
    assert item["ok"] is True
    assert item["progress"]["kind"] == "docker_runtime"


def test_get_remote_env_install_status_supports_workflow_bootstrap_jobs(
    runtime: RuntimeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "core.app_runtime.service.read_workflow_bootstrap_status",
        lambda _run, task_dir: (
            {"status": "RUNNING", "exit_code": "", "heartbeat": "123", "pid": "456", "log_preview": "准备 Nextflow"},
            True,
            "准备 Nextflow",
        ),
    )

    item = runtime.get_remote_env_install_status(job_id="h2o_workflow_bootstrap_personal_docker")

    assert item["status"] == "running"
    assert item["done"] is False
    assert item["progress"]["profile_kind"] == "personal_docker"
    assert item["progress"]["pid"] == "456"


def test_get_remote_env_install_status_rejects_empty_workflow_bootstrap_profile(runtime: RuntimeService) -> None:
    with pytest.raises(RuntimeServiceError, match="invalid workflow bootstrap job_id"):
        runtime.get_remote_env_install_status(job_id="h2o_workflow_bootstrap_")
