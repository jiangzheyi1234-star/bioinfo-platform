import type { WorkflowResultPackageExport } from "./workflows-page-model";

export const RESULT_PACKAGE_RETIRE_CONFIRMATION = "retire-result-package-export";

export type ResultPackageLifecycleAction = "retire";

export function resultPackageLifecycleState(item: WorkflowResultPackageExport): string {
  return item.lifecycleState?.trim() || "";
}

export function resultPackageBytesState(item: WorkflowResultPackageExport): string {
  return item.packageBytesState?.trim() || "";
}

export function resultPackageCanDownload(item: WorkflowResultPackageExport): boolean {
  return resultPackageLifecycleState(item) === "active" && resultPackageBytesState(item) === "available";
}

export function canRetireResultPackage(item: WorkflowResultPackageExport): boolean {
  return resultPackageCanDownload(item);
}

export function resultPackageActionConfirmation(): string {
  return RESULT_PACKAGE_RETIRE_CONFIRMATION;
}
