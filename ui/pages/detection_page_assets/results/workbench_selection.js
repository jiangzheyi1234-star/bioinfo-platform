(function(global) {
    'use strict';

    function resolveIntegratedViewSource(options) {
        var preferredSource = String(options.requestedSource || 'workflow').trim() || 'workflow';
        var integratedWorkbench = options.integratedWorkbench;
        var featureId = options.featureId;
        var integratedExecutionViews = options.integratedExecutionViews || {};
        var hasBaseView = Boolean(integratedWorkbench && integratedWorkbench.views && integratedWorkbench.views[featureId]);
        var hasExecutionView = Boolean(integratedExecutionViews[featureId]);

        if (preferredSource === 'history' && hasExecutionView) return 'history';
        if (!hasBaseView && hasExecutionView) return 'history';
        return preferredSource;
    }

    function getPreferredIntegratedViewSource(options) {
        if (options.pendingIntegratedViewSource) {
            return resolveIntegratedViewSource({
                featureId: options.featureId,
                requestedSource: options.pendingIntegratedViewSource,
                integratedWorkbench: options.integratedWorkbench,
                integratedExecutionViews: options.integratedExecutionViews,
            });
        }
        if (
            options.selectedIntegratedFeatureId === options.featureId &&
            options.selectedIntegratedViewSource === 'history' &&
            options.integratedExecutionViews[options.featureId]
        ) {
            return 'history';
        }
        return resolveIntegratedViewSource({
            featureId: options.featureId,
            requestedSource: 'workflow',
            integratedWorkbench: options.integratedWorkbench,
            integratedExecutionViews: options.integratedExecutionViews,
        });
    }

    function getIntegratedFeatureView(options) {
        var integratedWorkbench = options.integratedWorkbench;
        if (!integratedWorkbench) {
            return null;
        }
        var featureId = options.featureId;
        var preferredSource = String(options.sourceMode || 'workflow').trim() || 'workflow';
        var integratedExecutionViews = options.integratedExecutionViews || {};
        if (preferredSource === 'history' && integratedExecutionViews[featureId]) {
            return integratedExecutionViews[featureId];
        }
        return (integratedWorkbench.views || {})[featureId] || integratedExecutionViews[featureId] || null;
    }

    function pickPreferredFeature(options) {
        var features = Array.isArray(options.features) ? options.features : [];
        var preferredFeature = null;
        if (options.pendingIntegratedFeatureId) {
            preferredFeature = features.find(function(feature) { return feature.id === options.pendingIntegratedFeatureId; }) || null;
        }
        if (!preferredFeature && options.selectedIntegratedFeatureId) {
            preferredFeature = features.find(function(feature) { return feature.id === options.selectedIntegratedFeatureId; }) || null;
        }
        if (!preferredFeature && options.openResultsActiveKey) {
            preferredFeature = features.find(function(feature) { return feature.id === options.openResultsActiveKey; }) || null;
        }
        if (!preferredFeature) {
            preferredFeature = features.find(function(feature) { return feature.status === 'active'; }) || features[0] || null;
        }
        return preferredFeature;
    }

    global.IntegratedWorkbenchSelection = {
        resolveIntegratedViewSource: resolveIntegratedViewSource,
        getPreferredIntegratedViewSource: getPreferredIntegratedViewSource,
        getIntegratedFeatureView: getIntegratedFeatureView,
        pickPreferredFeature: pickPreferredFeature,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
