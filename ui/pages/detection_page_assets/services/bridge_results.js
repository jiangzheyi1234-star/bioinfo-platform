(function(global) {
    'use strict';

    function ensureCallback(fn) {
        return typeof fn === 'function' ? fn : function() {};
    }

    function createBridgeResultsService(options) {
        if (!options || typeof options.getBridge !== 'function') {
            throw new Error('BridgeResultsService requires getBridge()');
        }

        function getBridge() {
            return options.getBridge();
        }

        return {
            loadIntegratedWorkbench: function(onSuccess, onError) {
                var bridge = getBridge();
                if (!bridge || typeof bridge.get_integrated_workbench_config !== 'function') {
                    ensureCallback(onError)(new Error('集成工作台接口不可用'));
                    return;
                }
                bridge.get_integrated_workbench_config(ensureCallback(onSuccess));
            },
            loadExecutionResult: function(executionId, onSuccess, onError) {
                var bridge = getBridge();
                if (!bridge || typeof bridge.get_results_for_execution !== 'function') {
                    ensureCallback(onError)(new Error('任务结果加载接口不可用'));
                    return;
                }
                bridge.get_results_for_execution(executionId, ensureCallback(onSuccess));
            },
            openLocalFile: function(path, onSuccess, onError) {
                var bridge = getBridge();
                if (!bridge || typeof bridge.open_local_file !== 'function') {
                    ensureCallback(onError)(new Error('本地文件打开接口不可用'));
                    return;
                }
                bridge.open_local_file(path, ensureCallback(onSuccess));
            },
            browseDirectory: function(onSuccess, onError) {
                var bridge = getBridge();
                if (!bridge || typeof bridge.browse_directory !== 'function') {
                    ensureCallback(onError)(new Error('目录选择接口不可用'));
                    return;
                }
                bridge.browse_directory(ensureCallback(onSuccess));
            },
            scanLocalDatabaseResources: function(dirPath, onSuccess, onError) {
                var bridge = getBridge();
                if (!bridge || typeof bridge.scan_local_database_resources !== 'function') {
                    ensureCallback(onError)(new Error('数据库扫描接口不可用'));
                    return;
                }
                bridge.scan_local_database_resources(dirPath, ensureCallback(onSuccess));
            },
        };
    }

    global.BridgeResultsService = {
        createBridgeResultsService: createBridgeResultsService,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
