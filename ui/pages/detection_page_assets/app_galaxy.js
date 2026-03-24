let bridge = null;
let allTools = [];
let selectedToolId = null;
let selectedDescriptor = null;
let integratedWorkbench = null;
let selectedIntegratedFeatureId = null;
let pendingIntegratedFeatureId = null;
let databaseResources = [];
let historyRecords = [];
const toolDescriptorCache = {};
let noticeHideTimer = null;
let integratedRunModalContext = null;
let _integratedChartRetryTimer = null;
let _echartsLoadRequested = false;
const remoteStatusLoading = new Set();

console.log('=== Galaxy Style Detection Page ===');

function ensureNoticeContainer() {
    let container = document.getElementById('inline-notice-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'inline-notice-container';
        container.style.position = 'fixed';
        container.style.top = '18px';
        container.style.right = '18px';
        container.style.zIndex = '9999';
        container.style.pointerEvents = 'none';
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
        ? { bg: '#ecfdf3', border: '#86efac', color: '#166534', icon: '✓' }
        : type === 'warning'
            ? { bg: '#fffbeb', border: '#fcd34d', color: '#92400e', icon: '⚠' }
            : { bg: '#fef2f2', border: '#fca5a5', color: '#991b1b', icon: 'ⓘ' };

    container.innerHTML = `
        <div role="alert" style="
            pointer-events: auto;
            min-width: 320px;
            max-width: 520px;
            border-radius: 10px;
            border: 1px solid ${tone.border};
            background: ${tone.bg};
            color: ${tone.color};
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.14);
            padding: 12px 14px;
            display: flex;
            align-items: flex-start;
            gap: 10px;
            line-height: 1.5;
            font-size: 13px;
            white-space: pre-wrap;
        ">
            <div style="font-weight: 700; font-size: 15px; line-height: 1; margin-top: 2px;">${tone.icon}</div>
            <div style="flex:1;">${escapeHtml(text)}</div>
            <button type="button" style="
                border: none;
                background: transparent;
                color: ${tone.color};
                font-size: 16px;
                font-weight: 700;
                cursor: pointer;
                line-height: 1;
                padding: 0 2px;
            " onclick="dismissNotice()" aria-label="关闭">×</button>
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
            switchTab(tab);
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
            renderHistory(filterHistoryRecords(String(e.target.value || '')));
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
});

function getIntegratedToolId(feature, view) {
    return (view && view.tool_ids && view.tool_ids[0])
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
    modal.className = 'integrated-run-modal';
    modal.innerHTML = `
        <div class="integrated-run-modal-backdrop" data-close="1"></div>
        <div class="integrated-run-modal-card" role="dialog" aria-modal="true" aria-labelledby="integrated-run-modal-title">
            <div class="integrated-run-modal-header">
                <h3 id="integrated-run-modal-title">Run Entry</h3>
                <button class="integrated-run-modal-close" type="button" id="integrated-run-modal-close" aria-label="Close">&times;</button>
            </div>
            <div class="integrated-run-modal-body">
                <div class="integrated-run-modal-line"><span>Feature</span><strong id="integrated-run-modal-feature">-</strong></div>
                <div class="integrated-run-modal-line"><span>Tool</span><strong id="integrated-run-modal-tool">-</strong></div>
                <div class="integrated-run-modal-line" id="integrated-run-modal-tool-select-row" style="display:none">
                    <span>分类工具</span>
                    <div id="integrated-run-modal-tool-switch" class="integrated-tool-switch" role="group" aria-label="分类工具选择"></div>
                </div>
                <div class="integrated-run-modal-hint" id="integrated-run-modal-hint">Fill fields in this popup and submit directly, or open plugin workbench.</div>
                <div class="integrated-run-modal-form" id="integrated-run-modal-form"></div>
            </div>
            <div class="integrated-run-modal-actions">
                <button class="btn-secondary" type="button" id="integrated-run-modal-cancel">Cancel</button>
                <button class="btn-secondary" type="button" id="integrated-run-modal-open-tools">Open Tools</button>
                <button class="btn-primary" type="button" id="integrated-run-modal-confirm">Submit</button>
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
        bridge.get_tool_descriptor(nextToolId, function(json) {
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
        });
    };

    if (toolSelectRowEl && toolSwitchEl) {
        if (toolIds.length > 1) {
            toolSelectRowEl.style.display = '';
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
            toolSelectRowEl.style.display = 'none';
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
                        <input type="text" class="form-input" id="${id}" placeholder="${escapeHtml(input.description || 'Select file')}" readonly>
                        <button class="btn-browse" type="button" onclick="browseFile('${id}', '${browseFilter}', '${validator}')">Browse...</button>
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
                ? `<button type="button" class="help-icon-btn" aria-label="参数说明" title="${escapeHtml(tooltipText)}">?</button>`
                : '';
            let inputHtml = '';
            if (param.type === 'int' || param.type === 'integer') {
                inputHtml = `<input type="number" class="form-input" id="${id}" value="${defaultValue}" step="1">`;
            } else if (param.type === 'float' || param.type === 'number') {
                inputHtml = `<input type="number" class="form-input" id="${id}" value="${defaultValue}" step="0.01">`;
            } else if (param.type === 'bool' || param.type === 'boolean') {
                inputHtml = `<select class="form-input" id="${id}"><option value="true" ${defaultValue === true ? 'selected' : ''}>Yes</option><option value="false" ${defaultValue === false ? 'selected' : ''}>No</option></select>`;
            } else {
                inputHtml = `<input type="text" class="form-input" id="${id}" value="${escapeHtml(String(defaultValue))}" placeholder="${escapeHtml(param.description || '')}">`;
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
                    <input type="text" class="form-input" id="${id}" value="" readonly placeholder="自动使用设置中配置的数据库路径" style="color:#6c757d;background:#f8f9fa;cursor:default">
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

    bridge.run_tool(toolId, JSON.stringify(params));
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

    // 切换到历史标签时加载数据
    if (tab === 'history') {
        loadHistory();
    }

    if (tab === 'integrated') {
        loadIntegratedWorkbench(true);
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

function scanLocalDatabaseFolder() {
    if (!bridge || !bridge.browse_directory || !bridge.scan_local_database_resources) {
        showNotice('当前版本不支持数据库文件夹扫描', 'warning');
        return;
    }

    bridge.browse_directory(function(rawResult) {
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

        bridge.scan_local_database_resources(dirPath, function(scanResult) {
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
            renderDatabaseResources(databaseResources);
            switchTab('database');
        });
    });
}

function renderDatabaseResources(resources) {
    const grid = document.getElementById('database-grid');
    const empty = document.getElementById('database-empty-state');
    if (!grid || !empty) {
        return;
    }

    if (!resources.length) {
        grid.style.display = 'none';
        grid.innerHTML = '';
        empty.style.display = 'flex';
        return;
    }

    empty.style.display = 'none';
    grid.style.display = 'grid';
    grid.innerHTML = resources.map(function(item, index) {
        const stats = item.stats || {};
        const summary = item.type === 'directory'
            ? `FASTA ${stats.fasta_count || 0} · BLAST 索引 ${stats.blast_index_count || 0}`
            : `大小 ${(Number(stats.size_bytes || 0) / 1024 / 1024).toFixed(2)} MB`;
        const initial = escapeHtml(String(item.name || '?').slice(0, 1));
        return `
            <article class="database-resource-card">
                <div class="database-resource-badge">${initial}</div>
                <div class="database-resource-title">${escapeHtml(item.name || '')}</div>
                <div class="database-resource-desc">${escapeHtml(item.description || '暂无描述')}</div>
                <div class="database-resource-meta">${escapeHtml(summary)}</div>
                <button class="btn-secondary database-detail-btn" type="button" onclick="showDatabaseResourceDetail(${index})">查看详情</button>
            </article>
        `;
    }).join('');
}

function showDatabaseResourceDetail(index) {
    const item = databaseResources[index];
    if (!item) {
        return;
    }
    const stats = item.stats || {};
    const lines = [
        `名称: ${item.name || ''}`,
        `类型: ${item.type || ''}`,
        `路径: ${item.path || ''}`,
        `说明: ${item.description || ''}`,
    ];
    if (item.type === 'directory') {
        lines.push(`FASTA 文件数: ${stats.fasta_count || 0}`);
        lines.push(`BLAST 索引数: ${stats.blast_index_count || 0}`);
    } else if (typeof stats.size_bytes !== 'undefined') {
        lines.push(`文件大小: ${(Number(stats.size_bytes || 0) / 1024 / 1024).toFixed(2)} MB`);
    }
    showNotice(lines.join('\n'), 'success', 6000);
}

function loadIntegratedWorkbench(forceRefresh = false) {
    if (!bridge || !bridge.get_integrated_workbench_config) {
        return;
    }

    if (integratedWorkbench && !forceRefresh) {
        renderIntegratedWorkbench();
        return;
    }

    bridge.get_integrated_workbench_config(function(json) {
        try {
            integratedWorkbench = JSON.parse(json);
            renderIntegratedWorkbench();
        } catch (e) {
            console.error('Failed to parse integrated workbench config:', e);
        }
    });
}

function renderIntegratedWorkbench() {
    if (!integratedWorkbench) {
        return;
    }

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

    container.innerHTML = '';
    const features = integratedWorkbench.features || [];
    features.forEach(feature => {
        const item = document.createElement('button');
        item.className = 'integrated-feature-item';
        item.dataset.featureId = feature.id;
        const badgeHtml = feature.badge
            ? `<span class="integrated-feature-badge">${escapeHtml(feature.badge)}</span>`
            : '';
        item.innerHTML = `
            <div class="integrated-feature-main">
                <div class="integrated-feature-name">${escapeHtml(feature.name || feature.id)}</div>
                <div class="integrated-feature-desc">${escapeHtml(feature.description || '')}</div>
            </div>
            ${badgeHtml}
        `;
        item.addEventListener('click', function() {
            selectIntegratedFeature(feature.id);
        });
        container.appendChild(item);
    });

    let preferredFeature = null;
    if (pendingIntegratedFeatureId) {
        preferredFeature = features.find(feature => feature.id === pendingIntegratedFeatureId) || null;
    }
    if (!preferredFeature && selectedIntegratedFeatureId) {
        preferredFeature = features.find(feature => feature.id === selectedIntegratedFeatureId) || null;
    }
    if (!preferredFeature) {
        preferredFeature = features.find(feature => feature.status === 'active') || features[0];
    }
    if (preferredFeature) {
        selectIntegratedFeature(preferredFeature.id);
    }
    pendingIntegratedFeatureId = null;
}

function selectIntegratedFeature(featureId) {
    if (!integratedWorkbench) {
        return;
    }

    selectedIntegratedFeatureId = featureId;
    document.querySelectorAll('.integrated-feature-item').forEach(item => {
        item.classList.toggle('active', item.dataset.featureId === featureId);
    });

    const features = integratedWorkbench.features || [];
    const feature = features.find(item => item.id === featureId);
    const view = (integratedWorkbench.views || {})[featureId];
    renderIntegratedFeature(feature, view);
}

function renderIntegratedFeature(feature, view) {
    const emptyState = document.getElementById('integrated-empty-state');
    const detail = document.getElementById('integrated-detail');
    const statusChip = document.getElementById('integrated-status-chip');

    if (!feature || !view) {
        if (emptyState) emptyState.style.display = 'flex';
        if (detail) detail.style.display = 'none';
        if (statusChip) statusChip.textContent = '待选择功能';
        return;
    }

    if (emptyState) emptyState.style.display = 'none';
    if (detail) detail.style.display = 'flex';
    if (statusChip) statusChip.textContent = feature.badge || '已选择';

    document.getElementById('feature-title').textContent = view.title || feature.name || feature.id;
    document.getElementById('feature-description').textContent = view.description || '';

    initializeIntegratedSectionToggles();
    setSectionCollapsed('integrated-run-body', true);
    setSectionCollapsed('artifact-list-wrap', true);

    renderIntegratedRunEntry(feature, view);
    renderSummaryGrid(view.summary || []);
    renderArtifactList(view.artifacts || []);
    renderIntegratedTable(view.columns || [], view.rows || []);
    renderIntegratedChart(view.charts || view.chart || null);

    // 动态更新表标题和 badge
    const resultsTitle = document.getElementById('results-card-title');
    if (resultsTitle) resultsTitle.textContent = view.table_title || '分析结果';
    const resultsBadge = document.getElementById('results-card-badge');
    if (resultsBadge) resultsBadge.textContent = view.table_badge || (view.artifacts && view.artifacts[0] ? view.artifacts[0].name : '');

    const subtitleEl = document.getElementById('results-card-subtitle');
    if (subtitleEl) subtitleEl.textContent = view.table_subtitle || '分析结果将在此处展示。';
}

function renderIntegratedRunEntry(feature, view) {
    const card = document.getElementById('integrated-run-card');
    const hint = document.getElementById('integrated-run-hint');
    const list = document.getElementById('integrated-input-list');
    const badge = document.getElementById('integrated-run-badge');
    const runBtn = document.getElementById('integrated-run-btn');

    if (!card || !hint || !list || !badge || !runBtn) {
        return;
    }

    const toolId = getIntegratedToolId(feature, view);
    if (!toolId) {
        card.style.display = 'none';
        return;
    }

    card.style.display = 'flex';
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

    bridge.get_tool_descriptor(toolId, function(json) {
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

function renderSummaryGrid(summaryItems) {
    const container = document.getElementById('summary-grid');
    if (!container) {
        return;
    }

    container.innerHTML = '';
    summaryItems.forEach(item => {
        const card = document.createElement('div');
        card.className = `summary-card tone-${item.tone || 'default'}`;
        card.innerHTML = `
            <div class="summary-label">${escapeHtml(item.label || '')}</div>
            <div class="summary-value">${escapeHtml(String(item.value ?? ''))}</div>
        `;
        container.appendChild(card);
    });
}

function renderArtifactList(artifacts) {
    const container = document.getElementById('artifact-list');
    if (!container) {
        return;
    }

    container.innerHTML = '';

    // PDF 报告醒目按钮（置顶）
    const pdfArtifact = artifacts.find(a => a && a.is_pdf_report && a.available && a.local_path);
    if (pdfArtifact) {
        const btn = document.createElement('div');
        btn.className = 'pdf-report-btn';
        btn.innerHTML = `
            <span class="pdf-icon">📄</span>
            <span class="pdf-label">导出 PDF 检测报告</span>
        `;
        btn.addEventListener('click', function() {
            openLocalArtifact(pdfArtifact.local_path);
        });
        container.appendChild(btn);
    }

    artifacts.forEach(item => {
        const li = document.createElement('li');
        if (typeof item === 'string') {
            li.textContent = item;
            container.appendChild(li);
            return;
        }

        const available = Boolean(item && item.available && item.local_path);
        li.className = available ? 'artifact-item available' : 'artifact-item unavailable';
        li.innerHTML = `
            <div class="artifact-main">
                <span class="artifact-name">${escapeHtml(item?.name || '未命名文件')}</span>
                <span class="artifact-state">${available ? '已同步' : '不可用'}</span>
            </div>
            <div class="artifact-path">${escapeHtml(item?.local_path || item?.remote_path || '')}</div>
        `;
        if (available) {
            li.addEventListener('click', function() {
                openLocalArtifact(item.local_path);
            });
        }
        container.appendChild(li);
    });
}

function openLocalArtifact(localPath) {
    const path = String(localPath || '').trim();
    if (!path) {
        showNotice('本地结果文件路径为空');
        return;
    }
    if (!bridge || !bridge.open_local_file) {
        showNotice('本地文件打开接口不可用');
        return;
    }

    bridge.open_local_file(path, function(json) {
        try {
            const payload = JSON.parse(json || '{}');
            if (payload.status !== 'ok') {
                showNotice(payload.message || '打开本地结果文件失败');
            }
        } catch (error) {
            console.error('Failed to open local artifact:', error);
            showNotice('打开本地结果文件失败');
        }
    });
}

function renderIntegratedTable(columns, rows) {
    const head = document.getElementById('integrated-table-head');
    const body = document.getElementById('integrated-table-body');
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

    if (!rows.length) {
        body.innerHTML = `<tr><td colspan="${columns.length || 1}" class="empty-row">暂无结果 — 请通过右侧「执行入口」上传 FASTQ 文件并运行分析</td></tr>`;
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

function renderIntegratedChart(chartInput, retryCount = 0) {
    const card = document.getElementById('integrated-chart-card');
    const container = document.getElementById('integrated-chart-container');
    const titleEl = document.getElementById('chart-card-title');

    if (_integratedChartRetryTimer) {
        clearTimeout(_integratedChartRetryTimer);
        _integratedChartRetryTimer = null;
    }

    disposeIntegratedCharts();

    const charts = Array.isArray(chartInput) ? chartInput : (chartInput ? [chartInput] : []);
    const validCharts = charts.filter(c => c && Array.isArray(c.data) && c.data.length > 0);
    if (!validCharts.length) {
        if (card) card.style.display = 'none';
        return;
    }

    if (card) card.style.display = 'block';
    if (titleEl) titleEl.textContent = validCharts.length > 1 ? '图表视图' : (validCharts[0].title || '图表');
    if (!container || typeof echarts === 'undefined') {
        if (container && typeof echarts === 'undefined') {
            ensureEchartsLoaded();
            if (retryCount < 20) {
                container.innerHTML = '<div class="integrated-input-empty">Loading chart engine...</div>';
                _integratedChartRetryTimer = window.setTimeout(function() {
                    renderIntegratedChart(chartInput, retryCount + 1);
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

        if (chartType === 'abundance_bar') {
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
        } else if (chartType === 'bar') {
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
    bridge.get_tools(function(json) {
        try {
            allTools = JSON.parse(json);
            console.log(`✓ Loaded ${allTools.length} tools`);
            renderToolsList();
        } catch (e) {
            console.error('Failed to parse tools:', e);
        }
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
        container.innerHTML = '<div style="padding: 20px; text-align: center; color: #6c757d; font-size: 12px;">No tools found</div>';
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
    bridge.select_tool(toolId);

    // 获取工具详细信息
    bridge.get_tool_descriptor(toolId, function(json) {
        try {
            selectedDescriptor = JSON.parse(json);
            toolDescriptorCache[toolId] = selectedDescriptor;
            console.log('Tool descriptor:', selectedDescriptor);
            showToolPanel(selectedDescriptor);
        } catch (e) {
            console.error('Failed to parse descriptor:', e);
        }
    });
}

function showToolPanel(descriptor) {
    // 隐藏占位符，显示内容
    document.querySelector('.panel-placeholder').style.display = 'none';
    document.getElementById('panel-content').style.display = 'flex';

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
        document.getElementById('databases-section').style.display = 'block';
        renderDatabases(descriptor.databases);
    } else {
        document.getElementById('databases-section').style.display = 'none';
    }
}

function renderInputs(inputs) {
    const container = document.getElementById('inputs-container');
    container.innerHTML = '';

    if (inputs.length === 0) {
        container.innerHTML = '<div style="color: #6c757d; font-size: 13px;">No input files required</div>';
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
                       class="form-input"
                       id="input-${input.name}"
                       placeholder="${input.description || 'Select file...'}"
                       readonly>
                <button class="btn-browse" onclick="browseFile('input-${input.name}', '${browseFilter}', '${validator}')">Browse...</button>
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
        container.innerHTML = '<div style="color: #6c757d; font-size: 13px;">No parameters to configure</div>';
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
            ? `<button type="button" class="help-icon-btn" aria-label="参数说明" title="${escapeHtml(tooltipText)}">?</button>`
            : '';

        let inputHtml = '';
        if (param.type === 'int' || param.type === 'integer') {
            inputHtml = `<input type="number" class="form-input" id="param-${param.name}" value="${defaultValue}" step="1">`;
        } else if (param.type === 'float' || param.type === 'number') {
            inputHtml = `<input type="number" class="form-input" id="param-${param.name}" value="${defaultValue}" step="0.01">`;
        } else if (param.type === 'bool' || param.type === 'boolean') {
            inputHtml = `
                <select class="form-input" id="param-${param.name}">
                    <option value="true" ${defaultValue === true ? 'selected' : ''}>Yes</option>
                    <option value="false" ${defaultValue === false ? 'selected' : ''}>No</option>
                </select>
            `;
        } else {
            inputHtml = `<input type="text" class="form-input" id="param-${param.name}" value="${defaultValue}" placeholder="${param.description || ''}">`;
        }

        const guide = getUsageGuideForParam(selectedDescriptor, param.name);
        const helper = guide?.recommendation || param.description || '';
        const helperHtml = helper ? `<div class="form-help">${escapeHtml(String(helper))}</div>` : '';

        group.innerHTML = `
            <label class="form-label">
                ${param.label || param.name}${required} ${tooltipHtml}
            </label>
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
                       class="form-input"
                       id="db-${db.param_name || db.name}"
                       placeholder="${db.description || '远端数据库路径...'}"
                       title="${defaultVal}"
                       value="${defaultVal}">
                <button class="btn-browse" onclick="browseRemoteFile('db-${db.param_name || db.name}')">Browse...</button>
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
    bridge.browse_remote_file(inputId, function(rawResult) {
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
    });
}

function browseFile(inputId, fileFilter = '所有文件 (*.*)', validator = '') {
    console.log('Browse file:', inputId);
    bridge.browse_file(inputId, fileFilter, validator, function(rawResult) {
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

    bridge.run_tool(selectedToolId, JSON.stringify(params));
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
        showNotice(result.message || '任务已提交', 'success');
        loadHistory();
        loadIntegratedWorkbench(true);
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
    document.querySelectorAll('.form-input').forEach(input => {
        if (!input.readOnly) {
            input.value = '';
        }
    });
}

// 加载执行历史
function loadHistory() {
    console.log('Loading execution history...');
    
    // 调用 Python 获取执行历史
    bridge.get_execution_history(function(json) {
        try {
            historyRecords = JSON.parse(json);
            console.log(`✓ Loaded ${historyRecords.length} execution records`);
            const historySearch = document.getElementById('history-search');
            renderHistory(filterHistoryRecords(String(historySearch?.value || '')));
        } catch (e) {
            console.error('Failed to parse history:', e);
        }
    });
}

function filterHistoryRecords(query) {
    const keyword = String(query || '').trim().toLowerCase();
    if (!keyword) {
        return historyRecords;
    }
    return historyRecords.filter(record => {
        const toolName = (allTools.find(t => t.id === record.tool_id) || {}).name || record.tool_id;
        const haystack = [
            record.execution_id,
            record.tool_id,
            toolName,
            record.sample_name,
            record.sample_id,
            record.parameters,
            record.status
        ].join(' ').toLowerCase();
        return haystack.includes(keyword);
    });
}

// 渲染执行历史
function loadPrimerResultsFromHistory(executionId) {
    if (!executionId) {
        return;
    }
    if (!bridge || !bridge.get_primer_results_for_execution) {
        showNotice('任务结果加载接口不可用');
        return;
    }

    showNotice('正在加载引物结果...', 'warning', 10000);
    bridge.get_primer_results_for_execution(executionId, function(json) {
        try {
            const payload = JSON.parse(json);
            if (payload.status !== 'ok' || !payload.view) {
                showNotice(payload.message || '任务结果读取失败');
                return;
            }

            if (!integratedWorkbench) {
                integratedWorkbench = { views: {} };
            }
            if (!integratedWorkbench.views) {
                integratedWorkbench.views = {};
            }

            integratedWorkbench.views.primer_design = payload.view;
            pendingIntegratedFeatureId = 'primer_design';
            switchTab('integrated');
            selectIntegratedFeature('primer_design');
            showNotice('已加载该次引物设计结果', 'success');
        } catch (e) {
            console.error('Failed to parse execution primer results:', e);
            showNotice('任务结果解析失败');
        }
    });
}

function loadMultiplexResultsFromHistory(executionId) {
    if (!executionId) {
        return;
    }
    if (!bridge || !bridge.get_multiplex_results_for_execution) {
        showNotice('Multiplex 结果加载接口不可用');
        return;
    }

    showNotice('正在加载 multiplex 结果...', 'warning', 10000);
    bridge.get_multiplex_results_for_execution(executionId, function(json) {
        try {
            const payload = JSON.parse(json);
            if (payload.status !== 'ok' || !payload.view) {
                showNotice(payload.message || 'Multiplex 结果读取失败');
                return;
            }

            if (!integratedWorkbench) {
                integratedWorkbench = { views: {} };
            }
            if (!integratedWorkbench.views) {
                integratedWorkbench.views = {};
            }

            integratedWorkbench.views.multiplex_primer_panel = payload.view;
            pendingIntegratedFeatureId = 'multiplex_primer_panel';
            switchTab('integrated');
            selectIntegratedFeature('multiplex_primer_panel');
            showNotice('已加载该次 multiplex 结果', 'success');
        } catch (e) {
            console.error('Failed to parse execution multiplex results:', e);
            showNotice('Multiplex 结果解析失败');
        }
    });
}

function loadTargetedSeqResultsFromHistory(executionId) {
    if (!executionId) {
        return;
    }
    if (!bridge || !bridge.get_targeted_seq_results_for_execution) {
        showNotice('靶向测序结果加载接口不可用');
        return;
    }

    showNotice('正在加载靶向测序结果...', 'warning', 10000);
    bridge.get_targeted_seq_results_for_execution(executionId, function(json) {
        try {
            const payload = JSON.parse(json);
            if (payload.status !== 'ok' || !payload.view) {
                showNotice(payload.message || '靶向测序结果读取失败');
                return;
            }

            if (!integratedWorkbench) {
                integratedWorkbench = { views: {} };
            }
            if (!integratedWorkbench.views) {
                integratedWorkbench.views = {};
            }

            integratedWorkbench.views.targeted_sequencing = payload.view;
            pendingIntegratedFeatureId = 'targeted_sequencing';
            switchTab('integrated');
            selectIntegratedFeature('targeted_sequencing');
            showNotice('已加载靶向测序分析结果', 'success');
        } catch (e) {
            console.error('Failed to parse targeted seq results:', e);
            showNotice('靶向测序结果解析失败');
        }
    });
}

function loadDetectionResultsFromHistory(executionId) {
    if (!executionId) {
        return;
    }
    if (!bridge || !bridge.get_targeted_seq_results_for_execution) {
        showNotice('未知样品检测结果加载接口不可用');
        return;
    }

    showNotice('正在加载未知样品检测结果...', 'warning', 10000);
    bridge.get_targeted_seq_results_for_execution(executionId, function(json) {
        try {
            const payload = JSON.parse(json);
            if (payload.status !== 'ok' || !payload.view) {
                showNotice(payload.message || '检测结果读取失败');
                return;
            }

            if (!integratedWorkbench) {
                integratedWorkbench = { views: {} };
            }
            if (!integratedWorkbench.views) {
                integratedWorkbench.views = {};
            }

            integratedWorkbench.views.unknown_sample_detection = payload.view;
            pendingIntegratedFeatureId = 'unknown_sample_detection';
            switchTab('integrated');
            selectIntegratedFeature('unknown_sample_detection');
            showNotice('已加载未知样品检测结果', 'success');
        } catch (e) {
            console.error('Failed to parse detection results:', e);
            showNotice('检测结果解析失败');
        }
    });
}

function loadFastpResultsFromHistory(executionId) {
    if (!executionId) {
        return;
    }
    if (!bridge || !bridge.get_fastp_results_for_execution) {
        showNotice('fastp 结果加载接口不可用');
        return;
    }

    showNotice('正在加载 fastp QC 结果...', 'warning', 10000);
    bridge.get_fastp_results_for_execution(executionId, function(json) {
        try {
            const payload = JSON.parse(json);
            if (payload.status !== 'ok' || !payload.view) {
                showNotice(payload.message || 'fastp 结果读取失败');
                return;
            }

            if (!integratedWorkbench) {
                integratedWorkbench = { views: {} };
            }
            if (!integratedWorkbench.views) {
                integratedWorkbench.views = {};
            }

            integratedWorkbench.views.unknown_sample_detection = payload.view;
            pendingIntegratedFeatureId = 'unknown_sample_detection';
            switchTab('integrated');
            selectIntegratedFeature('unknown_sample_detection');
            showNotice('已加载 fastp 质控结果', 'success');
        } catch (e) {
            console.error('Failed to parse fastp results:', e);
            showNotice('fastp 结果解析失败');
        }
    });
}

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
    const logBlock = logTail ? `<pre class="task-details-pre" style="margin-top:8px;max-height:180px;overflow:auto;">${logTail}</pre>` : '';
    return `
        <div class="task-error-banner" style="background:#eef6ff;border-color:#bfdbfe;color:#1e3a8a;">
            服务器状态: ${escapeHtml(serverRuntimeStatus)} ｜ 远端状态: ${escapeHtml(String(data.remote_status || '-'))} ｜ screen: ${escapeHtml(screenText)} ｜ 心跳: ${escapeHtml(heartbeatAge)} ｜ exit_code: ${escapeHtml(String(data.exit_code || '-'))}
        </div>
        <pre class="task-details-pre" style="margin-top:8px;">${escapeHtml(JSON.stringify({
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
    if (!bridge || !bridge.get_execution_remote_status) {
        showNotice('远端状态接口不可用');
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
    bridge.get_execution_remote_status(executionId, function(json) {
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
    });
}

function deleteHistoryExecution(executionId) {
    if (!executionId) {
        return;
    }
    if (!bridge || !bridge.delete_execution_history) {
        showNotice('删除任务接口不可用');
        return;
    }
    if (!window.confirm('确定删除这条任务历史吗？\n仅从历史列表隐藏，不删除结果文件。')) {
        return;
    }

    bridge.delete_execution_history(executionId, function(json) {
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
    });
}

function formatParamsSummary(paramsJson) {
    if (!paramsJson) return '-';
    try {
        const params = typeof paramsJson === 'string' ? JSON.parse(paramsJson) : paramsJson;
        const entries = Object.entries(params).filter(([k, v]) => v !== '' && v !== null && v !== undefined);
        const summary = entries.slice(0, 3).map(([k, v]) => `${k}=${v}`).join(', ');
        return summary || '-';
    } catch (e) { return '-'; }
}

function formatDetailCell(record) {
    if (record.status === 'completed') {
        return `<a href="#" class="detail-link" data-exec-id="${record.execution_id}" data-tool-id="${record.tool_id}">查看</a>`;
    } else if (record.status === 'failed') {
        const errMsg = record.error || '未知错误';
        const short = errMsg.length > 30 ? errMsg.substring(0, 30) + '…' : errMsg;
        return `<span class="error-hint" title="${escapeHtml(errMsg)}">${escapeHtml(short)}</span>`;
    } else if (record.status === 'running') {
        return '<span style="color:#0d6efd;">运行中...</span>';
    }
    return '-';
}

function renderHistory(history) {
    const container = document.getElementById('history-container');
    container.innerHTML = '';

    if (history.length === 0) {
        container.innerHTML = `
            <div class="history-empty-state">
                <div class="history-empty-icon">∅</div>
                <div class="history-empty-title">暂无任务记录</div>
                <div class="history-empty-desc">新的 Primer Design 或 Multiplex Panel Design 任务会在这里显示。</div>
            </div>
        `;
        return;
    }

    history.forEach(record => {
        const row = document.createElement('div');
        row.className = 'task-row';

        const statusText = getStatusText(record.status);
        const statusClass = getStatusClass(record.status);

        const duration = record.completed_at
            ? formatDuration(record.completed_at - record.created_at)
            : '-';
        const durationClass = getDurationClass(record.completed_at ? (record.completed_at - record.created_at) : 0);

        const paramsSummary = formatParamsSummary(record.parameters);

        let prettyJson = '{}';
        try {
            const parsed = typeof record.parameters === 'string' ? JSON.parse(record.parameters) : record.parameters;
            prettyJson = JSON.stringify(parsed, null, 4);
        } catch(e) {
            prettyJson = record.parameters || '';
        }

        const toolName = (allTools.find(t => t.id === record.tool_id) || {}).name || record.tool_id;
        const sampleNameRaw = record.sample_name || record.sample_id || '-';
        const sampleName = escapeHtml(sampleNameRaw);
        const createdLabel = formatRelativeTime(record.created_at);
        const exactTime = formatExactTime(record.created_at);
        const hasDetails = record.status === 'failed' || prettyJson;

        let detailsHtml = '';
        if (record.status === 'failed' && record.error) {
            detailsHtml += `<div class="task-error-banner">错误信息: ${escapeHtml(record.error)}</div>`;
        }
        detailsHtml += `<pre class="task-details-pre">${escapeHtml(prettyJson)}</pre>`;

        row.innerHTML = `
            <div class="task-summary" onclick="this.parentElement.classList.toggle('expanded')">
                <div class="col-status-wrap task-status-combo">
                    <span class="status-inline ${statusClass}">
                        <span class="status-dot"></span>
                        ${record.status === 'running' ? '<span class="status-spinner"></span>' : ''}
                        <span>${statusText}</span>
                    </span>
                </div>
                <div class="col-tool val-tool" title="${toolName}">
                    <div class="tool-primary">${toolName}</div>
                    <div class="tool-secondary">${escapeHtml(record.tool_id || '')}</div>
                </div>
                <div class="col-sample val-sample" title="${sampleName}">${sampleName}</div>
                <div class="col-params val-params" title="${escapeHtml(prettyJson || paramsSummary)}">${escapeHtml(paramsSummary)}</div>
                <div class="col-time val-time" title="${escapeHtml(exactTime)}">
                    <div class="time-primary">${createdLabel}</div>
                </div>
                <div class="col-duration val-duration ${durationClass}">${duration}</div>
                <div class="col-actions">
                    <div class="task-actions" onclick="event.stopPropagation()">
                        <!-- 动态插入按钮 -->
                    </div>
                </div>
            </div>
            <div class="task-details${hasDetails ? '' : ' empty'}">
                ${detailsHtml}
            </div>
        `;

        const actionsContainer = row.querySelector('.task-actions');

        // 按钮逻辑 (与旧版对齐)
        // 1. 对于 primer_design 已完成任务，显示查看结果
        if (record.status === 'completed' && record.tool_id === 'primer_design') {
            const viewBtn = document.createElement('button');
            viewBtn.className = 'task-action-btn btn-view';
            viewBtn.textContent = '查看结果';
            viewBtn.onclick = function(e) {
                e.preventDefault();
                loadPrimerResultsFromHistory(record.execution_id);
            };
            actionsContainer.appendChild(viewBtn);
        } else if (record.status === 'completed' && record.tool_id === 'multiplex_primer_panel') {
            const viewBtn = document.createElement('button');
            viewBtn.className = 'task-action-btn btn-view';
            viewBtn.textContent = '查看结果';
            viewBtn.onclick = function(e) {
                e.preventDefault();
                loadMultiplexResultsFromHistory(record.execution_id);
            };
            actionsContainer.appendChild(viewBtn);
        } else if (record.status === 'completed' && record.tool_id === 'unknown_sample_detection') {
            const viewBtn = document.createElement('button');
            viewBtn.className = 'task-action-btn btn-view';
            viewBtn.textContent = '查看结果';
            viewBtn.onclick = function(e) {
                e.preventDefault();
                loadDetectionResultsFromHistory(record.execution_id);
            };
            actionsContainer.appendChild(viewBtn);
        } else if (record.status === 'completed' && (record.tool_id === 'centrifuge' || record.tool_id === 'kraken2')) {
            const viewBtn = document.createElement('button');
            viewBtn.className = 'task-action-btn btn-view';
            viewBtn.textContent = '查看结果';
            viewBtn.onclick = function(e) {
                e.preventDefault();
                // 根据 workflow 标记区分跳转到靶向测序 or 未知样品检测
                let workflow = '';
                try {
                    const params = JSON.parse(record.parameters || '{}');
                    workflow = params.workflow || '';
                } catch (_) { /* ignore */ }
                if (workflow === 'unknown_detection') {
                    loadDetectionResultsFromHistory(record.execution_id);
                } else {
                    loadTargetedSeqResultsFromHistory(record.execution_id);
                }
            };
            actionsContainer.appendChild(viewBtn);
        } else if (record.status === 'completed' && record.tool_id === 'fastp') {
            const viewBtn = document.createElement('button');
            viewBtn.className = 'task-action-btn btn-view';
            viewBtn.textContent = '查看结果';
            viewBtn.onclick = function(e) {
                e.preventDefault();
                loadFastpResultsFromHistory(record.execution_id);
            };
            actionsContainer.appendChild(viewBtn);
        } else if (record.status === 'running') {
            const statusBtn = document.createElement('button');
            statusBtn.className = 'task-action-btn btn-view';
            statusBtn.textContent = '查看状态';
            statusBtn.onclick = function(e) {
                e.preventDefault();
                e.stopPropagation();
                toggleExecutionRemoteStatus(record.execution_id, row);
            };
            actionsContainer.appendChild(statusBtn);
        }

        // 2. 完成或失败可删除
        if (record.status === 'completed' || record.status === 'failed') {
            const delBtn = document.createElement('button');
            delBtn.className = 'task-action-btn btn-delete';
            delBtn.setAttribute('title', '删除任务记录');
            delBtn.textContent = '⌫';
            delBtn.onclick = function(e) {
                e.preventDefault();
                deleteHistoryExecution(record.execution_id);
            };
            actionsContainer.appendChild(delBtn);
        }

        container.appendChild(row);
    });
}

// 获取状态文本
function getStatusText(status) {
    const statusMap = {
        'pending': '等待中',
        'running': '运行中',
        'completed': '已完成',
        'failed': '失败'
    };
    return statusMap[status] || status;
}

function getStatusClass(status) {
    const statusMap = {
        pending: 'pending',
        running: 'running',
        completed: 'completed',
        failed: 'failed'
    };
    return statusMap[status] || 'unknown';
}

function formatExactTime(timestamp) {
    const date = new Date(timestamp * 1000);
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function formatRelativeTime(timestamp) {
    const nowSeconds = Date.now() / 1000;
    const diff = Math.max(0, Math.round(nowSeconds - Number(timestamp || 0)));
    if (diff < 60) {
        return `${diff}秒前`;
    }
    if (diff < 3600) {
        return `${Math.round(diff / 60)}分钟前`;
    }

    const date = new Date(timestamp * 1000);
    const now = new Date();
    const sameDay = date.toDateString() === now.toDateString();
    if (sameDay) {
        return `今天 ${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`;
    }
    return `${date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })} ${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`;
}

function formatDuration(seconds) {
    if (seconds < 60) {
        return `${Math.round(seconds)}秒`;
    } else if (seconds < 3600) {
        return `${Math.round(seconds / 60)}分钟`;
    } else {
        return `${Math.round(seconds / 3600)}小时`;
    }
}

function getDurationClass(seconds) {
    if (!seconds || seconds < 3600) {
        return 'duration-normal';
    }
    if (seconds < 3 * 3600) {
        return 'duration-warn';
    }
    return 'duration-long';
}

