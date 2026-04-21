"use client";

import { useEffect, useState } from "react";

import { LocalApiError, requestLocalApiJson } from "@/app/lib/local-api-client";

import {
  serverReadiness as fallbackServerReadiness,
  type ReadinessCheck,
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

async function safeRequest<T>(path: string): Promise<T> {
  return requestLocalApiJson<T>("GET", path, { cache: "no-store" });
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
