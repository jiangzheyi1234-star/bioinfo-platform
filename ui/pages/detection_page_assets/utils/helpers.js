(function(global) {
    'use strict';

    function normalizePresetLabel(label) {
        return String(label || '').toLowerCase();
    }

    function getRecommendedPreset(descriptor) {
        var usage = descriptor && descriptor.usage ? descriptor.usage : {};
        var presets = Array.isArray(usage.presets) ? usage.presets : [];
        if (!presets.length) {
            return null;
        }
        var byId = presets.find(function(preset) {
            return String(preset && preset.id || '').toLowerCase() === 'standard';
        });
        if (byId) {
            return byId;
        }
        var byLabel = presets.find(function(preset) {
            return normalizePresetLabel(preset && preset.label).includes('recommended');
        });
        if (byLabel) {
            return byLabel;
        }
        return presets[0];
    }

    function getUsageGuideForParam(descriptor, paramName) {
        var usage = descriptor && descriptor.usage ? descriptor.usage : {};
        var guides = usage.parameter_guide;
        if (!Array.isArray(guides)) {
            return null;
        }
        return guides.find(function(item) {
            return String(item && item.name || '') === String(paramName || '');
        }) || null;
    }

    function getRecommendedValueFromUsage(descriptor, paramName) {
        var preset = getRecommendedPreset(descriptor);
        if (!preset || !preset.params || typeof preset.params !== 'object') {
            return undefined;
        }
        if (!Object.prototype.hasOwnProperty.call(preset.params, paramName)) {
            return undefined;
        }
        return preset.params[paramName];
    }

    function buildParamTooltipText(param, descriptor) {
        var parts = [];
        if (param && param.description) {
            parts.push(String(param.description).trim());
        }
        if (Array.isArray(param && param.range) && param.range.length === 2) {
            parts.push('范围: ' + param.range[0] + ' ~ ' + param.range[1]);
        }
        if (Array.isArray(param && param.choices) && param.choices.length) {
            parts.push('可选: ' + param.choices.join(', '));
        }
        var guide = getUsageGuideForParam(descriptor, param && param.name || '');
        if (guide && guide.recommendation) {
            parts.push(String(guide.recommendation).trim());
        }
        return parts.filter(Boolean).join('；');
    }

    function buildUsagePresetsPanel(descriptor, panelIdPrefix, escapeHtml) {
        if (typeof escapeHtml !== 'function') {
            throw new Error('DetectionPageHelpers.buildUsagePresetsPanel requires escapeHtml');
        }
        var usage = descriptor && descriptor.usage ? descriptor.usage : {};
        var presets = Array.isArray(usage.presets) ? usage.presets : [];
        if (!presets.length) {
            return '';
        }
        var preferred = getRecommendedPreset(descriptor);
        var listHtml = presets.map(function(preset) {
            var params = (preset && typeof preset.params === 'object') ? preset.params : {};
            var paramPairs = Object.keys(params).map(function(key) {
                return key + '=' + params[key];
            });
            var presetLine = paramPairs.length ? paramPairs.join(', ') : '无显式参数';
            var isRecommended = preferred && preset === preferred;
            var badge = isRecommended ? '<span class="usage-preset-recommended">Recommended</span>' : '';
            var notes = preset && preset.notes
                ? '<div class="usage-preset-notes">' + escapeHtml(String(preset.notes)) + '</div>'
                : '';
            return ''
                + '<div class="usage-preset-row">'
                + '  <div class="usage-preset-head">'
                + '    <span class="usage-preset-label">' + escapeHtml(String(preset && (preset.label || preset.id) || 'preset')) + '</span>'
                +      badge
                + '  </div>'
                + '  <div class="usage-preset-params">' + escapeHtml(presetLine) + '</div>'
                +      notes
                + '</div>';
        }).join('');

        var hint = usage.when_to_use
            ? '<div class="usage-presets-hint">' + escapeHtml(String(usage.when_to_use)) + '</div>'
            : '';

        return ''
            + '<details class="usage-presets-panel" id="' + escapeHtml(panelIdPrefix) + '-usage-presets">'
            + '  <summary>推荐预设与填写说明</summary>'
            +      hint
            + '  <div class="usage-presets-list">' + listHtml + '</div>'
            + '</details>';
    }

    global.DetectionPageHelpers = {
        normalizePresetLabel: normalizePresetLabel,
        getRecommendedPreset: getRecommendedPreset,
        getUsageGuideForParam: getUsageGuideForParam,
        getRecommendedValueFromUsage: getRecommendedValueFromUsage,
        buildParamTooltipText: buildParamTooltipText,
        buildUsagePresetsPanel: buildUsagePresetsPanel,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
