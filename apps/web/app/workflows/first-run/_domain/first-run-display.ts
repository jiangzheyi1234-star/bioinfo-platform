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

export function friendlyFirstRunMessage(message?: string) {
  const value = String(message || "").trim();
  if (!value) return "";
  if (/Remote end closed connection without response/i.test(value)) {
    return "远程服务连接已中断，请刷新状态或重新检查运行环境。";
  }
  if (/Failed to fetch/i.test(value)) {
    return "本地服务暂时不可用，请刷新状态后重试。";
  }
  return value
    .replace("runner readiness", "运行环境检查")
    .replace("execution diagnostics", "执行诊断")
    .replace("resultId", "结果 ID");
}
