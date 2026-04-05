(function(global) {
    'use strict';

    var runtimeDependencies = null;
    function configureRuntime(dependencies) {
        runtimeDependencies = Object.assign({}, runtimeDependencies || {}, dependencies || {});
    }

    function getRuntime() {
        if (!runtimeDependencies) {
            throw new Error('IntegratedWorkbenchRenderer runtime is not configured');
        }
        return runtimeDependencies;
    }

    function getResultShellRegistry() {
        if (!global.ResultShellRegistry) {
            throw new Error('IntegratedWorkbenchRenderer requires ResultShellRegistry');
        }
        return global.ResultShellRegistry;
    }

    function getIntegratedToolId(feature, view) {
        return (view && (view.toolId || view.tool_id))
            || (view && ((view.toolIds && view.toolIds[0]) || (view.tool_ids && view.tool_ids[0])))
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
        var activeTab = String(tabName || 'table').trim() || 'table';
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
            columns: Array.isArray(table.columns) ? table.columns : [],
            rows: Array.isArray(table.rows) ? table.rows : [],
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
        var registration = getResultShellRegistry().getRegistration(view && view.archetype);
        var archetype = String(view && view.archetype || '').trim();
        var mode = String(registration.mode || 'table-first').trim() || 'table-first';
        var primaryViewer = mode.replace('-first', '');
        return {
            archetype: archetype,
            mode: mode,
            primaryViewer: primaryViewer,
            requiredViewers: Array.isArray(registration.requiredViewers) ? registration.requiredViewers.slice() : [],
        };
    }

    function buildIntegratedViewerState(view) {
        var artifacts = Array.isArray(view && view.artifacts) ? view.artifacts : [];
        var tablePayload = getIntegratedTablePayload(view);
        var htmlArtifact = getIntegratedHtmlArtifact(artifacts);
        var strategy = getIntegratedViewerStrategy(view);
        var validation = getResultShellRegistry().validateView(view || {});
        var availability = {
            table: tablePayload.columns.length > 0 && tablePayload.rows.length > 0,
            chart: hasIntegratedChartData(view && view.charts),
            html: Boolean(htmlArtifact && htmlArtifact.available && htmlArtifact.local_path),
            files: artifacts.some(function(item) {
                return item && item.available && (item.local_path || item.remote_path);
            }),
            sections: Array.isArray(view && view.sections) && view.sections.length > 0,
        };
        var viewerErrors = {};
        validation.issues.forEach(function(issue) {
            if (issue.indexOf('viewer=chart') >= 0) viewerErrors.chart = issue;
            if (issue.indexOf('viewer=table') >= 0) viewerErrors.table = issue;
            if (issue.indexOf('viewer=files') >= 0) viewerErrors.files = issue;
            if (issue.indexOf('viewer=html') >= 0) viewerErrors.html = issue;
            if (issue.indexOf('viewer=sections') >= 0) viewerErrors.sections = issue;
        });
        return {
            strategy: strategy,
            availability: availability,
            validation: validation,
            viewerErrors: viewerErrors,
            table: tablePayload,
            htmlArtifact: htmlArtifact,
            primaryTab: strategy.primaryViewer === 'files'
                ? 'artifacts'
                : ((strategy.primaryViewer === 'chart' || strategy.primaryViewer === 'html') ? 'chart' : 'table'),
        };
    }

    function hasIntegratedResultContent(view) {
        var tablePayload = getIntegratedTablePayload(view);
        if (tablePayload.rows.length > 0) {
            return true;
        }
        if (hasIntegratedChartData(view && view.charts)) {
            return true;
        }
        return Boolean(getIntegratedHtmlArtifact(Array.isArray(view && view.artifacts) ? view.artifacts : []));
    }

    function getDefaultIntegratedResultTab(view, options) {
        var viewerState = buildIntegratedViewerState(view || {});
        return viewerState.primaryTab || 'table';
    }

    function configureIntegratedHeaderRunButton(feature, viewModel, options) {
        var runtime = getRuntime();
        var runBtn = document.getElementById('integrated-header-run-btn');
        if (!runBtn) {
            return;
        }
        var sourceMode = String(options && options.sourceMode || 'workflow').trim() || 'workflow';
        var isHistoryResult = sourceMode === 'history';
        var toolId = getIntegratedToolId(feature, viewModel);
        if (!toolId) {
            runtime.setHidden(runBtn, true);
            runBtn.onclick = null;
            return;
        }
        runtime.setHidden(runBtn, false);
        runBtn.textContent = isHistoryResult ? '重新运行' : '启动分析';
        runBtn.disabled = false;
        runBtn.onclick = function() {
            openIntegratedRunEntry();
        };
    }

    function normalizeIntegratedStatusState(rawState) {
        var state = String(rawState || '').trim().toLowerCase();
        if (!state || state === 'ready' || state === 'idle') {
            return 'pending';
        }
        if (state === 'completed' || state === 'success' || state === 'done') {
            return 'completed';
        }
        if (state === 'running' || state === 'executing' || state === 'processing') {
            return 'running';
        }
        if (state === 'failed' || state === 'error') {
            return 'failed';
        }
        return 'pending';
    }

    function configureIntegratedHeaderStatus(viewModel) {
        var statusChip = document.getElementById('integrated-header-status-chip');
        if (!statusChip) {
            return;
        }
        var status = (viewModel && viewModel.status && typeof viewModel.status === 'object') ? viewModel.status : {};
        var normalizedState = normalizeIntegratedStatusState(status.state);
        var statusLabel = String(status.label || '').trim();
        if (!statusLabel) {
            if (normalizedState === 'completed') {
                statusLabel = '结果可用';
            } else if (normalizedState === 'running') {
                statusLabel = '运行中';
            } else if (normalizedState === 'failed') {
                statusLabel = '运行失败';
            } else {
                statusLabel = '等待运行';
            }
        }
        statusChip.dataset.status = normalizedState;
        statusChip.textContent = statusLabel;
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
        var kicker = document.getElementById('feature-kicker');
        var sourceMode = String(options && options.sourceMode || runtime.getSelectedIntegratedViewSource() || 'workflow').trim() || 'workflow';
        var isHistoryResult = sourceMode === 'history';
        var viewModel = view ? getResultShellRegistry().buildViewModel(view, { sourceMode: sourceMode }) : null;
        var viewerState = buildIntegratedViewerState(viewModel);

        if (!feature || !view) {
            runtime.setHidden(emptyState, false);
            runtime.setHidden(detail, true);
            return;
        }

        runtime.setHidden(emptyState, true);
        runtime.setHidden(detail, false);
        if (detail) {
            detail.dataset.sourceMode = sourceMode;
        }
        if (kicker) {
            kicker.textContent = isHistoryResult ? 'Result Shell · ' + viewerState.strategy.mode : 'Workflow Entry';
        }

        document.getElementById('feature-title').textContent = viewModel.title || feature.name || feature.id;
        var featureDescription = String((feature && feature.description) || '').trim();
        var viewDescription = String((viewModel && viewModel.description) || '').trim();
        var descriptionText = featureDescription || viewDescription;
        document.getElementById('feature-description').textContent = descriptionText;

        initializeIntegratedSectionToggles();
        initializeIntegratedResultTabs();
        setSectionCollapsed('artifact-list-wrap', true);
        configureIntegratedHeaderStatus(viewModel);
        configureIntegratedHeaderRunButton(feature, viewModel, { sourceMode: sourceMode });

        global.ResultViewerRenderers.renderSummaryGrid({
            container: document.getElementById('summary-grid'),
            summaryItems: viewModel.summary || [],
            escapeHtml: runtime.escapeHtml,
        });
        global.ResultViewerRenderers.renderArtifactList({
            container: document.getElementById('artifact-list'),
            artifacts: viewModel.artifacts || [],
            requiredMessage: viewerState.viewerErrors.files || '',
            sortIntegratedArtifacts: sortIntegratedArtifacts,
            openLocalArtifact: openLocalArtifact,
            escapeHtml: runtime.escapeHtml,
        });
        global.ResultViewerRenderers.renderIntegratedProvenance({
            container: document.getElementById('integrated-provenance-list'),
            provenance: viewModel.provenance || {},
            hero: viewModel.hero || {},
            escapeHtml: runtime.escapeHtml,
        });
        global.ResultViewerRenderers.renderIntegratedSections({
            card: document.getElementById('integrated-sections-card'),
            container: document.getElementById('integrated-sections-list'),
            sections: viewModel.sections || [],
            requiredMessage: viewerState.viewerErrors.sections || '',
            setHidden: runtime.setHidden,
            escapeHtml: runtime.escapeHtml,
        });
        renderIntegratedHtmlPreview(viewModel.artifacts || [], { requiredMessage: viewerState.viewerErrors.html || '' });
        renderIntegratedTable(viewerState.table.columns || [], viewerState.table.rows || [], { requiredMessage: viewerState.viewerErrors.table || '' });
        runtime.renderIntegratedChart(viewModel.charts || [], { requiredMessage: viewerState.viewerErrors.chart || '' });
        switchIntegratedResultTab(getDefaultIntegratedResultTab(viewModel, { sourceMode: sourceMode }));

        var resultsTitle = document.getElementById('results-card-title');
        if (resultsTitle) {
            resultsTitle.textContent = viewerState.table.table.title || '分析结果';
        }
        var resultsBadge = document.getElementById('results-card-badge');
        if (resultsBadge) {
            resultsBadge.textContent = viewerState.strategy.mode;
        }

        var subtitleEl = document.getElementById('results-card-subtitle');
        if (subtitleEl) {
            subtitleEl.textContent = viewerState.viewerErrors[viewerState.strategy.primaryViewer]
                || viewerState.table.table.subtitle
                || String((viewModel && viewModel.status && viewModel.status.detail) || '分析结果将在此处展示。');
        }
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
        renderIntegratedHtmlPreview: renderIntegratedHtmlPreview,
        renderIntegratedTable: renderIntegratedTable,
        sortIntegratedArtifacts: sortIntegratedArtifacts,
        openLocalArtifact: openLocalArtifact,
        localPathToFileUrl: localPathToFileUrl,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
