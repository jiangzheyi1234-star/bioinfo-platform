(function(global) {
    'use strict';

    function renderFeatureItems(container, features, options) {
        var selectedFeatureId = String(options.selectedFeatureId || '').trim();
        var escapeHtml = options.escapeHtml;
        var isHistoryList = Boolean(options.isHistoryList);
        container.innerHTML = '';
        features.forEach(function(feature) {
            var featureId = String(feature && feature.id || '').trim();
            var isHistoryResult = Boolean(options.isHistoryResult && options.isHistoryResult(featureId, feature));
            var isPinned = Boolean(options.isPinned && options.isPinned(featureId, feature));
            var item = document.createElement('div');
            item.className = 'integrated-feature-item';
            item.dataset.featureId = featureId;
            item.dataset.sourceMode = isHistoryResult ? 'history' : 'workflow';
            item.classList.toggle('integrated-feature-item--pinned', isPinned);
            item.classList.toggle('active', selectedFeatureId === featureId);
            item.setAttribute('role', 'button');
            item.tabIndex = 0;

            var badgeHtml = feature && feature.badge
                ? '<span class="ui-badge ui-badge--accent integrated-feature-badge">' + escapeHtml(feature.badge) + '</span>'
                : '';
            var pinBadgeHtml = isPinned
                ? '<span class="integrated-feature-pin-dot" title="已固定" aria-label="已固定"></span>'
                : '';
            var isSelected = selectedFeatureId === featureId;
            var actionHtml = isHistoryResult
                ? (isSelected
                    ? ''
                    + '<div class="integrated-feature-actions">'
                    + '  <button type="button" class="integrated-feature-action integrated-feature-action--pin ' + (isPinned ? 'is-active' : '') + '" data-action="pin" aria-label="' + (isPinned ? '取消固定' : '固定') + '" title="' + (isPinned ? '取消固定' : '固定') + '">'
                    + '    <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2h8v2l-2 2v2l2 2v1H4v-1l2-2V6L4 4z"></path><path d="M8 11v3"></path></svg>'
                    + '  </button>'
                    + '  <button type="button" class="integrated-feature-action integrated-feature-action--close" data-action="close" aria-label="关闭" title="关闭">'
                    + '    <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"></path></svg>'
                    + '  </button>'
                    + '</div>'
                    : '')
                : '';

            item.innerHTML = ''
                + '<div class="integrated-feature-main">'
                + '  <div class="integrated-feature-name">' + escapeHtml(feature && (feature.name || feature.id) || featureId) + '</div>'
                + '</div>'
                + '<div class="integrated-feature-meta">'
                + badgeHtml
                + pinBadgeHtml
                + actionHtml
                + '</div>';

            item.addEventListener('click', function() {
                if (typeof options.onSelect === 'function') {
                    options.onSelect(featureId, { sourceMode: isHistoryResult ? 'history' : 'workflow' });
                }
            });
            item.addEventListener('keydown', function(event) {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    if (typeof options.onSelect === 'function') {
                        options.onSelect(featureId, { sourceMode: isHistoryResult ? 'history' : 'workflow' });
                    }
                }
            });
            item.querySelectorAll('[data-action]').forEach(function(actionBtn) {
                actionBtn.addEventListener('click', function(event) {
                    event.preventDefault();
                    event.stopPropagation();
                    var action = String(actionBtn.dataset.action || '').trim();
                    if (action === 'pin' && typeof options.onPinToggle === 'function') {
                        options.onPinToggle(featureId, !isPinned);
                        return;
                    }
                    if (action === 'close' && typeof options.onClose === 'function') {
                        options.onClose(featureId);
                    }
                });
            });

            container.appendChild(item);
        });

        if (features.length === 0 && isHistoryList) {
            container.innerHTML = '<div class="integrated-history-empty">暂无历史结果</div>';
        }
    }

    function renderSectionControls(options) {
        var toggleBtn = options.toggleBtn;
        var countEl = options.countEl;
        var container = options.container;
        var features = Array.isArray(options.features) ? options.features : [];
        var collapsed = Boolean(options.collapsed);
        var controlsId = String(options.controlsId || '').trim();

        if (countEl) {
            countEl.textContent = String(features.length);
        }
        if (container) {
            container.classList.toggle('is-collapsed', collapsed);
        }
        if (!toggleBtn) {
            return;
        }

        toggleBtn.classList.toggle('is-collapsed', collapsed);
        toggleBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        toggleBtn.dataset.collapsed = collapsed ? '1' : '0';
        if (controlsId) {
            toggleBtn.setAttribute('aria-controls', controlsId);
        }
        toggleBtn.disabled = features.length === 0;

        if (toggleBtn.dataset.bound === '1') {
            return;
        }
        toggleBtn.dataset.bound = '1';
        toggleBtn.addEventListener('click', function() {
            var isCollapsed = toggleBtn.dataset.collapsed === '1';
            if (typeof options.onToggle === 'function') {
                options.onToggle(!isCollapsed);
            }
        });
        toggleBtn.addEventListener('keydown', function(event) {
            if (event.key !== 'Enter' && event.key !== ' ') {
                return;
            }
            event.preventDefault();
            var isCollapsed = toggleBtn.dataset.collapsed === '1';
            if (typeof options.onToggle === 'function') {
                options.onToggle(!isCollapsed);
            }
        });
    }

    function renderIntegratedSidebar(options) {
        var analysisContainer = options.analysisContainer;
        var analysisToggleBtn = options.analysisToggleBtn;
        var analysisCountEl = options.analysisCountEl;
        var historyContainer = options.historyContainer;
        var historyToggleBtn = options.historyToggleBtn;
        var historyCountEl = options.historyCountEl;
        var analysisFeatures = Array.isArray(options.analysisFeatures) ? options.analysisFeatures : [];
        var historyFeatures = Array.isArray(options.historyFeatures) ? options.historyFeatures : [];
        var analysisCollapsed = Boolean(options.analysisCollapsed);
        var historyCollapsed = Boolean(options.historyCollapsed);
        var escapeHtml = options.escapeHtml;

        if (!analysisContainer || !analysisToggleBtn || !analysisCountEl || !historyContainer || !historyToggleBtn || !historyCountEl || typeof escapeHtml !== 'function') {
            return;
        }

        renderFeatureItems(analysisContainer, analysisFeatures, Object.assign({}, options, { isHistoryList: false }));
        renderFeatureItems(historyContainer, historyFeatures, Object.assign({}, options, { isHistoryList: true }));
        renderSectionControls({
            toggleBtn: analysisToggleBtn,
            countEl: analysisCountEl,
            container: analysisContainer,
            features: analysisFeatures,
            collapsed: analysisCollapsed,
            controlsId: 'integrated-analysis-feature-list',
            onToggle: options.onAnalysisToggle,
        });
        renderSectionControls({
            toggleBtn: historyToggleBtn,
            countEl: historyCountEl,
            container: historyContainer,
            features: historyFeatures,
            collapsed: historyCollapsed,
            controlsId: 'integrated-history-feature-list',
            onToggle: options.onHistoryToggle,
        });
    }

    global.IntegratedSidebarRenderer = {
        renderIntegratedSidebar: renderIntegratedSidebar,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
