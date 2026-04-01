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
if (!window.DatabasePanelRenderer || !window.HistoryPanelRenderer || !window.HistoryStatusRenderer || !window.IntegratedSidebarRenderer || !window.ResultViewerRenderers) {
    throw new Error('Render modules are required for detection page bootstrapping');
}
if (!window.HistoryResultLoader || !window.IntegratedWorkbenchSelection) {
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
let noticeHideTimer = null;
let integratedRunModalContext = null;
let _integratedChartRetryTimer = null;
let _echartsLoadRequested = false;
const remoteStatusLoading = new Set();
let _helpTooltipBound = false;
let _activeHelpTooltip = null;
const DETECTION_WORKFLOW_TOOL_IDS = [
    'unknown_sample_detection',
    'wastewater_metagenomics_basic',
    'animal_metagenomics_basic',
];
console.log('=== Galaxy Style Detection Page ===');

function setHidden(element, hidden) {
    if (!element) {
        return;
    }
    element.classList.toggle('is-hidden', Boolean(hidden));
}

function getIntegratedOpenResultsState() {
    return integratedOpenResultsStore.getState();
}

function syncIntegratedExecutionViewsFromState(snapshot = getIntegratedOpenResultsState()) {
    Object.keys(integratedExecutionViews).forEach(function(featureId) {
        delete integratedExecutionViews[featureId];
    });
    Object.keys(snapshot.entitiesByKey || {}).forEach(function(featureId) {
        integratedExecutionViews[featureId] = snapshot.entitiesByKey[featureId];
    });
    return snapshot;
}

function isIntegratedHistoryFeatureId(featureId) {
    return getIntegratedOpenResultsState().openKeys.includes(String(featureId || '').trim());
}

function isIntegratedPinnedFeatureId(featureId) {
    return getIntegratedOpenResultsState().pinnedKeys.includes(String(featureId || '').trim());
}

function syncIntegratedHistoryResultControls() {
    const clearBtn = document.getElementById('integrated-clear-history-results');
    if (!clearBtn) {
        return;
    }
    const snapshot = getIntegratedOpenResultsState();
    setHidden(clearBtn, snapshot.openKeys.length === 0);
    clearBtn.disabled = snapshot.openKeys.length === 0 || snapshot.openKeys.every(function(key) {
        return snapshot.pinnedKeys.includes(key);
    });
}

function buildIntegratedHistoryResultKey(baseFeatureId, executionId) {
    return window.IntegratedOpenResultsState.buildHistoryResultKey(baseFeatureId, executionId);
}

function getIntegratedHistoryFeatureLabel(view, fallbackFeatureId = '') {
    const baseTitle = String(view?.title || fallbackFeatureId || '结果').trim() || '结果';
    const sampleName = String(view?.hero?.sample_name || view?.hero?.sampleName || '').trim();
    const executionId = String(view?.provenance?.execution_id || view?.hero?.execution_id || '').trim();
    if (sampleName && executionId) {
        return `${baseTitle} · ${sampleName} · ${executionId.slice(0, 8)}`;
    }
    if (sampleName) {
        return `${baseTitle} · ${sampleName}`;
    }
    if (executionId) {
        return `${baseTitle} · ${executionId.slice(0, 8)}`;
    }
    return baseTitle;
}

function rememberIntegratedExecutionView(resultKey, view) {
    return syncIntegratedExecutionViewsFromState(
        integratedOpenResultsStore.registerResult(resultKey, {
            ...view,
            __displaySource: 'history',
        }),
    );
}

function setIntegratedHistoryResultPinned(resultKey, pinned) {
    return syncIntegratedExecutionViewsFromState(
        integratedOpenResultsStore.setPinned(resultKey, pinned),
    );
}

function setIntegratedHistoryResultActive(resultKey) {
    return syncIntegratedExecutionViewsFromState(
        integratedOpenResultsStore.setActive(resultKey),
    );
}

function closeIntegratedHistoryResultState(resultKey, nextActiveKey = '') {
    return syncIntegratedExecutionViewsFromState(
        integratedOpenResultsStore.closeResult(resultKey, nextActiveKey),
    );
}

function clearUnpinnedIntegratedHistoryResultState(nextActiveKey = '') {
    return syncIntegratedExecutionViewsFromState(
        integratedOpenResultsStore.clearUnpinned(nextActiveKey),
    );
}

function ensureNoticeContainer() {
    let container = document.getElementById('inline-notice-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'inline-notice-container';
        container.className = 'inline-notice-container';
        document.body.appendChild(container);
    }

    return container;
}

function showNotice(message, type = 'error', durationMs = 3600) {
    const text = String(message || '').trim();
    if (!text) {
        return;
    }

    const container = ensureNoticeContainer();
    const tone = type === 'success'
        ? { noticeClass: 'ui-notice--success', icon: '✓' }
        : type === 'warning'
            ? { noticeClass: 'ui-notice--warning', icon: '⚠' }
            : { noticeClass: 'ui-notice--danger', icon: 'ⓘ' };

    container.innerHTML = `
        <div role="alert" class="ui-notice ${tone.noticeClass}">
            <div class="ui-notice-icon">${tone.icon}</div>
            <div class="ui-notice-body">${escapeHtml(text)}</div>
            <button type="button" class="ui-notice-close" onclick="dismissNotice()" aria-label="关闭">×</button>
        </div>
    `;

    if (noticeHideTimer) {
        clearTimeout(noticeHideTimer);
    }
    noticeHideTimer = setTimeout(dismissNotice, Math.max(1200, Number(durationMs) || 3600));
}

function dismissNotice() {
    if (noticeHideTimer) {
        clearTimeout(noticeHideTimer);
        noticeHideTimer = null;
    }
    const container = document.getElementById('inline-notice-container');
    if (container) {
        container.innerHTML = '';
    }
}

function closeHelpTooltip() {
    if (!_activeHelpTooltip) {
        return;
    }
    const trigger = _activeHelpTooltip.trigger;
    if (trigger) {
        trigger.setAttribute('aria-expanded', 'false');
    }
    try {
        _activeHelpTooltip.node?.remove();
    } catch (_) {
        // ignore
    }
    _activeHelpTooltip = null;
}

function openHelpTooltip(triggerEl, text) {
    closeHelpTooltip();
    if (!triggerEl || !text) {
        return;
    }

    const tip = document.createElement('div');
    tip.className = 'help-tooltip-popover';
    tip.setAttribute('role', 'tooltip');
    tip.textContent = String(text);
    document.body.appendChild(tip);

    const rect = triggerEl.getBoundingClientRect();
    const margin = 8;
    const maxLeft = Math.max(8, window.innerWidth - tip.offsetWidth - 8);
    const left = Math.min(Math.max(8, rect.left), maxLeft);
    let top = rect.bottom + margin;
    if (top + tip.offsetHeight > window.innerHeight - 8) {
        top = Math.max(8, rect.top - tip.offsetHeight - margin);
    }
    tip.style.left = `${Math.round(left)}px`;
    tip.style.top = `${Math.round(top)}px`;

    triggerEl.setAttribute('aria-expanded', 'true');
    _activeHelpTooltip = { trigger: triggerEl, node: tip };
}

function bindHelpTooltipInteractions() {
    if (_helpTooltipBound) {
        return;
    }
    _helpTooltipBound = true;

    document.addEventListener('click', function(event) {
        const target = event.target;
        const trigger = target && target.closest ? target.closest('.help-icon-btn[data-help-text]') : null;
        if (trigger) {
            event.preventDefault();
            event.stopPropagation();
            const text = String(trigger.getAttribute('data-help-text') || '').trim();
            if (!text) {
                return;
            }
            if (_activeHelpTooltip && _activeHelpTooltip.trigger === trigger) {
                closeHelpTooltip();
                return;
            }
            openHelpTooltip(trigger, text);
            return;
        }

        if (_activeHelpTooltip && _activeHelpTooltip.node && target && _activeHelpTooltip.node.contains(target)) {
            return;
        }
        closeHelpTooltip();
    });

    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            closeHelpTooltip();
        }
    });

    window.addEventListener('resize', closeHelpTooltip);
    window.addEventListener('scroll', closeHelpTooltip, true);
}

// 初始化 QWebChannel
new QWebChannel(qt.webChannelTransport, function(channel) {
    console.log('✓ QWebChannel connected');
    bridge = channel.objects.bridge;

    // 监听 Python 信号
    bridge.tool_selected.connect(function(tool_id) {
        console.log('Tool selected from Python:', tool_id);
    });

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
    document.getElementById('btn-refresh').addEventListener('click', loadHistory);
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
            clearIntegratedTemporaryFeatures({ clearAllUnpinned: true });
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
        loadHistory();
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
            syncIntegratedWorkbenchProjectScope(nextWorkbench);
            integratedWorkbench = nextWorkbench;
            restoreIntegratedExecutionFeatures();
            renderIntegratedWorkbench();
        } catch (e) {
            console.error('Failed to parse integrated workbench config:', e);
        }
    }, function(error) {
        console.error('Failed to load integrated workbench:', error);
    });
}

function clearIntegratedExecutionCache() {
    syncIntegratedExecutionViewsFromState(integratedOpenResultsStore.reset());
    pendingIntegratedFeatureId = null;
    pendingIntegratedViewSource = '';
    selectedIntegratedViewSource = 'workflow';
    syncIntegratedHistoryResultControls();
}

function syncIntegratedWorkbenchProjectScope(nextWorkbench) {
    const nextProjectId = String(nextWorkbench?.project_id || '').trim();
    if (activeIntegratedProjectId && nextProjectId !== activeIntegratedProjectId) {
        clearIntegratedExecutionCache();
    }
    activeIntegratedProjectId = nextProjectId;
}

function restoreIntegratedExecutionFeatures() {
    if (!integratedWorkbench) {
        return;
    }

    Object.keys(getIntegratedOpenResultsState().entitiesByKey || {}).forEach(function(featureId) {
        const view = integratedExecutionViews[featureId];
        if (!view || getIntegratedWorkbenchFeature(featureId)) {
            return;
        }
        upsertIntegratedHistoryFeature(featureId, view, { temporary: true });
    });
    syncIntegratedHistoryResultControls();
}

function renderIntegratedWorkbench() {
    if (!integratedWorkbench) {
        return;
    }

    restoreIntegratedExecutionFeatures();
    const openResultsState = getIntegratedOpenResultsState();

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
            return isIntegratedHistoryFeatureId(featureId);
        },
        isPinned: function(featureId) {
            return isIntegratedPinnedFeatureId(featureId);
        },
        onSelect: function(featureId, options) {
            selectIntegratedFeature(featureId, options);
        },
        onPinToggle: function(featureId, pinned) {
            setIntegratedHistoryResultPinned(featureId, pinned);
            renderIntegratedWorkbench();
        },
        onClose: function(featureId) {
            closeIntegratedHistoryFeature(featureId);
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
    syncIntegratedHistoryResultControls();
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
    if (sourceMode === 'history' && isIntegratedHistoryFeatureId(featureId)) {
        setIntegratedHistoryResultActive(featureId);
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
function loadHistory() {
    console.log('Loading execution history...');
    bridgeHistoryService.loadExecutionHistory(function(json) {
        try {
            historyRecords = JSON.parse(json);
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
        }
    }, function(error) {
        console.error('Failed to load history:', error);
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

function ensureIntegratedWorkbenchViews() {
    if (!integratedWorkbench) {
        integratedWorkbench = { views: {}, features: [] };
    }
    if (!integratedWorkbench.views) {
        integratedWorkbench.views = {};
    }
    if (!integratedWorkbench.features) {
        integratedWorkbench.features = [];
    }
    return integratedWorkbench.views;
}

function getIntegratedWorkbenchFeature(featureId) {
    ensureIntegratedWorkbenchViews();
    return (integratedWorkbench.features || []).find(feature => feature && feature.id === featureId) || null;
}

function removeIntegratedWorkbenchFeature(featureId) {
    if (!integratedWorkbench) {
        return;
    }
    ensureIntegratedWorkbenchViews();
    integratedWorkbench.features = (integratedWorkbench.features || []).filter(function(feature) {
        return feature && feature.id !== featureId;
    });
    if (integratedWorkbench.views && Object.prototype.hasOwnProperty.call(integratedWorkbench.views, featureId)) {
        delete integratedWorkbench.views[featureId];
    }
}

function closeIntegratedHistoryFeature(featureId, options = {}) {
    const normalizedId = String(featureId || '').trim();
    if (!normalizedId || !isIntegratedHistoryFeatureId(normalizedId)) {
        return;
    }

    const nextSnapshot = closeIntegratedHistoryResultState(normalizedId, options.nextActiveKey || '');
    removeIntegratedWorkbenchFeature(normalizedId);
    if (pendingIntegratedFeatureId === normalizedId) {
        pendingIntegratedFeatureId = nextSnapshot.activeKey || '';
        pendingIntegratedViewSource = nextSnapshot.activeKey ? 'history' : '';
    }
    if (selectedIntegratedFeatureId === normalizedId) {
        selectedIntegratedFeatureId = nextSnapshot.activeKey || null;
        selectedIntegratedViewSource = nextSnapshot.activeKey ? 'history' : 'workflow';
    }
    renderIntegratedWorkbench();
}

function clearIntegratedTemporaryFeatures(options = {}) {
    ensureIntegratedWorkbenchViews();
    const normalizedOptions = typeof options === 'string'
        ? { exceptFeatureId: options }
        : (options || {});
    const preservedId = String(normalizedOptions.exceptFeatureId || '').trim();
    const snapshot = normalizedOptions.clearAllUnpinned
        ? clearUnpinnedIntegratedHistoryResultState(preservedId)
        : syncIntegratedExecutionViewsFromState(
            integratedOpenResultsStore.trimOpenResults({
                maxOpenResults: Number(normalizedOptions.maxCount) || INTEGRATED_HISTORY_RESULT_LIMIT,
                keepKeys: preservedId ? [preservedId] : [],
                keepActiveKey: preservedId || getIntegratedOpenResultsState().activeKey,
            }),
        );
    const preservedKeys = new Set(snapshot.openKeys || []);
    integratedWorkbench.features = (integratedWorkbench.features || []).filter(function(feature) {
        if (!feature || !feature.temporary) {
            return true;
        }
        return preservedKeys.has(feature.id);
    });
    if (!preservedKeys.has(String(selectedIntegratedFeatureId || '').trim())) {
        selectedIntegratedFeatureId = snapshot.activeKey || null;
        selectedIntegratedViewSource = snapshot.activeKey ? 'history' : selectedIntegratedViewSource;
    }
    syncIntegratedHistoryResultControls();
}

function upsertIntegratedHistoryFeature(featureId, view, options = {}) {
    if (!featureId) {
        return false;
    }
    ensureIntegratedWorkbenchViews();
    const temporary = Boolean(options.temporary);
    const existingIndex = (integratedWorkbench.features || []).findIndex(feature => feature && feature.id === featureId);

    if (temporary) {
        clearIntegratedTemporaryFeatures({ exceptFeatureId: featureId, maxCount: INTEGRATED_HISTORY_RESULT_LIMIT });
    }

    if (existingIndex >= 0) {
        const current = integratedWorkbench.features[existingIndex] || {};
        integratedWorkbench.features[existingIndex] = {
            ...current,
            id: featureId,
            name: temporary
                ? getIntegratedHistoryFeatureLabel(view, featureId)
                : String(current.name || view?.title || featureId),
            description: String(current.description || view?.description || ''),
            status: current.status || 'active',
            temporary: Boolean(current.temporary) || temporary,
        };
        return false;
    }

    integratedWorkbench.features.push({
        id: featureId,
        name: temporary
            ? getIntegratedHistoryFeatureLabel(view, featureId)
            : String(view?.title || featureId),
        badge: '',
        description: String(view?.description || ''),
        status: 'active',
        temporary,
    });
    return true;
}

function applyIntegratedHistoryPayload(payload, resolvedExecutionId, resolvedContext) {
    const errorMessage = resolvedContext.errorMessage || '任务结果读取失败';
    ensureIntegratedWorkbenchViews();
    const baseFeatureId = String(
        resolvedContext.featureId
        || payload.view.feature_id
        || payload.view.view_id
        || payload.view.tool_id
        || ''
    ).trim();
    if (!baseFeatureId) {
        showNotice(payload.message || errorMessage);
        return false;
    }
    const featureId = buildIntegratedHistoryResultKey(baseFeatureId, resolvedExecutionId);
    rememberIntegratedExecutionView(featureId, payload.view);
    pendingIntegratedFeatureId = featureId;
    pendingIntegratedViewSource = 'history';
    const existingFeature = getIntegratedWorkbenchFeature(featureId);
    const featureChanged = upsertIntegratedHistoryFeature(
        featureId,
        payload.view,
        { temporary: !existingFeature || Boolean(existingFeature?.temporary) },
    );
    switchTab('integrated');
    if (featureChanged) {
        renderIntegratedWorkbench();
    } else {
        selectIntegratedFeature(featureId, { sourceMode: 'history' });
    }
    return true;
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
    applyPayload: applyIntegratedHistoryPayload,
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
