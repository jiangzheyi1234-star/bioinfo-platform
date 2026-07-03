"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { cancelToolPrepareJob, fetchToolPrepareJob, fetchToolPrepareJobQueue, invalidateWorkflowToolCaches } from "./tools-page-api";
import {
  TOOL_PREPARE_ACTIVE_STATUSES,
  TOOL_PREPARE_TERMINAL_STATUSES,
  type ToolPrepareJob,
} from "./tools-page-model";

const POLL_INTERVAL_MS = 1500;
const MAX_RETAINED_TASKS = 8;
const ACTIVE_TOOL_PREPARE_STATUS_SET = new Set<string>(TOOL_PREPARE_ACTIVE_STATUSES);
const TERMINAL_TOOL_PREPARE_STATUS_SET = new Set<string>(TOOL_PREPARE_TERMINAL_STATUSES);

type ToolPrepareTaskContextValue = {
  tasks: ToolPrepareJob[];
  activeTasks: ToolPrepareJob[];
  trackToolPrepareJob: (job: ToolPrepareJob) => void;
  refreshToolPrepareJob: (jobId: string) => Promise<void>;
  cancelToolPrepareTask: (jobId: string) => Promise<void>;
  dismissToolPrepareTask: (jobId: string) => void;
};

const ToolPrepareTaskContext = createContext<ToolPrepareTaskContextValue | null>(null);

export function ToolPrepareTaskProvider({ children }: { children: ReactNode }) {
  const [tasks, setTasks] = useState<ToolPrepareJob[]>([]);

  const mergeTasks = useCallback((jobs: ToolPrepareJob[]) => {
    if (jobs.length === 0) return;
    const incomingIds = new Set(jobs.map((job) => job.jobId));
    setTasks((current) => trimTasks([...jobs, ...current.filter((item) => !incomingIds.has(item.jobId))]));
    if (jobs.some(isTerminalJob)) {
      invalidateWorkflowToolCaches();
    }
  }, []);

  const mergeTask = useCallback((job: ToolPrepareJob) => mergeTasks([job]), [mergeTasks]);

  const refreshToolPrepareJob = useCallback(
    async (jobId: string) => {
      const job = await fetchToolPrepareJob(jobId);
      mergeTask(job);
    },
    [mergeTask]
  );

  const cancelToolPrepareTask = useCallback(
    async (jobId: string) => {
      const job = await cancelToolPrepareJob(jobId);
      mergeTask(job);
    },
    [mergeTask]
  );

  const dismissToolPrepareTask = useCallback((jobId: string) => {
    setTasks((current) => current.filter((item) => item.jobId !== jobId || !isTerminalJob(item)));
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.allSettled(
      TOOL_PREPARE_ACTIVE_STATUSES.map((status) =>
        fetchToolPrepareJobQueue({ limit: 50, signal: controller.signal, status })
      )
    ).then((pages) => {
      if (controller.signal.aborted) return;
      const restoredTasks = pages
        .flatMap((page) => (page.status === "fulfilled" ? page.value.items : []))
        .filter(isActiveJob);
      mergeTasks(restoredTasks);
    });
    return () => controller.abort();
  }, [mergeTasks]);

  useEffect(() => {
    const activeIds = tasks.filter(isActiveJob).map((task) => task.jobId);
    if (activeIds.length === 0) return;
    const timer = window.setInterval(() => {
      activeIds.forEach((jobId) => {
        void refreshToolPrepareJob(jobId).catch(() => undefined);
      });
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refreshToolPrepareJob, tasks]);

  const value = useMemo<ToolPrepareTaskContextValue>(
    () => ({
      tasks,
      activeTasks: tasks.filter(isActiveJob),
      trackToolPrepareJob: mergeTask,
      refreshToolPrepareJob,
      cancelToolPrepareTask,
      dismissToolPrepareTask,
    }),
    [cancelToolPrepareTask, dismissToolPrepareTask, mergeTask, refreshToolPrepareJob, tasks]
  );

  return <ToolPrepareTaskContext.Provider value={value}>{children}</ToolPrepareTaskContext.Provider>;
}

export function useToolPrepareTasks() {
  const context = useContext(ToolPrepareTaskContext);
  if (!context) {
    throw new Error("useToolPrepareTasks must be used within ToolPrepareTaskProvider");
  }
  return context;
}

export function isActiveJob(job: ToolPrepareJob) {
  return ACTIVE_TOOL_PREPARE_STATUS_SET.has(job.status);
}

export function isTerminalJob(job: ToolPrepareJob) {
  return TERMINAL_TOOL_PREPARE_STATUS_SET.has(job.status);
}

function trimTasks(tasks: ToolPrepareJob[]) {
  const active = tasks.filter(isActiveJob);
  const terminal = tasks.filter((task) => !isActiveJob(task)).slice(0, Math.max(0, MAX_RETAINED_TASKS - active.length));
  return [...active, ...terminal];
}
