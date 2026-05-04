import { Database, Dna, SearchCode, ShieldCheck } from "lucide-react";

import { LocalApiError } from "@/app/lib/local-api-client";

export type DatabaseItem = {
  id: string; name: string; type: string; version: string; path: string; description: string; source: string; manifestPath: string; checksum: string;
  metadata?: {
    templateId?: string;
    templateLabel?: string;
    sourceUrl?: string;
    buildCommand?: string;
    dbParams?: string;
    expectedFiles?: string[];
    availableReadLengths?: number[];
    resolvedPath?: {
      kind?: string;
      path?: string;
      prefix?: string;
      firstMatch?: string;
      firstIndexPrefix?: string;
    };
    validation?: {
      toolProbe?: {
        ok?: boolean;
        command?: string;
        returncode?: number;
        stdout?: string;
        stderr?: string;
      };
    };
  };
  status: string; message: string; updatedAt: string;
  lastCheckedAt: string | null;
};

export type DatabasesResponse = {
  data: {
    items: DatabaseItem[];
  };
};

export type DatabaseTemplatesResponse = {
  data: {
    items: DatabaseTemplate[];
  };
};

export type RemoteFileItem = {
  name: string; path: string; type: string; isDirectory: boolean; hidden?: boolean; mtime?: number;
};

export type RemoteFilesResponse = {
  data: {
    path: string;
    parentPath: string;
    items: RemoteFileItem[];
    truncated: boolean;
    offset?: number;
    limit?: number;
    total?: number;
    nextOffset?: number | null;
  };
};

export type DatabaseCandidate = {
  label: string;
  entryPath: string;
  inputPath: string;
  pathKind: string;
  templateId: string;
  evidence?: string[];
};

export type DatabaseCandidateDetail = {
  status?: string;
  message?: string;
  templateId?: string;
  pathKind?: string;
  inputPath?: string;
  candidates?: DatabaseCandidate[];
};

export type PathSelectionMode = "none" | "browser" | "manual";
export type PathKind = "directory" | "file" | "prefix" | "primary_with_sidecars" | "composite";
export const REMOTE_BROWSER_PAGE_SIZE = 500;

export type DatabaseTemplateField = {
  label?: string;
  pathKind?: PathKind;
  required?: boolean;
  pathHint?: string;
};

export type DatabaseTemplate = {
  id: string; name: string; type: string;
  supportLevel?: "stable";
  category?: string;
  icon: "taxonomy" | "index" | "amr" | "custom";
  pathKind?: PathKind;
  pathLabel?: string;
  runtimeValue?: string;
  selectorKind: PathKind;
  selector?: {
    kind: PathKind;
    hint: string;
  };
  description: string; pathHint: string; expectedFiles: string[];
  indexSuffixes?: string[];
  prefixPatternSets?: string[][];
  prefixAliasPatterns?: string[];
  fields?: Record<string, DatabaseTemplateField>;
  toolProbe?: {
    packageSpec?: string;
    commandTemplate?: string;
  };
};

export const DATABASE_TYPE_GROUPS = [
  {
    label: "分类学数据库",
    category: "taxonomy",
  },
  {
    label: "比对索引",
    category: "alignment",
  },
  {
    label: "注释数据库",
    category: "annotation",
  },
];

export function templateCategory(template: DatabaseTemplate) {
  if (template.category) return template.category;
  if (template.type === "taxonomy") return "taxonomy";
  if (template.type === "sequence_index") return "alignment";
  if (["amr", "annotation", "functional_profile", "profile_hmm"].includes(template.type)) return "annotation";
  if (["blast", "diamond", "bowtie2", "bwa", "sourmash", "mmseqs2", "minimap2", "star", "hisat2", "salmon", "kallisto"].includes(template.id)) return "alignment";
  if (["card_rgi", "eggnog_mapper", "interproscan", "humann", "hmmer_pfam"].includes(template.id)) return "annotation";
  if (["kraken2", "bracken", "metaphlan", "centrifuge", "kaiju", "gtdbtk", "silva_qiime", "checkm", "ncbi_taxonomy"].includes(template.id)) return "taxonomy";
  return "custom";
}

export function groupedDatabaseTemplates(templates: DatabaseTemplate[]) {
  const grouped = DATABASE_TYPE_GROUPS.map((group) => ({
    label: group.label,
    templates: templates.filter((template) => templateCategory(template) === group.category),
  })).filter((group) => group.templates.length > 0);
  const groupedCategories = new Set(DATABASE_TYPE_GROUPS.map((group) => group.category));
  const otherTemplates = templates.filter((template) => !groupedCategories.has(templateCategory(template)));
  if (otherTemplates.length > 0) {
    grouped.push({ label: "其他数据库", templates: otherTemplates });
  }
  return grouped;
}

export function templateIcon(template: DatabaseTemplate, className = "h-4 w-4") {
  if (template.icon === "amr") {
    return <ShieldCheck strokeWidth={1.5} className={className} />;
  }
  if (template.icon === "index") {
    return <SearchCode strokeWidth={1.5} className={className} />;
  }
  if (template.icon === "custom") {
    return <Database strokeWidth={1.5} className={className} />;
  }
  return <Dna strokeWidth={1.5} className={className} />;
}

export function databaseErrorMessage(err: unknown, fallback: string) {
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return fallback;
}

export function candidateDetailFromError(err: unknown): DatabaseCandidateDetail | null {
  if (!(err instanceof LocalApiError) || err.status !== 409) return null;
  const detail = err.detail;
  if (!detail || typeof detail !== "object") return null;
  const candidateDetail = detail as DatabaseCandidateDetail;
  if (!Array.isArray(candidateDetail.candidates) || candidateDetail.candidates.length === 0) return null;
  return candidateDetail;
}

export function remoteBrowserErrorMessage(err: unknown) {
  const message = databaseErrorMessage(err, "读取远程路径失败");
  if (/^not found$/i.test(message.trim())) {
    return "远程路径浏览接口未加载，请重启本地后端或桌面应用后再试。";
  }
  return message;
}

export function statusText(item: DatabaseItem) {
  if (item.status === "available") return "可用";
  if (item.status === "missing") return "缺失";
  if (item.status === "failed") return "验证失败";
  if (item.status === "declared") return "未校验";
  return "未校验";
}

export function databaseStatusMessage(item: DatabaseItem) {
  if (item.status === "available") {
    return "";
  }
  return item.message;
}

export function templateText(item: DatabaseItem, templateById: Record<string, DatabaseTemplate>) {
  return item.metadata?.templateLabel || templateById[item.metadata?.templateId || ""]?.name || item.type || "reference";
}

export function databaseToolPath(item: DatabaseItem) {
  const resolved = item.metadata?.resolvedPath;
  if (resolved?.kind === "prefix") {
    return resolved.prefix || resolved.path || "";
  }
  if (resolved?.kind === "file") {
    return resolved.path || resolved.firstMatch || "";
  }
  if (resolved?.kind === "primary_with_sidecars") {
    return resolved.path || resolved.firstMatch || "";
  }
  return resolved?.path || item.path || "";
}

export function emptyForm(template?: DatabaseTemplate) {
  return {
    name: "",
    templateId: template?.id || "",
    type: template?.type || "",
    version: "",
    path: "",
    description: "",
    manifestPath: "",
    sourceUrl: "",
    buildCommand: "",
    dbParams: "",
    expectedFiles: "",
  };
}

export function editForm(item?: DatabaseItem | null) {
  return {
    name: item?.name || "",
    version: item?.version || "",
    description: item?.description || "",
  };
}

export function defaultDatabaseName(template: DatabaseTemplate, path: string) {
  const normalized = path.trim().replace(/\\/g, "/").replace(/\/+$/, "");
  const basename = normalized.split("/").filter(Boolean).pop();
  return basename ? `${template.name} ${basename}` : template.name;
}

export function selectionCopy(template: DatabaseTemplate) {
  if (template.selectorKind === "file") {
    return `选择${pathLabel(template)}，或选择只包含一个候选文件的目录。`;
  }
  if (template.selectorKind === "prefix") {
    return `选择${pathLabel(template)}。`;
  }
  if (template.selectorKind === "primary_with_sidecars") {
    return `选择${pathLabel(template)}，不要选择旁边的索引文件。`;
  }
  if (template.selectorKind === "composite") {
    return "按字段选择复合数据库所需的目录或文件。";
  }
  return `选择${pathLabel(template)}。`;
}

export function runtimeHint(template: DatabaseTemplate) {
  if (template.selectorKind === "prefix") {
    return "运行时注入去掉索引后缀后的 prefix。";
  }
  if (template.selectorKind === "primary_with_sidecars") {
    return "运行时注入 FASTA 主文件，并检查同名前缀索引。";
  }
  if (template.selectorKind === "file") {
    return "运行时直接注入该文件。";
  }
  if (template.selectorKind === "composite") {
    return "复合数据库需要填写多个路径字段。";
  }
  return "运行时直接注入该目录。";
}

export function stableComplexityCopy(template: DatabaseTemplate) {
  if (template.selectorKind === "composite") return "Stable · 复合数据库";
  if (template.selectorKind === "prefix") return "Stable · 高级路径解析";
  if (template.selectorKind === "primary_with_sidecars") return "Stable · 主文件与旁侧索引";
  return "Stable";
}

export function pathLabel(template: DatabaseTemplate | null) {
  if (template?.pathLabel) return template.pathLabel;
  if (template?.selectorKind === "composite") return "复合数据库路径";
  if (template?.selectorKind === "file") return "数据库文件";
  if (template?.selectorKind === "prefix") return "索引目录或索引文件";
  if (template?.selectorKind === "primary_with_sidecars") return "FASTA 主文件";
  return "数据库目录";
}

export function templateCheckItems(template: DatabaseTemplate | null) {
  if (!template) return "";
  if (template.expectedFiles.length > 0) return template.expectedFiles.join(", ");
  if (template.selectorKind === "file") return "匹配模板定义的数据库文件";
  if (template.selectorKind === "prefix") return "完整索引前缀文件组";
  if (template.selectorKind === "primary_with_sidecars") return "主文件及同名前缀索引文件";
  if (template.selectorKind === "composite") return "复合资源字段";
  return "路径存在且目录非空";
}

export function templateCheckItemList(template: DatabaseTemplate | null) {
  return templateCheckItems(template).split(",").map((item) => item.trim()).filter(Boolean);
}

export function compositeFieldEntries(template: DatabaseTemplate | null) {
  return Object.entries(template?.fields || {});
}

export function compositeFieldLabel(key: string, field: DatabaseTemplateField) {
  return field.label || key;
}

export function compositeInputFields(
  template: DatabaseTemplate | null,
  values: Record<string, string>
): Record<string, string> {
  return Object.fromEntries(
    compositeFieldEntries(template)
      .map(([key]) => [key, (values[key] || "").trim()])
      .filter(([, value]) => value)
  );
}

export function isBwaIndexFile(path: string) { return /\.(amb|ann|bwt|pac|sa)$/i.test(path); }

export function browserFileAction(template: DatabaseTemplate | null, item: RemoteFileItem) {
  if (item.isDirectory || !template || template.selectorKind === "directory") return null;
  if (template.selectorKind === "composite") return null;
  if (template.selectorKind === "prefix") return { label: "选择此索引", disabled: false, hint: "" };
  if (template.selectorKind === "primary_with_sidecars") {
    return isBwaIndexFile(item.path) ? { label: "索引文件不能作为 FASTA 主文件", disabled: true, hint: "请选择同名前缀的 FASTA 主文件" } : { label: "选择 FASTA 主文件", disabled: false, hint: "" };
  }
  return { label: "选择此文件", disabled: false, hint: "" };
}
