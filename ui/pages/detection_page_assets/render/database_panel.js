(function(global) {
    'use strict';

    function renderDatabaseResources(options) {
        var grid = options.grid;
        var empty = options.empty;
        var resources = Array.isArray(options.resources) ? options.resources : [];
        var setHidden = options.setHidden;
        var escapeHtml = options.escapeHtml;
        var onShowDetail = typeof options.onShowDetail === 'function' ? options.onShowDetail : null;

        if (!grid || !empty || typeof setHidden !== 'function' || typeof escapeHtml !== 'function') {
            return;
        }

        if (!resources.length) {
            setHidden(grid, true);
            grid.innerHTML = '';
            setHidden(empty, false);
            return;
        }

        setHidden(empty, true);
        setHidden(grid, false);
        grid.innerHTML = resources.map(function(item, index) {
            var stats = item.stats || {};
            var summary = item.type === 'directory'
                ? 'FASTA ' + (stats.fasta_count || 0) + ' · BLAST 索引 ' + (stats.blast_index_count || 0)
                : '大小 ' + (Number(stats.size_bytes || 0) / 1024 / 1024).toFixed(2) + ' MB';
            var initial = escapeHtml(String(item.name || '?').slice(0, 1));
            return ''
                + '<article class="database-resource-card">'
                + '  <div class="database-resource-badge">' + initial + '</div>'
                + '  <div class="database-resource-title">' + escapeHtml(item.name || '') + '</div>'
                + '  <div class="database-resource-desc">' + escapeHtml(item.description || '暂无描述') + '</div>'
                + '  <div class="database-resource-meta">' + escapeHtml(summary) + '</div>'
                + '  <button class="ui-button ui-button--secondary ui-button--sm database-detail-btn" type="button" data-resource-index="' + index + '">查看详情</button>'
                + '</article>';
        }).join('');

        if (onShowDetail) {
            grid.querySelectorAll('.database-detail-btn').forEach(function(button) {
                button.addEventListener('click', function() {
                    onShowDetail(Number(button.getAttribute('data-resource-index')));
                });
            });
        }
    }

    function buildDatabaseResourceDetail(item) {
        if (!item) {
            return [];
        }
        var stats = item.stats || {};
        var lines = [
            '名称: ' + (item.name || ''),
            '类型: ' + (item.type || ''),
            '路径: ' + (item.path || ''),
            '说明: ' + (item.description || ''),
        ];
        if (item.type === 'directory') {
            lines.push('FASTA 文件数: ' + (stats.fasta_count || 0));
            lines.push('BLAST 索引数: ' + (stats.blast_index_count || 0));
        } else if (typeof stats.size_bytes !== 'undefined') {
            lines.push('文件大小: ' + (Number(stats.size_bytes || 0) / 1024 / 1024).toFixed(2) + ' MB');
        }
        return lines;
    }

    global.DatabasePanelRenderer = {
        renderDatabaseResources: renderDatabaseResources,
        buildDatabaseResourceDetail: buildDatabaseResourceDetail,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
