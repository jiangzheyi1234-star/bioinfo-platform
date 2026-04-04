(function(global) {
    'use strict';

    function formatParamsSummary(paramsJson) {
        if (!paramsJson) return '-';
        try {
            var params = typeof paramsJson === 'string' ? JSON.parse(paramsJson) : paramsJson;
            var entries = Object.entries(params).filter(function(entry) {
                return entry[1] !== '' && entry[1] !== null && entry[1] !== undefined;
            });
            var summary = entries.slice(0, 3).map(function(entry) {
                return entry[0] + '=' + entry[1];
            }).join(', ');
            return summary || '-';
        } catch (error) {
            return '-';
        }
    }

    function getStatusText(status) {
        var statusMap = { pending: '等待中', running: '运行中', retrying: '重试中', completed: '已完成', failed: '失败' };
        return statusMap[status] || status;
    }

    function getStatusClass(status) {
        var statusMap = { pending: 'pending', running: 'running', retrying: 'running', completed: 'completed', failed: 'failed' };
        return statusMap[status] || 'unknown';
    }

    function formatExactTime(timestamp) {
        var date = new Date(timestamp * 1000);
        return date.toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
        });
    }

    function formatRelativeTime(timestamp) {
        var nowSeconds = Date.now() / 1000;
        var diff = Math.max(0, Math.round(nowSeconds - Number(timestamp || 0)));
        if (diff < 60) return diff + '秒前';
        if (diff < 3600) return Math.round(diff / 60) + '分钟前';

        var date = new Date(timestamp * 1000);
        var now = new Date();
        if (date.toDateString() === now.toDateString()) {
            return '今天 ' + date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        }
        return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }) + ' ' + date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    }

    function formatDuration(seconds) {
        if (seconds < 60) return Math.round(seconds) + '秒';
        if (seconds < 3600) return Math.round(seconds / 60) + '分钟';
        return Math.round(seconds / 3600) + '小时';
    }

    function getDurationClass(seconds) {
        if (!seconds || seconds < 3600) return 'duration-normal';
        if (seconds < 3 * 3600) return 'duration-warn';
        return 'duration-long';
    }

    function normalizeHistoryStatus(value) {
        return String(value || '').trim().toLowerCase();
    }

    function normalizeStatusFilter(value) {
        var normalized = normalizeHistoryStatus(value);
        return normalized === 'running' || normalized === 'failed' || normalized === 'completed'
            ? normalized
            : 'all';
    }

    function sortHistoryRecords(historyRecords) {
        return historyRecords.slice().sort(function(left, right) {
            var leftTime = Number(left && left.created_at || 0);
            var rightTime = Number(right && right.created_at || 0);
            if (rightTime !== leftTime) {
                return rightTime - leftTime;
            }
            var leftId = String(left && left.execution_id || '');
            var rightId = String(right && right.execution_id || '');
            return rightId.localeCompare(leftId, 'zh-CN');
        });
    }

    function matchesStatusFilter(record, statusFilter) {
        if (statusFilter === 'all') {
            return true;
        }
        var normalizedStatus = normalizeHistoryStatus(record && record.status);
        if (statusFilter === 'running') {
            return normalizedStatus === 'running' || normalizedStatus === 'retrying';
        }
        return normalizedStatus === statusFilter;
    }

    function filterHistoryRecords(options) {
        var query = String(options.query || '').trim().toLowerCase();
        var statusFilter = normalizeStatusFilter(options.statusFilter);
        var historyRecords = Array.isArray(options.historyRecords) ? options.historyRecords : [];
        var allTools = Array.isArray(options.allTools) ? options.allTools : [];
        return historyRecords.filter(function(record) {
            if (!matchesStatusFilter(record, statusFilter)) {
                return false;
            }
            if (!query) {
                return true;
            }
            var toolName = (allTools.find(function(tool) { return tool.id === record.tool_id; }) || {}).name || record.tool_id;
            var haystack = [
                record.execution_id,
                record.tool_id,
                toolName,
                record.sample_name,
                record.sample_id,
                record.parameters,
                record.status,
            ].join(' ').toLowerCase();
            return haystack.includes(query);
        });
    }

    function findHistoryRecord(options) {
        var executionId = String(options.executionId || '').trim();
        var historyRecords = Array.isArray(options.historyRecords) ? options.historyRecords : [];
        if (!executionId) return null;
        return historyRecords.find(function(record) {
            return String(record && record.execution_id || '').trim() === executionId;
        }) || null;
    }

    function getDeleteIconMarkup() {
        var iconRenderer = global.LinearIconRenderer;
        if (!iconRenderer || typeof iconRenderer.createIcon !== 'function') {
            return '<span class="task-action-icon-fallback" aria-hidden="true">×</span>';
        }
        try {
            return iconRenderer.createIcon('trash-2', {
                className: 'task-action-icon',
                size: 15,
                strokeWidth: 1.9,
                ariaHidden: true,
            });
        } catch (error) {
            console.error('Failed to render delete icon:', error);
            return '<span class="task-action-icon-fallback" aria-hidden="true">×</span>';
        }
    }

    function renderHistoryPanel(options) {
        var container = options.container;
        var history = Array.isArray(options.history) ? options.history : [];
        var allTools = Array.isArray(options.allTools) ? options.allTools : [];
        var escapeHtml = options.escapeHtml;
        var pendingExecutionId = String(options.pendingExecutionId || '').trim();
        var pendingOptions = options.pendingOptions || {};
        var activeExecutionId = String(options.activeExecutionId || '').trim();
        var emptyState = options.emptyState || null;

        if (!container || typeof escapeHtml !== 'function') {
            return;
        }

        container.innerHTML = '';
        var focusedRow = null;
        var focusedRemoteStatusRequested = false;

        if (history.length === 0) {
            var emptyTitle = '暂无任务记录';
            var emptyDesc = '新的 Primer Design 或 Multiplex Panel Design 任务会在这里显示。';
            if (emptyState && typeof emptyState.title === 'string' && emptyState.title.trim()) {
                emptyTitle = emptyState.title.trim();
            }
            if (emptyState && typeof emptyState.description === 'string' && emptyState.description.trim()) {
                emptyDesc = emptyState.description.trim();
            }
            container.innerHTML = ''
                + '<div class="history-empty-state">'
                + '  <div class="history-empty-icon">∅</div>'
                + '  <div class="history-empty-title">' + escapeHtml(emptyTitle) + '</div>'
                + '  <div class="history-empty-desc">' + escapeHtml(emptyDesc) + '</div>'
                + '</div>';
            return;
        }

        history.forEach(function(record) {
            var row = document.createElement('div');
            row.className = 'task-row';
            row.dataset.executionId = String(record.execution_id || '');
            if (activeExecutionId && row.dataset.executionId === activeExecutionId) {
                row.classList.add('active');
            }

            var statusText = getStatusText(record.status);
            var statusClass = getStatusClass(record.status);
            var duration = record.completed_at ? formatDuration(record.completed_at - record.created_at) : '-';
            var durationClass = getDurationClass(record.completed_at ? (record.completed_at - record.created_at) : 0);
            var paramsSummary = formatParamsSummary(record.parameters);

            var prettyJson = '{}';
            try {
                var parsed = typeof record.parameters === 'string' ? JSON.parse(record.parameters) : record.parameters;
                prettyJson = JSON.stringify(parsed, null, 4);
            } catch (error) {
                prettyJson = record.parameters || '';
            }

            var toolName = (allTools.find(function(tool) { return tool.id === record.tool_id; }) || {}).name || record.tool_id;
            var sampleNameRaw = record.sample_name || record.sample_id || '-';
            var sampleName = escapeHtml(sampleNameRaw);
            var createdLabel = formatRelativeTime(record.created_at);
            var exactTime = formatExactTime(record.created_at);
            var hasDetails = record.status === 'failed' || prettyJson;
            var detailsHtml = record.status === 'failed' && record.error
                ? '<div class="task-error-banner">错误信息: ' + escapeHtml(record.error) + '</div>'
                : '';
            detailsHtml += '<pre class="task-details-pre">' + escapeHtml(prettyJson) + '</pre>';

            row.innerHTML = ''
                + '<div class="task-summary" role="button" tabindex="0" aria-expanded="false">'
                + '  <div class="col-status-wrap task-status-combo">'
                + '    <span class="status-inline ' + statusClass + '">'
                + '      <span class="status-dot"></span>'
                + ((record.status === 'running' || record.status === 'retrying') ? '<span class="status-spinner"></span>' : '')
                + '      <span>' + statusText + '</span>'
                + '    </span>'
                + '  </div>'
                + '  <div class="col-tool val-tool" title="' + toolName + '">'
                + '    <div class="tool-primary">' + toolName + '</div>'
                + '    <div class="tool-secondary">' + escapeHtml(record.tool_id || '') + '</div>'
                + '  </div>'
                + '  <div class="col-sample val-sample" title="' + sampleName + '">' + sampleName + '</div>'
                + '  <div class="col-params val-params" title="' + escapeHtml(prettyJson || paramsSummary) + '">' + escapeHtml(paramsSummary) + '</div>'
                + '  <div class="col-time val-time" title="' + escapeHtml(exactTime) + '"><div class="time-primary">' + createdLabel + '</div></div>'
                + '  <div class="col-duration val-duration ' + durationClass + '">' + duration + '</div>'
                + '  <div class="col-actions"><div class="task-actions"></div></div>'
                + '</div>'
                + '<div class="task-details' + (hasDetails ? '' : ' empty') + '">'
                + '  <div class="task-details-inner">'
                + '    <div class="task-details-card">'
                + '      <div class="task-details-card-body">' + detailsHtml + '</div>'
                + '    </div>'
                + '  </div>'
                + '</div>';

            var summaryEl = row.querySelector('.task-summary');
            var toggleExpanded = function() {
                if (!hasDetails) {
                    return;
                }
                row.classList.toggle('expanded');
                if (summaryEl) {
                    summaryEl.setAttribute('aria-expanded', row.classList.contains('expanded') ? 'true' : 'false');
                }
            };
            var triggerExecutionOpen = function() {
                if (typeof options.onRowExecutionClick === 'function') {
                    options.onRowExecutionClick(record);
                }
            };
            if (summaryEl) {
                summaryEl.addEventListener('click', function() {
                    triggerExecutionOpen();
                    toggleExpanded();
                });
                summaryEl.addEventListener('keydown', function(event) {
                    if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        triggerExecutionOpen();
                        toggleExpanded();
                    }
                });
            }

            var actionsContainer = row.querySelector('.task-actions');
            if (actionsContainer) {
                actionsContainer.addEventListener('click', function(event) {
                    event.stopPropagation();
                });
            }
            if (record.status === 'completed') {
                var resultContext = typeof options.resolveHistoryResultContext === 'function'
                    ? options.resolveHistoryResultContext(record)
                    : {};
                var viewBtn = document.createElement('button');
                viewBtn.className = 'task-action-btn btn-view';
                viewBtn.textContent = '查看结果';
                viewBtn.onclick = function(event) {
                    event.preventDefault();
                    event.stopPropagation();
                    if (typeof options.openExecution === 'function') {
                        options.openExecution(record.execution_id, {
                            record: record,
                            resultContext: resultContext || {},
                            keepMainView: true,
                        });
                    }
                };
                actionsContainer.appendChild(viewBtn);
            } else {
                var statusBtn = document.createElement('button');
                statusBtn.className = 'task-action-btn btn-view';
                statusBtn.textContent = '查看状态';
                statusBtn.onclick = function(event) {
                    event.preventDefault();
                    event.stopPropagation();
                    if (typeof options.openExecution === 'function') {
                        options.openExecution(record.execution_id, {
                            record: record,
                            keepMainView: true,
                        });
                    }
                };
                actionsContainer.appendChild(statusBtn);
            }

            if (record.status === 'completed' || record.status === 'failed') {
                var delBtn = document.createElement('button');
                delBtn.className = 'task-action-btn btn-delete';
                delBtn.setAttribute('title', '删除任务记录');
                delBtn.setAttribute('aria-label', '删除任务记录');
                delBtn.innerHTML = getDeleteIconMarkup();
                delBtn.onclick = function(event) {
                    event.preventDefault();
                    if (typeof options.deleteHistoryExecution === 'function') {
                        options.deleteHistoryExecution(record.execution_id);
                    }
                };
                actionsContainer.appendChild(delBtn);
            }

            container.appendChild(row);

            if (pendingExecutionId && row.dataset.executionId === pendingExecutionId) {
                focusedRow = row;
                if (pendingOptions.expand !== false) {
                    row.classList.add('expanded');
                    if (summaryEl) {
                        summaryEl.setAttribute('aria-expanded', 'true');
                    }
                }
                if (pendingOptions.fetchRemoteStatus !== false) {
                    focusedRemoteStatusRequested = true;
                }
            }
        });

        if (focusedRow) {
            setTimeout(function() {
                try {
                    focusedRow.scrollIntoView({ block: 'center', behavior: 'smooth' });
                } catch (_) {}
            }, 0);
            if (pendingOptions.noticeMessage && typeof options.showNotice === 'function') {
                options.showNotice(pendingOptions.noticeMessage, 'success', 2800);
            }
            if (focusedRemoteStatusRequested && typeof options.toggleExecutionRemoteStatus === 'function') {
                options.toggleExecutionRemoteStatus(pendingExecutionId, focusedRow);
            }
            if (typeof options.onPendingResolved === 'function') {
                options.onPendingResolved();
            }
        } else if (pendingExecutionId && typeof options.onPendingMissing === 'function') {
            options.onPendingMissing(pendingExecutionId);
        }
    }

    global.HistoryPanelRenderer = {
        formatParamsSummary: formatParamsSummary,
        getStatusText: getStatusText,
        getStatusClass: getStatusClass,
        formatExactTime: formatExactTime,
        formatRelativeTime: formatRelativeTime,
        formatDuration: formatDuration,
        getDurationClass: getDurationClass,
        normalizeStatusFilter: normalizeStatusFilter,
        sortHistoryRecords: sortHistoryRecords,
        filterHistoryRecords: filterHistoryRecords,
        findHistoryRecord: findHistoryRecord,
        renderHistoryPanel: renderHistoryPanel,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
