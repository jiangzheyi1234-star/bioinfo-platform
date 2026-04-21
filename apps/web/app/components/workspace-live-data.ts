"use client";

import { useEffect, useState } from "react";

import { LocalApiError, requestLocalApiJson } from "@/app/lib/local-api-client";

import {
  recentResults as fallbackRecentResults,
  recentRuns as fallbackRecentRuns,
  runArtifacts as fallbackRunArtifacts,
  runEvents as fallbackRunEvents,
  runLogLines as fallbackRunLogLines,
  runSpecExample,
  serverReadiness as fallbackServerReadiness,
  type ReadinessCheck,
  type RecentResult,
  type RecentRun,
  type RunArtifact,
  type RunEvent,
} from "./workspace-mocks";

type ServerRecord = {
  serverId: string;
  label: string;
  host?: string;
  port?: number;
  user?: string;
  connected: boolean;
  ready: boolean;
  reasonCode: string;
  message?: string;
  health: {
    startup: { ok: boolean; message: string };
    live: { ok: boolean; message: string };
    ready: { ok: boolean; message: string };
    reasonCode: string;
    checkedAt?: string;
  };
};

type ProjectRecord = {
  project_id: string;
  name: string;
  description: string;
  status: string;
  created_at: number;
};

type ResultRecord = {
  resultId: string;
  runId: string;
  title: string;
  pipelineId: string;
  artifactCount: number;
  producedAt: string;
};

type ResultDetailRecord = ResultRecord & {
  artifacts: RunArtifact[];
};

type ResultPreviewRecord = {
  resultId: string;
  artifactId: string;
  artifact: RunArtifact;
  preview: {
    kind: "table" | "text" | "html" | "download";
    columns?: string[];
    rows?: string[][];
    content?: string;
  };
};

function isOfflineFallbackError(error: unknown): boolean {
  return error instanceof LocalApiError && (error.code === "backend_unreachable" || error.code === "backend_timeout");
}

function toReadinessChecks(server: ServerRecord | null): ReadinessCheck[] {
  if (!server) {
    return fallbackServerReadiness;
  }
  return [
    {
      key: "startup",
      label: "Startup",
      status: server.health.startup.ok ? "ok" : "failed",
      value: server.health.startup.message,
    },
    {
      key: "live",
      label: "Live",
      status: server.health.live.ok ? "ok" : "failed",
      value: server.health.live.message,
    },
    {
      key: "ready",
      label: "Ready",
      status: server.health.ready.ok ? "ok" : server.reasonCode ? "warning" : "failed",
      value: server.health.ready.message,
      reasonCode: server.reasonCode,
    },
  ];
}

function toRecentResults(items: ResultRecord[]): RecentResult[] {
  return items.map((item) => ({
    id: item.resultId,
    title: item.title,
    sourceRunId: item.runId,
    artifactCount: item.artifactCount,
    producedAt: item.producedAt,
  }));
}

async function safeRequest<T>(path: string): Promise<T> {
  return requestLocalApiJson<T>("GET", path, { cache: "no-store" });
}

export function useHomeData() {
  const [runs, setRuns] = useState<RecentRun[]>(fallbackRecentRuns);
  const [results, setResults] = useState<RecentResult[]>(fallbackRecentResults);
  const [readiness, setReadiness] = useState<ReadinessCheck[]>(fallbackServerReadiness);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [runsResponse, serversResponse, resultsResponse] = await Promise.all([
          safeRequest<{ data: { items: RecentRun[] } }>("/api/v1/runs"),
          safeRequest<{ data: { items: ServerRecord[] } }>("/api/v1/servers"),
          safeRequest<{ data: { items: ResultRecord[] } }>("/api/v1/results"),
        ]);
        if (cancelled) return;
        setRuns(runsResponse.data.items);
        setReadiness(toReadinessChecks(serversResponse.data.items[0] ?? null));
        setResults(toRecentResults(resultsResponse.data.items));
        setError("");
      } catch (error) {
        if (isOfflineFallbackError(error)) return;
        if (!cancelled) setError(error instanceof Error ? error.message : "Failed to load workspace data.");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return { runs, results, readiness, error };
}

export function useRunsData() {
  const [runs, setRuns] = useState<RecentRun[]>(fallbackRecentRuns);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await safeRequest<{ data: { items: RecentRun[] } }>("/api/v1/runs");
        if (!cancelled) {
          setRuns(response.data.items);
          setError("");
        }
      } catch (error) {
        if (isOfflineFallbackError(error)) return;
        if (!cancelled) setError(error instanceof Error ? error.message : "Failed to load runs.");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return { runs, error };
}

export function useRunDetailData(runId: string) {
  const [run, setRun] = useState<RecentRun>(fallbackRecentRuns.find((item) => item.runId === runId) ?? fallbackRecentRuns[0]);
  const [events, setEvents] = useState<RunEvent[]>(fallbackRunEvents);
  const [artifacts, setArtifacts] = useState<RunArtifact[]>(fallbackRunArtifacts);
  const [logLines, setLogLines] = useState<string[]>(fallbackRunLogLines);
  const [runSpec, setRunSpec] = useState(runSpecExample);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [runResponse, eventsResponse, resultsResponse, logsResponse] = await Promise.all([
          safeRequest<{ data: RecentRun }>(`/api/v1/runs/${runId}`),
          safeRequest<{ data: { items: RunEvent[] } }>(`/api/v1/runs/${runId}/events`),
          safeRequest<{ data: { artifacts: RunArtifact[] } }>(`/api/v1/runs/${runId}/results`),
          safeRequest<{ data: { lines: string[] } }>(`/api/v1/runs/${runId}/logs`),
        ]);
        if (cancelled) return;
        setRun(runResponse.data);
        setEvents(eventsResponse.data.items);
        setArtifacts(resultsResponse.data.artifacts);
        setLogLines(logsResponse.data.lines);
        setRunSpec((runResponse.data.runSpec as typeof runSpecExample | undefined) ?? runSpecExample);
        setError("");
      } catch (error) {
        if (isOfflineFallbackError(error)) return;
        if (!cancelled) setError(error instanceof Error ? error.message : "Failed to load run detail.");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  return { run, events, artifacts, logLines, runSpec, error };
}

export function useResultsData() {
  const [results, setResults] = useState<RecentResult[]>(fallbackRecentResults);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await safeRequest<{ data: { items: ResultRecord[] } }>("/api/v1/results");
        if (!cancelled) {
          setResults(toRecentResults(response.data.items));
          setError("");
        }
      } catch (error) {
        if (isOfflineFallbackError(error)) return;
        if (!cancelled) setError(error instanceof Error ? error.message : "Failed to load results.");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return { results, error };
}

export function useResultDetailData(resultId: string) {
  const fallbackResult = fallbackRecentResults.find((item) => item.id === resultId) ?? fallbackRecentResults[0];
  const [result, setResult] = useState<ResultDetailRecord>({
    resultId: fallbackResult.id,
    runId: fallbackResult.sourceRunId,
    title: fallbackResult.title,
    pipelineId: "taxonomy-v1",
    artifactCount: fallbackResult.artifactCount,
    producedAt: fallbackResult.producedAt,
    artifacts: fallbackRunArtifacts,
  });
  const [selectedArtifactId, setSelectedArtifactId] = useState<string>(fallbackRunArtifacts[0]?.artifactId ?? "");
  const [preview, setPreview] = useState<ResultPreviewRecord | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await safeRequest<{ data: ResultDetailRecord }>(`/api/v1/results/${resultId}`);
        if (!cancelled) {
          setResult(response.data);
          setSelectedArtifactId(response.data.artifacts[0]?.artifactId ?? "");
          setError("");
        }
      } catch (error) {
        if (isOfflineFallbackError(error)) return;
        if (!cancelled) setError(error instanceof Error ? error.message : "Failed to load result detail.");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [resultId]);

  useEffect(() => {
    let cancelled = false;
    async function loadPreview() {
      if (!selectedArtifactId) {
        setPreview(null);
        return;
      }
      try {
        const response = await safeRequest<{ data: ResultPreviewRecord }>(`/api/v1/results/${resultId}/preview?artifact_id=${encodeURIComponent(selectedArtifactId)}`);
        if (!cancelled) {
          setPreview(response.data);
          setError("");
        }
      } catch (error) {
        if (isOfflineFallbackError(error)) return;
        if (!cancelled) setError(error instanceof Error ? error.message : "Failed to load result preview.");
      }
    }
    void loadPreview();
    return () => {
      cancelled = true;
    };
  }, [resultId, selectedArtifactId]);

  const selectedArtifact = result.artifacts.find((artifact) => artifact.artifactId === selectedArtifactId) ?? result.artifacts[0] ?? null;
  return { result, selectedArtifact, selectedArtifactId, setSelectedArtifactId, preview, error };
}

export function useServerListData() {
  const [servers, setServers] = useState<ServerRecord[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await safeRequest<{ data: { items: ServerRecord[] } }>("/api/v1/servers");
        if (!cancelled) {
          setServers(response.data.items);
          setError("");
        }
      } catch (error) {
        if (isOfflineFallbackError(error)) return;
        if (!cancelled) setError(error instanceof Error ? error.message : "Failed to load servers.");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return { servers, error };
}

export function useServerDetailData(serverId: string) {
  const [server, setServer] = useState<ServerRecord | null>(null);
  const [readiness, setReadiness] = useState<ReadinessCheck[]>(fallbackServerReadiness);
  const [error, setError] = useState("");
  const [reloadNonce, setReloadNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await safeRequest<{ data: ServerRecord }>(`/api/v1/servers/${serverId}`);
        if (!cancelled) {
          setServer(response.data);
          setReadiness(toReadinessChecks(response.data));
          setError("");
        }
      } catch (error) {
        if (isOfflineFallbackError(error)) return;
        try {
          const fallback = await safeRequest<{ data: { items: ServerRecord[] } }>("/api/v1/servers");
          const firstServer = fallback.data.items[0] ?? null;
          if (!cancelled && firstServer) {
            setServer(firstServer);
            setReadiness(toReadinessChecks(firstServer));
            setError(serverId !== firstServer.serverId ? `Server ${serverId} not found; showing ${firstServer.label} instead.` : "");
            return;
          }
        } catch {
          // ignore nested fallback failure
        }
        if (!cancelled) setError(error instanceof Error ? error.message : "Failed to load server detail.");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [serverId, reloadNonce]);

  return { server, readiness, error, reload: () => setReloadNonce((value) => value + 1) };
}

export async function runServerAction(serverId: string, action: "refresh" | "bootstrap" | "accept-host-key" | "rotate-token") {
  const pathMap = {
    refresh: `/api/v1/servers/${serverId}/health/refresh`,
    bootstrap: `/api/v1/servers/${serverId}/bootstrap`,
    "accept-host-key": `/api/v1/servers/${serverId}/host-key/accept`,
    "rotate-token": `/api/v1/servers/${serverId}/token/rotate`,
  } as const;
  return requestLocalApiJson("POST", pathMap[action], {});
}

export function useProjectsData() {
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await requestLocalApiJson<{ items: ProjectRecord[] }>("GET", "/api/v1/projects", { cache: "no-store" });
        if (!cancelled) {
          setProjects(response.items);
          setError("");
        }
      } catch (error) {
        if (isOfflineFallbackError(error)) return;
        if (!cancelled) setError(error instanceof Error ? error.message : "Failed to load projects.");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return { projects, error };
}

export function useProjectDetailData(projectId: string) {
  const [project, setProject] = useState<ProjectRecord | null>(null);
  const [runs, setRuns] = useState<RecentRun[]>(fallbackRecentRuns.filter((run) => run.projectId === projectId || projectId === "proj_default"));
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [projectResponse, runsResponse] = await Promise.all([
          safeRequest<{ data: ProjectRecord }>(`/api/v1/projects/${projectId}`),
          safeRequest<{ data: { items: RecentRun[] } }>("/api/v1/runs"),
        ]);
        if (!cancelled) {
          setProject(projectResponse.data);
          setRuns(runsResponse.data.items.filter((run) => !projectId || run.projectId === projectId));
          setError("");
        }
      } catch (error) {
        if (isOfflineFallbackError(error)) return;
        if (!cancelled) setError(error instanceof Error ? error.message : "Failed to load project detail.");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return { project, runs, error };
}
