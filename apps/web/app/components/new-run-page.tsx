"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { apiBase, LocalApiError } from "@/app/lib/local-api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { SummaryStrip, WorkspacePageHeader, WorkspaceSection } from "./workspace-primitives";

type ServerRecord = {
  serverId: string;
  label: string;
  ready: boolean;
  reasonCode: string;
};

export function NewRunPage({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [servers, setServers] = useState<ServerRecord[]>([]);
  const [serverId, setServerId] = useState("");
  const [pipelineId, setPipelineId] = useState("taxonomy-v1");
  const [sampleId, setSampleId] = useState("sample_alpha");
  const [uploadId, setUploadId] = useState("upl_alpha");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function loadServers() {
      try {
        const response = await fetch(`${apiBase()}/api/v1/servers`, { cache: "no-store" });
        const payload = (await response.json()) as { data?: { items?: ServerRecord[] } };
        if (!response.ok) {
          throw new Error("Failed to load servers");
        }
        if (!cancelled) {
          const items = payload.data?.items ?? [];
          setServers(items);
          setServerId(items[0]?.serverId ?? "");
        }
      } catch {
        if (!cancelled) {
          setServers([]);
          setServerId("");
        }
      }
    }
    void loadServers();
    return () => {
      cancelled = true;
    };
  }, []);

  const runSpec = useMemo(
    () => ({
      projectId,
      serverId,
      pipelineId,
      runSpecVersion: "2026-04-21",
      inputs: [
        {
          sampleId,
          uploadId,
          kind: "fastq_pair",
        },
      ],
    }),
    [pipelineId, projectId, sampleId, serverId, uploadId]
  );

  async function handleSubmit() {
    setSubmitting(true);
    setError("");
    try {
      const response = await fetch(`${apiBase()}/api/v1/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pipelineId,
          runSpec,
          requestId: `req_ui_${Date.now()}`,
        }),
      });
      const payload = (await response.json()) as { data?: { runId?: string }; detail?: string };
      if (!response.ok) {
        throw new LocalApiError("backend_http_error", payload.detail || `HTTP ${response.status}`, response.status);
      }
      const nextRunId = payload.data?.runId;
      if (!nextRunId) {
        throw new Error("Run submission did not return a runId.");
      }
      router.push(`/runs/${nextRunId}`);
      router.refresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Failed to submit run.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <WorkspacePageHeader
        eyebrow="Run"
        breadcrumbs={[
          { label: "Projects", href: "/projects" },
          { label: projectId, href: `/projects/${projectId}` },
          { label: "New Run" },
        ]}
        title={`New Run · ${projectId}`}
        description="保持结构化提交流程：先选 server 与 pipeline，再检查 runSpec，最后异步提交并跳转到 Run Detail。"
      />

      <SummaryStrip
        items={[
          { label: "Project", value: projectId },
          { label: "Pipeline", value: pipelineId },
          { label: "Server", value: serverId || "Not selected" },
          { label: "Mode", value: "Structured execution" },
        ]}
      />

      {error ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3 text-sm text-rose-800">{error}</div>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
        <WorkspaceSection title="Submission form" description="字段保持少而必要，避免把 New Run 做成冗长后台表单。">
          <div className="space-y-4">
            <label className="grid gap-2 text-sm text-slate-700">
              <span className="text-[12px] font-medium text-slate-500">Server</span>
              <select
                value={serverId}
                onChange={(event) => setServerId(event.target.value)}
                className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none"
              >
                {servers.length ? (
                  servers.map((server) => (
                    <option key={server.serverId} value={server.serverId}>
                      {server.label} {server.ready ? "· Ready" : server.reasonCode ? `· ${server.reasonCode}` : ""}
                    </option>
                  ))
                ) : (
                  <option value="">No live server detected</option>
                )}
              </select>
            </label>

            <label className="grid gap-2 text-sm text-slate-700">
              <span className="text-[12px] font-medium text-slate-500">Pipeline</span>
              <select
                value={pipelineId}
                onChange={(event) => setPipelineId(event.target.value)}
                className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none"
              >
                <option value="taxonomy-v1">taxonomy-v1</option>
                <option value="assembly-v3">assembly-v3</option>
              </select>
            </label>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="grid gap-2 text-sm text-slate-700">
                <span className="text-[12px] font-medium text-slate-500">Sample ID</span>
                <Input value={sampleId} onChange={(event) => setSampleId(event.target.value)} />
              </label>
              <label className="grid gap-2 text-sm text-slate-700">
                <span className="text-[12px] font-medium text-slate-500">Upload ID</span>
                <Input value={uploadId} onChange={(event) => setUploadId(event.target.value)} />
              </label>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2">
              <Button type="button" variant="outline" onClick={() => router.push(`/projects/${projectId}`)}>
                Cancel
              </Button>
              <Button type="button" disabled={submitting || !serverId || !sampleId || !uploadId} onClick={() => void handleSubmit()}>
                {submitting ? "Submitting..." : "Submit run"}
              </Button>
            </div>
          </div>
        </WorkspaceSection>

        <WorkspaceSection title="runSpec preview" description="先看清楚再提交：右侧保留结构化 JSON 预览，强调 v1 不暴露任意 shell 运行。">
          <pre className="overflow-auto rounded-2xl bg-slate-950 px-4 py-4 text-[12px] leading-6 text-slate-100">
            {JSON.stringify(runSpec, null, 2)}
          </pre>
        </WorkspaceSection>
      </div>
    </div>
  );
}
