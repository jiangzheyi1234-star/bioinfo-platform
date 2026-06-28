"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

import { useWorkflowsPageState } from "./use-workflows-page-state";
import { WorkflowProductionGovernancePanel } from "./workflow-production-governance-panel";
import { WorkflowPageHeader } from "./workflow-page-header";
import { WorkflowScenarioPackSection } from "./workflow-scenario-pack-section";
import { WorkflowWorkspaceTabs } from "./workflow-workspace-tabs";
import { WorkflowCatalogTable } from "./workflows-page-ui";
import { fetchWorkflowScenarioPacks } from "./workflows-page-api";
import { workflowErrorMessage, type WorkflowScenarioPack } from "./workflows-page-model";

export function WorkflowsPage() {
  const state = useWorkflowsPageState();
  const [scenarioPacks, setScenarioPacks] = useState<WorkflowScenarioPack[]>([]);
  const [scenarioPacksLoading, setScenarioPacksLoading] = useState(false);
  const [scenarioPacksError, setScenarioPacksError] = useState("");

  const loadScenarioPacks = useCallback(async () => {
    setScenarioPacksLoading(true);
    setScenarioPacksError("");
    try {
      setScenarioPacks(await fetchWorkflowScenarioPacks());
    } catch (err) {
      setScenarioPacksError(workflowErrorMessage(err, "场景包目录加载失败"));
    } finally {
      setScenarioPacksLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadScenarioPacks();
  }, [loadScenarioPacks]);

  return (
    <div className="relative h-full w-full overflow-y-auto bg-white px-8 py-10 text-slate-800">
      <WorkflowWorkspaceTabs />
      <div className="mx-auto max-w-5xl space-y-6">
        <WorkflowPageHeader
          title="流程目录"
          actions={
            <Button
              variant="outline"
              className="h-9 bg-white px-3 text-slate-600"
              disabled={state.loading}
              onClick={() => {
                void state.loadWorkspace({ forceRefresh: true });
                void loadScenarioPacks();
              }}
            >
              {state.loading ? (
                <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw strokeWidth={1.5} className="mr-2 h-4 w-4" />
              )}
              刷新目录
            </Button>
          }
        />

        {state.error ? (
          <Alert variant="destructive">
            <AlertDescription>{state.error}</AlertDescription>
          </Alert>
        ) : null}

        <WorkflowProductionGovernancePanel />

        <WorkflowScenarioPackSection
          error={scenarioPacksError}
          loading={scenarioPacksLoading}
          packs={scenarioPacks}
        />

        {state.loading && state.catalog.length === 0 ? (
          <div className="flex h-48 items-center justify-center text-sm text-slate-400">
            <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
            正在读取 workflow catalog
          </div>
        ) : state.catalog.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-4 py-12 text-center text-sm text-slate-500">
            暂无可展示的 workflow。
          </div>
        ) : (
          <WorkflowCatalogTable items={state.catalog} />
        )}
      </div>
    </div>
  );
}
