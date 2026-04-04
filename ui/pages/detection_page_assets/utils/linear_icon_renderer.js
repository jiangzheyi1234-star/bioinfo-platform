(function(global) {
    'use strict';

    var ICON_DEFS = {
        'refresh-cw': [
            'M21 2v6h-6',
            'M3 12a9 9 0 0 1 15-6.7L21 8',
            'M3 22v-6h6',
            'M21 12a9 9 0 0 1-15 6.7L3 16',
        ],
        'trash-2': [
            'M3 6h18',
            'M8 6V4h8v2',
            'M19 6l-1 14H6L5 6',
            'M10 11v6',
            'M14 11v6',
        ],
    };

    function escAttr(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function createIcon(name, options) {
        var iconName = String(name || '').trim();
        var def = ICON_DEFS[iconName];
        if (!def) {
            throw new Error('Unknown icon: ' + iconName);
        }

        var opts = options || {};
        var size = Number(opts.size || 16);
        if (!Number.isFinite(size) || size <= 0) {
            size = 16;
        }
        var className = String(opts.className || '').trim();
        var attrs = [
            'xmlns="http://www.w3.org/2000/svg"',
            'viewBox="0 0 24 24"',
            'width="' + size + '"',
            'height="' + size + '"',
            'fill="none"',
            'stroke="currentColor"',
            'stroke-width="' + (opts.strokeWidth || 1.9) + '"',
            'stroke-linecap="round"',
            'stroke-linejoin="round"',
        ];
        if (className) {
            attrs.push('class="' + escAttr(className) + '"');
        }
        if (opts.ariaHidden !== false) {
            attrs.push('aria-hidden="true"');
            attrs.push('focusable="false"');
        }
        if (opts.label) {
            attrs.push('aria-label="' + escAttr(opts.label) + '"');
            attrs.push('role="img"');
        }

        var pathMarkup = def.map(function(pathData) {
            return '<path d="' + escAttr(pathData) + '"></path>';
        }).join('');

        return '<svg ' + attrs.join(' ') + '>' + pathMarkup + '</svg>';
    }

    function renderDataIcons(root) {
        var host = root && root.querySelectorAll ? root : document;
        if (!host || !host.querySelectorAll) {
            return;
        }
        host.querySelectorAll('[data-icon]').forEach(function(node) {
            var iconName = String(node.getAttribute('data-icon') || '').trim();
            if (!iconName) {
                return;
            }
            var className = String(node.getAttribute('data-icon-class') || '').trim();
            var sizeAttr = Number(node.getAttribute('data-icon-size') || 16);
            try {
                node.innerHTML = createIcon(iconName, {
                    className: className,
                    size: sizeAttr,
                    ariaHidden: true,
                });
            } catch (error) {
                console.error('Failed to render icon "' + iconName + '":', error);
            }
        });
    }

    global.LinearIconRenderer = {
        createIcon: createIcon,
        renderDataIcons: renderDataIcons,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
