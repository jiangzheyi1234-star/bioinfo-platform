let bridge = null;
let allTools = [];
let selectedToolId = null;
let selectedDescriptor = null;
let integratedWorkbench = null;
let selectedIntegratedFeatureId = null;
let databaseResources = [];
let historyRecords = [];
const toolDescriptorCache = {};
let noticeHideTimer = null;

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

    // 加载集成分析工作台
    loadIntegratedWorkbench();

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

    const remotePrimerLoadBtn = document.getElementById('remote-primer-load-btn');
    if (remotePrimerLoadBtn) {
        remotePrimerLoadBtn.addEventListener('click', loadRemotePrimerResults);
    }

    const integratedRunBtn = document.getElementById('integrated-run-btn');
    if (integratedRunBtn) {
        integratedRunBtn.addEventListener('click', openIntegratedRunEntry);
    }

    // placeholder removed
    const view = { remote_result_dir: '' };
    const remoteLoaderCard = null;
    const remoteInput = null;
    const remoteHint = null;

    if (false) {
        if (remoteLoaderCard) {
            remoteLoaderCard.style.display = 'block';
        }
        if (remoteInput) {
            remoteInput.value = view.remote_result_dir || '';
        }
        if (remoteHint && !view.remote_result_dir) {
            remoteHint.textContent = '直接读取服务器上的 multiplex 结果目录，并优先载入 multiplex_panel.txt。';
        }
    }

    if (false) {
        if (remoteLoaderCard) {
            remoteLoaderCard.style.display = 'block';
        }
        if (remoteInput) {
            remoteInput.value = view.remote_result_dir || '';
        }
        if (remoteHint && !view.remote_result_dir) {
            remoteHint.textContent = '直接读取服务器上的 multiplex 结果目录，并优先载入 multiplex_panel.txt。';
        }
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
        showNotice('当前功能暂未接入执行入口', 'warning');
        return;
    }

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

    const preferredFeature = features.find(feature => feature.status === 'active') || features[0];
    if (preferredFeature) {
        selectIntegratedFeature(preferredFeature.id);
    }
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
    document.getElementById('feature-state-label').textContent = view.status?.label || '已就绪';
    document.getElementById('feature-state-detail').textContent = view.status?.detail || '';

    const remoteLoaderCard = document.getElementById('remote-loader-card');
    const remoteInput = document.getElementById('remote-primer-dir');
    const remoteHint = document.getElementById('remote-primer-hint');
    if (remoteLoaderCard) {
        remoteLoaderCard.style.display = feature.id === 'primer_design' ? 'block' : 'none';
    }
    if (remoteInput && feature.id === 'primer_design') {
        remoteInput.value = view.remote_result_dir || '';
    }
    if (remoteHint && feature.id === 'primer_design') {
        remoteHint.textContent = view.remote_result_dir
            ? `当前目录：${view.remote_result_dir}`
            : '直接读取服务器上的 primer 结果目录，并优先载入 primer_result_final_2.txt。';
    }

    if (feature.id === 'multiplex_primer_panel') {
        if (remoteLoaderCard) {
            remoteLoaderCard.style.display = 'block';
        }
        if (remoteInput) {
            remoteInput.value = view.remote_result_dir || '';
        }
        if (remoteHint) {
            remoteHint.textContent = view.remote_result_dir
                ? `当前目录：${view.remote_result_dir}`
                : '直接读取服务器上的 multiplex 结果目录，并优先载入 multiplex_panel.txt。';
        }
    }

    initializeIntegratedSectionToggles();
    setSectionCollapsed('integrated-run-body', true);
    setSectionCollapsed('remote-loader-body', Boolean(view.remote_result_dir));
    setSectionCollapsed('parameter-list-wrap', true);
    setSectionCollapsed('artifact-list-wrap', true);

    renderIntegratedRunEntry(feature, view);
    renderSummaryGrid(view.summary || []);
    renderParameterList(view.parameters || []);
    renderArtifactList(view.artifacts || []);
    renderIntegratedTable(view.columns || [], view.rows || []);
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
    badge.textContent = toolId;
    hint.textContent = '在这里查看输入要求，点击右侧按钮可直接进入插件工作台配置输入文件并提交任务。';
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

function loadRemotePrimerResults() {
    if (!bridge || !bridge.get_remote_primer_results) {
        showNotice('远程结果接口不可用');
        return;
    }

    const input = document.getElementById('remote-primer-dir');
    const hint = document.getElementById('remote-primer-hint');
    const loadBtn = document.getElementById('remote-primer-load-btn');
    const remoteDir = input?.value?.trim() || '';
    if (!remoteDir) {
        showNotice('请先输入远程结果目录', 'warning');
        return;
    }

    if (loadBtn) {
        loadBtn.disabled = true;
        loadBtn.textContent = '加载中...';
    }
    if (hint) {
        hint.textContent = `正在读取：${remoteDir}`;
    }

    bridge.get_remote_primer_results(remoteDir, function(json) {
        if (loadBtn) {
            loadBtn.disabled = false;
            loadBtn.textContent = '加载';
        }

        try {
            const payload = JSON.parse(json);
            if (payload.status !== 'ok' || !payload.view) {
                if (hint) {
                    hint.textContent = payload.message || '远程结果读取失败';
                }
                showNotice(payload.message || '远程结果读取失败');
                return;
            }

            if (!integratedWorkbench || !integratedWorkbench.views) {
                return;
            }

            integratedWorkbench.views.primer_design = payload.view;
            if (hint) {
                hint.textContent = `已加载：${payload.view.remote_result_dir || remoteDir}`;
            }
            selectIntegratedFeature('primer_design');
        } catch (error) {
            console.error('Failed to parse remote primer results:', error);
            if (hint) {
                hint.textContent = '远程结果解析失败';
            }
            showNotice('远程结果解析失败');
        }
    });
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

function renderParameterList(parameters) {
    const container = document.getElementById('parameter-list');
    if (!container) {
        return;
    }

    container.innerHTML = '';
    parameters.forEach(param => {
        const row = document.createElement('div');
        row.className = 'parameter-row';
        const description = String(param.description || '').trim();
        row.innerHTML = `
            <div class="parameter-main">
                <span class="parameter-label">${escapeHtml(param.label || '')}</span>
                ${description ? `<div class="parameter-desc">${escapeHtml(description)}</div>` : ''}
            </div>
            <span class="parameter-value">${escapeHtml(String(param.value ?? ''))}</span>
        `;
        container.appendChild(row);
    });
}

function renderArtifactList(artifacts) {
    const container = document.getElementById('artifact-list');
    if (!container) {
        return;
    }

    container.innerHTML = '';
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

    if (!rows.length) {
        body.innerHTML = `<tr><td colspan="${columns.length || 1}" class="empty-row">暂无结果</td></tr>`;
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
    const wrapColumns = new Set(['pathogen', 'forward_primer', 'reverse_primer', 'amplicon', 'target_sequence', 'amplicon_seq']);

    if (truncateColumns.has(columnKey)) {
        return 'table-cell-truncate';
    }
    if (wrapColumns.has(columnKey)) {
        return 'table-cell-wrap';
    }
    return '';
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
        const defaultValue = param.default !== undefined ? param.default : '';

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

        group.innerHTML = `
            <label class="form-label">
                ${param.label || param.name}${required}
            </label>
            ${inputHtml}
            ${param.description ? `<div class="form-help">${param.description}</div>` : ''}
        `;

        container.appendChild(group);
    });
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
        return '压缩包 (*.zip *.tar *.tar.gz *.tgz)';
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
            switchTab('integrated');
            selectIntegratedFeature('multiplex_primer_panel');
            showNotice('已加载该次 multiplex 结果', 'success');
        } catch (e) {
            console.error('Failed to parse execution multiplex results:', e);
            showNotice('Multiplex 结果解析失败');
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
        } else if (record.status === 'running') {
            const runningTxt = document.createElement('span');
            runningTxt.className = 'task-running-hint';
            runningTxt.textContent = '查看状态';
            actionsContainer.appendChild(runningTxt);
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
