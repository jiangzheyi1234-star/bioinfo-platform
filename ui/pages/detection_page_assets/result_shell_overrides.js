(function(global) {
    'use strict';

    var registryApi = global.ResultShellRegistry;
    if (!registryApi) {
        return;
    }

    var originalRenderIntegratedTable = global.renderIntegratedTable;
    var originalRenderIntegratedChart = global.renderIntegratedChart;
    var originalRenderArtifactList = global.renderArtifactList;
    var originalRenderIntegratedHtmlPreview = global.renderIntegratedHtmlPreview;

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

    function setHiddenCompat(element, hidden) {
        if (!element) {
            return;
        }
        element.classList.toggle('is-hidden', Boolean(hidden));
    }

    function setPanelVisible(element, visible) {
        if (!element) {
            return;
        }
        element.dataset.panelVisible = visible ? '1' : '0';
        setHiddenCompat(element, !visible);
    }

    function isPanelVisible(element) {
        return Boolean(element) && !element.classList.contains('is-hidden') && element.dataset.panelVisible !== '0';
    }

    function setReportMode(mode) {
        var tab = document.getElementById('tab-integrated');
        if (!tab) {
            return;
        }
        tab.dataset.reportMode = text(mode, 'default');
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

    function getHeaderFacts(viewModel) {
        var hero = viewModel.hero || {};
        var provenance = viewModel.provenance || {};
        var facts = [];
        if (hero.sampleName) facts.push({ label: '样本', value: hero.sampleName });
        if (hero.updatedAt) facts.push({ label: '更新时间', value: hero.updatedAt });
        if (hero.executionId) facts.push({ label: '任务 ID', value: hero.executionId });
        if (provenance.tool_version) facts.push({ label: '工具版本', value: provenance.tool_version });
        return facts;
    }

    function ensureReportScaffold() {
        var detail = document.getElementById('integrated-detail');
        var primaryColumn = detail ? detail.querySelector('.integrated-primary-column') : null;
        var sideColumn = detail ? detail.querySelector('.integrated-side-column') : null;
        var headerCard = detail ? detail.querySelector('.detail-header-card') : null;
        if (!detail || !primaryColumn || !sideColumn || !headerCard) {
            return null;
        }

        var summaryGrid = document.getElementById('summary-grid');
        var overviewCard = document.getElementById('result-report-overview-card');
        if (!overviewCard) {
            overviewCard = document.createElement('section');
            overviewCard.id = 'result-report-overview-card';
            overviewCard.className = 'detail-card report-section-card';
            overviewCard.innerHTML = ''
                + '<div class="card-title-row">'
                + '  <h4>总览</h4>'
                + '</div>';
            primaryColumn.insertBefore(overviewCard, primaryColumn.firstChild);
        }
        if (summaryGrid && summaryGrid.parentElement !== overviewCard) {
            overviewCard.appendChild(summaryGrid);
        }
        if (summaryGrid) {
            summaryGrid.classList.remove('result-tab-overview', 'result-tab-panel', 'integrated-summary-grid', 'terra-summary-grid');
            summaryGrid.classList.add('report-summary-grid');
        }

        if (!document.getElementById('result-report-meta-strip')) {
            var metaStrip = document.createElement('div');
            metaStrip.id = 'result-report-meta-strip';
            metaStrip.className = 'result-report-meta-strip';
            var descriptionEl = document.getElementById('feature-description');
            if (descriptionEl && descriptionEl.parentElement === headerCard.querySelector('.detail-header-main')) {
                descriptionEl.insertAdjacentElement('afterend', metaStrip);
            } else {
                headerCard.querySelector('.detail-header-main').appendChild(metaStrip);
            }
        }

        if (!document.getElementById('result-report-issue-strip')) {
            var issueStrip = document.createElement('div');
            issueStrip.id = 'result-report-issue-strip';
            issueStrip.className = 'result-report-issue-strip';
            setPanelVisible(issueStrip, false);
            headerCard.insertAdjacentElement('afterend', issueStrip);
        }

        if (!document.getElementById('result-report-outline-card')) {
            var outlineCard = document.createElement('div');
            outlineCard.id = 'result-report-outline-card';
            outlineCard.className = 'detail-card report-outline-card';
            outlineCard.innerHTML = ''
                + '<div class="card-title-row compact-title-row">'
                + '  <h4>目录</h4>'
                + '</div>'
                + '<nav class="result-report-outline-nav" id="result-report-outline-nav"></nav>';
            sideColumn.appendChild(outlineCard);
        }

        var tabs = document.getElementById('integrated-result-tabs');
        if (tabs) {
            setPanelVisible(tabs, false);
        }

        var filesCard = document.getElementById('integrated-files-card');
        var htmlCard = document.getElementById('integrated-html-card');
        var tableCard = document.getElementById('integrated-table-card');
        var chartCard = document.getElementById('integrated-chart-card');
        var sectionsCard = document.getElementById('integrated-sections-card');
        var runCard = document.getElementById('integrated-run-card');
        var provenancePanel = document.querySelector('.result-tab-provenance');
        var staleMeta = document.getElementById('result-shell-meta-card');
        var staleDiagnostics = document.getElementById('result-shell-diagnostics-card');

        [filesCard, htmlCard, tableCard, chartCard, sectionsCard].forEach(function(card) {
            if (!card) {
                return;
            }
            card.classList.remove('result-tab-panel', 'result-tab-overview', 'result-tab-result', 'result-tab-files', 'result-tab-provenance');
            card.classList.add('report-section-card');
        });

        if (filesCard && filesCard.parentElement !== primaryColumn) {
            primaryColumn.appendChild(filesCard);
        }
        if (runCard) {
            setPanelVisible(runCard, false);
        }
        if (provenancePanel) {
            setPanelVisible(provenancePanel, false);
        }
        if (staleMeta) {
            staleMeta.remove();
        }
        if (staleDiagnostics) {
            staleDiagnostics.remove();
        }

        return {
            detail: detail,
            headerCard: headerCard,
            primaryColumn: primaryColumn,
            sideColumn: sideColumn,
            overviewCard: overviewCard,
            filesCard: filesCard,
            htmlCard: htmlCard,
            tableCard: tableCard,
            chartCard: chartCard,
            sectionsCard: sectionsCard
        };
    }

    function renderHeader(viewModel, feature, sourceMode) {
        var titleEl = document.getElementById('feature-title');
        var descriptionEl = document.getElementById('feature-description');
        var statusChip = document.getElementById('integrated-status-chip');
        var stateLabel = document.querySelector('.feature-state-label');
        var stateDetail = document.getElementById('feature-state-detail');
        var metaStrip = document.getElementById('result-report-meta-strip');
        var issueStrip = document.getElementById('result-report-issue-strip');
        var issues = asArray(viewModel.validation && viewModel.validation.issues);

        if (titleEl) {
            titleEl.textContent = viewModel.title || text(feature && feature.name, '结果');
        }
        if (descriptionEl) {
            descriptionEl.textContent = text(
                viewModel.description,
                sourceMode === 'history' ? '按报告顺序查看本次执行产出的结果内容。' : '按报告顺序查看当前工作流可生成的结果内容。'
            );
        }
        if (statusChip) {
            statusChip.textContent = text(viewModel.status && viewModel.status.label, text(feature && feature.badge, '已选择'));
            statusChip.dataset.status = text(viewModel.status && viewModel.status.state, sourceMode === 'history' ? 'completed' : 'pending');
        }
        if (stateLabel) {
            stateLabel.textContent = '状态';
        }
        if (stateDetail) {
            stateDetail.textContent = issues.length ? '部分区块有缺失' : '报告已就绪';
        }
        if (metaStrip) {
            var facts = getHeaderFacts(viewModel);
            metaStrip.innerHTML = facts.map(function(item) {
                return ''
                    + '<span class="report-meta-item">'
                    + '  <span class="report-meta-label">' + escapeHtmlCompat(item.label) + '</span>'
                    + '  <span class="report-meta-value">' + escapeHtmlCompat(item.value) + '</span>'
                    + '</span>';
            }).join('');
            setPanelVisible(metaStrip, facts.length > 0);
        }
        if (issueStrip) {
            if (!issues.length) {
                setPanelVisible(issueStrip, false);
                issueStrip.textContent = '';
            } else {
                setPanelVisible(issueStrip, true);
                issueStrip.textContent = '部分结果未完全生成，缺失内容已在对应区块标明。';
            }
        }
    }

    function renderSummarySection(summaryItems) {
        var card = document.getElementById('result-report-overview-card');
        var container = document.getElementById('summary-grid');
        if (!card || !container) {
            return;
        }

        var items = asArray(summaryItems).filter(function(item) {
            return text(item && item.label, '') && text(item && item.value, '');
        });
        if (!items.length) {
            setPanelVisible(card, false);
            container.innerHTML = '';
            return;
        }

        setPanelVisible(card, true);
        container.innerHTML = items.slice(0, 6).map(function(item) {
            return ''
                + '<article class="report-summary-card" data-tone="' + escapeHtmlCompat(text(item && item.tone, 'default')) + '">'
                + '  <div class="report-summary-label">' + escapeHtmlCompat(text(item && item.label, '指标')) + '</div>'
                + '  <div class="report-summary-value">' + escapeHtmlCompat(text(item && item.value, '-')) + '</div>'
                + '</article>';
        }).join('');
    }

    function renderSectionsReport(sections, options) {
        var card = document.getElementById('integrated-sections-card');
        var container = document.getElementById('integrated-sections-list');
        if (!card || !container) {
            return;
        }
        var normalizedSections = asArray(sections);
        if (!normalizedSections.length && !text(options && options.requiredMessage, '')) {
            setPanelVisible(card, false);
            container.innerHTML = '';
            return;
        }

        setPanelVisible(card, true);

        if (!normalizedSections.length) {
            container.innerHTML = '<div class="result-empty-block">' + escapeHtmlCompat(text(options && options.requiredMessage, '暂无分段结果。')) + '</div>';
            return;
        }

        container.innerHTML = normalizedSections.map(function(section, index) {
            var summary = asArray(section && section.summary).slice(0, 4).map(function(item) {
                return escapeHtmlCompat(text(item && item.label, '')) + ' ' + escapeHtmlCompat(text(item && item.value, '-'));
            }).filter(Boolean).join(' · ');
            return ''
                + '<article class="report-flow-item" data-flow-kind="section" data-outline-label="' + escapeHtmlCompat(text(section && section.title, '分段 ' + (index + 1))) + '">'
                + '  <div class="report-flow-title">' + escapeHtmlCompat(text(section && section.title, '未命名分段')) + '</div>'
                + '  <div class="report-flow-summary">' + escapeHtmlCompat(summary || text(options && options.requiredMessage, '已生成分段结果。')) + '</div>'
                + '</article>';
        }).join('');
    }

    function moveReportCards(scaffold, viewModel) {
        var primary = scaffold.primaryColumn;
        var orderedCards;
        if (viewModel.strategy && viewModel.strategy.archetype === 'html_report') {
            orderedCards = [scaffold.htmlCard, scaffold.overviewCard, scaffold.filesCard, scaffold.tableCard, scaffold.chartCard, scaffold.sectionsCard];
        } else {
            orderedCards = [scaffold.overviewCard, scaffold.tableCard, scaffold.chartCard, scaffold.sectionsCard, scaffold.filesCard, scaffold.htmlCard];
        }

        orderedCards.forEach(function(card) {
            if (card && card.parentElement !== primary) {
                primary.appendChild(card);
            }
        });
    }

    function setCardHeading(card, title, subtitle) {
        if (!card) {
            return;
        }
        var titleEl = card.querySelector('.card-title-row h4');
        if (titleEl) {
            titleEl.textContent = title;
        }
        var subtitleEl = card.querySelector('.results-card-subtitle');
        if (subtitleEl) {
            subtitleEl.textContent = subtitle || '';
        }
    }

    function slugify(value, fallback) {
        var base = text(value, fallback).toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-').replace(/^-+|-+$/g, '');
        return base || text(fallback, 'section');
    }

    function collectOutlineEntries(scaffold, viewModel) {
        var entries = [];

        function pushCardEntry(card, title) {
            if (!isPanelVisible(card)) {
                return;
            }
            var id = card.id || ('report-' + slugify(title, 'section'));
            card.id = id;
            entries.push({ label: title, targetId: id, level: 0 });
        }

        if (viewModel.strategy && viewModel.strategy.archetype === 'html_report') {
            pushCardEntry(scaffold.htmlCard, 'HTML 预览');
            pushCardEntry(scaffold.filesCard, '结果文件');
            return entries;
        }

        pushCardEntry(scaffold.overviewCard, '总览');
        pushCardEntry(scaffold.tableCard, '结果表');

        if (isPanelVisible(scaffold.chartCard)) {
            var chartItems = scaffold.chartCard.querySelectorAll('.integrated-chart-item');
            if (chartItems.length) {
                chartItems.forEach(function(item, index) {
                    var titleNode = item.querySelector('.integrated-chart-item-title');
                    var label = text(titleNode && titleNode.textContent, '图表 ' + (index + 1));
                    var id = 'report-chart-' + (index + 1);
                    item.id = id;
                    entries.push({ label: label, targetId: id, level: 1 });
                });
            } else {
                pushCardEntry(scaffold.chartCard, '图表');
            }
        }

        if (isPanelVisible(scaffold.sectionsCard)) {
            var flowItems = scaffold.sectionsCard.querySelectorAll('.report-flow-item');
            if (flowItems.length) {
                flowItems.forEach(function(item, index) {
                    var label = text(item.getAttribute('data-outline-label'), '分段 ' + (index + 1));
                    var id = 'report-section-' + (index + 1);
                    item.id = id;
                    entries.push({ label: label, targetId: id, level: 1 });
                });
            } else {
                pushCardEntry(scaffold.sectionsCard, '结果分段');
            }
        }

        pushCardEntry(scaffold.filesCard, '结果文件');
        return entries;
    }

    function renderOutline(entries) {
        var nav = document.getElementById('result-report-outline-nav');
        if (!nav) {
            return;
        }
        nav.innerHTML = '';
        entries.forEach(function(entry) {
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'result-report-outline-link' + (entry.level ? ' nested' : '');
            button.textContent = entry.label;
            button.setAttribute('data-target-id', entry.targetId);
            button.addEventListener('click', function() {
                nav.querySelectorAll('.result-report-outline-link').forEach(function(node) {
                    node.classList.remove('active');
                });
                button.classList.add('active');
                var target = document.getElementById(entry.targetId);
                if (target && typeof target.scrollIntoView === 'function') {
                    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            });
            nav.appendChild(button);
        });
        var first = nav.querySelector('.result-report-outline-link');
        if (first) {
            first.classList.add('active');
        }
    }

    function renderFeatureReport(feature, view, options) {
        var emptyState = document.getElementById('integrated-empty-state');
        var detail = document.getElementById('integrated-detail');
        if (!emptyState || !detail) {
            return;
        }

        if (!feature || !view) {
            setReportMode('default');
            setPanelVisible(emptyState, true);
            setPanelVisible(detail, false);
            return;
        }

        var scaffold = ensureReportScaffold();
        if (!scaffold) {
            return;
        }

        var sourceMode = inferSourceMode(view, options);
        var viewModel = registryApi.buildViewModel(view || {}, { sourceMode: sourceMode });
        var issueMap = buildIssueMap(viewModel.validation && viewModel.validation.issues);

        setReportMode('report');
        setPanelVisible(emptyState, false);
        setPanelVisible(detail, true);
        detail.dataset.sourceMode = sourceMode;

        renderHeader(viewModel, feature, sourceMode);
        renderSummarySection(viewModel.summary);
        renderSectionsReport(viewModel.sections, { requiredMessage: text(issueMap.sections, '') });

        if (typeof originalRenderIntegratedHtmlPreview === 'function') {
            originalRenderIntegratedHtmlPreview(viewModel.artifacts, { requiredMessage: text(issueMap.html, '') });
        }
        if (typeof originalRenderIntegratedTable === 'function') {
            originalRenderIntegratedTable(asArray(viewModel.table.columns), asArray(viewModel.table.rows), {
                requiredMessage: text(issueMap.table, '')
            });
        }
        if (typeof originalRenderIntegratedChart === 'function') {
            originalRenderIntegratedChart(viewModel.charts, { requiredMessage: text(issueMap.chart, '') });
        }
        if (typeof originalRenderArtifactList === 'function') {
            originalRenderArtifactList(viewModel.artifacts, { requiredMessage: text(issueMap.files, '') });
        }

        setCardHeading(scaffold.tableCard, text(viewModel.table.title, '结果表'), text(
            viewModel.table.subtitle,
            sourceMode === 'history' ? '本次执行返回的结构化结果表。' : '当前工作流可生成的结构化结果表。'
        ));
        setCardHeading(scaffold.chartCard, '图表', '');
        setCardHeading(scaffold.filesCard, '结果文件', '');
        setCardHeading(scaffold.htmlCard, 'HTML 预览', '');
        setCardHeading(scaffold.sectionsCard, '结果分段', '');

        moveReportCards(scaffold, viewModel);
        renderOutline(collectOutlineEntries(scaffold, viewModel));

        var artifactWrap = document.getElementById('artifact-list-wrap');
        if (artifactWrap) {
            artifactWrap.classList.remove('collapsed');
        }

        var content = document.querySelector('.integrated-content');
        if (content) {
            content.scrollTop = 0;
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
            primaryTab: 'report'
        };
    };

    global.renderIntegratedFeature = renderFeatureReport;
    global.renderSummaryGrid = renderSummarySection;
    global.renderIntegratedSections = renderSectionsReport;
    global.renderIntegratedProvenance = function() {};

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
                    noticeMessage: message || '任务已完成，结果报告页已自动刷新'
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
