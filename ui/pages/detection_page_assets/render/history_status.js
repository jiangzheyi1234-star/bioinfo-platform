(function(global) {
    'use strict';

    var runtimeDependencies = null;

    function configureRuntime(dependencies) {
        runtimeDependencies = Object.assign({}, runtimeDependencies || {}, dependencies || {});
    }

    function getRuntime() {
        if (!runtimeDependencies) {
            throw new Error('HistoryStatusRenderer runtime is not configured');
        }
        return runtimeDependencies;
    }

    function buildExecutionRemoteStatusHtml(data) {
        var runtime = getRuntime();
        var remoteStatusRaw = String(data.remote_status || '').toUpperCase();
        var localStatusRaw = String(data.local_status || '').toLowerCase();
        var heartbeatAgeValue = Number(data.heartbeat_age_sec);
        var heartbeatAge = Number.isFinite(heartbeatAgeValue) ? heartbeatAgeValue + ' s' : '-';
        var hasRecentHeartbeat = Number.isFinite(heartbeatAgeValue) && heartbeatAgeValue <= 180;

        var serverRuntimeStatus = '状态未知';
        if (data.screen_running === true) {
            if (hasRecentHeartbeat) {
                serverRuntimeStatus = '服务器活跃';
            } else if (Number.isFinite(heartbeatAgeValue)) {
                serverRuntimeStatus = '疑似挂起（心跳超时 ' + heartbeatAgeValue + 's）';
            } else {
                serverRuntimeStatus = '进程在跑（未检测到心跳）';
            }
        } else if (data.screen_running === false) {
            if (remoteStatusRaw === 'COMPLETED' || remoteStatusRaw === 'SUCCESS' || localStatusRaw === 'completed') {
                serverRuntimeStatus = '已结束（完成）';
            } else if (remoteStatusRaw === 'FAILED' || remoteStatusRaw === 'ERROR' || localStatusRaw === 'failed') {
                serverRuntimeStatus = '已结束（失败）';
            } else {
                serverRuntimeStatus = '未检测到进程';
            }
        } else if (remoteStatusRaw === 'RUNNING' && hasRecentHeartbeat) {
            serverRuntimeStatus = '服务器活跃';
        }

        var screenText = data.screen_running == null ? '-' : (data.screen_running ? 'running' : 'not found');
        var logTail = runtime.escapeHtml(String(data.log_tail || '').trim());
        var logBlock = logTail ? '<pre class="task-details-pre task-details-pre-scroll">' + logTail + '</pre>' : '';
        return ''
            + '<div class="task-error-banner task-info-banner">'
            + '服务器状态: ' + runtime.escapeHtml(serverRuntimeStatus)
            + ' ｜ 远端状态: ' + runtime.escapeHtml(String(data.remote_status || '-'))
            + ' ｜ screen: ' + runtime.escapeHtml(screenText)
            + ' ｜ 心跳: ' + runtime.escapeHtml(heartbeatAge)
            + ' ｜ exit_code: ' + runtime.escapeHtml(String(data.exit_code || '-'))
            + '</div>'
            + '<pre class="task-details-pre task-details-pre-offset">'
            + runtime.escapeHtml(JSON.stringify({
                execution_id: data.execution_id,
                tool_id: data.tool_id,
                sample_id: data.sample_id,
                local_status: data.local_status,
                task_dir: data.task_dir,
                ssh_connected: data.ssh_connected,
                remote_status: data.remote_status || '',
                screen_running: data.screen_running,
                exit_code: data.exit_code || '',
                heartbeat: data.heartbeat || '',
                heartbeat_age_sec: heartbeatAge,
                local_error: data.local_error || ''
            }, null, 2))
            + '</pre>'
            + logBlock;
    }

    function toggleExecutionRemoteStatus(executionId, rowEl) {
        var runtime = getRuntime();
        if (!executionId || !rowEl) {
            return;
        }
        if (runtime.isRemoteStatusLoading(executionId)) {
            runtime.showNotice('远端状态查询进行中...', 'warning', 2000);
            return;
        }

        var detailsBodyEl = rowEl.querySelector('.task-details-card-body');
        if (!detailsBodyEl) {
            return;
        }

        var existing = detailsBodyEl.querySelector('.remote-status-block');
        if (existing) {
            existing.remove();
            rowEl.classList.remove('expanded');
            var summaryEl = rowEl.querySelector('.task-summary');
            if (summaryEl) {
                summaryEl.setAttribute('aria-expanded', 'false');
            }
            return;
        }

        runtime.showNotice('正在查询远端执行状态...', 'warning', 6000);
        runtime.setRemoteStatusLoading(executionId, true);
        runtime.bridgeHistoryService.getExecutionRemoteStatus(executionId, function(json) {
            try {
                var payload = JSON.parse(json || '{}');
                if (payload.status !== 'ok' || !payload.data) {
                    runtime.showNotice(payload.message || '读取远端状态失败');
                    return;
                }

                var block = document.createElement('div');
                block.className = 'remote-status-block';
                block.innerHTML = buildExecutionRemoteStatusHtml(payload.data);
                detailsBodyEl.prepend(block);
                rowEl.classList.add('expanded');
                var summaryEl = rowEl.querySelector('.task-summary');
                if (summaryEl) {
                    summaryEl.setAttribute('aria-expanded', 'true');
                }
                runtime.showNotice('远端状态已更新', 'success', 2500);
            } catch (e) {
                console.error('Failed to parse remote status:', e);
                runtime.showNotice('远端状态解析失败');
            } finally {
                runtime.setRemoteStatusLoading(executionId, false);
            }
        }, function(error) {
            runtime.setRemoteStatusLoading(executionId, false);
            runtime.showNotice(error && error.message ? error.message : '远端状态接口不可用');
        });
    }

    function deleteHistoryExecution(executionId) {
        var runtime = getRuntime();
        if (!executionId) {
            return;
        }
        if (!window.confirm('确定删除这条任务历史吗？\n仅从历史列表隐藏，不删除结果文件。')) {
            return;
        }

        runtime.bridgeHistoryService.deleteExecutionHistory(executionId, function(json) {
            try {
                var payload = JSON.parse(json);
                if (payload.status !== 'ok') {
                    runtime.showNotice(payload.message || '删除任务记录失败');
                    return;
                }
                runtime.showNotice(payload.message || '任务记录已删除', 'success');
                runtime.loadHistory();
            } catch (e) {
                console.error('Failed to parse delete execution result:', e);
                runtime.showNotice('删除任务记录失败');
            }
        }, function(error) {
            runtime.showNotice(error && error.message ? error.message : '删除任务接口不可用');
        });
    }

    global.HistoryStatusRenderer = {
        configureRuntime: configureRuntime,
        buildExecutionRemoteStatusHtml: buildExecutionRemoteStatusHtml,
        toggleExecutionRemoteStatus: toggleExecutionRemoteStatus,
        deleteHistoryExecution: deleteHistoryExecution,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
