from __future__ import annotations

import json
import zipfile
from pathlib import Path

from apps.remote_runner.artifact_product_service import export_result_package
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.trigger_storage import (
    create_workflow_trigger,
    mark_workflow_trigger_dispatch_submitted,
    record_workflow_trigger_event,
)
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from tests.helpers.reference_database import make_configured_remote_runner


def test_result_package_export_includes_safe_trigger_provenance(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_completed_run(cfg, "run_trigger_export")
    trigger = create_workflow_trigger(
        cfg,
        name="Manual export trigger",
        source_type="manual",
        server_id="srv_artifact",
        pipeline_id="file-summary-standard-v1",
        run_spec={
            "runId": "run_trigger_export",
            "projectId": "proj_artifact",
            "pipelineId": "file-summary-standard-v1",
            "workflowRevisionId": revision["workflowRevisionId"],
        },
        trigger_spec={"mode": "manual"},
        enabled=True,
        actor="pytest",
    )
    event = record_workflow_trigger_event(
        cfg,
        trigger=trigger,
        event_type="manual",
        external_event_id="evt_manual_export",
        idempotency_key="manual:export",
        cursor="manual:export",
        payload={"dataset": "reads.fastq", "apiToken": "must-not-export"},
    )
    mark_workflow_trigger_dispatch_submitted(
        cfg,
        trigger_event_id=event["triggerEventId"],
        run_id="run_trigger_export",
    )
    report = _managed_artifact_file(cfg, "run_trigger_export", "report.txt")
    report.write_bytes(b"accepted\n")
    persist_artifact(
        cfg,
        run_id="run_trigger_export",
        kind="report",
        path=report,
        mime_type="text/plain",
        artifact_key="report",
    )

    package = export_result_package(cfg, "res_run_trigger_export", include_artifacts=True)

    trigger_provenance = package["manifest"]["triggerProvenance"]
    assert trigger_provenance["schemaVersion"] == "h2ometa.trigger-provenance.v1"
    assert trigger_provenance["triggerId"] == trigger["triggerId"]
    assert trigger_provenance["triggerEventId"] == event["triggerEventId"]
    assert trigger_provenance["event"] == {
        "triggerEventId": event["triggerEventId"],
        "triggerId": trigger["triggerId"],
        "sourceType": "manual",
        "eventType": "manual",
        "externalEventId": "evt_manual_export",
        "idempotencyKey": "manual:export",
        "payloadHash": event["payloadHash"],
        "cursor": "manual:export",
        "createdAt": event["createdAt"],
    }
    assert "payload" not in trigger_provenance["event"]
    assert trigger_provenance["dispatch"]["runId"] == "run_trigger_export"
    assert trigger_provenance["trigger"]["pipelineId"] == "file-summary-standard-v1"
    assert package["manifest"]["provenance"]["activity"]["wasStartedBy"] == (
        f"triggerEvent:{event['triggerEventId']}"
    )

    export_evidence = list_evidence_events(
        cfg,
        subject_kind="result",
        subject_id="res_run_trigger_export",
        event_type="result.export.v1",
    )
    assert export_evidence[-1]["payload"]["triggerProvenance"] == trigger_provenance

    with zipfile.ZipFile(package["packagePath"]) as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        run_metadata = json.loads(archive.read("metadata/run.json").decode("utf-8"))
        ro_crate = json.loads(archive.read("ro-crate-metadata.json").decode("utf-8"))
    graph_by_id = {item["@id"]: item for item in ro_crate["@graph"]}
    trigger_entity_id = f"#trigger-event-{event['triggerEventId']}"

    assert manifest["triggerProvenance"] == trigger_provenance
    assert run_metadata["trigger"] == {
        "triggerId": trigger["triggerId"],
        "triggerEventId": event["triggerEventId"],
        "source": "manual",
        "cursor": "manual:export",
    }
    assert graph_by_id["#run-run_trigger_export"]["h2ometa:triggerEvent"] == {"@id": trigger_entity_id}
    assert graph_by_id[trigger_entity_id]["h2ometa:payloadHash"] == event["payloadHash"]
    assert "must-not-export" not in json.dumps(package["manifest"], sort_keys=True)


def _create_completed_run(cfg, run_id: str) -> dict[str, object]:
    revision = create_or_fetch_workflow_revision(
        cfg,
        draft_id=f"draft_{run_id}",
        draft_revision=1,
        manifest={
            "files": [{"path": "workflow/Snakefile", "sha256": "a" * 64}],
            "layout": {"snakefile": "workflow/Snakefile"},
        },
        graph_snapshot={"nodes": ["summarize"], "edges": [], "runSpec": {"runId": run_id}},
        runtime_lock={"snakemake": "9.23.1"},
        compiler={"name": "h2ometa-test", "version": "0.1.0"},
        created_by="pytest",
    )
    create_run_record(
        cfg,
        server_id="srv_artifact",
        request_id=f"req_{run_id}",
        run_spec={
            "runId": run_id,
            "projectId": "proj_artifact",
            "pipelineId": "file-summary-standard-v1",
            "pipelineVersion": "0.1.0",
            "workflowRevisionId": revision["workflowRevisionId"],
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = 'completed',
                stage = 'complete',
                finished_at = '2099-06-07T10:00:03Z',
                last_updated_at = '2099-06-07T10:00:03Z'
            WHERE run_id = ?
            """,
            (run_id,),
        )
        connection.execute(
            """
            UPDATE run_jobs
            SET state = 'completed',
                updated_at = '2099-06-07T10:00:03Z'
            WHERE run_id = ?
            """,
            (run_id,),
        )
        connection.commit()
    return revision


def _managed_artifact_file(cfg, run_id: str, filename: str) -> Path:
    path = Path(cfg.results_dir) / run_id / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
