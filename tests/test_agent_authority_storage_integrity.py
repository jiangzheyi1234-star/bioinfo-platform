from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.remote_runner.agent_plan_storage import (
    AgentPlanStorageConflictError,
    create_agent_plan_revision,
    require_active_agent_plan_for_connection,
)
from apps.remote_runner.agent_session_storage import (
    AgentSessionStorageConflictError,
    create_agent_session,
    fetch_agent_session,
    fetch_agent_session_for_connection,
    require_agent_session_for_connection,
    transition_agent_session,
)
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_design_storage import create_workflow_design_draft
from tests.helpers.workflow_design_drafts import workflow_design_config, workflow_design_draft


_PLANNER = {
    "adapterId": "fixture.fastq-qc.v1",
    "adapterVersion": "1.0.0",
    "modelRef": "deterministic:fixture",
}


def _budget() -> dict[str, int]:
    return {
        "maxModelTurns": 8,
        "maxToolCalls": 12,
        "maxReplans": 3,
        "maxRetries": 2,
        "maxWallClockSeconds": 3_600,
    }


def _session(tmp_path: Path):
    cfg = workflow_design_config(tmp_path)
    session = create_agent_session(
        cfg,
        project_id="proj_design",
        goal={
            "summary": "Inspect FASTQ quality",
            "successCriteria": ["Produce a QC report"],
            "context": {"analysis": "storage-integrity-test"},
        },
        constraints={"requirements": {"networkAccess": "declared-only"}},
        budget=_budget(),
        creation_request_id="create-authority-integrity",
        created_by="user-1",
    )
    return cfg, session


def _ready_session_and_plan(tmp_path: Path):
    cfg, created = _session(tmp_path)
    planning = transition_agent_session(
        cfg,
        created["sessionId"],
        expected_state_version=created["stateVersion"],
        event_type="agent.plan_requested",
        to_status="planning",
        request_id="plan-authority-integrity",
        actor="user-1",
        idempotency_key="plan-authority-integrity",
        payload={"planner": _PLANNER},
        plan_generation=1,
        planner=_PLANNER,
    )["session"]
    draft = create_workflow_design_draft(cfg, workflow_design_draft())
    proposal = {"draft": draft["draft"], "planner": _PLANNER}
    plan = create_agent_plan_revision(
        cfg,
        session_id=planning["sessionId"],
        plan_generation=planning["planGeneration"],
        draft_id=draft["draftId"],
        draft_revision=draft["revision"],
        proposal=proposal,
        validation={"valid": True, "issues": [], "toolRevisionCount": 1},
        budget=_budget(),
        created_by=_PLANNER["adapterId"],
    )
    awaiting = transition_agent_session(
        cfg,
        planning["sessionId"],
        expected_state_version=planning["stateVersion"],
        expected_plan_generation=planning["planGeneration"],
        event_type="agent.plan_validated",
        to_status="awaiting_approval",
        request_id="validated-authority-integrity",
        actor=_PLANNER["adapterId"],
        idempotency_key="validated-authority-integrity",
        payload={"planRevisionId": plan["planRevisionId"]},
        active_draft_id=draft["draftId"],
        active_draft_revision=draft["revision"],
        active_plan_hash=plan["planHash"],
    )["session"]
    ready = transition_agent_session(
        cfg,
        awaiting["sessionId"],
        expected_state_version=awaiting["stateVersion"],
        expected_plan_generation=awaiting["planGeneration"],
        expected_plan_hash=plan["planHash"],
        event_type="agent.workflow_revision_compiled",
        to_status="ready_to_run",
        request_id="compiled-authority-integrity",
        actor="user-1",
        idempotency_key="compiled-authority-integrity",
        payload={"workflowRevisionId": "wfrev_authority_integrity"},
        workflow_revision_id="wfrev_authority_integrity",
    )["session"]
    return cfg, ready, plan


@pytest.mark.parametrize(
    ("statement", "value"),
    [
        (
            "UPDATE agent_sessions SET contract_version = ? WHERE session_id = ?",
            "agent-session.v999",
        ),
        (
            "UPDATE agent_sessions SET project_id = ? WHERE session_id = ?",
            "proj_tampered",
        ),
        (
            "UPDATE agent_sessions SET goal_json = ? WHERE session_id = ?",
            json.dumps({"summary": "Tampered", "successCriteria": [], "context": {}}),
        ),
        (
            "UPDATE agent_sessions SET constraints_json = ? WHERE session_id = ?",
            "{}",
        ),
        (
            "UPDATE agent_sessions SET budget_json = ? WHERE session_id = ?",
            json.dumps(_budget() | {"maxModelTurns": 9}),
        ),
        (
            "UPDATE agent_sessions SET created_by = ? WHERE session_id = ?",
            "user-tampered",
        ),
    ],
)
def test_session_read_rejects_tampered_creation_domain(
    tmp_path: Path,
    statement: str,
    value: str,
) -> None:
    cfg, session = _session(tmp_path)
    with get_connection(cfg) as connection:
        connection.execute(statement, (value, session["sessionId"]))
        connection.commit()

    with pytest.raises(
        AgentSessionStorageConflictError,
        match="AGENT_SESSION_STORED_CREATION_HASH_MISMATCH",
    ):
        fetch_agent_session(cfg, session["sessionId"])


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("goal_json", "{"),
        ("constraints_json", "[]"),
        ("budget_json", "null"),
    ],
)
def test_session_read_rejects_invalid_creation_json_or_type(
    tmp_path: Path,
    column: str,
    value: str,
) -> None:
    cfg, session = _session(tmp_path)
    statements = {
        "goal_json": "UPDATE agent_sessions SET goal_json = ? WHERE session_id = ?",
        "constraints_json": "UPDATE agent_sessions SET constraints_json = ? WHERE session_id = ?",
        "budget_json": "UPDATE agent_sessions SET budget_json = ? WHERE session_id = ?",
    }
    with get_connection(cfg) as connection:
        connection.execute(statements[column], (value, session["sessionId"]))
        connection.commit()

    with pytest.raises(
        AgentSessionStorageConflictError,
        match="AGENT_SESSION_STORED_CREATION_PAYLOAD_INVALID",
    ):
        fetch_agent_session(cfg, session["sessionId"])


@pytest.mark.parametrize("column", ["state_version", "plan_generation"])
def test_session_read_rejects_invalid_stored_integer(
    tmp_path: Path,
    column: str,
) -> None:
    cfg, session = _session(tmp_path)
    statements = {
        "state_version": "UPDATE agent_sessions SET state_version = ? WHERE session_id = ?",
        "plan_generation": "UPDATE agent_sessions SET plan_generation = ? WHERE session_id = ?",
    }
    with get_connection(cfg) as connection:
        connection.execute(statements[column], ("not-an-integer", session["sessionId"]))
        connection.commit()

    with pytest.raises(
        AgentSessionStorageConflictError,
        match="AGENT_SESSION_STORED_RECORD_INVALID",
    ):
        fetch_agent_session(cfg, session["sessionId"])


def test_connection_scoped_session_and_active_plan_load_exact_authority(
    tmp_path: Path,
) -> None:
    cfg, expected_session, expected_plan = _ready_session_and_plan(tmp_path)

    with get_connection(cfg) as connection:
        connection.execute("BEGIN")
        assert fetch_agent_session_for_connection(
            connection,
            expected_session["sessionId"],
        ) == expected_session
        session = require_agent_session_for_connection(
            connection,
            expected_session["sessionId"],
        )
        assert connection.in_transaction is True
        assert require_active_agent_plan_for_connection(connection, session) == expected_plan
        assert connection.in_transaction is True
        connection.rollback()


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("status", "awaiting_approval", "AGENT_ACTIVE_PLAN_SESSION_NOT_READY"),
        (
            "workflowRevisionId",
            None,
            "AGENT_ACTIVE_PLAN_WORKFLOW_REVISION_REQUIRED",
        ),
        ("activeDraftId", "wfd_other", "AGENT_ACTIVE_PLAN_DRAFT_ID_MISMATCH"),
        ("activeDraftRevision", 2, "AGENT_ACTIVE_PLAN_DRAFT_REVISION_MISMATCH"),
        ("activePlanHash", "f" * 64, "AGENT_ACTIVE_PLAN_HASH_MISMATCH"),
        ("planGeneration", 2, "AGENT_ACTIVE_PLAN_NOT_FOUND"),
        (
            "planner",
            {"adapterId": "fixture.other.v1"},
            "AGENT_ACTIVE_PLAN_PLANNER_MISMATCH",
        ),
        (
            "budget",
            _budget() | {"maxModelTurns": 9},
            "AGENT_ACTIVE_PLAN_BUDGET_MISMATCH",
        ),
    ],
)
def test_active_plan_loader_rejects_session_plan_ownership_mismatch(
    tmp_path: Path,
    field: str,
    value: object,
    code: str,
) -> None:
    cfg, session, _plan = _ready_session_and_plan(tmp_path)
    mismatched = {**session, field: value}

    with get_connection(cfg) as connection:
        with pytest.raises(AgentPlanStorageConflictError, match=code):
            require_active_agent_plan_for_connection(connection, mismatched)


def test_active_plan_loader_rejects_invalid_stored_plan_hash(tmp_path: Path) -> None:
    cfg, session, plan = _ready_session_and_plan(tmp_path)
    with get_connection(cfg) as connection:
        connection.execute("DROP TRIGGER agent_plan_revisions_no_update")
        connection.execute(
            "UPDATE agent_plan_revisions SET plan_hash = ? WHERE plan_revision_id = ?",
            ("f" * 64, plan["planRevisionId"]),
        )
        with pytest.raises(
            AgentPlanStorageConflictError,
            match="AGENT_PLAN_STORED_HASH_MISMATCH",
        ):
            require_active_agent_plan_for_connection(connection, session)
        connection.rollback()


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("proposal_json", "{"),
        ("validation_json", "[]"),
        ("budget_json", "null"),
        ("draft_revision", "not-an-integer"),
    ],
)
def test_active_plan_loader_rejects_invalid_stored_payload(
    tmp_path: Path,
    column: str,
    value: str,
) -> None:
    cfg, session, plan = _ready_session_and_plan(tmp_path)
    statements = {
        "proposal_json": "UPDATE agent_plan_revisions SET proposal_json = ? WHERE plan_revision_id = ?",
        "validation_json": "UPDATE agent_plan_revisions SET validation_json = ? WHERE plan_revision_id = ?",
        "budget_json": "UPDATE agent_plan_revisions SET budget_json = ? WHERE plan_revision_id = ?",
        "draft_revision": "UPDATE agent_plan_revisions SET draft_revision = ? WHERE plan_revision_id = ?",
    }
    with get_connection(cfg) as connection:
        connection.execute("DROP TRIGGER agent_plan_revisions_no_update")
        connection.execute(statements[column], (value, plan["planRevisionId"]))
        with pytest.raises(
            AgentPlanStorageConflictError,
            match="AGENT_PLAN_STORED_PAYLOAD_INVALID",
        ):
            require_active_agent_plan_for_connection(connection, session)
        connection.rollback()
