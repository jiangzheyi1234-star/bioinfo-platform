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
if (!window.DatabasePanelRenderer || !window.HistoryPanelRenderer || !window.IntegratedSidebarRenderer || !window.ResultViewerRenderers) {
    throw new Error('Render modules are required for detection page bootstrapping');
}
if (!window.HistoryResultLoader || !window.IntegratedWorkbenchSelection) {
    throw new Error('Result workbench modules are required for detection page bootstrapping');
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
const INTEGRATED_ARCHETYPE_VIEWER_STRATEGIES = {
    annotation_table: 'table-first',
    quality_assessment: 'table-first',
    html_report: 'html-first',
    artifact_collection: 'files-first',
    qc_report: 'chart-first',
    taxonomy_profile: 'chart-first',
    workflow_product: 'chart-first',
};
const INTEGRATED_REQUIRED_VIEWERS_BY_ARCHETYPE = {
    annotation_table: ['table', 'files'],
    quality_assessment: ['table'],
    html_report: ['html'],
    artifact_collection: ['files'],
    qc_report: ['chart', 'files'],
    taxonomy_profile: ['chart', 'table', 'files'],
    workflow_product: ['sections'],
};

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
    loadTools();

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
        renderToolsList(e.target.value);
    });

    // 刷新历史按钮
    document.getElementById('btn-refresh').addEventListener('click', loadHistory);
    const historySearch = document.getElementById('history-search');
    if (historySearch) {
        historySearch.addEventListener('input', function(e) {
            renderHistoryPanelView(window.HistoryPanelRenderer.filterHistoryRecords({
                query: String(e.target.value || ''),
                historyRecords,
                allTools,
            }));
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
    document.getElementById('run-btn').addEventListener('click', runTool);

    // 清空按钮
    document.getElementById('clear-btn').addEventListener('click', clearForm);

    const databaseScanBtn = document.getElementById('database-scan-btn');
    if (databaseScanBtn) {
        databaseScanBtn.addEventListener('click', scanLocalDatabaseFolder);
    }

    // Python 回调：运行结果
    window._onRunResult = onRunResult;
    const integratedRunBtn = document.getElementById('integrated-run-btn');
    if (integratedRunBtn) {
        integratedRunBtn.addEventListener('click', openIntegratedRunEntry);
    }
    initializeIntegratedSectionToggles();
    initializeIntegratedResultTabs();
    bindHelpTooltipInteractions();
});

function getIntegratedToolId(feature, view) {
    return (view && view.tool_id)
        || (view && view.tool_ids && view.tool_ids[0])
        || (feature && feature.tool_ids && feature.tool_ids[0])
        || null;
}

function openIntegratedRunEntry() {
    if (!integratedWorkbench || !selectedIntegratedFeatureId) {
        return;
    }

    const feature = (integratedWorkbench.features || []).find(item => item.id === selectedIntegratedFeatureId);
    const view = (integratedWorkbench.views || {})[selectedIntegratedFeatureId];
    const toolId = getIntegratedToolId(feature, view);
    if (!toolId) {
        showNotice('Current feature has no run entry yet', 'warning');
        return;
    }

    openIntegratedRunModal(feature, toolId);
}

function ensureIntegratedRunModal() {
    let modal = document.getElementById('integrated-run-modal');
    if (modal) {
        return modal;
    }

    modal = document.createElement('div');
    modal.id = 'integrated-run-modal';
    modal.className = 'integrated-run-modal ui-modal';
    modal.innerHTML = `
        <div class="integrated-run-modal-backdrop ui-modal__backdrop" data-close="1"></div>
        <div class="integrated-run-modal-card ui-modal__card" role="dialog" aria-modal="true" aria-labelledby="integrated-run-modal-title">
            <div class="integrated-run-modal-header">
                <h3 id="integrated-run-modal-title">Run Entry</h3>
                <button class="integrated-run-modal-close" type="button" id="integrated-run-modal-close" aria-label="Close">&times;</button>
            </div>
            <div class="integrated-run-modal-body">
                <div class="integrated-run-modal-line"><span>Feature</span><strong id="integrated-run-modal-feature">-</strong></div>
                <div class="integrated-run-modal-line"><span>Tool</span><strong id="integrated-run-modal-tool">-</strong></div>
                <div class="integrated-run-modal-line is-hidden" id="integrated-run-modal-tool-select-row">
                    <span>分类工具</span>
                    <div id="integrated-run-modal-tool-switch" class="integrated-tool-switch" role="group" aria-label="分类工具选择"></div>
                </div>
                <div class="integrated-run-modal-hint" id="integrated-run-modal-hint">Fill fields in this popup and submit directly, or open plugin workbench.</div>
                <div class="integrated-run-modal-form" id="integrated-run-modal-form"></div>
            </div>
            <div class="integrated-run-modal-actions">
                <button class="ui-button ui-button--secondary" type="button" id="integrated-run-modal-cancel">Cancel</button>
                <button class="ui-button ui-button--secondary" type="button" id="integrated-run-modal-open-tools">Open Tools</button>
                <button class="ui-button ui-button--primary" type="button" id="integrated-run-modal-confirm">Submit</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    modal.addEventListener('click', function(event) {
        if (event.target && event.target.dataset && event.target.dataset.close === '1') {
            closeIntegratedRunModal();
        }
    });

    const closeBtn = document.getElementById('integrated-run-modal-close');
    const cancelBtn = document.getElementById('integrated-run-modal-cancel');
    const openToolsBtn = document.getElementById('integrated-run-modal-open-tools');
    const confirmBtn = document.getElementById('integrated-run-modal-confirm');

    if (closeBtn) closeBtn.addEventListener('click', closeIntegratedRunModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeIntegratedRunModal);
    if (openToolsBtn) openToolsBtn.addEventListener('click', goToIntegratedRunTool);
    if (confirmBtn) confirmBtn.addEventListener('click', runIntegratedRunModal);

    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            closeIntegratedRunModal();
        }
    });

    return modal;
}

function openIntegratedRunModal(feature, toolId) {
    const view = (integratedWorkbench && integratedWorkbench.views)
        ? integratedWorkbench.views[feature?.id]
        : null;
    const toolIds = Array.isArray(view?.tool_ids) && view.tool_ids.length
        ? view.tool_ids.slice()
        : [toolId].filter(Boolean);
    const activeToolId = toolIds.includes(toolId) ? toolId : (toolIds[0] || toolId);

    integratedRunModalContext = {
        featureId: feature?.id || '',
        featureName: feature?.name || feature?.id || '',
        toolId: activeToolId,
        descriptor: null,
        _descriptorSeq: 0,
    };

    const modal = ensureIntegratedRunModal();
    const featureEl = document.getElementById('integrated-run-modal-feature');
    const toolEl = document.getElementById('integrated-run-modal-tool');
    const toolSelectRowEl = document.getElementById('integrated-run-modal-tool-select-row');
    const toolSwitchEl = document.getElementById('integrated-run-modal-tool-switch');
    const hintEl = document.getElementById('integrated-run-modal-hint');
    const formEl = document.getElementById('integrated-run-modal-form');

    if (featureEl) featureEl.textContent = integratedRunModalContext.featureName || '-';
    if (toolEl) toolEl.textContent = activeToolId || '-';
    if (hintEl) hintEl.textContent = 'Loading input requirements...';
    if (formEl) formEl.innerHTML = '<div class="integrated-input-empty">Loading...</div>';

    const applyDescriptor = function(descriptor, requestSeq) {
        if (!integratedRunModalContext || requestSeq !== integratedRunModalContext._descriptorSeq) {
            return;
        }
        integratedRunModalContext.descriptor = descriptor || {};
        const inputCount = (descriptor.inputs || []).length;
        const paramCount = (descriptor.parameters || []).length;
        const dbCount = (descriptor.databases || []).length;
        if (hintEl) {
            hintEl.textContent = `Inputs ${inputCount}, Params ${paramCount}, Databases ${dbCount}.`; 
        }
        renderIntegratedRunModalForm(descriptor || {});
    };

    const fetchDescriptorForTool = function(nextToolId) {
        if (!integratedRunModalContext) {
            return;
        }
        integratedRunModalContext.toolId = nextToolId;
        if (toolEl) toolEl.textContent = nextToolId || '-';
        if (hintEl) hintEl.textContent = 'Loading input requirements...';
        if (formEl) formEl.innerHTML = '<div class="integrated-input-empty">Loading...</div>';

        integratedRunModalContext._descriptorSeq += 1;
        const requestSeq = integratedRunModalContext._descriptorSeq;
        const cached = toolDescriptorCache[nextToolId];
        if (cached) {
            applyDescriptor(cached, requestSeq);
            return;
        }
        if (!(bridge && bridge.get_tool_descriptor)) {
            if (requestSeq === integratedRunModalContext._descriptorSeq) {
                if (hintEl) hintEl.textContent = 'Tool descriptor API unavailable.';
                if (formEl) formEl.innerHTML = '<div class="integrated-input-empty">API unavailable.</div>';
            }
            return;
        }
        bridgeToolsService.getToolDescriptor(nextToolId, function(json) {
            try {
                const descriptor = JSON.parse(json || '{}');
                toolDescriptorCache[nextToolId] = descriptor;
                applyDescriptor(descriptor, requestSeq);
            } catch (e) {
                if (requestSeq === integratedRunModalContext._descriptorSeq) {
                    if (hintEl) hintEl.textContent = 'Failed to load requirements. Use Open Tools instead.';
                    if (formEl) formEl.innerHTML = '<div class="integrated-input-empty">Parse failed.</div>';
                }
            }
        }, function() {
            if (requestSeq === integratedRunModalContext._descriptorSeq) {
                if (hintEl) hintEl.textContent = 'Tool descriptor API unavailable.';
                if (formEl) formEl.innerHTML = '<div class="integrated-input-empty">API unavailable.</div>';
            }
        });
    };

    if (toolSelectRowEl && toolSwitchEl) {
        if (toolIds.length > 1) {
            setHidden(toolSelectRowEl, false);
            toolSwitchEl.innerHTML = toolIds.map(id => {
                const activeClass = id === activeToolId ? 'is-active' : '';
                return `<button type="button" class="integrated-tool-switch-btn ${activeClass}" data-tool-id="${escapeHtml(id)}">${escapeHtml(id)}</button>`;
            }).join('');
            toolSwitchEl.querySelectorAll('.integrated-tool-switch-btn').forEach(btn => {
                btn.addEventListener('click', function() {
                    const nextToolId = btn.getAttribute('data-tool-id') || '';
                    if (!nextToolId || nextToolId === (integratedRunModalContext && integratedRunModalContext.toolId)) {
                        return;
                    }
                    toolSwitchEl.querySelectorAll('.integrated-tool-switch-btn').forEach(item => item.classList.remove('is-active'));
                    btn.classList.add('is-active');
                    fetchDescriptorForTool(nextToolId);
                });
            });
        } else {
            setHidden(toolSelectRowEl, true);
            toolSwitchEl.innerHTML = '';
        }
    }

    fetchDescriptorForTool(activeToolId);

    modal.classList.add('show');
}

function renderIntegratedRunModalForm(descriptor) {
    const formEl = document.getElementById('integrated-run-modal-form');
    if (!formEl) {
        return;
    }

    const inputs = descriptor.inputs || [];
    const parameters = descriptor.parameters || [];
    const databases = descriptor.databases || [];
    const parts = [];

    if (inputs.length) {
        parts.push('<div class="integrated-run-modal-group"><div class="integrated-run-modal-group-title">Inputs</div>');
        inputs.forEach(input => {
            const required = input.required !== false ? '<span class="integrated-input-required">Required</span>' : '';
            const browseFilter = getInputBrowseFilter(input, descriptor || {});
            const validator = getInputSelectionValidator(input, descriptor || {});
            const id = `modal-input-${input.name}`;
            parts.push(`
                <div class="integrated-input-item">
                    <div class="integrated-input-label-row"><span class="integrated-input-label">${escapeHtml(input.label || input.name || 'Input')}</span>${required}</div>
                    <div class="input-group">
                        <input type="text" class="ui-field" id="${id}" placeholder="${escapeHtml(input.description || 'Select file')}" readonly>
                        <button class="ui-button ui-button--secondary ui-button--sm form-browse-btn" type="button" onclick="browseFile('${id}', '${browseFilter}', '${validator}')">Browse...</button>
                    </div>
                </div>
            `);
        });
        parts.push('</div>');
    }

    if (parameters.length) {
        parts.push('<div class="integrated-run-modal-group"><div class="integrated-run-modal-group-title">Parameters</div>');
        parameters.forEach(param => {
            const id = `modal-param-${param.name}`;
            const label = escapeHtml(param.label || param.name || 'Param');
            const recommendedValue = getRecommendedValueFromUsage(descriptor, param.name);
            const defaultValue = recommendedValue !== undefined
                ? recommendedValue
                : (param.default !== undefined ? param.default : '');
            const tooltipText = buildParamTooltipText(param, descriptor);
            const tooltipHtml = tooltipText
                ? `<button type="button" class="help-icon-btn" aria-label="参数说明" aria-expanded="false" data-help-text="${escapeHtml(tooltipText)}" title="${escapeHtml(tooltipText)}">?</button>`
                : '';
            let inputHtml = '';
            if (param.type === 'int' || param.type === 'integer') {
                inputHtml = `<input type="number" class="ui-field" id="${id}" value="${defaultValue}" step="1">`;
            } else if (param.type === 'float' || param.type === 'number') {
                inputHtml = `<input type="number" class="ui-field" id="${id}" value="${defaultValue}" step="0.01">`;
            } else if (param.type === 'bool' || param.type === 'boolean') {
                inputHtml = `<select class="ui-field" id="${id}"><option value="true" ${defaultValue === true ? 'selected' : ''}>Yes</option><option value="false" ${defaultValue === false ? 'selected' : ''}>No</option></select>`;
            } else {
                inputHtml = `<input type="text" class="ui-field" id="${id}" value="${escapeHtml(String(defaultValue))}" placeholder="${escapeHtml(param.description || '')}">`;
            }
            const guide = getUsageGuideForParam(descriptor, param.name);
            const helper = guide?.recommendation || param.description || '';
            const helperHtml = helper
                ? `<div class="integrated-param-help">${escapeHtml(String(helper))}</div>`
                : '';
            parts.push(`
                <div class="integrated-input-item">
                    <div class="integrated-input-label-row">
                        <span class="integrated-input-label">${label}</span>
                        ${tooltipHtml}
                    </div>
                    ${inputHtml}
                    ${helperHtml}
                </div>
            `);
        });
        parts.push(buildUsagePresetsPanel(descriptor, 'integrated-modal'));
        parts.push('</div>');
    }

    if (databases.length) {
        parts.push('<div class="integrated-run-modal-group"><div class="integrated-run-modal-group-title">Databases</div>');
        databases.forEach(db => {
            const key = db.param_name || db.name;
            const id = `modal-db-${key}`;
            const required = db.required !== false ? '<span class="integrated-input-required">Required</span>' : '';
            const scopeHtml = db.scope
                ? `<div class="integrated-db-scope">${escapeHtml(db.scope)}</div>`
                : '';
            // 数据库路径由后端 build_database_paths 自动解析，此处仅展示提示
            parts.push(`
                <div class="integrated-input-item">
                    <div class="integrated-input-label-row"><span class="integrated-input-label">${escapeHtml(db.label || key)}</span>${required}</div>
                    <input type="text" class="ui-field integrated-managed-field" id="${id}" value="" readonly placeholder="自动使用设置中配置的数据库路径">
                </div>
            `);
        });
        parts.push('</div>');
    }

    if (!parts.length) {
        parts.push('<div class="integrated-input-empty">No declared inputs. You can submit directly.</div>');
    }

    formEl.innerHTML = parts.join('');
    if (databases.length) {
        databases.forEach(db => {
            if (!db || !db.scope) return;
            const key = db.param_name || db.name;
            const id = `modal-db-${key}`;
            const inputEl = document.getElementById(id);
            if (!inputEl || !inputEl.parentElement) return;
            const scopeDiv = document.createElement('div');
            scopeDiv.className = 'integrated-db-scope';
            scopeDiv.textContent = String(db.scope);
            inputEl.parentElement.appendChild(scopeDiv);
        });
    }
}

function runIntegratedRunModal() {
    if (!integratedRunModalContext || !integratedRunModalContext.toolId) {
        return;
    }

    const toolId = integratedRunModalContext.toolId;
    const descriptor = integratedRunModalContext.descriptor || {};
    const params = {};

    const inputs = descriptor.inputs || [];
    for (const input of inputs) {
        const value = document.getElementById(`modal-input-${input.name}`)?.value?.trim();
        if (input.required !== false && !value) {
            showNotice(`Missing required input: ${input.label || input.name}`, 'warning');
            return;
        }
        if (value) params[input.name] = value;
    }

    const parameters = descriptor.parameters || [];
    parameters.forEach(param => {
        const element = document.getElementById(`modal-param-${param.name}`);
        if (!element) return;
        let value = element.value;
        if (param.type === 'int' || param.type === 'integer') value = parseInt(value, 10);
        else if (param.type === 'float' || param.type === 'number') value = parseFloat(value);
        else if (param.type === 'bool' || param.type === 'boolean') value = value === 'true';
        params[param.name] = value;
    });

    const databases = descriptor.databases || [];
    for (const db of databases) {
        const key = db.param_name || db.name;
        const el = document.getElementById(`modal-db-${key}`);
        const value = el?.value?.trim();
        // readonly 空值 = 后端 build_database_paths 自动解析，跳过前端校验
        if (el && el.readOnly && !value) continue;
        if (db.required !== false && !value) {
            showNotice(`Missing required database path: ${db.label || key}`, 'warning');
            return;
        }
        if (value) params[key] = value;
    }

    const confirmBtn = document.getElementById('integrated-run-modal-confirm');
    if (confirmBtn) {
        confirmBtn.disabled = true;
        confirmBtn.textContent = 'Submitting...';
    }

    bridgeToolsService.runTool(toolId, JSON.stringify(params));
    closeIntegratedRunModal();
}

function closeIntegratedRunModal() {
    const modal = document.getElementById('integrated-run-modal');
    if (modal) modal.classList.remove('show');
    const confirmBtn = document.getElementById('integrated-run-modal-confirm');
    if (confirmBtn) {
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Submit';
    }
}

function goToIntegratedRunTool() {
    if (!integratedRunModalContext || !integratedRunModalContext.toolId) {
        closeIntegratedRunModal();
        return;
    }

    const toolId = integratedRunModalContext.toolId;
    closeIntegratedRunModal();

    switchTab('tools');
    selectTool(toolId);

    const panel = document.getElementById('right-panel');
    if (panel && panel.scrollIntoView) {
        panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function initializeIntegratedSectionToggles() {
    document.querySelectorAll('.section-toggle-btn').forEach(function(btn) {
        if (btn.dataset.bound === '1') {
            return;
        }
        btn.dataset.bound = '1';
        btn.addEventListener('click', function() {
            const targetId = btn.dataset.target;
            const body = document.getElementById(targetId);
            if (!body) {
                return;
            }
            const willCollapse = !body.classList.contains('collapsed');
            setSectionCollapsed(targetId, willCollapse);
        });
    });
}

function initializeIntegratedResultTabs() {
    document.querySelectorAll('.integrated-result-tab').forEach(function(btn) {
        if (btn.dataset.bound === '1') {
            return;
        }
        btn.dataset.bound = '1';
        btn.addEventListener('click', function() {
            const tab = String(btn.dataset.resultTab || '').trim();
            if (!tab) {
                return;
            }
            switchIntegratedResultTab(tab);
        });
    });
}

function switchIntegratedResultTab(tabName) {
    const activeTab = String(tabName || 'overview').trim() || 'overview';
    document.querySelectorAll('.integrated-result-tab').forEach(function(btn) {
        btn.classList.toggle('active', btn.dataset.resultTab === activeTab);
    });
    document.querySelectorAll('.result-tab-panel').forEach(function(panel) {
        const shouldShow = panel.classList.contains(`result-tab-${activeTab}`);
        const panelVisible = panel.dataset.panelVisible !== '0';
        setHidden(panel, !(shouldShow && panelVisible));
    });
}

function getIntegratedTablePayload(view) {
    const table = (view && view.table && typeof view.table === 'object') ? view.table : {};
    return {
        table,
        columns: Array.isArray(table.columns) ? table.columns : (Array.isArray(view?.columns) ? view.columns : []),
        rows: Array.isArray(table.rows) ? table.rows : (Array.isArray(view?.rows) ? view.rows : []),
    };
}

function getIntegratedCharts(chartInput) {
    return Array.isArray(chartInput) ? chartInput : (chartInput ? [chartInput] : []);
}

function hasIntegratedChartData(chartInput) {
    return getIntegratedCharts(chartInput).some(chart => {
        if (!chart || typeof chart !== 'object') {
            return false;
        }
        if (Array.isArray(chart.data) && chart.data.length > 0) {
            return true;
        }
        return Array.isArray(chart.series) && chart.series.some(series => Array.isArray(series?.data) && series.data.length > 0);
    });
}

function getIntegratedHtmlArtifact(artifacts) {
    const normalizedArtifacts = sortIntegratedArtifacts(Array.isArray(artifacts) ? artifacts : []);
    const hintedHtmlArtifact = normalizedArtifacts.find(item => (
        item
        && item.available
        && item.local_path
        && item.viewer_hint === 'html'
    ));
    if (hintedHtmlArtifact) {
        return hintedHtmlArtifact;
    }
    const availableArtifact = normalizedArtifacts.find(item => (
        item
        && item.available
        && item.local_path
        && typeof item.name === 'string'
        && item.name.toLowerCase().endsWith('.html')
    ));
    if (availableArtifact) {
        return availableArtifact;
    }
    return normalizedArtifacts.find(item => (
        item
        && typeof item.name === 'string'
        && item.name.toLowerCase().endsWith('.html')
    )) || null;
}

function getArtifactPriority(item) {
    if (!item || typeof item !== 'object') {
        return 999;
    }
    const role = String(item.display_role || '').trim();
    const hint = String(item.viewer_hint || '').trim();
    if (role === 'primary_result' && hint === 'html') return 0;
    if (role === 'report' && hint === 'html') return 1;
    if (role === 'primary_result' && hint === 'table') return 2;
    if (role === 'supporting_result') return 3;
    if (role === 'provenance') return 4;
    if (role === 'download') return 5;
    return 6;
}

function sortIntegratedArtifacts(artifacts) {
    const normalizedArtifacts = Array.isArray(artifacts) ? artifacts.slice() : [];
    normalizedArtifacts.sort(function(a, b) {
        const scoreDiff = getArtifactPriority(a) - getArtifactPriority(b);
        if (scoreDiff !== 0) {
            return scoreDiff;
        }
        return String(a?.name || '').localeCompare(String(b?.name || ''));
    });
    return normalizedArtifacts;
}

function getIntegratedViewerStrategy(view) {
    const archetype = String(view?.archetype || '').trim();
    const mode = INTEGRATED_ARCHETYPE_VIEWER_STRATEGIES[archetype] || 'table-first';
    const primaryViewer = mode.replace('-first', '');
    return {
        archetype,
        mode,
        primaryViewer,
        requiredViewers: Array.isArray(INTEGRATED_REQUIRED_VIEWERS_BY_ARCHETYPE[archetype])
            ? INTEGRATED_REQUIRED_VIEWERS_BY_ARCHETYPE[archetype]
            : [],
    };
}

function buildIntegratedViewerState(view) {
    const artifacts = Array.isArray(view?.artifacts) ? view.artifacts : [];
    const tablePayload = getIntegratedTablePayload(view);
    const htmlArtifact = getIntegratedHtmlArtifact(artifacts);
    const strategy = getIntegratedViewerStrategy(view);
    const availability = {
        table: tablePayload.columns.length > 0 && tablePayload.rows.length > 0,
        chart: hasIntegratedChartData(view?.charts || view?.chart || null),
        html: Boolean(htmlArtifact && htmlArtifact.available && htmlArtifact.local_path),
        files: artifacts.some(item => item && item.available && (item.local_path || item.remote_path)),
        sections: Array.isArray(view?.sections) && view.sections.length > 0,
    };
    const viewerErrors = {};
    strategy.requiredViewers.forEach(function(viewer) {
        if (availability[viewer]) {
            return;
        }
        viewerErrors[viewer] = `当前结果 archetype=${strategy.archetype || 'unknown'} 要求 ${strategy.mode} 主 viewer，但 execution 未提供${viewer}数据。`;
    });
    return {
        strategy,
        availability,
        viewerErrors,
        table: tablePayload,
        htmlArtifact,
        primaryTab: strategy.primaryViewer === 'files' ? 'files' : 'result',
    };
}

function hasIntegratedResultContent(view) {
    const tablePayload = getIntegratedTablePayload(view);
    if (tablePayload.rows.length > 0) {
        return true;
    }

    if (hasIntegratedChartData(view?.charts || view?.chart || null)) {
        return true;
    }

    const artifacts = Array.isArray(view?.artifacts) ? view.artifacts : [];
    return Boolean(getIntegratedHtmlArtifact(artifacts));
}

function getDefaultIntegratedResultTab(view, options = {}) {
    const sourceMode = String(options.sourceMode || 'workflow').trim() || 'workflow';
    if (sourceMode !== 'history') {
        return 'overview';
    }

    const viewerState = buildIntegratedViewerState(view);
    return viewerState.primaryTab;
}

function setSectionCollapsed(targetId, collapsed) {
    const body = document.getElementById(targetId);
    if (!body) {
        return;
    }
    body.classList.toggle('collapsed', collapsed);

    const btn = document.querySelector(`.section-toggle-btn[data-target="${targetId}"]`);
    if (btn) {
        btn.textContent = collapsed ? '展开' : '收起';
        btn.setAttribute('aria-expanded', String(!collapsed));
    }
}

function normalizePresetLabel(label) {
    return String(label || '').toLowerCase();
}

function getRecommendedPreset(descriptor) {
    const usage = descriptor?.usage || {};
    const presets = Array.isArray(usage.presets) ? usage.presets : [];
    if (!presets.length) {
        return null;
    }
    const byId = presets.find(p => String(p?.id || '').toLowerCase() === 'standard');
    if (byId) {
        return byId;
    }
    const byLabel = presets.find(p => normalizePresetLabel(p?.label).includes('recommended'));
    if (byLabel) {
        return byLabel;
    }
    return presets[0];
}

function getUsageGuideForParam(descriptor, paramName) {
    const guides = descriptor?.usage?.parameter_guide;
    if (!Array.isArray(guides)) {
        return null;
    }
    return guides.find(item => String(item?.name || '') === String(paramName || '')) || null;
}

function getRecommendedValueFromUsage(descriptor, paramName) {
    const preset = getRecommendedPreset(descriptor);
    if (!preset || !preset.params || typeof preset.params !== 'object') {
        return undefined;
    }
    if (!Object.prototype.hasOwnProperty.call(preset.params, paramName)) {
        return undefined;
    }
    return preset.params[paramName];
}

function buildParamTooltipText(param, descriptor) {
    const parts = [];
    if (param?.description) {
        parts.push(String(param.description).trim());
    }
    if (Array.isArray(param?.range) && param.range.length === 2) {
        parts.push(`范围: ${param.range[0]} ~ ${param.range[1]}`);
    }
    if (Array.isArray(param?.choices) && param.choices.length) {
        parts.push(`可选: ${param.choices.join(', ')}`);
    }
    const guide = getUsageGuideForParam(descriptor, param?.name || '');
    if (guide?.recommendation) {
        parts.push(String(guide.recommendation).trim());
    }
    return parts.filter(Boolean).join('；');
}

function buildUsagePresetsPanel(descriptor, panelIdPrefix) {
    const usage = descriptor?.usage || {};
    const presets = Array.isArray(usage.presets) ? usage.presets : [];
    if (!presets.length) {
        return '';
    }
    const preferred = getRecommendedPreset(descriptor);
    const listHtml = presets.map(preset => {
        const params = (preset && typeof preset.params === 'object') ? preset.params : {};
        const paramPairs = Object.keys(params).map(key => `${key}=${params[key]}`);
        const presetLine = paramPairs.length ? paramPairs.join(', ') : '无显式参数';
        const isRecommended = preferred && preset === preferred;
        const badge = isRecommended ? '<span class="usage-preset-recommended">Recommended</span>' : '';
        const notes = preset?.notes ? `<div class="usage-preset-notes">${escapeHtml(String(preset.notes))}</div>` : '';
        return `
            <div class="usage-preset-row">
                <div class="usage-preset-head">
                    <span class="usage-preset-label">${escapeHtml(String(preset?.label || preset?.id || 'preset'))}</span>
                    ${badge}
                </div>
                <div class="usage-preset-params">${escapeHtml(presetLine)}</div>
                ${notes}
            </div>
        `;
    }).join('');

    const hint = usage.when_to_use
        ? `<div class="usage-presets-hint">${escapeHtml(String(usage.when_to_use))}</div>`
        : '';

    return `
        <details class="usage-presets-panel" id="${escapeHtml(panelIdPrefix)}-usage-presets">
            <summary>推荐预设与填写说明</summary>
            ${hint}
            <div class="usage-presets-list">${listHtml}</div>
        </details>
    `;
}

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
        if (_integratedChartInstances && _integratedChartInstances.length) {
            setTimeout(function() {
                _integratedChartInstances.forEach(instance => {
                    try {
                        instance.resize();
                    } catch (_) {
                        // ignore
                    }
                });
            }, 100);
        }
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
            });
            switchTab('database');
        });
    }, function(error) {
        showNotice(error && error.message ? error.message : '当前版本不支持数据库文件夹扫描', 'warning');
    });
}

function showDatabaseResourceDetail(index) {
    const item = databaseResources[index];
    if (!item) {
        return;
    }
    const lines = window.DatabasePanelRenderer.buildDatabaseResourceDetail(item);
    showNotice(lines.join('\n'), 'success', 6000);
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
    renderIntegratedFeature(feature, view, { sourceMode });
}

function renderIntegratedFeature(feature, view, options = {}) {
    const emptyState = document.getElementById('integrated-empty-state');
    const detail = document.getElementById('integrated-detail');
    const statusChip = document.getElementById('integrated-status-chip');
    const stateDetail = document.getElementById('feature-state-detail');
    const kicker = document.getElementById('feature-kicker');
    const viewerState = buildIntegratedViewerState(view);
    const sourceMode = String(options.sourceMode || selectedIntegratedViewSource || 'workflow').trim() || 'workflow';
    const isHistoryResult = sourceMode === 'history';

    if (!feature || !view) {
        setHidden(emptyState, false);
        setHidden(detail, true);
        if (statusChip) {
            statusChip.textContent = '待选择功能';
            statusChip.dataset.status = 'pending';
        }
        if (stateDetail) stateDetail.textContent = '请选择左侧功能或通过运行历史进入结果。';
        return;
    }

    setHidden(emptyState, true);
    setHidden(detail, false);
    if (detail) detail.dataset.sourceMode = sourceMode;
    if (statusChip) {
        statusChip.textContent = view?.status?.label || feature.badge || '已选择';
        statusChip.dataset.status = String(view?.status?.state || (isHistoryResult ? 'completed' : 'pending')).trim() || 'pending';
    }
    if (kicker) kicker.textContent = isHistoryResult ? `Result Shell · ${viewerState.strategy.mode}` : 'Workflow Entry';

    document.getElementById('feature-title').textContent = view.title || feature.name || feature.id;
    document.getElementById('feature-description').textContent = view.description || '';
    if (stateDetail) {
        const executionId = String(view?.provenance?.execution_id || view?.hero?.execution_id || '').trim();
        stateDetail.textContent = isHistoryResult
            ? `当前为统一结果壳视图，主 viewer 策略为 ${viewerState.strategy.mode}${executionId ? `，execution_id: ${executionId}` : ''}。`
            : String(view?.status?.detail || '可从这里查看输入要求，并继续提交新的运行。');
    }

    initializeIntegratedSectionToggles();
    initializeIntegratedResultTabs();
    setSectionCollapsed('integrated-run-body', true);
    setSectionCollapsed('artifact-list-wrap', true);

    renderIntegratedRunEntry(feature, view, { hidden: isHistoryResult });
    window.ResultViewerRenderers.renderSummaryGrid({
        container: document.getElementById('summary-grid'),
        summaryItems: view.summary || [],
        escapeHtml,
    });
    window.ResultViewerRenderers.renderArtifactList({
        container: document.getElementById('artifact-list'),
        artifacts: view.artifacts || [],
        requiredMessage: viewerState.viewerErrors.files || '',
        sortIntegratedArtifacts,
        openLocalArtifact,
        escapeHtml,
    });
    window.ResultViewerRenderers.renderIntegratedProvenance({
        container: document.getElementById('integrated-provenance-list'),
        provenance: view.provenance || {},
        hero: view.hero || {},
        escapeHtml,
    });
    window.ResultViewerRenderers.renderIntegratedSections({
        card: document.getElementById('integrated-sections-card'),
        container: document.getElementById('integrated-sections-list'),
        sections: view.sections || [],
        requiredMessage: viewerState.viewerErrors.sections || '',
        setHidden,
        escapeHtml,
    });
    renderIntegratedHtmlPreview(view.artifacts || [], { requiredMessage: viewerState.viewerErrors.html || '' });
    renderIntegratedTable(viewerState.table.columns || [], viewerState.table.rows || [], { requiredMessage: viewerState.viewerErrors.table || '' });
    renderIntegratedChart(view.charts || view.chart || null, { requiredMessage: viewerState.viewerErrors.chart || '' });
    switchIntegratedResultTab(getDefaultIntegratedResultTab(view, { sourceMode }));

    // 动态更新表标题和 badge
    const resultsTitle = document.getElementById('results-card-title');
    if (resultsTitle) resultsTitle.textContent = viewerState.table.table.title || view.table_title || '分析结果';
    const resultsBadge = document.getElementById('results-card-badge');
    if (resultsBadge) resultsBadge.textContent = view.table_badge || viewerState.strategy.mode;

    const subtitleEl = document.getElementById('results-card-subtitle');
    if (subtitleEl) {
        subtitleEl.textContent = viewerState.viewerErrors[viewerState.strategy.primaryViewer]
            || viewerState.table.table.subtitle
            || view.table_subtitle
            || '分析结果将在此处展示。';
    }
}

function renderIntegratedRunEntry(feature, view, options = {}) {
    const card = document.getElementById('integrated-run-card');
    const hint = document.getElementById('integrated-run-hint');
    const list = document.getElementById('integrated-input-list');
    const badge = document.getElementById('integrated-run-badge');
    const runBtn = document.getElementById('integrated-run-btn');

    if (!card || !hint || !list || !badge || !runBtn) {
        return;
    }

    if (options.hidden) {
        setHidden(card, true);
        return;
    }

    const toolId = getIntegratedToolId(feature, view);
    if (!toolId) {
        setHidden(card, true);
        return;
    }

    setHidden(card, false);
    const supportedTools = Array.isArray(view?.tool_ids) ? view.tool_ids.filter(Boolean) : [];
    badge.textContent = toolId;
    hint.textContent = '在这里查看输入要求，点击右侧按钮可直接进入插件工作台配置输入文件并提交任务。';
    if (supportedTools.length > 1) {
        hint.textContent = '支持多分类工具（Centrifuge / Kraken2），可在运行弹窗切换并自动刷新参数。';
    }
    runBtn.disabled = false;
    list.innerHTML = '<div class="integrated-input-empty">正在读取输入要求…</div>';

    const cached = toolDescriptorCache[toolId];
    if (cached) {
        updateIntegratedRunEntryFromDescriptor(feature?.id, toolId, cached);
        return;
    }

    if (!bridge || !bridge.get_tool_descriptor) {
        list.innerHTML = '<div class="integrated-input-empty">工具描述符不可用，暂时无法显示输入要求。</div>';
        return;
    }

    bridgeToolsService.getToolDescriptor(toolId, function(json) {
        try {
            const descriptor = JSON.parse(json || '{}');
            toolDescriptorCache[toolId] = descriptor;
            updateIntegratedRunEntryFromDescriptor(feature?.id, toolId, descriptor);
        } catch (error) {
            console.error('Failed to parse integrated tool descriptor:', error);
            if (selectedIntegratedFeatureId === feature?.id) {
                list.innerHTML = '<div class="integrated-input-empty">输入要求解析失败。</div>';
            }
        }
    }, function() {
        if (selectedIntegratedFeatureId === feature?.id) {
            list.innerHTML = '<div class="integrated-input-empty">工具描述符不可用，暂时无法显示输入要求。</div>';
        }
    });
}

function updateIntegratedRunEntryFromDescriptor(featureId, toolId, descriptor) {
    if (selectedIntegratedFeatureId !== featureId) {
        return;
    }

    const list = document.getElementById('integrated-input-list');
    const hint = document.getElementById('integrated-run-hint');
    const runBtn = document.getElementById('integrated-run-btn');
    if (!list || !hint || !runBtn) {
        return;
    }

    const inputs = descriptor.inputs || [];
    const paramCount = (descriptor.parameters || []).length;
    const dbCount = (descriptor.databases || []).length;
    hint.textContent = `需要输入文件 ${inputs.length} 项，参数 ${paramCount} 项，数据库 ${dbCount} 项；点击右侧按钮可直接进入插件工作台配置并提交任务。`;
    runBtn.textContent = `配置并运行 ${descriptor.name || toolId}`;

    if (inputs.length === 0) {
        list.innerHTML = '<div class="integrated-input-empty">当前工具没有声明输入文件，可直接进入插件工作台查看参数并运行。</div>';
        return;
    }

    list.innerHTML = inputs.map(input => `
        <div class="integrated-input-item">
            <div class="integrated-input-label-row">
                <span class="integrated-input-label">${escapeHtml(input.label || input.name || '输入文件')}</span>
                ${input.required !== false ? '<span class="integrated-input-required">必填</span>' : ''}
            </div>
            <div class="integrated-input-desc">${escapeHtml(
                input.description || '请在插件工作台中选择文件'
            )}</div>
        </div>
    `).join('');
}

function openLocalArtifact(localPath) {
    const path = String(localPath || '').trim();
    if (!path) {
        showNotice('本地结果文件路径为空');
        return;
    }
    bridgeResultsService.openLocalFile(path, function(json) {
        try {
            const payload = JSON.parse(json || '{}');
            if (payload.status !== 'ok') {
                showNotice(payload.message || '打开本地结果文件失败');
            }
        } catch (error) {
            console.error('Failed to open local artifact:', error);
            showNotice('打开本地结果文件失败');
        }
    }, function(error) {
        showNotice(error && error.message ? error.message : '本地文件打开接口不可用');
    });
}

function localPathToFileUrl(localPath) {
    const raw = String(localPath || '').trim();
    if (!raw) {
        return '';
    }
    const normalized = raw.replace(/\\/g, '/');
    if (/^[a-zA-Z]:\//.test(normalized)) {
        return `file:///${encodeURI(normalized)}`;
    }
    if (normalized.startsWith('/')) {
        return `file://${encodeURI(normalized)}`;
    }
    return encodeURI(normalized);
}

function renderIntegratedHtmlPreview(artifacts, options = {}) {
    const card = document.getElementById('integrated-html-card');
    const frame = document.getElementById('integrated-html-frame');
    const empty = document.getElementById('integrated-html-empty');
    const titleEl = document.getElementById('html-preview-title');
    const openBtn = document.getElementById('html-open-btn');

    if (!card || !frame || !empty || !titleEl || !openBtn) {
        return;
    }

    const htmlArtifact = getIntegratedHtmlArtifact(artifacts || []);
    const htmlReady = Boolean(htmlArtifact && htmlArtifact.available && htmlArtifact.local_path);

    if (!htmlReady) {
        card.dataset.panelVisible = options.requiredMessage ? '1' : '0';
        setHidden(card, !options.requiredMessage);
        setHidden(frame, true);
        frame.src = 'about:blank';
        setHidden(openBtn, true);
        setHidden(empty, !options.requiredMessage);
        empty.textContent = options.requiredMessage || '';
        return;
    }

    const fileUrl = localPathToFileUrl(htmlArtifact.local_path);
    card.dataset.panelVisible = '1';
    setHidden(card, false);
    titleEl.textContent = htmlArtifact.name || 'HTML 预览';
    setHidden(frame, !fileUrl);
    frame.src = fileUrl || 'about:blank';
    setHidden(empty, Boolean(fileUrl));
    empty.textContent = fileUrl ? '' : 'HTML 文件已同步，但当前无法生成预览地址。';
    setHidden(openBtn, false);
    openBtn.onclick = function() {
        openLocalArtifact(htmlArtifact.local_path);
    };
}

function renderIntegratedTable(columns, rows, options = {}) {
    const head = document.getElementById('integrated-table-head');
    const body = document.getElementById('integrated-table-body');
    const card = document.getElementById('integrated-table-card');
    if (!head || !body) {
        return;
    }

    head.innerHTML = `<tr>${columns.map(column => {
        const key = column.key || '';
        return `<th class="col-${escapeHtml(key)}">${escapeHtml(column.label || key || '')}</th>`;
    }).join('')}</tr>`;
    body.innerHTML = '';

    const table = head.closest('table');
    if (table) table.classList.toggle('wide-table', columns.length > 6);

    if (card) {
        const shouldShow = columns.length > 0 || rows.length > 0 || Boolean(options.requiredMessage);
        card.dataset.panelVisible = shouldShow ? '1' : '0';
    }

    if (!rows.length) {
        body.innerHTML = `<tr><td colspan="${columns.length || 1}" class="empty-row">${escapeHtml(options.requiredMessage || '当前 execution 未提供表格结果。')}</td></tr>`;
        return;
    }

    rows.forEach(row => {
        const tr = document.createElement('tr');
        tr.innerHTML = columns.map(column => {
            const value = row[column.key] ?? '-';
            const text = escapeHtml(String(value));
            const rawKey = column.key || 'value';
            const key = escapeHtml(rawKey);
            const extraClass = getIntegratedColumnCellClass(rawKey);
            return `<td class="col-${key}${extraClass ? ` ${extraClass}` : ''}" title="${text}">${text}</td>`;
        }).join('');
        body.appendChild(tr);
    });
}

function getIntegratedColumnCellClass(columnKey) {
    const truncateColumns = new Set(['region_id', 'position']);
    const wrapColumns = new Set(['pathogen', 'forward_primer', 'reverse_primer', 'amplicon', 'target_sequence', 'amplicon_seq', 'name']);

    if (truncateColumns.has(columnKey)) {
        return 'table-cell-truncate';
    }
    if (wrapColumns.has(columnKey)) {
        return 'table-cell-wrap';
    }
    return '';
}

let _integratedChartInstances = [];
let _integratedChartResizeBound = false;

function disposeIntegratedCharts() {
    _integratedChartInstances.forEach(instance => {
        try {
            instance.dispose();
        } catch (_) {
            // ignore
        }
    });
    _integratedChartInstances = [];
}

function getDomainColor(name) {
    const text = String(name || '').toLowerCase();
    if (text.includes('virus') || text.includes('viruses')) return '#ef4444';
    if (text.includes('fungi') || text.includes('fungus')) return '#22c55e';
    if (text.includes('bacteria')) return '#3b82f6';
    if (text.includes('archaea')) return '#f59e0b';
    return '#64748b';
}

function getChartDomain(item) {
    const text = String(item?.name || '').toLowerCase();
    if (text.includes('virus')) return 'Viruses';
    if (text.includes('fung')) return 'Fungi';
    if (text.includes('archaea')) return 'Archaea';
    return 'Bacteria';
}

function ensureEchartsLoaded() {
    if (typeof echarts !== 'undefined') {
        return;
    }
    if (_echartsLoadRequested) {
        return;
    }
    _echartsLoadRequested = true;

    const script = document.createElement('script');
    script.src = 'echarts.min.js';
    script.async = false;
    script.onload = function() {
        console.log('echarts dynamically loaded');
    };
    script.onerror = function() {
        console.error('Failed to load echarts.min.js');
        showNotice('Failed to load local chart engine: echarts.min.js', 'error', 5000);
    };
    document.head.appendChild(script);
}

function renderIntegratedChart(chartInput, options = {}, retryCount = 0) {
    const card = document.getElementById('integrated-chart-card');
    const container = document.getElementById('integrated-chart-container');
    const titleEl = document.getElementById('chart-card-title');

    if (_integratedChartRetryTimer) {
        clearTimeout(_integratedChartRetryTimer);
        _integratedChartRetryTimer = null;
    }

    disposeIntegratedCharts();

    const charts = getIntegratedCharts(chartInput);
    const validCharts = charts.filter(hasIntegratedChartData);
    if (!validCharts.length) {
        if (card) card.dataset.panelVisible = options.requiredMessage ? '1' : '0';
        setHidden(card, !options.requiredMessage);
        if (container) {
            container.innerHTML = `<div class="${options.requiredMessage ? 'task-error-banner' : 'integrated-input-empty'}">${escapeHtml(options.requiredMessage || '暂无图表数据。')}</div>`;
        }
        return;
    }

    if (card) card.dataset.panelVisible = '1';
    setHidden(card, false);
    if (titleEl) titleEl.textContent = validCharts.length > 1 ? '图表视图' : (validCharts[0].title || '图表');
    if (!container || typeof echarts === 'undefined') {
        if (container && typeof echarts === 'undefined') {
            ensureEchartsLoaded();
            if (retryCount < 20) {
                container.innerHTML = '<div class="integrated-input-empty">Loading chart engine...</div>';
                _integratedChartRetryTimer = window.setTimeout(function() {
                    renderIntegratedChart(chartInput, options, retryCount + 1);
                }, 250);
            } else {
                container.innerHTML = '<div class="integrated-input-empty">Chart engine unavailable (echarts not loaded).</div>';
            }
        }
        return;
    }

    container.innerHTML = '';

    validCharts.forEach((chartData, index) => {
        const chartWrap = document.createElement('div');
        chartWrap.className = 'integrated-chart-item';
        const localTitle = document.createElement('div');
        localTitle.className = 'integrated-chart-item-title';
        localTitle.textContent = chartData.title || `图表 ${index + 1}`;
        const chartDiv = document.createElement('div');
        chartDiv.className = 'integrated-chart-item-canvas';
        chartDiv.style.width = '100%';
        const dynamicHeight = (chartData.type === 'abundance_bar' || chartData.type === 'amplicon_performance')
            ? `${Math.min(Math.max(300, chartData.data.length * 22 + 90), 680)}px`
            : '360px';
        chartDiv.style.height = dynamicHeight;
        chartWrap.appendChild(localTitle);
        chartWrap.appendChild(chartDiv);
        container.appendChild(chartWrap);

        const instance = echarts.init(chartDiv);
        const chartType = chartData.type || 'pie';
        let option = {};

        if (chartType === 'funnel') {
            option = {
                tooltip: {
                    trigger: 'item',
                    formatter: function(params) {
                        return `${params.name}<br/>Reads: ${Number(params.value || 0).toLocaleString()}`;
                    }
                },
                series: [{
                    type: 'funnel',
                    left: '10%',
                    top: 20,
                    bottom: 20,
                    width: '80%',
                    minSize: '30%',
                    maxSize: '100%',
                    sort: 'descending',
                    gap: 4,
                    label: {
                        show: true,
                        position: 'inside',
                        formatter: function(params) {
                            return `${params.name}\n${Number(params.value || 0).toLocaleString()}`;
                        }
                    },
                    itemStyle: {
                        borderColor: '#fff',
                        borderWidth: 1,
                    },
                    data: chartData.data.map((item, i) => ({
                        name: item.name,
                        value: item.value,
                        itemStyle: { color: ['#0ea5e9', '#38bdf8', '#22c55e', '#f59e0b', '#ef4444'][i % 5] }
                    })),
                }]
            };
        } else if (chartType === 'abundance_bar') {
            const sorted = chartData.data.slice().sort((a, b) => (b.reads || 0) - (a.reads || 0));
            const names = sorted.map(d => d.name);
            const reads = sorted.map(d => d.reads || 0);
            const colors = sorted.map(d => getDomainColor(getChartDomain(d)));
            option = {
                tooltip: {
                    trigger: 'axis',
                    axisPointer: { type: 'shadow' },
                    formatter: function(params) {
                        const p = params && params[0] ? params[0] : null;
                        if (!p) return '';
                        const row = sorted[p.dataIndex] || {};
                        const domain = getChartDomain(row);
                        return `${row.name || '-'}<br/>Reads: ${(row.reads || 0).toLocaleString()}<br/>Domain: ${domain}`;
                    }
                },
                grid: { left: '28%', right: '8%', top: 20, bottom: 30 },
                xAxis: { type: 'value', axisLabel: { fontSize: 10 } },
                yAxis: {
                    type: 'category',
                    data: names,
                    inverse: true,
                    axisLabel: { fontSize: 10, width: 220, overflow: 'truncate' }
                },
                series: [{
                    type: 'bar',
                    data: reads.map((value, i) => ({ value, itemStyle: { color: colors[i] } })),
                    barMaxWidth: 18,
                }]
            };
        } else if (chartType === 'coverage_depth') {
            const seriesData = chartData.data.map(d => [d.position, d.depth]);
            option = {
                tooltip: {
                    trigger: 'axis',
                    formatter: function(params) {
                        const p = params && params[0] ? params[0] : null;
                        if (!p) return '';
                        return `Position: ${p.value[0]}<br/>Depth: ${Number(p.value[1]).toFixed(2)}`;
                    }
                },
                grid: { left: '8%', right: '5%', top: 20, bottom: 40 },
                xAxis: { type: 'value', name: 'Position', axisLabel: { fontSize: 10 } },
                yAxis: { type: 'value', name: 'Depth', axisLabel: { fontSize: 10 } },
                series: [{
                    type: 'line',
                    showSymbol: false,
                    smooth: true,
                    lineStyle: { width: 1.5, color: '#2563eb' },
                    areaStyle: { color: 'rgba(37,99,235,0.15)' },
                    data: seriesData,
                }]
            };
        } else if (chartType === 'amplicon_performance') {
            const names = chartData.data.map(d => d.name);
            const reads = chartData.data.map(d => d.reads || 0);
            const breadth = chartData.data.map(d => d.breadth || 0);
            option = {
                tooltip: {
                    trigger: 'axis',
                    axisPointer: { type: 'shadow' },
                    formatter: function(params) {
                        const p1 = params.find(p => p.seriesName === 'Mean Depth');
                        const p2 = params.find(p => p.seriesName === 'Breadth (%)');
                        return `${params[0].axisValue}<br/>Mean Depth: ${p1 ? Number(p1.value).toFixed(2) : '-'}<br/>Breadth: ${p2 ? Number(p2.value).toFixed(2) : '-'}%`;
                    }
                },
                legend: { top: 0, textStyle: { fontSize: 10 } },
                grid: { left: '22%', right: '8%', top: 35, bottom: 30 },
                xAxis: { type: 'value', axisLabel: { fontSize: 10 } },
                yAxis: { type: 'category', data: names, inverse: true, axisLabel: { fontSize: 10, width: 200, overflow: 'truncate' } },
                series: [
                    {
                        name: 'Mean Depth',
                        type: 'bar',
                        data: reads,
                        barMaxWidth: 16,
                        itemStyle: { color: '#0ea5e9' }
                    },
                    {
                        name: 'Breadth (%)',
                        type: 'line',
                        xAxisIndex: 0,
                        yAxisIndex: 0,
                        data: breadth,
                        symbolSize: 4,
                        lineStyle: { color: '#f59e0b', width: 1.5 },
                        itemStyle: { color: '#f59e0b' }
                    }
                ]
            };
        } else if (chartType === 'sunburst') {
            option = {
                tooltip: {
                    trigger: 'item',
                    formatter: function(params) {
                        const value = params && params.value != null ? `${params.value}%` : '-';
                        return `${params.name}<br/>占比: ${value}`;
                    }
                },
                series: [{
                    type: 'sunburst',
                    radius: [0, '92%'],
                    sort: null,
                    emphasis: { focus: 'ancestor' },
                    data: chartData.data,
                    minAngle: 2,
                    labelLayout: { hideOverlap: true },
                    label: {
                        rotate: 'tangential',
                        fontSize: 10,
                        overflow: 'truncate',
                        width: 96,
                        formatter: function(params) {
                            const value = Number(params?.value || 0);
                            const depth = Number(params?.treePathInfo?.length || 0);
                            if (depth >= 4 && value < 3) return '';
                            if (depth >= 3 && value < 1.2) return '';
                            return params.name || '';
                        }
                    },
                    levels: [
                        {},
                        {
                            r0: '0%',
                            r: '28%',
                            label: { rotate: 0, fontSize: 13 }
                        },
                        {
                            r0: '28%',
                            r: '58%',
                            label: { rotate: 'tangential', fontSize: 11 }
                        },
                        {
                            r0: '58%',
                            r: '92%',
                            label: { rotate: 'tangential', fontSize: 9 }
                        }
                    ],
                }]
            };
        } else if (chartType === 'bar') {
            if (Array.isArray(chartData.series) && Array.isArray(chartData.categories)) {
                option = {
                    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
                    legend: { top: 0, textStyle: { fontSize: 10 } },
                    grid: { left: '8%', right: '5%', top: 36, bottom: 40 },
                    xAxis: { type: 'category', data: chartData.categories, axisLabel: { fontSize: 10, interval: 0 } },
                    yAxis: { type: 'value', axisLabel: { fontSize: 10 } },
                    series: chartData.series.map(series => ({
                        name: series.name || 'Series',
                        type: 'bar',
                        data: Array.isArray(series.data) ? series.data : [],
                        itemStyle: { color: series.color || '#3b82f6' },
                        barMaxWidth: 28,
                    })),
                };
            } else {
                const names = chartData.data.map(d => d.name);
                const values = chartData.data.map(d => d.value);
                const colors = chartData.data.map(d => {
                    if (d.status === 'suboptimal') return '#f59e0b';
                    if (d.status === 'no_candidate') return '#ef4444';
                    return '#3b82f6';
                });
                option = {
                    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
                    grid: { left: '22%', right: '8%', top: 20, bottom: 30 },
                    xAxis: { type: 'value', name: 'bp', axisLabel: { fontSize: 10 } },
                    yAxis: { type: 'category', data: names, inverse: true, axisLabel: { fontSize: 10, width: 140, overflow: 'truncate' } },
                    series: [{
                        type: 'bar',
                        data: values.map((v, i) => ({ value: v, itemStyle: { color: colors[i] } })),
                        barMaxWidth: 18,
                        label: { show: true, position: 'right', formatter: '{c} bp', fontSize: 10, color: '#64748b' },
                    }]
                };
            }
        } else {
            option = {
                tooltip: {
                    trigger: 'item',
                    formatter: function(params) {
                        const reads = params.data.reads != null ? params.data.reads.toLocaleString() : '-';
                        return `${params.name}<br/>占比: ${params.percent}%<br/>Reads: ${reads}`;
                    }
                },
                series: [{
                    type: 'pie',
                    radius: ['30%', '65%'],
                    center: ['50%', '50%'],
                    data: chartData.data.map(d => ({ name: d.name, value: d.value, reads: d.reads || 0 })),
                    label: { formatter: '{b}\n{d}%', fontSize: 11 },
                    emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.2)' } }
                }]
            };
        }

        instance.setOption(option);
        _integratedChartInstances.push(instance);
    });

    if (!_integratedChartResizeBound) {
        _integratedChartResizeBound = true;
        const chartContainer = document.getElementById('integrated-chart-container');
        if (chartContainer && typeof ResizeObserver !== 'undefined') {
            const ro = new ResizeObserver(() => {
                _integratedChartInstances.forEach(instance => {
                    try { instance.resize(); } catch (_) {}
                });
            });
            ro.observe(chartContainer);
        }
        // 保留 window resize 作为 fallback
        window.addEventListener('resize', function() {
            _integratedChartInstances.forEach(instance => {
                try {
                    instance.resize();
                } catch (_) {
                    // ignore
                }
            });
        });
    }
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function loadTools() {
    console.log('Loading tools...');
    bridgeToolsService.loadTools(function(json) {
        try {
            allTools = JSON.parse(json);
            console.log(`✓ Loaded ${allTools.length} tools`);
            renderToolsList();
        } catch (e) {
            console.error('Failed to parse tools:', e);
        }
    }, function(error) {
        console.error('Failed to load tools:', error);
    });
}

function renderToolsList(searchQuery = '') {
    const container = document.getElementById('tools-list');
    container.innerHTML = '';

    // 过滤工具
    let filtered = allTools;

    // 按搜索词过滤
    if (searchQuery) {
        const query = searchQuery.toLowerCase();
        filtered = filtered.filter(tool => {
            const searchText = `${tool.id} ${tool.name} ${tool.description}`.toLowerCase();
            return searchText.includes(query);
        });
    }

    // 更新计数
    document.getElementById('count').textContent = `${filtered.length} tools`;

    if (filtered.length === 0) {
        container.innerHTML = '<div class="integrated-input-empty tools-empty-state">No tools found</div>';
        return;
    }

    // 按分类分组
    const grouped = {};
    filtered.forEach(tool => {
        const category = tool.category || 'unknown';
        if (!grouped[category]) {
            grouped[category] = [];
        }
        grouped[category].push(tool);
    });

    // 渲染分类组
    Object.keys(grouped).sort().forEach(category => {
        const group = createCategoryGroup(category, grouped[category]);
        container.appendChild(group);
    });
}

function createCategoryGroup(category, tools) {
    const group = document.createElement('div');
    group.className = 'category-group';

    // 分类标题
    const header = document.createElement('div');
    header.className = 'category-header';
    header.innerHTML = `
        <span>${getCategoryName(category)}</span>
        <span class="category-arrow">▼</span>
    `;

    // 点击折叠/展开
    header.addEventListener('click', function() {
        group.classList.toggle('collapsed');
    });

    // 工具列表
    const toolsContainer = document.createElement('div');
    toolsContainer.className = 'category-tools';

    tools.forEach(tool => {
        const item = createToolItem(tool);
        toolsContainer.appendChild(item);
    });

    group.appendChild(header);
    group.appendChild(toolsContainer);

    return group;
}

function createToolItem(tool) {
    const item = document.createElement('div');
    item.className = 'tool-item';
    item.dataset.toolId = tool.id;

    item.innerHTML = `
        <div class="tool-name">${tool.name}</div>
        <div class="tool-desc">${tool.description || 'No description available'}</div>
    `;

    item.addEventListener('click', function() {
        selectTool(tool.id);
    });

    return item;
}

function getCategoryName(category) {
    const names = {
        'qc': '质量控制 (QC)',
        'host_removal': '宿主去除',
        'taxonomy': '物种分类',
        'binning': '分箱',
        'quality': '质量评估',
        'annotation': '功能注释',
        'blast': '序列比对',
        'unknown': '其他'
    };
    return names[category] || category.toUpperCase();
}

function selectTool(toolId) {
    console.log('Selecting tool:', toolId);
    selectedToolId = toolId;

    // 更新列表选中状态
    document.querySelectorAll('.tool-item').forEach(item => {
        item.classList.remove('selected');
    });
    const item = document.querySelector(`[data-tool-id="${toolId}"]`);
    if (item) {
        item.classList.add('selected');
    }

    // 通知 Python
    bridgeToolsService.selectTool(toolId);

    // 获取工具详细信息
    bridgeToolsService.getToolDescriptor(toolId, function(json) {
        try {
            selectedDescriptor = JSON.parse(json);
            toolDescriptorCache[toolId] = selectedDescriptor;
            console.log('Tool descriptor:', selectedDescriptor);
            showToolPanel(selectedDescriptor);
        } catch (e) {
            console.error('Failed to parse descriptor:', e);
        }
    }, function(error) {
        console.error('Failed to load descriptor:', error);
    });
}

function showToolPanel(descriptor) {
    // 隐藏占位符，显示内容
    setHidden(document.querySelector('.panel-placeholder'), true);
    setHidden(document.getElementById('panel-content'), false);

    // 更新头部信息
    document.getElementById('tool-name').textContent = descriptor.name || descriptor.id;
    document.getElementById('tool-id').textContent = descriptor.id;
    document.getElementById('tool-version').textContent = 'v' + (descriptor.version || 'unknown');
    document.getElementById('tool-category').textContent = getCategoryName(descriptor.category || 'unknown');

    // 渲染输入文件
    renderInputs(descriptor.inputs || []);

    // 渲染参数
    renderParams(descriptor.parameters || []);

    // 渲染数据库
    if (descriptor.databases && descriptor.databases.length > 0) {
        setHidden(document.getElementById('databases-section'), false);
        renderDatabases(descriptor.databases);
    } else {
        setHidden(document.getElementById('databases-section'), true);
    }
}

function renderInputs(inputs) {
    const container = document.getElementById('inputs-container');
    container.innerHTML = '';

    if (inputs.length === 0) {
        container.innerHTML = '<div class="integrated-input-empty">No input files required</div>';
        return;
    }

    inputs.forEach(input => {
        const group = document.createElement('div');
        group.className = 'form-group';

        const required = input.required !== false ? '<span class="required">*</span>' : '';
        const browseFilter = getInputBrowseFilter(input, selectedDescriptor || {});
        const validator = getInputSelectionValidator(input, selectedDescriptor || {});

        group.innerHTML = `
            <label class="form-label">
                ${input.label || input.name}${required}
            </label>
            <div class="input-group">
                <input type="text"
                       class="ui-field"
                       id="input-${input.name}"
                       placeholder="${input.description || 'Select file...'}"
                       readonly>
                <button class="ui-button ui-button--secondary ui-button--sm form-browse-btn" onclick="browseFile('input-${input.name}', '${browseFilter}', '${validator}')">Browse...</button>
            </div>
            ${input.description ? `<div class="form-help">${input.description}</div>` : ''}
        `;

        container.appendChild(group);
    });
}

function renderParams(params) {
    const container = document.getElementById('params-container');
    container.innerHTML = '';

    if (params.length === 0) {
        container.innerHTML = '<div class="integrated-input-empty">No parameters to configure</div>';
        return;
    }

    params.forEach(param => {
        const group = document.createElement('div');
        group.className = 'form-group';

        const required = param.required !== false ? '<span class="required">*</span>' : '';
        const recommendedValue = getRecommendedValueFromUsage(selectedDescriptor, param.name);
        const defaultValue = recommendedValue !== undefined
            ? recommendedValue
            : (param.default !== undefined ? param.default : '');
        const tooltipText = buildParamTooltipText(param, selectedDescriptor);
        const tooltipHtml = tooltipText
            ? `<button type="button" class="help-icon-btn" aria-label="参数说明" aria-expanded="false" data-help-text="${escapeHtml(tooltipText)}" title="${escapeHtml(tooltipText)}">?</button>`
            : '';

        let inputHtml = '';
        if (param.type === 'int' || param.type === 'integer') {
            inputHtml = `<input type="number" class="ui-field" id="param-${param.name}" value="${defaultValue}" step="1">`;
        } else if (param.type === 'float' || param.type === 'number') {
            inputHtml = `<input type="number" class="ui-field" id="param-${param.name}" value="${defaultValue}" step="0.01">`;
        } else if (param.type === 'bool' || param.type === 'boolean') {
            inputHtml = `
                <select class="ui-field" id="param-${param.name}">
                    <option value="true" ${defaultValue === true ? 'selected' : ''}>Yes</option>
                    <option value="false" ${defaultValue === false ? 'selected' : ''}>No</option>
                </select>
            `;
        } else {
            inputHtml = `<input type="text" class="ui-field" id="param-${param.name}" value="${defaultValue}" placeholder="${param.description || ''}">`;
        }

        const guide = getUsageGuideForParam(selectedDescriptor, param.name);
        const helper = guide?.recommendation || param.description || '';
        const helperHtml = helper ? `<div class="form-help">${escapeHtml(String(helper))}</div>` : '';

        group.innerHTML = `
            <div class="form-label-row">
                <label class="form-label" for="param-${param.name}">
                    ${param.label || param.name}${required}
                </label>
                ${tooltipHtml}
            </div>
            ${inputHtml}
            ${helperHtml}
        `;

        container.appendChild(group);
    });

    const usagePanelHtml = buildUsagePresetsPanel(selectedDescriptor || {}, 'tool-panel');
    if (usagePanelHtml) {
        const usageWrap = document.createElement('div');
        usageWrap.className = 'form-group';
        usageWrap.innerHTML = usagePanelHtml;
        container.appendChild(usageWrap);
    }
}

function renderDatabases(databases) {
    const container = document.getElementById('databases-container');
    container.innerHTML = '';

    databases.forEach(db => {
        const group = document.createElement('div');
        group.className = 'form-group';

        const required = db.required !== false ? '<span class="required">*</span>' : '';
        const defaultVal = db.default || '';

        group.innerHTML = `
            <label class="form-label">
                ${db.label || (db.param_name || db.name)}${required}
            </label>
            <div class="input-group">
                <input type="text"
                       class="ui-field"
                       id="db-${db.param_name || db.name}"
                       placeholder="${db.description || '远端数据库路径...'}"
                       title="${defaultVal}"
                       value="${defaultVal}">
                <button class="ui-button ui-button--secondary ui-button--sm form-browse-btn" onclick="browseRemoteFile('db-${db.param_name || db.name}')">Browse...</button>
            </div>
            ${db.description ? `<div class="form-help">${db.description}</div>` : ''}
        `;

        container.appendChild(group);
    });
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

function browseRemoteFile(inputId) {
    console.log('Browse remote file:', inputId);
    bridgeToolsService.browseRemoteFile(inputId, function(rawResult) {
        if (!rawResult) {
            return;
        }

        let payload = null;
        try {
            payload = JSON.parse(rawResult);
        } catch (e) {
            payload = { path: rawResult, error: '' };
        }

        const filePath = String(payload?.path || '');
        const errorMessage = String(payload?.error || '');

        if (errorMessage) {
            showNotice(errorMessage);
            return;
        }

        if (filePath) {
            const el = document.getElementById(inputId);
            el.value = filePath;
            el.title = filePath;
        }
    }, function(error) {
        showNotice(error && error.message ? error.message : '远端文件选择接口不可用');
    });
}

function browseFile(inputId, fileFilter = '所有文件 (*.*)', validator = '') {
    console.log('Browse file:', inputId);
    bridgeToolsService.browseFile(inputId, fileFilter, validator, function(rawResult) {
        if (!rawResult) {
            return;
        }

        let payload = null;
        try {
            payload = JSON.parse(rawResult);
        } catch (e) {
            payload = { path: rawResult, error: '' };
        }

        const filePath = String(payload?.path || '');
        const errorMessage = String(payload?.error || '');

        if (!filePath) {
            return;
        }

        if (errorMessage) {
            showNotice(errorMessage);
            return;
        }

        if (validator === 'primer_genomes_bundle' && !isPrimerGenomesBundlePath(filePath)) {
            showNotice('仅支持 .zip/.tar/.tar.gz/.tgz 或单个 .fasta/.fna/.fa 文件');
            return;
        }

        document.getElementById(inputId).value = filePath;
    }, function(error) {
        showNotice(error && error.message ? error.message : '文件选择接口不可用');
    });
}

function runTool() {
    if (!selectedToolId || !selectedDescriptor) {
        showNotice('请先选择工具', 'warning');
        return;
    }

    console.log('Running tool:', selectedToolId);

    const params = {};

    const inputs = selectedDescriptor.inputs || [];
    for (const input of inputs) {
        const value = document.getElementById(`input-${input.name}`)?.value?.trim();
        if (input.required !== false && !value) {
            showNotice(`缺少必填输入: ${input.label || input.name}`, 'warning');
            return;
        }
        if (value) {
            params[input.name] = value;
        }
    }

    const parameters = selectedDescriptor.parameters || [];
    parameters.forEach(param => {
        const element = document.getElementById(`param-${param.name}`);
        if (element) {
            let value = element.value;
            if (param.type === 'int' || param.type === 'integer') {
                value = parseInt(value, 10);
            } else if (param.type === 'float' || param.type === 'number') {
                value = parseFloat(value);
            } else if (param.type === 'bool' || param.type === 'boolean') {
                value = value === 'true';
            }
            params[param.name] = value;
        }
    });

    const databases = selectedDescriptor.databases || [];
    for (const db of databases) {
        const key = db.param_name || db.name;
        const value = document.getElementById(`db-${key}`)?.value?.trim();
        if (db.required !== false && !value) {
            showNotice(`缺少必填数据库路径: ${db.label || key}`, 'warning');
            return;
        }
        if (value) {
            params[key] = value;
        }
    }

    console.log('Parameters:', params);

    const runBtn = document.getElementById('run-btn');
    if (runBtn) {
        runBtn.disabled = true;
        runBtn.textContent = '运行中...';
    }

    bridgeToolsService.runTool(selectedToolId, JSON.stringify(params));
}

function onRunResult(result) {
    const runBtn = document.getElementById('run-btn');
    if (runBtn) {
        runBtn.disabled = false;
        runBtn.textContent = '▶ 运行工具';
    }

    if (!result || !result.status) {
        showNotice('运行结果未知');
        return;
    }

    if (result.status === 'ok') {
        const executionId = String(result.execution_id || '').trim();
        if (!executionId) {
            showNotice('任务已提交，但缺少 execution_id，无法自动定位');
            loadHistory();
            loadIntegratedWorkbench(true);
            return;
        }

        showNotice(result.message || '任务已提交', 'success');
        loadIntegratedWorkbench(true);
        window.HistoryResultLoader.openExecutionWithRuntime(executionId, {
            status: 'pending',
            fetchRemoteStatus: false,
            noticeMessage: '已定位到新提交任务，请在运行历史查看状态',
        });
        return;
    }

    if (result.status === 'no_project') {
        showNotice(result.message || '请先选择项目', 'warning');
        return;
    }

    if (result.status === 'no_sample') {
        showNotice(result.message || '样本不存在', 'warning');
        return;
    }

    showNotice(result.message || '任务提交失败');
}
function clearForm() {
    // 清空所有输入
    document.querySelectorAll('.ui-field').forEach(input => {
        if (!input.readOnly) {
            input.value = '';
        }
    });
}

// 加载执行历史
function loadHistory() {
    console.log('Loading execution history...');
    bridgeHistoryService.loadExecutionHistory(function(json) {
        try {
            historyRecords = JSON.parse(json);
            console.log(`✓ Loaded ${historyRecords.length} execution records`);
            const historySearch = document.getElementById('history-search');
            renderHistoryPanelView(window.HistoryPanelRenderer.filterHistoryRecords({
                query: String(historySearch?.value || ''),
                historyRecords,
                allTools,
            }));
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

function buildExecutionRemoteStatusHtml(data) {
    const remoteStatusRaw = String(data.remote_status || '').toUpperCase();
    const localStatusRaw = String(data.local_status || '').toLowerCase();
    const heartbeatAgeValue = Number(data.heartbeat_age_sec);
    const heartbeatAge = Number.isFinite(heartbeatAgeValue) ? `${heartbeatAgeValue} s` : '-';
    const hasRecentHeartbeat = Number.isFinite(heartbeatAgeValue) && heartbeatAgeValue <= 180;

    let serverRuntimeStatus = '状态未知';
    if (data.screen_running === true) {
        if (hasRecentHeartbeat) {
            serverRuntimeStatus = '服务器活跃';
        } else if (Number.isFinite(heartbeatAgeValue)) {
            serverRuntimeStatus = `疑似挂起（心跳超时 ${heartbeatAgeValue}s）`;
        } else {
            serverRuntimeStatus = '进程在跑（未检测到心跳）';
        }
    } else if (data.screen_running === false) {
        if (remoteStatusRaw === 'COMPLETED' || remoteStatusRaw === 'SUCCESS' || localStatusRaw === 'completed') {
            serverRuntimeStatus = '已结束（完成）';
        } else if (remoteStatusRaw === 'FAILED' || remoteStatusRaw === 'ERROR' || localStatusRaw === 'failed') {
            serverRuntimeStatus = '已结束（失败）';
        } else {
            serverRuntimeStatus = '未检测到进程';
        }
    } else if (remoteStatusRaw === 'RUNNING' && hasRecentHeartbeat) {
        serverRuntimeStatus = '服务器活跃';
    }

    const screenText = data.screen_running == null ? '-' : (data.screen_running ? 'running' : 'not found');
    const logTail = escapeHtml(String(data.log_tail || '').trim());
    const logBlock = logTail ? `<pre class="task-details-pre task-details-pre-scroll">${logTail}</pre>` : '';
    return `
        <div class="task-error-banner task-info-banner">
            服务器状态: ${escapeHtml(serverRuntimeStatus)} ｜ 远端状态: ${escapeHtml(String(data.remote_status || '-'))} ｜ screen: ${escapeHtml(screenText)} ｜ 心跳: ${escapeHtml(heartbeatAge)} ｜ exit_code: ${escapeHtml(String(data.exit_code || '-'))}
        </div>
        <pre class="task-details-pre task-details-pre-offset">${escapeHtml(JSON.stringify({
            execution_id: data.execution_id,
            tool_id: data.tool_id,
            sample_id: data.sample_id,
            local_status: data.local_status,
            task_dir: data.task_dir,
            ssh_connected: data.ssh_connected,
            remote_status: data.remote_status || '',
            screen_running: data.screen_running,
            exit_code: data.exit_code || '',
            heartbeat: data.heartbeat || '',
            heartbeat_age_sec: heartbeatAge,
            local_error: data.local_error || ''
        }, null, 2))}</pre>
        ${logBlock}
    `;
}

function toggleExecutionRemoteStatus(executionId, rowEl) {
    if (!executionId || !rowEl) {
        return;
    }
    if (remoteStatusLoading.has(executionId)) {
        showNotice('远端状态查询进行中...', 'warning', 2000);
        return;
    }

    const detailsEl = rowEl.querySelector('.task-details');
    if (!detailsEl) {
        return;
    }

    const existing = detailsEl.querySelector('.remote-status-block');
    if (existing) {
        existing.remove();
        rowEl.classList.remove('expanded');
        return;
    }

    showNotice('正在查询远端执行状态...', 'warning', 6000);
    remoteStatusLoading.add(executionId);
    bridgeHistoryService.getExecutionRemoteStatus(executionId, function(json) {
        try {
            const payload = JSON.parse(json || '{}');
            if (payload.status !== 'ok' || !payload.data) {
                showNotice(payload.message || '读取远端状态失败');
                return;
            }

            const block = document.createElement('div');
            block.className = 'remote-status-block';
            block.innerHTML = buildExecutionRemoteStatusHtml(payload.data);
            detailsEl.prepend(block);
            rowEl.classList.add('expanded');
            showNotice('远端状态已更新', 'success', 2500);
        } catch (e) {
            console.error('Failed to parse remote status:', e);
            showNotice('远端状态解析失败');
        } finally {
            remoteStatusLoading.delete(executionId);
        }
    }, function(error) {
        remoteStatusLoading.delete(executionId);
        showNotice(error && error.message ? error.message : '远端状态接口不可用');
    });
}

function deleteHistoryExecution(executionId) {
    if (!executionId) {
        return;
    }
    if (!window.confirm('确定删除这条任务历史吗？\n仅从历史列表隐藏，不删除结果文件。')) {
        return;
    }

    bridgeHistoryService.deleteExecutionHistory(executionId, function(json) {
        try {
            const payload = JSON.parse(json);
            if (payload.status !== 'ok') {
                showNotice(payload.message || '删除任务记录失败');
                return;
            }
            showNotice(payload.message || '任务记录已删除', 'success');
            loadHistory();
        } catch (e) {
            console.error('Failed to parse delete execution result:', e);
            showNotice('删除任务记录失败');
        }
    }, function(error) {
        showNotice(error && error.message ? error.message : '删除任务接口不可用');
    });
}

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

const renderHistoryPanelView = function(history) {
    window.HistoryPanelRenderer.renderHistoryPanel({
        container: document.getElementById('history-container'),
        history,
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
        deleteHistoryExecution,
        toggleExecutionRemoteStatus,
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
};
