(function() {
  var box = document.getElementById('contentModalBox');
  if (box) {
    box.classList.add('!max-w-[90vw]', '!md:max-w-[800px]', '!lg:max-w-[1100px]');
  }
})();

(function() {
  var chartDataEl = document.getElementById('forecast-modal-chart-data');
  if (!chartDataEl || typeof EChartsConfig === 'undefined' || typeof echarts === 'undefined') return;
  var labels = document.getElementById('forecast-modal-chart-labels').dataset;
  var payload = JSON.parse(chartDataEl.textContent);
  var categories = payload.categories || [];
  var fva = payload.forecast_vs_actual || {};
  var trend = payload.trend || {};
  var stackedCategory = payload.stacked_category_series || [];
  var colors = EChartsConfig.defaultColors;
  var chartInstances = [];
  var resizeObserver = null;

  function initEChart(domId, option) {
    var dom = document.getElementById(domId);
    if (!dom) return null;

    // Ensure container can shrink/expand inside flex/grid
    dom.style.width = '100%';

    // If modal is opened multiple times, dispose old instances on same DOM
    try {
      var existing = echarts.getInstanceByDom(dom);
      if (existing) existing.dispose();
    } catch (e) {}

    var inst = echarts.init(dom);
    inst.setOption(option, { notMerge: true });
    return inst;
  }

  function initColumnChart() {
    if (!fva.categories || fva.categories.length === 0) return null;
    var opt = {
      ...EChartsConfig.getAnimationConfig(),
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { ...EChartsConfig.getLegendConfig(), show: true },
      grid: EChartsConfig.getGridConfig(),
      xAxis: {
        type: 'category',
        data: fva.categories,
        axisLabel: { ...EChartsConfig.getAxisLabelStyle(), rotate: fva.categories.some(function(l) { return String(l).length > 6; }) ? 35 : 0 },
        axisLine: EChartsConfig.getAxisLineStyle()
      },
      yAxis: {
        type: 'value',
        axisLabel: EChartsConfig.getAxisLabelStyle(),
        axisLine: EChartsConfig.getAxisLineStyle(),
        splitLine: EChartsConfig.getSplitLineStyle()
      },
      color: [colors[0], colors[1]],
      series: [
        { name: labels.target, type: 'bar', data: fva.target || [], barWidth: '35%', itemStyle: { borderRadius: [4, 4, 0, 0] } },
        { name: labels.actual, type: 'bar', data: fva.actual || [], barWidth: '35%', itemStyle: { borderRadius: [4, 4, 0, 0] } }
      ]
    };
    return initEChart('forecast-modal-chart-column', opt);
  }

  function initLineChart() {
    if (!trend.categories || trend.categories.length === 0) return null;
    var opt = {
      ...EChartsConfig.getAnimationConfig(),
      tooltip: { trigger: 'axis' },
      legend: { ...EChartsConfig.getLegendConfig(), show: true },
      grid: EChartsConfig.getGridConfig(),
      xAxis: {
        type: 'category',
        data: trend.categories,
        boundaryGap: false,
        axisLabel: { ...EChartsConfig.getAxisLabelStyle(), rotate: trend.categories.some(function(l) { return String(l).length > 6; }) ? 35 : 0 },
        axisLine: EChartsConfig.getAxisLineStyle()
      },
      yAxis: {
        type: 'value',
        axisLabel: EChartsConfig.getAxisLabelStyle(),
        axisLine: EChartsConfig.getAxisLineStyle(),
        splitLine: EChartsConfig.getSplitLineStyle()
      },
      color: [colors[0], colors[1]],
      series: [
        { name: labels.target, type: 'line', data: trend.target || [], smooth: true, symbol: 'circle', symbolSize: 6 },
        { name: labels.actual, type: 'line', data: trend.actual || [], smooth: true, symbol: 'circle', symbolSize: 6 }
      ]
    };
    return initEChart('forecast-modal-chart-line', opt);
  }

  function initStackedChart() {
    if (categories.length === 0 || stackedCategory.length === 0) return null;
    var stackedData = { categories: categories, series: stackedCategory };
    var config = {
      type: 'stacked_vertical',
      labels: categories,
      data: stackedCategory[0] ? stackedCategory[0].data : [],
      colors: colors,
      labelField: labels.amount,
      stackedData: stackedData,
      hasMultipleGroups: true,
      urls: []
    };
    var option = EChartsConfig.getChartOption(config);
    var ch = initEChart('forecast-modal-chart-stacked', option);
    // Enable stacked dual-legend toggling (category legend) for this chart.
    if (ch && typeof EChartsConfig.attachStackedDualLegendHandler === 'function') {
      EChartsConfig.attachStackedDualLegendHandler(ch, config);
    }
    return ch;
  }

  var c1 = initColumnChart();
  var c2 = initLineChart();
  var c3 = initStackedChart();
  chartInstances = [c1, c2, c3].filter(Boolean);

  function resizeCharts() {
    chartInstances.forEach(function(ch) { if (ch) ch.resize(); });
  }

  // Resize when modal content box changes size (common in HTMX + modal transitions)
  try {
    var modalBox = document.getElementById('contentModalBox');
    if (modalBox && typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(function() { resizeCharts(); });
      resizeObserver.observe(modalBox);
    }
  } catch (e) {}

  window.addEventListener('resize', resizeCharts);
  // Run a couple times to catch transition/layout settling
  requestAnimationFrame(resizeCharts);
  setTimeout(resizeCharts, 150);
  setTimeout(resizeCharts, 450);
})();
