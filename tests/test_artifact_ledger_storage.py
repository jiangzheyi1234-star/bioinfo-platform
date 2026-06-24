from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from apps.remote_runner.artifact_input_lineage import record_run_input_artifact_lineage
from apps.remote_runner.artifact_ledger_storage import (
    list_artifact_materializations,
    list_lineage_edges_for_run,
    list_run_artifact_edges,
    record_artifact_blob_for_path,
    record_artifact_materialization,
    record_lineage_edge,
    record_run_artifact_edge,
)
from apps.remote_runner.evidence_storage import list_evidence_events
from tests.helpers.reference_database import make_configured_remote_runner


def test_artifact_blob_identity_is_content_addressed_across_materializations(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    first_path = tmp_path / "first" / "report.txt"
    second_path = tmp_path / "second" / "renamed.txt"
    first_path.parent.mkdir()
    second_path.parent.mkdir()
    first_path.write_text("same content\n", encoding="utf-8")
    second_path.write_text("same content\n", encoding="utf-8")

    first_blob = record_artifact_blob_for_path(
        cfg,
        path=first_path,
        media_type="text/plain",
        created_at="2099-06-07T10:00:00Z",
    )
    second_blob = record_artifact_blob_for_path(
        cfg,
        path=second_path,
        media_type="text/plain",
        created_at="2099-06-07T10:00:01Z",
    )
    first_materialization = record_artifact_materialization(
        cfg,
        artifact_blob_id=first_blob["artifactBlobId"],
        storage_backend="local",
        storage_uri=first_path.resolve().as_uri(),
        local_path=first_path,
        created_at="2099-06-07T10:00:02Z",
    )
    second_materialization = record_artifact_materialization(
        cfg,
        artifact_blob_id=second_blob["artifactBlobId"],
        storage_backend="local",
        storage_uri=second_path.resolve().as_uri(),
        local_path=second_path,
        created_at="2099-06-07T10:00:03Z",
    )
    replay = record_artifact_materialization(
        cfg,
        artifact_blob_id=second_blob["artifactBlobId"],
        storage_backend="local",
        storage_uri=second_path.resolve().as_uri(),
        local_path=second_path,
        created_at="2099-06-07T10:00:04Z",
    )

    assert second_blob["artifactBlobId"] == first_blob["artifactBlobId"]
    assert second_blob["created"] is False
    assert first_blob["sha256"] == second_blob["sha256"]
    assert first_materialization["materializationId"] != second_materialization["materializationId"]
    assert replay["materializationId"] == second_materialization["materializationId"]
    assert replay["created"] is False
    materializations = list_artifact_materializations(cfg, first_blob["artifactBlobId"])
    assert [item["storageUri"] for item in materializations] == [
        first_path.resolve().as_uri(),
        second_path.resolve().as_uri(),
    ]


def test_run_artifact_edges_model_bipartite_lineage(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    artifact_path = tmp_path / "sample.bam"
    artifact_path.write_text("bam content\n", encoding="utf-8")
    blob = record_artifact_blob_for_path(
        cfg,
        path=artifact_path,
        media_type="application/octet-stream",
        created_at="2099-06-07T10:00:00Z",
    )

    upstream = record_run_artifact_edge(
        cfg,
        run_id="run_align",
        artifact_blob_id=blob["artifactBlobId"],
        role="output",
        port_name="bam",
        step_id="align",
        upstream_run_id=None,
        created_at="2099-06-07T10:00:01Z",
    )
    downstream = record_run_artifact_edge(
        cfg,
        run_id="run_variant",
        artifact_blob_id=blob["artifactBlobId"],
        role="input",
        port_name="bam",
        step_id="call_variants",
        upstream_run_id="run_align",
        created_at="2099-06-07T10:00:02Z",
    )

    assert upstream["contentHash"] == blob["sha256"]
    assert downstream["upstreamRunId"] == "run_align"
    assert list_run_artifact_edges(cfg, "run_variant") == [downstream]


def test_lineage_edges_record_canonical_prov_relation(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    edge = record_lineage_edge(
        cfg,
        subject_kind="run",
        subject_id="run_align",
        predicate="prov:generated",
        object_kind="artifact_blob",
        object_id="ablob_demo",
        run_id="run_align",
        workflow_revision_id="wfrev_demo",
        payload={"portName": "bam", "stepId": "align"},
        content_hash="sha256:demo",
        created_at="2099-06-07T10:00:03Z",
    )

    assert edge["subjectKind"] == "run"
    assert edge["subjectId"] == "run_align"
    assert edge["predicate"] == "prov:generated"
    assert edge["objectKind"] == "artifact_blob"
    assert edge["objectId"] == "ablob_demo"
    assert edge["runId"] == "run_align"
    assert edge["workflowRevisionId"] == "wfrev_demo"
    assert edge["payload"] == {"portName": "bam", "stepId": "align"}
    assert edge["contentHash"] == "sha256:demo"
    assert list_lineage_edges_for_run(cfg, "run_align") == [edge]


def test_input_artifact_lineage_records_prov_used_without_path_leak(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    input_path = tmp_path / "uploads" / "reads.fastq"
    input_path.parent.mkdir()
    input_path.write_text("@read1\nACGT\n+\n!!!!\n", encoding="utf-8")
    sha256 = hashlib.sha256(input_path.read_bytes()).hexdigest()
    resolved_input = {
        "uploadId": "upl_reads",
        "name": "reads",
        "filename": "reads.fastq",
        "role": "reads",
        "path": str(input_path),
        "sizeBytes": input_path.stat().st_size,
        "sha256": sha256,
        "mimeType": "text/plain",
        "index": 0,
    }

    records = record_run_input_artifact_lineage(
        cfg,
        run_id="run_input",
        resolved_inputs=[resolved_input],
        created_at="2099-06-07T10:00:00Z",
    )
    replay = record_run_input_artifact_lineage(
        cfg,
        run_id="run_input",
        resolved_inputs=[resolved_input],
        created_at="2099-06-07T10:00:01Z",
    )

    run_edges = list_run_artifact_edges(cfg, "run_input")
    lineage_edges = list_lineage_edges_for_run(cfg, "run_input")
    evidence_events = list_evidence_events(
        cfg,
        subject_kind="artifact_blob",
        subject_id=records[0]["artifactBlobId"],
        event_type="artifact.input.v1",
    )

    assert replay[0]["runArtifactEdgeId"] == records[0]["runArtifactEdgeId"]
    assert len(run_edges) == 1
    assert run_edges[0]["role"] == "input"
    assert run_edges[0]["portName"] == "reads"
    assert run_edges[0]["contentHash"] == sha256
    assert len(lineage_edges) == 1
    assert lineage_edges[0]["predicate"] == "prov:used"
    assert lineage_edges[0]["payload"]["uploadId"] == "upl_reads"
    assert lineage_edges[0]["payload"]["portName"] == "reads"
    assert len(evidence_events) == 1
    assert evidence_events[0]["payload"]["sha256"] == sha256
    assert evidence_events[0]["payload"]["runArtifactEdgeId"] == run_edges[0]["edgeId"]
    for payload in (lineage_edges[0]["payload"], evidence_events[0]["payload"]):
        assert "path" not in payload
        assert "localPath" not in payload
        assert "storageUri" not in payload


def test_input_artifact_lineage_records_artifact_source_and_upstream_run(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    input_path = tmp_path / "results" / "source" / "summary.tsv"
    input_path.parent.mkdir(parents=True)
    input_path.write_text("sample\tcount\nA\t1\n", encoding="utf-8")
    blob = record_artifact_blob_for_path(
        cfg,
        path=input_path,
        media_type="text/tab-separated-values",
        created_at="2099-06-07T10:00:00Z",
    )
    materialization = record_artifact_materialization(
        cfg,
        artifact_blob_id=blob["artifactBlobId"],
        storage_backend="local",
        storage_uri=input_path.resolve().as_uri(),
        local_path=input_path,
        created_at="2099-06-07T10:00:01Z",
    )

    records = record_run_input_artifact_lineage(
        cfg,
        run_id="run_downstream",
        resolved_inputs=[
            {
                "sourceType": "artifact",
                "sourceId": "art_source",
                "artifactId": "art_source",
                "artifactBlobId": blob["artifactBlobId"],
                "materializationId": materialization["materializationId"],
                "upstreamRunId": "run_source",
                "name": "summary",
                "filename": "summary.tsv",
                "role": "summary",
                "path": str(input_path),
                "sizeBytes": blob["sizeBytes"],
                "sha256": blob["sha256"],
                "mimeType": blob["mediaType"],
                "index": 0,
            }
        ],
        created_at="2099-06-07T10:00:02Z",
    )

    run_edges = list_run_artifact_edges(cfg, "run_downstream")
    lineage_edges = list_lineage_edges_for_run(cfg, "run_downstream")
    evidence_events = list_evidence_events(
        cfg,
        subject_kind="artifact_blob",
        subject_id=blob["artifactBlobId"],
        event_type="artifact.input.v1",
    )

    assert records[0]["sourceType"] == "artifact"
    assert records[0]["artifactId"] == "art_source"
    assert run_edges[0]["upstreamRunId"] == "run_source"
    assert lineage_edges[0]["payload"]["sourceType"] == "artifact"
    assert lineage_edges[0]["payload"]["sourceId"] == "art_source"
    assert lineage_edges[0]["payload"]["artifactId"] == "art_source"
    assert lineage_edges[0]["payload"]["upstreamRunId"] == "run_source"
    assert "uploadId" not in lineage_edges[0]["payload"]
    assert evidence_events[0]["payload"]["artifactId"] == "art_source"
    assert evidence_events[0]["payload"]["upstreamRunId"] == "run_source"
    for payload in (lineage_edges[0]["payload"], evidence_events[0]["payload"]):
        assert "path" not in payload
        assert "localPath" not in payload
        assert "storageUri" not in payload


def test_input_artifact_lineage_rejects_digest_mismatch_before_recording(
    tmp_path: Path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    input_path = tmp_path / "uploads" / "reads.fastq"
    input_path.parent.mkdir()
    input_path.write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="INPUT_ARTIFACT_DIGEST_MISMATCH: upl_reads"):
        record_run_input_artifact_lineage(
            cfg,
            run_id="run_bad_input",
            resolved_inputs=[
                {
                    "uploadId": "upl_reads",
                    "filename": "reads.fastq",
                    "role": "reads",
                    "path": str(input_path),
                    "sizeBytes": input_path.stat().st_size,
                    "sha256": "0" * 64,
                    "mimeType": "text/plain",
                    "index": 0,
                }
            ],
        )

    assert list_run_artifact_edges(cfg, "run_bad_input") == []
    assert list_lineage_edges_for_run(cfg, "run_bad_input") == []
