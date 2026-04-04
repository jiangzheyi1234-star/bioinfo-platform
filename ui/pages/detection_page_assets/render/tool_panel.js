(function(global) {
    'use strict';

    var runtimeDependencies = null;

    function configureRuntime(dependencies) {
        runtimeDependencies = Object.assign({}, runtimeDependencies || {}, dependencies || {});
    }

    function getRuntime() {
        if (!runtimeDependencies) {
            throw new Error('ToolPanelRenderer runtime is not configured');
        }
        return runtimeDependencies;
    }

    function getCategoryName(category) {
        var names = {
            qc: '质量控制 (QC)',
            host_removal: '宿主去除',
            taxonomy: '物种分类',
            binning: '分箱',
            quality: '质量评估',
            annotation: '功能注释',
            blast: '序列比对',
            unknown: '其他'
        };
        return names[category] || String(category || '').toUpperCase();
    }

    function loadTools() {
        var runtime = getRuntime();
        console.log('Loading tools...');
        runtime.bridgeToolsService.loadTools(function(json) {
            try {
                runtime.setAllTools(JSON.parse(json));
                console.log('✓ Loaded ' + runtime.getAllTools().length + ' tools');
                renderToolsList();
            } catch (e) {
                console.error('Failed to parse tools:', e);
            }
        }, function(error) {
            console.error('Failed to load tools:', error);
        });
    }

    function renderToolsList(searchQuery) {
        var runtime = getRuntime();
        var container = document.getElementById('tools-list');
        if (!container) {
            return;
        }
        container.innerHTML = '';

        var filtered = runtime.getAllTools();
        var query = String(searchQuery || '').toLowerCase();
        if (query) {
            filtered = filtered.filter(function(tool) {
                var searchText = (tool.id + ' ' + tool.name + ' ' + tool.description).toLowerCase();
                return searchText.includes(query);
            });
        }

        var count = document.getElementById('count');
        if (count) {
            count.textContent = filtered.length + ' tools';
        }

        if (filtered.length === 0) {
            container.innerHTML = '<div class="integrated-input-empty tools-empty-state">No tools found</div>';
            return;
        }

        var grouped = {};
        filtered.forEach(function(tool) {
            var category = tool.category || 'unknown';
            if (!grouped[category]) {
                grouped[category] = [];
            }
            grouped[category].push(tool);
        });

        Object.keys(grouped).sort().forEach(function(category) {
            container.appendChild(createCategoryGroup(category, grouped[category]));
        });
    }

    function createCategoryGroup(category, tools) {
        var group = document.createElement('div');
        group.className = 'category-group';

        var header = document.createElement('div');
        header.className = 'category-header';
        header.innerHTML = '<span>' + getCategoryName(category) + '</span><span class="category-arrow">▼</span>';
        header.addEventListener('click', function() {
            group.classList.toggle('collapsed');
        });

        var toolsContainer = document.createElement('div');
        toolsContainer.className = 'category-tools';
        tools.forEach(function(tool) {
            toolsContainer.appendChild(createToolItem(tool));
        });

        group.appendChild(header);
        group.appendChild(toolsContainer);
        return group;
    }

    function createToolItem(tool) {
        var item = document.createElement('div');
        item.className = 'tool-item';
        item.dataset.toolId = tool.id;
        item.innerHTML = '<div class="tool-name">' + tool.name + '</div><div class="tool-desc">' + (tool.description || 'No description available') + '</div>';
        item.addEventListener('click', function() {
            selectTool(tool.id);
        });
        return item;
    }

    function selectTool(toolId) {
        var runtime = getRuntime();
        console.log('Selecting tool:', toolId);
        runtime.setSelectedToolId(toolId);

        document.querySelectorAll('.tool-item').forEach(function(item) {
            item.classList.remove('selected');
        });
        var item = document.querySelector('[data-tool-id="' + toolId + '"]');
        if (item) {
            item.classList.add('selected');
        }

        runtime.bridgeToolsService.selectTool(toolId);
        runtime.bridgeToolsService.getToolDescriptor(toolId, function(json) {
            try {
                var descriptor = JSON.parse(json);
                runtime.setSelectedDescriptor(descriptor);
                runtime.toolDescriptorCache[toolId] = descriptor;
                console.log('Tool descriptor:', descriptor);
                showToolPanel(descriptor);
            } catch (e) {
                console.error('Failed to parse descriptor:', e);
            }
        }, function(error) {
            console.error('Failed to load descriptor:', error);
        });
    }

    function showToolPanel(descriptor) {
        var runtime = getRuntime();
        runtime.setHidden(document.querySelector('.panel-placeholder'), true);
        runtime.setHidden(document.getElementById('panel-content'), false);

        document.getElementById('tool-name').textContent = descriptor.name || descriptor.id;
        document.getElementById('tool-id').textContent = descriptor.id;
        document.getElementById('tool-version').textContent = 'v' + (descriptor.version || 'unknown');
        document.getElementById('tool-category').textContent = getCategoryName(descriptor.category || 'unknown');

        renderInputs(descriptor.inputs || []);
        renderParams(descriptor.parameters || []);

        if (descriptor.databases && descriptor.databases.length > 0) {
            runtime.setHidden(document.getElementById('databases-section'), false);
            renderDatabases(descriptor.databases);
        } else {
            runtime.setHidden(document.getElementById('databases-section'), true);
        }
    }

    function renderInputs(inputs) {
        var runtime = getRuntime();
        var container = document.getElementById('inputs-container');
        container.innerHTML = '';

        if (inputs.length === 0) {
            container.innerHTML = '<div class="integrated-input-empty">No input files required</div>';
            return;
        }

        inputs.forEach(function(input) {
            var group = document.createElement('div');
            group.className = 'form-group';
            var required = input.required !== false ? '<span class="required">*</span>' : '';
            var browseFilter = runtime.getInputBrowseFilter(input, runtime.getSelectedDescriptor() || {});
            var validator = runtime.getInputSelectionValidator(input, runtime.getSelectedDescriptor() || {});

            group.innerHTML = ''
                + '<label class="form-label">' + (input.label || input.name) + required + '</label>'
                + '<div class="input-group">'
                + '  <input type="text" class="ui-field" id="input-' + input.name + '" placeholder="' + (input.description || 'Select file...') + '" readonly>'
                + '  <button class="ui-button ui-button--secondary ui-button--sm form-browse-btn" onclick="window.ToolPanelRenderer.browseFile(\'input-' + input.name + '\', \'' + browseFilter + '\', \'' + validator + '\')">Browse...</button>'
                + '</div>'
                + (input.description ? '<div class="form-help">' + input.description + '</div>' : '');

            container.appendChild(group);
        });
    }

    function renderParams(params) {
        var runtime = getRuntime();
        var container = document.getElementById('params-container');
        container.innerHTML = '';

        if (params.length === 0) {
            container.innerHTML = '<div class="integrated-input-empty">No parameters to configure</div>';
            return;
        }

        params.forEach(function(param) {
            var group = document.createElement('div');
            group.className = 'form-group';
            var label = runtime.escapeHtml(param.label || param.name || '参数');
            var recommendedValue = runtime.getRecommendedValueFromUsage(runtime.getSelectedDescriptor(), param.name);
            var defaultValue = recommendedValue !== undefined ? recommendedValue : (param.default !== undefined ? param.default : '');
            var tooltipText = runtime.buildParamTooltipText(param, runtime.getSelectedDescriptor());
            var tooltipHtml = tooltipText
                ? '<button type="button" class="help-icon-btn" aria-label="参数说明" aria-expanded="false" data-help-text="' + runtime.escapeHtml(tooltipText) + '" title="' + runtime.escapeHtml(tooltipText) + '">?</button>'
                : '';
            var inputHtml = '';

            if (param.type === 'int' || param.type === 'integer') {
                inputHtml = '<input type="number" class="ui-field" id="param-' + param.name + '" value="' + defaultValue + '" step="1">';
            } else if (param.type === 'float' || param.type === 'number') {
                inputHtml = '<input type="number" class="ui-field" id="param-' + param.name + '" value="' + defaultValue + '" step="0.01">';
            } else if (param.type === 'bool' || param.type === 'boolean') {
                inputHtml = '<select class="ui-field" id="param-' + param.name + '"><option value="true" ' + (defaultValue === true ? 'selected' : '') + '>Yes</option><option value="false" ' + (defaultValue === false ? 'selected' : '') + '>No</option></select>';
            } else if (Array.isArray(param.choices) && param.choices.length) {
                inputHtml = '<select class="ui-field" id="param-' + param.name + '">' + param.choices.map(function(choice) {
                    return '<option value="' + runtime.escapeHtml(String(choice)) + '" ' + (String(defaultValue) === String(choice) ? 'selected' : '') + '>' + runtime.escapeHtml(String(choice)) + '</option>';
                }).join('') + '</select>';
            } else {
                inputHtml = '<input type="text" class="ui-field" id="param-' + param.name + '" value="' + runtime.escapeHtml(String(defaultValue)) + '" placeholder="' + runtime.escapeHtml(param.description || '') + '">';
            }

            var guide = runtime.getUsageGuideForParam(runtime.getSelectedDescriptor(), param.name);
            var helper = guide && guide.recommendation || param.description || '';
            var helperHtml = helper ? '<div class="form-help">' + runtime.escapeHtml(String(helper)) + '</div>' : '';
            group.innerHTML = '<label class="form-label">' + label + tooltipHtml + '</label>' + inputHtml + helperHtml;
            container.appendChild(group);
        });

        container.insertAdjacentHTML('beforeend', runtime.buildUsagePresetsPanel(runtime.getSelectedDescriptor() || {}, 'tool-panel'));
        if (typeof runtime.bindHelpTooltipInteractions === 'function') {
            runtime.bindHelpTooltipInteractions();
        }
    }

    function renderDatabases(databases) {
        var runtime = getRuntime();
        var container = document.getElementById('databases-container');
        container.innerHTML = '';

        databases.forEach(function(db) {
            var key = db.param_name || db.name;
            var group = document.createElement('div');
            group.className = 'form-group';
            var required = db.required !== false ? '<span class="required">*</span>' : '';
            var isRemote = db.scope === 'remote';

            group.innerHTML = ''
                + '<label class="form-label">' + runtime.escapeHtml(db.label || key) + required + '</label>'
                + '<div class="input-group">'
                + '  <input type="text" class="ui-field" id="db-' + key + '" placeholder="' + runtime.escapeHtml(db.description || 'Select database path...') + '"' + (isRemote ? ' readonly' : '') + '>'
                + '  <button class="ui-button ui-button--secondary ui-button--sm form-browse-btn" onclick="' + (isRemote
                    ? 'window.ToolPanelRenderer.browseRemoteFile(\'db-' + key + '\')'
                    : 'window.ToolPanelRenderer.browseFile(\'db-' + key + '\')') + '">Browse...</button>'
                + '</div>'
                + (db.scope ? '<div class="form-help">' + runtime.escapeHtml(String(db.scope)) + '</div>' : '');

            container.appendChild(group);
        });
    }

    function browseRemoteFile(inputId) {
        var runtime = getRuntime();
        console.log('Browse remote file:', inputId);
        runtime.bridgeToolsService.browseRemoteFile(inputId, function(rawResult) {
            if (!rawResult) {
                return;
            }
            var payload = null;
            try {
                payload = JSON.parse(rawResult);
            } catch (e) {
                payload = { path: rawResult, error: '' };
            }

            var filePath = String((payload == null ? void 0 : payload.path) || '');
            var errorMessage = String((payload == null ? void 0 : payload.error) || '');
            if (errorMessage) {
                runtime.showNotice(errorMessage);
                return;
            }
            if (filePath) {
                var el = document.getElementById(inputId);
                if (el) {
                    el.value = filePath;
                    el.title = filePath;
                }
            }
        }, function(error) {
            runtime.showNotice(error && error.message ? error.message : '远端文件选择接口不可用');
        });
    }

    function browseFile(inputId, fileFilter, validator) {
        var runtime = getRuntime();
        var normalizedFilter = fileFilter || '所有文件 (*.*)';
        var normalizedValidator = validator || '';
        console.log('Browse file:', inputId);
        runtime.bridgeToolsService.browseFile(inputId, normalizedFilter, normalizedValidator, function(rawResult) {
            if (!rawResult) {
                return;
            }
            var payload = null;
            try {
                payload = JSON.parse(rawResult);
            } catch (e) {
                payload = { path: rawResult, error: '' };
            }

            var filePath = String((payload == null ? void 0 : payload.path) || '');
            var errorMessage = String((payload == null ? void 0 : payload.error) || '');
            if (!filePath) {
                return;
            }
            if (errorMessage) {
                runtime.showNotice(errorMessage);
                return;
            }
            if (normalizedValidator === 'primer_genomes_bundle' && !runtime.isPrimerGenomesBundlePath(filePath)) {
                runtime.showNotice('仅支持 .zip/.tar/.tar.gz/.tgz 或单个 .fasta/.fna/.fa 文件');
                return;
            }
            var el = document.getElementById(inputId);
            if (el) {
                el.value = filePath;
            }
        }, function(error) {
            runtime.showNotice(error && error.message ? error.message : '文件选择接口不可用');
        });
    }

    function runTool() {
        var runtime = getRuntime();
        if (!runtime.getSelectedToolId() || !runtime.getSelectedDescriptor()) {
            runtime.showNotice('请先选择工具', 'warning');
            return;
        }

        console.log('Running tool:', runtime.getSelectedToolId());
        var params = {};
        var selectedDescriptor = runtime.getSelectedDescriptor();
        var inputs = selectedDescriptor.inputs || [];
        for (var i = 0; i < inputs.length; i += 1) {
            var input = inputs[i];
            var inputValue = document.getElementById('input-' + input.name);
            var value = inputValue && inputValue.value && inputValue.value.trim();
            if (input.required !== false && !value) {
                runtime.showNotice('缺少必填输入: ' + (input.label || input.name), 'warning');
                return;
            }
            if (value) {
                params[input.name] = value;
            }
        }

        var parameters = selectedDescriptor.parameters || [];
        parameters.forEach(function(param) {
            var element = document.getElementById('param-' + param.name);
            if (!element) return;
            var value = element.value;
            if (param.type === 'int' || param.type === 'integer') value = parseInt(value, 10);
            else if (param.type === 'float' || param.type === 'number') value = parseFloat(value);
            else if (param.type === 'bool' || param.type === 'boolean') value = value === 'true';
            params[param.name] = value;
        });

        var databases = selectedDescriptor.databases || [];
        for (var j = 0; j < databases.length; j += 1) {
            var db = databases[j];
            var key = db.param_name || db.name;
            var dbEl = document.getElementById('db-' + key);
            var dbValue = dbEl && dbEl.value && dbEl.value.trim();
            if (db.required !== false && !dbValue) {
                runtime.showNotice('缺少必填数据库路径: ' + (db.label || key), 'warning');
                return;
            }
            if (dbValue) {
                params[key] = dbValue;
            }
        }

        console.log('Parameters:', params);
        var runBtn = document.getElementById('run-btn');
        if (runBtn) {
            runBtn.disabled = true;
            runBtn.textContent = '运行中...';
        }
        runtime.bridgeToolsService.runTool(runtime.getSelectedToolId(), JSON.stringify(params));
    }

    function onRunResult(result) {
        var runtime = getRuntime();
        var runBtn = document.getElementById('run-btn');
        if (runBtn) {
            runBtn.disabled = false;
            runBtn.textContent = '▶ 运行工具';
        }

        if (!result || !result.status) {
            runtime.showNotice('运行结果未知');
            return;
        }
        if (result.status === 'ok') {
            var executionId = String(result.execution_id || '').trim();
            if (!executionId) {
                runtime.showNotice('任务已提交，但缺少 execution_id，无法自动定位');
                runtime.loadHistory();
                runtime.loadIntegratedWorkbench(true);
                return;
            }

            runtime.showNotice(result.message || '任务已提交', 'success');
            runtime.loadIntegratedWorkbench(true);
            runtime.openExecutionWithRuntime(executionId, {
                status: 'pending',
                fetchRemoteStatus: false,
                keepMainView: true,
                noticeMessage: '已定位到新提交任务，可在运行历史视图查看状态',
            });
            return;
        }
        if (result.status === 'no_project') {
            runtime.showNotice(result.message || '请先选择项目', 'warning');
            return;
        }
        if (result.status === 'no_sample') {
            runtime.showNotice(result.message || '样本不存在', 'warning');
            return;
        }
        runtime.showNotice(result.message || '任务提交失败');
    }

    function clearForm() {
        document.querySelectorAll('.ui-field').forEach(function(input) {
            if (!input.readOnly) {
                input.value = '';
            }
        });
    }

    global.ToolPanelRenderer = {
        configureRuntime: configureRuntime,
        loadTools: loadTools,
        renderToolsList: renderToolsList,
        selectTool: selectTool,
        browseRemoteFile: browseRemoteFile,
        browseFile: browseFile,
        runTool: runTool,
        onRunResult: onRunResult,
        clearForm: clearForm,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
