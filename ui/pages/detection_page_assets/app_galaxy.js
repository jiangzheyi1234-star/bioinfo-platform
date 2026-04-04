let bridge = null;
let allTools = [];
let selectedToolId = null;
let selectedDescriptor = null;
let integratedWorkbench = null;
let integratedWorkbenchHydrated = false;
let selectedIntegratedFeatureId = null;
let pendingIntegratedFeatureId = null;
let databaseResources = [];
let historyRecords = [];
let pendingHistoryExecutionId = null;
let pendingHistoryExecutionOptions = null;
let pendingIntegratedViewSource = '';
let selectedIntegratedViewSource = 'workflow';
let activeIntegratedProjectId = '';
const integratedExecutionViews = {};
if (!window.IntegratedOpenResultsState || typeof window.IntegratedOpenResultsState.createStore !== 'function') {
    throw new Error('IntegratedOpenResultsState module is required for history multi-result workbench');
}
if (!window.BridgeToolsService || !window.BridgeHistoryService || !window.BridgeResultsService) {
    throw new Error('Bridge service modules are required for detection page bootstrapping');
}
if (!window.DetectionPageUiFeedback || !window.DatabasePanelRenderer || !window.HistoryPanelRenderer || !window.HistoryStatusRenderer || !window.IntegratedSidebarRenderer || !window.ResultViewerRenderers) {
    throw new Error('Render modules are required for detection page bootstrapping');
}
if (!window.HistoryResultLoader || !window.IntegratedWorkbenchSelection || !window.IntegratedWorkbenchStateManager) {
    throw new Error('Result workbench modules are required for detection page bootstrapping');
}
if (!window.IntegratedRunModal || !window.IntegratedChartRenderer) {
    throw new Error('Integrated modal/chart renderer modules are required for detection page bootstrapping');
}
if (!window.DetectionPageHelpers) {
    throw new Error('DetectionPageHelpers module is required for detection page bootstrapping');
}
if (!window.ToolPanelRenderer) {
    throw new Error('ToolPanelRenderer module is required for detection page bootstrapping');
}
if (!window.IntegratedWorkbenchRenderer) {
    throw new Error('IntegratedWorkbenchRenderer module is required for detection page bootstrapping');
}
const INTEGRATED_HISTORY_RESULT_LIMIT = window.IntegratedOpenResultsState.DEFAULT_MAX_OPEN_RESULTS;
const integratedOpenResultsStore = window.IntegratedOpenResultsState.createStore({
    maxOpenResults: INTEGRATED_HISTORY_RESULT_LIMIT,
});
const bridgeToolsService = window.BridgeToolsService.createBridgeToolsService({
    getBridge: function() { return bridge; },
});
const bridgeHistoryService = window.BridgeHistoryService.createBridgeHistoryService({
    getBridge: function() { return bridge; },
});
const bridgeResultsService = window.BridgeResultsService.createBridgeResultsService({
    getBridge: function() { return bridge; },
});
const toolDescriptorCache = {};
let integratedRunModalContext = null;
let _integratedChartRetryTimer = null;
let _echartsLoadRequested = false;
const remoteStatusLoading = new Set();
let historyRefreshRequestId = 0;
const HISTORY_REFRESH_MIN_LOADING_MS = 450;
let historyRefreshLoadingStartedAt = 0;
let historyRefreshLoadingTimer = null;
const WORKSPACE_MAIN_VIEW_STORAGE_KEY = 'detection.workspace.main_view.v1';
const WORKSPACE_RUN_PANEL_STORAGE_KEY = 'detection.workspace.run_panel.v1';
const HISTORY_STATUS_FILTER_STORAGE_KEY = 'detection.workspace.history.status_filter.v1';
let workspaceMainView = 'tools';
let workspaceRunPanelExpanded = false;
let workspaceLayoutInitialized = false;
let historyStatusFilter = 'all';
let activeHistoryExecutionId = '';
const DETECTION_WORKFLOW_TOOL_IDS = [
    'unknown_sample_detection',
    'wastewater_metagenomics_basic',
    'animal_metagenomics_basic',
];
console.log('=== Galaxy Style Detection Page ===');

const showNotice = window.DetectionPageUiFeedback.showNotice;
const bindHelpTooltipInteractions = window.DetectionPageUiFeedback.bindHelpTooltipInteractions;

function setHistoryRefreshLoading(loading) {
    const refreshBtn = document.getElementById('btn-refresh');
    if (!refreshBtn) {
        return;
    }

    refreshBtn.disabled = Boolean(loading);
    refreshBtn.classList.toggle('is-loading', Boolean(loading));
    refreshBtn.setAttribute('aria-busy', loading ? 'true' : 'false');
}

function beginHistoryRefreshLoading() {
    historyRefreshLoadingStartedAt = Date.now();
    if (historyRefreshLoadingTimer != null) {
        clearTimeout(historyRefreshLoadingTimer);
        historyRefreshLoadingTimer = null;
    }
    setHistoryRefreshLoading(true);
}

function completeHistoryRefreshLoading(requestId) {
    if (requestId !== historyRefreshRequestId) {
        return;
    }
    const elapsed = Math.max(0, Date.now() - historyRefreshLoadingStartedAt);
    const remainMs = Math.max(0, HISTORY_REFRESH_MIN_LOADING_MS - elapsed);
    if (historyRefreshLoadingTimer != null) {
        clearTimeout(historyRefreshLoadingTimer);
        historyRefreshLoadingTimer = null;
    }
    if (remainMs <= 0) {
        setHistoryRefreshLoading(false);
        return;
    }
    historyRefreshLoadingTimer = setTimeout(function() {
        historyRefreshLoadingTimer = null;
        if (requestId === historyRefreshRequestId) {
            setHistoryRefreshLoading(false);
        }
    }, remainMs);
}

function parseHistoryRecordsPayload(json) {
    const parsed = typeof json === 'string' ? JSON.parse(json) : json;
    if (!Array.isArray(parsed)) {
        throw new Error('执行历史返回格式错误（预期数组）');
    }
    return parsed;
}

function renderLinearIcons(root) {
    if (!window.LinearIconRenderer || typeof window.LinearIconRenderer.renderDataIcons !== 'function') {
        console.error('LinearIconRenderer module is unavailable');
        return;
    }
    window.LinearIconRenderer.renderDataIcons(root || document);
}

function setHidden(element, hidden) {
    if (!element) {
        return;
    }
    element.classList.toggle('is-hidden', Boolean(hidden));
}

function requireElement(id) {
    const element = document.getElementById(id);
    if (!element) {
        throw new Error('Missing required workspace element: #' + id);
    }
    return element;
}

function safeReadStorage(key) {
    return window.localStorage.getItem(key);
}

function safeWriteStorage(key, value) {
    window.localStorage.setItem(key, value);
}

function normalizeHistoryStatusFilter(value) {
    return window.HistoryPanelRenderer.normalizeStatusFilter(value);
}

function getHistorySearchQuery() {
    const searchInput = document.getElementById('history-search');
    return String(searchInput ? searchInput.value || '' : '').trim();
}

function getHistoryStatusFilterLabel(filterValue) {
    const labelMap = {
        all: '全部状态',
        running: '运行中',
        failed: '失败',
        completed: '已完成',
    };
    return labelMap[filterValue] || labelMap.all;
}

function buildHistoryEmptyState(query, statusFilter) {
    if (!historyRecords.length) {
        return {
            title: '暂无任务记录',
            description: '新的 Primer Design 或 Multiplex Panel Design 任务会在这里显示。',
        };
    }

    const hasQuery = Boolean(query);
    const hasStatusFilter = statusFilter !== 'all';
    if (!hasQuery && !hasStatusFilter) {
        return {
            title: '暂无任务记录',
            description: '新的 Primer Design 或 Multiplex Panel Design 任务会在这里显示。',
        };
    }

    const statusLabel = getHistoryStatusFilterLabel(statusFilter);
    if (hasQuery && hasStatusFilter) {
        return {
            title: '未找到匹配任务',
            description: `当前筛选：状态「${statusLabel}」+ 关键词「${query}」`,
        };
    }
    if (hasStatusFilter) {
        return {
            title: '当前筛选暂无结果',
            description: `状态筛选：${statusLabel}`,
        };
    }
    return {
        title: '当前搜索暂无结果',
        description: `关键词：${query}`,
    };
}

function setHistoryStatusFilter(nextFilter, options = {}) {
    historyStatusFilter = normalizeHistoryStatusFilter(nextFilter);
    const statusFilterSelect = document.getElementById('history-status-filter');
    if (statusFilterSelect) {
        statusFilterSelect.value = historyStatusFilter;
    }
    if (options.persist !== false) {
        safeWriteStorage(HISTORY_STATUS_FILTER_STORAGE_KEY, historyStatusFilter);
    }
}

function openHistoryExecution(executionId, context = {}) {
    const normalizedId = String(executionId || '').trim();
    if (!normalizedId) {
        throw new Error('openHistoryExecution requires executionId');
    }
    activeHistoryExecutionId = normalizedId;
    window.HistoryResultLoader.openExecutionWithRuntime(normalizedId, context);
}

function renderHistoryRecords() {
    const query = getHistorySearchQuery();
    const sortedHistory = window.HistoryPanelRenderer.sortHistoryRecords(historyRecords);
    const filteredHistory = window.HistoryPanelRenderer.filterHistoryRecords({
        query,
        statusFilter: historyStatusFilter,
        historyRecords: sortedHistory,
        allTools,
    });
    window.HistoryPanelRenderer.renderHistoryPanel({
        container: document.getElementById('history-container'),
        history: filteredHistory,
        allTools,
        pendingExecutionId: pendingHistoryExecutionId,
        pendingOptions: pendingHistoryExecutionOptions || {},
        activeExecutionId: activeHistoryExecutionId,
        emptyState: buildHistoryEmptyState(query, historyStatusFilter),
        escapeHtml,
        resolveHistoryResultContext: function(record) {
            return window.HistoryResultLoader.resolveHistoryResultContext(record);
        },
        onRowExecutionClick: function(record) {
            if (!record || !record.execution_id) {
                return;
            }
            setWorkspaceRunPanelExpanded(true);
            openHistoryExecution(record.execution_id, {
                record: record,
                resultContext: window.HistoryResultLoader.resolveHistoryResultContext(record),
                keepMainView: true,
            });
        },
        openExecution: function(nextExecutionId, context) {
            openHistoryExecution(nextExecutionId, context || {});
        },
        deleteHistoryExecution: function(executionId) {
            return window.HistoryStatusRenderer.deleteHistoryExecution(executionId);
        },
        toggleExecutionRemoteStatus: function(executionId, rowEl) {
            return window.HistoryStatusRenderer.toggleExecutionRemoteStatus(executionId, rowEl);
        },
        showNotice,
        onPendingResolved: function() {
            pendingHistoryExecutionId = null;
            pendingHistoryExecutionOptions = null;
        },
        onPendingMissing: function(executionId) {
            showNotice(`未找到对应任务记录: ${executionId}`);
            if (activeHistoryExecutionId === executionId) {
                activeHistoryExecutionId = '';
            }
            pendingHistoryExecutionId = null;
            pendingHistoryExecutionOptions = null;
        },
    });
}

function initializeHistoryFilterControls() {
    const searchInput = requireElement('history-search');
    const statusFilterSelect = requireElement('history-status-filter');
    const storedFilter = normalizeHistoryStatusFilter(safeReadStorage(HISTORY_STATUS_FILTER_STORAGE_KEY));
    setHistoryStatusFilter(storedFilter, { persist: false });
    searchInput.addEventListener('input', function() {
        renderHistoryRecords();
    });
    statusFilterSelect.addEventListener('change', function(event) {
        setHistoryStatusFilter(event && event.target ? event.target.value : 'all');
        renderHistoryRecords();
    });
}

function setWorkspaceRunPanelExpanded(expanded, options = {}) {
    const panel = requireElement('workspace-run-panel');
    const toggleBtn = requireElement('workspace-run-panel-toggle');
    workspaceRunPanelExpanded = Boolean(expanded);
    panel.classList.toggle('expanded', workspaceRunPanelExpanded);
    panel.classList.toggle('collapsed', !workspaceRunPanelExpanded);
    toggleBtn.setAttribute('aria-expanded', workspaceRunPanelExpanded ? 'true' : 'false');
    toggleBtn.textContent = workspaceRunPanelExpanded ? '收起' : '展开';
    if (options.persist !== false) {
        safeWriteStorage(WORKSPACE_RUN_PANEL_STORAGE_KEY, workspaceRunPanelExpanded ? '1' : '0');
    }
    if (workspaceRunPanelExpanded) {
        if (options.loadWorkbench !== false) {
            loadIntegratedWorkbench();
        }
        setTimeout(function() {
            window.IntegratedChartRenderer.resizeIntegratedCharts();
        }, 80);
    }
}

function switchWorkspaceMainView(view, options = {}) {
    const normalizedView = view === 'history' ? 'history' : 'tools';
    workspaceMainView = normalizedView;
    const toolsView = requireElement('workspace-view-tools');
    const historyView = requireElement('workspace-view-history');
    const toolsBtn = requireElement('workspace-view-tools-btn');
    const historyBtn = requireElement('workspace-view-history-btn');
    toolsView.classList.toggle('active', normalizedView === 'tools');
    historyView.classList.toggle('active', normalizedView === 'history');
    toolsBtn.classList.toggle('active', normalizedView === 'tools');
    historyBtn.classList.toggle('active', normalizedView === 'history');
    toolsBtn.setAttribute('aria-selected', normalizedView === 'tools' ? 'true' : 'false');
    historyBtn.setAttribute('aria-selected', normalizedView === 'history' ? 'true' : 'false');
    if (options.persist !== false) {
        safeWriteStorage(WORKSPACE_MAIN_VIEW_STORAGE_KEY, normalizedView);
    }
    if (normalizedView === 'history' && options.refresh !== false) {
        loadHistory(options.historyOptions || {});
    }
}

function moveWorkspaceTabToMount(tabId, mountId) {
    const tab = requireElement(tabId);
    const mount = requireElement(mountId);
    if (mount.contains(tab)) {
        return;
    }
    mount.appendChild(tab);
    tab.classList.add('workspace-embedded-tab');
}

function initializeDetectionWorkspaceLayout() {
    if (workspaceLayoutInitialized) {
        return;
    }
    workspaceLayoutInitialized = true;
    moveWorkspaceTabToMount('tab-history', 'workspace-history-mount');
    moveWorkspaceTabToMount('tab-integrated', 'workspace-run-panel-body');

    const viewButtons = document.querySelectorAll('.workspace-main-switch-btn[data-workspace-view]');
    viewButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            const nextView = btn.dataset.workspaceView === 'history' ? 'history' : 'tools';
            switchWorkspaceMainView(nextView, {
                refresh: nextView === 'history',
                historyOptions: { source: 'workspace-view-switch' },
            });
        });
    });

    const runPanelToggle = requireElement('workspace-run-panel-toggle');
    runPanelToggle.addEventListener('click', function() {
        setWorkspaceRunPanelExpanded(!workspaceRunPanelExpanded);
    });

    const drawerCloseBtn = document.getElementById('workspace-detail-drawer-close');
    if (drawerCloseBtn) {
        drawerCloseBtn.addEventListener('click', function() {
            const drawer = requireElement('workspace-detail-drawer');
            drawer.classList.add('is-hidden');
            drawer.setAttribute('aria-hidden', 'true');
        });
    }

    const storedView = safeReadStorage(WORKSPACE_MAIN_VIEW_STORAGE_KEY);
    const storedPanel = safeReadStorage(WORKSPACE_RUN_PANEL_STORAGE_KEY);
    switchWorkspaceMainView(storedView === 'history' ? 'history' : 'tools', {
        refresh: storedView === 'history',
        historyOptions: { source: 'workspace-restore' },
    });
    setWorkspaceRunPanelExpanded(storedPanel === '1', { persist: false });
}

renderLinearIcons(document);

// 初始化 QWebChannel
new QWebChannel(qt.webChannelTransport, function(channel) {
    console.log('✓ QWebChannel connected');
    bridge = channel.objects.bridge;

    // 监听 Python 信号
    bridge.tool_selected.connect(function(tool_id) {
        console.log('Tool selected from Python:', tool_id);
    });
    renderLinearIcons(document);
    initializeDetectionWorkspaceLayout();

    // 标签切换
    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            const tab = btn.dataset.tab;
            activateTab(tab);
        });
    });

    // 加载工具列表
    window.ToolPanelRenderer.loadTools();

    // 启动阶段避免重型同步请求阻塞 UI；仅在当前标签是 integrated 时延迟加载
    const activeTabBtn = document.querySelector('.tab-btn.active');
    if (activeTabBtn && activeTabBtn.dataset.tab === 'integrated') {
        setTimeout(function() {
            try {
                loadIntegratedWorkbench();
            } catch (e) {
                console.error('Deferred loadIntegratedWorkbench failed:', e);
            }
        }, 0);
    }

    // 搜索功能
    document.getElementById('search').addEventListener('input', function(e) {
        window.ToolPanelRenderer.renderToolsList(e.target.value);
    });

    // 刷新历史按钮
    document.getElementById('btn-refresh').addEventListener('click', function() {
        loadHistory({ source: 'manual' });
    });
    initializeHistoryFilterControls();
    const clearIntegratedHistoryResultsBtn = document.getElementById('integrated-clear-history-results');
    if (clearIntegratedHistoryResultsBtn) {
        clearIntegratedHistoryResultsBtn.addEventListener('click', function() {
            window.IntegratedWorkbenchStateManager.clearIntegratedTemporaryFeatures({ clearAllUnpinned: true });
            renderIntegratedWorkbench();
        });
    }

    // 运行按钮
    document.getElementById('run-btn').addEventListener('click', function() {
        window.ToolPanelRenderer.runTool();
    });

    // 清空按钮
    document.getElementById('clear-btn').addEventListener('click', function() {
        window.ToolPanelRenderer.clearForm();
    });

    const databaseScanBtn = document.getElementById('database-scan-btn');
    if (databaseScanBtn) {
        databaseScanBtn.addEventListener('click', scanLocalDatabaseFolder);
    }

    // Python 回调：运行结果
    window._onRunResult = function(result) {
        window.ToolPanelRenderer.onRunResult(result);
    };
    const integratedRunBtn = document.getElementById('integrated-run-btn');
    if (integratedRunBtn) {
        integratedRunBtn.addEventListener('click', function() {
            window.IntegratedWorkbenchRenderer.openIntegratedRunEntry();
        });
    }
    window.IntegratedWorkbenchRenderer.initializeIntegratedSectionToggles();
    window.IntegratedWorkbenchRenderer.initializeIntegratedResultTabs();
    bindHelpTooltipInteractions();
});

function switchTab(tab, options = {}) {
    if (tab === 'history') {
        switchTab('tools', options);
        switchWorkspaceMainView('history', {
            refresh: true,
            historyOptions: { source: options.source || 'tab-history' },
        });
        return;
    }
    if (tab === 'integrated') {
        switchTab('tools', options);
        setWorkspaceRunPanelExpanded(true);
        return;
    }
    // 更新按钮状态
    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });

    // 更新内容区状态
    document.querySelectorAll('.tab-content:not(.workspace-embedded-tab)').forEach(function(content) {
        content.classList.remove('active');
    });
    const target = document.getElementById('tab-' + tab);
    if (target) {
        target.classList.add('active');
    }
}

function activateTab(tab) {
    switchTab(tab, { source: 'manual-tab-click' });
}

function scanLocalDatabaseFolder() {
    bridgeResultsService.browseDirectory(function(rawResult) {
        let payload = null;
        try {
            payload = JSON.parse(rawResult);
        } catch (e) {
            payload = { path: '' };
        }

        const dirPath = String(payload?.path || '').trim();
        if (!dirPath) {
            return;
        }

        bridgeResultsService.scanLocalDatabaseResources(dirPath, function(scanResult) {
            let scanPayload = null;
            try {
                scanPayload = JSON.parse(scanResult);
            } catch (e) {
                scanPayload = { status: 'error', message: '扫描结果解析失败' };
            }

            if (!scanPayload || scanPayload.status !== 'ok') {
                showNotice(scanPayload?.message || '扫描数据库文件夹失败', 'error');
                return;
            }

            databaseResources = Array.isArray(scanPayload.resources) ? scanPayload.resources : [];
            const currentDir = document.getElementById('database-current-dir');
            if (currentDir) {
                currentDir.textContent = `当前目录：${scanPayload.directory || dirPath}`;
            }
            window.DatabasePanelRenderer.renderDatabaseResources({
                grid: document.getElementById('database-grid'),
                empty: document.getElementById('database-empty-state'),
                resources: databaseResources,
                setHidden,
                escapeHtml,
                onShowDetail: function(index) {
                    const item = databaseResources[index];
                    if (!item) {
                        return;
                    }
                    const lines = window.DatabasePanelRenderer.buildDatabaseResourceDetail(item);
                    showNotice(lines.join('\n'), 'success', 6000);
                },
            });
            switchTab('database');
        });
    }, function(error) {
        showNotice(error && error.message ? error.message : '当前版本不支持数据库文件夹扫描', 'warning');
    });
}

function loadIntegratedWorkbench(forceRefresh = false) {
    if (integratedWorkbenchHydrated && integratedWorkbench && !forceRefresh) {
        renderIntegratedWorkbench();
        return;
    }

    bridgeResultsService.loadIntegratedWorkbench(function(json) {
        try {
            const nextWorkbench = JSON.parse(json);
            window.IntegratedWorkbenchStateManager.syncIntegratedWorkbenchProjectScope(nextWorkbench);
            integratedWorkbench = nextWorkbench;
            integratedWorkbenchHydrated = true;
            window.IntegratedWorkbenchStateManager.restoreIntegratedExecutionFeatures();
            renderIntegratedWorkbench();
        } catch (e) {
            console.error('Failed to parse integrated workbench config:', e);
        }
    }, function(error) {
        console.error('Failed to load integrated workbench:', error);
    });
}

function renderIntegratedWorkbench() {
    if (!integratedWorkbench) {
        return;
    }

    window.IntegratedWorkbenchStateManager.restoreIntegratedExecutionFeatures();
    const openResultsState = window.IntegratedWorkbenchStateManager.getIntegratedOpenResultsState();

    const title = document.getElementById('integrated-title');
    const subtitle = document.getElementById('integrated-subtitle');
    if (title) {
        title.textContent = integratedWorkbench.title || '集成分析工作台';
    }
    if (subtitle) {
        subtitle.textContent = integratedWorkbench.subtitle || '';
    }

    const container = document.getElementById('integrated-feature-list');
    if (!container) {
        return;
    }

    const features = integratedWorkbench.features || [];
    window.IntegratedSidebarRenderer.renderIntegratedSidebar({
        container,
        features,
        selectedFeatureId: selectedIntegratedFeatureId,
        isHistoryResult: function(featureId) {
            return window.IntegratedWorkbenchStateManager.isIntegratedHistoryFeatureId(featureId);
        },
        isPinned: function(featureId) {
            return window.IntegratedWorkbenchStateManager.isIntegratedPinnedFeatureId(featureId);
        },
        onSelect: function(featureId, options) {
            selectIntegratedFeature(featureId, options);
        },
        onPinToggle: function(featureId, pinned) {
            window.IntegratedWorkbenchStateManager.setIntegratedHistoryResultPinned(featureId, pinned);
            renderIntegratedWorkbench();
        },
        onClose: function(featureId) {
            window.IntegratedWorkbenchStateManager.closeIntegratedHistoryFeature(featureId);
        },
        escapeHtml,
    });

    let preferredFeature = window.IntegratedWorkbenchSelection.pickPreferredFeature({
        features,
        pendingIntegratedFeatureId,
        selectedIntegratedFeatureId,
        openResultsActiveKey: openResultsState.activeKey,
    });
    if (preferredFeature) {
        const sourceMode = window.IntegratedWorkbenchSelection.getPreferredIntegratedViewSource({
            featureId: preferredFeature.id,
            pendingIntegratedViewSource,
            selectedIntegratedFeatureId,
            selectedIntegratedViewSource,
            integratedWorkbench,
            integratedExecutionViews,
        });
        selectIntegratedFeature(preferredFeature.id, { sourceMode });
    }
    pendingIntegratedFeatureId = null;
    pendingIntegratedViewSource = '';
    window.IntegratedWorkbenchStateManager.syncIntegratedHistoryResultControls();
}

function selectIntegratedFeature(featureId, options = {}) {
    if (!integratedWorkbench) {
        return;
    }

    const sourceMode = window.IntegratedWorkbenchSelection.resolveIntegratedViewSource({
        featureId,
        requestedSource: options.sourceMode || 'workflow',
        integratedWorkbench,
        integratedExecutionViews,
    });
    selectedIntegratedFeatureId = featureId;
    selectedIntegratedViewSource = sourceMode;
    if (sourceMode === 'history' && window.IntegratedWorkbenchStateManager.isIntegratedHistoryFeatureId(featureId)) {
        window.IntegratedWorkbenchStateManager.setIntegratedHistoryResultActive(featureId);
    }
    document.querySelectorAll('.integrated-feature-item').forEach(item => {
        item.classList.toggle('active', item.dataset.featureId === featureId);
    });

    const features = integratedWorkbench.features || [];
    const feature = features.find(item => item.id === featureId);
    const view = window.IntegratedWorkbenchSelection.getIntegratedFeatureView({
        featureId,
        sourceMode,
        integratedWorkbench,
        integratedExecutionViews,
    });
    window.IntegratedWorkbenchRenderer.renderIntegratedFeature(feature, view, { sourceMode });
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

window.DetectionPageUiFeedback.configureRuntime({
    escapeHtml,
});

function getInputBrowseFilter(input, descriptor) {
    if (descriptor?.id === 'primer_design' && input?.name === 'genomes_bundle') {
        return 'Primer 输入文件 (*.zip *.tar *.tar.gz *.tgz *.fasta *.fna *.fa);;压缩包 (*.zip *.tar *.tar.gz *.tgz);;序列文件 (*.fasta *.fna *.fa)';
    }

    if (input?.type === 'archive') {
        return '压缩包 (*.rar *.zip *.tar.gz *.tgz *.tar.bz2)';
    }

    return '所有文件 (*.*)';
}

function getInputSelectionValidator(input, descriptor) {
    if (descriptor?.id === 'primer_design' && input?.name === 'genomes_bundle') {
        return 'primer_genomes_bundle';
    }
    return '';
}

window.IntegratedRunModal.configureRuntime({
    getIntegratedWorkbench: function() {
        return integratedWorkbench;
    },
    getIntegratedRunModalContext: function() {
        return integratedRunModalContext;
    },
    setIntegratedRunModalContext: function(nextContext) {
        integratedRunModalContext = nextContext;
    },
    toolDescriptorCache,
    bridgeToolsService,
    getInputBrowseFilter,
    getInputSelectionValidator,
    getRecommendedValueFromUsage: window.DetectionPageHelpers.getRecommendedValueFromUsage,
    buildParamTooltipText: window.DetectionPageHelpers.buildParamTooltipText,
    getUsageGuideForParam: window.DetectionPageHelpers.getUsageGuideForParam,
    buildUsagePresetsPanel: function(descriptor, panelIdPrefix) {
        return window.DetectionPageHelpers.buildUsagePresetsPanel(descriptor, panelIdPrefix, escapeHtml);
    },
    showNotice,
    escapeHtml,
    setHidden,
    switchTab,
    switchWorkspaceMainView,
    selectTool: function(toolId) {
        window.ToolPanelRenderer.selectTool(toolId);
    },
    bindHelpTooltipInteractions,
});

window.IntegratedChartRenderer.configureRuntime({
    setHidden,
    escapeHtml,
    showNotice,
    getIntegratedCharts: function(chartInput) {
        return window.IntegratedWorkbenchRenderer.getIntegratedCharts(chartInput);
    },
    hasIntegratedChartData: function(chartInput) {
        return window.IntegratedWorkbenchRenderer.hasIntegratedChartData(chartInput);
    },
    getIntegratedChartRetryTimer: function() {
        return _integratedChartRetryTimer;
    },
    setIntegratedChartRetryTimer: function(nextTimer) {
        _integratedChartRetryTimer = nextTimer;
    },
    getEchartsLoadRequested: function() {
        return _echartsLoadRequested;
    },
    setEchartsLoadRequested: function(nextValue) {
        _echartsLoadRequested = Boolean(nextValue);
    },
});

window.IntegratedWorkbenchRenderer.configureRuntime({
    setHidden,
    escapeHtml,
    showNotice,
    toolDescriptorCache,
    bridgeToolsService,
    bridgeResultsService,
    getIntegratedWorkbench: function() {
        return integratedWorkbench;
    },
    getSelectedIntegratedFeatureId: function() {
        return selectedIntegratedFeatureId;
    },
    getSelectedIntegratedViewSource: function() {
        return selectedIntegratedViewSource;
    },
    openIntegratedRunModal: function(feature, toolId) {
        return window.IntegratedRunModal.openIntegratedRunModal(feature, toolId);
    },
    renderIntegratedChart: function(chartInput, options) {
        return window.IntegratedChartRenderer.renderIntegratedChart(chartInput, options);
    },
});

window.IntegratedWorkbenchStateManager.configureRuntime({
    integratedOpenResultsStore,
    integratedExecutionViews,
    integratedHistoryResultLimit: INTEGRATED_HISTORY_RESULT_LIMIT,
    setHidden,
    showNotice,
    switchTab,
    renderIntegratedWorkbench,
    selectIntegratedFeature,
    getIntegratedWorkbench: function() {
        return integratedWorkbench;
    },
    setIntegratedWorkbench: function(nextWorkbench) {
        integratedWorkbench = nextWorkbench;
    },
    getSelectedIntegratedFeatureId: function() {
        return selectedIntegratedFeatureId;
    },
    setSelectedIntegratedFeatureId: function(nextFeatureId) {
        selectedIntegratedFeatureId = nextFeatureId;
    },
    getPendingIntegratedFeatureId: function() {
        return pendingIntegratedFeatureId;
    },
    setPendingIntegratedFeatureId: function(nextFeatureId) {
        pendingIntegratedFeatureId = nextFeatureId;
    },
    getPendingIntegratedViewSource: function() {
        return pendingIntegratedViewSource;
    },
    setPendingIntegratedViewSource: function(nextSource) {
        pendingIntegratedViewSource = nextSource;
    },
    getSelectedIntegratedViewSource: function() {
        return selectedIntegratedViewSource;
    },
    setSelectedIntegratedViewSource: function(nextSource) {
        selectedIntegratedViewSource = nextSource;
    },
    getActiveIntegratedProjectId: function() {
        return activeIntegratedProjectId;
    },
    setActiveIntegratedProjectId: function(nextProjectId) {
        activeIntegratedProjectId = nextProjectId;
    },
});

window.HistoryStatusRenderer.configureRuntime({
    bridgeHistoryService,
    escapeHtml,
    showNotice,
    loadHistory,
    isRemoteStatusLoading: function(executionId) {
        return remoteStatusLoading.has(executionId);
    },
    setRemoteStatusLoading: function(executionId, loading) {
        if (!executionId) {
            return;
        }
        if (loading) {
            remoteStatusLoading.add(executionId);
            return;
        }
        remoteStatusLoading.delete(executionId);
    },
});

window.ToolPanelRenderer.configureRuntime({
    toolDescriptorCache,
    bridgeToolsService,
    escapeHtml,
    setHidden,
    showNotice,
    bindHelpTooltipInteractions,
    getInputBrowseFilter,
    getInputSelectionValidator,
    isPrimerGenomesBundlePath,
    getSelectedDescriptor: function() {
        return selectedDescriptor;
    },
    setSelectedDescriptor: function(nextDescriptor) {
        selectedDescriptor = nextDescriptor;
    },
    getSelectedToolId: function() {
        return selectedToolId;
    },
    setSelectedToolId: function(nextToolId) {
        selectedToolId = nextToolId;
    },
    getAllTools: function() {
        return allTools;
    },
    setAllTools: function(nextTools) {
        allTools = Array.isArray(nextTools) ? nextTools : [];
    },
    getRecommendedValueFromUsage: window.DetectionPageHelpers.getRecommendedValueFromUsage,
    buildParamTooltipText: window.DetectionPageHelpers.buildParamTooltipText,
    getUsageGuideForParam: window.DetectionPageHelpers.getUsageGuideForParam,
    buildUsagePresetsPanel: function(descriptor, panelIdPrefix) {
        return window.DetectionPageHelpers.buildUsagePresetsPanel(descriptor, panelIdPrefix, escapeHtml);
    },
    loadHistory,
    loadIntegratedWorkbench,
    openExecutionWithRuntime: function(executionId, context) {
        openHistoryExecution(executionId, context || {});
    },
});

function isPrimerGenomesBundlePath(filePath) {
    const path = String(filePath || '').toLowerCase();
    return path.endsWith('.zip')
        || path.endsWith('.tar.gz')
        || path.endsWith('.tgz')
        || path.endsWith('.tar')
        || path.endsWith('.fasta')
        || path.endsWith('.fna')
        || path.endsWith('.fa');
}

// 加载执行历史
function loadHistory(options = {}) {
    const requestId = ++historyRefreshRequestId;
    const withLoadingFeedback = options && options.source === 'manual';
    console.log('Loading execution history...');
    if (withLoadingFeedback) {
        beginHistoryRefreshLoading();
    }

    bridgeHistoryService.loadExecutionHistory(function(json) {
        if (requestId !== historyRefreshRequestId) {
            return;
        }
        try {
            historyRecords = parseHistoryRecordsPayload(json);
            console.log(`✓ Loaded ${historyRecords.length} execution records`);
            renderHistoryRecords();
        } catch (e) {
            console.error('Failed to parse history:', e);
            showNotice(`任务历史解析失败: ${e && e.message ? e.message : e}`);
        } finally {
            if (withLoadingFeedback) {
                completeHistoryRefreshLoading(requestId);
            }
        }
    }, function(error) {
        if (requestId !== historyRefreshRequestId) {
            return;
        }
        console.error('Failed to load history:', error);
        showNotice(error && error.message ? error.message : '加载任务历史失败');
        if (withLoadingFeedback) {
            completeHistoryRefreshLoading(requestId);
        }
    });
}

function normalizeExecutionStatus(status) {
    return String(status || '').trim().toLowerCase();
}

function focusHistoryExecution(executionId, options = {}) {
    const normalizedId = String(executionId || '').trim();
    if (!normalizedId) {
        showNotice('execution_id 不能为空');
        return;
    }

    activeHistoryExecutionId = normalizedId;
    setHistoryStatusFilter('all');
    const historySearch = document.getElementById('history-search');
    if (historySearch && String(historySearch.value || '').trim()) {
        historySearch.value = '';
    }

    pendingHistoryExecutionId = normalizedId;
    pendingHistoryExecutionOptions = {
        expand: options.expand !== false,
        fetchRemoteStatus: options.fetchRemoteStatus !== false,
        noticeMessage: String(options.noticeMessage || '').trim(),
    };
    if (options.keepMainView === true) {
        switchTab('tools', { source: 'focus-history-keep-main' });
        setWorkspaceRunPanelExpanded(true);
        loadHistory({ source: 'focus-history' });
        return;
    }
    switchTab('history', { source: 'focus-history' });
}

window.HistoryResultLoader.configureRuntime({
    bridgeResultsService,
    showNotice,
    findHistoryRecord: function(targetExecutionId) {
        return window.HistoryPanelRenderer.findHistoryRecord({
            executionId: targetExecutionId,
            historyRecords,
        });
    },
    normalizeExecutionStatus,
    focusHistoryExecution,
    applyPayload: function(payload, resolvedExecutionId, resolvedContext) {
        return window.IntegratedWorkbenchStateManager.applyIntegratedHistoryPayload(
            payload,
            resolvedExecutionId,
            resolvedContext,
        );
    },
});

function formatDetailCell(record) {
    if (record.status === 'completed') {
        return `<a href="#" class="detail-link" data-exec-id="${record.execution_id}" data-tool-id="${record.tool_id}">查看</a>`;
    } else if (record.status === 'failed') {
        const errMsg = record.error || '未知错误';
        const short = errMsg.length > 30 ? errMsg.substring(0, 30) + '…' : errMsg;
        return `<span class="error-hint" title="${escapeHtml(errMsg)}">${escapeHtml(short)}</span>`;
    } else if (record.status === 'running') {
        return '<span class="history-running-text">运行中...</span>';
    }
    return '-';
}
