/**
 * Dashboard chart preview: renders a sample chart for the selected chart type.
 *
 * Loaded by chart/preview_chart.html. The script tag carries the chart type in
 * data-chart-type. Re-runs each time the preview fragment is swapped in by
 * HTMX, like the inline script it replaces.
 */
(function() {
  var script = document.currentScript;
  const sampleData = {
    "column": {
      "labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
      "data": [120, 200, 150, 80, 70, 110, 130],
      "labelField": "Sample Data"
    },
    "bar": {
      "labels": ["Category A", "Category B", "Category C", "Category D"],
      "data": [12, 19, 15, 17],
      "labelField": "Sample Data"
    },
    "pie": {
      "labels": ["Sample A", "Sample B", "Sample C", "Sample D"],
      "data": [30, 25, 25, 20],
      "labelField": "Sample Data"
    },
    "donut": {
      "labels": ["Sample 1", "Sample 2", "Sample 3"],
      "data": [40, 35, 25],
      "labelField": "Sample Data"
    },
    "line": {
      "labels": ["Week 1", "Week 2", "Week 3", "Week 4", "Week 5"],
      "data": [10, 25, 15, 30, 28],
      "labelField": "Sample Data"
    },
    "stacked_vertical": {
      "stackedData": {
        "categories": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "series": [
          {"name": "Series 1", "data": [10, 20, 15, 25, 30]},
          {"name": "Series 2", "data": [5, 10, 8, 12, 15]}
        ]
      },
      "labelField": "Sample Data",
      "hasMultipleGroups": true
    },
    "stacked_horizontal": {
      "stackedData": {
        "categories": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "series": [
          {"name": "Series 1", "data": [10, 20, 15, 25, 30]},
          {"name": "Series 2", "data": [5, 10, 8, 12, 15]}
        ]
      },
      "labelField": "Sample Data",
      "hasMultipleGroups": true
    },
    "funnel": {
      "labels": ["Stage 1", "Satge 2", "Stage 3", "Stage 4", "Stage 5"],
      "data": [100, 75, 50, 30, 20],
      "labelField": "Sample Data"
    },
    "scatter": {
      "labels": ["Point A", "Point B", "Point C", "Point D", "Point E"],
      "data": [10, 35, 22, 45, 30],
      "labelField": "Sample Scatter"
    },
    "heatmap": {
      "stackedData": {
        "categories": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "series": [
          { "name": "Group 1", "data": [5, 20, 15, 25, 30] },
          { "name": "Group 2", "data": [10, 15, 20, 18, 22] }
        ]
      },
      "labelField": "Sample Heatmap",
      "hasMultipleGroups": true
    },
    "treemap": {
      "labels": ["Segment A", "Segment B", "Segment C", "Segment D"],
      "data": [40, 25, 20, 15],
      "labelField": "Sample Treemap"
    },
    "area": {
      "labels": ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
      "data": [12, 18, 25, 20, 28, 32],
      "labelField": "Sample Area"
    },
    "sankey": {
      "stackedData": {
        "categories": ["Source A", "Source B", "Source C"],
        "series": [
          { "name": "Target X", "data": [20, 10, 5] },
          { "name": "Target Y", "data": [15, 25, 10] }
        ]
      },
      "labelField": "Sample Sankey",
      "hasMultipleGroups": true
    },
    "radar": {
      "stackedData": {
        "categories": ["Metric 1", "Metric 2", "Metric 3", "Metric 4", "Metric 5"],
        "series": [
          { "name": "Group A", "data": [60, 80, 70, 85, 75] },
          { "name": "Group B", "data": [55, 75, 65, 80, 70] }
        ]
      },
      "labelField": "Sample Radar",
      "hasMultipleGroups": true
    }
  };

  const chartType = (script && script.dataset.chartType) || "";
  const config = sampleData[chartType] ? { type: chartType, ...sampleData[chartType] } : null;

  const chartDom = document.getElementById('preview-chart-' + chartType);
  if (chartDom && config && typeof EChartsConfig !== 'undefined' && typeof echarts !== 'undefined') {
    const previewKey = 'preview-chart-' + chartType;
    if (window.chartInstances && window.chartInstances[previewKey]) {
      try { window.chartInstances[previewKey].instance.dispose(); } catch (e) {}
    }
    const myChart = echarts.init(chartDom);
    const option = EChartsConfig.getChartOption(config);
    myChart.setOption(option);
    if (typeof window.chartInstances === 'undefined') window.chartInstances = {};
    window.chartInstances[previewKey] = { instance: myChart, config: config };
  }
})();
