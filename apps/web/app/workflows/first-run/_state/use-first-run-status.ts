"use client";

import { useCallback, useEffect, useState } from "react";

import { workflowErrorMessage } from "@/app/components/workflows-page-model";

import { fetchFirstRunStatus } from "../_api/workflow-first-run-api";
import type { FirstRunStatus } from "../_domain/first-run-types";

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

  const refreshStatus = useCallback(
    async (options: { forceRefresh?: boolean } = {}) => {
      setLoading(true);
      setError("");
      try {
        const nextStatus = await fetchFirstRunStatus({
          refresh: options.forceRefresh === true,
          runId: normalizedRunId || undefined,
          serverId: normalizedServerId || undefined,
        });
        setStatus(nextStatus);
        return nextStatus;
      } catch (err) {
        setStatus(null);
        setError(workflowErrorMessage(err, "读取首跑状态失败"));
        return null;
      } finally {
        setLoading(false);
      }
    },
    [normalizedRunId, normalizedServerId]
  );

  useEffect(() => {
    void refreshStatus({ forceRefresh: true });
  }, [refreshStatus]);

  return {
    error,
    loading,
    refreshStatus,
    status,
  };
}
