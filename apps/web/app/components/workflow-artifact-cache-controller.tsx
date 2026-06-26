"use client";

import { useCallback, useEffect, useState } from "react";

import {
  fetchArtifactCacheEntries,
  fetchArtifactCachePins,
  releaseArtifactCachePolicyPin,
  retainArtifactCacheEntry,
} from "./workflow-artifact-cache-api";
import { WorkflowArtifactCachePanel } from "./workflow-artifact-cache-panel";
import type { WorkflowArtifactCacheEntry, WorkflowArtifactCachePin } from "./workflow-artifact-cache-model";
import { workflowErrorMessage } from "./workflows-page-model";

export function WorkflowArtifactCacheController({
  onPolicyChanged,
  refreshVersion,
}: {
  onPolicyChanged: () => Promise<void>;
  refreshVersion: number;
}) {
  const [entries, setEntries] = useState<WorkflowArtifactCacheEntry[]>([]);
  const [pins, setPins] = useState<WorkflowArtifactCachePin[]>([]);
  const [loading, setLoading] = useState(true);
  const [retainingEntryId, setRetainingEntryId] = useState("");
  const [releasingPinId, setReleasingPinId] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async (forceRefresh = false) => {
    setLoading(true);
    setError("");
    try {
      const [nextEntries, nextPins] = await Promise.all([
        fetchArtifactCacheEntries({ forceRefresh, limit: 25 }),
        fetchArtifactCachePins({ forceRefresh, limit: 25 }),
      ]);
      setEntries(nextEntries.items || []);
      setPins(nextPins.items || []);
    } catch (err) {
      setError(artifactCacheErrorMessage(err, "读取 artifact cache 失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(refreshVersion > 0);
  }, [load, refreshVersion]);

  async function retain(cacheEntryId: string, reason: string) {
    if (retainingEntryId) return;
    setRetainingEntryId(cacheEntryId);
    setNotice("");
    setError("");
    try {
      await retainArtifactCacheEntry(cacheEntryId, {
        actor: "web-ui",
        reason,
      });
      setNotice(`已创建 policy pin: ${cacheEntryId}`);
      await Promise.all([load(true), onPolicyChanged()]);
    } catch (err) {
      setError(artifactCacheErrorMessage(err, "保留 artifact cache 失败"));
    } finally {
      setRetainingEntryId("");
    }
  }

  async function release(cachePinId: string, confirmation: string, reason: string) {
    if (releasingPinId) return;
    setReleasingPinId(cachePinId);
    setNotice("");
    setError("");
    try {
      await releaseArtifactCachePolicyPin(cachePinId, {
        actor: "web-ui",
        confirmation,
        reason,
      });
      setNotice(`已释放 policy pin: ${cachePinId}`);
      await Promise.all([load(true), onPolicyChanged()]);
    } catch (err) {
      setError(artifactCacheErrorMessage(err, "释放 artifact cache policy pin 失败"));
    } finally {
      setReleasingPinId("");
    }
  }

  return (
    <WorkflowArtifactCachePanel
      entries={entries}
      error={error}
      loading={loading}
      notice={notice}
      onRefresh={() => void load(true)}
      onReleasePin={(cachePinId, confirmation, reason) => void release(cachePinId, confirmation, reason)}
      onRetainEntry={(cacheEntryId, reason) => void retain(cacheEntryId, reason)}
      pins={pins}
      releasingPinId={releasingPinId}
      retainingEntryId={retainingEntryId}
    />
  );
}

function artifactCacheErrorMessage(err: unknown, fallback: string) {
  const message = workflowErrorMessage(err, fallback);
  const status = typeof err === "object" && err && "status" in err ? Number((err as { status?: unknown }).status) : 0;
  if (status === 404 || /^not found$/i.test(message)) {
    return "当前远程 runner 未暴露 artifact cache API，请部署包含 artifact cache endpoints 的 runner 后重试。";
  }
  return message;
}
