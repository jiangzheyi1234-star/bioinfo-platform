let bridge = null;
let allTools = [];
let selectedToolId = null;
let selectedDescriptor = null;
let integratedWorkbench = null;
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
const INTEGRATED_SIDEBAR_DRAWER_BREAKPOINT = 1280;
let integratedSidebarDrawerHandlersBound = false;
let integratedAnalysisSectionCollapsed = false;
let integratedHistorySectionCollapsed = true;
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

function isIntegratedSidebarDrawerMode() {
    return window.matchMedia(`(max-width: ${INTEGRATED_SIDEBAR_DRAWER_BREAKPOINT}px)`).matches;
}

function setIntegratedSidebarDrawerOpen(open) {
    const tabIntegrated = document.getElementById('tab-integrated');
    const toggleBtn = document.getElementById('integrated-sidebar-toggle');
    const nextOpen = Boolean(open) && isIntegratedSidebarDrawerMode();
    if (tabIntegrated) {
        tabIntegrated.classList.toggle('integrated-sidebar-open', nextOpen);
    }
    if (toggleBtn) {
        toggleBtn.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
    }
}

function closeIntegratedSidebarDrawer() {
    setIntegratedSidebarDrawerOpen(false);
}

function bindIntegratedSidebarDrawerControls() {
    const toggleBtn = document.getElementById('integrated-sidebar-toggle');
    const backdrop = document.getElementById('integrated-sidebar-backdrop');

    if (toggleBtn && toggleBtn.dataset.bound !== '1') {
        toggleBtn.dataset.bound = '1';
        toggleBtn.addEventListener('click', function() {
            const tabIntegrated = document.getElementById('tab-integrated');
            const opening = !(tabIntegrated && tabIntegrated.classList.contains('integrated-sidebar-open'));
            setIntegratedSidebarDrawerOpen(opening);
        });
    }

    if (backdrop && backdrop.dataset.bound !== '1') {
        backdrop.dataset.bound = '1';
        backdrop.addEventListener('click', function() {
            closeIntegratedSidebarDrawer();
        });
    }

    if (integratedSidebarDrawerHandlersBound) {
        if (!isIntegratedSidebarDrawerMode()) {
            closeIntegratedSidebarDrawer();
        }
        return;
    }
    integratedSidebarDrawerHandlersBound = true;

    window.addEventListener('resize', function() {
        if (!isIntegratedSidebarDrawerMode()) {
            closeIntegratedSidebarDrawer();
        }
    });
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            closeIntegratedSidebarDrawer();
        }
    });
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
    const historySearch = document.getElementById('history-search');
    if (historySearch) {
        historySearch.addEventListener('input', function(e) {
            window.HistoryPanelRenderer.renderHistoryPanel({
                container: document.getElementById('history-container'),
                history: window.HistoryPanelRenderer.filterHistoryRecords({
                    query: String(e.target.value || ''),
                    historyRecords,
                    allTools,
                }),
                allTools,
                pendingExecutionId: pendingHistoryExecutionId,
                pendingOptions: pendingHistoryExecutionOptions || {},
                escapeHtml,
                resolveHistoryResultContext: function(record) {
                    return window.HistoryResultLoader.resolveHistoryResultContext(record);
                },
                openExecution: function(executionId, context) {
                    window.HistoryResultLoader.openExecutionWithRuntime(executionId, context);
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
                    pendingHistoryExecutionId = null;
                    pendingHistoryExecutionOptions = null;
                },
            });
        });
    }
    const clearIntegratedHistoryResultsBtn = document.getElementById('integrated-clear-history-results');
    if (clearIntegratedHistoryResultsBtn) {
        clearIntegratedHistoryResultsBtn.addEventListener('click', function() {
            window.IntegratedWorkbenchStateManager.clearIntegratedTemporaryFeatures({ clearAllUnpinned: true });
            renderIntegratedWorkbench();
        });
    }
    bindIntegratedSidebarDrawerControls();

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
    window.IntegratedWorkbenchRenderer.initializeIntegratedSectionToggles();
    window.IntegratedWorkbenchRenderer.initializeIntegratedResultTabs();
    bindHelpTooltipInteractions();
});

function switchTab(tab) {
    // 更新按钮状态
    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });

    // 更新内容区状态
    document.querySelectorAll('.tab-content').forEach(function(content) {
        content.classList.remove('active');
    });
    const target = document.getElementById('tab-' + tab);
    if (target) {
        target.classList.add('active');
    }

    if (tab !== 'integrated') {
        closeIntegratedSidebarDrawer();
    }

    if (tab === 'integrated') {
        // ECharts resize on tab switch
        setTimeout(function() {
            window.IntegratedChartRenderer.resizeIntegratedCharts();
        }, 100);
    }
}

function activateTab(tab) {
    switchTab(tab);

    if (tab === 'history') {
        loadHistory({ source: 'tab-switch' });
        return;
    }

    if (tab === 'integrated') {
        loadIntegratedWorkbench();
    }
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
    if (integratedWorkbench && !forceRefresh) {
        renderIntegratedWorkbench();
        return;
    }

    bridgeResultsService.loadIntegratedWorkbench(function(json) {
        try {
            const nextWorkbench = JSON.parse(json);
            window.IntegratedWorkbenchStateManager.syncIntegratedWorkbenchProjectScope(nextWorkbench);
            integratedWorkbench = nextWorkbench;
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

    const analysisContainer = document.getElementById('integrated-analysis-feature-list');
    const analysisToggleBtn = document.getElementById('integrated-analysis-toggle');
    const analysisCountEl = document.getElementById('integrated-analysis-count');
    const historyContainer = document.getElementById('integrated-history-feature-list');
    const historyToggleBtn = document.getElementById('integrated-history-toggle');
    const historyCountEl = document.getElementById('integrated-history-count');
    if (!analysisContainer || !analysisToggleBtn || !analysisCountEl || !historyContainer || !historyToggleBtn || !historyCountEl) {
        return;
    }

    const features = integratedWorkbench.features || [];
    const analysisFeatures = [];
    const historyFeatures = [];
    features.forEach(function(feature) {
        const featureId = String(feature && feature.id || '').trim();
        if (window.IntegratedWorkbenchStateManager.isIntegratedHistoryFeatureId(featureId)) {
            historyFeatures.push(feature);
            return;
        }
        analysisFeatures.push(feature);
    });
    window.IntegratedSidebarRenderer.renderIntegratedSidebar({
        analysisContainer,
        analysisToggleBtn,
        analysisCountEl,
        historyContainer,
        historyToggleBtn,
        historyCountEl,
        analysisFeatures,
        historyFeatures,
        analysisCollapsed: integratedAnalysisSectionCollapsed,
        historyCollapsed: integratedHistorySectionCollapsed,
        selectedFeatureId: selectedIntegratedFeatureId,
        isHistoryResult: function(featureId) {
            return window.IntegratedWorkbenchStateManager.isIntegratedHistoryFeatureId(featureId);
        },
        isPinned: function(featureId) {
            return window.IntegratedWorkbenchStateManager.isIntegratedPinnedFeatureId(featureId);
        },
        onSelect: function(featureId, options) {
            closeIntegratedSidebarDrawer();
            selectIntegratedFeature(featureId, options);
        },
        onAnalysisToggle: function(nextCollapsed) {
            integratedAnalysisSectionCollapsed = Boolean(nextCollapsed);
            renderIntegratedWorkbench();
        },
        onHistoryToggle: function(nextCollapsed) {
            integratedHistorySectionCollapsed = Boolean(nextCollapsed);
            renderIntegratedWorkbench();
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
        window.HistoryResultLoader.openExecutionWithRuntime(executionId, context);
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
            const historySearch = document.getElementById('history-search');
            window.HistoryPanelRenderer.renderHistoryPanel({
                container: document.getElementById('history-container'),
                history: window.HistoryPanelRenderer.filterHistoryRecords({
                    query: String(historySearch?.value || ''),
                    historyRecords,
                    allTools,
                }),
                allTools,
                pendingExecutionId: pendingHistoryExecutionId,
                pendingOptions: pendingHistoryExecutionOptions || {},
                escapeHtml,
                resolveHistoryResultContext: function(record) {
                    return window.HistoryResultLoader.resolveHistoryResultContext(record);
                },
                openExecution: function(executionId, context) {
                    window.HistoryResultLoader.openExecutionWithRuntime(executionId, context);
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
                    pendingHistoryExecutionId = null;
                    pendingHistoryExecutionOptions = null;
                },
            });
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
    activateTab('history');
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
