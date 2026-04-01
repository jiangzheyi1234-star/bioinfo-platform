(function(global) {
    'use strict';

    var runtimeDependencies = null;
    var noticeHideTimer = null;
    var helpTooltipBound = false;
    var activeHelpTooltip = null;

    function configureRuntime(dependencies) {
        runtimeDependencies = Object.assign({}, runtimeDependencies || {}, dependencies || {});
    }

    function getRuntime() {
        if (!runtimeDependencies) {
            throw new Error('DetectionPageUiFeedback runtime is not configured');
        }
        return runtimeDependencies;
    }

    function ensureNoticeContainer() {
        var container = document.getElementById('inline-notice-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'inline-notice-container';
            container.className = 'inline-notice-container';
            document.body.appendChild(container);
        }
        return container;
    }

    function dismissNotice() {
        if (noticeHideTimer) {
            clearTimeout(noticeHideTimer);
            noticeHideTimer = null;
        }
        var container = document.getElementById('inline-notice-container');
        if (container) {
            container.innerHTML = '';
        }
    }

    function showNotice(message, type, durationMs) {
        var runtime = getRuntime();
        var text = String(message || '').trim();
        var tone = type || 'error';
        var duration = durationMs == null ? 3600 : durationMs;
        if (!text) {
            return;
        }

        var container = ensureNoticeContainer();
        var toneConfig = tone === 'success'
            ? { noticeClass: 'ui-notice--success', icon: '✓' }
            : tone === 'warning'
                ? { noticeClass: 'ui-notice--warning', icon: '⚠' }
                : { noticeClass: 'ui-notice--danger', icon: 'ⓘ' };

        container.innerHTML = ''
            + '<div role="alert" class="ui-notice ' + toneConfig.noticeClass + '">'
            + '  <div class="ui-notice-icon">' + toneConfig.icon + '</div>'
            + '  <div class="ui-notice-body">' + runtime.escapeHtml(text) + '</div>'
            + '  <button type="button" class="ui-notice-close" onclick="window.DetectionPageUiFeedback.dismissNotice()" aria-label="关闭">×</button>'
            + '</div>';

        if (noticeHideTimer) {
            clearTimeout(noticeHideTimer);
        }
        noticeHideTimer = setTimeout(dismissNotice, Math.max(1200, Number(duration) || 3600));
    }

    function closeHelpTooltip() {
        if (!activeHelpTooltip) {
            return;
        }
        var trigger = activeHelpTooltip.trigger;
        if (trigger) {
            trigger.setAttribute('aria-expanded', 'false');
        }
        try {
            activeHelpTooltip.node && activeHelpTooltip.node.remove();
        } catch (_) {
            // ignore
        }
        activeHelpTooltip = null;
    }

    function openHelpTooltip(triggerEl, text) {
        closeHelpTooltip();
        if (!triggerEl || !text) {
            return;
        }

        var tip = document.createElement('div');
        tip.className = 'help-tooltip-popover';
        tip.setAttribute('role', 'tooltip');
        tip.textContent = String(text);
        document.body.appendChild(tip);

        var rect = triggerEl.getBoundingClientRect();
        var margin = 8;
        var maxLeft = Math.max(8, window.innerWidth - tip.offsetWidth - 8);
        var left = Math.min(Math.max(8, rect.left), maxLeft);
        var top = rect.bottom + margin;
        if (top + tip.offsetHeight > window.innerHeight - 8) {
            top = Math.max(8, rect.top - tip.offsetHeight - margin);
        }
        tip.style.left = Math.round(left) + 'px';
        tip.style.top = Math.round(top) + 'px';

        triggerEl.setAttribute('aria-expanded', 'true');
        activeHelpTooltip = { trigger: triggerEl, node: tip };
    }

    function bindHelpTooltipInteractions() {
        if (helpTooltipBound) {
            return;
        }
        helpTooltipBound = true;

        document.addEventListener('click', function(event) {
            var target = event.target;
            var trigger = target && target.closest ? target.closest('.help-icon-btn[data-help-text]') : null;
            if (trigger) {
                event.preventDefault();
                event.stopPropagation();
                var text = String(trigger.getAttribute('data-help-text') || '').trim();
                if (!text) {
                    return;
                }
                if (activeHelpTooltip && activeHelpTooltip.trigger === trigger) {
                    closeHelpTooltip();
                    return;
                }
                openHelpTooltip(trigger, text);
                return;
            }

            if (activeHelpTooltip && activeHelpTooltip.node && target && activeHelpTooltip.node.contains(target)) {
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

    global.DetectionPageUiFeedback = {
        configureRuntime: configureRuntime,
        ensureNoticeContainer: ensureNoticeContainer,
        showNotice: showNotice,
        dismissNotice: dismissNotice,
        bindHelpTooltipInteractions: bindHelpTooltipInteractions,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
