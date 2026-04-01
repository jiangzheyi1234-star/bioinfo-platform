(function(global) {
    'use strict';

    var runtimeDependencies = null;

    function configureRuntime(dependencies) {
        runtimeDependencies = Object.assign({}, runtimeDependencies || {}, dependencies || {});
    }

    function getRuntime() {
        if (!runtimeDependencies) {
            throw new Error('IntegratedWorkbenchStateManager runtime is not configured');
        }
        return runtimeDependencies;
    }

    function getIntegratedOpenResultsState() {
        return getRuntime().integratedOpenResultsStore.getState();
    }

    function syncIntegratedExecutionViewsFromState(snapshot) {
        var runtime = getRuntime();
        var normalizedSnapshot = snapshot || getIntegratedOpenResultsState();
        var integratedExecutionViews = runtime.integratedExecutionViews;
        Object.keys(integratedExecutionViews).forEach(function(featureId) {
            delete integratedExecutionViews[featureId];
        });
        Object.keys(normalizedSnapshot.entitiesByKey || {}).forEach(function(featureId) {
            integratedExecutionViews[featureId] = normalizedSnapshot.entitiesByKey[featureId];
        });
        return normalizedSnapshot;
    }

    function isIntegratedHistoryFeatureId(featureId) {
        return getIntegratedOpenResultsState().openKeys.includes(String(featureId || '').trim());
    }

    function isIntegratedPinnedFeatureId(featureId) {
        return getIntegratedOpenResultsState().pinnedKeys.includes(String(featureId || '').trim());
    }

    function syncIntegratedHistoryResultControls() {
        var runtime = getRuntime();
        var clearBtn = document.getElementById('integrated-clear-history-results');
        if (!clearBtn) {
            return;
        }
        var snapshot = getIntegratedOpenResultsState();
        runtime.setHidden(clearBtn, snapshot.openKeys.length === 0);
        clearBtn.disabled = snapshot.openKeys.length === 0 || snapshot.openKeys.every(function(key) {
            return snapshot.pinnedKeys.includes(key);
        });
    }

    function buildIntegratedHistoryResultKey(baseFeatureId, executionId) {
        return global.IntegratedOpenResultsState.buildHistoryResultKey(baseFeatureId, executionId);
    }

    function getIntegratedHistoryFeatureLabel(view, fallbackFeatureId) {
        var baseTitle = String(view && view.title || fallbackFeatureId || '结果').trim() || '结果';
        var sampleName = String(view && view.hero && (view.hero.sample_name || view.hero.sampleName) || '').trim();
        var executionId = String(view && ((view.provenance && view.provenance.execution_id) || (view.hero && view.hero.execution_id)) || '').trim();
        if (sampleName && executionId) {
            return baseTitle + ' · ' + sampleName + ' · ' + executionId.slice(0, 8);
        }
        if (sampleName) {
            return baseTitle + ' · ' + sampleName;
        }
        if (executionId) {
            return baseTitle + ' · ' + executionId.slice(0, 8);
        }
        return baseTitle;
    }

    function rememberIntegratedExecutionView(resultKey, view) {
        var runtime = getRuntime();
        return syncIntegratedExecutionViewsFromState(
            runtime.integratedOpenResultsStore.registerResult(resultKey, Object.assign({}, view, {
                __displaySource: 'history',
            }))
        );
    }

    function setIntegratedHistoryResultPinned(resultKey, pinned) {
        return syncIntegratedExecutionViewsFromState(
            getRuntime().integratedOpenResultsStore.setPinned(resultKey, pinned)
        );
    }

    function setIntegratedHistoryResultActive(resultKey) {
        return syncIntegratedExecutionViewsFromState(
            getRuntime().integratedOpenResultsStore.setActive(resultKey)
        );
    }

    function closeIntegratedHistoryResultState(resultKey, nextActiveKey) {
        return syncIntegratedExecutionViewsFromState(
            getRuntime().integratedOpenResultsStore.closeResult(resultKey, nextActiveKey || '')
        );
    }

    function clearUnpinnedIntegratedHistoryResultState(nextActiveKey) {
        return syncIntegratedExecutionViewsFromState(
            getRuntime().integratedOpenResultsStore.clearUnpinned(nextActiveKey || '')
        );
    }

    function clearIntegratedExecutionCache() {
        var runtime = getRuntime();
        syncIntegratedExecutionViewsFromState(runtime.integratedOpenResultsStore.reset());
        runtime.setPendingIntegratedFeatureId(null);
        runtime.setPendingIntegratedViewSource('');
        runtime.setSelectedIntegratedViewSource('workflow');
        syncIntegratedHistoryResultControls();
    }

    function syncIntegratedWorkbenchProjectScope(nextWorkbench) {
        var runtime = getRuntime();
        var nextProjectId = String(nextWorkbench && nextWorkbench.project_id || '').trim();
        if (runtime.getActiveIntegratedProjectId() && nextProjectId !== runtime.getActiveIntegratedProjectId()) {
            clearIntegratedExecutionCache();
        }
        runtime.setActiveIntegratedProjectId(nextProjectId);
    }

    function ensureIntegratedWorkbenchViews() {
        var runtime = getRuntime();
        var integratedWorkbench = runtime.getIntegratedWorkbench();
        if (!integratedWorkbench) {
            integratedWorkbench = { views: {}, features: [] };
            runtime.setIntegratedWorkbench(integratedWorkbench);
        }
        if (!integratedWorkbench.views) {
            integratedWorkbench.views = {};
        }
        if (!integratedWorkbench.features) {
            integratedWorkbench.features = [];
        }
        return integratedWorkbench.views;
    }

    function getIntegratedWorkbenchFeature(featureId) {
        var runtime = getRuntime();
        ensureIntegratedWorkbenchViews();
        return ((runtime.getIntegratedWorkbench().features || []).find(function(feature) {
            return feature && feature.id === featureId;
        })) || null;
    }

    function removeIntegratedWorkbenchFeature(featureId) {
        var runtime = getRuntime();
        var integratedWorkbench = runtime.getIntegratedWorkbench();
        if (!integratedWorkbench) {
            return;
        }
        ensureIntegratedWorkbenchViews();
        integratedWorkbench.features = (integratedWorkbench.features || []).filter(function(feature) {
            return feature && feature.id !== featureId;
        });
        if (integratedWorkbench.views && Object.prototype.hasOwnProperty.call(integratedWorkbench.views, featureId)) {
            delete integratedWorkbench.views[featureId];
        }
    }

    function restoreIntegratedExecutionFeatures() {
        var runtime = getRuntime();
        if (!runtime.getIntegratedWorkbench()) {
            return;
        }
        Object.keys(getIntegratedOpenResultsState().entitiesByKey || {}).forEach(function(featureId) {
            var view = runtime.integratedExecutionViews[featureId];
            if (!view || getIntegratedWorkbenchFeature(featureId)) {
                return;
            }
            upsertIntegratedHistoryFeature(featureId, view, { temporary: true });
        });
        syncIntegratedHistoryResultControls();
    }

    function closeIntegratedHistoryFeature(featureId, options) {
        var runtime = getRuntime();
        var normalizedId = String(featureId || '').trim();
        var normalizedOptions = options || {};
        if (!normalizedId || !isIntegratedHistoryFeatureId(normalizedId)) {
            return;
        }

        var nextSnapshot = closeIntegratedHistoryResultState(normalizedId, normalizedOptions.nextActiveKey || '');
        removeIntegratedWorkbenchFeature(normalizedId);
        if (runtime.getPendingIntegratedFeatureId() === normalizedId) {
            runtime.setPendingIntegratedFeatureId(nextSnapshot.activeKey || '');
            runtime.setPendingIntegratedViewSource(nextSnapshot.activeKey ? 'history' : '');
        }
        if (runtime.getSelectedIntegratedFeatureId() === normalizedId) {
            runtime.setSelectedIntegratedFeatureId(nextSnapshot.activeKey || null);
            runtime.setSelectedIntegratedViewSource(nextSnapshot.activeKey ? 'history' : 'workflow');
        }
        runtime.renderIntegratedWorkbench();
    }

    function clearIntegratedTemporaryFeatures(options) {
        var runtime = getRuntime();
        ensureIntegratedWorkbenchViews();
        var normalizedOptions = typeof options === 'string'
            ? { exceptFeatureId: options }
            : (options || {});
        var preservedId = String(normalizedOptions.exceptFeatureId || '').trim();
        var snapshot = normalizedOptions.clearAllUnpinned
            ? clearUnpinnedIntegratedHistoryResultState(preservedId)
            : syncIntegratedExecutionViewsFromState(
                runtime.integratedOpenResultsStore.trimOpenResults({
                    maxOpenResults: Number(normalizedOptions.maxCount) || runtime.integratedHistoryResultLimit,
                    keepKeys: preservedId ? [preservedId] : [],
                    keepActiveKey: preservedId || getIntegratedOpenResultsState().activeKey,
                })
            );
        var preservedKeys = new Set(snapshot.openKeys || []);
        var integratedWorkbench = runtime.getIntegratedWorkbench();
        integratedWorkbench.features = (integratedWorkbench.features || []).filter(function(feature) {
            if (!feature || !feature.temporary) {
                return true;
            }
            return preservedKeys.has(feature.id);
        });
        if (!preservedKeys.has(String(runtime.getSelectedIntegratedFeatureId() || '').trim())) {
            runtime.setSelectedIntegratedFeatureId(snapshot.activeKey || null);
            runtime.setSelectedIntegratedViewSource(snapshot.activeKey ? 'history' : runtime.getSelectedIntegratedViewSource());
        }
        syncIntegratedHistoryResultControls();
    }

    function upsertIntegratedHistoryFeature(featureId, view, options) {
        var runtime = getRuntime();
        var normalizedOptions = options || {};
        if (!featureId) {
            return false;
        }
        ensureIntegratedWorkbenchViews();
        var integratedWorkbench = runtime.getIntegratedWorkbench();
        var temporary = Boolean(normalizedOptions.temporary);
        var existingIndex = (integratedWorkbench.features || []).findIndex(function(feature) {
            return feature && feature.id === featureId;
        });

        if (temporary) {
            clearIntegratedTemporaryFeatures({ exceptFeatureId: featureId, maxCount: runtime.integratedHistoryResultLimit });
        }

        if (existingIndex >= 0) {
            var current = integratedWorkbench.features[existingIndex] || {};
            integratedWorkbench.features[existingIndex] = Object.assign({}, current, {
                id: featureId,
                name: temporary ? getIntegratedHistoryFeatureLabel(view, featureId) : String(current.name || view && view.title || featureId),
                description: String(current.description || view && view.description || ''),
                status: current.status || 'active',
                temporary: Boolean(current.temporary) || temporary,
            });
            return false;
        }

        integratedWorkbench.features.push({
            id: featureId,
            name: temporary ? getIntegratedHistoryFeatureLabel(view, featureId) : String(view && view.title || featureId),
            badge: '',
            description: String(view && view.description || ''),
            status: 'active',
            temporary: temporary,
        });
        return true;
    }

    function applyIntegratedHistoryPayload(payload, resolvedExecutionId, resolvedContext) {
        var runtime = getRuntime();
        var errorMessage = resolvedContext.errorMessage || '任务结果读取失败';
        ensureIntegratedWorkbenchViews();
        var baseFeatureId = String(
            resolvedContext.featureId
            || payload.view.feature_id
            || payload.view.view_id
            || payload.view.tool_id
            || ''
        ).trim();
        if (!baseFeatureId) {
            runtime.showNotice(payload.message || errorMessage);
            return false;
        }
        var featureId = buildIntegratedHistoryResultKey(baseFeatureId, resolvedExecutionId);
        rememberIntegratedExecutionView(featureId, payload.view);
        runtime.setPendingIntegratedFeatureId(featureId);
        runtime.setPendingIntegratedViewSource('history');
        var existingFeature = getIntegratedWorkbenchFeature(featureId);
        var featureChanged = upsertIntegratedHistoryFeature(
            featureId,
            payload.view,
            { temporary: !existingFeature || Boolean(existingFeature && existingFeature.temporary) }
        );
        runtime.switchTab('integrated');
        if (featureChanged) {
            runtime.renderIntegratedWorkbench();
        } else {
            runtime.selectIntegratedFeature(featureId, { sourceMode: 'history' });
        }
        return true;
    }

    global.IntegratedWorkbenchStateManager = {
        configureRuntime: configureRuntime,
        getIntegratedOpenResultsState: getIntegratedOpenResultsState,
        syncIntegratedExecutionViewsFromState: syncIntegratedExecutionViewsFromState,
        isIntegratedHistoryFeatureId: isIntegratedHistoryFeatureId,
        isIntegratedPinnedFeatureId: isIntegratedPinnedFeatureId,
        syncIntegratedHistoryResultControls: syncIntegratedHistoryResultControls,
        buildIntegratedHistoryResultKey: buildIntegratedHistoryResultKey,
        rememberIntegratedExecutionView: rememberIntegratedExecutionView,
        setIntegratedHistoryResultPinned: setIntegratedHistoryResultPinned,
        setIntegratedHistoryResultActive: setIntegratedHistoryResultActive,
        closeIntegratedHistoryResultState: closeIntegratedHistoryResultState,
        clearUnpinnedIntegratedHistoryResultState: clearUnpinnedIntegratedHistoryResultState,
        clearIntegratedExecutionCache: clearIntegratedExecutionCache,
        syncIntegratedWorkbenchProjectScope: syncIntegratedWorkbenchProjectScope,
        restoreIntegratedExecutionFeatures: restoreIntegratedExecutionFeatures,
        ensureIntegratedWorkbenchViews: ensureIntegratedWorkbenchViews,
        getIntegratedWorkbenchFeature: getIntegratedWorkbenchFeature,
        removeIntegratedWorkbenchFeature: removeIntegratedWorkbenchFeature,
        closeIntegratedHistoryFeature: closeIntegratedHistoryFeature,
        clearIntegratedTemporaryFeatures: clearIntegratedTemporaryFeatures,
        upsertIntegratedHistoryFeature: upsertIntegratedHistoryFeature,
        applyIntegratedHistoryPayload: applyIntegratedHistoryPayload,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
