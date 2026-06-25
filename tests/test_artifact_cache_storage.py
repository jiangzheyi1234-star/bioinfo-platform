from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from apps.remote_runner.artifact_cache_storage import (
    ARTIFACT_CACHE_PIN_PROTECTION_REASON,
    ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND,
    ARTIFACT_CACHE_RESTORE_PIN_SCOPE,
    create_artifact_cache_pins,
    list_artifact_cache_entries,
    list_artifact_cache_pins,
    lookup_artifact_cache_entry,
)
from apps.remote_runner.artifact_cache_adoption import try_adopt_cached_outputs
from apps.remote_runner.artifact_cache_pin_service import (
    ARTIFACT_CACHE_POLICY_PIN_RELEASE_CONFIRMATION,
    list_artifact_cache_policy_pins,
    release_artifact_cache_policy_pin,
    retain_artifact_cache_policy_pin,
)
from apps.remote_runner.artifact_ledger_storage import list_artifact_materializations
from apps.remote_runner.artifact_lifecycle_service import ARTIFACT_GC_CONFIRMATION, preview_artifact_gc, run_artifact_gc
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.execution_query_storage import fetch_run_results
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.upload_storage import persist_upload
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.workflow_run_storage import StaleRunAttemptError
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from tests.helpers.reference_database import make_configured_remote_runner


def test_artifact_cache_records_workflow_revision_key_and_verified_lookup_hit(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    run_spec = _run_spec("run_cache_hit", revision["workflowRevisionId"])
    _create_terminal_run(cfg, run_spec)
    artifact_path = _managed_report(cfg, "run_cache_hit", b"cached output\n")

    artifact = persist_artifact(
        cfg,
        run_id="run_cache_hit",
        kind="report",
        path=artifact_path,
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )
    lookup = lookup_artifact_cache_entry(cfg, _lookup_payload(revision["workflowRevisionId"]))
    entries = list_artifact_cache_entries(cfg, workflow_revision_id=revision["workflowRevisionId"])["items"]
    events = list_evidence_events(cfg, subject_kind="artifact_cache", subject_id=lookup["cacheKey"])

    assert artifact["artifactCacheEligible"] is True
    assert artifact["artifactCacheKey"] == lookup["cacheKey"]
    assert lookup["hit"] is True
    assert lookup["reason"] == "hit"
    assert lookup["entry"]["artifactId"] == artifact["artifactId"]
    assert lookup["entry"]["hitCount"] == 1
    assert entries[0]["cacheKey"] == lookup["cacheKey"]
    assert entries[0]["hitCount"] == 1
    assert events[-1]["eventType"] == "artifact.cache.lookup.v1"
    assert events[-1]["payload"]["hit"] is True


def test_artifact_cache_lookup_misses_when_relevant_inputs_change(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    run_spec = _run_spec("run_cache_miss", revision["workflowRevisionId"])
    _create_terminal_run(cfg, run_spec)
    persist_artifact(
        cfg,
        run_id="run_cache_miss",
        kind="report",
        path=_managed_report(cfg, "run_cache_miss", b"cached output\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )

    changed = _lookup_payload(revision["workflowRevisionId"])
    changed["params"] = {"threshold": 9}
    lookup = lookup_artifact_cache_entry(cfg, changed)

    assert lookup["hit"] is False
    assert lookup["reason"] == "cache_key_not_found"


def test_artifact_cache_key_uses_upload_content_digest_for_inputs(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    first_upload = _upload(cfg, "first.fastq", b"same reads\n")
    second_upload = _upload(cfg, "renamed.fastq", b"same reads\n")
    run_spec = _run_spec(
        "run_cache_upload",
        revision["workflowRevisionId"],
        inputs=[{"name": "reads", "uploadId": first_upload["uploadId"], "filename": "first.fastq"}],
    )
    _create_terminal_run(cfg, run_spec)
    persist_artifact(
        cfg,
        run_id="run_cache_upload",
        kind="report",
        path=_managed_report(cfg, "run_cache_upload", b"content keyed\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )

    lookup = lookup_artifact_cache_entry(
        cfg,
        _lookup_payload(
            revision["workflowRevisionId"],
            inputs=[{"name": "reads", "uploadId": second_upload["uploadId"], "filename": "renamed.fastq"}],
        ),
    )

    assert lookup["hit"] is True
    assert lookup["reason"] == "hit"


def test_artifact_cache_key_uses_artifact_content_digest_for_inputs(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    upload = _upload(cfg, "reads.fastq", b"same reads\n")
    cached_run_spec = _run_spec(
        "run_cache_upload_source",
        revision["workflowRevisionId"],
        inputs=[{"name": "reads", "uploadId": upload["uploadId"], "filename": "reads.fastq"}],
    )
    _create_terminal_run(cfg, cached_run_spec)
    persist_artifact(
        cfg,
        run_id="run_cache_upload_source",
        kind="report",
        path=_managed_report(cfg, "run_cache_upload_source", b"content keyed\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )
    artifact_source_spec = _run_spec(
        "run_cache_artifact_source",
        revision["workflowRevisionId"],
        inputs=[{"name": "seed", "sha256": "seed"}],
    )
    _create_terminal_run(cfg, artifact_source_spec)
    source_input = persist_artifact(
        cfg,
        run_id="run_cache_artifact_source",
        kind="reads",
        path=_managed_report(cfg, "run_cache_artifact_source", b"same reads\n"),
        mime_type="text/plain",
        artifact_key="reads",
        step_id="prepare_reads",
    )

    lookup = lookup_artifact_cache_entry(
        cfg,
        _lookup_payload(
            revision["workflowRevisionId"],
            inputs=[
                {
                    "name": "reads",
                    "artifactId": source_input["artifactId"],
                    "filename": "source.fastq",
                    "upstreamRunId": "run_cache_artifact_source",
                }
            ],
        ),
    )

    assert lookup["hit"] is True
    assert lookup["reason"] == "hit"


def test_artifact_cache_key_conflict_does_not_overwrite_existing_entry(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    first_spec = _run_spec("run_cache_original", revision["workflowRevisionId"])
    second_spec = _run_spec("run_cache_conflict", revision["workflowRevisionId"])
    _create_terminal_run(cfg, first_spec)
    _create_terminal_run(cfg, second_spec)
    first = persist_artifact(
        cfg,
        run_id="run_cache_original",
        kind="report",
        path=_managed_report(cfg, "run_cache_original", b"original\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )
    conflict = persist_artifact(
        cfg,
        run_id="run_cache_conflict",
        kind="report",
        path=_managed_report(cfg, "run_cache_conflict", b"different\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )
    entries = list_artifact_cache_entries(cfg, workflow_revision_id=revision["workflowRevisionId"])["items"]

    assert first["artifactCacheEligible"] is True
    assert conflict["artifactCacheEligible"] is False
    assert conflict["artifactCacheIneligibleReason"] == "cache_key_conflict"
    assert [entry["artifactId"] for entry in entries] == [first["artifactId"]]


def test_artifact_cache_does_not_index_outputs_without_workflow_revision(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_spec = _run_spec("run_cache_ineligible", "")
    run_spec.pop("workflowRevisionId")
    _create_terminal_run(cfg, run_spec)

    artifact = persist_artifact(
        cfg,
        run_id="run_cache_ineligible",
        kind="report",
        path=_managed_report(cfg, "run_cache_ineligible", b"uncached\n"),
        mime_type="text/plain",
        artifact_key="report",
    )

    assert artifact["artifactCacheEligible"] is False
    assert artifact["artifactCacheIneligibleReason"] == "workflow_revision_missing"
    assert list_artifact_cache_entries(cfg)["items"] == []


def test_artifact_cache_does_not_index_unmanaged_local_payload(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    run_spec = _run_spec("run_cache_unmanaged_index", revision["workflowRevisionId"])
    _create_terminal_run(cfg, run_spec)
    outside = tmp_path / "outside-cache-index.txt"
    outside.write_bytes(b"outside cache\n")

    artifact = persist_artifact(
        cfg,
        run_id="run_cache_unmanaged_index",
        kind="report",
        path=outside,
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )

    assert artifact["artifactCacheEligible"] is False
    assert artifact["artifactCacheIneligibleReason"] == "artifact_unmanaged"
    assert list_artifact_cache_entries(cfg)["items"] == []


def test_artifact_cache_marks_entry_deleted_after_gc(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    run_spec = _run_spec("run_cache_gc", revision["workflowRevisionId"])
    _create_terminal_run(cfg, run_spec)
    persist_artifact(
        cfg,
        run_id="run_cache_gc",
        kind="report",
        path=_managed_report(cfg, "run_cache_gc", b"gc cached\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )

    run_artifact_gc(
        cfg,
        {
            "retentionDays": 30,
            "confirmation": ARTIFACT_GC_CONFIRMATION,
        },
    )
    lookup = lookup_artifact_cache_entry(cfg, _lookup_payload(revision["workflowRevisionId"]))
    entry = list_artifact_cache_entries(cfg, workflow_revision_id=revision["workflowRevisionId"])["items"][0]

    assert entry["lifecycleState"] == "deleted"
    assert lookup["hit"] is False
    assert lookup["reason"] == "cache_entry_not_active"


def test_artifact_cache_pin_protects_cached_storage_object_from_gc(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    run_spec = _run_spec("run_cache_pin_gc", revision["workflowRevisionId"])
    _create_terminal_run(cfg, run_spec)
    persist_artifact(
        cfg,
        run_id="run_cache_pin_gc",
        kind="report",
        path=_managed_report(cfg, "run_cache_pin_gc", b"pinned cache\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )
    lookup = lookup_artifact_cache_entry(cfg, _lookup_payload(revision["workflowRevisionId"]))
    pins = create_artifact_cache_pins(
        cfg,
        entries=[lookup["entry"]],
        pin_scope="policy",
        owner_kind="operator",
        owner_id="retain-cache-object",
        reason="operator-retain",
        ttl_seconds=None,
    )

    plan = preview_artifact_gc(cfg, {"retentionDays": 30})

    assert pins[0]["state"] == "active"
    assert plan["candidateCount"] == 0
    assert plan["protected"][0]["storageUri"] == lookup["entry"]["storageUri"]
    assert ARTIFACT_CACHE_PIN_PROTECTION_REASON in plan["protected"][0]["reasons"]


def test_artifact_cache_policy_pin_retain_and_release_controls_gc(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    run_spec = _run_spec("run_cache_policy_pin", revision["workflowRevisionId"])
    _create_terminal_run(cfg, run_spec)
    persist_artifact(
        cfg,
        run_id="run_cache_policy_pin",
        kind="report",
        path=_managed_report(cfg, "run_cache_policy_pin", b"operator retained\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )
    lookup = lookup_artifact_cache_entry(cfg, _lookup_payload(revision["workflowRevisionId"]))

    pin = retain_artifact_cache_policy_pin(
        cfg,
        lookup["entry"]["cacheEntryId"],
        {"ownerId": "curator@example.test", "reason": "retain-for-review"},
        actor="curator@example.test",
    )
    protected = preview_artifact_gc(cfg, {"retentionDays": 30})
    listed = list_artifact_cache_policy_pins(
        cfg,
        cache_entry_id=lookup["entry"]["cacheEntryId"],
        state="active",
    )["items"]
    retain_audit = list_governance_audit_events(cfg, action="artifact.cache_pin.retain")["items"]

    assert pin["pinScope"] == "policy"
    assert pin["ownerKind"] == "operator"
    assert pin["expiresAt"] is None
    assert protected["candidateCount"] == 0
    assert ARTIFACT_CACHE_PIN_PROTECTION_REASON in protected["protected"][0]["reasons"]
    assert [item["cachePinId"] for item in listed] == [pin["cachePinId"]]
    assert retain_audit[-1]["details"]["cacheEntryId"] == lookup["entry"]["cacheEntryId"]
    assert "cacheKey" not in retain_audit[-1]["details"]
    assert "storageUri" not in retain_audit[-1]["details"]

    released = release_artifact_cache_policy_pin(
        cfg,
        pin["cachePinId"],
        {"confirmation": ARTIFACT_CACHE_POLICY_PIN_RELEASE_CONFIRMATION, "reason": "review-complete"},
        actor="curator@example.test",
    )
    unprotected = preview_artifact_gc(cfg, {"retentionDays": 30})
    release_audit = list_governance_audit_events(cfg, action="artifact.cache_pin.release")["items"]

    assert released["state"] == "released"
    assert released["releasedAt"]
    assert list_artifact_cache_policy_pins(cfg, cache_entry_id=lookup["entry"]["cacheEntryId"], state="active")[
        "items"
    ] == []
    assert unprotected["candidateCount"] == 1
    assert release_audit[-1]["details"]["cacheEntryId"] == lookup["entry"]["cacheEntryId"]


def test_artifact_cache_policy_release_rejects_restore_pins(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    run_spec = _run_spec("run_cache_restore_pin_release", revision["workflowRevisionId"])
    _create_terminal_run(cfg, run_spec)
    persist_artifact(
        cfg,
        run_id="run_cache_restore_pin_release",
        kind="report",
        path=_managed_report(cfg, "run_cache_restore_pin_release", b"restore pin\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )
    lookup = lookup_artifact_cache_entry(cfg, _lookup_payload(revision["workflowRevisionId"]))
    restore_pin = create_artifact_cache_pins(
        cfg,
        entries=[lookup["entry"]],
        pin_scope=ARTIFACT_CACHE_RESTORE_PIN_SCOPE,
        owner_kind=ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND,
        owner_id="attempt_restore:1",
        reason="cache_restore",
    )[0]

    with pytest.raises(ValueError, match="ARTIFACT_CACHE_PIN_SCOPE_UNSUPPORTED"):
        release_artifact_cache_policy_pin(
            cfg,
            restore_pin["cachePinId"],
            {"confirmation": ARTIFACT_CACHE_POLICY_PIN_RELEASE_CONFIRMATION},
            actor="curator@example.test",
        )


def test_artifact_cache_hit_adopts_cached_artifact_for_current_attempt(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    source_spec = _run_spec("run_cache_source", revision["workflowRevisionId"])
    target_spec = _run_spec("run_cache_adopt", revision["workflowRevisionId"])
    _create_terminal_run(cfg, source_spec)
    source = persist_artifact(
        cfg,
        run_id="run_cache_source",
        kind="report",
        path=_managed_report(cfg, "run_cache_source", b"reused output\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )
    claim = _create_active_attempt(cfg, target_spec)

    adopted = try_adopt_cached_outputs(
        cfg,
        run_id="run_cache_adopt",
        request_id="req_run_cache_adopt",
        run_spec=target_spec,
        output_schema=_output_schema(),
        outputs={"report": str(Path(cfg.results_dir) / "run_cache_adopt" / "report.txt")},
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        result_dir=str(Path(cfg.results_dir) / "run_cache_adopt"),
    )

    restored_path = Path(cfg.results_dir) / "run_cache_adopt" / "report.txt"
    results = fetch_run_results(cfg, "run_cache_adopt")
    events = list_evidence_events(cfg, event_type="artifact.cache.adopt.v1")
    materializations = list_artifact_materializations(cfg, source["artifactBlobId"])
    pins = list_artifact_cache_pins(cfg, cache_entry_id=events[-1]["payload"]["cacheEntryId"])["items"]
    with get_connection(cfg) as connection:
        run = connection.execute(
            "SELECT status, stage FROM runs WHERE run_id = ?",
            ("run_cache_adopt",),
        ).fetchone()
        attempt = connection.execute(
            "SELECT output_adoption_state FROM run_attempts WHERE attempt_id = ?",
            (claim["attemptId"],),
        ).fetchone()
        lineage = connection.execute(
            "SELECT predicate, workflow_revision_id FROM lineage_edges WHERE run_id = ?",
            ("run_cache_adopt",),
        ).fetchone()
        run_event = connection.execute(
            """
            SELECT details_json
            FROM run_events
            WHERE run_id = ? AND event_type = 'status-transition'
            ORDER BY seq DESC
            LIMIT 1
            """,
            ("run_cache_adopt",),
        ).fetchone()
    run_event_payload = json.loads(run_event["details_json"])["payload"]

    assert adopted["adopted"] is True
    assert adopted["reason"] == "cache_hit"
    assert adopted["artifactIds"] == [results["artifacts"][0]["artifactId"]]
    assert results["artifacts"][0]["artifactId"] != source["artifactId"]
    assert results["artifacts"][0]["sha256"] == source["sha256"]
    assert results["artifacts"][0]["path"] == str(restored_path.resolve())
    assert results["artifacts"][0]["storageBackend"] == "local"
    assert results["artifacts"][0]["storageUri"] == restored_path.resolve().as_uri()
    assert restored_path.read_bytes() == b"reused output\n"
    assert any(item["localPath"] == str(restored_path.resolve()) for item in materializations)
    assert run["status"] == "completed"
    assert run["stage"] == "cache"
    assert attempt["output_adoption_state"] == "adopted"
    assert lineage["predicate"] == "h2ometa:cache_adopted"
    assert lineage["workflow_revision_id"] == revision["workflowRevisionId"]
    assert events[-1]["payload"]["sourceArtifactId"] == source["artifactId"]
    assert events[-1]["payload"]["artifactId"] == results["artifacts"][0]["artifactId"]
    assert events[-1]["payload"]["sourceStorageUri"] == source["storageUri"]
    assert events[-1]["payload"]["localPath"] == str(restored_path.resolve())
    assert adopted["cachePinIds"] == [pins[0]["cachePinId"]]
    assert pins[0]["pinScope"] == ARTIFACT_CACHE_RESTORE_PIN_SCOPE
    assert pins[0]["ownerKind"] == ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND
    assert pins[0]["ownerId"] == f"{claim['attemptId']}:{claim['leaseGeneration']}"
    assert pins[0]["state"] == "released"
    assert pins[0]["releasedAt"]
    assert events[-1]["payload"]["cachePinId"] == pins[0]["cachePinId"]
    assert run_event_payload["cachePinIds"] == adopted["cachePinIds"]
    assert run_event_payload["restoredPaths"] == [str(restored_path.resolve())]
    assert run_event_payload["restoredMaterializationIds"] == [
        events[-1]["payload"]["restoredMaterializationId"]
    ]


def test_artifact_cache_adoption_skips_when_cached_payload_is_unavailable(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    source_spec = _run_spec("run_cache_source_missing_payload", revision["workflowRevisionId"])
    target_spec = _run_spec("run_cache_adopt_missing_payload", revision["workflowRevisionId"])
    _create_terminal_run(cfg, source_spec)
    source_path = _managed_report(cfg, "run_cache_source_missing_payload", b"missing later\n")
    persist_artifact(
        cfg,
        run_id="run_cache_source_missing_payload",
        kind="report",
        path=source_path,
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )
    source_path.unlink()
    claim = _create_active_attempt(cfg, target_spec)

    adopted = try_adopt_cached_outputs(
        cfg,
        run_id="run_cache_adopt_missing_payload",
        request_id="req_run_cache_adopt_missing_payload",
        run_spec=target_spec,
        output_schema=_output_schema(),
        outputs={"report": str(Path(cfg.results_dir) / "run_cache_adopt_missing_payload" / "report.txt")},
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        result_dir=str(Path(cfg.results_dir) / "run_cache_adopt_missing_payload"),
    )

    assert adopted["adopted"] is False
    assert adopted["reason"] == "cache_miss"
    assert adopted["misses"][0]["reason"] == "artifact_unavailable"
    assert fetch_run_results(cfg, "run_cache_adopt_missing_payload")["artifacts"] == []


def test_artifact_cache_lookup_and_adoption_reject_unmanaged_local_payload(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    source_spec = _run_spec("run_cache_source_unmanaged", revision["workflowRevisionId"])
    target_spec = _run_spec("run_cache_adopt_unmanaged", revision["workflowRevisionId"])
    _create_terminal_run(cfg, source_spec)
    source = persist_artifact(
        cfg,
        run_id="run_cache_source_unmanaged",
        kind="report",
        path=_managed_report(cfg, "run_cache_source_unmanaged", b"cached outside\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )
    outside = tmp_path / "outside-cache-hit.txt"
    outside.write_bytes(b"cached outside\n")
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE artifact_cache_entries
            SET storage_uri = ?
            WHERE artifact_id = ?
            """,
            (outside.resolve().as_uri(), source["artifactId"]),
        )
        connection.commit()
    lookup = lookup_artifact_cache_entry(cfg, _lookup_payload(revision["workflowRevisionId"]))
    claim = _create_active_attempt(cfg, target_spec)

    adopted = try_adopt_cached_outputs(
        cfg,
        run_id="run_cache_adopt_unmanaged",
        request_id="req_run_cache_adopt_unmanaged",
        run_spec=target_spec,
        output_schema=_output_schema(),
        outputs={"report": str(Path(cfg.results_dir) / "run_cache_adopt_unmanaged" / "report.txt")},
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        result_dir=str(Path(cfg.results_dir) / "run_cache_adopt_unmanaged"),
    )

    assert lookup["hit"] is False
    assert lookup["reason"] == "artifact_unmanaged"
    assert adopted["adopted"] is False
    assert adopted["reason"] == "cache_miss"
    assert adopted["misses"][0]["reason"] == "artifact_unmanaged"
    assert fetch_run_results(cfg, "run_cache_adopt_unmanaged")["artifacts"] == []


def test_artifact_cache_adoption_rejects_stale_lease_before_lookup(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    source_spec = _run_spec("run_cache_source_stale", revision["workflowRevisionId"])
    target_spec = _run_spec("run_cache_adopt_stale", revision["workflowRevisionId"])
    _create_terminal_run(cfg, source_spec)
    persist_artifact(
        cfg,
        run_id="run_cache_source_stale",
        kind="report",
        path=_managed_report(cfg, "run_cache_source_stale", b"stale lease\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )
    claim = _create_active_attempt(cfg, target_spec)
    before_events = list_evidence_events(cfg, event_type="artifact.cache.lookup.v1")

    with pytest.raises(StaleRunAttemptError, match="RUN_ATTEMPT_STALE"):
        try_adopt_cached_outputs(
            cfg,
            run_id="run_cache_adopt_stale",
            request_id="req_run_cache_adopt_stale",
            run_spec=target_spec,
            output_schema=_output_schema(),
            outputs={"report": str(Path(cfg.results_dir) / "run_cache_adopt_stale" / "report.txt")},
            attempt_id=claim["attemptId"],
            lease_generation=claim["leaseGeneration"] + 1,
            result_dir=str(Path(cfg.results_dir) / "run_cache_adopt_stale"),
        )

    after_events = list_evidence_events(cfg, event_type="artifact.cache.lookup.v1")
    assert after_events == before_events
    assert fetch_run_results(cfg, "run_cache_adopt_stale")["artifacts"] == []


def _create_revision(cfg) -> dict[str, Any]:
    return create_or_fetch_workflow_revision(
        cfg,
        draft_id="draft_cache",
        draft_revision=1,
        manifest={"files": [{"path": "workflow/Snakefile", "sha256": "snake"}]},
        graph_snapshot={"nodes": [{"id": "summarize", "toolRevisionId": "tool#1"}]},
        runtime_lock={"snakemake": "9.23.1", "python": "3.12"},
        compiler={"name": "h2ometa", "version": "cache-test"},
    )


def _run_spec(run_id: str, workflow_revision_id: str, *, inputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "runId": run_id,
        "projectId": "proj_cache",
        "pipelineId": "pipeline_cache",
        "pipelineVersion": "0.1.0",
        "workflowRevisionId": workflow_revision_id,
        "inputs": inputs or [{"name": "reads", "sha256": "sha256:reads"}],
        "params": {"threshold": 3},
        "resourceBindings": {"taxonomy": {"databaseId": "db_ref", "templateId": "kraken2"}},
        "execution": {"profile": "default"},
    }


def _lookup_payload(workflow_revision_id: str, *, inputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "workflowRevisionId": workflow_revision_id,
        "artifactKey": "report",
        "stepId": "summarize",
        "role": "output",
        "inputs": inputs or [{"name": "reads", "sha256": "sha256:reads"}],
        "params": {"threshold": 3},
        "resourceBindings": {"taxonomy": {"databaseId": "db_ref", "templateId": "kraken2"}},
        "execution": {"profile": "default"},
    }


def _output_schema() -> dict[str, Any]:
    return {
        "artifacts": [
            {
                "key": "report",
                "kind": "report",
                "mimeType": "text/plain",
                "stepId": "summarize",
            }
        ]
    }


def _create_terminal_run(cfg, run_spec: dict[str, Any]) -> None:
    create_run_record(
        cfg,
        server_id="srv_cache",
        request_id=f"req_{run_spec['runId']}",
        run_spec=run_spec,
        idempotency_key=f"idem_{run_spec['runId']}",
        payload_hash=f"hash_{run_spec['runId']}",
    )
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = 'completed',
                stage = 'complete',
                finished_at = '2025-01-01T00:00:00Z',
                last_updated_at = '2025-01-01T00:00:00Z'
            WHERE run_id = ?
            """,
            (run_spec["runId"],),
        )
        connection.execute(
            "UPDATE run_jobs SET state = 'completed', updated_at = '2025-01-01T00:00:00Z' WHERE run_id = ?",
            (run_spec["runId"],),
        )
        connection.commit()


def _create_active_attempt(cfg, run_spec: dict[str, Any]) -> dict[str, Any]:
    create_run_record(
        cfg,
        server_id="srv_cache",
        request_id=f"req_{run_spec['runId']}",
        run_spec=run_spec,
        idempotency_key=f"idem_{run_spec['runId']}",
        payload_hash=f"hash_{run_spec['runId']}",
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_cache",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    return claim


def _managed_report(cfg, run_id: str, payload: bytes) -> Path:
    path = Path(cfg.results_dir) / run_id / "report.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _upload(cfg, filename: str, payload: bytes) -> dict[str, Any]:
    return persist_upload(
        cfg,
        filename=filename,
        content_base64=base64.b64encode(payload).decode("ascii"),
        mime_type="text/plain",
    )
