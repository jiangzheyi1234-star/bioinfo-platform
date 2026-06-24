import type { WorkflowResultPackageExport } from "./workflows-page-model";

export const RESULT_PACKAGE_RETIRE_CONFIRMATION = "retire-result-package-export";
export const RESULT_PACKAGE_BYTE_DELETE_CONFIRMATION = "delete-result-package-export-bytes";

export type ResultPackageLifecycleAction = "retire" | "deleteBytes";

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

export function canDeleteResultPackageBytes(item: WorkflowResultPackageExport): boolean {
  return resultPackageLifecycleState(item) === "retired" && resultPackageBytesState(item) === "available";
}

export function resultPackageActionConfirmation(action: ResultPackageLifecycleAction): string {
  return action === "retire" ? RESULT_PACKAGE_RETIRE_CONFIRMATION : RESULT_PACKAGE_BYTE_DELETE_CONFIRMATION;
}
