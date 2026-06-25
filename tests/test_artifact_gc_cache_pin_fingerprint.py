from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.artifact_cache_pin_service import retain_artifact_cache_policy_pin
from apps.remote_runner.artifact_cache_storage import (
    ARTIFACT_CACHE_PIN_PROTECTION_REASON,
    lookup_artifact_cache_entry,
)
from apps.remote_runner.artifact_lifecycle_service import ARTIFACT_GC_CONFIRMATION, preview_artifact_gc, run_artifact_gc
from apps.remote_runner.execution_query_storage import fetch_run_results
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.storage import persist_artifact
from tests.helpers.reference_database import make_configured_remote_runner
from tests.test_artifact_cache_storage import (
    _create_revision,
    _create_terminal_run,
    _lookup_payload,
    _managed_report,
    _run_spec,
)


def test_artifact_gc_rejects_stale_fingerprint_when_cache_pin_protects_candidate(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    run_spec = _run_spec("run_cache_pin_stale_gc", revision["workflowRevisionId"])
    _create_terminal_run(cfg, run_spec)
    artifact = persist_artifact(
        cfg,
        run_id="run_cache_pin_stale_gc",
        kind="report",
        path=_managed_report(cfg, "run_cache_pin_stale_gc", b"stale pinned cache\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )
    preview = preview_artifact_gc(cfg, {"retentionDays": 30})
    lookup = lookup_artifact_cache_entry(cfg, _lookup_payload(revision["workflowRevisionId"]))

    retain_artifact_cache_policy_pin(
        cfg,
        lookup["entry"]["cacheEntryId"],
        {"ownerId": "curator@example.test", "reason": "protect-between-preview-and-run"},
        actor="curator@example.test",
    )
    with pytest.raises(ValueError, match="ARTIFACT_GC_PLAN_FINGERPRINT_MISMATCH"):
        run_artifact_gc(
            cfg,
            {
                "retentionDays": 30,
                "confirmation": ARTIFACT_GC_CONFIRMATION,
                "planFingerprint": preview["planFingerprint"],
            },
        )
    denial = list_governance_audit_events(cfg, action="artifact.gc.run")["items"][-1]
    current = preview_artifact_gc(cfg, {"retentionDays": 30})
    result = run_artifact_gc(
        cfg,
        {
            "retentionDays": 30,
            "confirmation": ARTIFACT_GC_CONFIRMATION,
            "planFingerprint": current["planFingerprint"],
        },
    )
    fetched = fetch_run_results(cfg, "run_cache_pin_stale_gc")["artifacts"][0]

    assert Path(artifact["path"]).is_file()
    assert fetched["lifecycleState"] == "active"
    assert current["candidateCount"] == 0
    assert result["deletedCount"] == 0
    assert ARTIFACT_CACHE_PIN_PROTECTION_REASON in current["protected"][0]["reasons"]
    assert denial["reasonCode"] == "ARTIFACT_GC_PLAN_FINGERPRINT_MISMATCH"
    assert denial["details"]["deletedCount"] == 0
