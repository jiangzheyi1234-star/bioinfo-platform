(function(global) {
    'use strict';

    function asArray(value) {
        return Array.isArray(value) ? value : [];
    }

    function nonEmptyString(value) {
        return String(value || '').trim();
    }

    function hasChartData(input) {
        const chartPayload = Array.isArray(input) ? input : (input ? [input] : []);
        return chartPayload.some(function(chart) {
            if (!chart || typeof chart !== 'object') {
                return false;
            }
            if (Array.isArray(chart.series) && chart.series.length > 0) {
                return true;
            }
            if (chart.option && Array.isArray(chart.option.series) && chart.option.series.length > 0) {
                return true;
            }
            return false;
        });
    }

    function hasTableData(view) {
        var table = view && view.table && typeof view.table === 'object' ? view.table : {};
        var columns = asArray(table.columns).length > 0 || asArray(view && view.columns).length > 0;
        var rows = asArray(table.rows).length > 0 || asArray(view && view.rows).length > 0;
        return columns && rows;
    }

    function hasArtifacts(view) {
        return asArray(view && view.artifacts).some(function(item) {
            return item && item.available && (item.local_path || item.remote_path);
        });
    }

    function hasSections(view) {
        return asArray(view && view.sections).length > 0;
    }

    function hasHtmlArtifact(view) {
        return asArray(view && view.artifacts).some(function(item) {
            if (!item || !item.available || !item.local_path) {
                return false;
            }
            var hint = nonEmptyString(item.viewer_hint);
            var name = nonEmptyString(item.name).toLowerCase();
            return hint === 'html' || name.endsWith('.html');
        });
    }

    var registry = {
        annotation_table: {
            label: '注释结果',
            mode: 'table-first',
            requiredViewers: ['table', 'files'],
            highlights: ['summary', 'table', 'files', 'provenance'],
            tone: 'info'
        },
        quality_assessment: {
            label: '质量评估',
            mode: 'table-first',
            requiredViewers: ['table'],
            highlights: ['summary', 'table', 'provenance'],
            tone: 'success'
        },
        html_report: {
            label: '交互报告',
            mode: 'html-first',
            requiredViewers: ['html'],
            highlights: ['summary', 'html', 'files', 'provenance'],
            tone: 'accent'
        },
        artifact_collection: {
            label: '结果产物',
            mode: 'files-first',
            requiredViewers: ['files'],
            highlights: ['summary', 'files', 'provenance'],
            tone: 'warning'
        },
        qc_report: {
            label: '质量控制',
            mode: 'chart-first',
            requiredViewers: ['chart', 'files'],
            highlights: ['summary', 'chart', 'table', 'files', 'provenance'],
            tone: 'success'
        },
        taxonomy_profile: {
            label: '分类结果',
            mode: 'chart-first',
            requiredViewers: ['chart', 'table', 'files'],
            highlights: ['summary', 'chart', 'table', 'files', 'provenance'],
            tone: 'info'
        },
        workflow_product: {
            label: '工作流结果',
            mode: 'sections-first',
            requiredViewers: ['sections'],
            highlights: ['summary', 'sections', 'files', 'provenance'],
            tone: 'accent'
        },
        fallback: {
            label: '统一结果',
            mode: 'table-first',
            requiredViewers: [],
            highlights: ['summary', 'table', 'files', 'provenance'],
            tone: 'default'
        }
    };

    function getRegistration(archetype) {
        var key = nonEmptyString(archetype);
        return registry[key] || registry.fallback;
    }

    function getAvailability(view) {
        return {
            chart: hasChartData(view && (view.charts || view.chart)),
            table: hasTableData(view),
            files: hasArtifacts(view),
            sections: hasSections(view),
            html: hasHtmlArtifact(view)
        };
    }

    function validateView(view) {
        var archetype = nonEmptyString(view && view.archetype);
        var registration = getRegistration(archetype);
        var availability = getAvailability(view);
        var issues = [];

        if (!nonEmptyString(archetype)) {
            issues.push('Result view 缺少 archetype。');
        }
        if (!nonEmptyString(view && view.title)) {
            issues.push('Result view 缺少 title。');
        }
        if (!view || typeof view !== 'object') {
            issues.push('Result view 不是对象。');
        }

        registration.requiredViewers.forEach(function(viewerName) {
            if (availability[viewerName]) {
                return;
            }
            issues.push(
                '结果契约缺失：archetype='
                + (archetype || 'unknown')
                + ' 需要 viewer='
                + viewerName
                + '，但结果数据未提供对应内容。'
            );
        });

        return {
            archetype: archetype || 'fallback',
            registration: registration,
            availability: availability,
            issues: issues,
            ok: issues.length === 0
        };
    }

    function buildViewModel(view, options) {
        var validation = validateView(view || {});
        var registration = validation.registration;
        var hero = view && typeof view.hero === 'object' ? view.hero : {};
        var provenance = view && typeof view.provenance === 'object' ? view.provenance : {};
        var primaryViewer = registration.mode.replace('-first', '');
        var sourceMode = nonEmptyString(options && options.sourceMode) || 'workflow';

        return {
            sourceMode: sourceMode,
            validation: validation,
            strategy: {
                archetype: validation.archetype,
                mode: registration.mode,
                primaryViewer: primaryViewer,
                requiredViewers: registration.requiredViewers.slice()
            },
            title: nonEmptyString(view && view.title) || '统一结果',
            description: nonEmptyString(view && view.description),
            label: registration.label,
            tone: registration.tone,
            summary: asArray(view && view.summary),
            charts: asArray(view && view.charts).length ? asArray(view && view.charts) : (view && view.chart ? [view.chart] : []),
            sections: asArray(view && view.sections),
            artifacts: asArray(view && view.artifacts),
            table: view && typeof view.table === 'object'
                ? view.table
                : {
                    title: nonEmptyString(view && view.table_title),
                    subtitle: nonEmptyString(view && view.table_subtitle),
                    columns: asArray(view && view.columns),
                    rows: asArray(view && view.rows)
                },
            hero: {
                sampleName: nonEmptyString(hero.sample_name),
                executionId: nonEmptyString(hero.execution_id) || nonEmptyString(provenance.execution_id),
                updatedAt: nonEmptyString(hero.updated_at),
                primaryAction: nonEmptyString(hero.primary_action) || 'view_result'
            },
            provenance: provenance,
            status: view && typeof view.status === 'object' ? view.status : {}
        };
    }

    global.ResultShellRegistry = {
        registry: registry,
        getRegistration: getRegistration,
        getAvailability: getAvailability,
        validateView: validateView,
        buildViewModel: buildViewModel
    };
})(window);
