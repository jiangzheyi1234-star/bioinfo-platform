(function(global) {
    'use strict';

    function renderSummaryGrid(options) {
        var container = options.container;
        var items = Array.isArray(options.summaryItems) ? options.summaryItems : [];
        var escapeHtml = options.escapeHtml;
        if (!container || typeof escapeHtml !== 'function') return;

        if (!items.length) {
            container.innerHTML = '<div class="integrated-input-empty">Overview 暂无 summary 信息。</div>';
            return;
        }

        container.innerHTML = '';
        items.forEach(function(item) {
            var card = document.createElement('div');
            card.className = 'summary-card tone-' + (item.tone || 'default');
            card.innerHTML = '<div class="summary-label">' + escapeHtml(item.label || '') + '</div><div class="summary-value">' + escapeHtml(String(item.value == null ? '' : item.value)) + '</div>';
            container.appendChild(card);
        });
    }

    function renderArtifactList(options) {
        var container = options.container;
        var escapeHtml = options.escapeHtml;
        var normalizedArtifacts = typeof options.sortIntegratedArtifacts === 'function'
            ? options.sortIntegratedArtifacts(Array.isArray(options.artifacts) ? options.artifacts : [])
            : (Array.isArray(options.artifacts) ? options.artifacts : []);
        if (!container || typeof escapeHtml !== 'function') return;

        container.innerHTML = '';
        if (!normalizedArtifacts.length) {
            container.innerHTML = '<li class="artifact-item unavailable"><div class="artifact-main"><span class="artifact-name">' + escapeHtml(options.requiredMessage || '暂无结果文件。') + '</span><span class="artifact-state">缺失</span></div></li>';
            return;
        }

        var pdfArtifact = normalizedArtifacts.find(function(item) {
            return item && item.is_pdf_report && item.available && item.local_path;
        });
        if (pdfArtifact) {
            var btn = document.createElement('div');
            btn.className = 'pdf-report-btn';
            btn.innerHTML = '<span class="pdf-icon">PDF</span><span class="pdf-label">导出 PDF 检测报告</span>';
            btn.addEventListener('click', function() {
                options.openLocalArtifact(pdfArtifact.local_path);
            });
            container.appendChild(btn);
        }

        if (options.requiredMessage) {
            var messageItem = document.createElement('li');
            messageItem.className = 'artifact-item unavailable';
            messageItem.innerHTML = '<div class="artifact-main"><span class="artifact-name">' + escapeHtml(options.requiredMessage) + '</span><span class="artifact-state">缺失</span></div>';
            container.appendChild(messageItem);
        }

        normalizedArtifacts.forEach(function(item) {
            var li = document.createElement('li');
            if (typeof item === 'string') {
                li.textContent = item;
                container.appendChild(li);
                return;
            }
            var available = Boolean(item && item.available && item.local_path);
            li.className = available ? 'artifact-item available' : 'artifact-item unavailable';
            li.innerHTML = '<div class="artifact-main"><span class="artifact-name">' + escapeHtml(item && item.name || '未命名文件') + '</span><span class="artifact-state">' + (available ? '已同步' : '不可用') + '</span></div><div class="artifact-path">' + escapeHtml(item && (item.local_path || item.remote_path) || '') + '</div>';
            if (available) {
                li.addEventListener('click', function() {
                    options.openLocalArtifact(item.local_path);
                });
            }
            container.appendChild(li);
        });
    }

    function renderIntegratedProvenance(options) {
        var container = options.container;
        var escapeHtml = options.escapeHtml;
        var provenance = options.provenance || {};
        var hero = options.hero || {};
        if (!container || typeof escapeHtml !== 'function') return;

        var items = [];
        var params = Array.isArray(provenance.parameters) ? provenance.parameters : [];
        if (String(provenance.execution_id || hero.execution_id || '').trim()) items.push({ label: 'Execution ID', value: String(provenance.execution_id || hero.execution_id || '').trim() });
        if (String(hero.updated_at || '').trim()) items.push({ label: '完成时间', value: String(hero.updated_at || '').trim() });
        if (String(provenance.tool_version || '').trim()) items.push({ label: '工具版本', value: String(provenance.tool_version || '').trim() });
        if (String(provenance.remote_result_dir || '').trim()) items.push({ label: '远端结果目录', value: String(provenance.remote_result_dir || '').trim() });
        if (String(provenance.local_result_dir || '').trim()) items.push({ label: '本地结果目录', value: String(provenance.local_result_dir || '').trim() });
        params.slice(0, 8).forEach(function(item) {
            items.push({ label: item.label || '参数', value: String(item.value == null ? '' : item.value) });
        });

        if (!items.length) {
            container.innerHTML = '<div class="integrated-input-empty">暂无运行追溯信息。</div>';
            return;
        }

        container.innerHTML = items.map(function(item) {
            return '<div class="integrated-input-item"><div class="integrated-input-label">' + escapeHtml(item.label || '') + '</div><div class="integrated-input-desc">' + escapeHtml(item.value || '') + '</div></div>';
        }).join('');
    }

    function renderIntegratedSections(options) {
        var card = options.card;
        var container = options.container;
        var setHidden = options.setHidden;
        var escapeHtml = options.escapeHtml;
        var normalizedSections = Array.isArray(options.sections) ? options.sections : [];
        if (!card || !container || typeof setHidden !== 'function' || typeof escapeHtml !== 'function') return;

        setHidden(card, false);
        card.dataset.panelVisible = '1';
        if (!normalizedSections.length) {
            container.innerHTML = '<div class="' + (options.requiredMessage ? 'task-error-banner' : 'integrated-input-empty') + '">' + escapeHtml(options.requiredMessage || 'Overview 暂无 section 内容。') + '</div>';
            return;
        }

        container.innerHTML = normalizedSections.map(function(section) {
            var summary = Array.isArray(section && section.summary) ? section.summary : [];
            var table = section && section.table && typeof section.table === 'object' ? section.table : {};
            var artifacts = Array.isArray(section && section.artifacts) ? section.artifacts : [];
            return '<div class="integrated-input-item integrated-section-item"><div class="integrated-input-label-row integrated-section-header"><span class="integrated-input-label">' + escapeHtml(section && (section.title || section.section_id) || 'section') + '</span><span class="integrated-input-required">' + escapeHtml(section && section.archetype || '') + '</span></div><div class="integrated-input-desc">' + escapeHtml(summary.slice(0, 3).map(function(item) { return item.label + ': ' + item.value; }).join(' | ') || '无摘要') + '</div><div class="integrated-input-desc">' + escapeHtml('表格 ' + (Array.isArray(table.rows) ? table.rows.length : 0) + ' 行 | 文件 ' + artifacts.length + ' 个') + '</div></div>';
        }).join('');
    }

    global.ResultViewerRenderers = {
        renderSummaryGrid: renderSummaryGrid,
        renderArtifactList: renderArtifactList,
        renderIntegratedProvenance: renderIntegratedProvenance,
        renderIntegratedSections: renderIntegratedSections,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
