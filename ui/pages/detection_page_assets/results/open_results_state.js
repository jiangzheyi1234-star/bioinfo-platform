(function(global) {
    'use strict';

    var DEFAULT_MAX_OPEN_RESULTS = 6;

    function sanitizeKey(value) {
        return String(value || '').trim();
    }

    function cloneEntities(entitiesByKey) {
        var next = {};
        Object.keys(entitiesByKey || {}).forEach(function(key) {
            next[key] = entitiesByKey[key];
        });
        return next;
    }

    function uniqueKeys(keys) {
        var seen = Object.create(null);
        var output = [];
        (keys || []).forEach(function(value) {
            var key = sanitizeKey(value);
            if (!key || seen[key]) {
                return;
            }
            seen[key] = true;
            output.push(key);
        });
        return output;
    }

    function normalizeState(input) {
        var raw = input || {};
        var entitiesByKey = cloneEntities(raw.entitiesByKey || {});
        var openKeys = uniqueKeys(raw.openKeys).filter(function(key) {
            return Object.prototype.hasOwnProperty.call(entitiesByKey, key);
        });
        var pinnedKeys = uniqueKeys(raw.pinnedKeys).filter(function(key) {
            return openKeys.indexOf(key) >= 0;
        });
        var activeKey = sanitizeKey(raw.activeKey);
        var normalizedMax = Number(raw.maxOpenResults);

        return {
            maxOpenResults: Number.isFinite(normalizedMax) && normalizedMax > 0
                ? Math.floor(normalizedMax)
                : DEFAULT_MAX_OPEN_RESULTS,
            entitiesByKey: entitiesByKey,
            openKeys: openKeys,
            pinnedKeys: pinnedKeys,
            activeKey: openKeys.indexOf(activeKey) >= 0 ? activeKey : (openKeys[openKeys.length - 1] || ''),
        };
    }

    function buildHistoryResultKey(baseFeatureId, executionId) {
        var featurePart = sanitizeKey(baseFeatureId) || 'unknown_feature';
        var executionPart = sanitizeKey(executionId) || 'unknown_execution';
        return featurePart + '::' + executionPart;
    }

    function removeKeysFromState(state, keysToRemove, preferredActiveKey) {
        var removalSet = Object.create(null);
        uniqueKeys(keysToRemove).forEach(function(key) {
            removalSet[key] = true;
        });

        var nextEntities = {};
        Object.keys(state.entitiesByKey || {}).forEach(function(key) {
            if (!removalSet[key]) {
                nextEntities[key] = state.entitiesByKey[key];
            }
        });

        var nextOpenKeys = state.openKeys.filter(function(key) {
            return !removalSet[key];
        });
        var nextPinnedKeys = state.pinnedKeys.filter(function(key) {
            return !removalSet[key];
        });
        var desiredActiveKey = sanitizeKey(preferredActiveKey);
        var nextActiveKey = nextOpenKeys.indexOf(desiredActiveKey) >= 0
            ? desiredActiveKey
            : (nextOpenKeys[nextOpenKeys.length - 1] || '');

        return normalizeState({
            maxOpenResults: state.maxOpenResults,
            entitiesByKey: nextEntities,
            openKeys: nextOpenKeys,
            pinnedKeys: nextPinnedKeys,
            activeKey: nextActiveKey,
        });
    }

    function collectTrimmedKeys(state, options) {
        var keepSet = Object.create(null);
        uniqueKeys(options && options.keepKeys).forEach(function(key) {
            keepSet[key] = true;
        });

        var maxOpenResults = Number(options && options.maxOpenResults);
        var allowedOpenResults = Number.isFinite(maxOpenResults) && maxOpenResults > 0
            ? Math.floor(maxOpenResults)
            : state.maxOpenResults;

        var unpinnedKeys = state.openKeys.filter(function(key) {
            return state.pinnedKeys.indexOf(key) === -1;
        });

        var removableCount = Math.max(0, unpinnedKeys.length - allowedOpenResults);
        if (!removableCount) {
            return [];
        }

        var removed = [];
        state.openKeys.forEach(function(key) {
            if (removed.length >= removableCount) {
                return;
            }
            if (state.pinnedKeys.indexOf(key) >= 0 || keepSet[key]) {
                return;
            }
            removed.push(key);
        });
        return removed;
    }

    function reduceIntegratedOpenResultsState(currentState, action) {
        var state = normalizeState(currentState);
        var type = sanitizeKey(action && action.type);
        var payload = action && action.payload ? action.payload : {};

        if (type === 'register_result') {
            var resultKey = sanitizeKey(payload.resultKey);
            if (!resultKey) {
                throw new Error('register_result requires resultKey');
            }

            var nextEntities = cloneEntities(state.entitiesByKey);
            nextEntities[resultKey] = payload.entity;

            var nextOpenKeys = state.openKeys.filter(function(key) {
                return key !== resultKey;
            });
            nextOpenKeys.push(resultKey);

            return normalizeState({
                maxOpenResults: state.maxOpenResults,
                entitiesByKey: nextEntities,
                openKeys: nextOpenKeys,
                pinnedKeys: state.pinnedKeys,
                activeKey: resultKey,
            });
        }

        if (type === 'set_active') {
            var activeKey = sanitizeKey(payload.resultKey);
            return normalizeState({
                maxOpenResults: state.maxOpenResults,
                entitiesByKey: state.entitiesByKey,
                openKeys: state.openKeys,
                pinnedKeys: state.pinnedKeys,
                activeKey: state.openKeys.indexOf(activeKey) >= 0 ? activeKey : state.activeKey,
            });
        }

        if (type === 'set_pinned') {
            var pinKey = sanitizeKey(payload.resultKey);
            if (state.openKeys.indexOf(pinKey) < 0) {
                return state;
            }
            var pinned = Boolean(payload.pinned);
            var nextPinnedKeys = state.pinnedKeys.filter(function(key) {
                return key !== pinKey;
            });
            if (pinned) {
                nextPinnedKeys.push(pinKey);
            }
            return normalizeState({
                maxOpenResults: state.maxOpenResults,
                entitiesByKey: state.entitiesByKey,
                openKeys: state.openKeys,
                pinnedKeys: nextPinnedKeys,
                activeKey: state.activeKey,
            });
        }

        if (type === 'close_result') {
            return removeKeysFromState(state, [payload.resultKey], payload.nextActiveKey);
        }

        if (type === 'clear_unpinned') {
            var keysToRemove = state.openKeys.filter(function(key) {
                return state.pinnedKeys.indexOf(key) < 0;
            });
            return removeKeysFromState(state, keysToRemove, payload.nextActiveKey);
        }

        if (type === 'trim_open_results') {
            var trimmedKeys = collectTrimmedKeys(state, payload);
            return removeKeysFromState(state, trimmedKeys, payload.keepActiveKey || state.activeKey);
        }

        if (type === 'reset') {
            return normalizeState({ maxOpenResults: state.maxOpenResults });
        }

        throw new Error('Unknown open results action: ' + type);
    }

    function createStore(initialState) {
        var currentState = normalizeState(initialState);

        function dispatch(type, payload) {
            currentState = reduceIntegratedOpenResultsState(currentState, {
                type: type,
                payload: payload || {},
            });
            return getState();
        }

        function getState() {
            return normalizeState(currentState);
        }

        return {
            getState: getState,
            reset: function() {
                return dispatch('reset');
            },
            registerResult: function(resultKey, entity) {
                return dispatch('register_result', { resultKey: resultKey, entity: entity });
            },
            setActive: function(resultKey) {
                return dispatch('set_active', { resultKey: resultKey });
            },
            setPinned: function(resultKey, pinned) {
                return dispatch('set_pinned', { resultKey: resultKey, pinned: pinned });
            },
            closeResult: function(resultKey, nextActiveKey) {
                return dispatch('close_result', { resultKey: resultKey, nextActiveKey: nextActiveKey });
            },
            clearUnpinned: function(nextActiveKey) {
                return dispatch('clear_unpinned', { nextActiveKey: nextActiveKey });
            },
            trimOpenResults: function(options) {
                return dispatch('trim_open_results', options || {});
            },
        };
    }

    var api = {
        DEFAULT_MAX_OPEN_RESULTS: DEFAULT_MAX_OPEN_RESULTS,
        buildHistoryResultKey: buildHistoryResultKey,
        normalizeState: normalizeState,
        reduceIntegratedOpenResultsState: reduceIntegratedOpenResultsState,
        createStore: createStore,
    };

    global.IntegratedOpenResultsState = api;

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
})(typeof globalThis !== 'undefined' ? globalThis : window);
