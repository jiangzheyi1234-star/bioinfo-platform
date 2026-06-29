import type { WorkflowArtifact } from "@/app/components/workflows-page-model";

export function artifactName(artifact: WorkflowArtifact) {
  return (
    artifactDisplayValue(artifact, "artifactKey") ||
    artifactDisplayValue(artifact, "name") ||
    artifactDisplayValue(artifact, "path").split("/").pop() ||
    artifact.kind ||
    artifact.artifactId
  );
}

function artifactDisplayValue(artifact: WorkflowArtifact, key: "artifactKey" | "name" | "path") {
  const display = artifact as WorkflowArtifact & Record<typeof key, string | undefined>;
  return display[key] || "";
}

export function formatBytes(bytes?: number) {
  if (!bytes) return "";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const index = Math.min(sizes.length - 1, Math.floor(Math.log(bytes) / Math.log(k)));
  return `${parseFloat((bytes / k ** index).toFixed(2))} ${sizes[index]}`;
}
