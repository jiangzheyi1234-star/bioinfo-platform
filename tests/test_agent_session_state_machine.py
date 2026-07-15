from __future__ import annotations

import pytest

from apps.remote_runner.agent_session_state_machine import AgentSessionStateMachine


def test_initial_planning_and_validation_have_explicit_versions_and_generation() -> None:
    created = AgentSessionStateMachine.create()
    planning = AgentSessionStateMachine.start_planning(
        current_status=created.to_status,
        state_version=created.state_version,
        plan_generation=created.plan_generation,
        expected_state_version=1,
    )
    validated = AgentSessionStateMachine.plan_validated(
        current_status=planning.to_status,
        state_version=planning.state_version,
        plan_generation=planning.plan_generation,
        expected_state_version=2,
        plan_hash="sha256:plan-1",
    )

    assert created.event_type == "agent.session_created"
    assert created.to_status == "created"
    assert created.state_version == 1
    assert created.plan_generation == 0
    assert planning.event_type == "agent.plan_requested"
    assert planning.from_status == "created"
    assert planning.to_status == "planning"
    assert planning.state_version == 2
    assert planning.plan_generation == 1
    assert planning.clear_active_plan is True
    assert validated.event_type == "agent.plan_validated"
    assert validated.to_status == "awaiting_approval"
    assert validated.state_version == 3
    assert validated.plan_generation == 1
    assert validated.plan_hash == "sha256:plan-1"


def test_plan_failure_is_explicit_and_can_only_replan_through_replan_command() -> None:
    failed = AgentSessionStateMachine.plan_failed(
        current_status="planning",
        state_version=2,
        plan_generation=1,
        expected_state_version=2,
    )
    replan = AgentSessionStateMachine.request_replan(
        current_status=failed.to_status,
        state_version=failed.state_version,
        plan_generation=failed.plan_generation,
        expected_state_version=3,
        max_replans=2,
    )

    assert failed.to_status == "plan_failed"
    assert failed.event_type == "agent.plan_rejected"
    assert failed.state_version == 3
    assert replan.event_type == "agent.replan_requested"
    assert replan.to_status == "planning"
    assert replan.state_version == 4
    assert replan.plan_generation == 2
    assert replan.clear_active_plan is True

    with pytest.raises(ValueError, match="AGENT_SESSION_START_PLANNING_STATUS_INVALID: plan_failed"):
        AgentSessionStateMachine.start_planning(
            current_status="plan_failed",
            state_version=3,
            plan_generation=1,
            expected_state_version=3,
        )


def test_approval_is_bound_to_exact_state_plan_hash_and_workflow_revision() -> None:
    approved = AgentSessionStateMachine.approve(
        current_status="awaiting_approval",
        state_version=3,
        plan_generation=1,
        expected_state_version=3,
        current_plan_hash="sha256:plan-1",
        expected_plan_hash="sha256:plan-1",
        workflow_revision_id="wfr_1",
    )

    assert approved.event_type == "agent.workflow_revision_compiled"
    assert approved.to_status == "ready_to_run"
    assert approved.state_version == 4
    assert approved.plan_hash == "sha256:plan-1"
    assert approved.workflow_revision_id == "wfr_1"

    with pytest.raises(
        ValueError,
        match="AGENT_SESSION_STATE_VERSION_CONFLICT: expected=2 actual=3",
    ):
        AgentSessionStateMachine.approve(
            current_status="awaiting_approval",
            state_version=3,
            plan_generation=1,
            expected_state_version=2,
            current_plan_hash="sha256:plan-1",
            expected_plan_hash="sha256:plan-1",
            workflow_revision_id="wfr_1",
        )

    with pytest.raises(ValueError, match="AGENT_SESSION_PLAN_HASH_CONFLICT"):
        AgentSessionStateMachine.approve(
            current_status="awaiting_approval",
            state_version=3,
            plan_generation=1,
            expected_state_version=3,
            current_plan_hash="sha256:plan-2",
            expected_plan_hash="sha256:plan-1",
            workflow_revision_id="wfr_1",
        )

    with pytest.raises(ValueError, match="AGENT_SESSION_WORKFLOW_REVISION_REQUIRED"):
        AgentSessionStateMachine.approve(
            current_status="awaiting_approval",
            state_version=3,
            plan_generation=1,
            expected_state_version=3,
            current_plan_hash="sha256:plan-1",
            expected_plan_hash="sha256:plan-1",
            workflow_revision_id=" ",
        )


def test_change_request_is_plan_bound_and_replan_increments_generation() -> None:
    changes = AgentSessionStateMachine.request_changes(
        current_status="awaiting_approval",
        state_version=3,
        plan_generation=1,
        expected_state_version=3,
        current_plan_hash="sha256:plan-1",
        expected_plan_hash="sha256:plan-1",
    )
    replan = AgentSessionStateMachine.request_replan(
        current_status=changes.to_status,
        state_version=changes.state_version,
        plan_generation=changes.plan_generation,
        expected_state_version=4,
        max_replans=3,
    )

    assert changes.to_status == "changes_requested"
    assert changes.plan_hash == "sha256:plan-1"
    assert replan.to_status == "planning"
    assert replan.plan_generation == 2


@pytest.mark.parametrize("status", ["plan_failed", "changes_requested", "ready_to_run"])
def test_replanable_states_obey_hard_replan_budget(status: str) -> None:
    with pytest.raises(
        ValueError,
        match="AGENT_SESSION_REPLAN_BUDGET_EXHAUSTED: used=2 max=2",
    ):
        AgentSessionStateMachine.request_replan(
            current_status=status,
            state_version=8,
            plan_generation=3,
            expected_state_version=8,
            max_replans=2,
        )


def test_cancelled_is_terminal_and_cancel_is_idempotent_at_state_level() -> None:
    cancelled = AgentSessionStateMachine.cancel(
        current_status="awaiting_approval",
        state_version=3,
        plan_generation=1,
        expected_state_version=3,
    )
    repeated = AgentSessionStateMachine.cancel(
        current_status=cancelled.to_status,
        state_version=cancelled.state_version,
        plan_generation=cancelled.plan_generation,
        expected_state_version=4,
    )

    assert cancelled.to_status == "cancelled"
    assert cancelled.state_version == 4
    assert AgentSessionStateMachine.is_terminal(cancelled.to_status) is True
    assert repeated.to_status == "cancelled"
    assert repeated.state_version == 4
    assert repeated.update_session is False

    with pytest.raises(ValueError, match="AGENT_SESSION_TERMINAL_IMMUTABLE: cancelled"):
        AgentSessionStateMachine.request_replan(
            current_status="cancelled",
            state_version=4,
            plan_generation=1,
            expected_state_version=4,
            max_replans=3,
        )


def test_state_machine_rejects_non_strict_versions_and_unsupported_statuses() -> None:
    with pytest.raises(ValueError, match="AGENT_SESSION_STATE_VERSION_INVALID"):
        AgentSessionStateMachine.start_planning(
            current_status="created",
            state_version=True,
            plan_generation=0,
            expected_state_version=1,
        )

    with pytest.raises(ValueError, match="AGENT_SESSION_STATUS_UNSUPPORTED: running"):
        AgentSessionStateMachine.cancel(
            current_status="running",
            state_version=1,
            plan_generation=0,
            expected_state_version=1,
        )
