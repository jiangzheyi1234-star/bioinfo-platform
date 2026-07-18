from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from pydantic import ValidationError

from apps.remote_runner.agent_effect_budget_storage import (
    AgentEffectBudgetStorageConflictError,
    effective_agent_run_submission_limit,
    grant_agent_session_effect_budget,
    read_agent_session_effect_budget,
)
from apps.remote_runner.agent_session_storage import (
    create_agent_session,
    transition_agent_session,
)
from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.storage_core import get_connection
from core.contracts.agent_effect_budget import AgentSessionEffectBudgetGrantRequest
from tests.helpers.reference_database import make_remote_runner_config


def _configured_runner(tmp_path: Path):
    cfg = make_remote_runner_config(tmp_path)
    ensure_runtime_layout(cfg)
    return cfg


def _create_session(cfg, *, request_id: str = "create-effect-budget") -> dict:
    return create_agent_session(
        cfg,
        project_id="proj_effect_budget",
        goal={"summary": "Inspect FASTQ quality"},
        constraints={"forbiddenActions": ["arbitrary_shell"]},
        budget={
            "maxModelTurns": 8,
            "maxToolCalls": 12,
            "maxReplans": 3,
            "maxRetries": 2,
            "maxWallClockSeconds": 3_600,
        },
        creation_request_id=request_id,
        created_by="runner-principal",
    )


def _grant_request(
    *,
    request_id: str = "grant-effect-budget",
    idempotency_key: str = "grant-effect-budget",
) -> AgentSessionEffectBudgetGrantRequest:
    return AgentSessionEffectBudgetGrantRequest(
        expectedStateVersion=1,
        maxRunSubmissions=1,
        confirmation="enable-one-run",
        requestId=request_id,
        idempotencyKey=idempotency_key,
    )


def _start_planning(cfg, session_id: str, *, suffix: str = "1") -> dict:
    return transition_agent_session(
        cfg,
        session_id,
        expected_state_version=1,
        event_type="agent.plan_requested",
        to_status="planning",
        request_id=f"plan-request-{suffix}",
        actor="runner-principal",
        idempotency_key=f"plan-request-{suffix}",
        payload={"planner": {"adapterId": "fixture.fastq-qc.v1"}},
        plan_generation=1,
        planner={"adapterId": "fixture.fastq-qc.v1", "adapterVersion": "1"},
    )


def test_effect_budget_read_is_authoritative_absent_then_present_and_immutable(
    tmp_path: Path,
) -> None:
    cfg = _configured_runner(tmp_path)
    session = _create_session(cfg)
    session_id = session["sessionId"]

    assert read_agent_session_effect_budget(cfg, session_id) == {
        "contractVersion": "agent-session-effect-budget-read.v1",
        "sessionId": session_id,
        "state": "absent",
    }
    assert effective_agent_run_submission_limit(cfg, session_id) == 0

    receipt = grant_agent_session_effect_budget(
        cfg,
        session_id,
        _grant_request(),
        actor="runner-principal",
    )
    assert read_agent_session_effect_budget(cfg, session_id) == {
        "contractVersion": "agent-session-effect-budget-read.v1",
        "sessionId": session_id,
        "state": "present",
        "budget": receipt,
    }
    assert effective_agent_run_submission_limit(cfg, session_id) == 1

    with get_connection(cfg) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="AGENT_SESSION_EFFECT_BUDGET_IMMUTABLE"):
            connection.execute(
                "UPDATE agent_session_effect_budgets SET actor = 'tampered' WHERE session_id = ?",
                (session_id,),
            )
    with get_connection(cfg) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="AGENT_SESSION_EFFECT_BUDGET_IMMUTABLE"):
            connection.execute(
                "DELETE FROM agent_session_effect_budgets WHERE session_id = ?",
                (session_id,),
            )


def test_effect_budget_replays_after_planning_and_rejects_other_grants(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path)
    session = _create_session(cfg)
    session_id = session["sessionId"]
    request = _grant_request()
    receipt = grant_agent_session_effect_budget(
        cfg,
        session_id,
        request,
        actor="runner-principal",
    )
    _start_planning(cfg, session_id)

    assert (
        grant_agent_session_effect_budget(
            cfg,
            session_id,
            request,
            actor="runner-principal",
        )
        == receipt
    )
    with pytest.raises(AgentEffectBudgetStorageConflictError, match="ALREADY_GRANTED"):
        grant_agent_session_effect_budget(
            cfg,
            session_id,
            _grant_request(request_id="other", idempotency_key="other"),
            actor="runner-principal",
        )
    with pytest.raises(AgentEffectBudgetStorageConflictError, match="ALREADY_GRANTED"):
        grant_agent_session_effect_budget(
            cfg,
            session_id,
            request,
            actor="different-principal",
        )


def test_concurrent_same_key_effect_budget_grants_return_one_receipt(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path)
    session_id = _create_session(cfg)["sessionId"]
    request = _grant_request()
    barrier = Barrier(2)

    def grant() -> dict:
        barrier.wait()
        return grant_agent_session_effect_budget(
            cfg,
            session_id,
            request,
            actor="runner-principal",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(lambda _index: grant(), range(2)))

    assert receipts[0] == receipts[1]
    with get_connection(cfg) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM agent_session_effect_budgets WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
    assert count == 1


def test_effect_budget_grant_and_plan_are_serialized_without_late_grant(
    tmp_path: Path,
) -> None:
    cfg = _configured_runner(tmp_path)
    session_id = _create_session(cfg)["sessionId"]
    request = _grant_request()
    barrier = Barrier(2)

    def grant() -> tuple[str, object]:
        barrier.wait()
        try:
            return (
                "granted",
                grant_agent_session_effect_budget(
                    cfg,
                    session_id,
                    request,
                    actor="runner-principal",
                ),
            )
        except AgentEffectBudgetStorageConflictError as exc:
            return "rejected", exc

    def plan() -> tuple[str, object]:
        barrier.wait()
        return "planned", _start_planning(cfg, session_id, suffix="race")

    with ThreadPoolExecutor(max_workers=2) as executor:
        grant_future = executor.submit(grant)
        plan_future = executor.submit(plan)
        grant_outcome = grant_future.result()
        plan_outcome = plan_future.result()

    assert plan_outcome[0] == "planned"
    read = read_agent_session_effect_budget(cfg, session_id)
    if grant_outcome[0] == "granted":
        assert read["state"] == "present"
    else:
        assert "ADMISSION_CLOSED" in str(grant_outcome[1])
        assert read["state"] == "absent"


def test_effect_budget_grant_is_rejected_after_planning(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path)
    session_id = _create_session(cfg)["sessionId"]
    _start_planning(cfg, session_id)

    with pytest.raises(AgentEffectBudgetStorageConflictError, match="ADMISSION_CLOSED"):
        grant_agent_session_effect_budget(
            cfg,
            session_id,
            _grant_request(),
            actor="runner-principal",
        )


@pytest.mark.parametrize(
    ("column", "value"),
    (("actor", "tampered-principal"), ("receipt_hash", "0" * 64)),
)
def test_effect_budget_read_rejects_tampered_hash_covered_storage(
    tmp_path: Path,
    column: str,
    value: str,
) -> None:
    cfg = _configured_runner(tmp_path)
    session_id = _create_session(cfg)["sessionId"]
    grant_agent_session_effect_budget(
        cfg,
        session_id,
        _grant_request(),
        actor="runner-principal",
    )

    with get_connection(cfg) as connection:
        trigger_sql = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'trigger' AND name = 'agent_session_effect_budgets_no_update'
            """
        ).fetchone()[0]
        connection.execute("DROP TRIGGER agent_session_effect_budgets_no_update")
        connection.execute(
            f"UPDATE agent_session_effect_budgets SET {column} = ? WHERE session_id = ?",
            (value, session_id),
        )
        connection.execute(trigger_sql)
        connection.commit()

    with pytest.raises(
        AgentEffectBudgetStorageConflictError,
        match="STORED_RECEIPT_HASH_MISMATCH",
    ):
        read_agent_session_effect_budget(cfg, session_id)


def test_effect_budget_storage_rejects_non_string_identity_values(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path)
    session_id = _create_session(cfg)["sessionId"]

    with pytest.raises(ValueError, match="AGENT_SESSION_ID_REQUIRED"):
        grant_agent_session_effect_budget(  # type: ignore[arg-type]
            cfg,
            True,
            _grant_request(),
            actor="runner-principal",
        )
    with pytest.raises(ValueError, match="AGENT_EFFECT_BUDGET_ACTOR_REQUIRED"):
        grant_agent_session_effect_budget(  # type: ignore[arg-type]
            cfg,
            session_id,
            _grant_request(),
            actor=1,
        )
    assert read_agent_session_effect_budget(cfg, session_id)["state"] == "absent"


@pytest.mark.parametrize(
    ("field", "value"),
    (("maxRunSubmissions", 2), ("confirmation", "tampered-confirmation")),
)
def test_effect_budget_grant_revalidates_mutated_request_instance(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    cfg = _configured_runner(tmp_path)
    session_id = _create_session(cfg)["sessionId"]
    request = _grant_request()
    request.__dict__[field] = value

    with pytest.raises(ValidationError):
        grant_agent_session_effect_budget(
            cfg,
            session_id,
            request,
            actor="runner-principal",
        )
    assert read_agent_session_effect_budget(cfg, session_id)["state"] == "absent"
