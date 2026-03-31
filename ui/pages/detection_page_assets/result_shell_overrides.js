(function(global) {
    'use strict';

    var registryApi = global.ResultShellRegistry;
    if (!registryApi) {
        return;
    }

    var originalRenderIntegratedTable = global.renderIntegratedTable;
    var originalRenderIntegratedChart = global.renderIntegratedChart;
    var originalRenderArtifactList = global.renderArtifactList;
    var originalSwitchIntegratedResultTab = global.switchIntegratedResultTab;

    function asArray(value) {
        return Array.isArray(value) ? value : [];
    }

    function text(value, fallback) {
        var output = String(value || '').trim();
        return output || String(fallback || '').trim();
    }

    function escapeHtmlCompat(value) {
        if (typeof global.escapeHtml === 'function') {
            return global.escapeHtml(value);
        }
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function inferSourceMode(view, options) {
        var explicit = text(options && options.sourceMode, '');
        if (explicit) {
            return explicit;
        }
        return text(view && view.__displaySource, '') === 'history' ? 'history' : 'workflow';
    }

    function buildIssueMap(issues) {
        return asArray(issues).reduce(function(acc, issue) {
            if (issue.indexOf('viewer=chart') >= 0) acc.chart = issue;
            if (issue.indexOf('viewer=table') >= 0) acc.table = issue;
            if (issue.indexOf('viewer=files') >= 0) acc.files = issue;
            if (issue.indexOf('viewer=html') >= 0) acc.html = issue;
            if (issue.indexOf('viewer=sections') >= 0) acc.sections = issue;
            return acc;
        }, {});
    }

    function pickPrimaryResultTab(viewModel) {
        var availability = viewModel.validation && viewModel.validation.availability
            ? viewModel.validation.availability
            : {};
        if (availability.html || availability.chart || availability.table || availability.sections) {
            return 'result';
        }
        if (availability.files) {
            return 'files';
        }
        return 'provenance';
    }

    function ensureTerraScaffold() {
        var detail = document.getElementById('integrated-detail');
        var sideColumn = detail ? detail.querySelector('.integrated-side-column') : null;
        var primaryColumn = detail ? detail.querySelector('.integrated-primary-column') : null;
        if (!detail || !sideColumn || !primaryColumn) {
            return null;
        }

        var staleHero = document.getElementById('result-shell-hero');
        if (staleHero) {
            staleHero.remove();
        }
        var staleInsights = document.getElementById('result-shell-insights');
        if (staleInsights) {
            staleInsights.remove();
        }

        if (!document.getElementById('result-shell-meta-card')) {
            var metaCard = document.createElement('div');
            metaCard.id = 'result-shell-meta-card';
            metaCard.className = 'detail-card compact-detail-card terra-side-card terra-sticky-side-card';
            metaCard.innerHTML = ''
                + '<div class="card-title-row compact-title-row">'
                + '  <h4>关键信息</h4>'
                + '</div>'
                + '<div class="terra-meta-list" id="result-shell-meta-list"></div>';
            sideColumn.insertBefore(metaCard, sideColumn.firstChild);
        }

        if (!document.getElementById('result-shell-diagnostics-card')) {
            var diagnosticsCard = document.createElement('div');
            diagnosticsCard.id = 'result-shell-diagnostics-card';
            diagnosticsCard.className = 'detail-card compact-detail-card terra-side-card terra-sticky-side-card';
            diagnosticsCard.innerHTML = ''
                + '<div class="card-title-row compact-title-row">'
                + '  <h4>诊断</h4>'
                + '  <div class="side-card-actions">'
                + '    <button class="section-toggle-btn" data-target="result-shell-diagnostics-body" type="button">展开</button>'
                + '  </div>'
                + '</div>'
                + '<div class="side-section-body collapsed" id="result-shell-diagnostics-body">'
                + '  <div class="terra-diagnostics-list" id="result-shell-diagnostics-list"></div>'
                + '</div>';
            var provenanceCard = document.querySelector('.result-tab-provenance .card-title-row')?.parentElement;
            if (provenanceCard && provenanceCard.parentElement === sideColumn) {
                sideColumn.insertBefore(diagnosticsCard, provenanceCard);
            } else {
                sideColumn.appendChild(diagnosticsCard);
            }
        }

        var summaryGrid = document.getElementById('summary-grid');
        if (summaryGrid) {
            summaryGrid.classList.remove('result-tab-overview');
            summaryGrid.classList.add('result-tab-result');
            summaryGrid.classList.add('terra-summary-grid');
        }

        var sectionsCard = document.getElementById('integrated-sections-card');
        if (sectionsCard) {
            sectionsCard.classList.remove('result-tab-overview');
            sectionsCard.classList.add('terra-sections-card');
        }

        var filesCard = document.getElementById('integrated-files-card');
        if (filesCard) {
            filesCard.classList.remove('result-tab-panel', 'result-tab-files');
            filesCard.classList.add('terra-side-card', 'terra-sticky-side-card');
            filesCard.style.display = 'block';
            filesCard.dataset.panelVisible = '1';
        }

        var provenancePanel = document.querySelector('.result-tab-provenance');
        if (provenancePanel) {
            provenancePanel.classList.remove('result-tab-panel', 'result-tab-provenance');
            provenancePanel.style.display = 'none';
        }

        return {
            detail: detail,
            primaryColumn: primaryColumn,
            sideColumn: sideColumn
        };
    }

    function renderHeader(viewModel, feature, sourceMode) {
        var kicker = document.getElementById('feature-kicker');
        var titleEl = document.getElementById('feature-title');
        var descriptionEl = document.getElementById('feature-description');
        var statusChip = document.getElementById('integrated-status-chip');
        var stateDetail = document.getElementById('feature-state-detail');
        if (!kicker || !titleEl || !descriptionEl || !statusChip || !stateDetail) {
            return;
        }

        var issues = asArray(viewModel.validation && viewModel.validation.issues);
        kicker.textContent = '';
        titleEl.textContent = viewModel.title || text(feature && feature.name, '结果');
        descriptionEl.textContent = text(viewModel.description, '');

        statusChip.textContent = text(viewModel.status && viewModel.status.label, text(feature && feature.badge, '已选择'));
        statusChip.dataset.status = text(viewModel.status && viewModel.status.state, sourceMode === 'history' ? 'completed' : 'pending');
        stateDetail.textContent = issues.length
            ? '有结构化告警'
            : '已完成';

        var resultTabs = document.getElementById('integrated-result-tabs');
        if (resultTabs) {
            resultTabs.style.display = 'none';
        }
    }

    function renderSummaryGridTerra(summaryItems) {
        var container = document.getElementById('summary-grid');
        if (!container) {
            return;
        }
        var items = asArray(summaryItems).filter(function(item) {
            return text(item && item.label, '') && text(item && item.value, '');
        }).slice(0, 4);
        if (!items.length) {
            container.style.display = 'none';
            container.innerHTML = '';
            return;
        }
        container.style.display = 'grid';
        container.innerHTML = items.map(function(item) {
            return ''
                + '<article class="terra-summary-card" data-tone="' + escapeHtmlCompat(text(item && item.tone, 'default')) + '">'
                + '  <div class="terra-summary-label">' + escapeHtmlCompat(text(item && item.label, '指标')) + '</div>'
                + '  <div class="terra-summary-value">' + escapeHtmlCompat(text(item && item.value, '-')) + '</div>'
                + '</article>';
        }).join('');
    }

    function renderMetadataCard(viewModel) {
        var container = document.getElementById('result-shell-meta-list');
        if (!container) {
            return;
        }
        var hero = viewModel.hero || {};
        var provenance = viewModel.provenance || {};
        var items = [];

        if (hero.sampleName) items.push({ label: '样本', value: hero.sampleName });
        if (hero.updatedAt) items.push({ label: '更新时间', value: hero.updatedAt });
        if (hero.executionId) items.push({ label: '任务 ID', value: hero.executionId });
        if (provenance.tool_version) items.push({ label: '工具版本', value: provenance.tool_version });

        if (!items.length) {
            container.innerHTML = '';
            return;
        }
        container.innerHTML = items.map(function(item) {
            return ''
                + '<div class="terra-meta-row">'
                + '  <div class="terra-meta-label">' + escapeHtmlCompat(item.label) + '</div>'
                + '  <div class="terra-meta-value">' + escapeHtmlCompat(item.value) + '</div>'
                + '</div>';
        }).join('');
    }

    function renderDiagnostics(viewModel) {
        var container = document.getElementById('result-shell-diagnostics-list');
        var card = document.getElementById('result-shell-diagnostics-card');
        if (!container || !card) {
            return;
        }

        var issues = asArray(viewModel.validation && viewModel.validation.issues);
        var availability = viewModel.validation && viewModel.validation.availability
            ? viewModel.validation.availability
            : {};
        var items = [];

        if (issues.length) {
            issues.forEach(function(issue) {
                items.push({ tone: 'warning', title: '视图契约', body: issue });
            });
        }

        Object.keys(availability).forEach(function(key) {
            if (availability[key]) {
                return;
            }
            items.push({
                tone: 'default',
                title: '缺失数据',
                body: '当前结果未提供 ' + key + ' 所需内容。'
            });
        });

        if (!items.length) {
            card.style.display = 'none';
            container.innerHTML = '';
            return;
        }

        card.style.display = 'block';
        container.innerHTML = items.map(function(item) {
            return ''
                + '<article class="terra-diagnostic-item" data-tone="' + escapeHtmlCompat(item.tone) + '">'
                + '  <div class="terra-diagnostic-title">' + escapeHtmlCompat(item.title) + '</div>'
                + '  <div class="terra-diagnostic-body">' + escapeHtmlCompat(item.body) + '</div>'
                + '</article>';
        }).join('');
        if (typeof global.setSectionCollapsed === 'function') {
            global.setSectionCollapsed('result-shell-diagnostics-body', false);
        }
    }

    function renderProvenanceMerged(provenance, hero) {
        var container = document.getElementById('integrated-provenance-list');
        var provenancePanel = container ? container.closest('.result-tab-provenance') : null;
        if (!container || !provenancePanel) {
            return;
        }
        provenancePanel.style.display = 'none';
        container.innerHTML = '';
    }

    function renderSectionsTerra(sections, options) {
        var card = document.getElementById('integrated-sections-card');
        var container = document.getElementById('integrated-sections-list');
        if (!card || !container) {
            return;
        }
        var normalizedSections = asArray(sections);
        if (!normalizedSections.length) {
            card.style.display = 'none';
            card.dataset.panelVisible = '0';
            container.innerHTML = '';
            return;
        }

        card.style.display = 'block';
        card.dataset.panelVisible = '1';
        container.innerHTML = normalizedSections.map(function(section) {
            var summaryText = asArray(section && section.summary).slice(0, 3).map(function(item) {
                return escapeHtmlCompat(text(item && item.label, '')) + ' ' + escapeHtmlCompat(text(item && item.value, '-'));
            }).filter(Boolean).join(' · ');
            return ''
                + '<article class="terra-section-card">'
                + '  <div class="terra-section-heading">'
                + '    <div class="terra-section-title">' + escapeHtmlCompat(text(section && section.title, '未命名分段')) + '</div>'
                + '    <div class="terra-section-archetype">' + escapeHtmlCompat(text(section && section.archetype, 'section')) + '</div>'
                + '  </div>'
                + '  <div class="terra-section-summary">' + escapeHtmlCompat(summaryText || text(options && options.requiredMessage, '已生成分段结果。')) + '</div>'
                + '</article>';
        }).join('');
    }

    function renderFeatureTerra(feature, view, options) {
        var emptyState = document.getElementById('integrated-empty-state');
        var detail = document.getElementById('integrated-detail');
        if (!emptyState || !detail) {
            return;
        }

        if (!feature || !view) {
            emptyState.style.display = 'flex';
            detail.style.display = 'none';
            return;
        }

        var scaffold = ensureTerraScaffold();
        if (!scaffold) {
            return;
        }

        var sourceMode = inferSourceMode(view, options);
        var viewModel = registryApi.buildViewModel(view, { sourceMode: sourceMode });
        var issueMap = buildIssueMap(viewModel.validation && viewModel.validation.issues);
        var primaryTab = pickPrimaryResultTab(viewModel);

        emptyState.style.display = 'none';
        detail.style.display = 'flex';
        detail.dataset.sourceMode = sourceMode;

        renderHeader(viewModel, feature, sourceMode);

        if (typeof global.initializeIntegratedSectionToggles === 'function') {
            global.initializeIntegratedSectionToggles();
        }
        if (typeof global.initializeIntegratedResultTabs === 'function') {
            global.initializeIntegratedResultTabs();
        }
        if (typeof global.renderIntegratedRunEntry === 'function') {
            global.renderIntegratedRunEntry(feature, view, { hidden: sourceMode === 'history' });
        }

        var filesCard = document.getElementById('integrated-files-card');
        if (filesCard) {
            filesCard.style.display = 'block';
            filesCard.dataset.panelVisible = '1';
        }
        if (typeof global.setSectionCollapsed === 'function') {
            global.setSectionCollapsed('artifact-list-wrap', false);
        }

        renderSummaryGridTerra(viewModel.summary);
        renderMetadataCard(viewModel);
        renderDiagnostics(viewModel);
        renderProvenanceMerged(viewModel.provenance, viewModel.hero);
        renderSectionsTerra(viewModel.sections, { requiredMessage: text(issueMap.sections, '') });

        if (typeof global.renderIntegratedHtmlPreview === 'function') {
            global.renderIntegratedHtmlPreview(viewModel.artifacts, { requiredMessage: text(issueMap.html, '') });
        }
        if (typeof originalRenderIntegratedChart === 'function') {
            originalRenderIntegratedChart(viewModel.charts, { requiredMessage: text(issueMap.chart, '') });
        }
        if (typeof originalRenderIntegratedTable === 'function') {
            originalRenderIntegratedTable(asArray(viewModel.table.columns), asArray(viewModel.table.rows), {
                requiredMessage: text(issueMap.table, '')
            });
        }
        if (typeof originalRenderArtifactList === 'function') {
            originalRenderArtifactList(viewModel.artifacts, { requiredMessage: text(issueMap.files, '') });
        }

        var resultsTitle = document.getElementById('results-card-title');
        var resultsBadge = document.getElementById('results-card-badge');
        var resultsSubtitle = document.getElementById('results-card-subtitle');
        if (resultsTitle) {
            resultsTitle.textContent = text(viewModel.table.title, '分析结果');
        }
        if (resultsBadge) {
            resultsBadge.textContent = text(viewModel.strategy.archetype, 'result');
        }
        if (resultsSubtitle) {
            resultsSubtitle.classList.remove('result-contract-banner');
            resultsSubtitle.textContent = text(
                viewModel.table.subtitle,
                sourceMode === 'history' ? '直接查看本次执行产生的结果内容。' : '直接查看当前工作流的结果内容。'
            );
        }

        if (typeof originalSwitchIntegratedResultTab === 'function') {
            originalSwitchIntegratedResultTab('result');
        }
    }

    global.getIntegratedViewerStrategy = function(view) {
        return registryApi.buildViewModel(view || {}, { sourceMode: inferSourceMode(view, null) }).strategy;
    };

    global.buildIntegratedViewerState = function(view) {
        var model = registryApi.buildViewModel(view || {}, { sourceMode: inferSourceMode(view, null) });
        return {
            strategy: model.strategy,
            availability: model.validation.availability,
            viewerErrors: buildIssueMap(model.validation.issues),
            table: {
                columns: asArray(model.table.columns),
                rows: asArray(model.table.rows),
                table: model.table
            },
            htmlArtifact: null,
            primaryTab: pickPrimaryResultTab(model)
        };
    };

    global.renderSummaryGrid = renderSummaryGridTerra;
    global.renderIntegratedProvenance = renderProvenanceMerged;
    global.renderIntegratedSections = renderSectionsTerra;
    global.renderIntegratedFeature = renderFeatureTerra;

    global._onExecutionUpdate = function(payload) {
        var executionId = text(payload && payload.execution_id, '');
        var status = text(payload && payload.status, '');
        var message = text(payload && payload.message, '');
        if (!executionId || !status) {
            return;
        }

        if (typeof global.loadHistory === 'function') {
            global.loadHistory();
        }

        if (status === 'completed') {
            if (typeof global.loadIntegratedWorkbench === 'function') {
                global.loadIntegratedWorkbench(true);
            }
            if (typeof global.openExecution === 'function') {
                global.openExecution(executionId, {
                    status: 'completed',
                    noticeMessage: message || '任务已完成，结果工作台已自动刷新'
                });
                return;
            }
        }

        if (status === 'failed') {
            if (typeof global.switchTab === 'function') {
                global.switchTab('history');
            }
            if (typeof global.openExecution === 'function') {
                global.openExecution(executionId, {
                    status: 'failed',
                    fetchRemoteStatus: true,
                    noticeMessage: message || '任务执行失败，请查看历史记录'
                });
                return;
            }
        }

        if (message && typeof global.showNotice === 'function') {
            global.showNotice(message, status === 'failed' ? 'error' : 'success');
        }
    };
})(window);
