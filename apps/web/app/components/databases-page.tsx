"use client";

import { ArrowLeft, ChevronUp, Database, Dna, FolderOpen, Plus, RefreshCw, SearchCode, ShieldCheck, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { requestLocalApiJson } from "@/app/lib/local-api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import { WorkflowWorkspaceTabs } from "./workflow-workspace-tabs";

type DatabaseItem = {
  id: string;
  name: string;
  type: string;
  version: string;
  path: string;
  description: string;
  source: string;
  manifestPath: string;
  checksum: string;
  metadata?: {
    templateId?: string;
    templateLabel?: string;
    sourceUrl?: string;
    buildCommand?: string;
    dbParams?: string;
    expectedFiles?: string[];
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
        stderr?: string;
      };
    };
  };
  status: string;
  message: string;
  updatedAt: string;
  lastCheckedAt: string | null;
};

type DatabasesResponse = {
  data: {
    items: DatabaseItem[];
  };
};

type DatabaseTemplatesResponse = {
  data: {
    items: DatabaseTemplate[];
  };
};

type RemoteFileItem = {
  name: string;
  path: string;
  type: string;
  isDirectory: boolean;
  hidden?: boolean;
  mtime?: number;
};

type RemoteFilesResponse = {
  data: {
    path: string;
    parentPath: string;
    items: RemoteFileItem[];
    truncated: boolean;
  };
};

type DatabaseTemplate = {
  id: string;
  name: string;
  type: string;
  icon: "taxonomy" | "index" | "amr" | "custom";
  pathKind?: "directory" | "file" | "prefix";
  selectorKind: "directory" | "file" | "prefix";
  selector?: {
    kind: "directory" | "file" | "prefix";
    hint: string;
  };
  description: string;
  pathHint: string;
  expectedFiles: string[];
  toolProbe?: {
    packageSpec?: string;
    commandTemplate?: string;
  };
};

function templateIcon(template: DatabaseTemplate, className = "h-4 w-4") {
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

function databaseErrorMessage(err: unknown, fallback: string) {
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return fallback;
}

function remoteBrowserErrorMessage(err: unknown) {
  const message = databaseErrorMessage(err, "读取远程路径失败");
  if (/^not found$/i.test(message.trim())) {
    return "远程路径浏览接口未加载，请重启本地后端或桌面应用后再试。";
  }
  return message;
}

function statusText(item: DatabaseItem) {
  if (item.status === "available") {
    return "可用";
  }
  if (item.status === "missing") {
    return "缺失";
  }
  if (item.status === "failed") {
    return "验证失败";
  }
  return "已登记";
}

function templateText(item: DatabaseItem, templateById: Record<string, DatabaseTemplate>) {
  return item.metadata?.templateLabel || templateById[item.metadata?.templateId || ""]?.name || item.type || "reference";
}

function databaseToolPath(item: DatabaseItem) {
  const resolved = item.metadata?.resolvedPath;
  return resolved?.prefix || resolved?.firstIndexPrefix || resolved?.firstMatch || resolved?.path || "";
}

function emptyForm(template?: DatabaseTemplate) {
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

function defaultDatabaseName(template: DatabaseTemplate, path: string) {
  const normalized = path.trim().replace(/\\/g, "/").replace(/\/+$/, "");
  const basename = normalized.split("/").filter(Boolean).pop();
  return basename ? `${template.name} ${basename}` : template.name;
}

function browserSelectionPath(item: RemoteFileItem, template: DatabaseTemplate | null, currentPath: string) {
  if (!item.isDirectory && template?.selectorKind === "directory") {
    return currentPath;
  }
  if (!item.isDirectory && template?.selectorKind === "prefix") {
    return stripIndexSuffix(item.path);
  }
  return item.path;
}

function stripIndexSuffix(path: string) {
  return path.replace(/(\.rev\.[12]\.(bt2l?|ht2l?)|\.[1-8]\.(bt2l?|ht2l?)|\.[1-4]\.cf|\.(nhr|nin|nsq|phr|pin|psq|amb|ann|bwt|pac|sa|dbtype)|_(h|seq))$/, "");
}

function selectionCopy(template: DatabaseTemplate) {
  if (template.selectorKind === "directory") {
    return "请选择包含索引文件的目录。";
  }
  if (template.selectorKind === "file") {
    return "请选择数据库文件。";
  }
  return "请选择索引前缀或任一索引文件。";
}

export function DatabasesPage() {
  const [templates, setTemplates] = useState<DatabaseTemplate[]>([]);
  const [items, setItems] = useState<DatabaseItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [templateError, setTemplateError] = useState("");
  const [templateLoading, setTemplateLoading] = useState(false);
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [checkingId, setCheckingId] = useState("");
  const [form, setForm] = useState(emptyForm);
  const [browserOpen, setBrowserOpen] = useState(false);
  const [browserPath, setBrowserPath] = useState("~");
  const [browserItems, setBrowserItems] = useState<RemoteFileItem[]>([]);
  const [browserParentPath, setBrowserParentPath] = useState("");
  const [browserLoading, setBrowserLoading] = useState(false);
  const [browserError, setBrowserError] = useState("");
  const [browserTruncated, setBrowserTruncated] = useState(false);
  const browserListRef = useRef<HTMLDivElement | null>(null);
  const browserScrollByPathRef = useRef<Record<string, number>>({});
  const templateById: Record<string, DatabaseTemplate> = Object.fromEntries(templates.map((template) => [template.id, template]));

  const loadDatabases = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await requestLocalApiJson<DatabasesResponse>("GET", "/api/v1/databases", { cache: "no-store" });
      setItems(response.data.items);
    } catch (err) {
      setError(databaseErrorMessage(err, "读取数据库列表失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDatabaseTemplates = useCallback(async () => {
    setTemplateLoading(true);
    setTemplateError("");
    try {
      const response = await requestLocalApiJson<DatabaseTemplatesResponse>("GET", "/api/v1/database-templates", { cache: "no-store" });
      const nextTemplates = response.data.items || [];
      if (nextTemplates.length === 0) {
        throw new Error("远端未返回数据库模板。");
      }
      setTemplates(nextTemplates);
      setForm((current) => {
        if (nextTemplates.some((template) => template.id === current.templateId)) {
          return current;
        }
        const template = nextTemplates[0];
        return {
          ...current,
          templateId: template.id,
          type: template.type,
          description: current.description || template.description,
        };
      });
    } catch (err) {
      setTemplates([]);
      setTemplateError(databaseErrorMessage(err, "读取数据库模板失败"));
    } finally {
      setTemplateLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDatabases();
    void loadDatabaseTemplates();
  }, [loadDatabases, loadDatabaseTemplates]);

  const updateForm = (key: keyof typeof form, value: string) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const rememberBrowserScroll = useCallback(() => {
    const node = browserListRef.current;
    if (!node || !browserPath) {
      return;
    }
    browserScrollByPathRef.current[browserPath] = node.scrollTop;
  }, [browserPath]);

  const loadRemotePath = useCallback(
    async (path: string) => {
      rememberBrowserScroll();
      const nextPath = path.trim() || "~";
      setBrowserOpen(true);
      setBrowserLoading(true);
      setBrowserError("");
      try {
        const response = await requestLocalApiJson<RemoteFilesResponse>(
          "GET",
          `/api/v1/ssh/files?path=${encodeURIComponent(nextPath)}&directories_only=false&limit=200`,
          { cache: "no-store" }
        );
        setBrowserPath(response.data.path);
        setBrowserParentPath(response.data.parentPath);
        setBrowserItems(response.data.items || []);
        setBrowserTruncated(Boolean(response.data.truncated));
      } catch (err) {
        setBrowserItems([]);
        setBrowserTruncated(false);
        setBrowserError(remoteBrowserErrorMessage(err));
      } finally {
        setBrowserLoading(false);
      }
    },
    [rememberBrowserScroll]
  );

  useEffect(() => {
    const node = browserListRef.current;
    if (!node || browserLoading) {
      return;
    }
    node.scrollTop = browserScrollByPathRef.current[browserPath] || 0;
  }, [browserPath, browserItems, browserLoading]);

  const selectTemplate = (templateId: string) => {
    const template = templateById[templateId];
    if (!template) {
      setError("数据库模板不可用，请刷新模板后重试。");
      return;
    }
    setForm((current) => ({
      ...current,
      templateId: template.id,
      type: template.type,
      description: current.description || template.description,
    }));
  };

  const addDatabase = async () => {
    const path = form.path.trim();
    if (!selectedTemplate) {
      setError("数据库模板未加载，不能添加数据库。");
      return;
    }
    if (!path) {
      setError("远程路径不能为空");
      return;
    }
    const name = form.name.trim() || defaultDatabaseName(selectedTemplate, path);
    setSaving(true);
    setError("");
    try {
      const response = await requestLocalApiJson<{ data: DatabaseItem }>("POST", "/api/v1/databases", {
        body: {
          name,
          templateId: form.templateId,
          type: form.type,
          version: form.version.trim(),
          path,
          description: form.description.trim(),
          manifestPath: form.manifestPath.trim(),
          source: "manual",
          metadata: {
            templateId: form.templateId,
            sourceUrl: form.sourceUrl.trim(),
            buildCommand: form.buildCommand.trim(),
            dbParams: form.dbParams.trim(),
            expectedFiles: form.expectedFiles
              .split(",")
              .map((value) => value.trim())
              .filter(Boolean),
          },
        },
      });
      setItems((current) => [response.data, ...current.filter((item) => item.id !== response.data.id)]);
      setForm(emptyForm(templates[0]));
      setAdding(false);
      void checkDatabase(response.data.id);
    } catch (err) {
      setError(databaseErrorMessage(err, "添加数据库失败"));
    } finally {
      setSaving(false);
    }
  };

  const checkDatabase = async (id: string) => {
    setCheckingId(id);
    setError("");
    try {
      const response = await requestLocalApiJson<{ data: DatabaseItem }>("POST", `/api/v1/databases/${encodeURIComponent(id)}/check`);
      setItems((current) => current.map((item) => (item.id === id ? response.data : item)));
    } catch (err) {
      setError(databaseErrorMessage(err, "校验数据库失败"));
    } finally {
      setCheckingId("");
    }
  };

  const removeDatabase = async (id: string) => {
    setError("");
    try {
      await requestLocalApiJson("DELETE", `/api/v1/databases/${encodeURIComponent(id)}`);
      setItems((current) => current.filter((item) => item.id !== id));
    } catch (err) {
      setError(databaseErrorMessage(err, "移除数据库失败"));
    }
  };

  const selectedTemplate = templateById[form.templateId] || templates[0] || null;

  return (
    <div className="relative h-full w-full overflow-y-auto bg-white px-8 py-10 text-slate-800">
      <WorkflowWorkspaceTabs />
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex h-9 items-center justify-end">
          {adding ? (
            <Button type="button" variant="outline" className="h-9 bg-white px-3 text-slate-600" onClick={() => setAdding(false)}>
              <ArrowLeft strokeWidth={1.5} className="mr-2 h-4 w-4" />
              返回数据库
            </Button>
          ) : (
            <Button
              type="button"
              variant="outline"
              className="h-9 bg-white px-3 text-slate-600"
              disabled={templateLoading || templates.length === 0}
              onClick={() => setAdding(true)}
            >
              <Plus strokeWidth={1.5} className="mr-2 h-4 w-4" />
              添加数据库
            </Button>
          )}
        </div>

        <div className="text-center">
          <h1 className="text-2xl font-semibold">数据库</h1>
        </div>

        {error ? <div className="py-1 text-sm text-red-600">{error}</div> : null}
        {templateError ? <div className="py-1 text-sm text-red-600">{templateError}</div> : null}

        {adding ? (
          <div className="grid grid-cols-1 gap-6 border-y border-slate-100 py-4 md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <div className="space-y-3">
              <Label>选择模板</Label>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-1">
                {templateLoading ? <div className="px-3 py-3 text-xs text-slate-400">正在读取数据库模板</div> : null}
                {!templateLoading && templates.length === 0 ? <div className="px-3 py-3 text-xs text-red-600">数据库模板不可用</div> : null}
                {templates.map((template) => (
                  <button
                    key={template.id}
                    type="button"
                    className={cn(
                      "flex min-h-16 items-start rounded-md border bg-white px-3 py-2 text-left transition-colors hover:border-blue-300 hover:bg-blue-50/40",
                      form.templateId === template.id ? "border-blue-400 bg-blue-50" : "border-slate-200"
                    )}
                    onClick={() => selectTemplate(template.id)}
                  >
                    <span className="mt-0.5 text-blue-600">{templateIcon(template)}</span>
                    <span className="ml-2 min-w-0">
                      <span className="block truncate text-sm font-medium text-slate-800">{template.name}</span>
                      <span className="mt-0.5 block truncate text-xs text-slate-500">{template.description}</span>
                    </span>
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-4">
              {selectedTemplate ? (
                <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
                  <div className="flex items-center gap-2 text-sm font-medium text-slate-700">
                    {templateIcon(selectedTemplate, "h-4 w-4 text-blue-600")}
                    {selectedTemplate.name}
                  </div>
                  <p className="mt-1 text-xs text-slate-500">路径示例：{selectedTemplate.pathHint}</p>
                  {selectedTemplate.expectedFiles.length > 0 ? (
                    <p className="mt-1 text-xs text-slate-500">验证：{selectedTemplate.expectedFiles.join(", ")}</p>
                  ) : (
                    <p className="mt-1 text-xs text-slate-500">验证：路径存在且目录非空。</p>
                  )}
                  <p className="mt-1 text-xs text-slate-500">工具验证：{selectedTemplate.toolProbe?.packageSpec || "自定义规则"}</p>
                  <p className="mt-1 text-xs text-slate-500">选择方式：{selectionCopy(selectedTemplate)}</p>
                </div>
              ) : null}

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="space-y-1.5 md:col-span-2">
                  <Label htmlFor="database-path">远程路径</Label>
                  <Input
                    id="database-path"
                    placeholder={selectedTemplate?.pathHint || ""}
                    value={form.path}
                    onChange={(event) => updateForm("path", event.target.value)}
                  />
                  <div className="flex justify-end">
                    <Button
                      type="button"
                      variant="outline"
                      className="h-8 px-2 text-xs text-slate-600"
                      onClick={() => void loadRemotePath(form.path.trim() || "~")}
                    >
                      <FolderOpen strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
                      浏览远程路径
                    </Button>
                  </div>
                </div>
              </div>

              {browserOpen ? (
                <div className="rounded-md border border-slate-200 bg-white">
                  <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2">
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-mono text-xs text-slate-700">{browserPath}</div>
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-xs text-slate-600"
                      disabled={browserLoading || !browserParentPath || browserParentPath === browserPath}
                      onClick={() => void loadRemotePath(browserParentPath)}
                    >
                      <ChevronUp strokeWidth={1.5} className="mr-1 h-3.5 w-3.5" />
                      上级
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-xs text-slate-600"
                      disabled={browserLoading}
                      onClick={() => void loadRemotePath(browserPath)}
                    >
                      <RefreshCw strokeWidth={1.5} className={cn("mr-1 h-3.5 w-3.5", browserLoading && "animate-spin")} />
                      刷新
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 px-2 text-xs"
                      onClick={() => updateForm("path", browserPath)}
                    >
                      {selectedTemplate?.selectorKind === "directory" ? "选择当前目录" : "选择当前路径"}
                    </Button>
                  </div>
                  {browserError ? <div className="px-3 py-2 text-xs text-red-600">{browserError}</div> : null}
                  {browserLoading ? (
                    <div className="flex items-center px-3 py-3 text-xs text-slate-400">
                      <RefreshCw strokeWidth={1.5} className="mr-2 h-3.5 w-3.5 animate-spin" />
                      正在读取远程目录
                    </div>
                  ) : browserItems.length === 0 && !browserError ? (
                    <div className="px-3 py-3 text-xs text-slate-400">当前目录没有可选路径</div>
                  ) : (
                    <div ref={browserListRef} className="max-h-64 overflow-auto p-1">
                      {browserItems.map((item) => (
                        <div
                          key={item.path}
                          className="flex items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-slate-50"
                        >
                          {item.isDirectory ? (
                            <FolderOpen strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-blue-600" />
                          ) : (
                            <Database strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-slate-500" />
                          )}
                          <button
                            type="button"
                            className="min-w-0 flex-1 truncate text-left font-mono text-slate-700"
                            onClick={() =>
                              item.isDirectory
                                ? void loadRemotePath(item.path)
                                : updateForm("path", browserSelectionPath(item, selectedTemplate, browserPath))
                            }
                          >
                            {item.name}
                          </button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-6 px-2 text-[11px] text-slate-500"
                            onClick={() => updateForm("path", browserSelectionPath(item, selectedTemplate, browserPath))}
                          >
                            {item.isDirectory || selectedTemplate?.selectorKind !== "directory" ? "选择" : "选所在目录"}
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}
                  {browserTruncated ? <div className="border-t border-slate-100 px-3 py-1.5 text-[11px] text-amber-700">结果已截断，请进入更具体的目录。</div> : null}
                </div>
              ) : null}

              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" className="h-9 px-3 text-slate-500" onClick={() => setAdding(false)}>
                  取消
                </Button>
                <Button type="button" className="h-9 px-3" onClick={addDatabase} disabled={saving || !form.path.trim() || !selectedTemplate}>
                  {saving ? "加入中" : "加入"}
                </Button>
              </div>
            </div>
          </div>
        ) : null}

        <div className="grid grid-cols-1 gap-x-12 gap-y-2 md:grid-cols-2">
          {items.map((item) => (
            <div
              key={item.id}
              className="flex items-center rounded-lg border border-transparent bg-white px-3 py-3 transition-colors hover:border-slate-200 hover:bg-slate-50"
            >
              <Database strokeWidth={1.5} className="mr-3 h-4 w-4 flex-shrink-0 text-zinc-500" />
              <div className="min-w-0 flex-1">
                <h3 className="truncate text-sm font-medium text-slate-800">{item.name}</h3>
                <p className="mt-1 truncate text-xs text-slate-500">
                  {templateText(item, templateById)} {item.version ? `· ${item.version}` : ""} · {statusText(item)}
                </p>
                {item.message ? <p className="mt-1 truncate text-xs text-slate-400">{item.message}</p> : null}
                {databaseToolPath(item) && databaseToolPath(item) !== item.path ? (
                  <p className="mt-1 truncate font-mono text-[11px] text-slate-400">实际工具路径：{databaseToolPath(item)}</p>
                ) : null}
              </div>
              <div className="ml-3 flex items-center gap-1">
                <Button type="button" variant="ghost" size="icon" className="h-8 w-8 text-slate-400" onClick={() => checkDatabase(item.id)}>
                  <RefreshCw strokeWidth={1.5} className={cn("h-4 w-4", checkingId === item.id && "animate-spin")} />
                </Button>
                <Button type="button" variant="ghost" size="icon" className="h-8 w-8 text-slate-400" onClick={() => removeDatabase(item.id)}>
                  <Trash2 strokeWidth={1.5} className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>

        {!loading && items.length === 0 ? <div className="py-8 text-center text-sm text-slate-500">暂无数据库</div> : null}
      </div>
    </div>
  );
}
