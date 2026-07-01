"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { workflowErrorMessage } from "@/app/components/workflows-page-model";

import { fetchFirstRunStatus } from "../_api/workflow-first-run-api";
import type { FirstRunStatus } from "../_domain/first-run-types";

const FIRST_RUN_STATUS_POLL_MS = 5000;

type FirstRunStatusRefreshOptions = {
  forceRefresh?: boolean;
  silent?: boolean;
};

export function firstRunStatusShouldPoll(status: FirstRunStatus | null): boolean {
  return (
    status?.status === "waiting" ||
    status?.stage === "run_in_progress" ||
    status?.nextAction?.code === "REFRESH_RUN"
  );
}

export function useFirstRunStatus({
  runId,
  serverId,
}: {
  runId?: string;
  serverId?: string;
}) {
  const normalizedServerId = String(serverId || "").trim();
  const normalizedRunId = String(runId || "").trim();
  const [status, setStatus] = useState<FirstRunStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const silentRefreshInFlightRef = useRef<Promise<FirstRunStatus | null> | null>(null);

  const refreshStatus = useCallback(
    async (options: FirstRunStatusRefreshOptions = {}) => {
      if (options.silent && silentRefreshInFlightRef.current) {
        return silentRefreshInFlightRef.current;
      }
      if (!options.silent) {
        setLoading(true);
      }
      setError("");
      const request = (async () => {
        const nextStatus = await fetchFirstRunStatus({
          refresh: options.forceRefresh === true,
          runId: normalizedRunId || undefined,
          serverId: normalizedServerId || undefined,
        });
        setStatus(nextStatus);
        return nextStatus;
      })();
      if (options.silent) {
        silentRefreshInFlightRef.current = request;
      }
      try {
        return await request;
      } catch (err) {
        if (!options.silent) {
          setStatus(null);
        }
        setError(workflowErrorMessage(err, "读取首跑状态失败"));
        return null;
      } finally {
        if (silentRefreshInFlightRef.current === request) {
          silentRefreshInFlightRef.current = null;
        }
        if (!options.silent) {
          setLoading(false);
        }
      }
    },
    [normalizedRunId, normalizedServerId]
  );

  useEffect(() => {
    void refreshStatus({ forceRefresh: true });
  }, [refreshStatus]);

  useEffect(() => {
    if (!firstRunStatusShouldPoll(status)) {
      return;
    }
    const timer = window.setInterval(() => {
      void refreshStatus({ forceRefresh: true, silent: true });
    }, FIRST_RUN_STATUS_POLL_MS);
    return () => window.clearInterval(timer);
  }, [refreshStatus, status]);

  return {
    error,
    loading,
    refreshStatus,
    status,
  };
}
