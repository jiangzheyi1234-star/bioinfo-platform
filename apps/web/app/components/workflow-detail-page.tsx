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
                onFocus={() => void fetchWorkflowCatalog().catch(() => undefined)}
                onPointerEnter={() => void fetchWorkflowCatalog().catch(() => undefined)}
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
            artifactInputDetail={state.artifactInputDetail}
            artifactInputError={state.artifactInputError}
            artifactInputLoading={state.artifactInputLoading}
            artifactInputRunId={state.artifactInputRunId}
            artifactInputs={state.artifactInputs}
            canSubmit={state.canSubmit}
            files={state.files}
            sampleLoading={state.sampleLoading}
            sampleUploads={state.sampleUploads}
            runHistory={state.runHistory}
            onArtifactInputRunChange={(runId) => void state.loadArtifactInputRun(runId)}
            onArtifactInputSelect={state.selectArtifactInput}
            onArtifactInputRemove={state.removeArtifactInput}
            onClearArtifactInputs={state.clearArtifactInputs}
            onFilesChange={state.setFiles}
            onLoadSampleData={() => void state.loadSampleData()}
            onSubmit={() => void state.submitRun()}
            onEnsureRunner={() => void state.ensureRunner()}
            onRefreshServer={state.refreshWorkflowServer}
            isGeneratedToolRun={state.isGeneratedToolRun}
            selectedResourceDatabaseIds={state.selectedResourceDatabaseIds}
            server={state.server}
            runnerEnsureBusy={state.runnerEnsureBusy}
            runnerRepairError={state.runnerRepairError}
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
                activeDesignDraft={state.activeWorkflowDesignDraft}
                availableDatabases={state.availableDatabases}
                builder={state.generatedBuilder}
                designBusy={state.workflowDesignBusy}
                compileResult={state.workflowDesignCompileResult}
                designDrafts={state.workflowDesignDrafts}
                designError={state.workflowDesignError}
                designPlan={state.workflowDesignPlan}
                inputCount={state.generatedInputCount}
                onAddRecommendedTool={state.addRecommendedWorkflowTool}
                onOpenDesignDraft={state.openWorkflowDesignDraft}
                onPlanProposedConnection={state.planGeneratedWorkflowProposedConnection}
                onCompile={() => {
                  void state.compileGeneratedWorkflowDesign().catch(() => undefined);
                }}
                onSaveAndValidate={() => {
                  void state.saveAndValidateGeneratedWorkflowDesign().catch(() => undefined);
                }}
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
