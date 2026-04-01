(function(global) {
    'use strict';

    var runtimeDependencies = null;
    var integratedChartInstances = [];
    var integratedChartResizeBound = false;

    function configureRuntime(dependencies) {
        runtimeDependencies = Object.assign({}, runtimeDependencies || {}, dependencies || {});
    }

    function getRuntime() {
        if (!runtimeDependencies) {
            throw new Error('IntegratedChartRenderer runtime is not configured');
        }
        return runtimeDependencies;
    }

    function disposeIntegratedCharts() {
        integratedChartInstances.forEach(function(instance) {
            try {
                instance.dispose();
            } catch (_) {
                // ignore
            }
        });
        integratedChartInstances = [];
    }

    function getDomainColor(name) {
        var text = String(name || '').toLowerCase();
        if (text.includes('virus') || text.includes('viruses')) return '#ef4444';
        if (text.includes('fungi') || text.includes('fungus')) return '#22c55e';
        if (text.includes('bacteria')) return '#3b82f6';
        if (text.includes('archaea')) return '#f59e0b';
        return '#64748b';
    }

    function getChartDomain(item) {
        var text = String(item && item.name || '').toLowerCase();
        if (text.includes('virus')) return 'Viruses';
        if (text.includes('fung')) return 'Fungi';
        if (text.includes('archaea')) return 'Archaea';
        return 'Bacteria';
    }

    function ensureEchartsLoaded() {
        var runtime = getRuntime();
        if (typeof echarts !== 'undefined') {
            return;
        }
        if (runtime.getEchartsLoadRequested()) {
            return;
        }
        runtime.setEchartsLoadRequested(true);

        var script = document.createElement('script');
        script.src = 'echarts.min.js';
        script.async = false;
        script.onload = function() {
            console.log('echarts dynamically loaded');
        };
        script.onerror = function() {
            console.error('Failed to load echarts.min.js');
            runtime.showNotice('Failed to load local chart engine: echarts.min.js', 'error', 5000);
        };
        document.head.appendChild(script);
    }

    function resizeIntegratedCharts() {
        integratedChartInstances.forEach(function(instance) {
            try {
                instance.resize();
            } catch (_) {
                // ignore
            }
        });
    }

    function renderIntegratedChart(chartInput, options, retryCount) {
        var runtime = getRuntime();
        var normalizedOptions = options || {};
        var normalizedRetryCount = Number(retryCount || 0);
        var card = document.getElementById('integrated-chart-card');
        var container = document.getElementById('integrated-chart-container');
        var titleEl = document.getElementById('chart-card-title');

        if (runtime.getIntegratedChartRetryTimer()) {
            clearTimeout(runtime.getIntegratedChartRetryTimer());
            runtime.setIntegratedChartRetryTimer(null);
        }

        disposeIntegratedCharts();

        var charts = runtime.getIntegratedCharts(chartInput);
        var validCharts = charts.filter(runtime.hasIntegratedChartData);
        if (!validCharts.length) {
            if (card) card.dataset.panelVisible = normalizedOptions.requiredMessage ? '1' : '0';
            runtime.setHidden(card, !normalizedOptions.requiredMessage);
            if (container) {
                container.innerHTML = '<div class="' + (normalizedOptions.requiredMessage ? 'task-error-banner' : 'integrated-input-empty') + '">' + runtime.escapeHtml(normalizedOptions.requiredMessage || '暂无图表数据。') + '</div>';
            }
            return;
        }

        if (card) card.dataset.panelVisible = '1';
        runtime.setHidden(card, false);
        if (titleEl) titleEl.textContent = validCharts.length > 1 ? '图表视图' : (validCharts[0].title || '图表');
        if (!container || typeof echarts === 'undefined') {
            if (container && typeof echarts === 'undefined') {
                ensureEchartsLoaded();
                if (normalizedRetryCount < 20) {
                    container.innerHTML = '<div class="integrated-input-empty">Loading chart engine...</div>';
                    runtime.setIntegratedChartRetryTimer(window.setTimeout(function() {
                        renderIntegratedChart(chartInput, normalizedOptions, normalizedRetryCount + 1);
                    }, 250));
                } else {
                    container.innerHTML = '<div class="integrated-input-empty">Chart engine unavailable (echarts not loaded).</div>';
                }
            }
            return;
        }

        container.innerHTML = '';

        validCharts.forEach(function(chartData, index) {
            var chartWrap = document.createElement('div');
            chartWrap.className = 'integrated-chart-item';
            var localTitle = document.createElement('div');
            localTitle.className = 'integrated-chart-item-title';
            localTitle.textContent = chartData.title || ('图表 ' + (index + 1));
            var chartDiv = document.createElement('div');
            chartDiv.className = 'integrated-chart-item-canvas';
            chartDiv.style.width = '100%';
            var dynamicHeight = (chartData.type === 'abundance_bar' || chartData.type === 'amplicon_performance')
                ? Math.min(Math.max(300, chartData.data.length * 22 + 90), 680) + 'px'
                : '360px';
            chartDiv.style.height = dynamicHeight;
            chartWrap.appendChild(localTitle);
            chartWrap.appendChild(chartDiv);
            container.appendChild(chartWrap);

            var instance = echarts.init(chartDiv);
            var chartType = chartData.type || 'pie';
            var option = {};

            if (chartType === 'funnel') {
                option = {
                    tooltip: {
                        trigger: 'item',
                        formatter: function(params) {
                            return params.name + '<br/>Reads: ' + Number(params.value || 0).toLocaleString();
                        }
                    },
                    series: [{
                        type: 'funnel',
                        left: '10%',
                        top: 20,
                        bottom: 20,
                        width: '80%',
                        minSize: '30%',
                        maxSize: '100%',
                        sort: 'descending',
                        gap: 4,
                        label: {
                            show: true,
                            position: 'inside',
                            formatter: function(params) {
                                return params.name + '\n' + Number(params.value || 0).toLocaleString();
                            }
                        },
                        itemStyle: {
                            borderColor: '#fff',
                            borderWidth: 1,
                        },
                        data: chartData.data.map(function(item, i) {
                            return {
                                name: item.name,
                                value: item.value,
                                itemStyle: { color: ['#0ea5e9', '#38bdf8', '#22c55e', '#f59e0b', '#ef4444'][i % 5] }
                            };
                        }),
                    }]
                };
            } else if (chartType === 'abundance_bar') {
                var sorted = chartData.data.slice().sort(function(a, b) { return (b.reads || 0) - (a.reads || 0); });
                var names = sorted.map(function(d) { return d.name; });
                var reads = sorted.map(function(d) { return d.reads || 0; });
                var colors = sorted.map(function(d) { return getDomainColor(getChartDomain(d)); });
                option = {
                    tooltip: {
                        trigger: 'axis',
                        axisPointer: { type: 'shadow' },
                        formatter: function(params) {
                            var p = params && params[0] ? params[0] : null;
                            if (!p) return '';
                            var row = sorted[p.dataIndex] || {};
                            var domain = getChartDomain(row);
                            return (row.name || '-') + '<br/>Reads: ' + (row.reads || 0).toLocaleString() + '<br/>Domain: ' + domain;
                        }
                    },
                    grid: { left: '28%', right: '8%', top: 20, bottom: 30 },
                    xAxis: { type: 'value', axisLabel: { fontSize: 10 } },
                    yAxis: {
                        type: 'category',
                        data: names,
                        inverse: true,
                        axisLabel: { fontSize: 10, width: 220, overflow: 'truncate' }
                    },
                    series: [{
                        type: 'bar',
                        data: reads.map(function(value, i) { return ({ value: value, itemStyle: { color: colors[i] } }); }),
                        barMaxWidth: 18,
                    }]
                };
            } else if (chartType === 'coverage_depth') {
                var seriesData = chartData.data.map(function(d) { return [d.position, d.depth]; });
                option = {
                    tooltip: {
                        trigger: 'axis',
                        formatter: function(params) {
                            var p = params && params[0] ? params[0] : null;
                            if (!p) return '';
                            return 'Position: ' + p.value[0] + '<br/>Depth: ' + Number(p.value[1]).toFixed(2);
                        }
                    },
                    grid: { left: '8%', right: '5%', top: 20, bottom: 40 },
                    xAxis: { type: 'value', name: 'Position', axisLabel: { fontSize: 10 } },
                    yAxis: { type: 'value', name: 'Depth', axisLabel: { fontSize: 10 } },
                    series: [{
                        type: 'line',
                        showSymbol: false,
                        smooth: true,
                        lineStyle: { width: 1.5, color: '#2563eb' },
                        areaStyle: { color: 'rgba(37,99,235,0.15)' },
                        data: seriesData,
                    }]
                };
            } else if (chartType === 'amplicon_performance') {
                var ampliconNames = chartData.data.map(function(d) { return d.name; });
                var ampliconReads = chartData.data.map(function(d) { return d.reads || 0; });
                var breadth = chartData.data.map(function(d) { return d.breadth || 0; });
                option = {
                    tooltip: {
                        trigger: 'axis',
                        axisPointer: { type: 'shadow' },
                        formatter: function(params) {
                            var p1 = params.find(function(p) { return p.seriesName === 'Mean Depth'; });
                            var p2 = params.find(function(p) { return p.seriesName === 'Breadth (%)'; });
                            return params[0].axisValue + '<br/>Mean Depth: ' + (p1 ? Number(p1.value).toFixed(2) : '-') + '<br/>Breadth: ' + (p2 ? Number(p2.value).toFixed(2) : '-') + '%';
                        }
                    },
                    legend: { top: 0, textStyle: { fontSize: 10 } },
                    grid: { left: '22%', right: '8%', top: 35, bottom: 30 },
                    xAxis: { type: 'value', axisLabel: { fontSize: 10 } },
                    yAxis: { type: 'category', data: ampliconNames, inverse: true, axisLabel: { fontSize: 10, width: 200, overflow: 'truncate' } },
                    series: [
                        {
                            name: 'Mean Depth',
                            type: 'bar',
                            data: ampliconReads,
                            barMaxWidth: 16,
                            itemStyle: { color: '#0ea5e9' }
                        },
                        {
                            name: 'Breadth (%)',
                            type: 'line',
                            xAxisIndex: 0,
                            yAxisIndex: 0,
                            data: breadth,
                            symbolSize: 4,
                            lineStyle: { color: '#f59e0b', width: 1.5 },
                            itemStyle: { color: '#f59e0b' }
                        }
                    ]
                };
            } else if (chartType === 'sunburst') {
                option = {
                    tooltip: {
                        trigger: 'item',
                        formatter: function(params) {
                            var value = params && params.value != null ? params.value + '%' : '-';
                            return params.name + '<br/>占比: ' + value;
                        }
                    },
                    series: [{
                        type: 'sunburst',
                        radius: [0, '92%'],
                        sort: null,
                        emphasis: { focus: 'ancestor' },
                        data: chartData.data,
                        minAngle: 2,
                        labelLayout: { hideOverlap: true },
                        label: {
                            rotate: 'tangential',
                            fontSize: 10,
                            overflow: 'truncate',
                            width: 96,
                            formatter: function(params) {
                                var value = Number((params == null ? void 0 : params.value) || 0);
                                var depth = Number((params == null ? void 0 : params.treePathInfo) && params.treePathInfo.length || 0);
                                if (depth >= 4 && value < 3) return '';
                                if (depth >= 3 && value < 1.2) return '';
                                return params.name || '';
                            }
                        },
                        levels: [{}, { r0: '0%', r: '28%', label: { rotate: 0, fontSize: 13 } }, { r0: '28%', r: '58%', label: { rotate: 'tangential', fontSize: 11 } }, { r0: '58%', r: '92%', label: { rotate: 'tangential', fontSize: 9 } }]
                    }]
                };
            } else if (chartType === 'bar') {
                if (Array.isArray(chartData.series) && Array.isArray(chartData.categories)) {
                    option = {
                        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
                        legend: { top: 0, textStyle: { fontSize: 10 } },
                        grid: { left: '8%', right: '5%', top: 36, bottom: 40 },
                        xAxis: { type: 'category', data: chartData.categories, axisLabel: { fontSize: 10, interval: 0 } },
                        yAxis: { type: 'value', axisLabel: { fontSize: 10 } },
                        series: chartData.series.map(function(series) {
                            return {
                                name: series.name || 'Series',
                                type: 'bar',
                                data: Array.isArray(series.data) ? series.data : [],
                                itemStyle: { color: series.color || '#3b82f6' },
                                barMaxWidth: 28,
                            };
                        }),
                    };
                } else {
                    var barNames = chartData.data.map(function(d) { return d.name; });
                    var values = chartData.data.map(function(d) { return d.value; });
                    var barColors = chartData.data.map(function(d) {
                        if (d.status === 'suboptimal') return '#f59e0b';
                        if (d.status === 'no_candidate') return '#ef4444';
                        return '#3b82f6';
                    });
                    option = {
                        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
                        grid: { left: '22%', right: '8%', top: 20, bottom: 30 },
                        xAxis: { type: 'value', name: 'bp', axisLabel: { fontSize: 10 } },
                        yAxis: { type: 'category', data: barNames, inverse: true, axisLabel: { fontSize: 10, width: 140, overflow: 'truncate' } },
                        series: [{
                            type: 'bar',
                            data: values.map(function(v, i) { return ({ value: v, itemStyle: { color: barColors[i] } }); }),
                            barMaxWidth: 18,
                            label: { show: true, position: 'right', formatter: '{c} bp', fontSize: 10, color: '#64748b' },
                        }]
                    };
                }
            } else {
                option = {
                    tooltip: {
                        trigger: 'item',
                        formatter: function(params) {
                            var readsLabel = params.data.reads != null ? params.data.reads.toLocaleString() : '-';
                            return params.name + '<br/>占比: ' + params.percent + '%<br/>Reads: ' + readsLabel;
                        }
                    },
                    series: [{
                        type: 'pie',
                        radius: ['30%', '65%'],
                        center: ['50%', '50%'],
                        data: chartData.data.map(function(d) { return ({ name: d.name, value: d.value, reads: d.reads || 0 }); }),
                        label: { formatter: '{b}\n{d}%', fontSize: 11 },
                        emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.2)' } }
                    }]
                };
            }

            instance.setOption(option);
            integratedChartInstances.push(instance);
        });

        if (!integratedChartResizeBound) {
            integratedChartResizeBound = true;
            var chartContainer = document.getElementById('integrated-chart-container');
            if (chartContainer && typeof ResizeObserver !== 'undefined') {
                var ro = new ResizeObserver(function() {
                    resizeIntegratedCharts();
                });
                ro.observe(chartContainer);
            }
            window.addEventListener('resize', resizeIntegratedCharts);
        }
    }

    global.IntegratedChartRenderer = {
        configureRuntime: configureRuntime,
        disposeIntegratedCharts: disposeIntegratedCharts,
        ensureEchartsLoaded: ensureEchartsLoaded,
        renderIntegratedChart: renderIntegratedChart,
        resizeIntegratedCharts: resizeIntegratedCharts,
    };
})(typeof globalThis !== 'undefined' ? globalThis : window);
