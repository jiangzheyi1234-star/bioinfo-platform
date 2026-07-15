"""Provider-neutral AgentSession lifecycle over existing workflow design services."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core.contracts.agent_session import (
    AgentApprovalRequest,
    AgentCancelRequest,
    AgentPlanRequest,
    AgentReplanRequest,
    AgentSessionCreateRequest,
)

from .agent_plan_storage import (
    create_agent_plan_revision,
    list_agent_approvals,
    list_agent_plan_revisions,
    record_agent_approval,
)
from .agent_session_state_machine import AgentSessionStateMachine
from .agent_session_storage import (
    AgentSessionStorageConflictError,
    create_agent_session,
    fetch_agent_events,
    list_agent_sessions,
    require_agent_session,
    transition_agent_session,
)
from .config import RemoteRunnerConfig
from .errors import RemoteRunnerAuthorizationError
from .route_utils import (
    authorized_config,
    data_response,
    remote_runner_principal,
    run_sync,
)
from .workflow_design_service import (
    compile_workflow_design_draft_export,
    plan_workflow_design_draft_preview,
)
from .workflow_design_storage import (
    create_or_fetch_workflow_design_draft,
    require_workflow_design_draft,
)


def create_agent_session_from_request(
    cfg: RemoteRunnerConfig,
    request: AgentSessionCreateRequest,
) -> dict[str, Any]:
    payload = request.runtime_payload()
    return create_agent_session(
        cfg,
        project_id=str(payload["projectId"]),
        goal=dict(payload["goal"]),
        constraints=dict(payload["constraints"]),
        budget=dict(payload["budget"]),
        creation_request_id=str(payload["creationRequestId"]),
        created_by=str(payload["createdBy"]),
    )


def plan_agent_session_from_request(
    cfg: RemoteRunnerConfig,
    session_id: str,
    request: AgentPlanRequest | AgentReplanRequest,
    *,
    replan: bool,
) -> dict[str, Any]:
    request_payload = request.runtime_payload()
    command_hash = _hash_json(
        {
            "command": "replan" if replan else "plan",
            "request": request_payload,
            "sessionId": session_id,
        }
    )
    generation = _target_plan_generation(cfg, session_id, request, replan=replan)
    proposal = dict(request_payload["proposal"])
    proposal["draft"] = _agent_draft(
        dict(proposal["draft"]),
        session_id=session_id,
        plan_generation=generation,
    )
    proposal_hash = _hash_json(proposal)
    existing_event = _command_event(cfg, session_id, request.idempotencyKey)
    if existing_event is not None:
        expected_event_type = "agent.replan_requested" if replan else "agent.plan_requested"
        if (
            existing_event["eventType"] != expected_event_type
            or str(existing_event["payload"].get("commandHash") or "") != command_hash
            or str(existing_event["payload"].get("proposalHash") or "") != proposal_hash
        ):
            raise AgentSessionStorageConflictError("AGENT_COMMAND_IDEMPOTENCY_CONFLICT")
        parent_draft_id = _optional_text(existing_event["payload"].get("parentDraftId"))
        parent_plan_revision_id = _optional_text(
            existing_event["payload"].get("parentPlanRevisionId")
        )
        session = require_agent_session(cfg, session_id)
        completed = _completed_plan_result(cfg, session, generation)
        if completed is not None:
            return completed
    else:
        before = require_agent_session(cfg, session_id)
        parent_draft_id = before.get("activeDraftId") if replan else None
        parent_plan_revision_id = _latest_plan_revision_id(cfg, session_id) if replan else None
        decision = _planning_transition(before, request, replan=replan)
        command_payload = {
            "commandHash": command_hash,
            "parentDraftId": parent_draft_id,
            "parentPlanRevisionId": parent_plan_revision_id,
            "planner": proposal["planner"],
            "proposalHash": proposal_hash,
        }
        if isinstance(request, AgentReplanRequest):
            command_payload["reason"] = request.reason
        transition = transition_agent_session(
            cfg,
            session_id,
            expected_state_version=request.expectedStateVersion,
            event_type=decision.event_type,
            to_status=decision.to_status,
            request_id=request.requestId,
            actor=request.actor,
            idempotency_key=request.idempotencyKey,
            payload=command_payload,
            plan_generation=decision.plan_generation,
            active_draft_id=None,
            active_draft_revision=None,
            active_plan_hash=None,
            workflow_revision_id=None,
            planner=dict(proposal["planner"]),
            last_error_code="",
        )
        session = transition["session"]
        generation = int(session["planGeneration"])

    draft_id = _agent_draft_id(session_id, generation)
    draft = create_or_fetch_workflow_design_draft(
        cfg,
        draft_id,
        dict(proposal["draft"]),
        parent_draft_id=parent_draft_id,
    )
    validation = plan_workflow_design_draft_preview(cfg, draft_id, [])
    session = require_agent_session(cfg, session_id)
    plan = create_agent_plan_revision(
        cfg,
        session_id=session_id,
        plan_generation=generation,
        parent_plan_revision_id=parent_plan_revision_id,
        draft_id=draft_id,
        draft_revision=int(draft["revision"]),
        proposal={"draft": draft["draft"], "planner": proposal["planner"]},
        validation=validation,
        budget=dict(session["budget"]),
        created_by=str(proposal["planner"]["adapterId"]),
    )
    if not bool(validation.get("valid")):
        failed = _mark_plan_failed(
            cfg,
            session_id=session_id,
            request=request,
            generation=generation,
            draft=draft,
            plan=plan,
            validation=validation,
        )
        return {
            "session": failed,
            "draft": draft,
            "plan": plan,
            "validation": validation,
        }

    session = require_agent_session(cfg, session_id)
    if session["status"] == "awaiting_approval" and session["activePlanHash"] == plan["planHash"]:
        return {"session": session, "draft": draft, "plan": plan, "validation": validation}
    decision = AgentSessionStateMachine.plan_validated(
        current_status=session["status"],
        state_version=int(session["stateVersion"]),
        plan_generation=int(session["planGeneration"]),
        expected_state_version=int(session["stateVersion"]),
        plan_hash=str(plan["planHash"]),
    )
    validated = transition_agent_session(
        cfg,
        session_id,
        expected_state_version=int(session["stateVersion"]),
        expected_plan_generation=generation,
        event_type=decision.event_type,
        to_status=decision.to_status,
        request_id=request.requestId,
        actor=str(proposal["planner"]["adapterId"]),
        idempotency_key=f"validated:{request.idempotencyKey}",
        correlation_id=request.requestId,
        payload={
            "draftId": draft_id,
            "draftRevision": draft["revision"],
            "planHash": plan["planHash"],
            "planRevisionId": plan["planRevisionId"],
        },
        active_draft_id=draft_id,
        active_draft_revision=int(draft["revision"]),
        active_plan_hash=str(plan["planHash"]),
    )
    return {
        "session": validated["session"],
        "draft": draft,
        "plan": plan,
        "validation": validation,
    }


def approve_agent_session_from_request(
    cfg: RemoteRunnerConfig,
    session_id: str,
    request: AgentApprovalRequest,
) -> dict[str, Any]:
    session = require_agent_session(cfg, session_id)
    plan = _active_plan(cfg, session)
    approval = record_agent_approval(
        cfg,
        session_id=session_id,
        plan_revision_id=plan["planRevisionId"],
        expected_state_version=request.expectedStateVersion,
        expected_plan_hash=request.expectedPlanHash,
        decision=request.decision,
        actor=request.actor,
        request_id=request.requestId,
        idempotency_key=request.idempotencyKey,
        reason=request.reason,
    )
    session = require_agent_session(cfg, session_id)
    if request.decision == "request_changes":
        if session["status"] != "changes_requested":
            decision = AgentSessionStateMachine.request_changes(
                current_status=session["status"],
                state_version=int(session["stateVersion"]),
                plan_generation=int(session["planGeneration"]),
                expected_state_version=int(session["stateVersion"]),
                current_plan_hash=str(session["activePlanHash"]),
                expected_plan_hash=request.expectedPlanHash,
            )
            changed = transition_agent_session(
                cfg,
                session_id,
                expected_state_version=int(session["stateVersion"]),
                expected_plan_hash=request.expectedPlanHash,
                event_type=decision.event_type,
                to_status=decision.to_status,
                request_id=request.requestId,
                actor=request.actor,
                idempotency_key=f"apply:{request.idempotencyKey}",
                payload={
                    "approvalId": approval["approvalId"],
                    "planRevisionId": plan["planRevisionId"],
                    "reason": request.reason,
                },
            )
            session = changed["session"]
        return {"session": session, "plan": plan, "approval": approval, "compiled": None}

    if session["status"] == "ready_to_run":
        return {
            "session": session,
            "plan": plan,
            "approval": approval,
            "compiled": _compile_approved_plan(cfg, plan),
        }
    if session["status"] != "awaiting_approval":
        raise AgentSessionStorageConflictError(
            f"AGENT_APPROVAL_SESSION_STATUS_INVALID: {session['status']}"
        )
    compiled = _compile_approved_plan(cfg, plan)
    revision_id = str(compiled["workflowRevisionId"])
    session = require_agent_session(cfg, session_id)
    decision = AgentSessionStateMachine.approve(
        current_status=session["status"],
        state_version=int(session["stateVersion"]),
        plan_generation=int(session["planGeneration"]),
        expected_state_version=int(session["stateVersion"]),
        current_plan_hash=str(session["activePlanHash"]),
        expected_plan_hash=request.expectedPlanHash,
        workflow_revision_id=revision_id,
    )
    completed = transition_agent_session(
        cfg,
        session_id,
        expected_state_version=int(session["stateVersion"]),
        expected_plan_hash=request.expectedPlanHash,
        expected_plan_generation=int(session["planGeneration"]),
        event_type=decision.event_type,
        to_status=decision.to_status,
        request_id=request.requestId,
        actor=request.actor,
        idempotency_key=f"compile:{request.idempotencyKey}",
        correlation_id=request.requestId,
        payload={
            "approvalId": approval["approvalId"],
            "planRevisionId": plan["planRevisionId"],
            "workflowRevisionId": revision_id,
        },
        workflow_revision_id=revision_id,
    )
    return {
        "session": completed["session"],
        "plan": plan,
        "approval": approval,
        "compiled": compiled,
    }


def cancel_agent_session_from_request(
    cfg: RemoteRunnerConfig,
    session_id: str,
    request: AgentCancelRequest,
) -> dict[str, Any]:
    command_hash = _hash_json(
        {
            "command": "cancel",
            "request": request.runtime_payload(),
            "sessionId": session_id,
        }
    )
    existing_event = _command_event(cfg, session_id, request.idempotencyKey)
    if existing_event is not None:
        if (
            existing_event["eventType"] != "agent.session_cancelled"
            or str(existing_event["payload"].get("commandHash") or "") != command_hash
        ):
            raise AgentSessionStorageConflictError("AGENT_COMMAND_IDEMPOTENCY_CONFLICT")
        return require_agent_session(cfg, session_id)
    session = require_agent_session(cfg, session_id)
    decision = AgentSessionStateMachine.cancel(
        current_status=session["status"],
        state_version=int(session["stateVersion"]),
        plan_generation=int(session["planGeneration"]),
        expected_state_version=request.expectedStateVersion,
    )
    if not decision.update_session:
        return session
    result = transition_agent_session(
        cfg,
        session_id,
        expected_state_version=request.expectedStateVersion,
        event_type=decision.event_type,
        to_status=decision.to_status,
        request_id=request.requestId,
        actor=request.actor,
        idempotency_key=request.idempotencyKey,
        payload={"commandHash": command_hash, "reason": request.reason},
    )
    return result["session"]


async def list_agent_sessions_from_http(authorization: str | None) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="agent_session.list")
    return data_response({"items": await run_sync(list_agent_sessions, cfg)})


async def create_agent_session_from_http(
    request: AgentSessionCreateRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="agent_session.create")
    _require_authenticated_actor(cfg, request.createdBy)
    return data_response(await run_sync(create_agent_session_from_request, cfg, request))


async def get_agent_session_from_http(session_id: str, authorization: str | None) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="agent_session.read")
    return data_response(await run_sync(require_agent_session, cfg, session_id))


async def list_agent_events_from_http(session_id: str, authorization: str | None) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="agent_session.events.read")
    await run_sync(require_agent_session, cfg, session_id)
    return data_response({"items": await run_sync(fetch_agent_events, cfg, session_id)})


async def list_agent_plans_from_http(session_id: str, authorization: str | None) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="agent_session.plans.read")
    await run_sync(require_agent_session, cfg, session_id)
    return data_response({"items": await run_sync(list_agent_plan_revisions, cfg, session_id)})


async def list_agent_approvals_from_http(session_id: str, authorization: str | None) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="agent_session.approvals.read")
    await run_sync(require_agent_session, cfg, session_id)
    return data_response({"items": await run_sync(list_agent_approvals, cfg, session_id)})


async def plan_agent_session_from_http(
    session_id: str,
    request: AgentPlanRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="agent_session.plan")
    _require_authenticated_actor(cfg, request.actor)
    return data_response(
        await run_sync(plan_agent_session_from_request, cfg, session_id, request, replan=False)
    )


async def replan_agent_session_from_http(
    session_id: str,
    request: AgentReplanRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="agent_session.replan")
    _require_authenticated_actor(cfg, request.actor)
    return data_response(
        await run_sync(plan_agent_session_from_request, cfg, session_id, request, replan=True)
    )


async def approve_agent_session_from_http(
    session_id: str,
    request: AgentApprovalRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="agent_session.approval")
    _require_authenticated_actor(cfg, request.actor)
    return data_response(await run_sync(approve_agent_session_from_request, cfg, session_id, request))


async def cancel_agent_session_from_http(
    session_id: str,
    request: AgentCancelRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="agent_session.cancel")
    _require_authenticated_actor(cfg, request.actor)
    return data_response(await run_sync(cancel_agent_session_from_request, cfg, session_id, request))


def _planning_transition(
    session: dict[str, Any],
    request: AgentPlanRequest | AgentReplanRequest,
    *,
    replan: bool,
):
    if replan:
        return AgentSessionStateMachine.request_replan(
            current_status=session["status"],
            state_version=int(session["stateVersion"]),
            plan_generation=int(session["planGeneration"]),
            expected_state_version=request.expectedStateVersion,
            max_replans=int(session["budget"]["maxReplans"]),
        )
    return AgentSessionStateMachine.start_planning(
        current_status=session["status"],
        state_version=int(session["stateVersion"]),
        plan_generation=int(session["planGeneration"]),
        expected_state_version=request.expectedStateVersion,
    )


def _target_plan_generation(
    cfg: RemoteRunnerConfig,
    session_id: str,
    request: AgentPlanRequest | AgentReplanRequest,
    *,
    replan: bool,
) -> int:
    existing = _command_event(cfg, session_id, request.idempotencyKey)
    if existing is not None:
        return int(existing["planGeneration"])
    session = require_agent_session(cfg, session_id)
    return int(session["planGeneration"]) + (1 if replan or session["planGeneration"] == 0 else 0)


def _mark_plan_failed(
    cfg: RemoteRunnerConfig,
    *,
    session_id: str,
    request: AgentPlanRequest | AgentReplanRequest,
    generation: int,
    draft: dict[str, Any],
    plan: dict[str, Any],
    validation: dict[str, Any],
) -> dict[str, Any]:
    session = require_agent_session(cfg, session_id)
    if session["status"] == "plan_failed":
        return session
    decision = AgentSessionStateMachine.plan_failed(
        current_status=session["status"],
        state_version=int(session["stateVersion"]),
        plan_generation=int(session["planGeneration"]),
        expected_state_version=int(session["stateVersion"]),
    )
    issues = validation.get("validationIssues") if isinstance(validation.get("validationIssues"), list) else []
    error_code = str((issues[0] if issues and isinstance(issues[0], dict) else {}).get("code") or "AGENT_PLAN_VALIDATION_FAILED")
    failed = transition_agent_session(
        cfg,
        session_id,
        expected_state_version=int(session["stateVersion"]),
        expected_plan_generation=generation,
        event_type=decision.event_type,
        to_status=decision.to_status,
        request_id=request.requestId,
        actor=str(request.proposal.planner.adapterId),
        idempotency_key=f"failed:{request.idempotencyKey}",
        correlation_id=request.requestId,
        payload={
            "draftId": draft["draftId"],
            "draftRevision": draft["revision"],
            "errorCode": error_code,
            "planHash": plan["planHash"],
            "planRevisionId": plan["planRevisionId"],
            "validationIssues": issues,
        },
        active_draft_id=draft["draftId"],
        active_draft_revision=int(draft["revision"]),
        active_plan_hash=str(plan["planHash"]),
        last_error_code=error_code,
    )
    return failed["session"]


def _completed_plan_result(
    cfg: RemoteRunnerConfig,
    session: dict[str, Any],
    generation: int,
) -> dict[str, Any] | None:
    plan = next(
        (item for item in list_agent_plan_revisions(cfg, session["sessionId"]) if item["planGeneration"] == generation),
        None,
    )
    if plan is None or session["status"] not in {"awaiting_approval", "ready_to_run", "changes_requested"}:
        return None
    draft = require_workflow_design_draft(cfg, str(plan["draftId"]))
    return {"session": session, "draft": draft, "plan": plan, "validation": plan["validation"]}


def _active_plan(cfg: RemoteRunnerConfig, session: dict[str, Any]) -> dict[str, Any]:
    plan = next(
        (
            item
            for item in reversed(list_agent_plan_revisions(cfg, session["sessionId"]))
            if item["planHash"] == session.get("activePlanHash")
        ),
        None,
    )
    if plan is None:
        raise AgentSessionStorageConflictError("AGENT_ACTIVE_PLAN_NOT_FOUND")
    return plan


def _compile_approved_plan(
    cfg: RemoteRunnerConfig,
    plan: dict[str, Any],
) -> dict[str, Any]:
    return compile_workflow_design_draft_export(
        cfg,
        str(plan["draftId"]),
        expected_revision=int(plan["draftRevision"]),
        expected_draft=dict(plan["proposal"]["draft"]),
    )


def _latest_plan_revision_id(cfg: RemoteRunnerConfig, session_id: str) -> str | None:
    plans = list_agent_plan_revisions(cfg, session_id)
    return str(plans[-1]["planRevisionId"]) if plans else None


def _command_event(cfg: RemoteRunnerConfig, session_id: str, idempotency_key: str) -> dict[str, Any] | None:
    return next(
        (item for item in fetch_agent_events(cfg, session_id) if item["idempotencyKey"] == idempotency_key),
        None,
    )


def _agent_draft(draft: dict[str, Any], *, session_id: str, plan_generation: int) -> dict[str, Any]:
    draft["provenance"] = {
        **dict(draft.get("provenance") or {}),
        "agentSessionId": session_id,
        "agentPlanGeneration": plan_generation,
    }
    return draft


def _agent_draft_id(session_id: str, plan_generation: int) -> str:
    digest = hashlib.sha256(f"{session_id}:{plan_generation}".encode("utf-8")).hexdigest()
    return f"wfd_agent_{digest[:16]}"


def _hash_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _optional_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _require_authenticated_actor(cfg: RemoteRunnerConfig, claimed_actor: str) -> None:
    principal = remote_runner_principal(cfg)
    if claimed_actor != principal.actor:
        raise RemoteRunnerAuthorizationError(
            "agent actor does not match authenticated runner principal"
        )
