import type {
  DatabaseItem,
  DatabaseTemplate,
  DatabaseTemplateField,
  RemoteFileItem,
} from "./database-page-model";

export function databaseToolPath(item: DatabaseItem) {
  const resolved = item.resolvedPath;
  const entryPath = item.entryPath || item.inputPath || item.path || "";
  if (item.pathMode === "prefix") {
    return resolved?.prefix || resolved?.path || entryPath;
  }
  if (item.pathMode === "directory") {
    return entryPath || resolved?.firstIndexPrefix || resolved?.firstMatch || resolved?.path || "";
  }
  if (item.pathMode === "file") {
    return entryPath || resolved?.path || resolved?.firstMatch || "";
  }
  if (item.pathMode === "primary_with_sidecars") {
    return entryPath || resolved?.path || resolved?.firstMatch || "";
  }
  if (item.pathMode === "composite") {
    return "";
  }
  return entryPath || resolved?.firstIndexPrefix || resolved?.firstMatch || resolved?.path || "";
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

function normalizeCompositePath(value: string) {
  return value.trim().replace(/\\/g, "/").replace(/\/+$/, "");
}

function compositePathRoot(value: string) {
  if (!value) {
    return { kind: "empty", root: "" };
  }
  if (value === "~" || value.startsWith("~/")) {
    return { kind: "tilde", root: "~" };
  }
  if (/^[A-Za-z]:(?:\/|$)/.test(value)) {
    return { kind: "drive", root: `${value.slice(0, 2)}/` };
  }
  if (value.startsWith("/")) {
    return { kind: "unix", root: "/" };
  }
  return { kind: "relative", root: "." };
}

function compositePathSegments(value: string, root: string) {
  if (!value) {
    return [];
  }
  if (root === "/") {
    return value.slice(1).split("/").filter(Boolean);
  }
  if (root === "~") {
    return value.slice(1).replace(/^\/+/, "").split("/").filter(Boolean);
  }
  if (/^[A-Za-z]:\/$/.test(root)) {
    return value.slice(root.length).split("/").filter(Boolean);
  }
  return value.split("/").filter(Boolean);
}

function commonCompositePath(values: string[]) {
  if (values.length === 0) {
    return "";
  }
  const normalizedValues = values.map((value) => normalizeCompositePath(value)).filter(Boolean);
  if (normalizedValues.length === 0) {
    return "";
  }
  const roots = normalizedValues.map((value) => compositePathRoot(value));
  const rootKind = roots[0].kind;
  const root = roots[0].root;
  if (roots.some((currentRoot) => currentRoot.kind !== rootKind || currentRoot.root !== root)) {
    return ".";
  }
  const segments = normalizedValues.map((value) => compositePathSegments(value, root));

  const [first, ...rest] = segments;
  let commonLength = first.length;
  for (const current of rest) {
    let index = 0;
    while (index < commonLength && index < current.length && first[index] === current[index]) {
      index += 1;
    }
    commonLength = index;
    if (commonLength === 0) {
      break;
    }
  }

  if (commonLength === 0) {
    return root;
  }

  const commonSegments = first.slice(0, commonLength);
  if (root === ".") {
    return commonSegments.join("/");
  }
  return `${root}${commonSegments.join("/")}`;
}

export function compositeFallbackPath(values: Record<string, string>) {
  const filledValues = Object.values(values)
    .map((value) => value.trim())
    .filter(Boolean);
  if (filledValues.length === 0) {
    return "";
  }
  return commonCompositePath(filledValues);
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
