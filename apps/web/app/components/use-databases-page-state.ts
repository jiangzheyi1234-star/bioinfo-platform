import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  browseRemoteFiles,
  checkDatabaseAvailability,
  createDatabase,
  deleteDatabase,
  fetchDatabases,
  fetchDatabasePacks,
  fetchDatabaseTemplates,
  getCachedDatabases,
  getCachedDatabasePacks,
  getCachedDatabaseTemplates,
  updateDatabaseRecord,
} from "./database-page-api";
import {
  candidateDetailFromError,
  databaseErrorMessage,
  editForm,
  emptyForm,
  groupedDatabaseTemplates,
  remoteBrowserErrorMessage,
  type DatabaseCandidateDetail,
  type DatabaseItem,
  type DatabasePack,
  type DatabaseTemplate,
  type PathSelectionMode,
  type RemoteFileItem,
} from "./database-page-model";
import {
  compositeFieldEntries,
  compositeFallbackPath,
  compositeInputFields,
  defaultDatabaseName,
} from "./database-path-utils";

type DatabaseForm = ReturnType<typeof emptyForm>;
type DatabaseEditForm = ReturnType<typeof editForm>;

export type DatabasesPageState = {
  templates: DatabaseTemplate[];
  packs: DatabasePack[];
  items: DatabaseItem[];
  loading: boolean;
  error: string;
  templateError: string;
  packError: string;
  templateLoading: boolean;
  packLoading: boolean;
  adding: boolean;
  saving: boolean;
  checkingId: string;
  form: DatabaseForm;
  selectionMode: PathSelectionMode;
  compositeFields: Record<string, string>;
  activeCompositeField: string;
  editingItem: DatabaseItem | null;
  editValues: DatabaseEditForm;
  detailsItem: DatabaseItem | null;
  candidateDetail: DatabaseCandidateDetail | null;
  updatingId: string;
  browserOpen: boolean;
  browserPath: string;
  browserItems: RemoteFileItem[];
  browserParentPath: string;
  browserLoading: boolean;
  browserLoadingMore: boolean;
  browserError: string;
  browserTruncated: boolean;
  browserTotal: number | null;
  browserListRef: React.RefObject<HTMLDivElement | null>;
  templateById: Record<string, DatabaseTemplate>;
  templateGroups: ReturnType<typeof groupedDatabaseTemplates>;
  selectedTemplate: DatabaseTemplate | null;
  canSubmitDatabase: boolean;
  loadRemotePath: (path: string, options?: { append?: boolean }) => Promise<void>;
  handleBrowserScroll: () => void;
  updateForm: (key: keyof DatabaseForm, value: string) => void;
  updateCompositeField: (key: string, value: string) => void;
  editManualPath: (value: string) => void;
  selectBrowserPath: (path: string) => void;
  selectBrowserPathForCompositeField: (key: string, path: string) => void;
  selectTemplate: (templateId: string) => void;
  startAddingFromPack: (packId: string) => void;
  setSelectionMode: (mode: PathSelectionMode) => void;
  setActiveCompositeField: (field: string) => void;
  submitDatabase: (selectedEntryPath?: string) => Promise<void>;
  addDatabase: () => Promise<void>;
  checkDatabase: (id: string) => Promise<void>;
  openEditDatabase: (item: DatabaseItem) => void;
  updateEditValue: (field: keyof DatabaseEditForm, value: string) => void;
  updateDatabase: () => Promise<void>;
  copyDatabasePath: (path: string) => Promise<void>;
  copyDatabaseText: (text: string) => Promise<void>;
  removeDatabase: (id: string) => Promise<void>;
  startAdding: () => void;
  cancelAdding: () => void;
  closeEditDialog: () => void;
  setDetailsItem: (item: DatabaseItem | null) => void;
  setCandidateDetail: (detail: DatabaseCandidateDetail | null) => void;
};

function templateByIdUtil(templates: DatabaseTemplate[]) {
  return Object.fromEntries(templates.map((template) => [template.id, template]));
}

export function useDatabasesPageState(): DatabasesPageState {
  const [initialCachedItems] = useState(() => getCachedDatabases());
  const [initialCachedTemplates] = useState(() => getCachedDatabaseTemplates());
  const [initialCachedPacks] = useState(() => getCachedDatabasePacks());
  const [templates, setTemplates] = useState<DatabaseTemplate[]>(() => initialCachedTemplates || []);
  const [packs, setPacks] = useState<DatabasePack[]>(() => initialCachedPacks || []);
  const [items, setItems] = useState<DatabaseItem[]>(() => initialCachedItems || []);
  const itemsRef = useRef<DatabaseItem[]>(initialCachedItems || []);
  const templatesRef = useRef<DatabaseTemplate[]>(initialCachedTemplates || []);
  const packsRef = useRef<DatabasePack[]>(initialCachedPacks || []);
  const [loading, setLoading] = useState(() => !initialCachedItems);
  const [error, setError] = useState("");
  const [templateError, setTemplateError] = useState("");
  const [packError, setPackError] = useState("");
  const [templateLoading, setTemplateLoading] = useState(() => !initialCachedTemplates);
  const [packLoading, setPackLoading] = useState(() => !initialCachedPacks);
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [checkingId, setCheckingId] = useState("");
  const [form, setForm] = useState<DatabaseForm>(emptyForm());
  const [selectionMode, setSelectionMode] = useState<PathSelectionMode>("none");
  const [compositeFields, setCompositeFields] = useState<Record<string, string>>({});
  const [activeCompositeField, setActiveCompositeField] = useState("");
  const [editingItem, setEditingItem] = useState<DatabaseItem | null>(null);
  const [editValues, setEditValues] = useState<DatabaseEditForm>(editForm());
  const [detailsItem, setDetailsItem] = useState<DatabaseItem | null>(null);
  const [candidateDetail, setCandidateDetail] = useState<DatabaseCandidateDetail | null>(null);
  const [updatingId, setUpdatingId] = useState("");
  const [browserOpen, setBrowserOpen] = useState(false);
  const [browserPath, setBrowserPath] = useState("~");
  const [browserItems, setBrowserItems] = useState<RemoteFileItem[]>([]);
  const [browserParentPath, setBrowserParentPath] = useState("");
  const [browserLoading, setBrowserLoading] = useState(false);
  const [browserLoadingMore, setBrowserLoadingMore] = useState(false);
  const [browserError, setBrowserError] = useState("");
  const [browserTruncated, setBrowserTruncated] = useState(false);
  const [browserTotal, setBrowserTotal] = useState<number | null>(null);
  const [browserNextOffset, setBrowserNextOffset] = useState<number | null>(null);
  const browserListRef = useRef<HTMLDivElement | null>(null);
  const browserScrollByPathRef = useRef<Record<string, number>>({});

  const templateById = useMemo(() => templateByIdUtil(templates), [templates]);
  const templateGroups = useMemo(() => groupedDatabaseTemplates(templates), [templates]);
  const selectedTemplate = useMemo(
    () => templateById[form.templateId] || templates[0] || null,
    [form.templateId, templateById, templates]
  );

  const isCompositeTemplate = selectedTemplate?.selectorKind === "composite";
  const compositeReady = useMemo(
    () =>
      Boolean(
        selectedTemplate &&
          isCompositeTemplate &&
          compositeFieldEntries(selectedTemplate).every(([key, field]) => field.required === false || Boolean(compositeFields[key]?.trim()))
      ),
    [compositeFields, isCompositeTemplate, selectedTemplate]
  );
  const canSubmitDatabase = Boolean(selectedTemplate && (isCompositeTemplate ? compositeReady : form.path.trim()));

  const loadDatabases = useCallback(async (options: { forceRefresh?: boolean; silent?: boolean } = {}) => {
    const showLoading = !options.silent && itemsRef.current.length === 0;
    if (showLoading) {
      setLoading(true);
    }
    setError("");
    try {
      const nextItems = await fetchDatabases({ forceRefresh: options.forceRefresh });
      itemsRef.current = nextItems;
      setItems(nextItems);
    } catch (err) {
      setError(databaseErrorMessage(err, "读取数据库列表失败"));
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  }, []);

  const loadDatabaseTemplates = useCallback(async (options: { forceRefresh?: boolean; silent?: boolean } = {}) => {
    const showLoading = !options.silent && templatesRef.current.length === 0;
    if (showLoading) {
      setTemplateLoading(true);
    }
    setTemplateError("");
    try {
      const nextTemplates = await fetchDatabaseTemplates({ forceRefresh: options.forceRefresh });
      if (nextTemplates.length === 0) {
        throw new Error("远端未返回数据库模板。");
      }
      templatesRef.current = nextTemplates;
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
      if (templatesRef.current.length === 0) {
        setTemplates([]);
      }
      setTemplateError(databaseErrorMessage(err, "读取数据库模板失败"));
    } finally {
      if (showLoading) {
        setTemplateLoading(false);
      }
    }
  }, []);

  const loadDatabasePacks = useCallback(async (options: { forceRefresh?: boolean; silent?: boolean } = {}) => {
    const showLoading = !options.silent && packsRef.current.length === 0;
    if (showLoading) {
      setPackLoading(true);
    }
    setPackError("");
    try {
      const nextPacks = await fetchDatabasePacks({ forceRefresh: options.forceRefresh });
      packsRef.current = nextPacks;
      setPacks(nextPacks);
    } catch (err) {
      if (packsRef.current.length === 0) {
        setPacks([]);
      }
      setPackError(databaseErrorMessage(err, "读取数据库包失败"));
    } finally {
      if (showLoading) {
        setPackLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadDatabases({ silent: Boolean(initialCachedItems) });
    void loadDatabaseTemplates({ silent: Boolean(initialCachedTemplates) });
    void loadDatabasePacks({ silent: Boolean(initialCachedPacks) });
  }, [
    initialCachedItems,
    initialCachedPacks,
    initialCachedTemplates,
    loadDatabasePacks,
    loadDatabases,
    loadDatabaseTemplates,
  ]);

  const updateForm = useCallback((key: keyof DatabaseForm, value: string) => {
    setForm((current) => ({ ...current, [key]: value }));
  }, []);

  const updateCompositeField = useCallback((key: string, value: string) => {
    setCompositeFields((current) => ({ ...current, [key]: value }));
    setError("");
  }, []);

  const editManualPath = useCallback((value: string) => {
    setSelectionMode(value.trim() ? "manual" : "none");
    setError("");
    updateForm("path", value);
  }, [updateForm]);

  const selectBrowserPath = useCallback((path: string) => {
    setSelectionMode(path.trim() ? "browser" : "none");
    setError("");
    updateForm("path", path);
  }, [updateForm]);

  const selectBrowserPathForCompositeField = useCallback((key: string, path: string) => {
    setSelectionMode(path.trim() ? "browser" : "none");
    setError("");
    updateCompositeField(key, path);
  }, [updateCompositeField]);

  const rememberBrowserScroll = useCallback(() => {
    const node = browserListRef.current;
    if (!node || !browserPath) {
      return;
    }
    browserScrollByPathRef.current[browserPath] = node.scrollTop;
  }, [browserPath]);

  const loadRemotePath = useCallback(
    async (path: string, options: { append?: boolean } = {}) => {
      const append = Boolean(options.append);
      if (!append) {
        rememberBrowserScroll();
      }
      const nextPath = path.trim() || "~";
      const offset = append ? (browserNextOffset ?? browserItems.length) : 0;
      setBrowserOpen(true);
      if (append) {
        setBrowserLoadingMore(true);
      } else {
        setBrowserLoading(true);
      }
      setBrowserError("");
      try {
        const data = await browseRemoteFiles({ path: nextPath, offset });
        setBrowserPath(data.path);
        setBrowserParentPath(data.parentPath);
        setBrowserItems((current) => (append ? [...current, ...(data.items || [])] : data.items || []));
        setBrowserTruncated(Boolean(data.truncated));
        setBrowserTotal(typeof data.total === "number" ? data.total : null);
        setBrowserNextOffset(typeof data.nextOffset === "number" ? data.nextOffset : null);
      } catch (err) {
        if (!append) {
          setBrowserItems([]);
          setBrowserTotal(null);
          setBrowserNextOffset(null);
        }
        setBrowserTruncated(false);
        setBrowserError(remoteBrowserErrorMessage(err));
      } finally {
        setBrowserLoading(false);
        setBrowserLoadingMore(false);
      }
    },
    [browserItems.length, browserNextOffset, rememberBrowserScroll]
  );

  useEffect(() => {
    const node = browserListRef.current;
    if (!node || browserLoading) {
      return;
    }
    node.scrollTop = browserScrollByPathRef.current[browserPath] || 0;
  }, [browserPath, browserItems, browserLoading]);

  const handleBrowserScroll = useCallback(() => {
    const node = browserListRef.current;
    if (!node || !browserTruncated || browserLoading || browserLoadingMore) {
      return;
    }
    const distanceToBottom = node.scrollHeight - node.scrollTop - node.clientHeight;
    if (distanceToBottom < 48) {
      void loadRemotePath(browserPath, { append: true });
    }
  }, [browserLoading, browserLoadingMore, browserPath, browserTruncated, loadRemotePath]);

  const selectTemplate = useCallback(
    (templateId: string) => {
      const template = templateById[templateId];
      if (!template) {
        setError("数据库模板不可用，请刷新模板后重试。");
        return;
      }
      setForm((current) => ({
        ...current,
        templateId: template.id,
        type: template.type,
        databaseLayer: "user_manual",
        packId: "",
        description: current.description || template.description,
        path: "",
      }));
      setCompositeFields(Object.fromEntries(compositeFieldEntries(template).map(([key]) => [key, ""])));
      setActiveCompositeField(compositeFieldEntries(template)[0]?.[0] || "");
      setSelectionMode("none");
      setError("");
    },
    [templateById]
  );

  const startAddingFromPack = useCallback(
    (packId: string) => {
      const pack = packsRef.current.find((item) => item.packId === packId);
      const template = pack ? templateById[pack.templateId] : null;
      if (!pack || !template) {
        setPackError("数据库包对应的模板不可用，请刷新后重试。");
        return;
      }
      setForm({
        ...emptyForm(template),
        name: pack.name,
        templateId: template.id,
        type: pack.type,
        version: pack.version,
        databaseLayer: pack.installedLayer,
        packId: pack.packId,
        description: `${pack.name} installed manually from ${pack.packId}.`,
        sourceUrl: pack.sourceUrl,
        buildCommand: pack.registrationHandoff.scriptPath,
        dbParams: pack.registrationHandoff.defaultRemoteRoot,
        expectedFiles: pack.expectedFiles.join(", "),
      });
      setCompositeFields(Object.fromEntries(compositeFieldEntries(template).map(([key]) => [key, ""])));
      setActiveCompositeField(compositeFieldEntries(template)[0]?.[0] || "");
      setSelectionMode("none");
      setCandidateDetail(null);
      setError("");
      setPackError("");
      setAdding(true);
    },
    [templateById]
  );

  const submitDatabase = useCallback(
    async (selectedEntryPath = "") => {
      if (!selectedTemplate) {
        setError("数据库模板未加载，不能添加数据库。");
        return;
      }
      const isComposite = selectedTemplate.selectorKind === "composite";
      const compositeFieldValues = compositeInputFields(selectedTemplate, compositeFields);
      const path = isComposite ? compositeFallbackPath(compositeFieldValues) : form.path.trim();
      if (!path) {
        setError("远程路径不能为空");
        return;
      }
      if (isComposite && compositeFieldEntries(selectedTemplate).some(([key, field]) => field.required !== false && !compositeFieldValues[key])) {
        setError("请填写所有必需的复合数据库路径。");
        return;
      }
      const name = form.name.trim() || defaultDatabaseName(selectedTemplate, path);
      const metadataInput = isComposite ? { kind: "multi" as const, fields: compositeInputFields(selectedTemplate, compositeFields) } : undefined;
      const selectedPack = form.packId ? packsRef.current.find((item) => item.packId === form.packId) : null;
      const databaseLayer = selectedPack?.installedLayer || form.databaseLayer || "user_manual";
      setSaving(true);
      setError("");
      try {
        const database = await createDatabase({
          name,
          templateId: form.templateId,
          type: form.type,
          version: form.version.trim(),
          path,
          description: form.description.trim(),
          manifestPath: form.manifestPath.trim(),
          source: selectedPack?.sourceUrl || "manual",
          databaseLayer,
          ...(selectedEntryPath ? { selectedEntryPath } : {}),
          ...(selectedPack ? { sizeBytes: selectedPack.archiveSizeBytes, checksum: selectedPack.checksum } : {}),
          metadata: {
            templateId: form.templateId,
            databaseLayer,
            ...(selectedEntryPath ? { selectedEntryPath } : {}),
            ...(metadataInput ? { input: metadataInput } : {}),
            ...(selectedPack
              ? {
                  packId: selectedPack.packId,
                  installedFromPackId: selectedPack.packId,
                  packVersion: selectedPack.version,
                  packSourceUrl: selectedPack.sourceUrl,
                  packChecksum: selectedPack.checksum,
                  packArchiveSizeBytes: selectedPack.archiveSizeBytes,
                  installationMethod: "manual_external" as const,
                }
              : {}),
            sourceUrl: form.sourceUrl.trim(),
            buildCommand: form.buildCommand.trim(),
            dbParams: form.dbParams.trim(),
            expectedFiles: form.expectedFiles
              .split(",")
              .map((value) => value.trim())
              .filter(Boolean),
          },
        });
        if (database.status !== "available") {
          throw new Error(database.message || "数据库添加接口未返回可用状态。");
        }
        setItems((current) => {
          const nextItems = [database, ...current.filter((item) => item.id !== database.id)];
          itemsRef.current = nextItems;
          return nextItems;
        });
        setForm(emptyForm(templates[0]));
        setCompositeFields({});
        setActiveCompositeField("");
        setSelectionMode("none");
        setCandidateDetail(null);
        setAdding(false);
      } catch (err) {
        const detail = candidateDetailFromError(err);
        if (detail) {
          setCandidateDetail(detail);
          setError("");
        } else {
          setError(databaseErrorMessage(err, "添加数据库失败"));
        }
      } finally {
        setSaving(false);
      }
    },
    [compositeFields, form, selectedTemplate, templates]
  );

  const addDatabase = useCallback(async () => {
    await submitDatabase();
  }, [submitDatabase]);

  const checkDatabase = useCallback(async (id: string) => {
    setCheckingId(id);
    setError("");
    try {
      const database = await checkDatabaseAvailability(id);
      setItems((current) => {
        const nextItems = current.map((item) => (item.id === id ? database : item));
        itemsRef.current = nextItems;
        return nextItems;
      });
    } catch (err) {
      setError(databaseErrorMessage(err, "校验数据库失败"));
    } finally {
      setCheckingId("");
    }
  }, []);

  const openEditDatabase = useCallback((item: DatabaseItem) => {
    setEditingItem(item);
    setEditValues(editForm(item));
    setError("");
  }, []);

  const updateEditValue = useCallback((field: keyof DatabaseEditForm, value: string) => {
    setEditValues((current) => ({ ...current, [field]: value }));
  }, []);

  const updateDatabase = useCallback(async () => {
    if (!editingItem) {
      return;
    }
    const name = editValues.name.trim();
    if (!name) {
      setError("数据库名称不能为空");
      return;
    }
    setUpdatingId(editingItem.id);
    setError("");
    try {
      const database = await updateDatabaseRecord(editingItem.id, {
        name,
        version: editValues.version.trim(),
        description: editValues.description.trim(),
      });
      setItems((current) => {
        const nextItems = current.map((item) => (item.id === editingItem.id ? database : item));
        itemsRef.current = nextItems;
        return nextItems;
      });
      setEditingItem(null);
      setEditValues(editForm());
    } catch (err) {
      setError(databaseErrorMessage(err, "更新数据库失败"));
    } finally {
      setUpdatingId("");
    }
  }, [editValues, editingItem]);

  const copyDatabasePath = useCallback(async (path: string) => {
    if (!path) {
      return;
    }
    try {
      await navigator.clipboard.writeText(path);
    } catch (err) {
      setError(databaseErrorMessage(err, "复制路径失败"));
    }
  }, []);

  const copyDatabaseText = useCallback(async (text: string) => {
    if (!text) {
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
    } catch (err) {
      setError(databaseErrorMessage(err, "复制内容失败"));
    }
  }, []);

  const removeDatabase = useCallback(async (id: string) => {
    setError("");
    try {
      await deleteDatabase(id);
      setItems((current) => {
        const nextItems = current.filter((item) => item.id !== id);
        itemsRef.current = nextItems;
        return nextItems;
      });
    } catch (err) {
      setError(databaseErrorMessage(err, "移除数据库失败"));
    }
  }, []);

  const startAdding = useCallback(() => {
    setError("");
    setSelectionMode("none");
    setAdding(true);
  }, []);

  const cancelAdding = useCallback(() => {
    setError("");
    setAdding(false);
    setSelectionMode("none");
  }, []);

  const closeEditDialog = useCallback(() => setEditingItem(null), []);

  return {
    templates,
    packs,
    items,
    loading,
    error,
    templateError,
    packError,
    templateLoading,
    packLoading,
    adding,
    saving,
    checkingId,
    form,
    selectionMode,
    compositeFields,
    activeCompositeField,
    editingItem,
    editValues,
    detailsItem,
    candidateDetail,
    updatingId,
    browserOpen,
    browserPath,
    browserItems,
    browserParentPath,
    browserLoading,
    browserLoadingMore,
    browserError,
    browserTruncated,
    browserTotal,
    browserListRef,
    templateById,
    templateGroups,
    selectedTemplate,
    canSubmitDatabase,
    loadRemotePath,
    handleBrowserScroll,
    updateForm,
    updateCompositeField,
    editManualPath,
    selectBrowserPath,
    selectBrowserPathForCompositeField,
    setSelectionMode,
    setActiveCompositeField,
    selectTemplate,
    startAddingFromPack,
    submitDatabase,
    addDatabase,
    checkDatabase,
    openEditDatabase,
    updateEditValue,
    updateDatabase,
    copyDatabasePath,
    copyDatabaseText,
    removeDatabase,
    startAdding,
    cancelAdding,
    closeEditDialog,
    setDetailsItem,
    setCandidateDetail,
  };
}
