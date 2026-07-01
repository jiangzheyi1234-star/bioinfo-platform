from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from apps.remote_runner import trigger_readiness_watcher as watcher
from apps.remote_runner.api_models import WorkflowTriggerCreateRequest
from apps.remote_runner.databases import add_reference_database
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.trigger_readiness_read_model import get_workflow_trigger_readiness_observation_from_storage
from apps.remote_runner.trigger_readiness_watcher import run_workflow_trigger_readiness_watcher_once
from apps.remote_runner.trigger_readiness_watcher_storage import fetch_readiness_observation
from apps.remote_runner.trigger_service import create_workflow_trigger_from_request
from apps.remote_runner.trigger_storage import list_workflow_trigger_events
from apps.remote_runner.execution_query_storage import list_runs
from tests.helpers.reference_database import make_configured_remote_runner


ROOT = Path(__file__).resolve().parents[1]


def test_readiness_watcher_dispatches_local_path_once_and_skips_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
    watched = tmp_path / "incoming" / "reads.fastq"
    watched.parent.mkdir()
    watched.write_text("@read\nACGT\n+\n!!!!\n", encoding="utf-8")
    trigger = _create_file_trigger(cfg, watched)

    first = run_workflow_trigger_readiness_watcher_once(cfg)
    first_events = list_workflow_trigger_events(cfg, trigger["triggerId"])["items"]
    first_dispatch_audit = list_governance_audit_events(cfg, action="workflow_trigger.dispatch")["items"]
    observation = fetch_readiness_observation(cfg, trigger["triggerId"])
    public_read = get_workflow_trigger_readiness_observation_from_storage(cfg, trigger["triggerId"])
    second = run_workflow_trigger_readiness_watcher_once(cfg)
    second_events = list_workflow_trigger_events(cfg, trigger["triggerId"])["items"]
    second_dispatch_audit = list_governance_audit_events(cfg, action="workflow_trigger.dispatch")["items"]

    assert first["checked"] == 1
    assert first["ready"] == 1
    assert first["submitted"] == 1
    assert first["unchanged"] == 0
    assert len(first_events) == 1
    assert len(list_runs(cfg)) == 1
    assert observation is not None
    assert observation["observedState"] == "ready"
    assert observation["dispatchState"] == "submitted"
    assert observation["triggerEventId"] == first_events[0]["triggerEventId"]
    assert observation["runId"] == first_events[0]["dispatch"]["runId"]
    assert public_read["data"]["schemaVersion"] == "workflow-trigger-readiness-observation.v1"
    public_observation = public_read["data"]["observation"]
    assert public_observation["observedState"] == "ready"
    assert public_observation["dispatchState"] == "submitted"
    assert public_observation["triggerEventId"] == first_events[0]["triggerEventId"]
    assert public_observation["runId"] == first_events[0]["dispatch"]["runId"]
    assert public_observation["observedChecksum"].startswith("sha256:")
    assert public_observation["resourceIdentity"]["type"] == "file"
    assert public_observation["resourceIdentity"]["idPresent"] is True
    assert len(public_observation["resourceIdentity"]["idHash"]) == 64
    assert public_observation["resourceUriPresent"] is True
    assert "resourceId" not in public_observation
    assert "resourceUri" not in public_observation
    assert str(watched) not in repr(public_read)
    assert "file:/incoming/reads.fastq" not in repr(public_read)
    assert first_events[0]["eventType"] == "file.ready"
    assert first_events[0]["payload"]["resource"]["checksum"].startswith("sha256:")
    assert first_events[0]["payload"]["payload"]["watcher"]["pathHash"]
    assert str(watched) not in repr(first_events[0]["payload"]["payload"])
    assert second["checked"] == 1
    assert second["ready"] == 0
    assert second["submitted"] == 0
    assert second["unchanged"] == 1
    assert [item["triggerEventId"] for item in second_events] == [first_events[0]["triggerEventId"]]
    assert len(second_dispatch_audit) == len(first_dispatch_audit)


def test_readiness_watcher_dispatches_changed_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
    watched = tmp_path / "incoming" / "reads.fastq"
    watched.parent.mkdir()
    watched.write_text("first\n", encoding="utf-8")
    trigger = _create_file_trigger(cfg, watched)

    run_workflow_trigger_readiness_watcher_once(cfg)
    watched.write_text("second\n", encoding="utf-8")
    tick = run_workflow_trigger_readiness_watcher_once(cfg)
    events = list_workflow_trigger_events(cfg, trigger["triggerId"])["items"]

    assert tick["ready"] == 1
    assert tick["submitted"] == 1
    assert len(events) == 2
    assert events[0]["payload"]["resource"]["checksum"] != events[1]["payload"]["resource"]["checksum"]


def test_readiness_watcher_waits_for_local_path_stability_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
    watched = tmp_path / "incoming" / "reads.fastq"
    watched.parent.mkdir()
    watched.write_text("new data\n", encoding="utf-8")
    trigger = _create_file_trigger_with_stability(cfg, watched, stability_seconds=3600)

    first = run_workflow_trigger_readiness_watcher_once(cfg)
    first_observation = fetch_readiness_observation(cfg, trigger["triggerId"])

    assert first["checked"] == 1
    assert first["missing"] == 1
    assert first["submitted"] == 0
    assert first_observation["observedState"] == "missing"
    assert list_workflow_trigger_events(cfg, trigger["triggerId"])["items"] == []

    old_mtime = time.time() - 7200
    os.utime(watched, (old_mtime, old_mtime))
    second = run_workflow_trigger_readiness_watcher_once(cfg)
    events = list_workflow_trigger_events(cfg, trigger["triggerId"])["items"]

    assert second["ready"] == 1
    assert second["submitted"] == 1
    assert len(events) == 1
    assert events[0]["payload"]["payload"]["watcher"]["stabilitySeconds"] == 3600
    assert str(watched) not in repr(events[0]["payload"]["payload"])


def test_readiness_observation_read_model_returns_null_before_first_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
    trigger = _create_file_trigger(cfg, tmp_path / "not-observed.fastq")

    public_read = get_workflow_trigger_readiness_observation_from_storage(cfg, trigger["triggerId"])

    assert public_read == {
        "data": {
            "schemaVersion": "workflow-trigger-readiness-observation.v1",
            "triggerId": trigger["triggerId"],
            "sourceType": "file",
            "observation": None,
        }
    }


def test_readiness_watcher_dispatches_database_registry_record_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
    database_path = tmp_path / "db" / "kraken2"
    database_path.mkdir(parents=True)
    database = _add_available_database(cfg, database_path, version="2026.06", checksum="a" * 64)
    trigger = _create_database_ready_trigger(cfg, database["id"])

    first = run_workflow_trigger_readiness_watcher_once(cfg)
    first_events = list_workflow_trigger_events(cfg, trigger["triggerId"])["items"]
    second = run_workflow_trigger_readiness_watcher_once(cfg)
    second_events = list_workflow_trigger_events(cfg, trigger["triggerId"])["items"]

    assert first["checked"] == 1
    assert first["ready"] == 1
    assert first["submitted"] == 1
    assert second["unchanged"] == 1
    assert len(first_events) == 1
    assert [item["triggerEventId"] for item in second_events] == [first_events[0]["triggerEventId"]]
    payload = first_events[0]["payload"]
    assert payload["resource"]["type"] == "database"
    assert payload["resource"]["id"] == database["id"]
    assert payload["resource"]["version"].startswith("database:")
    assert payload["resource"]["checksum"] == f"sha256:{'a' * 64}"
    assert payload["payload"]["watcher"]["adapter"] == "database_registry"
    assert payload["payload"]["watcher"]["databaseHash"]
    assert str(database_path) not in repr(payload)


def test_readiness_watcher_dispatches_database_registry_record_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
    database_path = tmp_path / "db" / "kraken2"
    database_path.mkdir(parents=True)
    _add_available_database(cfg, database_path, version="2026.06", checksum="a" * 64)
    trigger = _create_database_ready_trigger(cfg, "db_kraken2")
    run_workflow_trigger_readiness_watcher_once(cfg)

    _add_available_database(cfg, database_path, version="2026.07", checksum="b" * 64)
    tick = run_workflow_trigger_readiness_watcher_once(cfg)
    events = list_workflow_trigger_events(cfg, trigger["triggerId"])["items"]

    assert tick["ready"] == 1
    assert tick["submitted"] == 1
    assert len(events) == 2
    assert {
        event["payload"]["resource"]["checksum"]
        for event in events
    } == {f"sha256:{'a' * 64}", f"sha256:{'b' * 64}"}
    assert len({event["payload"]["resource"]["version"] for event in events}) == 2


def test_readiness_watcher_ignores_database_registry_display_and_path_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
    first_path = tmp_path / "db" / "kraken2-a"
    second_path = tmp_path / "db" / "kraken2-b"
    first_path.mkdir(parents=True)
    second_path.mkdir(parents=True)
    _add_available_database(cfg, first_path, version="2026.06", checksum="a" * 64)
    trigger = _create_database_ready_trigger(cfg, "db_kraken2")
    run_workflow_trigger_readiness_watcher_once(cfg)

    add_reference_database(
        cfg,
        {
            "id": "db_kraken2",
            "name": "Kraken2 renamed",
            "templateId": "kraken2",
            "type": "taxonomy",
            "version": "2026.06",
            "path": str(second_path),
            "checksum": "a" * 64,
            "sizeBytes": 42,
            "status": "available",
            "message": "Display-only registry fields changed.",
            "metadata": {
                "templateId": "kraken2",
                "pathMode": "directory",
                "inputPath": str(second_path),
                "entryPath": str(second_path),
                "resolvedPath": {"kind": "directory", "path": str(second_path)},
            },
        },
    )
    tick = run_workflow_trigger_readiness_watcher_once(cfg)
    events = list_workflow_trigger_events(cfg, trigger["triggerId"])["items"]

    assert tick["ready"] == 0
    assert tick["submitted"] == 0
    assert tick["unchanged"] == 1
    assert len(events) == 1


def test_readiness_watcher_database_registry_records_unavailable_without_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    database_path = tmp_path / "db" / "kraken2"
    _add_database(cfg, database_path, status="missing", checksum="")
    trigger = _create_database_ready_trigger(cfg, "db_kraken2")

    tick = run_workflow_trigger_readiness_watcher_once(cfg)

    assert tick["checked"] == 1
    assert tick["missing"] == 1
    assert tick["submitted"] == 0
    assert list_workflow_trigger_events(cfg, trigger["triggerId"])["items"] == []
    observation = fetch_readiness_observation(cfg, trigger["triggerId"])
    assert observation["watcherAdapter"] == "database_registry"
    assert observation["observedState"] == "missing"
    public_read = get_workflow_trigger_readiness_observation_from_storage(cfg, trigger["triggerId"])
    assert public_read["data"]["observation"]["observedState"] == "missing"
    assert public_read["data"]["observation"]["resourceUriPresent"] is True
    assert "resourceId" not in public_read["data"]["observation"]
    assert "resourceUri" not in public_read["data"]["observation"]


def test_readiness_watcher_records_missing_and_unsupported_without_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    missing_path = tmp_path / "missing.fastq"
    missing = _create_file_trigger(cfg, missing_path)
    unsupported = create_workflow_trigger_from_request(
        cfg,
        WorkflowTriggerCreateRequest(
            name="Unsupported watcher",
            sourceType="file",
            serverId="srv_primary",
            runSpec={
                "pipelineId": "file-summary-standard-v1",
                "inputs": [{"uploadId": "upl_reads", "filename": "reads.fastq"}],
            },
            triggerSpec={
                "resource": {
                    "type": "file",
                    "id": "file:/unsupported.fastq",
                    "watch": {"enabled": True, "adapter": "s3_object"},
                }
            },
        ),
        actor="pytest",
    )["data"]

    tick = run_workflow_trigger_readiness_watcher_once(cfg)

    assert tick["checked"] == 2
    assert tick["missing"] == 1
    assert tick["submitted"] == 0
    assert tick["errors"][0]["triggerId"] == unsupported["triggerId"]
    assert "WORKFLOW_TRIGGER_READINESS_WATCHER_ADAPTER_UNSUPPORTED" in tick["errors"][0]["message"]
    assert list_workflow_trigger_events(cfg, missing["triggerId"])["items"] == []
    assert fetch_readiness_observation(cfg, missing["triggerId"])["observedState"] == "missing"
    assert fetch_readiness_observation(cfg, unsupported["triggerId"])["observedState"] == "error"
    missing_public = get_workflow_trigger_readiness_observation_from_storage(cfg, missing["triggerId"])
    unsupported_public = get_workflow_trigger_readiness_observation_from_storage(cfg, unsupported["triggerId"])
    assert missing_public["data"]["observation"]["observedState"] == "missing"
    assert "resourceId" not in missing_public["data"]["observation"]
    assert "resourceUri" not in missing_public["data"]["observation"]
    assert str(missing_path) not in repr(missing_public)
    assert unsupported_public["data"]["observation"]["observedState"] == "error"
    assert unsupported_public["data"]["observation"]["error"] == {
        "errorType": "ValueError",
        "reasonCode": "WORKFLOW_TRIGGER_READINESS_WATCHER_ADAPTER_UNSUPPORTED",
    }


def test_readiness_observation_read_model_hashes_unsafe_resource_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
    watched = tmp_path / "incoming" / "secret-token.fastq"
    watched.parent.mkdir()
    watched.write_text("secret\n", encoding="utf-8")
    unsafe_resource_id = f"{watched}?token=super-secret"
    trigger = _create_file_trigger_with_resource_id(cfg, watched, unsafe_resource_id)

    tick = run_workflow_trigger_readiness_watcher_once(cfg)
    public_read = get_workflow_trigger_readiness_observation_from_storage(cfg, trigger["triggerId"])
    public_observation = public_read["data"]["observation"]

    assert tick["submitted"] == 1
    assert public_observation["observedState"] == "ready"
    assert public_observation["resourceIdentity"] == {
        "type": "file",
        "idPresent": True,
        "idLength": len(unsafe_resource_id),
        "idHash": public_observation["resourceIdentity"]["idHash"],
    }
    assert len(public_observation["resourceIdentity"]["idHash"]) == 64
    assert "resourceId" not in public_observation
    assert str(watched) not in repr(public_read)
    assert watched.as_uri() not in repr(public_read)
    assert "super-secret" not in repr(public_read)


def test_configured_readiness_watcher_is_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("H2OMETA_TRIGGER_READINESS_WATCHER", raising=False)
    monkeypatch.setattr(watcher, "load_remote_runner_config", lambda: SimpleNamespace(token="token"))

    assert watcher.start_configured_workflow_trigger_readiness_watcher_supervisor() is None


def test_configured_readiness_watcher_builds_supervisor_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []
    sentinel = object()
    cfg = SimpleNamespace(token="token")

    def fake_start(cfg_arg, *, poll_interval_seconds: float, limit: int):
        captured.append({"cfg": cfg_arg, "pollIntervalSeconds": poll_interval_seconds, "limit": limit})
        return sentinel

    monkeypatch.setattr(watcher, "load_remote_runner_config", lambda: cfg)
    monkeypatch.setattr(watcher, "start_workflow_trigger_readiness_watcher_supervisor", fake_start)
    monkeypatch.setenv("H2OMETA_TRIGGER_READINESS_WATCHER", "1")
    monkeypatch.setenv("H2OMETA_TRIGGER_READINESS_WATCHER_POLL_SECONDS", "7.5")
    monkeypatch.setenv("H2OMETA_TRIGGER_READINESS_WATCHER_LIMIT", "12")

    supervisor = watcher.start_configured_workflow_trigger_readiness_watcher_supervisor()

    assert supervisor is sentinel
    assert captured == [{"cfg": cfg, "pollIntervalSeconds": 7.5, "limit": 12}]


def test_readiness_watcher_supervisor_runs_ticks(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    cfg = SimpleNamespace(service_name="remote-runner")

    def fake_tick(tick_cfg, *, limit: int):
        calls.append({"cfg": tick_cfg, "limit": limit})
        return {"errors": []}

    monkeypatch.setattr(watcher, "run_workflow_trigger_readiness_watcher_once", fake_tick)
    supervisor = watcher.start_workflow_trigger_readiness_watcher_supervisor(
        cfg,
        poll_interval_seconds=0.01,
        limit=3,
    )
    deadline = time.monotonic() + 1
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)
    supervisor.stop(timeout_seconds=1)

    assert calls
    assert calls[0] == {"cfg": cfg, "limit": 3}


def test_readiness_watcher_source_boundary_uses_existing_readiness_submission() -> None:
    source = (ROOT / "apps" / "remote_runner" / "trigger_readiness_watcher.py").read_text(encoding="utf-8")

    assert "submit_workflow_trigger_readiness_event_from_request" in source
    assert "fetch_reference_database" in source
    assert "create_run_record" not in source
    assert "mark_workflow_trigger_dispatch_submitted" not in source
    assert "record_workflow_trigger_event(" not in source


def _add_available_database(cfg, database_path: Path, *, version: str, checksum: str) -> dict[str, Any]:
    return _add_database(cfg, database_path, version=version, status="available", checksum=checksum)


def _add_database(
    cfg,
    database_path: Path,
    *,
    version: str = "2026.06",
    status: str,
    checksum: str,
) -> dict[str, Any]:
    return add_reference_database(
        cfg,
        {
            "id": "db_kraken2",
            "name": "Kraken2 mini",
            "templateId": "kraken2",
            "type": "taxonomy",
            "version": version,
            "path": str(database_path),
            "checksum": checksum,
            "sizeBytes": 42,
            "status": status,
            "message": f"Database is {status}.",
            "metadata": {"templateId": "kraken2", "pathMode": "directory"},
        },
    )


def _create_database_ready_trigger(cfg, database_id: str) -> dict[str, Any]:
    return create_workflow_trigger_from_request(
        cfg,
        WorkflowTriggerCreateRequest(
            name="Watched database",
            sourceType="database_ready",
            serverId="srv_primary",
            runSpec={
                "pipelineId": "file-summary-standard-v1",
                "inputs": [{"uploadId": "upl_reads", "filename": "reads.fastq"}],
            },
            triggerSpec={
                "resource": {
                    "type": "database",
                    "id": database_id,
                    "uri": f"h2ometa://database/{database_id}",
                    "watch": {"enabled": True, "adapter": "database_registry"},
                }
            },
        ),
        actor="pytest",
    )["data"]


def _create_file_trigger(cfg, watched: Path) -> dict[str, Any]:
    return _create_file_trigger_with_resource_id(cfg, watched, "file:/incoming/reads.fastq")


def _create_file_trigger_with_stability(cfg, watched: Path, *, stability_seconds: int) -> dict[str, Any]:
    return create_workflow_trigger_from_request(
        cfg,
        WorkflowTriggerCreateRequest(
            name="Stable watched FASTQ",
            sourceType="file",
            serverId="srv_primary",
            runSpec={
                "pipelineId": "file-summary-standard-v1",
                "inputs": [{"uploadId": "upl_reads", "filename": "reads.fastq"}],
            },
            triggerSpec={
                "resource": {
                    "type": "file",
                    "id": "file:/incoming/reads.fastq",
                    "uri": watched.as_uri(),
                    "watch": {
                        "enabled": True,
                        "adapter": "local_path",
                        "path": str(watched),
                        "stabilitySeconds": stability_seconds,
                    },
                }
            },
        ),
        actor="pytest",
    )["data"]


def _create_file_trigger_with_resource_id(cfg, watched: Path, resource_id: str) -> dict[str, Any]:
    return create_workflow_trigger_from_request(
        cfg,
        WorkflowTriggerCreateRequest(
            name="Watched FASTQ",
            sourceType="file",
            serverId="srv_primary",
            runSpec={
                "pipelineId": "file-summary-standard-v1",
                "inputs": [{"uploadId": "upl_reads", "filename": "reads.fastq"}],
            },
            triggerSpec={
                "resource": {
                    "type": "file",
                    "id": resource_id,
                    "uri": watched.as_uri(),
                    "watch": {"enabled": True, "adapter": "local_path", "path": str(watched)},
                }
            },
        ),
        actor="pytest",
    )["data"]
