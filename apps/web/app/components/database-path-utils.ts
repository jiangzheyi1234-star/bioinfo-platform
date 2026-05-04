import type {
  DatabaseItem,
  DatabaseTemplate,
  DatabaseTemplateField,
  RemoteFileItem,
} from "./database-page-model";

export function databaseToolPath(item: DatabaseItem) {
  const resolved = item.metadata?.resolvedPath;
  if (resolved?.kind === "prefix") {
    return resolved.prefix || resolved.path || "";
  }
  if (resolved?.kind === "directory") {
    return resolved.firstIndexPrefix || resolved.firstMatch || resolved.path || "";
  }
  if (resolved?.kind === "file") {
    return resolved.path || resolved.firstMatch || "";
  }
  if (resolved?.kind === "primary_with_sidecars") {
    return resolved.path || resolved.firstMatch || "";
  }
  return resolved?.firstIndexPrefix || resolved?.firstMatch || resolved?.path || item.path || "";
}

export function defaultDatabaseName(template: DatabaseTemplate, path: string) {
  const normalized = path.trim().replace(/\\/g, "/").replace(/\/+$/, "");
  const basename = normalized.split("/").filter(Boolean).pop();
  return basename ? `${template.name} ${basename}` : template.name;
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

function isBwaIndexFile(path: string) { return /\.(amb|ann|bwt|pac|sa)$/i.test(path); }

export function browserFileAction(template: DatabaseTemplate | null, item: RemoteFileItem) {
  if (item.isDirectory || !template || template.selectorKind === "directory") return null;
  if (template.selectorKind === "composite") return null;
  if (template.selectorKind === "prefix") return { label: "选择此索引", disabled: false, hint: "" };
  if (template.selectorKind === "primary_with_sidecars") {
    return isBwaIndexFile(item.path) ? { label: "索引文件不能作为 FASTA 主文件", disabled: true, hint: "请选择同名前缀的 FASTA 主文件" } : { label: "选择 FASTA 主文件", disabled: false, hint: "" };
  }
  return { label: "选择此文件", disabled: false, hint: "" };
}
