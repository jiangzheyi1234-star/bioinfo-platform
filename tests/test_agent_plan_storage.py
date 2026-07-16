from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from apps.remote_runner.agent_plan_storage import (
    AgentPlanStorageConflictError,
    create_agent_plan_revision,
    fetch_agent_plan_revision,
    list_agent_approvals,
    list_agent_plan_revisions,
    record_agent_approval,
)
from apps.remote_runner.agent_session_storage import create_agent_session, transition_agent_session
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_design_storage import create_workflow_design_draft, fork_workflow_design_draft
from tests.helpers.workflow_design_drafts import workflow_design_config, workflow_design_draft


def _budget() -> dict[str, int]:
    return {
        "maxModelTurns": 8,
        "maxToolCalls": 12,
        "maxReplans": 3,
        "maxRetries": 2,
        "maxWallClockSeconds": 3_600,
    }


def _planning_session(tmp_path: Path):
    cfg = workflow_design_config(tmp_path)
    session = create_agent_session(
        cfg,
        project_id="proj_design",
        goal={"summary": "Inspect FASTQ quality", "successCriteria": ["Produce a QC report"]},
        constraints={
            "forbiddenActions": ["arbitrary_shell"],
            "requirements": {"networkAccess": "declared-only"},
        },
        budget=_budget(),
        creation_request_id="create-plan-session",
        created_by="user-1",
    )
    planning = transition_agent_session(
        cfg,
        session["sessionId"],
        expected_state_version=1,
        event_type="agent.plan_requested",
        to_status="planning",
        request_id="plan-request-1",
        actor="user-1",
        idempotency_key="plan-request-1",
        payload={"planner": {"adapterId": "fixture.fastq-qc.v1"}},
        plan_generation=1,
        planner={"adapterId": "fixture.fastq-qc.v1", "adapterVersion": "1"},
    )
    draft = create_workflow_design_draft(cfg, workflow_design_draft())
    proposal = {
        "draft": draft["draft"],
        "planner": {"adapterId": "fixture.fastq-qc.v1", "adapterVersion": "1"},
    }
    return cfg, planning["session"], draft, proposal


def _create_first_plan(tmp_path: Path):
    cfg, session, draft, proposal = _planning_session(tmp_path)
    plan = create_agent_plan_revision(
        cfg,
        session_id=session["sessionId"],
        plan_generation=1,
        draft_id=draft["draftId"],
        draft_revision=draft["revision"],
        proposal=proposal,
        validation={"valid": True, "issues": [], "toolRevisionCount": 1},
        budget=_budget(),
        created_by="fixture.fastq-qc.v1",
    )
    awaiting = transition_agent_session(
        cfg,
        session["sessionId"],
        expected_state_version=session["stateVersion"],
        expected_plan_generation=1,
        event_type="agent.plan_validated",
        to_status="awaiting_approval",
        request_id="plan-validated-1",
        actor="fixture.fastq-qc.v1",
        idempotency_key="plan-validated-1",
        payload={
            "planRevisionId": plan["planRevisionId"],
            "draftId": draft["draftId"],
            "draftRevision": draft["revision"],
            "planHash": plan["planHash"],
        },
        active_draft_id=draft["draftId"],
        active_draft_revision=draft["revision"],
        active_plan_hash=plan["planHash"],
    )
    return cfg, awaiting["session"], draft, proposal, plan


def test_agent_plan_revision_is_immutable_idempotent_and_bound_to_draft(tmp_path: Path) -> None:
    cfg, session, draft, proposal, plan = _create_first_plan(tmp_path)

    replay = create_agent_plan_revision(
        cfg,
        session_id=session["sessionId"],
        plan_generation=1,
        draft_id=draft["draftId"],
        draft_revision=draft["revision"],
        proposal=proposal,
        validation={"valid": True, "issues": [], "toolRevisionCount": 1},
        budget=_budget(),
        created_by="fixture.fastq-qc.v1",
    )

    assert replay == plan
    assert len(plan["planHash"]) == 64
    assert hashlib.sha256(plan["canonicalPayload"].encode("utf-8")).hexdigest() == plan["planHash"]
    assert json.loads(plan["canonicalPayload"])["proposal"] == plan["proposal"]
    assert fetch_agent_plan_revision(cfg, plan["planRevisionId"]) == plan
    assert list_agent_plan_revisions(cfg, session["sessionId"]) == [plan]

    changed = dict(proposal)
    changed["planner"] = {"adapterId": "different-adapter"}
    with pytest.raises(AgentPlanStorageConflictError, match="AGENT_PLAN_GENERATION_ALREADY_COMMITTED"):
        create_agent_plan_revision(
            cfg,
            session_id=session["sessionId"],
            plan_generation=1,
            draft_id=draft["draftId"],
            draft_revision=draft["revision"],
            proposal=changed,
            validation={"valid": True},
            budget=_budget(),
            created_by="different-adapter",
        )

    with get_connection(cfg) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="AGENT_PLAN_REVISION_IMMUTABLE"):
            connection.execute(
                "UPDATE agent_plan_revisions SET plan_hash = ? WHERE plan_revision_id = ?",
                ("f" * 64, plan["planRevisionId"]),
            )
        with pytest.raises(sqlite3.IntegrityError, match="AGENT_PLAN_REVISION_IMMUTABLE"):
            connection.execute(
                "DELETE FROM agent_plan_revisions WHERE plan_revision_id = ?",
                (plan["planRevisionId"],),
            )


def test_agent_approval_is_plan_bound_idempotent_and_immutable(tmp_path: Path) -> None:
    cfg, session, _draft, _proposal, plan = _create_first_plan(tmp_path)
    command = {
        "session_id": session["sessionId"],
        "plan_revision_id": plan["planRevisionId"],
        "expected_state_version": session["stateVersion"],
        "expected_plan_hash": plan["planHash"],
        "decision": "approve",
        "actor": "user-1",
        "request_id": "approve-request-1",
        "idempotency_key": "approve-request-1",
        "reason": "Reviewed exact tools and parameters",
    }

    approval = record_agent_approval(cfg, **command)
    replay = record_agent_approval(cfg, **command)

    assert replay == approval
    assert approval["scope"] == "compile_workflow_revision"
    assert list_agent_approvals(cfg, session["sessionId"]) == [approval]

    with pytest.raises(AgentPlanStorageConflictError, match="AGENT_APPROVAL_IDEMPOTENCY_CONFLICT"):
        record_agent_approval(cfg, **(command | {"decision": "request_changes", "reason": "Change it"}))

    with pytest.raises(
        AgentPlanStorageConflictError,
        match="AGENT_APPROVAL_EFFECTIVE_DECISION_ALREADY_RECORDED",
    ):
        record_agent_approval(
            cfg,
            **(
                command
                | {
                    "request_id": "approve-request-duplicate",
                    "idempotency_key": "approve-request-duplicate",
                }
            ),
        )

    with get_connection(cfg) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="AGENT_APPROVAL_IMMUTABLE"):
            connection.execute(
                "UPDATE agent_approvals SET reason = 'changed' WHERE approval_id = ?",
                (approval["approvalId"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="AGENT_APPROVAL_IMMUTABLE"):
            connection.execute(
                "DELETE FROM agent_approvals WHERE approval_id = ?",
                (approval["approvalId"],),
            )


def test_agent_approval_rejects_stale_state_and_plan_hash(tmp_path: Path) -> None:
    cfg, session, _draft, _proposal, plan = _create_first_plan(tmp_path)

    with pytest.raises(AgentPlanStorageConflictError, match="AGENT_APPROVAL_STATE_VERSION_CONFLICT"):
        record_agent_approval(
            cfg,
            session_id=session["sessionId"],
            plan_revision_id=plan["planRevisionId"],
            expected_state_version=session["stateVersion"] - 1,
            expected_plan_hash=plan["planHash"],
            decision="approve",
            actor="user-1",
            request_id="approve-stale",
            idempotency_key="approve-stale",
        )


def test_agent_approval_rejects_live_draft_revision_drift(tmp_path: Path) -> None:
    cfg, session, draft, _proposal, plan = _create_first_plan(tmp_path)
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE workflow_design_drafts
            SET revision = revision + 1
            WHERE draft_id = ?
            """,
            (draft["draftId"],),
        )
        connection.commit()

    with pytest.raises(
        AgentPlanStorageConflictError,
        match="AGENT_APPROVAL_DRAFT_REVISION_CONFLICT",
    ):
        record_agent_approval(
            cfg,
            session_id=session["sessionId"],
            plan_revision_id=plan["planRevisionId"],
            expected_state_version=session["stateVersion"],
            expected_plan_hash=plan["planHash"],
            decision="approve",
            actor="user-1",
            request_id="approve-drifted-draft",
            idempotency_key="approve-drifted-draft",
        )
    assert list_agent_approvals(cfg, session["sessionId"]) == []

    with pytest.raises(AgentPlanStorageConflictError, match="AGENT_APPROVAL_ACTIVE_PLAN_HASH_CONFLICT"):
        record_agent_approval(
            cfg,
            session_id=session["sessionId"],
            plan_revision_id=plan["planRevisionId"],
            expected_state_version=session["stateVersion"],
            expected_plan_hash="b" * 64,
            decision="approve",
            actor="user-1",
            request_id="approve-hash",
            idempotency_key="approve-hash",
        )


def test_replan_requires_parent_revision_and_preserves_old_plan(tmp_path: Path) -> None:
    cfg, session, draft, _proposal, first_plan = _create_first_plan(tmp_path)
    changes = transition_agent_session(
        cfg,
        session["sessionId"],
        expected_state_version=session["stateVersion"],
        expected_plan_hash=first_plan["planHash"],
        event_type="agent.changes_requested",
        to_status="changes_requested",
        request_id="changes-1",
        actor="user-1",
        idempotency_key="changes-1",
        payload={"reason": "Use a revised plan"},
    )
    planning = transition_agent_session(
        cfg,
        session["sessionId"],
        expected_state_version=changes["session"]["stateVersion"],
        expected_plan_generation=1,
        event_type="agent.replan_requested",
        to_status="planning",
        request_id="replan-2",
        actor="user-1",
        idempotency_key="replan-2",
        payload={"parentPlanRevisionId": first_plan["planRevisionId"]},
        plan_generation=2,
        active_draft_id=None,
        active_draft_revision=None,
        active_plan_hash=None,
        workflow_revision_id=None,
    )
    fork = fork_workflow_design_draft(cfg, draft["draftId"])
    proposal = {
        "draft": fork["draft"],
        "planner": {"adapterId": "fixture.fastq-qc.v1", "adapterVersion": "1"},
    }

    with pytest.raises(AgentPlanStorageConflictError, match="AGENT_PLAN_PARENT_REVISION_REQUIRED"):
        create_agent_plan_revision(
            cfg,
            session_id=session["sessionId"],
            plan_generation=2,
            draft_id=fork["draftId"],
            draft_revision=fork["revision"],
            proposal=proposal,
            validation={"valid": True},
            budget=_budget(),
            created_by="fixture.fastq-qc.v1",
        )

    second_plan = create_agent_plan_revision(
        cfg,
        session_id=session["sessionId"],
        plan_generation=planning["session"]["planGeneration"],
        parent_plan_revision_id=first_plan["planRevisionId"],
        draft_id=fork["draftId"],
        draft_revision=fork["revision"],
        proposal=proposal,
        validation={"valid": True},
        budget=_budget(),
        created_by="fixture.fastq-qc.v1",
    )

    assert second_plan["parentPlanRevisionId"] == first_plan["planRevisionId"]
    assert second_plan["planHash"] != first_plan["planHash"]
    assert [item["planGeneration"] for item in list_agent_plan_revisions(cfg, session["sessionId"])] == [1, 2]
