from __future__ import annotations

from pathlib import Path

from apps.remote_runner.artifact_ledger_storage import (
    list_artifact_materializations,
    list_lineage_edges_for_run,
    list_run_artifact_edges,
    record_artifact_blob_for_path,
    record_artifact_materialization,
    record_lineage_edge,
    record_run_artifact_edge,
)
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
