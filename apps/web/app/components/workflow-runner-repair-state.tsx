"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, ChevronDown, RefreshCw } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { MANUAL_RUNNER_STOP_REASON, runnerEnsureActionLabel, type RunnerRepairStatus } from "./ssh-shell-model";
import { RunnerRepairPanel } from "./ssh-runner-repair-panel";
import { ensureWorkflowServerRunner, startWorkflowServerRunner } from "./workflow-server-readiness-api";
import { fetchWorkflowServer, getCachedWorkflowServer } from "./workflows-page-api";
import { workflowErrorMessage, type WorkflowServer } from "./workflows-page-model";

export type WorkflowRunnerRepairController = {
  server: WorkflowServer | null;
  status: RunnerRepairStatus | null;
  loading: boolean;
  loadError: string;
  runnerEnsureBusy: boolean;
  runnerRepairError: string;
  ensureRunner: () => Promise<WorkflowServer | null>;
  refreshWorkflowServer: () => Promise<WorkflowServer | null>;
};

export function workflowServerRepairStatus(server: WorkflowServer | null): RunnerRepairStatus | null {
  if (!server?.serverId) {
    return null;
  }
  const runner = server.runner;
  const reasonCode = runner?.reasonCode || server.reasonCode || "";
  const connected = server.connected === true;
  return {
    connected,
    displayTarget: server.label || server.serverId,
    message: server.message || "",
    serverId: server.serverId,
    runner: connected && runner
      ? {
          state:
            runner.state ||
            (runner.ready === true
              ? "ready"
              : reasonCode === MANUAL_RUNNER_STOP_REASON
                ? "stopped"
                : reasonCode
                  ? "repair_needed"
                  : "preparing"),
          ready: runner.ready === true,
          message: runner.message || server.message || "",
          reasonCode,
          deploymentAction: runner.deploymentAction,
          servicePort: runner.servicePort,
          tunnelPort: runner.tunnelPort,
        }
      : undefined,
  };
}

export function workflowServerRunnerManuallyStopped(server: WorkflowServer | null) {
  const runner = server?.runner;
  return Boolean(
    server?.connected &&
      runner &&
      runner.ready !== true &&
      (runner.state === "stopped" || runner.reasonCode === MANUAL_RUNNER_STOP_REASON)
  );
}

export async function runWorkflowServerRunnerRepairAction(server: WorkflowServer | null): Promise<void> {
  const serverId = server?.serverId || "";
  if (!serverId) {
    throw new Error("serverId is required");
  }
  const action = workflowServerRunnerManuallyStopped(server) ? startWorkflowServerRunner : ensureWorkflowServerRunner;
  await action(serverId);
}

export function useWorkflowRunnerRepairState(): WorkflowRunnerRepairController {
  const [server, setServer] = useState<WorkflowServer | null>(() => getCachedWorkflowServer() || null);
  const [loading, setLoading] = useState(() => !getCachedWorkflowServer());
  const [loadError, setLoadError] = useState("");
  const [runnerEnsureBusy, setRunnerEnsureBusy] = useState(false);
  const [runnerRepairError, setRunnerRepairError] = useState("");

  const refreshWorkflowServer = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const nextServer = await fetchWorkflowServer({ forceRefresh: true });
      setServer(nextServer);
      setRunnerRepairError("");
      return nextServer;
    } catch (err) {
      setLoadError(workflowErrorMessage(err, "读取工作流运行服务失败"));
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const ensureRunner = useCallback(async () => {
    if (!server?.serverId || runnerEnsureBusy) {
      return null;
    }
    setRunnerEnsureBusy(true);
    setRunnerRepairError("");
    try {
      await runWorkflowServerRunnerRepairAction(server);
      return await refreshWorkflowServer();
    } catch (err) {
      setRunnerRepairError(workflowErrorMessage(err, "runner readiness 准备失败"));
      return null;
    } finally {
      setRunnerEnsureBusy(false);
    }
  }, [refreshWorkflowServer, runnerEnsureBusy, server]);

  useEffect(() => {
    void refreshWorkflowServer();
  }, [refreshWorkflowServer]);

  return {
    server,
    status: workflowServerRepairStatus(server),
    loading,
    loadError,
    runnerEnsureBusy,
    runnerRepairError,
    ensureRunner,
    refreshWorkflowServer,
  };
}

export function WorkflowRunnerRepairNotice({
  className = "",
  controller,
  mode = "full",
}: {
  className?: string;
  controller: WorkflowRunnerRepairController;
  mode?: "compact" | "full";
}) {
  const [expanded, setExpanded] = useState(mode === "full");
  const status = controller.status;
  const hasKnownRunnerTarget = Boolean(status?.serverId || controller.server?.serverId);
  const visibleLoadError = hasKnownRunnerTarget ? controller.loadError : "";
  const showPanel = Boolean(status?.connected && (!status.runner || !status.runner.ready));
  if (!showPanel && !visibleLoadError && !controller.runnerRepairError) {
    return null;
  }
  const compact = mode === "compact";
  const canPrepareRunner = Boolean(status?.connected && status.serverId && !status.runner?.ready);
  const title = status?.runner?.reasonCode === MANUAL_RUNNER_STOP_REASON ? "远程服务已停止" : "远程服务未就绪";
  return (
    <section
      className={cn("rounded-lg border border-amber-200 bg-amber-50 p-3", className)}
      data-testid="workflow-runner-repair-notice"
      data-runner-repair-mode={mode}
    >
      {visibleLoadError || controller.runnerRepairError ? (
        <Alert variant="destructive" className="mb-3 bg-white text-xs">
          <AlertCircle strokeWidth={1.5} className="h-3.5 w-3.5" />
          <AlertDescription>{controller.runnerRepairError || visibleLoadError}</AlertDescription>
        </Alert>
      ) : null}
      {compact && showPanel && status ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="text-xs font-semibold text-amber-950">{title}</div>
            <div className="mt-0.5 truncate text-[11px] text-amber-800">
              {status.runner?.message || status.message || status.displayTarget || "等待 runner readiness"}
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            {canPrepareRunner ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={controller.runnerEnsureBusy}
                onClick={() => void controller.ensureRunner()}
                className="h-8 border-amber-200 bg-white px-2.5 text-xs text-amber-900 hover:bg-amber-50"
              >
                <RefreshCw className={cn("mr-1.5 h-3.5 w-3.5", controller.runnerEnsureBusy ? "animate-spin" : "")} />
                {runnerEnsureActionLabel(status, controller.runnerEnsureBusy)}
              </Button>
            ) : null}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setExpanded((value) => !value)}
              className="h-8 border-amber-200 bg-white px-2.5 text-xs text-amber-900 hover:bg-amber-50"
            >
              <ChevronDown className={cn("mr-1.5 h-3.5 w-3.5 transition-transform", expanded ? "rotate-180" : "")} />
              诊断
            </Button>
          </div>
        </div>
      ) : null}
      {showPanel && status && (!compact || expanded) ? (
        <RunnerRepairPanel
          status={status}
          ensureRunnerBusy={controller.runnerEnsureBusy}
          onEnsureRunner={() => void controller.ensureRunner()}
          onRefreshStatus={controller.refreshWorkflowServer}
          className={cn("bg-white shadow-none", compact ? "mt-3" : "")}
        />
      ) : null}
    </section>
  );
}
