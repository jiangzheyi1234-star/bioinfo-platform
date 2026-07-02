from __future__ import annotations

from pathlib import Path

from apps.remote_runner.artifact_cache_storage import (
    ARTIFACT_CACHE_PIN_PROTECTION_REASON,
    create_artifact_cache_pins,
    list_artifact_cache_entries,
    lookup_artifact_cache_entry,
)
from apps.remote_runner.artifact_cache_pin_service import (
    ARTIFACT_CACHE_POLICY_PIN_RELEASE_CONFIRMATION,
    list_artifact_cache_policy_pins,
    release_artifact_cache_policy_pin,
    retain_artifact_cache_policy_pin,
)
from apps.remote_runner.artifact_lifecycle_service import ARTIFACT_GC_CONFIRMATION, preview_artifact_gc, run_artifact_gc
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.storage import persist_artifact
from tests.helpers.reference_database import make_configured_remote_runner
from tests.test_artifact_cache_storage import (
    _create_revision,
    _create_terminal_run,
    _gc_policy,
    _lookup_payload,
    _managed_report,
    _run_spec,
)


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

    plan = preview_artifact_gc(cfg, _gc_policy())
    run_artifact_gc(
        cfg,
        {
            **_gc_policy(),
            "confirmation": ARTIFACT_GC_CONFIRMATION,
            "planFingerprint": plan["planFingerprint"],
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

    plan = preview_artifact_gc(cfg, _gc_policy())

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
    protected = preview_artifact_gc(cfg, _gc_policy())
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
    unprotected = preview_artifact_gc(cfg, _gc_policy())
    release_audit = list_governance_audit_events(cfg, action="artifact.cache_pin.release")["items"]

    assert released["state"] == "released"
    assert released["releasedAt"]
    assert list_artifact_cache_policy_pins(cfg, cache_entry_id=lookup["entry"]["cacheEntryId"], state="active")[
        "items"
    ] == []
    assert unprotected["candidateCount"] == 1
    assert release_audit[-1]["details"]["cacheEntryId"] == lookup["entry"]["cacheEntryId"]
