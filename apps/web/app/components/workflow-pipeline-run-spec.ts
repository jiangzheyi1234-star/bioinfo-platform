import type { WorkflowResourceBindings, WorkflowUpload } from "./workflows-page-model";

export type WorkflowArtifactRunInput = {
  artifactId: string;
  filename?: string;
  kind?: string;
  mimeType?: string;
  role?: string;
  sha256?: string;
  sizeBytes?: number;
  upstreamRunId?: string;
};

export type BuildPipelineRunSpecInput = {
  projectId: string;
  pipelineId: string;
  artifactInputs?: WorkflowArtifactRunInput[];
  uploads?: WorkflowUpload[];
  params?: Record<string, unknown>;
  resourceBindings?: WorkflowResourceBindings;
};

export function buildPipelineRunSpec({
  projectId,
  pipelineId,
  artifactInputs = [],
  uploads = [],
  params,
  resourceBindings,
}: BuildPipelineRunSpecInput) {
  const hasUploads = uploads.length > 0;
  const hasArtifactInputs = artifactInputs.length > 0;
  if (hasUploads === hasArtifactInputs) {
    throw new Error(hasUploads ? "PIPELINE_INPUT_SOURCE_AMBIGUOUS" : "PIPELINE_INPUT_SOURCE_REQUIRED");
  }
  const runSpec: Record<string, unknown> = {
    projectId,
    pipelineId,
    inputs: hasArtifactInputs
      ? artifactInputs.map((artifact, index) => ({
          artifactId: artifact.artifactId,
          ...(artifact.filename ? { filename: artifact.filename } : {}),
          role: artifact.role || (index === 0 ? "reads" : `reads_${index + 1}`),
          ...(artifact.upstreamRunId ? { upstreamRunId: artifact.upstreamRunId } : {}),
        }))
      : uploads.map((upload, index) => ({
          uploadId: upload.uploadId,
          filename: upload.filename,
          role: upload.role || (index === 0 ? "reads" : `reads_${index + 1}`),
        })),
    params: params || {},
  };
  if (resourceBindings && Object.keys(resourceBindings).length > 0) {
    runSpec.resourceBindings = resourceBindings;
  }
  return runSpec;
}
