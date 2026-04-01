(function(global) {
    'use strict';

    var runtimeDependencies = null;

    function configureRuntime(dependencies) {
        runtimeDependencies = Object.assign({}, runtimeDependencies || {}, dependencies || {});
    }

    function getRuntime() {
        if (!runtimeDependencies) {
            throw new Error('IntegratedRunModal runtime is not configured');
        }
        return runtimeDependencies;
    }

    function getContext() {
        return getRuntime().getIntegratedRunModalContext();
    }

    function setContext(nextContext) {
        getRuntime().setIntegratedRunModalContext(nextContext);
    }

    function ensureIntegratedRunModal() {
        var runtime = getRuntime();
        var modal = document.getElementById('integrated-run-modal');
        if (modal) {
            return modal;
        }

        modal = document.createElement('div');
        modal.id = 'integrated-run-modal';
        modal.className = 'integrated-run-modal ui-modal';
        modal.innerHTML = ''
            + '<div class="integrated-run-modal-backdrop ui-modal__backdrop" data-close="1"></div>'
            + '<div class="integrated-run-modal-card ui-modal__card" role="dialog" aria-modal="true" aria-labelledby="integrated-run-modal-title">'
            + '  <div class="integrated-run-modal-header">'
            + '    <h3 id="integrated-run-modal-title">Run Entry</h3>'
            + '    <button class="integrated-run-modal-close" type="button" id="integrated-run-modal-close" aria-label="Close">&times;</button>'
            + '  </div>'
            + '  <div class="integrated-run-modal-body">'
            + '    <div class="integrated-run-modal-line"><span>Feature</span><strong id="integrated-run-modal-feature">-</strong></div>'
            + '    <div class="integrated-run-modal-line"><span>Tool</span><strong id="integrated-run-modal-tool">-</strong></div>'
            + '    <div class="integrated-run-modal-line is-hidden" id="integrated-run-modal-tool-select-row">'
            + '      <span>分类工具</span>'
            + '      <div id="integrated-run-modal-tool-switch" class="integrated-tool-switch" role="group" aria-label="分类工具选择"></div>'
            + '    </div>'
            + '    <div class="integrated-run-modal-hint" id="integrated-run-modal-hint">Fill fields in this popup and submit directly, or open plugin workbench.</div>'
            + '    <div class="integrated-run-modal-form" id="integrated-run-modal-form"></div>'
            + '  </div>'
            + '  <div class="integrated-run-modal-actions">'
            + '    <button class="ui-button ui-button--secondary" type="button" id="integrated-run-modal-cancel">Cancel</button>'
            + '    <button class="ui-button ui-button--secondary" type="button" id="integrated-run-modal-open-tools">Open Tools</button>'
            + '    <button class="ui-button ui-button--primary" type="button" id="integrated-run-modal-confirm">Submit</button>'
            + '  </div>'
            + '</div>';

        document.body.appendChild(modal);

        modal.addEventListener('click', function(event) {
            if (event.target && event.target.dataset && event.target.dataset.close === '1') {
                closeIntegratedRunModal();
            }
        });

        var closeBtn = document.getElementById('integrated-run-modal-close');
        var cancelBtn = document.getElementById('integrated-run-modal-cancel');
        var openToolsBtn = document.getElementById('integrated-run-modal-open-tools');
        var confirmBtn = document.getElementById('integrated-run-modal-confirm');

        if (closeBtn) closeBtn.addEventListener('click', closeIntegratedRunModal);
        if (cancelBtn) cancelBtn.addEventListener('click', closeIntegratedRunModal);
        if (openToolsBtn) openToolsBtn.addEventListener('click', goToIntegratedRunTool);
        if (confirmBtn) confirmBtn.addEventListener('click', runIntegratedRunModal);

        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') {
                closeIntegratedRunModal();
            }
        });

        if (typeof runtime.bindHelpTooltipInteractions === 'function') {
            runtime.bindHelpTooltipInteractions();
        }

        return modal;
    }

    function openIntegratedRunModal(feature, toolId) {
        var runtime = getRuntime();
        var integratedWorkbench = runtime.getIntegratedWorkbench();
        var view = integratedWorkbench && integratedWorkbench.views
            ? integratedWorkbench.views[feature && feature.id]
            : null;
        var toolIds = Array.isArray(view && view.tool_ids) && view.tool_ids.length
            ? view.tool_ids.slice()
            : [toolId].filter(Boolean);
        var activeToolId = toolIds.indexOf(toolId) >= 0 ? toolId : (toolIds[0] || toolId);

        setContext({
            featureId: feature && feature.id || '',
            featureName: feature && (feature.name || feature.id) || '',
            toolId: activeToolId,
            descriptor: null,
            _descriptorSeq: 0,
        });

        var modal = ensureIntegratedRunModal();
        var featureEl = document.getElementById('integrated-run-modal-feature');
        var toolEl = document.getElementById('integrated-run-modal-tool');
        var toolSelectRowEl = document.getElementById('integrated-run-modal-tool-select-row');
        var toolSwitchEl = document.getElementById('integrated-run-modal-tool-switch');
        var hintEl = document.getElementById('integrated-run-modal-hint');
        var formEl = document.getElementById('integrated-run-modal-form');

        if (featureEl) featureEl.textContent = getContext().featureName || '-';
        if (toolEl) toolEl.textContent = activeToolId || '-';
        if (hintEl) hintEl.textContent = 'Loading input requirements...';
        if (formEl) formEl.innerHTML = '<div class="integrated-input-empty">Loading...</div>';

        function applyDescriptor(descriptor, requestSeq) {
            var context = getContext();
            if (!context || requestSeq !== context._descriptorSeq) {
                return;
            }
            context.descriptor = descriptor || {};
            setContext(context);
            var inputCount = (descriptor.inputs || []).length;
            var paramCount = (descriptor.parameters || []).length;
            var dbCount = (descriptor.databases || []).length;
            if (hintEl) {
                hintEl.textContent = 'Inputs ' + inputCount + ', Params ' + paramCount + ', Databases ' + dbCount + '.';
            }
            renderIntegratedRunModalForm(descriptor || {});
        }

        function fetchDescriptorForTool(nextToolId) {
            var context = getContext();
            if (!context) {
                return;
            }
            context.toolId = nextToolId;
            context._descriptorSeq += 1;
            setContext(context);
            if (toolEl) toolEl.textContent = nextToolId || '-';
            if (hintEl) hintEl.textContent = 'Loading input requirements...';
            if (formEl) formEl.innerHTML = '<div class="integrated-input-empty">Loading...</div>';

            var requestSeq = getContext()._descriptorSeq;
            var cached = runtime.toolDescriptorCache[nextToolId];
            if (cached) {
                applyDescriptor(cached, requestSeq);
                return;
            }

            runtime.bridgeToolsService.getToolDescriptor(nextToolId, function(json) {
                try {
                    var descriptor = JSON.parse(json || '{}');
                    runtime.toolDescriptorCache[nextToolId] = descriptor;
                    applyDescriptor(descriptor, requestSeq);
                } catch (_) {
                    if (getContext() && requestSeq === getContext()._descriptorSeq) {
                        if (hintEl) hintEl.textContent = 'Failed to load requirements. Use Open Tools instead.';
                        if (formEl) formEl.innerHTML = '<div class="integrated-input-empty">Parse failed.</div>';
                    }
                }
            }, function() {
                if (getContext() && requestSeq === getContext()._descriptorSeq) {
                    if (hintEl) hintEl.textContent = 'Tool descriptor API unavailable.';
                    if (formEl) formEl.innerHTML = '<div class="integrated-input-empty">API unavailable.</div>';
                }
            });
        }

        if (toolSelectRowEl && toolSwitchEl) {
            if (toolIds.length > 1) {
                runtime.setHidden(toolSelectRowEl, false);
                toolSwitchEl.innerHTML = toolIds.map(function(id) {
                    var activeClass = id === activeToolId ? 'is-active' : '';
                    return '<button type="button" class="integrated-tool-switch-btn ' + activeClass + '" data-tool-id="' + runtime.escapeHtml(id) + '">' + runtime.escapeHtml(id) + '</button>';
                }).join('');
                toolSwitchEl.querySelectorAll('.integrated-tool-switch-btn').forEach(function(btn) {
                    btn.addEventListener('click', function() {
                        var nextToolId = btn.getAttribute('data-tool-id') || '';
                        if (!nextToolId || nextToolId === (getContext() && getContext().toolId)) {
                            return;
                        }
                        toolSwitchEl.querySelectorAll('.integrated-tool-switch-btn').forEach(function(item) {
                            item.classList.remove('is-active');
                        });
                        btn.classList.add('is-active');
                        fetchDescriptorForTool(nextToolId);
                    });
                });
            } else {
                runtime.setHidden(toolSelectRowEl, true);
                toolSwitchEl.innerHTML = '';
            }
        }

        fetchDescriptorForTool(activeToolId);
        modal.classList.add('show');
    }

    function renderIntegratedRunModalForm(descriptor) {
        var runtime = getRuntime();
        var formEl = document.getElementById('integrated-run-modal-form');
        if (!formEl) {
            return;
        }

        var inputs = descriptor.inputs || [];
        var parameters = descriptor.parameters || [];
        var databases = descriptor.databases || [];
        var parts = [];

        if (inputs.length) {
            parts.push('<div class="integrated-run-modal-group"><div class="integrated-run-modal-group-title">Inputs</div>');
            inputs.forEach(function(input) {
                var required = input.required !== false ? '<span class="integrated-input-required">Required</span>' : '';
                var browseFilter = runtime.getInputBrowseFilter(input, descriptor || {});
                var validator = runtime.getInputSelectionValidator(input, descriptor || {});
                var id = 'modal-input-' + input.name;
                parts.push(
                    '<div class="integrated-input-item">'
                    + '  <div class="integrated-input-label-row"><span class="integrated-input-label">' + runtime.escapeHtml(input.label || input.name || 'Input') + '</span>' + required + '</div>'
                    + '  <div class="input-group">'
                    + '    <input type="text" class="ui-field" id="' + id + '" placeholder="' + runtime.escapeHtml(input.description || 'Select file') + '" readonly>'
                    + '    <button class="ui-button ui-button--secondary ui-button--sm form-browse-btn" type="button" onclick="browseFile(\'' + id + '\', \'' + browseFilter + '\', \'' + validator + '\')">Browse...</button>'
                    + '  </div>'
                    + '</div>'
                );
            });
            parts.push('</div>');
        }

        if (parameters.length) {
            parts.push('<div class="integrated-run-modal-group"><div class="integrated-run-modal-group-title">Parameters</div>');
            parameters.forEach(function(param) {
                var id = 'modal-param-' + param.name;
                var label = runtime.escapeHtml(param.label || param.name || 'Param');
                var recommendedValue = runtime.getRecommendedValueFromUsage(descriptor, param.name);
                var defaultValue = recommendedValue !== undefined
                    ? recommendedValue
                    : (param.default !== undefined ? param.default : '');
                var tooltipText = runtime.buildParamTooltipText(param, descriptor);
                var tooltipHtml = tooltipText
                    ? '<button type="button" class="help-icon-btn" aria-label="参数说明" aria-expanded="false" data-help-text="' + runtime.escapeHtml(tooltipText) + '" title="' + runtime.escapeHtml(tooltipText) + '">?</button>'
                    : '';
                var inputHtml = '';
                if (param.type === 'int' || param.type === 'integer') {
                    inputHtml = '<input type="number" class="ui-field" id="' + id + '" value="' + defaultValue + '" step="1">';
                } else if (param.type === 'float' || param.type === 'number') {
                    inputHtml = '<input type="number" class="ui-field" id="' + id + '" value="' + defaultValue + '" step="0.01">';
                } else if (param.type === 'bool' || param.type === 'boolean') {
                    inputHtml = '<select class="ui-field" id="' + id + '"><option value="true" ' + (defaultValue === true ? 'selected' : '') + '>Yes</option><option value="false" ' + (defaultValue === false ? 'selected' : '') + '>No</option></select>';
                } else {
                    inputHtml = '<input type="text" class="ui-field" id="' + id + '" value="' + runtime.escapeHtml(String(defaultValue)) + '" placeholder="' + runtime.escapeHtml(param.description || '') + '">';
                }
                var guide = runtime.getUsageGuideForParam(descriptor, param.name);
                var helper = guide && guide.recommendation || param.description || '';
                var helperHtml = helper
                    ? '<div class="integrated-param-help">' + runtime.escapeHtml(String(helper)) + '</div>'
                    : '';
                parts.push(
                    '<div class="integrated-input-item">'
                    + '  <div class="integrated-input-label-row"><span class="integrated-input-label">' + label + '</span>' + tooltipHtml + '</div>'
                    +      inputHtml
                    +      helperHtml
                    + '</div>'
                );
            });
            parts.push(runtime.buildUsagePresetsPanel(descriptor, 'integrated-modal'));
            parts.push('</div>');
        }

        if (databases.length) {
            parts.push('<div class="integrated-run-modal-group"><div class="integrated-run-modal-group-title">Databases</div>');
            databases.forEach(function(db) {
                var key = db.param_name || db.name;
                var id = 'modal-db-' + key;
                var required = db.required !== false ? '<span class="integrated-input-required">Required</span>' : '';
                parts.push(
                    '<div class="integrated-input-item">'
                    + '  <div class="integrated-input-label-row"><span class="integrated-input-label">' + runtime.escapeHtml(db.label || key) + '</span>' + required + '</div>'
                    + '  <input type="text" class="ui-field integrated-managed-field" id="' + id + '" value="" readonly placeholder="自动使用设置中配置的数据库路径">'
                    + '</div>'
                );
            });
            parts.push('</div>');
        }

        if (!parts.length) {
            parts.push('<div class="integrated-input-empty">No declared inputs. You can submit directly.</div>');
        }

        formEl.innerHTML = parts.join('');
        if (typeof runtime.bindHelpTooltipInteractions === 'function') {
            runtime.bindHelpTooltipInteractions();
        }

        if (databases.length) {
            databases.forEach(function(db) {
                if (!db || !db.scope) return;
                var key = db.param_name || db.name;
                var id = 'modal-db-' + key;
                var inputEl = document.getElementById(id);
                if (!inputEl || !inputEl.parentElement) return;
                var scopeDiv = document.createElement('div');
                scopeDiv.className = 'integrated-db-scope';
                scopeDiv.textContent = String(db.scope);
                inputEl.parentElement.appendChild(scopeDiv);
            });
        }
    }

    function runIntegratedRunModal() {
        var runtime = getRuntime();
        var context = getContext();
        if (!context || !context.toolId) {
            return;
        }

        var toolId = context.toolId;
        var descriptor = context.descriptor || {};
        var params = {};

        var inputs = descriptor.inputs || [];
        for (var i = 0; i < inputs.length; i += 1) {
            var input = inputs[i];
            var inputValue = document.getElementById('modal-input-' + input.name);
            var value = inputValue && inputValue.value && inputValue.value.trim();
            if (input.required !== false && !value) {
                runtime.showNotice('Missing required input: ' + (input.label || input.name), 'warning');
                return;
            }
            if (value) params[input.name] = value;
        }

        var parameters = descriptor.parameters || [];
        parameters.forEach(function(param) {
            var element = document.getElementById('modal-param-' + param.name);
            if (!element) return;
            var value = element.value;
            if (param.type === 'int' || param.type === 'integer') value = parseInt(value, 10);
            else if (param.type === 'float' || param.type === 'number') value = parseFloat(value);
            else if (param.type === 'bool' || param.type === 'boolean') value = value === 'true';
            params[param.name] = value;
        });

        var databases = descriptor.databases || [];
        for (var j = 0; j < databases.length; j += 1) {
            var db = databases[j];
            var key = db.param_name || db.name;
            var el = document.getElementById('modal-db-' + key);
            var dbValue = el && el.value && el.value.trim();
            if (el && el.readOnly && !dbValue) continue;
            if (db.required !== false && !dbValue) {
                runtime.showNotice('Missing required database path: ' + (db.label || key), 'warning');
                return;
            }
            if (dbValue) params[key] = dbValue;
        }

        var confirmBtn = document.getElementById('integrated-run-modal-confirm');
        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.textContent = 'Submitting...';
        }

        runtime.bridgeToolsService.runTool(toolId, JSON.stringify(params));
        closeIntegratedRunModal();
    }

    function closeIntegratedRunModal() {
        var modal = document.getElementById('integrated-run-modal');
        if (modal) modal.classList.remove('show');
        var confirmBtn = document.getElementById('integrated-run-modal-confirm');
        if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.textContent = 'Submit';
        }
    }

    function goToIntegratedRunTool() {
        var runtime = getRuntime();
        var context = getContext();
        if (!context || !context.toolId) {
            closeIntegratedRunModal();
            return;
        }

        var toolId = context.toolId;
        closeIntegratedRunModal();
        runtime.switchTab('tools');
        runtime.selectTool(toolId);

        var panel = document.getElementById('right-panel');
        if (panel && panel.scrollIntoView) {
            panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }

    global.IntegratedRunModal = {
        configureRuntime: configureRuntime,
        ensureIntegratedRunModal: ensureIntegratedRunModal,
        openIntegratedRunModal: openIntegratedRunModal,
        renderIntegratedRunModalForm: renderIntegratedRunModalForm,
        runIntegratedRunModal: runIntegratedRunModal,
        closeIntegratedRunModal: closeIntegratedRunModal,
        goToIntegratedRunTool: goToIntegratedRunTool,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
