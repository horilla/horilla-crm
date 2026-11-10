var EChartsConfig = {

    // Default colors palette
    defaultColors: [
        '#a5b4fc', '#fca5a5', '#fdba74', '#38bdf8', '#a7f3d0',
        '#c084fc', '#fb7185', '#60a5fa', '#5eead4', '#22d3ee',
        '#f8b4cb', '#b4d8ff', '#c7d2fe', '#fde68a',
        '#d1d5db', '#e879f9', '#94a3b8', '#fcd34d',
        '#86efac', '#f472b6', '#818cf8', '#fb923c',
        '#a78bfa', '#4ade80', '#f59e0b', '#ec4899', '#06b6d4'
    ],

    /** Escape a value for safe use inside ECharts HTML tooltips */
    escapeHtml: function(value) {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },

    isDarkMode: function() {
        return document.body.classList.contains('dark');
    },

    getTextColor: function() {
        return this.isDarkMode() ? '#e5e7eb' : '#374151';
    },

    getAxisLineColor: function() {
        return this.isDarkMode() ? '#4b5563' : '#d1d5db';
    },

    getSplitLineColor: function() {
        return this.isDarkMode() ? '#374151' : '#e5e7eb';
    },

    /** Shared: pie/donut data nodes from labels + data + urls */
    _mapPieData: function(labels, data, urls) {
        return labels.map(function(label, index) {
            return {
                name: label,
                value: data[index] || 0,
                url: urls && urls[index] ? urls[index] : null
            };
        });
    },

    /** Shared: tooltip / click URL check */
    _dataHasUrl: function(d) {
        return d && d.url && d.url !== '#';
    },

    /** Radar: index of the data point (axis) the pointer is on, or -1 if it is not on a point */
    _radarHoveredIndex: function(vals, indicator) {
        try {
            var ev = EChartsConfig._lastPointer;
            if (!ev || typeof echarts === 'undefined') return -1;
            var dom = ev.target && ev.target.closest ? ev.target.closest('[_echarts_instance_]') : null;
            var inst = dom && echarts.getInstanceByDom(dom);
            var cs = inst && inst.getModel().getComponent('radar', 0).coordinateSystem;
            if (!cs) return -1;
            var rect = dom.getBoundingClientRect();
            var mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
            var n = indicator.length, best = -1, bestD = 18;
            for (var i = 0; i < n; i++) {
                var max = Number(indicator[i].max) || 1;
                var rr = cs.r * Math.min(1, (Number(vals[i]) || 0) / max);
                var ang = Math.PI / 2 + i * 2 * Math.PI / n;
                var px = cs.cx + rr * Math.cos(ang), py = cs.cy - rr * Math.sin(ang);
                var d = Math.sqrt((px - mx) * (px - mx) + (py - my) * (py - my));
                if (d < bestD) { bestD = d; best = i; }
            }
            return best;
        } catch (e) { return -1; }
    },

    /** Radar tooltip body: only the hovered point's count (falls back to all counts) */
    _radarTooltipHtml: function(title, vals, indicator) {
        var lines = ['<strong>' + EChartsConfig.escapeHtml(title) + '</strong>'];
        var idx = EChartsConfig._radarHoveredIndex(vals, indicator);
        var from = idx >= 0 ? idx : 0, to = idx >= 0 ? idx + 1 : Math.min(vals.length, indicator.length);
        for (var i = from; i < to; i++) {
            lines.push(EChartsConfig.escapeHtml(indicator[i].name) + ': <strong>' + EChartsConfig.escapeHtml(vals[i]) + '</strong>');
        }
        return lines.join('<br/>');
    },

    /** Shared: item tooltip for column/bar (hovered bar only, like donut) */
    _barColumnTooltipFormatter: function(urls) {
        var self = this;
        return function(params) {
            var hasUrl = (urls && urls.length > 0) || self._dataHasUrl(params.data);
            return params.marker + ' ' + EChartsConfig.escapeHtml(params.seriesName) + ': ' + EChartsConfig.escapeHtml(params.value) +
                (hasUrl ? '<br/><i style="color: #999; font-size: 11px;">Click to view details</i>' : '');
        };
    },

    /** Shared: line/area axis tooltip formatter */
    _lineAreaTooltipFormatter: function() {
        return function(params) {
            if (!params || !params.length) return '';
            var tooltip = '<strong>' + EChartsConfig.escapeHtml(params[0].axisValue) + '</strong><br/>';
            for (var i = 0; i < params.length; i++) {
                var param = params[i];
                var v = param.data && typeof param.data === 'object' && param.data.value !== undefined
                    ? param.data.value
                    : param.value;
                var hasUrl = param.data && param.data.url && param.data.url !== '#';
                tooltip += param.marker + ' ' + EChartsConfig.escapeHtml(param.seriesName) + ': ' + EChartsConfig.escapeHtml(v);
                if (hasUrl) {
                    tooltip += '<br/><i style="color: #999; font-size: 11px;">Click to view details</i>';
                }
                tooltip += '<br/>';
            }
            return tooltip;
        };
    },

    /** Shared: heatmap + radar legend selected merge */
    _mergeDualLegendSelected: function(catIds, serIds, sel) {
        var s = {};
        var i;
        for (i = 0; i < catIds.length; i++) s[catIds[i]] = true;
        for (i = 0; i < serIds.length; i++) s[serIds[i]] = true;
        if (sel) {
            for (var k in sel) {
                if (k.indexOf('__g_') === 0 || k.indexOf('__s_') === 0) {
                    s[k] = sel[k];
                }
            }
        }
        return s;
    },

    getChartBorderColor: function() {
        return this.isDarkMode() ? '#374151' : '#fff';
    },

    commonStyles: {
        fontFamily: "'Inter', sans-serif",
        fontSize: 12,
        legendFontSize: 12,
        axisFontSize: 11
    },

    getChartOption: function(config) {
        const { type, labels, data, colors, labelField, stackedData, hasMultipleGroups, urls } = config;
        const chartColors = this.defaultColors;

        this._currentUrls = urls || [];

        switch (type.toLowerCase()) {
            case 'pie':
                return this.getPieChartOption(labels, data, chartColors, labelField, urls);
            case 'donut':
                return this.getDonutChartOption(labels, data, chartColors, labelField, urls);
            case 'bar':
                return this.getBarChartOption(labels, data, chartColors, labelField, urls);
            case 'column':
                return this.getColumnChartOption(labels, data, chartColors, labelField, urls);
            case 'line':
                return this.getLineChartOption(labels, data, chartColors, labelField, urls);
            case 'funnel':
                return this.getFunnelChartOption(labels, data, chartColors, labelField, urls);
            case 'scatter':
                return this.getScatterChartOption(labels, data, chartColors, labelField, urls);
            case 'treemap':
                return this.getTreemapChartOption(labels, data, chartColors, labelField, urls);
            case 'area':
                return this.getAreaChartOption(labels, data, chartColors, labelField, urls);
            case 'stacked_vertical':
                return hasMultipleGroups ?
                    this.getStackedVerticalChartOption(stackedData, chartColors, labelField, urls) :
                    this.getColumnChartOption(labels, data, chartColors, labelField, urls);
            case 'stacked_horizontal':
                return hasMultipleGroups ?
                    this.getStackedHorizontalChartOption(stackedData, chartColors, labelField, urls) :
                    this.getBarChartOption(labels, data, chartColors, labelField, urls);
            case 'heatmap':
                return hasMultipleGroups && stackedData && stackedData.series && stackedData.series.length > 0 ?
                    this.getHeatmapChartOption(stackedData, chartColors, labelField, urls) :
                    this.getColumnChartOption(labels, data, chartColors, labelField, urls);
            case 'sankey':
                return hasMultipleGroups && stackedData && stackedData.series && stackedData.series.length > 0 ?
                    this.getSankeyChartOption(stackedData, chartColors, labelField, urls) :
                    this.getColumnChartOption(labels, data, chartColors, labelField, urls);
            case 'radar':
                if (hasMultipleGroups && stackedData && stackedData.categories && stackedData.series && stackedData.series.length > 0) {
                    return this.getRadarChartOptionFromStacked(stackedData, chartColors, labelField, urls);
                }
                return this.getRadarChartOption(labels, data, chartColors, labelField, urls);
            default:
                return this.getPieChartOption(labels, data, chartColors, labelField, urls);
        }
    },

    getLegendConfig: function(position = 'bottom') {
        return {
            show: true,
            type: 'scroll',
            orient: position === 'bottom' ? 'horizontal' : 'vertical',
            bottom: position === 'bottom' ? '0%' : undefined,
            left: position === 'bottom' ? 'center' : '0%',
            top: position === 'left' ? 'center' : undefined,
            itemWidth: 12,
            itemHeight: 12,
            textStyle: {
                fontSize: this.commonStyles.legendFontSize,
                fontFamily: this.commonStyles.fontFamily,
                color: this.getTextColor()
            }
        };
    },

    getGridConfig: function() {
        return {
            left: '3%',
            right: '4%',
            bottom: '22%',
            top: '10%',
            containLabel: true
        };
    },

    getAxisLabelStyle: function() {
        return {
            fontSize: this.commonStyles.axisFontSize,
            fontFamily: this.commonStyles.fontFamily,
            color: this.getTextColor()
        };
    },

    getAxisLineStyle: function() {
        return {
            lineStyle: {
                color: this.getAxisLineColor()
            }
        };
    },

    getSplitLineStyle: function() {
        return {
            show: true,
            lineStyle: {
                type: 'dashed',
                color: this.getSplitLineColor()
            }
        };
    },

    // Pie Chart Configuration
    getPieChartOption: function(labels, data, colors, labelField, urls) {
        var pieData = this._mapPieData(labels, data, urls);
        var self = this;

        return {
            ...this.getAnimationConfig(),
            tooltip: {
                trigger: 'item',
                formatter: function(params) {
                    var hasUrl = self._dataHasUrl(params.data);
                    return EChartsConfig.escapeHtml(params.seriesName) + '<br/>' + EChartsConfig.escapeHtml(params.name) + ': ' + EChartsConfig.escapeHtml(params.value) + ' (' + params.percent + '%)' +
                        (hasUrl ? '<br/><i>Click to view details</i>' : '');
                }
            },
            legend: this.getLegendConfig(),
            color: colors,
            series: [{
                name: labelField,
                type: 'pie',
                radius: '65%',
                center: ['50%', '45%'],
                avoidLabelOverlap: false,
                itemStyle: {
                    borderRadius: 4,
                    borderColor: this.getChartBorderColor(),
                    borderWidth: 2
                },
                label: {
                    show: false
                },
                emphasis: {
                    label: {
                        show: true,
                        fontSize: 14,
                        fontWeight: 'bold',
                        color: this.getTextColor()
                    },
                    itemStyle: {
                        shadowBlur: 10,
                        shadowOffsetX: 0,
                        shadowColor: 'rgba(0, 0, 0, 0.5)'
                    }
                },
                labelLine: {
                    show: false
                },
                data: pieData
            }]
        };
    },

    // Donut Chart Configuration
    getDonutChartOption: function(labels, data, colors, labelField, urls) {
        var pieData = this._mapPieData(labels, data, urls);
        var self = this;
        var total = (data || []).reduce(function(sum, v) { return sum + (Number(v) || 0); }, 0);

        return {
            ...this.getAnimationConfig(),
            tooltip: {
                trigger: 'item',
                formatter: function(params) {
                    var hasUrl = self._dataHasUrl(params.data);
                    return EChartsConfig.escapeHtml(params.seriesName) + '<br/>' + EChartsConfig.escapeHtml(params.name) + ': ' + EChartsConfig.escapeHtml(params.value) + ' (' + params.percent + '%)' +
                        (hasUrl ? '<br/><i style="color: #999; font-size: 11px;">Click to view details</i>' : '');
                }
            },
            legend: Object.assign({}, this.getLegendConfig(), { data: pieData.map(function(d) { return d.name; }) }),
            color: colors,
            series: [{
                name: labelField,
                type: 'pie',
                radius: ['40%', '70%'],
                center: ['50%', '45%'],
                avoidLabelOverlap: false,
                itemStyle: {
                    borderRadius: 6,
                    borderColor: this.getChartBorderColor(),
                    borderWidth: 2
                },
                label: {
                    show: false
                },
                emphasis: {
                    label: {
                        show: true,
                        fontSize: 14,
                        fontWeight: 'bold',
                        color: this.getTextColor()
                    },
                    itemStyle: {
                        shadowBlur: 10,
                        shadowOffsetX: 0,
                        shadowColor: 'rgba(0, 0, 0, 0.5)'
                    }
                },
                labelLine: {
                    show: false
                },
                data: pieData
            }, {
                // Invisible pie whose centered label shows the total inside the donut hole
                type: 'pie',
                radius: ['0%', '40%'],
                center: ['50%', '45%'],
                silent: true,
                tooltip: { show: false },
                legendHoverLink: false,
                itemStyle: { color: 'transparent' },
                labelLine: { show: false },
                label: {
                    show: true,
                    position: 'center',
                    formatter: '{label|Total}\n{value|' + total + '}',
                    rich: {
                        label: { fontSize: 14, color: '#8a8f98', lineHeight: 22, align: 'center' },
                        value: { fontSize: 28, fontWeight: 'bold', color: this.getTextColor(), lineHeight: 36, align: 'center' }
                    }
                },
                data: [{ value: 1, name: '' }]
            }]
        };
    },

    // Column Chart Configuration
    getColumnChartOption: function(labels, data, colors, labelField, urls) {
        const series = labels.map((label, index) => ({
            name: label,
            type: 'bar',
            data: [data[index] || 0],
            itemStyle: {
                color: colors[index % colors.length],
                borderRadius: [4, 4, 0, 0]
            },
            emphasis: {
                itemStyle: {
                    shadowBlur: 10,
                    shadowOffsetX: 0,
                    shadowColor: 'rgba(0, 0, 0, 0.5)'
                }
            }
        }));

        return {
            ...this.getAnimationConfig(),
            tooltip: {
                trigger: 'item',
                formatter: this._barColumnTooltipFormatter(urls)
            },
            legend: {
                ...this.getLegendConfig(),
                show: true,
                type: 'scroll'
            },
            grid: this.getGridConfig(),
            xAxis: {
                type: 'category',
                data: [labelField],
                axisLabel: this.getAxisLabelStyle(),
                axisLine: this.getAxisLineStyle()
            },
            yAxis: {
                type: 'value',
                axisLabel: this.getAxisLabelStyle(),
                axisLine: this.getAxisLineStyle(),
                splitLine: this.getSplitLineStyle()
            },
            color: colors,
            series: series
        };
    },

    // Bar Chart Configuration
    getBarChartOption: function(labels, data, colors, labelField, urls) {
        const series = labels.map((label, index) => ({
            name: label,
            type: 'bar',
            data: [data[index] || 0],
            itemStyle: {
                color: colors[index % colors.length],
                borderRadius: [0, 4, 4, 0]
            },
            emphasis: {
                itemStyle: {
                    shadowBlur: 10,
                    shadowOffsetX: 0,
                    shadowColor: 'rgba(0, 0, 0, 0.5)'
                }
            }
        }));

        return {
            ...this.getAnimationConfig(),
            tooltip: {
                trigger: 'item',
                formatter: this._barColumnTooltipFormatter(urls)
            },
            legend: {
                ...this.getLegendConfig(),
                show: true,
                type: 'scroll'
            },
            grid: this.getGridConfig(),
            xAxis: {
                type: 'value',
                axisLabel: this.getAxisLabelStyle(),
                axisLine: this.getAxisLineStyle(),
                splitLine: this.getSplitLineStyle()
            },
            yAxis: {
                type: 'category',
                data: [labelField],
                axisLabel: this.getAxisLabelStyle(),
                axisLine: this.getAxisLineStyle()
            },
            color: colors,
            series: series
        };
    },

    // Line chart
    getLineChartOption: function(labels, data, colors, labelField, urls) {
        const lineData = labels.map(function(value, index) {
            const v = data[index] != null ? Number(data[index]) || 0 : 0;
            const item = { value: v };
            if (urls && urls[index]) {
                item.url = urls[index];
            }
            return item;
        });
        const primaryColor = this.defaultColors[0];

        return {
            ...this.getAnimationConfig(),
            tooltip: {
                trigger: 'axis',
                formatter: this._lineAreaTooltipFormatter()
            },
            legend: {
                ...this.getLegendConfig(),
                show: true,
                type: 'scroll'
            },
            grid: this.getGridConfig(),
            xAxis: {
                type: 'category',
                data: labels,
                boundaryGap: false,
                axisLabel: {
                    ...this.getAxisLabelStyle(),
                    rotate: labels.some(function(l) { return String(l).length > 8; }) ? 45 : 0
                },
                axisLine: this.getAxisLineStyle()
            },
            yAxis: {
                type: 'value',
                axisLabel: this.getAxisLabelStyle(),
                axisLine: this.getAxisLineStyle(),
                splitLine: this.getSplitLineStyle()
            },
            color: this.defaultColors,
            series: [{
                name: labelField || 'Series',
                type: 'line',
                data: lineData,
                smooth: true,
                symbol: 'circle',
                symbolSize: 6,
                showSymbol: true,
                lineStyle: {
                    width: 3,
                    color: primaryColor
                },
                itemStyle: {
                    color: primaryColor
                }
            }]
        };
    },

    // Funnel Chart Configuration
    getFunnelChartOption: function(labels, data, colors, labelField, urls) {
        var funnelData = this._mapPieData(labels, data, urls);
        var self = this;

        return {
            ...this.getAnimationConfig(),
            tooltip: {
                trigger: 'item',
                formatter: function(params) {
                    var hasUrl = self._dataHasUrl(params.data);
                    return EChartsConfig.escapeHtml(params.seriesName) + '<br/>' + EChartsConfig.escapeHtml(params.name) + ': ' + EChartsConfig.escapeHtml(params.value) +
                        (hasUrl ? '<br/><i>Click to view details</i>' : '');
                }
            },
            legend: this.getLegendConfig(),
            color: colors,
            series: [{
                name: labelField,
                type: 'funnel',
                left: '10%',
                top: '5%',
                width: '80%',
                height: '70%',
                min: 0,
                max: Math.max(...data),
                minSize: '0%',
                maxSize: '100%',
                sort: 'descending',
                gap: 2,
                label: {
                    show: true,
                    position: 'inside',
                    fontSize: 12,
                    fontFamily: this.commonStyles.fontFamily,
                    color: this.getTextColor()
                },
                labelLine: {
                    length: 10,
                    lineStyle: {
                        width: 1,
                        type: 'solid'
                    }
                },
                itemStyle: {
                    borderColor: this.getChartBorderColor(),
                    borderWidth: 1
                },
                emphasis: {
                    label: {
                        fontSize: 14,
                        color: this.getTextColor()
                    }
                },
                data: funnelData
            }]
        };
    },

    // Scatter Chart Configuration
    getScatterChartOption: function(labels, data, colors, labelField, urls) {
        const series = labels.map((label, index) => ({
            name: label,
            type: 'scatter',
            data: [[index, data[index] || 0]],
            symbolSize: function(data) {
                return Math.sqrt(data[1]) * 2 + 10;
            },
            itemStyle: {
                color: colors[index % colors.length],
                opacity: 0.8
            },
            emphasis: {
                focus: 'series',
                itemStyle: {
                    opacity: 1
                }
            }
        }));

        return {
            ...this.getAnimationConfig(),
            tooltip: {
                trigger: 'item',
                formatter: function(params) {
                    const hasUrl = params.data[2] && params.data[2] !== '#';
                    return `${EChartsConfig.escapeHtml(params.seriesName)}: ${EChartsConfig.escapeHtml(params.data[1])}${hasUrl ? '<br/><i style="color: #999; font-size: 11px;">Click to view details</i>' : ''}`;
                }
            },
            legend: {
                ...this.getLegendConfig(),
                show: true,
                type: 'scroll'
            },
            grid: this.getGridConfig(),
            xAxis: {
                type: 'category',
                data: labels,
                axisLabel: {
                    ...this.getAxisLabelStyle(),
                    rotate: labels.some(label => label.length > 8) ? 45 : 0
                },
                axisLine: this.getAxisLineStyle()
            },
            yAxis: {
                type: 'value',
                axisLabel: this.getAxisLabelStyle(),
                axisLine: this.getAxisLineStyle(),
                splitLine: this.getSplitLineStyle()
            },
            color: colors,
            series: series
        };
    },

    // Treemap Chart Configuration
    getTreemapChartOption: function(labels, data, colors, labelField, urls) {
        const palette = this.defaultColors;
        const treemapData = labels.map((label, index) => ({
            name: label,
            value: Math.max(0, Number(data[index]) || 0),
            url: urls && urls[index] ? urls[index] : null,
            itemStyle: {
                color: palette[index % palette.length],
                borderColor: this.getChartBorderColor(),
                borderWidth: 1
            }
        }));

        const legendSeries = labels.map(function(label, index) {
            return {
                name: String(label),
                type: 'bar',
                xAxisIndex: 0,
                yAxisIndex: 0,
                data: [0],
                barWidth: 0,
                barGap: '-100%',
                tooltip: { show: false },
                itemStyle: {
                    color: palette[index % palette.length]
                },
                emphasis: { disabled: true }
            };
        });

        return {
            ...this.getAnimationConfig(),
            tooltip: {
                trigger: 'item',
                formatter: function(params) {
                    if (params.seriesType === 'bar') return '';
                    const d = params.data;
                    const hasUrl = d && d.url && d.url !== '#';
                    return (
                        (params.treePathInfo && params.treePathInfo.length
                            ? params.treePathInfo.map(function(p) { return EChartsConfig.escapeHtml(p.name); }).join(' / ')
                            : EChartsConfig.escapeHtml(params.name)) +
                        '<br/>' +
                        (labelField ? EChartsConfig.escapeHtml(labelField) + ': ' : '') +
                        EChartsConfig.escapeHtml(params.value) +
                        (hasUrl ? '<br/><i style="color: #999; font-size: 11px;">Click to view details</i>' : '')
                    );
                }
            },
            legend: {
                ...this.getLegendConfig(),
                show: labels.length > 0,
                type: 'scroll',
                data: labels.map(function(l) { return String(l); }),
                selectedMode: true
            },
            color: palette,
            grid: {
                left: -1000,
                top: -1000,
                width: 1,
                height: 1,
                show: false
            },
            xAxis: [{
                type: 'category',
                data: [''],
                show: false
            }],
            yAxis: [{
                type: 'value',
                show: false,
                max: 1
            }],
            series: legendSeries.concat([{
                id: 'treemap-main',
                name: labelField || 'Treemap',
                type: 'treemap',
                width: '100%',
                height: '85%',
                top: '2%',
                roam: false,
                nodeClick: false,
                breadcrumb: {
                    show: false
                },
                label: {
                    show: true,
                    formatter: '{b}',
                    fontSize: 11,
                    fontFamily: this.commonStyles.fontFamily,
                    color: this.getTextColor()
                },
                upperLabel: {
                    show: false
                },
                itemStyle: {
                    borderColor: this.getChartBorderColor(),
                    borderWidth: 1,
                    gapWidth: 2
                },
                emphasis: {
                    itemStyle: {
                        shadowBlur: 10,
                        shadowColor: 'rgba(0, 0, 0, 0.25)'
                    },
                    label: {
                        fontSize: 12,
                        fontWeight: 'bold'
                    }
                },
                data: treemapData
            }])
        };
    },

    // Area Chart Configuration (filled line / area under curve)
    getAreaChartOption: function(labels, data, colors, labelField, urls) {
        const areaData = data.map((value, index) => ({
            value: value,
            url: urls && urls[index] ? urls[index] : null
        }));
        const primaryColor = this.defaultColors[0];

        return {
            ...this.getAnimationConfig(),
            tooltip: {
                trigger: 'axis',
                formatter: this._lineAreaTooltipFormatter()
            },
            legend: {
                ...this.getLegendConfig(),
                show: true,
                type: 'scroll'
            },
            grid: this.getGridConfig(),
            xAxis: {
                type: 'category',
                boundaryGap: false,
                data: labels,
                axisLabel: {
                    ...this.getAxisLabelStyle(),
                    rotate: labels.some(function(label) { return String(label).length > 8; }) ? 45 : 0
                },
                axisLine: this.getAxisLineStyle()
            },
            yAxis: {
                type: 'value',
                axisLabel: this.getAxisLabelStyle(),
                axisLine: this.getAxisLineStyle(),
                splitLine: this.getSplitLineStyle()
            },
            color: this.defaultColors,
            series: [{
                name: labelField,
                type: 'line',
                data: areaData,
                smooth: true,
                symbol: 'circle',
                symbolSize: 6,
                showSymbol: true,
                lineStyle: {
                    width: 2,
                    color: primaryColor
                },
                itemStyle: {
                    color: primaryColor
                },
                areaStyle: {
                    color: primaryColor,
                    opacity: this.isDarkMode() ? 0.35 : 0.45
                }
            }]
        };
    },

    _phantomLegendGrid: function() {
        return {
            grid: { left: -1000, top: -1000, width: 1, height: 1, show: false },
            xAxis: [{ type: 'category', data: [''], show: false }],
            yAxis: [{ type: 'value', show: false, max: 1 }]
        };
    },

    filterStackedDataByCategories: function(stackedData, selected) {
        if (!stackedData || !stackedData.categories || !stackedData.series) return stackedData;
        var categories = stackedData.categories;
        var keepIdx = [];
        for (var i = 0; i < categories.length; i++) {
            var key = '__g_' + i + '__';
            if (selected && selected[key] === false) continue;
            keepIdx.push(i);
        }
        if (keepIdx.length === 0) return { categories: [], series: stackedData.series.map(function(s) { return { name: s.name, data: [] }; }) };
        var newCategories = keepIdx.map(function(i) { return categories[i]; });
        var newSeries = stackedData.series.map(function(s) {
            var row = s.data || [];
            return {
                name: s.name,
                data: keepIdx.map(function(i) { return row[i]; })
            };
        });
        return { categories: newCategories, series: newSeries };
    },

    getStackedVerticalChartOption: function(stackedData, colors, labelField, urls, opts) {
        if (!stackedData || !stackedData.categories || !stackedData.series || stackedData.series.length === 0) {
            return this.getColumnChartOption(['No Data'], [0], this.defaultColors, labelField);
        }

        opts = opts || {};
        const palette = this.defaultColors;
        const categories = stackedData.categories;
        const originalCats = (opts.originalStackedData && opts.originalStackedData.categories) || categories;
        const catIds = originalCats.map(function(_, i) { return '__g_' + i + '__'; });
        const catLabelById = {};
        originalCats.forEach(function(c, i) { catLabelById[catIds[i]] = String(c); });

        const phantomCats = catIds.map(function(id, index) {
            return {
                name: id,
                type: 'bar',
                gridIndex: 0,
                xAxisIndex: 0,
                yAxisIndex: 0,
                data: [0],
                barWidth: 0,
                barGap: '-100%',
                tooltip: { show: false },
                itemStyle: { color: palette[index % palette.length] },
                emphasis: { disabled: true }
            };
        });

        const series = stackedData.series.map((seriesItem, index) => ({
            name: seriesItem.name,
            type: 'bar',
            stack: 'total',
            data: seriesItem.data,
            barWidth: '60%',
            itemStyle: {
                borderRadius: index === stackedData.series.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]
            },
            emphasis: {
                itemStyle: {
                    shadowBlur: 10,
                    shadowOffsetX: 0,
                    shadowColor: 'rgba(0, 0, 0, 0.5)'
                }
            }
        }));

        const legendBase = this.getLegendConfig();
        const seriesNames = stackedData.series.map(function(s) { return s.name; });
        const dualLegend = [
            {
                ...legendBase,
                show: catIds.length > 0,
                type: 'scroll',
                data: catIds,
                selectedMode: true,
                top: '0%',
                bottom: undefined,
                left: 'center',
                formatter: function(name) { return catLabelById[name] != null ? catLabelById[name] : name; },
                selected: opts.legendSelected ? (function() {
                    var s = {};
                    catIds.forEach(function(id) {
                        if (opts.legendSelected[id] !== undefined) s[id] = opts.legendSelected[id];
                    });
                    return Object.keys(s).length ? s : undefined;
                })() : undefined
            },
            {
                ...legendBase,
                show: true,
                type: 'scroll',
                data: seriesNames,
                selectedMode: true,
                bottom: '0%',
                top: undefined,
                left: 'center',
                selected: opts.legendSelected ? (function() {
                    var s = {};
                    seriesNames.forEach(function(n) {
                        if (opts.legendSelected[n] !== undefined) s[n] = opts.legendSelected[n];
                    });
                    return Object.keys(s).length ? s : undefined;
                })() : undefined
            }
        ];
        const phantom = this._phantomLegendGrid();
        const mainGrid = { ...this.getGridConfig(), top: '12%', bottom: '20%' };

        return {
            ...this.getAnimationConfig(),
            tooltip: {
                trigger: 'item',
                formatter: function(param) {
                    if (!param || (param.seriesName && param.seriesName.indexOf('__g_') === 0)) return '';
                    const v = param.data && typeof param.data === 'object' && param.data.value !== undefined
                        ? param.data.value
                        : param.value;
                    const hasUrl = param.data && param.data.url && param.data.url !== '#';
                    return `<strong>${EChartsConfig.escapeHtml(param.name)}</strong><br/>${param.marker} ${EChartsConfig.escapeHtml(param.seriesName)}: ${EChartsConfig.escapeHtml(v)}${hasUrl ? '<br/><i style="color: #999; font-size: 11px;">Click to view details</i>' : ''}`;
                }
            },
            legend: dualLegend,
            grid: [phantom.grid, mainGrid],
            xAxis: [
                phantom.xAxis[0],
                {
                gridIndex: 1,
                type: 'category',
                data: stackedData.categories,
                axisLabel: {
                    ...this.getAxisLabelStyle(),
                    rotate: stackedData.categories.some(cat => cat.length > 8) ? 45 : 0
                },
                axisTick: {
                    show: false
                },
                axisLine: this.getAxisLineStyle()
            }
            ],
            yAxis: [
                phantom.yAxis[0],
                {
                gridIndex: 1,
                type: 'value',
                axisLabel: this.getAxisLabelStyle(),
                axisLine: this.getAxisLineStyle(),
                splitLine: this.getSplitLineStyle()
            }
            ],
            color: palette,
            series: phantomCats.concat(series.map(function(s) {
                s.gridIndex = 1;
                s.xAxisIndex = 1;
                s.yAxisIndex = 1;
                return s;
            }))
        };
    },

    // Stacked Horizontal Chart Configuration (dual legend when two groups)
    getStackedHorizontalChartOption: function(stackedData, colors, labelField, urls, opts) {
        if (!stackedData || !stackedData.categories || !stackedData.series || stackedData.series.length === 0) {
            return this.getBarChartOption(['No Data'], [0], this.defaultColors, labelField);
        }

        opts = opts || {};
        const palette = this.defaultColors;
        const categories = stackedData.categories;
        const originalCats = (opts.originalStackedData && opts.originalStackedData.categories) || categories;
        const catIds = originalCats.map(function(_, i) { return '__g_' + i + '__'; });
        const catLabelById = {};
        originalCats.forEach(function(c, i) { catLabelById[catIds[i]] = String(c); });

        const phantomCats = catIds.map(function(id, index) {
            return {
                name: id,
                type: 'bar',
                gridIndex: 0,
                xAxisIndex: 0,
                yAxisIndex: 0,
                data: [0],
                barWidth: 0,
                barGap: '-100%',
                tooltip: { show: false },
                itemStyle: { color: palette[index % palette.length] },
                emphasis: { disabled: true }
            };
        });

        const series = stackedData.series.map((seriesItem, index) => ({
            name: seriesItem.name,
            type: 'bar',
            stack: 'total',
            data: seriesItem.data,
            barWidth: '60%',
            itemStyle: {
                borderRadius: index === stackedData.series.length - 1 ? [0, 4, 4, 0] : [0, 0, 0, 0]
            },
            emphasis: {
                itemStyle: {
                    shadowBlur: 10,
                    shadowOffsetX: 0,
                    shadowColor: 'rgba(0, 0, 0, 0.5)'
                }
            }
        }));

        const legendBase = this.getLegendConfig();
        const seriesNamesH = stackedData.series.map(function(s) { return s.name; });
        const dualLegend = [
            {
                ...legendBase,
                show: catIds.length > 0,
                type: 'scroll',
                data: catIds,
                selectedMode: true,
                top: '0%',
                bottom: undefined,
                left: 'center',
                formatter: function(name) { return catLabelById[name] != null ? catLabelById[name] : name; },
                selected: opts.legendSelected ? (function() {
                    var s = {};
                    catIds.forEach(function(id) {
                        if (opts.legendSelected[id] !== undefined) s[id] = opts.legendSelected[id];
                    });
                    return Object.keys(s).length ? s : undefined;
                })() : undefined
            },
            {
                ...legendBase,
                show: true,
                type: 'scroll',
                data: seriesNamesH,
                selectedMode: true,
                bottom: '0%',
                top: undefined,
                left: 'center',
                selected: opts.legendSelected ? (function() {
                    var s = {};
                    seriesNamesH.forEach(function(n) {
                        if (opts.legendSelected[n] !== undefined) s[n] = opts.legendSelected[n];
                    });
                    return Object.keys(s).length ? s : undefined;
                })() : undefined
            }
        ];
        const phantom = this._phantomLegendGrid();
        const mainGrid = { ...this.getGridConfig(), left: '8%', top: '12%', bottom: '20%' };

        return {
            ...this.getAnimationConfig(),
            tooltip: {
                trigger: 'item',
                formatter: function(param) {
                    if (!param || (param.seriesName && param.seriesName.indexOf('__g_') === 0)) return '';
                    const v = param.data && typeof param.data === 'object' && param.data.value !== undefined
                        ? param.data.value : param.value;
                    const hasUrl = param.data && param.data.url && param.data.url !== '#';
                    return `<strong>${EChartsConfig.escapeHtml(param.name)}</strong><br/>${param.marker} ${EChartsConfig.escapeHtml(param.seriesName)}: ${EChartsConfig.escapeHtml(v)}${hasUrl ? '<br/><i style="color: #999; font-size: 11px;">Click to view details</i>' : ''}`;
                }
            },
            legend: dualLegend,
            grid: [phantom.grid, mainGrid],
            xAxis: [
                phantom.xAxis[0],
                {
                gridIndex: 1,
                type: 'value',
                axisLabel: this.getAxisLabelStyle(),
                axisLine: this.getAxisLineStyle(),
                splitLine: this.getSplitLineStyle()
            }
            ],
            yAxis: [
                phantom.yAxis[0],
                {
                gridIndex: 1,
                type: 'category',
                data: stackedData.categories,
                axisLabel: this.getAxisLabelStyle(),
                axisTick: { show: false },
                axisLine: this.getAxisLineStyle()
            }
            ],
            color: palette,
            series: phantomCats.concat(series.map(function(s) {
                s.gridIndex = 1;
                s.xAxisIndex = 1;
                s.yAxisIndex = 1;
                return s;
            }))
        };
    },


    buildHeatmapData: function(stackedData, selected) {
        const categories = stackedData.categories;
        const seriesList = stackedData.series;
        const keepI = [];
        const keepJ = [];
        for (let i = 0; i < categories.length; i++) {
            if (selected && selected['__g_' + i + '__'] === false) continue;
            keepI.push(i);
        }
        for (let j = 0; j < seriesList.length; j++) {
            if (selected && selected['__s_' + j + '__'] === false) continue;
            keepJ.push(j);
        }
        if (keepI.length === 0 || keepJ.length === 0) {
            return { categories: [], yNames: [], heatData: [], maxVal: 0 };
        }
        const newCategories = keepI.map(function(i) { return categories[i]; });
        const newYNames = keepJ.map(function(j) { return seriesList[j].name; });
        const heatData = [];
        let maxVal = 0;
        for (let jj = 0; jj < keepJ.length; jj++) {
            const j = keepJ[jj];
            const row = seriesList[j].data || [];
            for (let ii = 0; ii < keepI.length; ii++) {
                const i = keepI[ii];
                const raw = row[i];
                const v = typeof raw === 'object' && raw !== null && raw.value !== undefined
                    ? Number(raw.value) || 0
                    : Number(raw) || 0;
                const cellUrl = typeof raw === 'object' && raw !== null && raw.url ? raw.url : null;
                if (v > maxVal) maxVal = v;
                if (cellUrl) {
                    heatData.push([ii, jj, v, cellUrl]);
                } else {
                    heatData.push([ii, jj, v]);
                }
            }
        }
        return { categories: newCategories, yNames: newYNames, heatData: heatData, maxVal: maxVal };
    },

    // Heatmap Configuration
    getHeatmapChartOption: function(stackedData, colors, labelField, urls, opts) {
        if (!stackedData || !stackedData.categories || !stackedData.series || stackedData.series.length === 0) {
            return this.getColumnChartOption(['No Data'], [0], this.defaultColors, labelField);
        }

        opts = opts || {};
        const originalStacked = opts.originalStackedData || stackedData;
        const originalCats = originalStacked.categories;
        const originalSeries = originalStacked.series;
        const originalYNames = originalSeries.map(function(s) { return s.name; });

        const built = this.buildHeatmapData(originalStacked, opts.legendSelected || null);
        let categories = built.categories;
        let yNames = built.yNames;
        let heatData = built.heatData;
        let maxVal = built.maxVal;
        if (categories.length === 0 || yNames.length === 0) {
            return this.getColumnChartOption(['No Data'], [0], this.defaultColors, labelField);
        }

        const catIds = originalCats.map(function(_, i) { return '__g_' + i + '__'; });
        const serIds = originalYNames.map(function(_, j) { return '__s_' + j + '__'; });

        const textColor = this.getTextColor();
        const isDark = this.isDarkMode();
        const heatmapColors = isDark
            ? ['#fca5a5', '#f9a8a2', '#c4b5fd', '#a5b4fc', '#818cf8']
            : ['#fca5a5', '#fbcfe8', '#ddd6fe', '#a5b4fc'];
        const heatmapBg = isDark ? '#111827' : '#f8fafc';
        const palette = this.defaultColors;
        const catLabelById = {};
        originalCats.forEach(function(c, i) { catLabelById[catIds[i]] = String(c); });
        const serLabelById = {};
        originalYNames.forEach(function(n, j) { serLabelById[serIds[j]] = String(n); });
        const phantom = this._phantomLegendGrid();
        const phantomCats = catIds.map(function(id, index) {
            return {
                name: id, type: 'bar', gridIndex: 0, xAxisIndex: 0, yAxisIndex: 0,
                data: [0], barWidth: 0, barGap: '-100%', tooltip: { show: false },
                itemStyle: { color: palette[index % palette.length] }, emphasis: { disabled: true }
            };
        });
        const phantomSeries = serIds.map(function(id, index) {
            return {
                name: id, type: 'bar', gridIndex: 0, xAxisIndex: 0, yAxisIndex: 0,
                data: [0], barWidth: 0, barGap: '-100%', tooltip: { show: false },
                itemStyle: { color: palette[(index + catIds.length) % palette.length] }, emphasis: { disabled: true }
            };
        });
        const legendBase = this.getLegendConfig();
        const legendSelectedFull = this._mergeDualLegendSelected(catIds, serIds, opts.legendSelected);
        const heatmapDualLegend = [
            {
                ...legendBase,
                show: catIds.length > 0,
                type: 'scroll',
                data: catIds,
                selectedMode: true,
                top: '1%',
                bottom: undefined,
                left: 'center',
                formatter: function(name) { return catLabelById[name] != null ? catLabelById[name] : name; },
                selected: legendSelectedFull
            },
            {
                ...legendBase,
                show: serIds.length > 0,
                type: 'scroll',
                data: serIds,
                selectedMode: true,
                bottom: '0%',
                top: undefined,
                left: 'center',
                formatter: function(name) { return serLabelById[name] != null ? serLabelById[name] : name; },
                selected: legendSelectedFull
            }
        ];

        return {
            ...this.getAnimationConfig(),
            backgroundColor: heatmapBg,
            legend: heatmapDualLegend,
            tooltip: {
                position: 'top',
                formatter: function(params) {
                    if (!params.data || params.data.length < 3) return '';
                    const xIdx = params.data[0];
                    const yIdx = params.data[1];
                    const val = params.data[2];
                    const xLabel = categories[xIdx] != null ? categories[xIdx] : xIdx;
                    const yLabel = yNames[yIdx] != null ? yNames[yIdx] : yIdx;
                    let s = EChartsConfig.escapeHtml(xLabel) + ' × ' + EChartsConfig.escapeHtml(yLabel) + '<br/><strong>' + EChartsConfig.escapeHtml(val) + '</strong>';
                    if (urls && urls[xIdx] && urls[xIdx] !== '#') {
                        s += '<br/><i style="color: #999; font-size: 11px;">Click to view details</i>';
                    }
                    return s;
                }
            },
            grid: [
                phantom.grid,
                { left: '8%', right: '6%', top: '12%', bottom: '28%', containLabel: false }
            ],
            xAxis: [
                phantom.xAxis[0],
                {
                gridIndex: 1,
                type: 'category',
                data: categories,
                splitArea: { show: false },
                axisLabel: {
                    ...this.getAxisLabelStyle(),
                    rotate: categories.some(function(c) { return String(c).length > 10; }) ? 45 : 0,
                    interval: 0,
                    margin: 10
                },
                axisLine: this.getAxisLineStyle()
            }
            ],
            yAxis: [
                phantom.yAxis[0],
                {
                gridIndex: 1,
                type: 'category',
                data: yNames,
                splitArea: { show: false },
                axisLabel: this.getAxisLabelStyle(),
                axisLine: this.getAxisLineStyle()
            }
            ],
            visualMap: {
                show: true,
                type: 'continuous',
                min: 0,
                max: Math.max(maxVal, 1),
                dimension: 2,
                calculable: true,
                orient: 'horizontal',
                left: 'center',
                bottom: '9%',
                padding: [4, 0, 4, 0],
                textStyle: { color: textColor },
                inRange: {
                    color: heatmapColors
                },
                outOfRange: {
                    color: [heatmapColors[0]]
                },
                seriesIndex: [catIds.length + serIds.length]
            },
            series: phantomCats.concat(phantomSeries).concat([{
                name: labelField || 'Heatmap',
                type: 'heatmap',
                gridIndex: 1,
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: heatData,
                itemStyle: {
                    borderColor: isDark ? '#1f2937' : '#e2e8f0',
                    borderWidth: 1
                },
                label: {
                    show: true,
                    color: isDark ? '#f9fafb' : '#1e293b',
                    textBorderColor: isDark ? '#0c0a09' : '#ffffff',
                    textBorderWidth: 1,
                    fontWeight: 600,
                    formatter: function(p) {
                        return p.data[2] > 0 ? p.data[2] : '';
                    }
                },
                emphasis: {
                    itemStyle: {
                        shadowBlur: 10,
                        shadowColor: 'rgba(0,0,0,0.3)'
                    }
                },
                progressive: 0,
                animation: true
            }])
        };
    },


    buildSankeyNodesLinks: function(stackedData, colors, selected) {
        const palette = this.defaultColors;
        const categories = stackedData.categories;
        const seriesList = stackedData.series;
        const leftSet = new Set(categories.map(function(c) { return String(c); }));
        const seenRight = new Set(leftSet);
        const rightTargets = seriesList.map(function(s, j) {
            const label = String(s.name);
            let id = label;
            if (seenRight.has(id)) {
                id = '__sk_t_' + j;
            }
            if (seenRight.has(id)) {
                id = id + '_' + j;
            }
            seenRight.add(id);
            return { id: id, label: label };
        });

        const links = [];
        for (let j = 0; j < seriesList.length; j++) {
            const row = seriesList[j].data || [];
            const targetId = rightTargets[j].id;
            if (selected && selected[targetId] === false) continue;
            for (let i = 0; i < categories.length; i++) {
                const sourceName = String(categories[i]);
                if (selected && selected[sourceName] === false) continue;
                const raw = row[i];
                const v = typeof raw === 'object' && raw !== null && raw.value !== undefined
                    ? Number(raw.value) || 0
                    : Number(raw) || 0;
                const url = typeof raw === 'object' && raw !== null && raw.url ? raw.url : null;
                if (v > 0) {
                    links.push({
                        source: sourceName,
                        target: targetId,
                        value: v,
                        url: url
                    });
                }
            }
        }

        const leftUsed = new Set();
        const rightUsed = new Set();
        links.forEach(function(l) {
            leftUsed.add(l.source);
            rightUsed.add(l.target);
        });

        const nodes = [];
        categories.forEach(function(c, idx) {
            const name = String(c);
            if (!leftUsed.has(name)) return;
            nodes.push({
                name: name,
                depth: 0,
                itemStyle: {
                    color: palette[idx % palette.length],
                    borderColor: this.getChartBorderColor()
                }
            });
        }.bind(this));
        rightTargets.forEach(function(t, idx) {
            if (!rightUsed.has(t.id)) return;
            nodes.push({
                name: t.id,
                depth: 1,
                itemStyle: {
                    color: palette[idx % palette.length],
                    borderColor: this.getChartBorderColor()
                }
            });
        }.bind(this));

        return {
            nodes: nodes,
            links: links,
            categoryNames: categories.map(function(c) { return String(c); }),
            rightTargets: rightTargets
        };
    },

    getSankeyChartOption: function(stackedData, colors, labelField, urls) {
        if (!stackedData || !stackedData.categories || !stackedData.series || stackedData.series.length === 0) {
            return this.getColumnChartOption(['No Data'], [0], this.defaultColors, labelField);
        }

        const palette = this.defaultColors;
        const built = this.buildSankeyNodesLinks(stackedData, palette, null);
        const nodes = built.nodes;
        const links = built.links;
        const categoryNames = built.categoryNames;
        const rightTargets = built.rightTargets || [];

        if (links.length === 0) {
            return this.getColumnChartOption(['No Data'], [0], this.defaultColors, labelField);
        }

        const textColor = this.getTextColor();
        const isDark = this.isDarkMode();
        const self = this;

        const legendSeriesLeft = categoryNames.map(function(name, index) {
            return {
                name: name,
                type: 'bar',
                xAxisIndex: 0,
                yAxisIndex: 0,
                data: [0],
                barWidth: 0,
                barGap: '-100%',
                tooltip: { show: false },
                itemStyle: {
                    color: palette[index % palette.length]
                },
                emphasis: { disabled: true }
            };
        });
        const rightIdToLabel = {};
        rightTargets.forEach(function(t) { rightIdToLabel[t.id] = t.label; });

        const legendSeriesRight = rightTargets.map(function(t, index) {
            return {
                name: t.id,
                type: 'bar',
                xAxisIndex: 0,
                yAxisIndex: 0,
                data: [0],
                barWidth: 0,
                barGap: '-100%',
                tooltip: { show: false },
                itemStyle: {
                    color: palette[index % palette.length]
                },
                emphasis: { disabled: true }
            };
        });
        const legendSeries = legendSeriesLeft.concat(legendSeriesRight);

        const legendBase = this.getLegendConfig();
        const dualLegend = [];
        if (categoryNames.length > 0) {
            dualLegend.push({
                ...legendBase,
                show: true,
                type: 'scroll',
                data: categoryNames,
                selectedMode: true,
                top: '0%',
                bottom: undefined,
                left: 'center'
            });
        }
        if (rightTargets.length > 0) {
            dualLegend.push({
                ...legendBase,
                show: true,
                type: 'scroll',
                data: rightTargets.map(function(t) { return t.id; }),
                formatter: function(name) { return rightIdToLabel[name] != null ? rightIdToLabel[name] : name; },
                selectedMode: true,
                bottom: '0%',
                top: undefined,
                left: 'center'
            });
        }

        return {
            ...this.getAnimationConfig(),
            tooltip: {
                trigger: 'item',
                triggerOn: 'mousemove',
                formatter: function(params) {
                    if (params.seriesType === 'bar') return '';
                    if (params.dataType === 'edge') {
                        var tgt = params.data.target;
                        if (rightIdToLabel[tgt] != null) tgt = rightIdToLabel[tgt];
                        return EChartsConfig.escapeHtml(params.data.source) + ' → ' + EChartsConfig.escapeHtml(tgt) + '<br/><strong>' + EChartsConfig.escapeHtml(params.data.value) + '</strong>';
                    }
                    if (params.dataType === 'node') {
                        if (rightIdToLabel[params.name] != null) return EChartsConfig.escapeHtml(rightIdToLabel[params.name]);
                        return EChartsConfig.escapeHtml(params.name);
                    }
                    return '';
                }
            },
            legend: dualLegend.length > 1 ? dualLegend : (dualLegend.length === 1 ? dualLegend[0] : { show: false }),
            color: palette,
            grid: {
                left: -1000,
                top: -1000,
                width: 1,
                height: 1,
                show: false
            },
            xAxis: [{
                type: 'category',
                data: [''],
                show: false
            }],
            yAxis: [{
                type: 'value',
                show: false,
                max: 1
            }],
            series: legendSeries.concat([{
                id: 'sankey-main',
                name: labelField || 'Sankey',
                type: 'sankey',
                top: dualLegend.length > 1 ? '10%' : '2%',
                bottom: dualLegend.length > 1 ? '14%' : undefined,
                emphasis: {
                    itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.5)' },
                    lineStyle: { opacity: 0.8 }
                },
                layoutIterations: 32,
                data: nodes,
                links: links,
                lineStyle: {
                    color: 'gradient',
                    curveness: 0.5,
                    opacity: isDark ? 0.35 : 0.45
                },
                label: {
                    color: textColor,
                    fontFamily: self.commonStyles.fontFamily,
                    fontSize: 11,
                    formatter: function(p) {
                        var n = p.name != null ? p.name : (p.data && p.data.name);
                        if (n && rightIdToLabel[n] != null) return rightIdToLabel[n];
                        return n || '';
                    }
                },
                itemStyle: {
                    borderWidth: 0
                },
                levels: [
                    { depth: 0, itemStyle: { borderColor: self.getChartBorderColor() } },
                    { depth: 1, itemStyle: { borderColor: self.getChartBorderColor() } }
                ],
                nodeWidth: 12,
                nodeGap: 8
            }])
        };
    },

    // Radar chart — single dimension: one polygon over labels as axes
    getRadarChartOption: function(labels, data, colors, labelField, urls) {
        if (!labels || labels.length === 0) {
            return this.getPieChartOption(['No Data'], [0], colors, labelField, urls);
        }

        function toNum(v) {
            if (typeof v === 'object' && v !== null && v.value !== undefined) {
                return Math.max(0, Number(v.value) || 0);
            }
            return Math.max(0, Number(v) || 0);
        }

        const values = labels.map(function(_, i) { return toNum(data[i]); });
        const globalMax = Math.max.apply(null, values.concat([1]));
        const axisMax = Math.ceil(globalMax * 1.15) || 1;

        const indicator = labels.map(function(name) {
            return { name: String(name), max: axisMax };
        });

        const textColor = this.getTextColor();
        const radarLine = this.getAxisLineColor();

        return {
            ...this.getAnimationConfig(),
            tooltip: {
                trigger: 'item',
                formatter: function(params) {
                    if (!params.data || !params.data.value || !indicator.length) {
                        return EChartsConfig.escapeHtml(params.name || params.seriesName || '');
                    }
                    var seriesName = params.data.name || params.seriesName || (labelField || 'Radar');
                    return EChartsConfig._radarTooltipHtml(seriesName, params.data.value, indicator);
                }
            },
            legend: {
                ...this.getLegendConfig(),
                show: true,
                type: 'scroll'
            },
            radar: {
                indicator: indicator,
                shape: 'polygon',
                splitNumber: 4,
                axisName: {
                    color: textColor,
                    fontSize: 11,
                    fontFamily: this.commonStyles.fontFamily
                },
                splitLine: { lineStyle: { color: this.getSplitLineColor() } },
                splitArea: { show: true, areaStyle: { color: [this.isDarkMode() ? 'rgba(55,65,81,0.15)' : 'rgba(0,0,0,0.02)'] } },
                axisLine: { lineStyle: { color: radarLine } }
            },
            series: [{
                name: labelField || 'Radar',
                type: 'radar',
                symbol: 'circle',
                symbolSize: 6,
                lineStyle: { width: 2, color: this.defaultColors[0] },
                itemStyle: { color: this.defaultColors[0] },
                areaStyle: { opacity: 0.2 },
                data: [{
                    value: values,
                    name: labelField || 'Value'
                }]
            }]
        };
    },

    /**
     * Build radar indicator + radarData from stackedData; selected __g_i__ / __s_j__ false excludes axis or polygon.
     */
    buildRadarFromStacked: function(stackedData, colors, selected) {
        const categories = stackedData.categories;
        const seriesList = stackedData.series;
        const palette = this.defaultColors;

        function toNum(v) {
            if (typeof v === 'object' && v !== null && v.value !== undefined) {
                return Math.max(0, Number(v.value) || 0);
            }
            return Math.max(0, Number(v) || 0);
        }

        const keepI = [];
        for (let i = 0; i < categories.length; i++) {
            if (selected && selected['__g_' + i + '__'] === false) continue;
            keepI.push(i);
        }
        const keepJ = [];
        for (let j = 0; j < seriesList.length; j++) {
            if (selected && selected['__s_' + j + '__'] === false) continue;
            keepJ.push(j);
        }
        if (keepI.length === 0 || keepJ.length === 0) {
            return { indicator: [], radarData: [], axisMax: 1 };
        }

        let globalMax = 1;
        for (let jj = 0; jj < keepJ.length; jj++) {
            const j = keepJ[jj];
            const row = seriesList[j].data || [];
            for (let ii = 0; ii < keepI.length; ii++) {
                const i = keepI[ii];
                const v = toNum(row[i]);
                if (v > globalMax) globalMax = v;
            }
        }
        const axisMax = Math.ceil(globalMax * 1.15) || 1;

        const indicator = keepI.map(function(i) {
            return { name: String(categories[i]), max: axisMax };
        });

        const radarData = keepJ.map(function(j, idx) {
            const s = seriesList[j];
            const row = s.data || [];
            const vals = keepI.map(function(i) { return toNum(row[i]); });
            return {
                value: vals,
                name: '__s_' + j + '__',
                itemStyle: { color: palette[j % palette.length] },
                lineStyle: { color: palette[j % palette.length] },
                areaStyle: { opacity: 0.12 }
            };
        });

        return { indicator: indicator, radarData: radarData, axisMax: axisMax, keepI: keepI, keepJ: keepJ };
    },

    // Radar chart — stacked payload: dual legends like Sankey (axes + series), clickable
    getRadarChartOptionFromStacked: function(stackedData, colors, labelField, urls, opts) {
        const categories = stackedData.categories;
        const seriesList = stackedData.series;
        if (!categories || categories.length === 0 || !seriesList || seriesList.length === 0) {
            return this.getRadarChartOption(['No Data'], [0], this.defaultColors, labelField, urls);
        }

        opts = opts || {};
        const originalStacked = opts.originalStackedData || stackedData;
        const originalCats = originalStacked.categories;
        const originalSeries = originalStacked.series;
        const palette = this.defaultColors;

        const catIds = originalCats.map(function(_, i) { return '__g_' + i + '__'; });
        const serIds = originalSeries.map(function(_, j) { return '__s_' + j + '__'; });
        const catLabelById = {};
        originalCats.forEach(function(c, i) { catLabelById[catIds[i]] = String(c); });
        const serLabelById = {};
        originalSeries.forEach(function(s, j) { serLabelById[serIds[j]] = String(s.name); });

        const legendSelectedFull = this._mergeDualLegendSelected(catIds, serIds, opts.legendSelected);

        const built = this.buildRadarFromStacked(originalStacked, palette, opts.legendSelected || null);
        if (!built.indicator.length || !built.radarData.length) {
            return this.getRadarChartOption(['No Data'], [0], this.defaultColors, labelField, urls);
        }

        const textColor = this.getTextColor();
        const phantom = this._phantomLegendGrid();
        const phantomCats = catIds.map(function(id, index) {
            return {
                name: id, type: 'bar', gridIndex: 0, xAxisIndex: 0, yAxisIndex: 0,
                data: [0], barWidth: 0, barGap: '-100%', tooltip: { show: false },
                itemStyle: { color: palette[index % palette.length] }, emphasis: { disabled: true }
            };
        });
        const phantomSeries = serIds.map(function(id, index) {
            return {
                name: id, type: 'bar', gridIndex: 0, xAxisIndex: 0, yAxisIndex: 0,
                data: [0], barWidth: 0, barGap: '-100%', tooltip: { show: false },
                itemStyle: { color: palette[(index + catIds.length) % palette.length] }, emphasis: { disabled: true }
            };
        });

        const legendBase = this.getLegendConfig();
        const dualLegend = [
            {
                ...legendBase,
                show: catIds.length > 0,
                type: 'scroll',
                data: catIds,
                selectedMode: true,
                top: '0%',
                bottom: undefined,
                left: 'center',
                formatter: function(name) { return catLabelById[name] != null ? catLabelById[name] : name; },
                selected: legendSelectedFull
            },
            {
                ...legendBase,
                show: serIds.length > 0,
                type: 'scroll',
                data: serIds,
                selectedMode: true,
                bottom: '0%',
                top: undefined,
                left: 'center',
                formatter: function(name) { return serLabelById[name] != null ? serLabelById[name] : name; },
                selected: legendSelectedFull
            }
        ];

        return {
            ...this.getAnimationConfig(),
            tooltip: {
                trigger: 'item',
                formatter: function(params) {
                    if (params.seriesType === 'bar') return '';
                    var n = params.name;
                    if (serLabelById[n] != null) n = serLabelById[n];
                    if (params.data && params.data.value && built.indicator && built.indicator.length) {
                        return EChartsConfig._radarTooltipHtml(n, params.data.value, built.indicator);
                    }
                    return EChartsConfig.escapeHtml(n || '');
                }
            },
            legend: dualLegend,
            grid: [phantom.grid],
            xAxis: phantom.xAxis,
            yAxis: phantom.yAxis,
            radar: {
                indicator: built.indicator,
                shape: 'polygon',
                splitNumber: 4,
                center: ['50%', '52%'],
                radius: '58%',
                axisName: {
                    color: textColor,
                    fontSize: 11,
                    fontFamily: this.commonStyles.fontFamily
                },
                splitLine: { lineStyle: { color: this.getSplitLineColor() } },
                splitArea: { show: true, areaStyle: { color: [this.isDarkMode() ? 'rgba(55,65,81,0.15)' : 'rgba(0,0,0,0.02)'] } },
                axisLine: { lineStyle: { color: this.getAxisLineColor() } }
            },
            color: palette,
            series: phantomCats.concat(phantomSeries).concat([{
                id: 'radar-main',
                name: labelField || 'Radar',
                type: 'radar',
                symbol: 'circle',
                symbolSize: 5,
                data: built.radarData
            }])
        };
    },

    // Animation configurations (delay fns reused to avoid per-chart allocations)
    _animationDelayByIndex: function(idx) { return idx * 10; },
    getAnimationConfig: function() {
        return {
            animation: true,
            animationThreshold: 2000,
            animationDuration: 1000,
            animationEasing: 'cubicOut',
            animationDelay: this._animationDelayByIndex,
            animationDurationUpdate: 300,
            animationEasingUpdate: 'cubicOut',
            animationDelayUpdate: this._animationDelayByIndex
        };
    },

    /**
     * Treemap uses phantom bar series so the legend shows; when legend is clicked,
     * sync treemap data so tiles show/hide to match selection.
     */
    attachTreemapLegendHandler: function(chartInstance, config) {
        if (!chartInstance || !config || config.type !== 'treemap' || !config.labels || !config.labels.length) return;
        var self = this;
        var labels = config.labels;
        var data = config.data || [];
        var urls = config.urls || [];
        var palette = this.defaultColors;
        var labelField = config.labelField || 'Treemap';

        function buildTreemapData(selected) {
            var nodes = [];
            for (var i = 0; i < labels.length; i++) {
                var label = labels[i];
                var key = String(label);
                if (selected && selected[key] === false) continue;
                var index = i;
                nodes.push({
                    name: label,
                    value: Math.max(0, Number(data[index]) || 0),
                    url: urls[index] || null,
                    itemStyle: {
                        color: palette[index % palette.length],
                        borderColor: self.getChartBorderColor(),
                        borderWidth: 1
                    }
                });
            }
            if (nodes.length === 0) {
                nodes.push({
                    name: '(none)',
                    value: 1,
                    itemStyle: {
                        color: self.isDarkMode() ? '#374151' : '#e5e7eb',
                        borderColor: self.getChartBorderColor(),
                        borderWidth: 1
                    }
                });
            }
            return nodes;
        }

        chartInstance.on('legendselectchanged', function(evt) {
            if (!evt || !evt.selected) return;
            var treemapData = buildTreemapData(evt.selected);
            // Merge by series id so phantom bar series stay intact
            chartInstance.setOption({
                series: [{ id: 'treemap-main', data: treemapData }]
            });
        });
    },

    /**
     * Sankey legend = left column categories; clicking filters links from that source.
     */
    attachSankeyLegendHandler: function(chartInstance, config) {
        if (!chartInstance || !config || config.type !== 'sankey' || !config.stackedData ||
            !config.stackedData.categories || !config.stackedData.series || config.stackedData.series.length === 0) {
            return;
        }
        var self = this;
        var stackedData = config.stackedData;
        var palette = this.defaultColors;

        chartInstance.on('legendselectchanged', function(evt) {
            if (!evt || !evt.selected) return;
            var built = self.buildSankeyNodesLinks(stackedData, palette, evt.selected);
            if (built.links.length === 0) {
                // All categories hidden — show empty sankey placeholder to avoid ECharts errors
                chartInstance.setOption({
                    series: [{
                        id: 'sankey-main',
                        data: [{ name: '(none)', depth: 0 }],
                        links: []
                    }]
                });
                return;
            }
            chartInstance.setOption({
                series: [{
                    id: 'sankey-main',
                    data: built.nodes,
                    links: built.links
                }]
            });
        });
    },

    attachHeatmapLegendHandler: function(chartInstance, config) {
        if (!chartInstance || !config || config.type !== 'heatmap' || !config.stackedData ||
            !config.stackedData.categories || !config.stackedData.series || config.stackedData.series.length === 0) {
            return;
        }
        var self = this;
        var originalStacked = config.stackedData;
        var palette = this.defaultColors;
        var labelField = config.labelField || '';
        var urls = config.urls;

        if (!config._heatmapLegendSelected) config._heatmapLegendSelected = {};

        function handler(evt) {
            if (!evt || !evt.selected) return;
            var isG = evt.name && evt.name.indexOf('__g_') === 0;
            var isS = evt.name && evt.name.indexOf('__s_') === 0;
            if (!isG && !isS) return;
            // Merge into persistent map so click-to-show again works (evt.selected can be partial after rebuild)
            for (var k in evt.selected) {
                if (k.indexOf('__g_') === 0 || k.indexOf('__s_') === 0) {
                    config._heatmapLegendSelected[k] = evt.selected[k];
                }
            }
            var built = self.buildHeatmapData(originalStacked, config._heatmapLegendSelected);
            if (!built.categories.length || !built.yNames.length) {
                // All hidden on one axis — restore last toggle so user can recover
                if (evt.name) config._heatmapLegendSelected[evt.name] = true;
                built = self.buildHeatmapData(originalStacked, config._heatmapLegendSelected);
                if (!built.categories.length || !built.yNames.length) return;
            }
            var opt = self.getHeatmapChartOption(originalStacked, palette, labelField, urls, {
                originalStackedData: originalStacked,
                legendSelected: config._heatmapLegendSelected
            });
            chartInstance.setOption(opt, {
                notMerge: true,
                replaceMerge: ['series', 'xAxis', 'yAxis', 'grid', 'legend', 'visualMap']
            });
        }

        chartInstance.off('legendselectchanged');
        chartInstance.on('legendselectchanged', handler);
    },

    attachRadarLegendHandler: function(chartInstance, config) {
        if (!chartInstance || !config || config.type !== 'radar' || !config.stackedData ||
            !config.stackedData.categories || !config.stackedData.series || config.stackedData.series.length === 0) {
            return;
        }
        var self = this;
        var originalStacked = config.stackedData;
        var palette = this.defaultColors;
        var labelField = config.labelField || '';

        if (!config._radarLegendSelected) config._radarLegendSelected = {};

        function handler(evt) {
            if (!evt || !evt.selected) return;
            var isG = evt.name && evt.name.indexOf('__g_') === 0;
            var isS = evt.name && evt.name.indexOf('__s_') === 0;
            if (!isG && !isS) return;
            for (var k in evt.selected) {
                if (k.indexOf('__g_') === 0 || k.indexOf('__s_') === 0) {
                    config._radarLegendSelected[k] = evt.selected[k];
                }
            }
            var built = self.buildRadarFromStacked(originalStacked, palette, config._radarLegendSelected);
            if (!built.indicator.length || !built.radarData.length) {
                if (evt.name) config._radarLegendSelected[evt.name] = true;
                built = self.buildRadarFromStacked(originalStacked, palette, config._radarLegendSelected);
                if (!built.indicator.length || !built.radarData.length) return;
            }
            var opt = self.getRadarChartOptionFromStacked(originalStacked, palette, labelField, config.urls, {
                originalStackedData: originalStacked,
                legendSelected: config._radarLegendSelected
            });
            chartInstance.setOption(opt, {
                notMerge: true,
                replaceMerge: ['series', 'radar', 'legend', 'grid', 'xAxis', 'yAxis']
            });
        }

        chartInstance.off('legendselectchanged');
        chartInstance.on('legendselectchanged', handler);
    },

    attachStackedDualLegendHandler: function(chartInstance, config) {
        if (!chartInstance || !config || !config.stackedData ||
            !config.stackedData.categories || !config.stackedData.series || config.stackedData.series.length === 0) {
            return;
        }
        var type = (config.type || '').toLowerCase();
        if (type !== 'stacked_vertical' && type !== 'stacked_horizontal') return;
        var self = this;
        var originalStacked = config.stackedData;
        var palette = this.defaultColors;
        var labelField = config.labelField || '';

        function handler(evt) {
            if (!evt || !evt.selected) return;
            var toggledCategory = evt.name && evt.name.indexOf('__g_') === 0;
            if (!toggledCategory) return;
            var filtered = self.filterStackedDataByCategories(originalStacked, evt.selected);
            if (!filtered.categories || filtered.categories.length === 0) return;
            var opts = { originalStackedData: originalStacked, legendSelected: evt.selected };
            var opt = type === 'stacked_horizontal'
                ? self.getStackedHorizontalChartOption(filtered, palette, labelField, config.urls, opts)
                : self.getStackedVerticalChartOption(filtered, palette, labelField, config.urls, opts);
            chartInstance.setOption(opt, {
                notMerge: true,
                replaceMerge: ['series', 'xAxis', 'yAxis', 'grid', 'legend']
            });
        }

        chartInstance.off('legendselectchanged');
        chartInstance.on('legendselectchanged', handler);
    },

    attachClickHandler: function(chartInstance, urls, config) {
        if (config && config.type === 'treemap') {
            this.attachTreemapLegendHandler(chartInstance, config);
        }
        if (config && config.type === 'sankey') {
            this.attachSankeyLegendHandler(chartInstance, config);
        }
        if (config && (config.type === 'stacked_vertical' || config.type === 'stacked_horizontal')) {
            this.attachStackedDualLegendHandler(chartInstance, config);
        }
        if (config && config.type === 'heatmap') {
            this.attachHeatmapLegendHandler(chartInstance, config);
        }
        if (config && config.type === 'radar' && config.stackedData &&
            config.stackedData.categories && config.stackedData.series && config.stackedData.series.length > 0) {
            this.attachRadarLegendHandler(chartInstance, config);
        }
        if (!urls || urls.length === 0) return;

        chartInstance.on('click', function(params) {
            let targetUrl = null;

            // Sankey: prefer edge-level URL (two-dimensional filter)
            if (config && config.type === 'sankey' && params.seriesType === 'sankey') {
                if (params.dataType === 'edge' && params.data && params.data.url && params.data.url !== '#') {
                    targetUrl = params.data.url;
                } else if (params.dataType === 'node' && params.name && config.stackedData && Array.isArray(config.stackedData.categories)) {
                    // Left-side node click falls back to primary-dimension URL
                    const idx = config.stackedData.categories.indexOf(params.name);
                    if (idx >= 0 && idx < urls.length && urls[idx] && urls[idx] !== '#') {
                        targetUrl = urls[idx];
                    }
                }
            } else if (params.seriesType === 'heatmap' && Array.isArray(params.data) && params.data.length >= 1) {
                if (params.data.length >= 4 && params.data[3] && params.data[3] !== '#') {
                    targetUrl = params.data[3];
                } else if (params.data[0] != null && urls[params.data[0]] && urls[params.data[0]] !== '#') {
                    targetUrl = urls[params.data[0]];
                }
            } else if (params.data && params.data.url) {
                targetUrl = params.data.url;
            }
            else if (params.seriesIndex !== undefined && params.seriesIndex < urls.length) {
                targetUrl = urls[params.seriesIndex];
            }
            else if (params.dataIndex !== undefined && params.dataIndex < urls.length) {
                targetUrl = urls[params.dataIndex];
            }

            if (targetUrl && targetUrl !== '#') {
                if (typeof htmx !== 'undefined') {
                    const tempLink = document.createElement('a');
                    tempLink.href = targetUrl;
                    tempLink.setAttribute('hx-get', targetUrl);
                    tempLink.setAttribute('hx-target', '#mainContent');
                    tempLink.setAttribute('hx-swap', 'outerHTML');
                    tempLink.setAttribute('hx-push-url', 'true');
                    tempLink.setAttribute('hx-select', '#mainContent');
                    tempLink.setAttribute('hx-select-oob', '#sideMenuContainer');

                    htmx.process(tempLink);
                    tempLink.click();
                } else {
                    window.location.href = targetUrl;
                }
            }
        });

        chartInstance.on('mouseover', function(params) {
            let hasUrl = false;

            if (params.seriesType === 'heatmap' && Array.isArray(params.data) && urls && urls.length > 0) {
                if (params.data[0] != null && params.data[0] < urls.length && urls[params.data[0]] && urls[params.data[0]] !== '#') {
                    hasUrl = true;
                }
            } else if (params.data && params.data.url && params.data.url !== '#') {
                hasUrl = true;
            } else if (urls && (params.dataIndex < urls.length || params.seriesIndex < urls.length)) {
                hasUrl = true;
            }

            if (hasUrl) {
                chartInstance.getDom().style.cursor = 'pointer';
            }
        });

        chartInstance.on('mouseout', function() {
            chartInstance.getDom().style.cursor = 'default';
        });
    },

    refreshChartTheme: function(chartInstance, config) {
        if (!chartInstance) return;
        try {
            const dom = chartInstance.getDom && chartInstance.getDom();
            if (dom && !document.body.contains(dom)) return; // Chart no longer in DOM (e.g. navigated away)
        } catch (e) { return; }

        const option = this.getChartOption(config);

        chartInstance.setOption(option, {
            notMerge: true,
            replaceMerge: ['series', 'xAxis', 'yAxis'],
            lazyUpdate: false
        });
    },

    formatNumber: function(num, decimals = 0) {
        if (num === null || num === undefined) return '0';
        const factor = Math.pow(10, decimals);
        const formatted = Math.round(num * factor) / factor;
        return formatted.toLocaleString();
    },

    getDynamicColors: function(dataLength) {
        const colors = [...this.defaultColors];
        while (colors.length < dataLength) {
            const hue = (colors.length * 137.5) % 360;
            colors.push(`hsl(${hue}, 70%, 60%)`);
        }
        return colors.slice(0, dataLength);
    },

    exportChart: function(chartInstance, filename = 'chart', format = 'png') {
        if (!chartInstance) return;

        const url = chartInstance.getDataURL({
            pixelRatio: 2,
            backgroundColor: '#fff',
            excludeComponents: ['toolbox']
        });

        const link = document.createElement('a');
        link.download = `${filename}.${format}`;
        link.href = url;
        link.click();
    },


    getChartInstanceByDomId: function(chartDomId) {
        if (!chartDomId) return null;
        var dom = document.getElementById(chartDomId);
        if (dom && typeof echarts !== 'undefined' && echarts.getInstanceByDom) {
            var inst = echarts.getInstanceByDom(dom);
            if (inst && !inst.isDisposed()) return inst;
        }
        if (window.chartInstances) {
            var key = 'horilla-chart-view-' + chartDomId;
            if (window.chartInstances[key] && window.chartInstances[key].instance) {
                var i = window.chartInstances[key].instance;
                if (i && !i.isDisposed()) return i;
            }
        }
        if (chartDomId.indexOf('chart-') === 0) {
            var pk = chartDomId.split('-')[1];
            if (pk && window['reportChartInstance_' + pk]) {
                var r = window['reportChartInstance_' + pk];
                if (r && !r.isDisposed()) return r;
            }
        }
        return null;
    },


    exportChartAsPDF: function(chartDomId, filename) {
        try {
            if (!window.jspdf || !window.jspdf.jsPDF) {
                console.error('jsPDF library is not loaded.');
                if (typeof alert !== 'undefined') {
                    alert('Failed to export PDF: jsPDF library is not loaded.');
                }
                return;
            }
            var chartInstance = this.getChartInstanceByDomId(chartDomId);
            if (!chartInstance) {
                console.error('Chart instance not found for id:', chartDomId);
                if (typeof alert !== 'undefined') {
                    alert('Failed to export PDF: Chart instance not available.');
                }
                return;
            }
            chartInstance.resize();
            var imgData = chartInstance.getDataURL({
                pixelRatio: 2,
                backgroundColor: '#fff',
                excludeComponents: ['toolbox']
            });
            if (!imgData) {
                console.error('Failed to generate chart image data.');
                if (typeof alert !== 'undefined') {
                    alert('Failed to export PDF: Could not generate chart image.');
                }
                return;
            }
            var jsPDF = window.jspdf.jsPDF;
            var pdf = new jsPDF({
                orientation: 'landscape',
                unit: 'px',
                format: [800, 400]
            });
            var imgProps = pdf.getImageProperties(imgData);
            var pdfWidth = pdf.internal.pageSize.getWidth();
            var pdfHeight = pdf.internal.pageSize.getHeight();
            var imgWidth = 700;
            var imgHeight = (imgProps.height * imgWidth) / imgProps.width;
            var x = (pdfWidth - imgWidth) / 2;
            var y = (pdfHeight - imgHeight) / 2;
            pdf.addImage(imgData, 'PNG', x, y, imgWidth, imgHeight);
            pdf.save((filename || 'chart') + '.pdf');
        } catch (error) {
            console.error('Error exporting chart as PDF:', error);
            if (typeof alert !== 'undefined') {
                alert('Failed to export PDF: An error occurred.');
            }
        }
    }
};


if (typeof window !== 'undefined') {
    window.exportChartAsPDF = function(chartDomId, filename) {
        if (EChartsConfig && typeof EChartsConfig.exportChartAsPDF === 'function') {
            return EChartsConfig.exportChartAsPDF(chartDomId, filename);
        }
    };
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = EChartsConfig;
}

// Track the latest pointer position so radar tooltips can show only the hovered point
document.addEventListener('mousemove', function(e) { EChartsConfig._lastPointer = e; }, true);
