"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import {
  cancelAgentSession,
  createAgentSession,
  decideAgentPlan,
  fetchAgentSessionSnapshot,
  fetchAgentSessions,
  loadAgentServer,
  planAgentSession,
  uploadAndVerifyAgentFastq,
  type AgentCommandInput,
  type CreateAgentSessionInput,
  type DecideAgentPlanInput,
} from "./agent-workbench-api";
import {
  agentFastqContext,
  latestAgentPlan,
  type AgentBudget,
  type AgentSession,
  type AgentSessionSnapshot,
  type AgentWorkbenchProblem,
} from "./agent-workbench-model";
import type { AgentGoalComposerSubmission } from "./agent-goal-composer";
import {
  clearPending,
  pendingCommand,
  readPending,
  storePending,
} from "./agent-workbench-pending";
import {
  agentProblem,
  approvalStillNeedsReplay,
  isUncertainCommandFailure,
  mergeAgentSessionLists,
  mergeAgentSnapshots,
  newCommandIntent,
  sameIdentity,
  uniqueCommandId,
  upsertSession,
} from "./agent-workbench-state-helpers";
import type { WorkflowServer } from "./workflows-page-model";

type AgentWorkbenchBusyAction =
  | ""
  | "bootstrap"
  | "refresh"
  | "create"
  | "plan"
  | "approve"
  | "request_changes"
  | "cancel";

type ComposerPrefill = {
  budget?: AgentBudget;
  projectId?: string;
  successCriterion?: string;
  summary?: string;
  version: number;
};
export function useAgentWorkbenchState() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const serverParam = (searchParams.get("server") || "").trim();
  const sessionParam = (searchParams.get("session") || "").trim();
  const observedUrlIdentity = `${serverParam}\u0000${sessionParam}`;
  const observedUrlIdentityRef = useRef(observedUrlIdentity);
  const identityRef = useRef({ serverId: serverParam, sessionId: sessionParam });
  if (observedUrlIdentityRef.current !== observedUrlIdentity) {
    observedUrlIdentityRef.current = observedUrlIdentity;
    identityRef.current = { serverId: serverParam, sessionId: sessionParam };
  }
  const [server, setServer] = useState<WorkflowServer | null>(null);
  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [snapshot, setSnapshot] = useState<AgentSessionSnapshot | null>(null);
  const [busyAction, setBusyAction] = useState<AgentWorkbenchBusyAction>("bootstrap");
  const [problem, setProblem] = useState<AgentWorkbenchProblem | null>(null);
  const [statusMessage, setStatusMessage] = useState("正在连接 Agent 控制面");
  const [composerPrefill, setComposerPrefill] = useState<ComposerPrefill>({ version: 0 });
  const sessionsValueRef = useRef<AgentSession[]>([]);
  const snapshotValueRef = useRef<AgentSessionSnapshot | null>(null);
  const loadSequence = useRef(0);
  const sessionsServerRef = useRef(serverParam);
  const snapshotServerRef = useRef(serverParam);
  const selectedSession = snapshot?.session || null;
  const currentPlan = useMemo(
    () => (snapshot ? latestAgentPlan(snapshot.plans) : null),
    [snapshot]
  );
  const parentPlan = useMemo(() => {
    if (!snapshot || !currentPlan?.parentPlanRevisionId) return null;
    return (
      snapshot.plans.find(
        (candidate) => candidate.planRevisionId === currentPlan.parentPlanRevisionId
      ) || null
    );
  }, [currentPlan, snapshot]);

  const replaceIdentity = useCallback(
    (serverId: string, sessionId = "") => {
      identityRef.current = { serverId, sessionId };
      const query = new URLSearchParams();
      query.set("server", serverId);
      if (sessionId) query.set("session", sessionId);
      router.replace(`/workflows?${query.toString()}`, { scroll: false });
    },
    [router]
  );
  const isCurrentIdentity = useCallback((serverId: string, sessionId: string) => {
    return (
      identityRef.current.serverId === serverId &&
      identityRef.current.sessionId === sessionId
    );
  }, []);

  const setSnapshotValue = useCallback((value: AgentSessionSnapshot | null) => {
    snapshotValueRef.current = value;
    setSnapshot(value);
  }, []);
  const setSessionsValue = useCallback((value: AgentSession[]) => {
    sessionsValueRef.current = value;
    setSessions(value);
  }, []);
  const applySnapshot = useCallback((serverId: string, value: AgentSessionSnapshot) => {
    if (!isCurrentIdentity(serverId, value.session.sessionId)) return false;
    const sameServer = snapshotServerRef.current === serverId;
    let merged: AgentSessionSnapshot;
    let mergedSessions: AgentSession[];
    try {
      merged = mergeAgentSnapshots(sameServer ? snapshotValueRef.current : null, value);
      mergedSessions = upsertSession(sessionsValueRef.current, merged.session);
    } catch (error) {
      setProblem(agentProblem(error, "Agent 快照一致性校验失败"));
      setStatusMessage("快照冲突；已保留最后一次可信状态");
      return false;
    }
    snapshotServerRef.current = serverId;
    sessionsServerRef.current = serverId;
    setSnapshotValue(merged);
    setSessionsValue(mergedSessions);
    return true;
  }, [isCurrentIdentity, setSessionsValue, setSnapshotValue]);

  const applySessionList = useCallback((serverId: string, items: AgentSession[]) => {
    const currentServerId = identityRef.current.serverId;
    if (currentServerId && currentServerId !== serverId) return false;
    const sameServer = sessionsServerRef.current === serverId;
    let merged: AgentSession[];
    try {
      merged = mergeAgentSessionLists(sameServer ? sessionsValueRef.current : [], items);
    } catch (error) {
      setProblem(agentProblem(error, "Agent 会话列表一致性校验失败"));
      setStatusMessage("会话列表冲突；已保留最后一次可信状态");
      return false;
    }
    sessionsServerRef.current = serverId;
    setSessionsValue(merged);
    return true;
  }, [setSessionsValue]);

  useEffect(() => {
    const sequence = ++loadSequence.current;
    let cancelled = false;

    async function bootstrap() {
      setBusyAction("bootstrap");
      setProblem(null);
      setStatusMessage("正在读取远程 Agent 会话");
      setServer(null);
      setSessionsValue([]);
      setSnapshotValue(null);
      sessionsServerRef.current = serverParam;
      snapshotServerRef.current = serverParam;
      try {
        if (sessionParam && !serverParam) throw new Error("AGENT_SESSION_SERVER_ID_REQUIRED");
        const selectedServer = await loadAgentServer(
          serverParam ? { serverId: serverParam } : {}
        );
        const items = await fetchAgentSessions({ serverId: selectedServer.serverId });
        if (cancelled || sequence !== loadSequence.current) return;
        setServer(selectedServer);
        applySessionList(selectedServer.serverId, items);
        if (!sessionParam) {
          const pendingCreate = readPending("create", selectedServer.serverId, "new");
          if (pendingCreate?.kind === "create") {
            setStatusMessage("正在复用上次结果不确定的会话创建命令");
            let recovered: AgentSession;
            try {
              recovered = await createAgentSession(pendingCreate.body);
              clearPending(pendingCreate);
            } catch (error) {
              if (!isUncertainCommandFailure(error)) clearPending(pendingCreate);
              throw error;
            }
            if (cancelled || sequence !== loadSequence.current) return;
            replaceIdentity(selectedServer.serverId, recovered.sessionId);
            const createdSnapshot = await fetchAgentSessionSnapshot({
              serverId: selectedServer.serverId,
              sessionId: recovered.sessionId,
              refresh: true,
            });
            if (cancelled || sequence !== loadSequence.current) return;
            if (!applySnapshot(selectedServer.serverId, createdSnapshot)) return;
            if (createdSnapshot.session.status !== "created") {
              setStatusMessage("会话已由其他命令推进；已恢复权威状态，未重复规划");
              return;
            }

            const intent = newCommandIntent(
              selectedServer.serverId,
              recovered.sessionId,
              recovered.stateVersion,
              "plan"
            );
            const pendingPlan = pendingCommand(
              "plan",
              selectedServer.serverId,
              recovered.sessionId,
              intent
            );
            storePending(pendingPlan);
            setStatusMessage("会话创建已恢复，正在生成同一目标的结构化方案");
            try {
              await planAgentSession(intent);
              clearPending(pendingPlan);
            } catch (error) {
              if (!isUncertainCommandFailure(error)) clearPending(pendingPlan);
              if (!cancelled && sequence === loadSequence.current) {
                setProblem(agentProblem(error, "恢复规划命令未完成"));
                setStatusMessage("规划结果不确定；原命令已保存，可从会话继续恢复");
              }
            }
            try {
              const recoveredSnapshot = await fetchAgentSessionSnapshot({
                serverId: selectedServer.serverId,
                sessionId: recovered.sessionId,
                refresh: true,
              });
              applySnapshot(selectedServer.serverId, recoveredSnapshot);
            } catch {
              // The URL and pending command retain enough identity for an explicit refresh.
            }
            return;
          }
        }
        if (!serverParam) {
          replaceIdentity(selectedServer.serverId, sessionParam);
        }
        if (sessionParam) {
          const nextSnapshot = await fetchAgentSessionSnapshot({
            serverId: selectedServer.serverId,
            sessionId: sessionParam,
          });
          if (cancelled || sequence !== loadSequence.current) return;
          if (applySnapshot(selectedServer.serverId, nextSnapshot)) {
            setStatusMessage(`已恢复会话 ${sessionParam}`);
          }
        } else {
          setSnapshotValue(null);
          setStatusMessage("Agent 控制面已就绪，可创建目标");
        }
      } catch (error) {
        if (cancelled || sequence !== loadSequence.current) return;
        setProblem(agentProblem(error, "Agent 控制面加载失败"));
        setStatusMessage("Agent 控制面加载失败");
      } finally {
        if (!cancelled && sequence === loadSequence.current) setBusyAction("");
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
    // Deliberately key durable identity to URL parameters, not transient state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    applySessionList,
    applySnapshot,
    replaceIdentity,
    serverParam,
    sessionParam,
    setSessionsValue,
    setSnapshotValue,
  ]);

  const refreshWorkspace = useCallback(
    async (forceRefresh = true) => {
      const originIdentity = { ...identityRef.current };
      let completionIdentity = originIdentity;
      setBusyAction("refresh");
      setProblem(null);
      setStatusMessage("正在从远程 runner 刷新持久状态");
      try {
        if (originIdentity.sessionId && !originIdentity.serverId) {
          throw new Error("AGENT_SESSION_SERVER_ID_REQUIRED");
        }
        const selectedServer = await loadAgentServer({
          forceRefresh,
          ...(originIdentity.serverId ? { serverId: originIdentity.serverId } : {}),
        });
        const [items, nextSnapshot] = await Promise.all([
          fetchAgentSessions({ serverId: selectedServer.serverId, refresh: forceRefresh }),
          originIdentity.sessionId
            ? fetchAgentSessionSnapshot({
                serverId: selectedServer.serverId,
                sessionId: originIdentity.sessionId,
                refresh: forceRefresh,
              })
            : Promise.resolve(null),
        ]);
        if (!sameIdentity(identityRef.current, originIdentity)) return;
        if (!originIdentity.serverId) {
          completionIdentity = { serverId: selectedServer.serverId, sessionId: "" };
          replaceIdentity(selectedServer.serverId);
        }
        setServer(selectedServer);
        applySessionList(selectedServer.serverId, items);
        if (nextSnapshot && !applySnapshot(selectedServer.serverId, nextSnapshot)) return;
        setStatusMessage("远程持久状态已刷新");
      } catch (error) {
        if (!sameIdentity(identityRef.current, completionIdentity)) return;
        setProblem(agentProblem(error, "刷新 Agent 控制面失败"));
        setStatusMessage("刷新失败；仍保留最后一次成功快照");
      } finally {
        if (sameIdentity(identityRef.current, completionIdentity)) setBusyAction("");
      }
    },
    [applySessionList, applySnapshot, replaceIdentity]
  );

  const refreshSelectedAfterConflict = useCallback(async () => {
    const serverId = serverParam || server?.serverId;
    const sessionId = snapshot?.session.sessionId || sessionParam;
    if (!serverId || !sessionId) return null;
    try {
      const nextSnapshot = await fetchAgentSessionSnapshot({
        serverId,
        sessionId,
        refresh: true,
      });
      return applySnapshot(serverId, nextSnapshot) ? nextSnapshot : null;
    } catch {
      // The command error remains primary; the last successful snapshot stays visible.
      return null;
    }
  }, [applySnapshot, server?.serverId, serverParam, sessionParam, snapshot?.session.sessionId]);

  const runPlan = useCallback(
    async (intent: AgentCommandInput) => {
      if (!isCurrentIdentity(intent.serverId, intent.sessionId)) return;
      const pending = pendingCommand("plan", intent.serverId, intent.sessionId, intent);
      storePending(pending);
      setBusyAction("plan");
      setProblem(null);
      setStatusMessage("正在生成并验证结构化 FASTQ QC 方案");
      try {
        await planAgentSession(intent);
        clearPending(pending);
        if (!isCurrentIdentity(intent.serverId, intent.sessionId)) return;
        const nextSnapshot = await fetchAgentSessionSnapshot({
          serverId: intent.serverId,
          sessionId: intent.sessionId,
          refresh: true,
        });
        if (applySnapshot(intent.serverId, nextSnapshot)) {
          setStatusMessage("方案已持久化，等待 hash 绑定审批");
        }
      } catch (error) {
        if (!isUncertainCommandFailure(error)) clearPending(pending);
        if (!isCurrentIdentity(intent.serverId, intent.sessionId)) return;
        try {
          const nextSnapshot = await fetchAgentSessionSnapshot({
            serverId: intent.serverId,
            sessionId: intent.sessionId,
            refresh: true,
          });
          applySnapshot(intent.serverId, nextSnapshot);
        } catch {
          // The command error remains primary; the last successful snapshot stays visible.
        }
        setProblem(agentProblem(error, "方案生成未完成"));
        setStatusMessage(
          isUncertainCommandFailure(error)
            ? "结果不确定；已保存原命令，可安全重放"
            : "方案生成被明确拒绝"
        );
      } finally {
        if (isCurrentIdentity(intent.serverId, intent.sessionId)) setBusyAction("");
      }
    },
    [applySnapshot, isCurrentIdentity]
  );

  const submitGoal = useCallback(
    async (submission: AgentGoalComposerSubmission) => {
      const originIdentity = { ...identityRef.current };
      if (
        !server?.serverId ||
        !serverParam ||
        server.serverId !== serverParam ||
        originIdentity.serverId !== serverParam ||
        originIdentity.sessionId !== sessionParam ||
        Boolean(originIdentity.sessionId)
      ) {
        setProblem({ code: "AGENT_WORKBENCH_READY_SERVER_REQUIRED", message: "远程 runner 尚未就绪。" });
        return;
      }
      const serverId = server.serverId;
      let durableCreatePending = false;
      setBusyAction("create");
      setProblem(null);
      try {
        const storedCreate = readPending("create", serverId, "new");
        const reusableCreate =
          storedCreate?.kind === "create" && storedCreate.body.serverId === serverId
            ? storedCreate
            : null;
        if (storedCreate && !reusableCreate) clearPending(storedCreate);
        let createInput: CreateAgentSessionInput;
        let pending: ReturnType<typeof pendingCommand>;
        if (reusableCreate) {
          createInput = reusableCreate.body;
          pending = reusableCreate;
          setStatusMessage("正在重放上次结果不确定的会话创建命令");
        } else {
          setStatusMessage("正在上传并权威核对 FASTQ manifest");
          const upload = await uploadAndVerifyAgentFastq({ serverId, files: [submission.file] });
          if (!sameIdentity(identityRef.current, originIdentity)) return;
          createInput = {
            serverId,
            projectId: submission.projectId,
            creationRequestId: uniqueCommandId("agent-create"),
            goal: {
              summary: submission.summary,
              successCriteria: [submission.successCriterion],
              context: {
                schemaVersion: "agent-fastq-qc-goal.v1",
                analysis: "fastq-qc",
                inputs: [upload],
                reportFormat: "multiqc-html",
              },
            },
            constraints: {
              allowedToolRevisionIds: [],
              forbiddenActions: ["arbitrary_shell", "undeclared_network"],
              requirements: {
                evidence: "multiqc-html",
                inputMode: "single-uncompressed-fastq",
                networkAccess: "declared-only",
              },
            },
            budget: submission.budget,
          };
          pending = pendingCommand("create", serverId, "new", createInput);
          setStatusMessage("上传已核验，正在持久化 Agent 目标");
        }
        storePending(pending);
        durableCreatePending = true;
        let created: AgentSession;
        try {
          created = await createAgentSession(createInput);
          clearPending(pending);
          durableCreatePending = false;
        } catch (error) {
          if (!isUncertainCommandFailure(error)) clearPending(pending);
          throw error;
        }
        if (!sameIdentity(identityRef.current, originIdentity)) return;
        replaceIdentity(serverId, created.sessionId);
        let createdSnapshot: AgentSessionSnapshot;
        try {
          createdSnapshot = await fetchAgentSessionSnapshot({
            serverId,
            sessionId: created.sessionId,
            refresh: true,
          });
        } catch (error) {
          setProblem(agentProblem(error, "会话已创建，但权威快照读取失败"));
          setStatusMessage("会话已创建；请刷新以恢复权威状态");
          setBusyAction("");
          return;
        }
        if (!applySnapshot(serverId, createdSnapshot)) { setBusyAction(""); return; }
        if (createdSnapshot.session.status !== "created") {
          setStatusMessage("会话已由其他命令推进；已恢复权威状态，未重复规划");
          setBusyAction(""); return;
        }
        const planIntent = newCommandIntent(serverId, created.sessionId, created.stateVersion, "plan");
        await runPlan(planIntent);
      } catch (error) {
        if (!sameIdentity(identityRef.current, originIdentity)) return;
        setProblem(agentProblem(error, "Agent 会话创建失败"));
        setStatusMessage(
          isUncertainCommandFailure(error) && durableCreatePending
            ? "结果不确定；已保存可恢复命令"
            : "Agent 会话创建失败"
        );
        setBusyAction("");
      }
    },
    [applySnapshot, replaceIdentity, runPlan, server, serverParam, sessionParam]
  );

  const resumePlanning = useCallback(async () => {
    if (!server || !snapshot) return;
    const { session, events } = snapshot;
    if (session.status !== "created" && session.status !== "planning") return;
    const stored = readPending("plan", server.serverId, session.sessionId);
    let intent = stored?.kind === "plan" ? stored.body : null;
    if (session.status === "planning") {
      const event = events
        .filter((candidate) => candidate.eventType === "agent.plan_requested")
        .sort((left, right) => right.sequence - left.sequence)[0];
      if (!event) {
        setProblem({
          code: "AGENT_PLAN_REPLAY_INTENT_UNAVAILABLE",
          message: "planning 状态缺少 durable agent.plan_requested 事件，拒绝猜测恢复命令。",
          nextAction: "刷新会话或检查远程 runner 审计存储。",
        });
        return;
      }
      intent = {
        serverId: server.serverId,
        sessionId: session.sessionId,
        requestId: event.requestId,
        idempotencyKey: event.idempotencyKey,
        expectedStateVersion: Math.max(1, event.stateVersion - 1),
      };
    }
    await runPlan(
      intent || newCommandIntent(server.serverId, session.sessionId, session.stateVersion, "plan")
    );
  }, [runPlan, server, snapshot]);

  const decide = useCallback(
    async (decision: "approve" | "request_changes", reason: string) => {
      if (!server || !snapshot || !currentPlan) return;
      const serverId = server.serverId;
      const sessionId = snapshot.session.sessionId;
      if (!isCurrentIdentity(serverId, sessionId)) return;
      const durableApproval = snapshot.approvals
        .filter(
          (candidate) =>
            candidate.planRevisionId === currentPlan.planRevisionId &&
            candidate.planHash === currentPlan.planHash &&
            candidate.expectedStateVersion === snapshot.session.stateVersion
        )
        .sort((left, right) => right.createdAt.localeCompare(left.createdAt))[0];
      if (durableApproval && durableApproval.decision !== decision) {
        setProblem({
          code: "AGENT_APPROVAL_RECOVERY_DECISION_MISMATCH",
          message: `已有 ${durableApproval.decision} 审批事实尚未完成状态转换，拒绝创建相反决策。`,
          nextAction:
            durableApproval.decision === "approve"
              ? "点击“批准并编译”恢复原审批命令。"
              : "点击“记录修改意见”恢复原决策。",
        });
        return;
      }
      const oppositeDecision = decision === "approve" ? "request_changes" : "approve";
      const oppositePending = readPending(
        oppositeDecision,
        server.serverId,
        snapshot.session.sessionId
      );
      if (
        !durableApproval &&
        oppositePending &&
        (oppositePending.kind === "approve" || oppositePending.kind === "request_changes") &&
        oppositePending.body.expectedPlanHash === currentPlan.planHash &&
        oppositePending.body.expectedStateVersion === snapshot.session.stateVersion
      ) {
        setProblem({
          code: "AGENT_APPROVAL_PENDING_DECISION_MISMATCH",
          message: `已有结果不确定的 ${oppositeDecision} 命令，拒绝发送相反决策。`,
          nextAction:
            oppositeDecision === "approve"
              ? "点击“批准并编译”重放原命令。"
              : "点击“记录修改意见”重放原命令。",
        });
        return;
      }
      const stored = readPending(decision, server.serverId, snapshot.session.sessionId);
      const storedDecision =
        stored && (stored.kind === "approve" || stored.kind === "request_changes")
          ? stored
          : null;
      const reusableStored =
        storedDecision &&
        storedDecision.serverId === serverId &&
        storedDecision.sessionId === sessionId &&
        storedDecision.body.serverId === serverId &&
        storedDecision.body.sessionId === sessionId &&
        storedDecision.body.decision === decision &&
        storedDecision.body.expectedPlanHash === currentPlan.planHash &&
        storedDecision.body.expectedStateVersion === snapshot.session.stateVersion
          ? storedDecision
          : null;
      if (storedDecision && !reusableStored) clearPending(storedDecision);
      const command: DecideAgentPlanInput = durableApproval
        ? {
            serverId: server.serverId,
            sessionId: snapshot.session.sessionId,
            requestId: durableApproval.requestId,
            idempotencyKey: durableApproval.idempotencyKey,
            expectedStateVersion: durableApproval.expectedStateVersion,
            decision: durableApproval.decision,
            expectedPlanHash: durableApproval.planHash,
            ...(durableApproval.reason ? { reason: durableApproval.reason } : {}),
          }
        : reusableStored?.body || {
            ...newCommandIntent(
              server.serverId,
              snapshot.session.sessionId,
              snapshot.session.stateVersion,
              decision
            ),
            decision,
            expectedPlanHash: currentPlan.planHash,
            ...(reason.trim() ? { reason: reason.trim() } : {}),
          };
      const pending =
        reusableStored ||
        pendingCommand(decision, server.serverId, snapshot.session.sessionId, command);
      storePending(pending);
      setBusyAction(decision);
      setProblem(null);
      setStatusMessage(
        durableApproval || reusableStored
          ? "正在重放原始审批命令并完成中断后的状态转换"
          : decision === "approve"
            ? "正在记录审批并编译不可变 revision"
            : "正在记录修改意见"
      );
      try {
        await decideAgentPlan(command);
        clearPending(pending);
        if (!isCurrentIdentity(serverId, sessionId)) return;
        const nextSnapshot = await fetchAgentSessionSnapshot({
          serverId,
          sessionId,
          refresh: true,
        });
        if (applySnapshot(serverId, nextSnapshot)) {
          setStatusMessage(
            decision === "approve"
              ? "WorkflowRevision 已编译；未提交 Run"
              : "修改意见已记录；当前 adapter 不支持自动重规划"
          );
        }
      } catch (error) {
        const authoritative = await refreshSelectedAfterConflict();
        if (!isCurrentIdentity(serverId, sessionId)) return;
        if (
          !isUncertainCommandFailure(error) &&
          authoritative &&
          !approvalStillNeedsReplay(authoritative, command)
        ) {
          clearPending(pending);
        }
        setProblem(agentProblem(error, decision === "approve" ? "审批未完成" : "修改意见未记录"));
        setStatusMessage(
          isUncertainCommandFailure(error)
            ? "结果不确定；已保存原审批命令"
            : "命令被明确拒绝，已刷新权威状态"
        );
      } finally {
        if (isCurrentIdentity(serverId, sessionId)) setBusyAction("");
      }
    },
    [
      applySnapshot,
      currentPlan,
      isCurrentIdentity,
      refreshSelectedAfterConflict,
      server,
      snapshot,
    ]
  );

  const cancel = useCallback(async () => {
    if (!server || !snapshot || snapshot.session.status === "cancelled") return;
    const serverId = server.serverId;
    const sessionId = snapshot.session.sessionId;
    if (!isCurrentIdentity(serverId, sessionId)) return;
    let pending: ReturnType<typeof pendingCommand> | null = null;
    setBusyAction("cancel");
    setProblem(null);
    setStatusMessage("正在取消会话并保留审计历史");
    try {
      const stored = readPending("cancel", serverId, sessionId);
      const reusable =
        stored?.kind === "cancel" &&
        stored.serverId === serverId &&
        stored.sessionId === sessionId &&
        stored.body.serverId === serverId &&
        stored.body.sessionId === sessionId &&
        stored.body.expectedStateVersion === snapshot.session.stateVersion
          ? stored
          : null;
      if (stored && !reusable) clearPending(stored);
      const command = reusable?.body || {
        ...newCommandIntent(serverId, sessionId, snapshot.session.stateVersion, "cancel"),
        reason: "Cancelled from Agent Workbench.",
      };
      pending = reusable || pendingCommand("cancel", serverId, sessionId, command);
      storePending(pending);
      await cancelAgentSession(command);
      clearPending(pending);
      if (!isCurrentIdentity(serverId, sessionId)) return;
      const nextSnapshot = await fetchAgentSessionSnapshot({
        serverId,
        sessionId,
        refresh: true,
      });
      if (applySnapshot(serverId, nextSnapshot)) {
        setStatusMessage("会话已取消，历史保持只读");
      }
    } catch (error) {
      if (pending && !isUncertainCommandFailure(error)) clearPending(pending);
      await refreshSelectedAfterConflict();
      if (!isCurrentIdentity(serverId, sessionId)) return;
      setProblem(agentProblem(error, "取消会话未完成"));
      setStatusMessage("取消命令未完成");
    } finally {
      if (isCurrentIdentity(serverId, sessionId)) setBusyAction("");
    }
  }, [applySnapshot, isCurrentIdentity, refreshSelectedAfterConflict, server, snapshot]);

  const selectSession = useCallback(
    (sessionId: string) => {
      if (!server?.serverId) return;
      if (identityRef.current.sessionId === sessionId) return;
      setProblem(null);
      setBusyAction("bootstrap");
      setStatusMessage(`正在读取会话 ${sessionId}`);
      if (snapshot?.session.sessionId !== sessionId) setSnapshotValue(null);
      replaceIdentity(server.serverId, sessionId);
    },
    [replaceIdentity, server?.serverId, setSnapshotValue, snapshot?.session.sessionId]
  );

  const startNew = useCallback(
    (fromCurrent = false) => {
      const current = snapshot?.session;
      const context = current ? agentFastqContext(current) : null;
      setComposerPrefill((previous) => ({
        version: previous.version + 1,
        ...(fromCurrent && current
          ? {
              budget: current.budget,
              projectId: current.projectId,
              summary: current.goal.summary,
              successCriterion: current.goal.successCriteria[0] || undefined,
            }
          : {}),
      }));
      setProblem(null);
      setSnapshotValue(null);
      if (server?.serverId) replaceIdentity(server.serverId);
      setStatusMessage(
        fromCurrent && context
          ? "已复制目标与预算；请选择 FASTQ 后创建新 lineage"
          : "可创建新的 Agent 会话"
      );
    },
    [replaceIdentity, server?.serverId, setSnapshotValue, snapshot?.session]
  );

  return {
    busyAction,
    composerPrefill,
    currentPlan,
    loading: busyAction === "bootstrap",
    parentPlan,
    problem,
    requestedSessionId: sessionParam,
    refreshing: busyAction === "refresh",
    selectedSession,
    server,
    sessions,
    snapshot,
    statusMessage,
    approve: (reason: string) => decide("approve", reason),
    cancel,
    refreshWorkspace,
    requestChanges: (reason: string) => decide("request_changes", reason),
    resumePlanning,
    selectSession,
    startNew: () => startNew(false),
    startNewFromCurrent: () => startNew(true),
    submitGoal,
  };
}
