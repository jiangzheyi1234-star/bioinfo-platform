(function(global) {
    'use strict';

    var runtimeDependencies = null;

    var HISTORY_RESULT_CONTEXTS = {
        primer_design: {
            featureId: 'primer_design',
            loadingMessage: '正在加载引物结果...',
            successMessage: '已加载该次引物设计结果',
            errorMessage: '任务结果读取失败',
            unavailableMessage: '任务结果加载接口不可用',
        },
        multiplex_primer_panel: {
            featureId: 'multiplex_primer_panel',
            loadingMessage: '正在加载 multiplex 结果...',
            successMessage: '已加载该次 multiplex 结果',
            errorMessage: 'Multiplex 结果读取失败',
            unavailableMessage: 'Multiplex 结果加载接口不可用',
        },
        targeted_sequencing: {
            featureId: 'targeted_sequencing',
            loadingMessage: '正在加载靶向测序结果...',
            successMessage: '已加载靶向测序分析结果',
            errorMessage: '靶向测序结果读取失败',
            unavailableMessage: '靶向测序结果加载接口不可用',
        },
        unknown_sample_detection: {
            featureId: 'unknown_sample_detection',
            loadingMessage: '正在加载未知样品检测结果...',
            successMessage: '已加载检测结果',
            errorMessage: '检测结果读取失败',
            unavailableMessage: '未知样品检测结果加载接口不可用',
        },
        fastp: {
            featureId: 'fastp',
            loadingMessage: '正在加载 fastp QC 结果...',
            successMessage: '已加载 fastp 质控结果',
            errorMessage: 'fastp 结果读取失败',
            unavailableMessage: 'fastp 结果加载接口不可用',
        },
    };

    function parseHistoryParameters(record) {
        try {
            return typeof (record && record.parameters) === 'string'
                ? JSON.parse(record.parameters || '{}')
                : ((record && record.parameters) || {});
        } catch (_) {
            return {};
        }
    }

    function resolveHistoryResultContext(record) {
        var toolId = String(record && record.tool_id || '').trim();
        var params = parseHistoryParameters(record);
        if (toolId === 'centrifuge' || toolId === 'kraken2') {
            var workflow = String(params.workflow || '').trim();
            return workflow === 'unknown_detection'
                ? HISTORY_RESULT_CONTEXTS.unknown_sample_detection
                : {
                    featureId: toolId,
                    loadingMessage: '正在加载 ' + toolId + ' 分类结果...',
                    successMessage: '已加载 ' + toolId + ' 分类结果',
                    errorMessage: '靶向测序结果读取失败',
                    unavailableMessage: '靶向测序结果加载接口不可用',
                };
        }
        return HISTORY_RESULT_CONTEXTS[toolId] || {
            featureId: toolId,
            loadingMessage: '正在加载 ' + (toolId || '任务') + ' 结果...',
            successMessage: '已加载任务结果',
            errorMessage: '任务结果读取失败',
            unavailableMessage: '任务结果加载接口不可用',
        };
    }

    function loadExecutionResultsFromHistory(options) {
        var executionId = String(options.executionId || '').trim();
        if (!executionId) {
            return;
        }
        var context = options.context || {};
        var bridgeResultsService = options.bridgeResultsService;
        if (!bridgeResultsService || typeof bridgeResultsService.loadExecutionResult !== 'function') {
            throw new Error('HistoryResultLoader requires bridgeResultsService.loadExecutionResult');
        }

        var loadingMessage = context.loadingMessage || '正在加载任务结果...';
        var successMessage = context.successMessage || '已加载任务结果';
        var errorMessage = context.errorMessage || '任务结果读取失败';
        if (typeof options.showNotice === 'function') {
            options.showNotice(loadingMessage, 'warning', 10000);
        }

        bridgeResultsService.loadExecutionResult(executionId, function(json) {
            try {
                var payload = JSON.parse(json || '{}');
                if (payload.status !== 'ok' || !payload.view) {
                    if (typeof options.showNotice === 'function') {
                        options.showNotice(payload.message || errorMessage);
                    }
                    return;
                }
                if (typeof options.applyPayload !== 'function') {
                    throw new Error('HistoryResultLoader requires applyPayload');
                }
                options.applyPayload(payload, executionId, context);
                if (typeof options.showNotice === 'function') {
                    options.showNotice(payload.message || successMessage, 'success');
                }
            } catch (error) {
                console.error('Failed to parse history results via get_results_for_execution:', error);
                if (typeof options.showNotice === 'function') {
                    options.showNotice(errorMessage);
                }
            }
        }, function() {
            if (typeof options.showNotice === 'function') {
                options.showNotice(context.unavailableMessage || '任务结果加载接口不可用');
            }
        });
    }

    function openExecution(options) {
        var executionId = String(options.executionId || '').trim();
        if (!executionId) {
            if (typeof options.showNotice === 'function') {
                options.showNotice('任务提交成功，但缺少 execution_id，无法自动定位');
            }
            return;
        }

        var record = options.record || (typeof options.findHistoryRecord === 'function'
            ? options.findHistoryRecord(executionId)
            : null);
        var normalizeExecutionStatus = options.normalizeExecutionStatus || function(value) {
            return String(value || '').trim().toLowerCase();
        };
        var status = normalizeExecutionStatus(options.status || options.local_status || (record && record.status));

        if (status === 'completed') {
            loadExecutionResultsFromHistory({
                executionId: executionId,
                context: options.resultContext || resolveHistoryResultContext(record || {}),
                bridgeResultsService: options.bridgeResultsService,
                showNotice: options.showNotice,
                applyPayload: options.applyPayload,
            });
            return;
        }

        var shouldFetchRemoteStatus = typeof options.fetchRemoteStatus === 'boolean'
            ? options.fetchRemoteStatus
            : (status === 'running' || status === 'failed');
        if (typeof options.focusHistoryExecution === 'function') {
            options.focusHistoryExecution(executionId, {
                expand: true,
                fetchRemoteStatus: shouldFetchRemoteStatus,
                noticeMessage: options.noticeMessage || '',
            });
        }
    }

    function configureRuntime(dependencies) {
        runtimeDependencies = Object.assign({}, runtimeDependencies || {}, dependencies || {});
    }

    function getConfiguredRuntime() {
        if (!runtimeDependencies) {
            throw new Error('HistoryResultLoader runtime is not configured');
        }
        var requiredKeys = [
            'bridgeResultsService',
            'showNotice',
            'findHistoryRecord',
            'normalizeExecutionStatus',
            'focusHistoryExecution',
            'applyPayload',
        ];
        requiredKeys.forEach(function(key) {
            if (typeof runtimeDependencies[key] !== 'function' && key !== 'bridgeResultsService') {
                throw new Error('HistoryResultLoader runtime missing dependency: ' + key);
            }
        });
        if (!runtimeDependencies.bridgeResultsService) {
            throw new Error('HistoryResultLoader runtime missing dependency: bridgeResultsService');
        }
        return runtimeDependencies;
    }

    function openExecutionWithRuntime(executionId, context) {
        var runtime = getConfiguredRuntime();
        var normalizedContext = context || {};
        return openExecution({
            executionId: executionId,
            record: normalizedContext.record,
            status: normalizedContext.status,
            local_status: normalizedContext.local_status,
            resultContext: normalizedContext.resultContext,
            fetchRemoteStatus: normalizedContext.fetchRemoteStatus,
            noticeMessage: normalizedContext.noticeMessage,
            bridgeResultsService: runtime.bridgeResultsService,
            showNotice: runtime.showNotice,
            findHistoryRecord: runtime.findHistoryRecord,
            normalizeExecutionStatus: runtime.normalizeExecutionStatus,
            focusHistoryExecution: runtime.focusHistoryExecution,
            applyPayload: runtime.applyPayload,
        });
    }

    global.HistoryResultLoader = {
        HISTORY_RESULT_CONTEXTS: HISTORY_RESULT_CONTEXTS,
        parseHistoryParameters: parseHistoryParameters,
        resolveHistoryResultContext: resolveHistoryResultContext,
        loadExecutionResultsFromHistory: loadExecutionResultsFromHistory,
        openExecution: openExecution,
        configureRuntime: configureRuntime,
        openExecutionWithRuntime: openExecutionWithRuntime,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
