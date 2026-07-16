from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "apps" / "web" / "app" / "components" / "agent-workbench-state-helpers.ts"


def _source() -> str:
    return HELPERS.read_text(encoding="utf-8")


def _between(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def test_snapshot_merge_selects_one_complete_snapshot_without_synthesizing_items() -> None:
    source = _source()
    merge = _between(
        source,
        "export function mergeAgentSnapshots(",
        "export function isUncertainCommandFailure",
    )

    assert "assertAgentSnapshotConsistent(next)" in merge
    assert "assertImmutableSnapshotHistory(current, next)" in merge
    assert "agentSessionLineage(current.session), agentSessionLineage(next.session)" in merge
    assert "snapshotHistoryContains(next, current)" in merge
    assert "snapshotHistoryContains(current, next)" in merge
    assert "assertSnapshotHistoryContains(next, current)" in merge
    assert "assertSnapshotHistoryContains(current, next)" in merge
    assert "return next" in merge
    assert "return current" in merge
    assert "mergeAgentItems" not in source
    assert "events:" not in merge
    assert "plans:" not in merge
    assert "approvals:" not in merge


def test_same_version_sessions_and_shared_item_ids_must_be_deeply_equivalent() -> None:
    source = _source()
    newer_session = _between(source, "function newerAgentSession(", "function assertAgentSnapshotConsistent")
    immutable_history = _between(
        source,
        "function assertImmutableSnapshotHistory(",
        "function assertSnapshotHistoryContains(",
    )

    assert "agentSessionProjection(left), agentSessionProjection(right)" in newer_session
    for field in (
        "activeDraftId",
        "activeDraftRevision",
        "activePlanHash",
        "workflowRevisionId",
        "cancelledAt",
    ):
        assert f"{field}: session.{field} ?? null" in newer_session
    assert "goal: session.goal" in newer_session
    assert "agentJsonEqual(existing, item)" in immutable_history
    assert "AGENT_SESSION_SNAPSHOT_IMMUTABLE_CONFLICT" in source


def test_newer_session_versions_preserve_immutable_lineage_fields() -> None:
    source = _source()
    newer_session = _between(source, "function newerAgentSession(", "function assertAgentSnapshotConsistent")

    assert "assertImmutableEquivalent(agentSessionLineage(left), agentSessionLineage(right))" in newer_session
    for field in (
        "projectId",
        "goal",
        "constraints",
        "budget",
        "creationRequestId",
        "createdBy",
        "createdAt",
    ):
        assert f"{field}: session.{field}" in newer_session


def test_snapshot_consistency_rejects_future_state_and_enforces_status_bound_active_plan() -> None:
    source = _source()
    consistency = _between(
        source,
        "function assertAgentSnapshotConsistent(",
        "function assertUniqueScopedItems",
    )

    assert "event.stateVersion > session.stateVersion" in consistency
    assert "event.planGeneration > session.planGeneration" in consistency
    assert "plan.planGeneration > session.planGeneration" in consistency
    assert "approval.planGeneration > session.planGeneration" in consistency
    assert "currentGenerationPlans.length" in consistency
    assert '"plan_failed"' in consistency
    assert 'session.status === "created"' in consistency
    assert "currentGenerationPlans[0].planHash !== session.activePlanHash" in consistency
    assert "currentGenerationPlans[0].draftId !== session.activeDraftId" in consistency
    assert "currentGenerationPlans[0].draftRevision !== session.activeDraftRevision" in consistency
    assert "AGENT_SESSION_SNAPSHOT_INCONSISTENT" in source
