(function(global) {
    'use strict';

    function ensureCallback(fn) {
        return typeof fn === 'function' ? fn : function() {};
    }

    function createBridgeHistoryService(options) {
        if (!options || typeof options.getBridge !== 'function') {
            throw new Error('BridgeHistoryService requires getBridge()');
        }

        function getBridge() {
            return options.getBridge();
        }

        return {
            loadExecutionHistory: function(onSuccess, onError) {
                var bridge = getBridge();
                if (!bridge || typeof bridge.get_execution_history !== 'function') {
                    ensureCallback(onError)(new Error('执行历史接口不可用'));
                    return;
                }
                bridge.get_execution_history(ensureCallback(onSuccess));
            },
            getExecutionRemoteStatus: function(executionId, onSuccess, onError) {
                var bridge = getBridge();
                if (!bridge || typeof bridge.get_execution_remote_status !== 'function') {
                    ensureCallback(onError)(new Error('远端状态接口不可用'));
                    return;
                }
                bridge.get_execution_remote_status(executionId, ensureCallback(onSuccess));
            },
            deleteExecutionHistory: function(executionId, onSuccess, onError) {
                var bridge = getBridge();
                if (!bridge || typeof bridge.delete_execution_history !== 'function') {
                    ensureCallback(onError)(new Error('删除任务接口不可用'));
                    return;
                }
                bridge.delete_execution_history(executionId, ensureCallback(onSuccess));
            },
        };
    }

    global.BridgeHistoryService = {
        createBridgeHistoryService: createBridgeHistoryService,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
