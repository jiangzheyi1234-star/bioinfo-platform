from __future__ import annotations

import json

from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.resource_storage import (
    apply_resource,
    enqueue_reconcile,
    mark_resource_for_deletion,
    record_reconcile_failure,
)
from tests.helpers.reference_database import make_configured_remote_runner


def test_apply_resource_is_idempotent_and_bumps_generation_on_desired_change(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)

    first = apply_resource(
        cfg,
        kind="RemoteRuntime",
        name="local-edge",
        desired={"runnerVersion": "2026.6.0"},
        owner_kind="Project",
        owner_id="proj_demo",
        finalizers=["h2ometa.io/runtime-cleanup"],
    )
    replay = apply_resource(
        cfg,
        kind="RemoteRuntime",
        name="local-edge",
        desired={"runnerVersion": "2026.6.0"},
        owner_kind="Project",
        owner_id="proj_demo",
        finalizers=["h2ometa.io/runtime-cleanup"],
    )
    changed = apply_resource(
        cfg,
        kind="RemoteRuntime",
        name="local-edge",
        desired={"runnerVersion": "2026.6.1"},
        owner_kind="Project",
        owner_id="proj_demo",
        finalizers=["h2ometa.io/runtime-cleanup"],
    )

    assert replay["resourceId"] == first["resourceId"]
    assert first["generation"] == 1
    assert replay["generation"] == 1
    assert changed["generation"] == 2
    assert changed["observedGeneration"] == 0
    assert changed["ownerKind"] == "Project"
    assert changed["ownerId"] == "proj_demo"

    with get_connection(cfg) as connection:
        events = connection.execute(
            "SELECT seq, event_type FROM resource_events WHERE resource_id = ? ORDER BY seq",
            (first["resourceId"],),
        ).fetchall()
    assert [(row["seq"], row["event_type"]) for row in events] == [
        (1, "resource_created"),
        (2, "resource_desired_changed"),
    ]


def test_mark_resource_for_deletion_sets_timestamp_and_keeps_finalizers(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    resource = apply_resource(
        cfg,
        kind="RunnerRelease",
        name="release-2026-06",
        desired={"buildId": "build_1"},
        finalizers=["h2ometa.io/delete-release-files"],
        conditions=[{"type": "Ready", "status": "True"}],
    )

    deleted = mark_resource_for_deletion(
        cfg,
        resource["resourceId"],
        deleted_at="2026-06-07T10:00:00Z",
    )
    replay = mark_resource_for_deletion(
        cfg,
        resource["resourceId"],
        deleted_at="2026-06-07T10:05:00Z",
    )

    assert deleted["deletionTimestamp"] == "2026-06-07T10:00:00Z"
    assert replay["deletionTimestamp"] == "2026-06-07T10:00:00Z"
    assert deleted["finalizers"] == ["h2ometa.io/delete-release-files"]
    assert deleted["conditions"] == [{"type": "Ready", "status": "True"}]

    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT finalizers_json, conditions_json FROM resources WHERE resource_id = ?",
            (resource["resourceId"],),
        ).fetchone()
    assert json.loads(row["finalizers_json"]) == ["h2ometa.io/delete-release-files"]
    assert json.loads(row["conditions_json"]) == [{"type": "Ready", "status": "True"}]


def test_owner_reference_must_be_paired_and_finalizers_are_deduplicated(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)

    try:
        apply_resource(
            cfg,
            kind="RemoteRuntime",
            name="missing-owner-id",
            desired={},
            owner_kind="Project",
        )
    except ValueError as exc:
        assert str(exc) == "RESOURCE_OWNER_REF_INCOMPLETE"
    else:
        raise AssertionError("owner_kind without owner_id should fail")

    resource = apply_resource(
        cfg,
        kind="RemoteRuntime",
        name="dedupe-finalizers",
        desired={},
        finalizers=["h2ometa.io/cleanup", "h2ometa.io/cleanup", "h2ometa.io/audit"],
    )

    assert resource["finalizers"] == ["h2ometa.io/cleanup", "h2ometa.io/audit"]


def test_reconcile_queue_deduplicates_and_uses_bounded_backoff(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    resource = apply_resource(
        cfg,
        kind="RunJob",
        name="run_123",
        desired={"runId": "run_123"},
        owner_kind="Run",
        owner_id="run_123",
    )

    first = enqueue_reconcile(
        cfg,
        resource["resourceId"],
        reason="desired_changed",
        now="2026-06-07T10:00:00Z",
    )
    replay = enqueue_reconcile(
        cfg,
        resource["resourceId"],
        reason="desired_changed",
        now="2026-06-07T10:00:05Z",
    )
    failed = record_reconcile_failure(
        cfg,
        first["itemId"],
        error="runner not reachable",
        now="2026-06-07T10:00:10Z",
        max_backoff_seconds=16,
    )

    assert replay["itemId"] == first["itemId"]
    assert failed["attempts"] == 1
    assert failed["state"] == "pending"
    assert 2 <= failed["backoffSeconds"] <= 16
    assert failed["availableAt"] > "2026-06-07T10:00:10Z"
    assert failed["lastError"] == "runner not reachable"

    exhausted = failed
    for _ in range(12):
        exhausted = record_reconcile_failure(
            cfg,
            first["itemId"],
            error="still failing",
            now="2026-06-07T10:01:00Z",
            max_backoff_seconds=16,
        )
    assert exhausted["state"] == "exhausted"
    assert exhausted["backoffSeconds"] <= 16


def test_reconcile_queue_dedup_key_is_scoped_by_resource_and_reason(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    first_resource = apply_resource(
        cfg,
        kind="RunJob",
        name="run_1",
        desired={"runId": "run_1"},
    )
    second_resource = apply_resource(
        cfg,
        kind="RunJob",
        name="run_2",
        desired={"runId": "run_2"},
    )

    first = enqueue_reconcile(
        cfg,
        first_resource["resourceId"],
        reason="desired_changed",
        now="2026-06-07T10:00:00Z",
    )
    first_replay = enqueue_reconcile(
        cfg,
        first_resource["resourceId"],
        reason="desired_changed",
        now="2026-06-07T10:00:05Z",
    )
    second = enqueue_reconcile(
        cfg,
        second_resource["resourceId"],
        reason="desired_changed",
        now="2026-06-07T10:00:10Z",
    )

    assert first_replay["itemId"] == first["itemId"]
    assert second["itemId"] != first["itemId"]
    assert first["dedupKey"] == f"{first_resource['resourceId']}:desired_changed"
    assert second["dedupKey"] == f"{second_resource['resourceId']}:desired_changed"


def test_custom_reconcile_dedup_key_is_still_scoped_by_resource(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    first_resource = apply_resource(
        cfg,
        kind="RunnerRelease",
        name="release-a",
        desired={"buildId": "build_a"},
    )
    second_resource = apply_resource(
        cfg,
        kind="RunnerRelease",
        name="release-b",
        desired={"buildId": "build_b"},
    )

    first = enqueue_reconcile(
        cfg,
        first_resource["resourceId"],
        reason="desired_changed",
        dedup_key="release",
        now="2026-06-07T10:00:00Z",
    )
    second = enqueue_reconcile(
        cfg,
        second_resource["resourceId"],
        reason="desired_changed",
        dedup_key="release",
        now="2026-06-07T10:00:05Z",
    )

    assert first["itemId"] != second["itemId"]
    assert first["dedupKey"] == f"{first_resource['resourceId']}:release"
    assert second["dedupKey"] == f"{second_resource['resourceId']}:release"


def test_exhausted_reconcile_item_can_be_reactivated_by_new_desired_state(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    resource = apply_resource(
        cfg,
        kind="RunnerRelease",
        name="release-reactivate",
        desired={"buildId": "build_1"},
    )
    item = enqueue_reconcile(
        cfg,
        resource["resourceId"],
        reason="desired_changed",
        now="2026-06-07T10:00:00Z",
        max_attempts=1,
    )
    exhausted = record_reconcile_failure(
        cfg,
        item["itemId"],
        error="failed once",
        now="2026-06-07T10:01:00Z",
    )

    reactivated = enqueue_reconcile(
        cfg,
        resource["resourceId"],
        reason="desired_changed",
        now="2026-06-07T10:02:00Z",
    )

    assert exhausted["state"] == "exhausted"
    assert reactivated["itemId"] == item["itemId"]
    assert reactivated["state"] == "pending"
    assert reactivated["attempts"] == 0
    assert reactivated["backoffSeconds"] == 1
    assert reactivated["lastError"] is None
    assert reactivated["availableAt"] == "2026-06-07T10:02:00Z"
