from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.storage import upsert_tool
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.tool_platform_storage import record_prepare_job_validation_result
from apps.remote_runner.tool_prepare_job_storage import create_tool_prepare_job
from apps.remote_runner.tool_revisions import publish_tool_revision
from apps.remote_runner.tools import mark_registered_tool_production_enabled
from tests.test_tool_contract_production_evidence import _completed_run_with_artifact, _ready_tool


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token="evidence-ledger-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
    )


def test_prepare_validation_results_append_hash_chained_evidence_events(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    job = create_tool_prepare_job(
        cfg,
        {
            "id": "bioconda::fastqc",
            "name": "fastqc",
            "packageSpec": "bioconda::fastqc=0.12.1",
            "targetPlatform": "linux-64",
        },
    )

    with get_connection(cfg) as connection:
        first = record_prepare_job_validation_result(
            connection,
            job_id=job["jobId"],
            stage="dry_run",
            status="succeeded",
            result={"toolRevisionId": "bioconda::fastqc@1"},
            created_at="2099-06-07T10:00:00Z",
        )
        second = record_prepare_job_validation_result(
            connection,
            job_id=job["jobId"],
            stage="output_validation",
            status="succeeded",
            result={
                "toolRevisionId": "bioconda::fastqc@1",
                "logs": ["dry-run ok", "output ok"],
                "artifacts": [{"path": "report.html", "sizeBytes": 123}],
            },
            created_at="2099-06-07T10:00:01Z",
        )
        connection.commit()

    events = list_evidence_events(cfg, subject_kind="tool", subject_id="bioconda::fastqc")

    assert [event["eventType"] for event in events] == [
        "tool.validation.result.v1",
        "tool.validation.result.v1",
    ]
    assert first["evidenceId"] == events[0]["eventId"]
    assert second["evidenceId"] == events[1]["eventId"]
    assert events[0]["seq"] == 1
    assert events[0]["prevEventHash"] == ""
    assert events[1]["seq"] == 2
    assert events[1]["prevEventHash"] == events[0]["eventHash"]
    assert events[1]["schema"]["name"] == "ToolValidationResultEvidence"
    assert events[1]["payload"]["validationResultId"] == second["validationResultId"]
    assert events[1]["payload"]["runtimeProfileId"] == second["runtimeProfileId"]
    assert events[1]["payload"]["artifacts"] == [{"path": "report.html", "sizeBytes": 123}]


def test_production_promotion_appends_scoped_evidence_event(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _ready_tool(cfg)
    _completed_run_with_artifact(cfg, tmp_path)

    accepted = mark_registered_tool_production_enabled(
        cfg,
        "conda-forge::production-ready",
        {
            "runId": "run_real_data",
            "message": "Accepted against real remote data.",
            "logPath": "/remote/logs/run_real_data.log",
            "evidenceType": "real-data-acceptance",
            "artifactName": "report.txt",
            "targetPlatform": "linux-64",
            "environmentLock": {"manager": "conda", "packageSpec": "conda-forge::production-ready=9.5"},
            "policyVersion": "tool-production-policy-v1",
        },
    )

    events = list_evidence_events(
        cfg,
        subject_kind="tool",
        subject_id="conda-forge::production-ready",
    )

    assert accepted["contractStatus"]["production"]["evidenceId"] == events[-1]["eventId"]
    assert events[-1]["eventType"] == "tool.production.acceptance.v1"
    assert events[-1]["schema"]["name"] == "ToolProductionAcceptanceEvidence"
    assert events[-1]["payload"]["toolId"] == "conda-forge::production-ready"
    assert events[-1]["payload"]["runId"] == "run_real_data"
    assert events[-1]["payload"]["targetPlatform"] == "linux-64"
    assert events[-1]["payload"]["environmentLock"] == {
        "manager": "conda",
        "packageSpec": "conda-forge::production-ready=9.5",
    }
    assert events[-1]["payload"]["policyVersion"] == "tool-production-policy-v1"


def test_production_promotion_event_records_current_tool_revision(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    saved = _ready_tool(cfg)
    revision = publish_tool_revision(cfg, saved)
    saved["toolRevisionId"] = revision["toolRevisionId"]
    saved["revision"] = revision["revision"]
    saved["publishedAt"] = revision["publishedAt"]
    upsert_tool(cfg, saved)
    _completed_run_with_artifact(
        cfg,
        tmp_path,
        run_id="run_revision_tool",
        run_spec={
            "runId": "run_revision_tool",
            "pipelineId": "generated-tool-run-v1",
            "workflow": {
                "contractVersion": "rule-contract-v1",
                "nodes": [{"id": "copy_report", "toolRevisionId": revision["toolRevisionId"]}],
                "edges": [],
                "outputs": [],
            },
        },
    )

    mark_registered_tool_production_enabled(
        cfg,
        "conda-forge::production-ready",
        {"runId": "run_revision_tool", "message": "Accepted.", "evidenceType": "real-data-acceptance"},
    )

    events = list_evidence_events(
        cfg,
        subject_kind="tool",
        subject_id="conda-forge::production-ready",
    )

    assert events[-1]["eventType"] == "tool.production.acceptance.v1"
    assert events[-1]["payload"]["toolRevisionId"] == revision["toolRevisionId"]
