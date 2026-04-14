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
    service_locator = SimpleNamespace(plugin_registry=SimpleNamespace(), ssh_service=_DummySSH())
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
