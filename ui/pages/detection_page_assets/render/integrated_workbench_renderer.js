(function(global) {
    'use strict';

    var runtimeDependencies = null;
    var INTEGRATED_ARCHETYPE_VIEWER_STRATEGIES = {
        annotation_table: 'table-first',
        quality_assessment: 'table-first',
        html_report: 'html-first',
        artifact_collection: 'files-first',
        qc_report: 'chart-first',
        taxonomy_profile: 'chart-first',
        workflow_product: 'chart-first',
    };
    var INTEGRATED_REQUIRED_VIEWERS_BY_ARCHETYPE = {
        annotation_table: ['table', 'files'],
        quality_assessment: ['table'],
        html_report: ['html'],
        artifact_collection: ['files'],
        qc_report: ['chart', 'files'],
        taxonomy_profile: ['chart', 'table', 'files'],
        workflow_product: ['sections'],
    };

    function configureRuntime(dependencies) {
        runtimeDependencies = Object.assign({}, runtimeDependencies || {}, dependencies || {});
    }

    function getRuntime() {
        if (!runtimeDependencies) {
            throw new Error('IntegratedWorkbenchRenderer runtime is not configured');
        }
        return runtimeDependencies;
    }

    function getIntegratedToolId(feature, view) {
        return (view && view.tool_id)
            || (view && view.tool_ids && view.tool_ids[0])
            || (feature && feature.tool_ids && feature.tool_ids[0])
            || null;
    }

    function openIntegratedRunEntry() {
        var runtime = getRuntime();
        var integratedWorkbench = runtime.getIntegratedWorkbench();
        var selectedIntegratedFeatureId = String(runtime.getSelectedIntegratedFeatureId() || '').trim();
        if (!integratedWorkbench || !selectedIntegratedFeatureId) {
            return;
        }

        var feature = (integratedWorkbench.features || []).find(function(item) {
            return item && item.id === selectedIntegratedFeatureId;
        });
        var view = (integratedWorkbench.views || {})[selectedIntegratedFeatureId];
        var toolId = getIntegratedToolId(feature, view);
        if (!toolId) {
            runtime.showNotice('Current feature has no run entry yet', 'warning');
            return;
        }

        return runtime.openIntegratedRunModal(feature, toolId);
    }

    function initializeIntegratedSectionToggles() {
        document.querySelectorAll('.section-toggle-btn').forEach(function(btn) {
            if (btn.dataset.bound === '1') {
                return;
            }
            btn.dataset.bound = '1';
            btn.addEventListener('click', function() {
                var targetId = btn.dataset.target;
                var body = document.getElementById(targetId);
                if (!body) {
                    return;
                }
                var willCollapse = !body.classList.contains('collapsed');
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
                var tab = String(btn.dataset.resultTab || '').trim();
                if (!tab) {
                    return;
                }
                switchIntegratedResultTab(tab);
            });
        });
    }

    function switchIntegratedResultTab(tabName) {
        var runtime = getRuntime();
        var activeTab = String(tabName || 'overview').trim() || 'overview';
        document.querySelectorAll('.integrated-result-tab').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.resultTab === activeTab);
        });
        document.querySelectorAll('.result-tab-panel').forEach(function(panel) {
            var shouldShow = panel.classList.contains('result-tab-' + activeTab);
            var panelVisible = panel.dataset.panelVisible !== '0';
            runtime.setHidden(panel, !(shouldShow && panelVisible));
        });
    }

    function getIntegratedTablePayload(view) {
        var table = (view && view.table && typeof view.table === 'object') ? view.table : {};
        return {
            table: table,
            columns: Array.isArray(table.columns) ? table.columns : (Array.isArray(view && view.columns) ? view.columns : []),
            rows: Array.isArray(table.rows) ? table.rows : (Array.isArray(view && view.rows) ? view.rows : []),
        };
    }

    function getIntegratedCharts(chartInput) {
        return Array.isArray(chartInput) ? chartInput : (chartInput ? [chartInput] : []);
    }

    function hasIntegratedChartData(chartInput) {
        return getIntegratedCharts(chartInput).some(function(chart) {
            if (!chart || typeof chart !== 'object') {
                return false;
            }
            if (Array.isArray(chart.data) && chart.data.length > 0) {
                return true;
            }
            return Array.isArray(chart.series) && chart.series.some(function(series) {
                return Array.isArray(series && series.data) && series.data.length > 0;
            });
        });
    }

    function getArtifactPriority(item) {
        if (!item || typeof item !== 'object') {
            return 999;
        }
        var role = String(item.display_role || '').trim();
        var hint = String(item.viewer_hint || '').trim();
        if (role === 'primary_result' && hint === 'html') return 0;
        if (role === 'report' && hint === 'html') return 1;
        if (role === 'primary_result' && hint === 'table') return 2;
        if (role === 'supporting_result') return 3;
        if (role === 'provenance') return 4;
        if (role === 'download') return 5;
        return 6;
    }

    function sortIntegratedArtifacts(artifacts) {
        var normalizedArtifacts = Array.isArray(artifacts) ? artifacts.slice() : [];
        normalizedArtifacts.sort(function(a, b) {
            var scoreDiff = getArtifactPriority(a) - getArtifactPriority(b);
            if (scoreDiff !== 0) {
                return scoreDiff;
            }
            return String(a && a.name || '').localeCompare(String(b && b.name || ''));
        });
        return normalizedArtifacts;
    }

    function getIntegratedHtmlArtifact(artifacts) {
        var normalizedArtifacts = sortIntegratedArtifacts(Array.isArray(artifacts) ? artifacts : []);
        var hintedHtmlArtifact = normalizedArtifacts.find(function(item) {
            return item
                && item.available
                && item.local_path
                && item.viewer_hint === 'html';
        });
        if (hintedHtmlArtifact) {
            return hintedHtmlArtifact;
        }
        var availableArtifact = normalizedArtifacts.find(function(item) {
            return item
                && item.available
                && item.local_path
                && typeof item.name === 'string'
                && item.name.toLowerCase().endsWith('.html');
        });
        if (availableArtifact) {
            return availableArtifact;
        }
        return normalizedArtifacts.find(function(item) {
            return item
                && typeof item.name === 'string'
                && item.name.toLowerCase().endsWith('.html');
        }) || null;
    }

    function getIntegratedViewerStrategy(view) {
        var archetype = String(view && view.archetype || '').trim();
        var mode = INTEGRATED_ARCHETYPE_VIEWER_STRATEGIES[archetype] || 'table-first';
        var primaryViewer = mode.replace('-first', '');
        return {
            archetype: archetype,
            mode: mode,
            primaryViewer: primaryViewer,
            requiredViewers: Array.isArray(INTEGRATED_REQUIRED_VIEWERS_BY_ARCHETYPE[archetype])
                ? INTEGRATED_REQUIRED_VIEWERS_BY_ARCHETYPE[archetype]
                : [],
        };
    }

    function buildIntegratedViewerState(view) {
        var artifacts = Array.isArray(view && view.artifacts) ? view.artifacts : [];
        var tablePayload = getIntegratedTablePayload(view);
        var htmlArtifact = getIntegratedHtmlArtifact(artifacts);
        var strategy = getIntegratedViewerStrategy(view);
        var availability = {
            table: tablePayload.columns.length > 0 && tablePayload.rows.length > 0,
            chart: hasIntegratedChartData((view && view.charts) || (view && view.chart) || null),
            html: Boolean(htmlArtifact && htmlArtifact.available && htmlArtifact.local_path),
            files: artifacts.some(function(item) {
                return item && item.available && (item.local_path || item.remote_path);
            }),
            sections: Array.isArray(view && view.sections) && view.sections.length > 0,
        };
        var viewerErrors = {};
        strategy.requiredViewers.forEach(function(viewer) {
            if (availability[viewer]) {
                return;
            }
            viewerErrors[viewer] = '当前结果 archetype=' + (strategy.archetype || 'unknown') + ' 要求 ' + strategy.mode + ' 主 viewer，但 execution 未提供' + viewer + '数据。';
        });
        return {
            strategy: strategy,
            availability: availability,
            viewerErrors: viewerErrors,
            table: tablePayload,
            htmlArtifact: htmlArtifact,
            primaryTab: strategy.primaryViewer === 'files' ? 'files' : 'result',
        };
    }

    function hasIntegratedResultContent(view) {
        var tablePayload = getIntegratedTablePayload(view);
        if (tablePayload.rows.length > 0) {
            return true;
        }
        if (hasIntegratedChartData((view && view.charts) || (view && view.chart) || null)) {
            return true;
        }
        return Boolean(getIntegratedHtmlArtifact(Array.isArray(view && view.artifacts) ? view.artifacts : []));
    }

    function getDefaultIntegratedResultTab(view, options) {
        var sourceMode = String(options && options.sourceMode || 'workflow').trim() || 'workflow';
        if (sourceMode !== 'history') {
            return 'overview';
        }
        return buildIntegratedViewerState(view).primaryTab;
    }

    function setSectionCollapsed(targetId, collapsed) {
        var body = document.getElementById(targetId);
        if (!body) {
            return;
        }
        body.classList.toggle('collapsed', collapsed);

        var btn = document.querySelector('.section-toggle-btn[data-target="' + targetId + '"]');
        if (btn) {
            btn.textContent = collapsed ? '展开' : '收起';
            btn.setAttribute('aria-expanded', String(!collapsed));
        }
    }

    function renderIntegratedFeature(feature, view, options) {
        var runtime = getRuntime();
        var emptyState = document.getElementById('integrated-empty-state');
        var detail = document.getElementById('integrated-detail');
        var statusChip = document.getElementById('integrated-status-chip');
        var stateDetail = document.getElementById('feature-state-detail');
        var kicker = document.getElementById('feature-kicker');
        var viewerState = buildIntegratedViewerState(view);
        var sourceMode = String(options && options.sourceMode || runtime.getSelectedIntegratedViewSource() || 'workflow').trim() || 'workflow';
        var isHistoryResult = sourceMode === 'history';

        if (!feature || !view) {
            runtime.setHidden(emptyState, false);
            runtime.setHidden(detail, true);
            if (statusChip) {
                statusChip.textContent = '待选择功能';
                statusChip.dataset.status = 'pending';
            }
            if (stateDetail) {
                stateDetail.textContent = '请选择左侧功能或通过运行历史进入结果。';
            }
            return;
        }

        runtime.setHidden(emptyState, true);
        runtime.setHidden(detail, false);
        if (detail) {
            detail.dataset.sourceMode = sourceMode;
        }
        if (statusChip) {
            statusChip.textContent = (view && view.status && view.status.label) || feature.badge || '已选择';
            statusChip.dataset.status = String((view && view.status && view.status.state) || (isHistoryResult ? 'completed' : 'pending')).trim() || 'pending';
        }
        if (kicker) {
            kicker.textContent = isHistoryResult ? 'Result Shell · ' + viewerState.strategy.mode : 'Workflow Entry';
        }

        document.getElementById('feature-title').textContent = view.title || feature.name || feature.id;
        document.getElementById('feature-description').textContent = view.description || '';
        if (stateDetail) {
            var executionId = String((view && view.provenance && view.provenance.execution_id) || (view && view.hero && view.hero.execution_id) || '').trim();
            stateDetail.textContent = isHistoryResult
                ? '当前为统一结果壳视图，主 viewer 策略为 ' + viewerState.strategy.mode + (executionId ? '，execution_id: ' + executionId : '') + '。'
                : String((view && view.status && view.status.detail) || '可从这里查看输入要求，并继续提交新的运行。');
        }

        initializeIntegratedSectionToggles();
        initializeIntegratedResultTabs();
        setSectionCollapsed('integrated-run-body', true);
        setSectionCollapsed('artifact-list-wrap', true);

        renderIntegratedRunEntry(feature, view, { hidden: isHistoryResult });
        global.ResultViewerRenderers.renderSummaryGrid({
            container: document.getElementById('summary-grid'),
            summaryItems: view.summary || [],
            escapeHtml: runtime.escapeHtml,
        });
        global.ResultViewerRenderers.renderArtifactList({
            container: document.getElementById('artifact-list'),
            artifacts: view.artifacts || [],
            requiredMessage: viewerState.viewerErrors.files || '',
            sortIntegratedArtifacts: sortIntegratedArtifacts,
            openLocalArtifact: openLocalArtifact,
            escapeHtml: runtime.escapeHtml,
        });
        global.ResultViewerRenderers.renderIntegratedProvenance({
            container: document.getElementById('integrated-provenance-list'),
            provenance: view.provenance || {},
            hero: view.hero || {},
            escapeHtml: runtime.escapeHtml,
        });
        global.ResultViewerRenderers.renderIntegratedSections({
            card: document.getElementById('integrated-sections-card'),
            container: document.getElementById('integrated-sections-list'),
            sections: view.sections || [],
            requiredMessage: viewerState.viewerErrors.sections || '',
            setHidden: runtime.setHidden,
            escapeHtml: runtime.escapeHtml,
        });
        renderIntegratedHtmlPreview(view.artifacts || [], { requiredMessage: viewerState.viewerErrors.html || '' });
        renderIntegratedTable(viewerState.table.columns || [], viewerState.table.rows || [], { requiredMessage: viewerState.viewerErrors.table || '' });
        runtime.renderIntegratedChart(view.charts || view.chart || null, { requiredMessage: viewerState.viewerErrors.chart || '' });
        switchIntegratedResultTab(getDefaultIntegratedResultTab(view, { sourceMode: sourceMode }));

        var resultsTitle = document.getElementById('results-card-title');
        if (resultsTitle) {
            resultsTitle.textContent = viewerState.table.table.title || view.table_title || '分析结果';
        }
        var resultsBadge = document.getElementById('results-card-badge');
        if (resultsBadge) {
            resultsBadge.textContent = view.table_badge || viewerState.strategy.mode;
        }

        var subtitleEl = document.getElementById('results-card-subtitle');
        if (subtitleEl) {
            subtitleEl.textContent = viewerState.viewerErrors[viewerState.strategy.primaryViewer]
                || viewerState.table.table.subtitle
                || view.table_subtitle
                || '分析结果将在此处展示。';
        }
    }

    function renderIntegratedRunEntry(feature, view, options) {
        var runtime = getRuntime();
        var card = document.getElementById('integrated-run-card');
        var hint = document.getElementById('integrated-run-hint');
        var list = document.getElementById('integrated-input-list');
        var badge = document.getElementById('integrated-run-badge');
        var runBtn = document.getElementById('integrated-run-btn');

        if (!card || !hint || !list || !badge || !runBtn) {
            return;
        }
        if (options && options.hidden) {
            runtime.setHidden(card, true);
            return;
        }

        var toolId = getIntegratedToolId(feature, view);
        if (!toolId) {
            runtime.setHidden(card, true);
            return;
        }

        runtime.setHidden(card, false);
        var supportedTools = Array.isArray(view && view.tool_ids) ? view.tool_ids.filter(Boolean) : [];
        badge.textContent = toolId;
        hint.textContent = '在这里查看输入要求，点击右侧按钮可直接进入插件工作台配置输入文件并提交任务。';
        if (supportedTools.length > 1) {
            hint.textContent = '支持多分类工具（Centrifuge / Kraken2），可在运行弹窗切换并自动刷新参数。';
        }
        runBtn.disabled = false;
        list.innerHTML = '<div class="integrated-input-empty">正在读取输入要求…</div>';

        var cached = runtime.toolDescriptorCache[toolId];
        if (cached) {
            updateIntegratedRunEntryFromDescriptor(feature && feature.id, toolId, cached);
            return;
        }

        runtime.bridgeToolsService.getToolDescriptor(toolId, function(json) {
            try {
                var descriptor = JSON.parse(json || '{}');
                runtime.toolDescriptorCache[toolId] = descriptor;
                updateIntegratedRunEntryFromDescriptor(feature && feature.id, toolId, descriptor);
            } catch (error) {
                console.error('Failed to parse integrated tool descriptor:', error);
                if (String(runtime.getSelectedIntegratedFeatureId() || '').trim() === String(feature && feature.id || '').trim()) {
                    list.innerHTML = '<div class="integrated-input-empty">输入要求解析失败。</div>';
                }
            }
        }, function() {
            if (String(runtime.getSelectedIntegratedFeatureId() || '').trim() === String(feature && feature.id || '').trim()) {
                list.innerHTML = '<div class="integrated-input-empty">工具描述符不可用，暂时无法显示输入要求。</div>';
            }
        });
    }

    function updateIntegratedRunEntryFromDescriptor(featureId, toolId, descriptor) {
        var runtime = getRuntime();
        if (String(runtime.getSelectedIntegratedFeatureId() || '').trim() !== String(featureId || '').trim()) {
            return;
        }

        var list = document.getElementById('integrated-input-list');
        var hint = document.getElementById('integrated-run-hint');
        var runBtn = document.getElementById('integrated-run-btn');
        if (!list || !hint || !runBtn) {
            return;
        }

        var inputs = descriptor.inputs || [];
        var paramCount = (descriptor.parameters || []).length;
        var dbCount = (descriptor.databases || []).length;
        hint.textContent = '需要输入文件 ' + inputs.length + ' 项，参数 ' + paramCount + ' 项，数据库 ' + dbCount + ' 项；点击右侧按钮可直接进入插件工作台配置并提交任务。';
        runBtn.textContent = '配置并运行 ' + (descriptor.name || toolId);

        if (inputs.length === 0) {
            list.innerHTML = '<div class="integrated-input-empty">当前工具没有声明输入文件，可直接进入插件工作台查看参数并运行。</div>';
            return;
        }

        list.innerHTML = inputs.map(function(input) {
            return ''
                + '<div class="integrated-input-item">'
                + '  <div class="integrated-input-label-row">'
                + '    <span class="integrated-input-label">' + runtime.escapeHtml(input.label || input.name || '输入文件') + '</span>'
                + (input.required !== false ? '<span class="integrated-input-required">必填</span>' : '')
                + '  </div>'
                + '  <div class="integrated-input-desc">' + runtime.escapeHtml(input.description || '请在插件工作台中选择文件') + '</div>'
                + '</div>';
        }).join('');
    }

    function openLocalArtifact(localPath) {
        var runtime = getRuntime();
        var path = String(localPath || '').trim();
        if (!path) {
            runtime.showNotice('本地结果文件路径为空');
            return;
        }
        runtime.bridgeResultsService.openLocalFile(path, function(json) {
            try {
                var payload = JSON.parse(json || '{}');
                if (payload.status !== 'ok') {
                    runtime.showNotice(payload.message || '打开本地结果文件失败');
                }
            } catch (error) {
                console.error('Failed to open local artifact:', error);
                runtime.showNotice('打开本地结果文件失败');
            }
        }, function(error) {
            runtime.showNotice(error && error.message ? error.message : '本地文件打开接口不可用');
        });
    }

    function localPathToFileUrl(localPath) {
        var raw = String(localPath || '').trim();
        if (!raw) {
            return '';
        }
        var normalized = raw.replace(/\\/g, '/');
        if (/^[a-zA-Z]:\//.test(normalized)) {
            return 'file:///' + encodeURI(normalized);
        }
        if (normalized.startsWith('/')) {
            return 'file://' + encodeURI(normalized);
        }
        return encodeURI(normalized);
    }

    function renderIntegratedHtmlPreview(artifacts, options) {
        var runtime = getRuntime();
        var card = document.getElementById('integrated-html-card');
        var frame = document.getElementById('integrated-html-frame');
        var empty = document.getElementById('integrated-html-empty');
        var titleEl = document.getElementById('html-preview-title');
        var openBtn = document.getElementById('html-open-btn');

        if (!card || !frame || !empty || !titleEl || !openBtn) {
            return;
        }

        var htmlArtifact = getIntegratedHtmlArtifact(artifacts || []);
        var htmlReady = Boolean(htmlArtifact && htmlArtifact.available && htmlArtifact.local_path);

        if (!htmlReady) {
            card.dataset.panelVisible = options && options.requiredMessage ? '1' : '0';
            runtime.setHidden(card, !(options && options.requiredMessage));
            runtime.setHidden(frame, true);
            frame.src = 'about:blank';
            runtime.setHidden(openBtn, true);
            runtime.setHidden(empty, !(options && options.requiredMessage));
            empty.textContent = options && options.requiredMessage || '';
            return;
        }

        var fileUrl = localPathToFileUrl(htmlArtifact.local_path);
        card.dataset.panelVisible = '1';
        runtime.setHidden(card, false);
        titleEl.textContent = htmlArtifact.name || 'HTML 预览';
        runtime.setHidden(frame, !fileUrl);
        frame.src = fileUrl || 'about:blank';
        runtime.setHidden(empty, Boolean(fileUrl));
        empty.textContent = fileUrl ? '' : 'HTML 文件已同步，但当前无法生成预览地址。';
        runtime.setHidden(openBtn, false);
        openBtn.onclick = function() {
            openLocalArtifact(htmlArtifact.local_path);
        };
    }

    function getIntegratedColumnCellClass(columnKey) {
        var truncateColumns = new Set(['region_id', 'position']);
        var wrapColumns = new Set(['pathogen', 'forward_primer', 'reverse_primer', 'amplicon', 'target_sequence', 'amplicon_seq', 'name']);

        if (truncateColumns.has(columnKey)) {
            return 'table-cell-truncate';
        }
        if (wrapColumns.has(columnKey)) {
            return 'table-cell-wrap';
        }
        return '';
    }

    function renderIntegratedTable(columns, rows, options) {
        var runtime = getRuntime();
        var head = document.getElementById('integrated-table-head');
        var body = document.getElementById('integrated-table-body');
        var card = document.getElementById('integrated-table-card');
        if (!head || !body) {
            return;
        }

        head.innerHTML = '<tr>' + columns.map(function(column) {
            var key = column.key || '';
            return '<th class="col-' + runtime.escapeHtml(key) + '">' + runtime.escapeHtml(column.label || key || '') + '</th>';
        }).join('') + '</tr>';
        body.innerHTML = '';

        var table = head.closest('table');
        if (table) {
            table.classList.toggle('wide-table', columns.length > 6);
        }

        if (card) {
            var shouldShow = columns.length > 0 || rows.length > 0 || Boolean(options && options.requiredMessage);
            card.dataset.panelVisible = shouldShow ? '1' : '0';
        }

        if (!rows.length) {
            body.innerHTML = '<tr><td colspan="' + (columns.length || 1) + '" class="empty-row">' + runtime.escapeHtml(options && options.requiredMessage || '当前 execution 未提供表格结果。') + '</td></tr>';
            return;
        }

        rows.forEach(function(row) {
            var tr = document.createElement('tr');
            tr.innerHTML = columns.map(function(column) {
                var value = row[column.key] == null ? '-' : row[column.key];
                var text = runtime.escapeHtml(String(value));
                var rawKey = column.key || 'value';
                var key = runtime.escapeHtml(rawKey);
                var extraClass = getIntegratedColumnCellClass(rawKey);
                return '<td class="col-' + key + (extraClass ? ' ' + extraClass : '') + '" title="' + text + '">' + text + '</td>';
            }).join('');
            body.appendChild(tr);
        });
    }

    global.IntegratedWorkbenchRenderer = {
        configureRuntime: configureRuntime,
        openIntegratedRunEntry: openIntegratedRunEntry,
        initializeIntegratedSectionToggles: initializeIntegratedSectionToggles,
        initializeIntegratedResultTabs: initializeIntegratedResultTabs,
        switchIntegratedResultTab: switchIntegratedResultTab,
        getIntegratedCharts: getIntegratedCharts,
        hasIntegratedChartData: hasIntegratedChartData,
        getIntegratedViewerStrategy: getIntegratedViewerStrategy,
        buildIntegratedViewerState: buildIntegratedViewerState,
        hasIntegratedResultContent: hasIntegratedResultContent,
        getDefaultIntegratedResultTab: getDefaultIntegratedResultTab,
        renderIntegratedFeature: renderIntegratedFeature,
        renderIntegratedRunEntry: renderIntegratedRunEntry,
        updateIntegratedRunEntryFromDescriptor: updateIntegratedRunEntryFromDescriptor,
        renderIntegratedHtmlPreview: renderIntegratedHtmlPreview,
        renderIntegratedTable: renderIntegratedTable,
        sortIntegratedArtifacts: sortIntegratedArtifacts,
        openLocalArtifact: openLocalArtifact,
        localPathToFileUrl: localPathToFileUrl,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
