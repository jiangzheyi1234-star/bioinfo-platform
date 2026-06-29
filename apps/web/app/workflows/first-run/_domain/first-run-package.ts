import type { WorkflowResultPackageExport } from "@/app/components/workflows-page-model";

export function firstRunResultPackageReady(item: WorkflowResultPackageExport) {
  return (
    item.lifecycleState === "active" &&
    item.packageBytesState === "available" &&
    Boolean(item.download) &&
    (item.artifactPayloadMode === "full" || item.includeArtifacts === true)
  );
}

export function mergePackageExport(
  item: WorkflowResultPackageExport,
  current: WorkflowResultPackageExport[]
): WorkflowResultPackageExport[] {
  const packageExportId = item.packageExportId || "";
  if (!packageExportId) return [item, ...current];
  return [item, ...current.filter((candidate) => candidate.packageExportId !== packageExportId)];
}
