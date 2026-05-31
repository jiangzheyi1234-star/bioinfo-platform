"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  addToolDependency,
  checkToolDependency,
  fetchAddedTools,
  getCachedAddedTools,
  openToolSourceUrl,
  prepareToolDependency,
  removeToolDependency,
  searchToolCapabilities,
  updateToolRuleTemplate,
} from "./tools-page-api";
import {
  type AddedTool,
  type RuleSpecTemplate,
  type ToolSearchItem,
  applySelectedPackageLock,
  applySelectedWrapperLock,
  buildExecutableRuleSpecForSelectedTool,
  defaultRuleSpecOutputPath,
  dependencyKey,
  missingRuleSpecFields,
  packageSpecLocked,
  searchErrorMessage,
  toolErrorMessage,
} from "./tools-page-model";
import { withCuratedRuleTemplate } from "./tool-rule-readiness";

export function useToolsPageState() {
  const [initialCachedAddedTools] = useState(() => getCachedAddedTools());
  const [view, setView] = useState<"library" | "search">("library");
  const [addedTools, setAddedTools] = useState<AddedTool[]>(() => initialCachedAddedTools || []);
  const addedToolsRef = useRef<AddedTool[]>(initialCachedAddedTools || []);
  const [toolsLoading, setToolsLoading] = useState(() => !initialCachedAddedTools);
  const [toolsError, setToolsError] = useState("");
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("all");
  const [items, setItems] = useState<ToolSearchItem[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [versionOverrides, setVersionOverrides] = useState<Record<string, string>>({});
  const [wrapperOverrides, setWrapperOverrides] = useState<Record<string, string>>({});
  const [outputPathOverrides, setOutputPathOverrides] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searchPage, setSearchPage] = useState(1);
  const [searchTotal, setSearchTotal] = useState(0);
  const [searchHasMore, setSearchHasMore] = useState(false);
  const [searchComplete, setSearchComplete] = useState(true);
  const [editingRuleSpecToolId, setEditingRuleSpecToolId] = useState("");
  const [ruleSpecSavingId, setRuleSpecSavingId] = useState("");
  const [ruleSpecEditError, setRuleSpecEditError] = useState("");
  const [checkingToolId, setCheckingToolId] = useState("");
  const [addingSelectedTool, setAddingSelectedTool] = useState(false);

  const loadAddedTools = useCallback(async (options: { forceRefresh?: boolean; silent?: boolean } = {}) => {
    const currentTools = addedToolsRef.current;
    const showLoading = !options.silent && currentTools.length === 0;
    if (showLoading) {
      setToolsLoading(true);
    }
    setToolsError("");
    try {
      const nextTools = await fetchAddedTools({ forceRefresh: options.forceRefresh });
      addedToolsRef.current = nextTools;
      setAddedTools(nextTools);
    } catch (err) {
      if (addedToolsRef.current.length === 0) {
        setAddedTools([]);
      }
      setToolsError(toolErrorMessage(err, "读取工具列表失败"));
    } finally {
      if (showLoading) {
        setToolsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadAddedTools({ silent: Boolean(initialCachedAddedTools) });
  }, [initialCachedAddedTools, loadAddedTools]);

  useEffect(() => {
    const normalized = query.trim();
    if (normalized.length < 2) {
      setItems([]);
      setSelectedId("");
      setError("");
      setLoading(false);
      setSearchTotal(0);
      setSearchHasMore(false);
      setSearchComplete(true);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError("");
      try {
        const response = await searchToolCapabilities({
          query: normalized,
          page: searchPage,
          signal: controller.signal,
        });
        const nextItems = response.items || [];
        setItems(nextItems);
        setSearchTotal(response.total ?? nextItems.length);
        setSearchHasMore(Boolean(response.hasMore));
        setSearchComplete(response.complete !== false);
        setError("");
        setSelectedId((current) => (nextItems.some((item) => item.id === current) ? current : nextItems[0]?.id || ""));
      } catch (err) {
        if (controller.signal.aborted) {
          return;
        }
        setItems([]);
        setSelectedId("");
        setSearchTotal(0);
        setSearchHasMore(false);
        setSearchComplete(true);
        setError(searchErrorMessage(err));
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }, 350);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query, searchPage]);

  const filtered = useMemo(() => {
    if (source === "all") {
      return items;
    }
    return items.filter((item) => item.source === source);
  }, [items, source]);

  const baseSelected = filtered.find((item) => item.id === selectedId) ?? filtered[0];
  const selectedVersion = baseSelected ? (versionOverrides[baseSelected.id] ?? baseSelected.latestVersion ?? "") : "";
  const selectedPackageSpec = baseSelected
    ? selectedVersion.trim()
      ? `${baseSelected.source}::${baseSelected.name}=${selectedVersion.trim()}`
      : `${baseSelected.source}::${baseSelected.name}`
    : "";
  const selectedWrapperPath = baseSelected
    ? wrapperOverrides[baseSelected.id] ?? baseSelected.snakemakeWrappers?.[0]?.wrapperPath ?? ""
    : "";
  const selectedOutputPath = baseSelected
    ? outputPathOverrides[baseSelected.id] ?? defaultRuleSpecOutputPath(baseSelected, selectedWrapperPath)
    : "";
  const selected = baseSelected
    ? buildExecutableRuleSpecForSelectedTool(
        applySelectedWrapperLock(applySelectedPackageLock(baseSelected, selectedVersion, selectedPackageSpec), selectedWrapperPath),
        { outputPath: selectedOutputPath, selectedPackageSpec, selectedVersion }
      )
    : undefined;
  const selectedAlreadyAdded = Boolean(
    selectedPackageSpec && addedTools.some((tool) => dependencyKey(tool.selectedPackageSpec || tool.packageSpec) === dependencyKey(selectedPackageSpec))
  );
  const selectedPackageLocked = packageSpecLocked(selectedPackageSpec);
  const missingSelectedRuleSpecFields = selected ? missingRuleSpecFields(selected) : [];
  const canSaveSelected = Boolean(
    selected?.targetPlatformSupported === true &&
      selectedPackageLocked &&
      !selectedAlreadyAdded
  );
  const canValidateSelected = Boolean(
    canSaveSelected &&
      missingSelectedRuleSpecFields.length === 0
  );

  function updateQuery(value: string) {
    setQuery(value);
    setSearchPage(1);
  }

  function updateSelectedVersion(id: string, version: string) {
    setVersionOverrides((current) => ({
      ...current,
      [id]: version,
    }));
  }

  function updateSelectedWrapper(id: string, wrapperPath: string) {
    setWrapperOverrides((current) => ({
      ...current,
      [id]: wrapperPath,
    }));
  }

  function updateSelectedOutputPath(id: string, outputPath: string) {
    setOutputPathOverrides((current) => ({
      ...current,
      [id]: outputPath,
    }));
  }

  function editToolRuleTemplate(id: string) {
    setRuleSpecEditError("");
    setEditingRuleSpecToolId(id);
  }

  function selectedToolForSave(): AddedTool | null {
    if (!selected || !canSaveSelected) {
      if (selected?.targetPlatformSupported === false) {
        setToolsError("该工具当前目标平台不可用，不能加入工具库。");
      }
      if (selected && !selectedPackageLocked) {
        setToolsError("请选择一个明确版本后再加入工具。");
      }
      if (selectedAlreadyAdded) {
        setToolsError("该依赖版本已经加入项目。");
        setView("library");
      }
      return null;
    }
    const nextTool = withCuratedRuleTemplate<AddedTool>({
      ...selected,
      selectedVersion,
      selectedPackageSpec,
      packageSpec: selectedPackageSpec,
    });
    const executableTool = buildExecutableRuleSpecForSelectedTool(nextTool, {
      outputPath: selectedOutputPath,
      selectedPackageSpec,
      selectedVersion,
    });
    return draftOnlyWhenActionMissing(executableTool);
  }

  function selectedToolForValidation(): AddedTool | null {
    if (!selected || !canValidateSelected) {
      if (selected && !selectedPackageLocked) {
        setToolsError("请选择一个明确版本后再加入工具。");
      }
      if (selectedAlreadyAdded) {
        setToolsError("该依赖版本已经加入项目。");
        setView("library");
      }
      if (selected && missingSelectedRuleSpecFields.length > 0) {
        setToolsError(formatMissingRuleSpecFields(missingSelectedRuleSpecFields));
      }
      return null;
    }
    const nextTool = withCuratedRuleTemplate<AddedTool>({
      ...selected,
      selectedVersion,
      selectedPackageSpec,
      packageSpec: selectedPackageSpec,
    });
    const executableTool = buildExecutableRuleSpecForSelectedTool(nextTool, {
      outputPath: selectedOutputPath,
      selectedPackageSpec,
      selectedVersion,
    });
    const missing = missingRuleSpecFields(executableTool);
    if (missing.length > 0) {
      setToolsError(formatMissingRuleSpecFields(missing));
      return null;
    }
    return executableTool;
  }

  function addSelectedTool() {
    const nextTool = selectedToolForSave();
    if (!nextTool) return;
    void (async () => {
      setAddingSelectedTool(true);
      setCheckingToolId(nextTool.id);
      setToolsError("");
      try {
        await addToolDependency(nextTool);
        await loadAddedTools({ forceRefresh: true, silent: true });
        setView("library");
      } catch (err) {
        setToolsError(toolErrorMessage(err, "加入工具失败"));
      } finally {
        setAddingSelectedTool(false);
        setCheckingToolId("");
      }
    })();
  }

  function addAndCheckSelectedTool() {
    const nextTool = selectedToolForValidation();
    if (!nextTool) return;
    void (async () => {
      setAddingSelectedTool(true);
      setCheckingToolId(nextTool.id);
      setToolsError("");
      try {
        await prepareToolDependency(nextTool);
        await loadAddedTools({ forceRefresh: true, silent: true });
        setView("library");
      } catch (err) {
        setToolsError(toolErrorMessage(err, "加入并验证工具失败"));
        await loadAddedTools({ forceRefresh: true, silent: true });
      } finally {
        setAddingSelectedTool(false);
        setCheckingToolId("");
      }
    })();
  }

  function removeAddedTool(id: string) {
    void (async () => {
      setToolsError("");
      try {
        await removeToolDependency(id);
        await loadAddedTools({ forceRefresh: true, silent: true });
      } catch (err) {
        setToolsError(toolErrorMessage(err, "移除工具失败"));
      }
    })();
  }

  function saveToolRuleTemplate(id: string, ruleTemplate: RuleSpecTemplate) {
    void (async () => {
      setRuleSpecSavingId(id);
      setRuleSpecEditError("");
      try {
        await updateToolRuleTemplate(id, ruleTemplate);
        await loadAddedTools({ forceRefresh: true, silent: true });
        setEditingRuleSpecToolId("");
      } catch (err) {
        setRuleSpecEditError(toolErrorMessage(err, "保存 RuleSpec 失败"));
      } finally {
        setRuleSpecSavingId("");
      }
    })();
  }

  function checkTool(id: string) {
    void (async () => {
      setCheckingToolId(id);
      setToolsError("");
      try {
        await checkToolDependency(id);
        await loadAddedTools({ forceRefresh: true, silent: true });
      } catch (err) {
        setToolsError(toolErrorMessage(err, "验证工具失败"));
      } finally {
        setCheckingToolId("");
      }
    })();
  }

  return {
    addedTools,
    addingSelectedTool,
    canSaveSelected,
    canValidateSelected,
    checkingToolId,
    editingRuleSpecToolId,
    error,
    filtered,
    loading,
    missingSelectedRuleSpecFields,
    query,
    searchComplete,
    searchHasMore,
    searchPage,
    searchTotal,
    selected,
    selectedAlreadyAdded,
    selectedId,
    selectedOutputPath,
    selectedPackageSpec,
    selectedPackageLocked,
    selectedVersion,
    selectedWrapperPath,
    setSearchPage,
    setSelectedId,
    setSource,
    setView,
    source,
    toolsError,
    toolsLoading,
    ruleSpecEditError,
    ruleSpecSavingId,
    updateQuery,
    updateSelectedOutputPath,
    updateSelectedVersion,
    updateSelectedWrapper,
    view,
    addAndCheckSelectedTool,
    addSelectedTool,
    loadAddedTools: () => loadAddedTools({ forceRefresh: true, silent: addedTools.length > 0 }),
    openToolSourceUrl,
    removeAddedTool,
    checkTool,
    editToolRuleTemplate,
    saveToolRuleTemplate,
    setEditingRuleSpecToolId,
  };
}

function formatMissingRuleSpecFields(fields: string[]) {
  return `还不能加入流程：\n- ${fields.join("\n- ")}`;
}

function draftOnlyWhenActionMissing(tool: AddedTool): AddedTool {
  const missing = missingRuleSpecFields(tool);
  if (!missing.includes("缺少执行动作") && !missing.includes("执行动作冲突")) {
    return tool;
  }
  const packageSpec = tool.selectedPackageSpec || tool.packageSpec;
  const draft = tool.ruleSpecDraft || {
    source: "conda-package",
    notes: ["补全 RuleSpec 后再验证发布。"],
  };
  return {
    ...tool,
    ruleTemplate: {},
    ruleSpecDraft: {
      ...draft,
      status: draft.status || "needs-user-completion",
      requiresUserCompletion: true,
      lock: {
        ...(draft.lock || {}),
        packageSpec,
        version: tool.selectedVersion || tool.version || "",
        source: tool.source,
      },
      ruleTemplate: tool.ruleTemplate,
    },
  };
}
