(function(global) {
    'use strict';

    function renderIntegratedSidebar(options) {
        var container = options.container;
        var features = Array.isArray(options.features) ? options.features : [];
        var escapeHtml = options.escapeHtml;
        var selectedFeatureId = String(options.selectedFeatureId || '').trim();

        if (!container || typeof escapeHtml !== 'function') {
            return;
        }

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
                ? '<span class="ui-badge integrated-feature-badge integrated-feature-pin-badge">已固定</span>'
                : '';
            var actionHtml = isHistoryResult
                ? ''
                    + '<div class="integrated-feature-actions">'
                    + '  <button type="button" class="integrated-feature-action ' + (isPinned ? 'is-active' : '') + '" data-action="pin">' + (isPinned ? '取消固定' : '固定') + '</button>'
                    + '  <button type="button" class="integrated-feature-action" data-action="close">关闭</button>'
                    + '</div>'
                : '';

            item.innerHTML = ''
                + '<div class="integrated-feature-main">'
                + '  <div class="integrated-feature-name">' + escapeHtml(feature && (feature.name || feature.id) || featureId) + '</div>'
                + '  <div class="integrated-feature-desc">' + escapeHtml(feature && feature.description || '') + '</div>'
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
    }

    global.IntegratedSidebarRenderer = {
        renderIntegratedSidebar: renderIntegratedSidebar,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
