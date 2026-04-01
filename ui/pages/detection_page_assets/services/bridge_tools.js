(function(global) {
    'use strict';

    function ensureCallback(fn) {
        return typeof fn === 'function' ? fn : function() {};
    }

    function createBridgeToolsService(options) {
        if (!options || typeof options.getBridge !== 'function') {
            throw new Error('BridgeToolsService requires getBridge()');
        }

        function getBridge() {
            return options.getBridge();
        }

        return {
            loadTools: function(onSuccess, onError) {
                var bridge = getBridge();
                if (!bridge || typeof bridge.get_tools !== 'function') {
                    ensureCallback(onError)(new Error('工具列表接口不可用'));
                    return;
                }
                bridge.get_tools(ensureCallback(onSuccess));
            },
            getToolDescriptor: function(toolId, onSuccess, onError) {
                var bridge = getBridge();
                if (!bridge || typeof bridge.get_tool_descriptor !== 'function') {
                    ensureCallback(onError)(new Error('工具描述接口不可用'));
                    return;
                }
                bridge.get_tool_descriptor(toolId, ensureCallback(onSuccess));
            },
            runTool: function(toolId, paramsJson, onSuccess, onError) {
                var bridge = getBridge();
                if (!bridge || typeof bridge.run_tool !== 'function') {
                    ensureCallback(onError)(new Error('运行工具接口不可用'));
                    return;
                }
                bridge.run_tool(toolId, paramsJson, ensureCallback(onSuccess));
            },
            selectTool: function(toolId) {
                var bridge = getBridge();
                if (!bridge || typeof bridge.select_tool !== 'function') {
                    throw new Error('工具选择接口不可用');
                }
                bridge.select_tool(toolId);
            },
            browseRemoteFile: function(inputId, onSuccess, onError) {
                var bridge = getBridge();
                if (!bridge || typeof bridge.browse_remote_file !== 'function') {
                    ensureCallback(onError)(new Error('远端文件选择接口不可用'));
                    return;
                }
                bridge.browse_remote_file(inputId, ensureCallback(onSuccess));
            },
            browseFile: function(inputId, fileFilter, validator, onSuccess, onError) {
                var bridge = getBridge();
                if (!bridge || typeof bridge.browse_file !== 'function') {
                    ensureCallback(onError)(new Error('文件选择接口不可用'));
                    return;
                }
                bridge.browse_file(inputId, fileFilter, validator, ensureCallback(onSuccess));
            },
        };
    }

    global.BridgeToolsService = {
        createBridgeToolsService: createBridgeToolsService,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
