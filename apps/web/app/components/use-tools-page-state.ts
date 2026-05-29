"use client";

import { useEffect, useMemo, useState } from "react";

import {
  addToolDependency,
  fetchAddedTools,
  openToolSourceUrl,
  removeToolDependency,
  searchToolCapabilities,
  updateToolRuleTemplate,
} from "./tools-page-api";
import {
  type AddedTool,
  type RuleSpecTemplate,
  type ToolSearchItem,
  applySelectedPackageLock,
  dependencyKey,
  searchErrorMessage,
  toolErrorMessage,
} from "./tools-page-model";

export function useToolsPageState() {
  const [view, setView] = useState<"library" | "search">("library");
  const [addedTools, setAddedTools] = useState<AddedTool[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);
  const [toolsError, setToolsError] = useState("");
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("all");
  const [items, setItems] = useState<ToolSearchItem[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [versionOverrides, setVersionOverrides] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searchPage, setSearchPage] = useState(1);
  const [searchTotal, setSearchTotal] = useState(0);
  const [searchHasMore, setSearchHasMore] = useState(false);
  const [searchComplete, setSearchComplete] = useState(true);
  const [editingRuleSpecToolId, setEditingRuleSpecToolId] = useState("");
  const [ruleSpecSavingId, setRuleSpecSavingId] = useState("");
  const [ruleSpecEditError, setRuleSpecEditError] = useState("");

  async function loadAddedTools() {
    setToolsLoading(true);
    setToolsError("");
    try {
      setAddedTools(await fetchAddedTools());
    } catch (err) {
      setAddedTools([]);
      setToolsError(toolErrorMessage(err, "读取工具列表失败"));
    } finally {
      setToolsLoading(false);
    }
  }

  useEffect(() => {
    void loadAddedTools();
  }, []);

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
  const selected = baseSelected ? applySelectedPackageLock(baseSelected, selectedVersion, selectedPackageSpec) : undefined;
  const selectedAlreadyAdded = Boolean(
    selectedPackageSpec && addedTools.some((tool) => dependencyKey(tool.selectedPackageSpec || tool.packageSpec) === dependencyKey(selectedPackageSpec))
  );
  const canAddSelected = selected?.targetPlatformSupported === true && !selectedAlreadyAdded;

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

  function editToolRuleTemplate(id: string) {
    setRuleSpecEditError("");
    setEditingRuleSpecToolId(id);
  }

  function addSelectedTool() {
    if (!selected || !canAddSelected) {
      if (selectedAlreadyAdded) {
        setToolsError("该依赖版本已经加入项目。");
        setView("library");
      }
      return;
    }
    const nextTool: AddedTool = {
      ...selected,
      selectedVersion,
      selectedPackageSpec,
      packageSpec: selectedPackageSpec,
    };
    void (async () => {
      setToolsError("");
      try {
        await addToolDependency(nextTool);
        await loadAddedTools();
        setView("library");
      } catch (err) {
        setToolsError(toolErrorMessage(err, "加入工具失败"));
      }
    })();
  }

  function removeAddedTool(id: string) {
    void (async () => {
      setToolsError("");
      try {
        await removeToolDependency(id);
        await loadAddedTools();
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
        await loadAddedTools();
        setEditingRuleSpecToolId("");
      } catch (err) {
        setRuleSpecEditError(toolErrorMessage(err, "保存 RuleSpec 失败"));
      } finally {
        setRuleSpecSavingId("");
      }
    })();
  }

  return {
    addedTools,
    canAddSelected,
    editingRuleSpecToolId,
    error,
    filtered,
    loading,
    query,
    searchComplete,
    searchHasMore,
    searchPage,
    searchTotal,
    selected,
    selectedAlreadyAdded,
    selectedId,
    selectedPackageSpec,
    selectedVersion,
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
    updateSelectedVersion,
    view,
    addSelectedTool,
    loadAddedTools,
    openToolSourceUrl,
    removeAddedTool,
    editToolRuleTemplate,
    saveToolRuleTemplate,
    setEditingRuleSpecToolId,
  };
}
