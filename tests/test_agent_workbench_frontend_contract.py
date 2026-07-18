from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_APP = ROOT / "apps" / "web" / "app"
COMPONENTS = WEB_APP / "components"

FILES = {
    "root_route": WEB_APP / "workflows" / "page.tsx",
    "catalog_route": WEB_APP / "workflows" / "catalog" / "page.tsx",
    "page": COMPONENTS / "agent-workbench-page.tsx",
    "api": COMPONENTS / "agent-workbench-api.ts",
    "decode": COMPONENTS / "agent-workbench-decode.ts",
    "integrity": COMPONENTS / "agent-workbench-integrity.ts",
    "durable_proof": COMPONENTS / "agent-workbench-durable-proof.ts",
    "observation": COMPONENTS / "agent-session-observation.ts",
    "state": COMPONENTS / "use-agent-workbench-state.ts",
    "state_helpers": COMPONENTS / "agent-workbench-state-helpers.ts",
    "pending": COMPONENTS / "agent-workbench-pending.ts",
    "plan": COMPONENTS / "agent-plan-card.tsx",
    "approval": COMPONENTS / "agent-approval-panel.tsx",
    "workflow_api": COMPONENTS / "workflows-page-api.ts",
    "workflow_e2e": ROOT / "tests" / "e2e" / "workflow-lifecycle.spec.ts",
    "local_smoke": ROOT / "scripts" / "local_web_smoke.ps1",
}


def _source(name: str) -> str:
    return FILES[name].read_text(encoding="utf-8")


def _between(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def _assert_contains(source: str, *tokens: str) -> None:
    for token in tokens:
        assert token in source


def _assert_not_contains(source: str, *tokens: str) -> None:
    for token in tokens:
        assert token not in source


def test_workflow_root_is_agent_first_and_catalog_keeps_the_existing_library() -> None:
    root_source = _source("root_route")
    catalog_source = _source("catalog_route")

    _assert_contains(root_source, 'import { AgentWorkbenchPage }', "<AgentWorkbenchPage />")
    _assert_not_contains(root_source, "WorkflowsPage")
    _assert_contains(catalog_source, 'import { WorkflowsPage }', "<WorkflowsPage />")
    _assert_not_contains(catalog_source, "AgentWorkbenchPage")


def test_existing_catalog_browser_and_local_smoke_checks_use_the_catalog_route() -> None:
    e2e_source = _source("workflow_e2e")
    smoke_source = _source("local_smoke")
    catalog_test = _between(
        e2e_source,
        'test("browse workflow catalog page"',
        'test("navigate to workflow detail page"',
    )

    _assert_contains(catalog_test, 'page.goto("/workflows/catalog")', "流程目录")
    _assert_not_contains(catalog_test, 'page.goto("/workflows")')
    _assert_contains(
        smoke_source,
        '@{ Path = "/workflows"; Text = @("/workflows/catalog"',
        '@{ Path = "/workflows/catalog";',
        '"app/workflows/catalog/page.js"',
    )


def test_agent_workbench_composes_goal_plan_approval_and_durable_timeline() -> None:
    source = _source("page")

    _assert_contains(
        source,
        "useAgentWorkbenchState()",
        "AgentGoalComposer",
        "AgentSessionList",
        "AgentPlanCard",
        "AgentApprovalPanel",
        "AgentEventTimeline",
        "WorkflowWorkspaceTabs",
        'aria-label="Agent 工作台主内容"',
    )
    _assert_not_contains(source, "<main")


def test_browser_agent_command_payloads_are_server_bound_and_cannot_supply_authority_or_graphs() -> None:
    api_source = _source("api")
    create_input = _between(
        api_source,
        "export type CreateAgentSessionInput = {",
        "export type AgentReadInput = {",
    )
    command_input = _between(
        api_source,
        "export type AgentCommandInput = {",
        "export type PlanAgentSessionInput",
    )
    create_request = _between(
        api_source,
        "export async function createAgentSession",
        "export async function fetchAgentSessions",
    )
    plan_request = _between(
        api_source,
        "export async function planAgentSession",
        "export async function decideAgentPlan",
    )
    approval_request = _between(
        api_source,
        "export async function decideAgentPlan",
        "export async function cancelAgentSession",
    )
    cancel_request = _between(
        api_source,
        "export async function cancelAgentSession",
        "async function requireDurableCommandEvent",
    )
    command_body = _between(
        api_source,
        "function commandBody(input: AgentCommandInput)",
        "function readQuery",
    )
    request_surface = "\n".join(
        (
            create_input,
            command_input,
            create_request,
            plan_request,
            approval_request,
            cancel_request,
            command_body,
        )
    )

    _assert_contains(
        create_input,
        "serverId: string",
        "creationRequestId: string",
    )
    _assert_contains(
        command_input,
        "serverId: string",
        "sessionId: string",
        "requestId: string",
        "idempotencyKey: string",
        "expectedStateVersion: number",
    )
    _assert_contains(
        command_body,
        "serverId:",
        "requestId:",
        "idempotencyKey:",
        "expectedStateVersion:",
    )
    _assert_contains(plan_request, "body: command")
    _assert_contains(approval_request, "...commandBody(input)", "expectedPlanHash:")
    _assert_contains(cancel_request, "...commandBody(input)")
    _assert_not_contains(
        request_surface,
        "actor:",
        "createdBy:",
        "proposal:",
        "nodes:",
        "edges:",
    )


def test_reads_writes_and_reload_identity_remain_bound_to_one_server() -> None:
    api_source = _source("api")
    state_source = _source("state")
    workflow_api_source = _source("workflow_api")

    _assert_contains(
        api_source,
        "AGENT_WORKBENCH_SERVER_IDENTITY_CONFLICT",
        "AGENT_WORKBENCH_SERVER_IDENTITY_MISMATCH",
        "new URLSearchParams({",
        'serverId: requireInputText(serverId, "AGENT_WORKBENCH_SERVER_ID_REQUIRED")',
        "readQuery(input.serverId, input.refresh)",
    )
    _assert_contains(
        state_source,
        'searchParams.get("server")',
        'searchParams.get("session")',
        'query.set("server", serverId)',
        'query.set("session", sessionId)',
        "serverId: selectedServer.serverId",
        "serverId: server.serverId",
    )
    _assert_contains(
        workflow_api_source,
        'items.find((item) => item.serverId === expectedServerId)',
        '`${WORKFLOW_SERVER_CACHE_KEY}:${expectedServerId || "default"}`',
    )


def test_async_completions_are_identity_guarded_and_snapshots_never_regress() -> None:
    state_source = _source("state")
    helpers_source = _source("state_helpers")
    page_source = _source("page")

    _assert_contains(
        state_source,
        "identityRef.current.serverId === serverId",
        "identityRef.current.sessionId === sessionId",
        'if (sessionParam && !serverParam) throw new Error("AGENT_SESSION_SERVER_ID_REQUIRED")',
        "if (!isCurrentIdentity(intent.serverId, intent.sessionId)) return",
        "mergeAgentSnapshots(sameServer ? snapshotValueRef.current : null, value)",
        "mergeAgentSessionLists(sameServer ? sessionsValueRef.current : [], items)",
        "mergedSessions = upsertSession(sessionsValueRef.current, merged.session)",
        "setSnapshotValue(merged)",
        "setSessionsValue(mergedSessions)",
        "快照冲突；已保留最后一次可信状态",
        "会话列表冲突；已保留最后一次可信状态",
        "snapshotServerRef.current === serverId",
        "if (identityRef.current.sessionId === sessionId) return",
    )
    _assert_contains(
        helpers_source,
        "assertAgentSnapshotConsistent(next)",
        "assertImmutableSnapshotHistory(current, next)",
        "assertSnapshotHistoryContains(next, current)",
    )
    _assert_contains(
        page_source,
        "disabled={Boolean(state.busyAction)}",
        "state.selectedSession && !state.busyAction",
    )


def test_malformed_success_responses_fail_before_rendering_nested_agent_state() -> None:
    api_source = _source("api")
    decode_source = _source("decode")

    _assert_contains(
        decode_source,
        "function requireAgentWorkflowDraft",
        'draft.contractVersion !== "workflow-design-draft-v1"',
        "requireTextArray(goal.successCriteria, code)",
        "requireArray(draft.nodes, code)",
        "plan.planGeneration !== session.planGeneration",
        "session.activePlanHash !== plan.planHash",
        "approval.planRevisionId !== plan.planRevisionId",
        "session.workflowRevisionId === compiled.workflowRevisionId",
        "requireAgentSessionSnapshot",
        'record.contractVersion !== "agent-session-snapshot.v1"',
        "requireExactRecord(",
    )
    _assert_contains(
        api_source,
        "AGENT_SESSION_CREATE_RESPONSE_IDENTITY_MISMATCH",
        "result.approval.requestId !== input.requestId",
        "result.approval.idempotencyKey !== input.idempotencyKey",
        "AGENT_SESSION_APPROVAL_RESPONSE_IDENTITY_MISMATCH",
        "AGENT_SESSION_SNAPSHOT_ACTIVE_PLAN_MISMATCH",
        "AGENT_SESSION_SNAPSHOT_APPROVAL_PLAN_MISMATCH",
    )


def test_workspace_snapshot_is_one_atomic_server_bound_read() -> None:
    api_source = _source("api")
    snapshot_read = _between(
        api_source,
        "export async function fetchAgentSessionSnapshot",
        "export async function planAgentSession",
    )

    _assert_contains(
        snapshot_read,
        '"GET"',
        "/snapshot?${readQuery(serverId, input.refresh)}",
        "requireAgentSessionSnapshot(",
        "sessionId !== expectedSessionId",
        "plans.map((plan) => assertAgentPlanHash(plan))",
        "AGENT_SESSION_SNAPSHOT_ACTIVE_PLAN_MISMATCH",
        "AGENT_SESSION_SNAPSHOT_APPROVAL_PLAN_MISMATCH",
        '"plan_failed"',
        'session.status === "created"',
    )
    _assert_not_contains(
        snapshot_read,
        "fetchAgentSession(input)",
        "fetchAgentSessionEvents(input)",
        "fetchAgentPlanRevisions(input)",
        "fetchAgentApprovals(input)",
    )
    _assert_not_contains(
        api_source,
        "export async function fetchAgentSession(",
        "export async function fetchAgentSessionEvents(",
        "export async function fetchAgentPlanRevisions(",
        "export async function fetchAgentApprovals(",
        "function fetchAgentItems",
    )


def test_agent_numeric_contracts_reject_unsafe_javascript_integers() -> None:
    api_source = _source("api")
    decode_source = _source("decode")

    assert "Number.isInteger" not in decode_source
    _assert_contains(
        decode_source,
        "Number.isSafeInteger(value)",
        "requireRecordPositiveInteger",
        "requireRecordNonnegativeInteger",
    )
    _assert_contains(
        api_source,
        "function addSafeStateVersion",
        "Number.isSafeInteger(next)",
        "planningStateVersion",
        "completedStateVersion",
        "decidedStateVersion",
        "cancelledStateVersion",
    )


def test_browser_recomputes_upload_and_plan_digests_before_approval() -> None:
    api_source = _source("api")
    integrity_source = _source("integrity")

    _assert_contains(
        api_source,
        "sha256Hex(await file.arrayBuffer())",
        "created.sha256 !== localSha256",
        "verified.sha256 !== localSha256",
        "await assertAgentPlanHash(result.plan)",
        "plans.map((plan) => assertAgentPlanHash(plan))",
    )
    _assert_contains(
        integrity_source,
        "parentPlanRevisionId: plan.parentPlanRevisionId ?? null",
        "proposal: plan.proposal",
        "validation: plan.validation",
        "JSON.parse(plan.canonicalPayload)",
        "agentJsonEqual(boundPayload, payload)",
        "sha256Hex(plan.canonicalPayload)",
        "AGENT_PLAN_CANONICAL_HASH_MISMATCH",
        "Number.isFinite(value)",
    )


def test_plan_card_is_a_read_only_projection_and_approval_is_hash_and_version_bound() -> None:
    plan_source = _source("plan")
    approval_source = _source("approval")
    api_source = _source("api")
    state_source = _source("state")
    plan_props = _between(plan_source, "export type AgentPlanCardProps = {", "type ToolRow")
    decide_flow = _between(state_source, "const decide = useCallback(", "const cancel = useCallback")

    _assert_contains(
        plan_source,
        'data-read-only="true"',
        "高级：Execution graph（只读）",
        "不支持拖拽、连线或参数编辑",
        "Approval-bound planHash",
    )
    _assert_contains(plan_props, "parentPlan?: AgentPlanRevision | null", "plan: AgentPlanRevision")
    _assert_not_contains(plan_props, "onChange", "onConnect", "onNodesChange", "onEdgesChange")
    _assert_contains(
        api_source,
        "expectedStateVersion: number",
        "expectedPlanHash: string",
        "expectedPlanHash: requireInputText(",
    )
    _assert_contains(
        decide_flow,
        "snapshot.session.stateVersion",
        "expectedPlanHash: currentPlan.planHash",
        "await decideAgentPlan(command)",
    )
    _assert_contains(
        approval_source,
        "本审批精确绑定到当前 PlanRevision、draft revision 和 planHash",
        'data-testid="agent-approval-review-confirmation"',
        "确认批准并编译",
    )


def test_ready_to_run_never_submits_a_run_and_replan_recovery_is_explicit() -> None:
    api_source = _source("api")
    state_source = _source("state")
    approval_source = _source("approval")
    command_surface = "\n".join((api_source, state_source))
    ready_panel = _between(
        approval_source,
        '{session.status === "ready_to_run" ? (',
        '{session.status === "plan_failed" || session.status === "changes_requested" ? (',
    )
    unsupported_panel = _between(
        approval_source,
        "function UnsupportedReplan({",
        "function CancelButton({",
    )

    _assert_contains(
        ready_panel,
        'data-testid="agent-ready-to-run"',
        "不可变 WorkflowRevision 已编译",
        "本次审批没有提交 Run",
        "运行授权属于后续独立控制点",
    )
    _assert_not_contains(
        command_surface,
        '"/api/v1/runs',
        "submitRun(",
        "submitWorkflowRun(",
        '"/replan"',
        "replanAgentSession(",
    )
    _assert_contains(
        unsupported_panel,
        "WORKFLOW_FASTQ_QC_REPLAN_ADJUSTMENT_UNSUPPORTED",
        "只有 adapter 声明并实际应用 typed adjustment 后",
        "重规划（当前不支持）",
        "disabled",
        "<RefreshButton",
        "<CancelButton",
        "按新目标创建会话",
    )
    _assert_contains(
        approval_source,
        "刷新状态",
        "取消会话",
        'data-testid="agent-cancel-dialog"',
        'data-testid="agent-cancel-confirm"',
        "取消会进入不可逆终态",
        "确认取消并保留历史",
        "同一会话不能按自由文本自动 replan",
        "基于修改后的目标或输入新建会话",
        "旧 lineage 保留",
    )


def test_uncertain_commands_reuse_durable_identity_instead_of_forking_effects() -> None:
    state_source = _source("state")
    pending_source = _source("pending")
    approval_flow = _between(
        state_source,
        "const decide = useCallback(",
        "const cancel = useCallback",
    )
    planning_flow = _between(
        state_source,
        "const resumePlanning = useCallback(",
        "const decide = useCallback",
    )
    create_flow = _between(
        state_source,
        "const submitGoal = useCallback(",
        "const resumePlanning = useCallback",
    )
    cancel_flow = _between(
        state_source,
        "const cancel = useCallback",
        "const selectSession = useCallback",
    )

    _assert_contains(
        state_source,
        'readPending("create", selectedServer.serverId, "new")',
        "await createAgentSession(pendingCreate.body)",
        'readPending("create", serverId, "new")',
        "createInput = reusableCreate.body",
        "pending = reusableCreate",
        'pendingCommand("plan"',
    )
    _assert_contains(
        pending_source,
        "window.localStorage.setItem",
        "window.localStorage.getItem",
        "agent-workbench-pending-command.v1",
        "AGENT_PENDING_COMMAND_STORE_FAILED",
        "AGENT_PENDING_COMMAND_READ_FAILED",
        "AGENT_PENDING_COMMAND_INVALID",
        "throw pendingStorageError",
        "Number.isSafeInteger(body.expectedStateVersion)",
    )
    _assert_contains(
        create_flow,
        "storePending(pending)",
        "durableCreatePending = true",
        "created = await createAgentSession(createInput)",
    )
    _assert_contains(
        planning_flow,
        'candidate.eventType === "agent.plan_requested"',
        "requestId: event.requestId",
        "idempotencyKey: event.idempotencyKey",
        "expectedStateVersion: Math.max(1, event.stateVersion - 1)",
    )
    _assert_contains(
        approval_flow,
        "snapshot.approvals",
        "requestId: durableApproval.requestId",
        "idempotencyKey: durableApproval.idempotencyKey",
        "expectedStateVersion: durableApproval.expectedStateVersion",
        "expectedPlanHash: durableApproval.planHash",
        "AGENT_APPROVAL_PENDING_DECISION_MISMATCH",
        "AGENT_APPROVAL_RECOVERY_DECISION_MISMATCH",
        "storedDecision.body.serverId === serverId",
        "storedDecision.body.sessionId === sessionId",
    )
    _assert_contains(
        cancel_flow,
        'readPending("cancel", serverId, sessionId)',
        'stored?.kind === "cancel"',
        "stored.body.expectedStateVersion === snapshot.session.stateVersion",
        "pending = reusable || pendingCommand",
        "storePending(pending)",
        "await cancelAgentSession(command)",
    )


def test_create_and_command_successes_are_bound_to_current_identity_and_durable_events() -> None:
    api_source = _source("api")
    durable_proof_source = _source("durable_proof")
    state_source = _source("state")
    create_flow = _between(
        state_source,
        "const submitGoal = useCallback(",
        "const resumePlanning = useCallback",
    )
    plan_api = _between(
        api_source,
        "export async function planAgentSession",
        "export async function decideAgentPlan",
    )
    approval_api = _between(
        api_source,
        "export async function decideAgentPlan",
        "export async function cancelAgentSession",
    )
    cancel_api = _between(
        api_source,
        "export async function cancelAgentSession",
        "async function requireDurableCommandEvent",
    )
    event_binding = _between(
        api_source,
        "async function requireDurableCommandEvent",
        "function optionalEventText",
    )

    _assert_contains(
        create_flow,
        "server.serverId !== serverParam",
        "originIdentity.serverId !== serverParam",
        "originIdentity.sessionId !== sessionParam",
        "Boolean(originIdentity.sessionId)",
    )
    _assert_contains(
        plan_api,
        '"agent.plan_requested"',
        "planningStateVersion",
        "completedStateVersion",
        "commandEvent.planGeneration !== result.session.planGeneration",
        "result.session.stateVersion !== completedStateVersion",
    )
    _assert_contains(
        approval_api,
        "decidedStateVersion",
        "result.session.stateVersion !== decidedStateVersion",
        "fetchAgentSessionSnapshot({",
        "assertAgentApprovalDurableProof(snapshot, result)",
    )
    _assert_contains(
        durable_proof_source,
        '"agent.workflow_revision_compiled"',
        '"agent.changes_requested"',
        "event.payload.approvalId === approval.approvalId",
        "event.payload.planRevisionId === plan.planRevisionId",
        "event.stateVersion === session.stateVersion",
        "durable.stateVersion < response.stateVersion",
        "durable.planGeneration < response.planGeneration",
        "reason: approval.reason ?? null",
        "parentPlanRevisionId: plan.parentPlanRevisionId ?? null",
    )
    _assert_contains(
        cancel_api,
        '"agent.session_cancelled"',
        "cancelledStateVersion",
        'session.status !== "cancelled"',
        "session.stateVersion !== commandEvent.stateVersion",
        "eventReason !== reason",
    )
    _assert_not_contains(cancel_api, "session.stateVersion < input.expectedStateVersion")
    _assert_contains(
        event_binding,
        "fetchAgentSessionSnapshot({",
        "event.sessionId === sessionId",
        "event.requestId === requestId",
        "event.idempotencyKey === idempotencyKey",
        "event.stateVersion === expectedNewStateVersion",
        "matches.length !== 1",
    )


def test_invalid_or_changed_server_identity_clears_stale_workspace_state() -> None:
    state_source = _source("state")
    bootstrap = _between(state_source, "async function bootstrap()", "const refreshWorkspace")
    refresh = _between(state_source, "const refreshWorkspace", "const refreshSelectedAfterConflict")

    _assert_contains(
        bootstrap,
        "setServer(null)",
        "setSessionsValue([])",
        "setSnapshotValue(null)",
        "snapshotServerRef.current = serverParam",
    )
    _assert_contains(
        refresh,
        "const originIdentity = { ...identityRef.current }",
        "originIdentity.sessionId && !originIdentity.serverId",
        "AGENT_SESSION_SERVER_ID_REQUIRED",
        "...(originIdentity.serverId ? { serverId: originIdentity.serverId } : {})",
        "completionIdentity = { serverId: selectedServer.serverId, sessionId: \"\" }",
        "replaceIdentity(selectedServer.serverId)",
        "sameIdentity(identityRef.current, completionIdentity)",
        'setBusyAction("")',
    )


def test_agent_session_observation_is_a_pure_atomic_snapshot_derivation() -> None:
    source = _source("observation")
    signature_match = re.search(
        r"export function deriveAgentSessionObservation\((.*?)\)\s*"
        r":\s*AgentSessionObservationV1\s*\{",
        source,
        re.DOTALL,
    )

    assert signature_match is not None
    signature = signature_match.group(1)
    _assert_contains(
        source,
        "import type {",
        "AgentSessionSnapshot",
        'contractVersion: "agent-session-observation.v1"',
        "const events = snapshot.events",
        "const { session } = snapshot",
        "plans: snapshot.plans.length",
        "approvals: snapshot.approvals.length",
    )
    _assert_contains(
        signature, "snapshot: AgentSessionSnapshot", "observedAtEpochMs: number"
    )
    _assert_not_contains(
        signature, "serverId:", "sessionId:", "events:", "plans:", "approvals:"
    )
    _assert_not_contains(
        source,
        '"use client"',
        "fetch(",
        "XMLHttpRequest",
        "axios",
        "createAgentSession(",
        "planAgentSession(",
        "decideAgentPlan(",
        "cancelAgentSession(",
        "fetchAgentSessionSnapshot(",
        "useEffect(",
        "useState(",
        "window.",
        "document.",
        "localStorage",
        "sessionStorage",
        "Date.now(",
        "Math.random(",
        "crypto.randomUUID(",
    )
    assert re.search(r"^import (?!type\b)", source, re.MULTILINE) is None
    assert re.search(r"\basync\b|\bPromise\s*<", source) is None
    assert (
        re.search(
            r"\bsnapshot(?:\.[A-Za-z_$][\w$]*|\[[^\]]+\])+\s*"
            r"(?:=(?!=)|\+=|-=|\+\+|--)",
            source,
        )
        is None
    )
    assert (
        re.search(
            r"snapshot\.(?:events|plans|approvals)\."
            r"(?:copyWithin|fill|pop|push|reverse|shift|sort|splice|unshift)\(",
            source,
        )
        is None
    )


def test_agent_session_observation_has_fixed_redaction_and_stable_error_codes() -> None:
    source = _source("observation")
    policy = _between(
        source,
        "const REDACTION_POLICY = Object.freeze({",
        "} as const);",
    )
    expected_redactions = {
        "eventPayloadsDisplayed",
        "commandHashesExposed",
        "requestIdentitiesDisplayed",
        "actorsDisplayed",
        "pathsOrUrisDisplayed",
        "rawModelOutputDisplayed",
        "credentialsDisplayed",
    }
    actual_redactions = set(
        re.findall(r"^\s*([A-Za-z]+): false,?$", policy, re.MULTILINE)
    )

    assert actual_redactions == expected_redactions
    _assert_not_contains(policy, "true", "snapshot")
    _assert_contains(
        source,
        "export const AGENT_SESSION_OBSERVATION_ERRORS = Object.freeze({",
        "} as const);",
        "code: (typeof AGENT_SESSION_OBSERVATION_ERRORS)",
        "throw new Error(code)",
        "redactionPolicy: { ...REDACTION_POLICY }",
    )
    assert re.search(r"\bevent\s*(?:\.|\[)\s*[\"']?payload\b", source) is None
    assert re.search(r"\bpayload\b", source) is None
    error_values = re.findall(
        r'"(AGENT_SESSION_OBSERVATION_[A-Z0-9_]+)"',
        _between(
            source,
            "export const AGENT_SESSION_OBSERVATION_ERRORS = Object.freeze({",
            "} as const);",
        ),
    )
    assert len(error_values) >= 10
    assert len(error_values) == len(set(error_values))
    assert re.findall(r"throw new Error\((.*?)\)", source, re.DOTALL) == ["code"]
    _assert_not_contains(
        source, "JSON.stringify(snapshot)", "new Error(`", "new Error(message)"
    )
