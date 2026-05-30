"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

import { useWorkflowsPageState } from "./use-workflows-page-state";
import { fetchWorkflowCatalog } from "./workflows-page-api";
import { GeneratedWorkflowBuilder } from "./generated-workflow-builder";
import { WorkflowDagPreview } from "./workflow-dag-preview";
import { WorkflowPageHeader } from "./workflow-page-header";
import { WorkflowRunBuilder } from "./workflows-page-ui";
import { WorkflowWorkspaceTabs } from "./workflow-workspace-tabs";

export function WorkflowDetailPage({ workflowId: workflowIdProp = "" }: { workflowId?: string }) {
  const searchParams = useSearchParams();
  const workflowId = workflowIdProp || searchParams.get("workflow") || "";
  const state = useWorkflowsPageState(workflowId);
  const selectedWorkflow = state.catalog.find((item) => item.id === workflowId) || state.selectedWorkflow;

  return (
    <div className="relative flex-1 w-full h-full overflow-y-auto bg-white px-8 py-10 text-slate-800">
      <WorkflowWorkspaceTabs />
      <div className="mx-auto max-w-5xl space-y-6">
        <WorkflowPageHeader
          title={selectedWorkflow?.name || "流程详情"}
          actions={
            <Button asChild variant="outline" className="h-9 bg-white px-3 text-slate-600">
              <Link
                href="/workflows"
                onFocus={() => void fetchWorkflowCatalog()}
                onPointerEnter={() => void fetchWorkflowCatalog()}
              >
                <ArrowLeft strokeWidth={1.5} className="mr-2 h-4 w-4" />
                返回流程目录
              </Link>
            </Button>
          }
        />

        {state.loading ? (
          <div className="flex h-48 items-center justify-center text-sm text-slate-400">
            <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
            正在读取流程详情
          </div>
        ) : state.error ? (
          <Alert variant="destructive">
            <AlertDescription>{state.error}</AlertDescription>
          </Alert>
        ) : !selectedWorkflow ? (
          <Alert variant="destructive">
            <AlertDescription>没有找到流程 {workflowId}</AlertDescription>
          </Alert>
        ) : (
          <WorkflowRunBuilder
            availableDatabases={state.availableDatabases}
            canSubmit={state.canSubmit}
            files={state.files}
            sampleLoading={state.sampleLoading}
            sampleUploads={state.sampleUploads}
            onFilesChange={state.setFiles}
            onLoadSampleData={() => void state.loadSampleData()}
            onSubmit={() => void state.submitRun()}
            isGeneratedToolRun={state.isGeneratedToolRun}
            selectedResourceDatabaseIds={state.selectedResourceDatabaseIds}
            server={state.server}
            submitError={state.submitError}
            submittedRun={state.submittedRun}
            submitting={state.submitting}
            runDetail={state.runDetail}
            workflowResources={state.workflowResources}
            onWorkflowResourceBindingChange={state.setWorkflowResourceBinding}
            missingRequiredResourceKeys={state.missingRequiredResourceKeys}
            selectedWorkflow={selectedWorkflow}
            params={state.params}
            onParamsChange={state.setParams}
            generatedBuilder={
              <GeneratedWorkflowBuilder
                availableDatabases={state.availableDatabases}
                builder={state.generatedBuilder}
                inputCount={state.files.length}
                tools={state.runnableTools}
              />
            }
            dagPreview={
              <WorkflowDagPreview
                files={state.files}
                onLoadSampleData={() => void state.loadSampleData()}
                onParamsChange={state.setParams}
                params={state.params}
                runDetail={state.runDetail}
                sampleLoading={state.sampleLoading}
                sampleUploads={state.sampleUploads}
                workflow={selectedWorkflow}
              />
            }
          />
        )}
      </div>
    </div>
  );
}
