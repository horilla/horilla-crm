/**
 * Default home dashboard: chart rendering and layout (reorder) editing.
 *
 * Loaded by home/home.html when is_default_home is true. The script tag
 * carries the endpoints and CSRF token:
 *   data-save-url, data-reset-url, data-csrf-token
 * Chart data comes from sibling elements with class "js-default-chart-data"
 * (data-chart-index, data-chart-type) wrapping a json_script block.
 * Re-runs on every HTMX swap of the home view, like the inline script it
 * replaces.
 */
(function () {
  var script = document.currentScript;
  var dataset = (script && script.dataset) || {};
  var DEFAULT_HOME_SAVE_URL = dataset.saveUrl || "";
  var DEFAULT_HOME_RESET_URL = dataset.resetUrl || "";
  var DEFAULT_HOME_CSRF_TOKEN = dataset.csrfToken || "";

  function initializeCharts() {
    document.querySelectorAll(".js-default-chart-data").forEach(function (holder) {
      var dataEl = holder.querySelector('script[type="application/json"]');
      if (!dataEl) return;
      var chartData;
      try {
        chartData = JSON.parse(dataEl.textContent);
      } catch (e) {
        return;
      }
      initializeDefaultChart(
        parseInt(holder.dataset.chartIndex, 10),
        chartData,
        holder.dataset.chartType
      );
    });
  }

  function initializeDefaultChart(chartIndex, chartData, chartType) {
    const chartDom = document.getElementById('default-chart-' + chartIndex);
    if (chartDom && typeof echarts !== 'undefined' && typeof EChartsConfig !== 'undefined') {
      var key = 'default-chart-' + chartIndex;
      if (window.chartInstances && window.chartInstances[key] && window.chartInstances[key].instance) {
        try { window.chartInstances[key].instance.dispose(); } catch (e) {}
      }
      const myChart = echarts.init(chartDom);

      const config = {
        type: chartType,
        labels: chartData.labels,
        data: chartData.data,
        labelField: chartData.labelField,
        colors: EChartsConfig.defaultColors,
        urls: chartData.urls || [],
        stackedData: chartData.stackedData,
        hasMultipleGroups: chartData.hasMultipleGroups
      };

      const option = EChartsConfig.getChartOption(config);
      myChart.setOption(option);

      if (chartData.urls && chartData.urls.length > 0) {
        EChartsConfig.attachClickHandler(myChart, chartData.urls);
      }

      if (typeof window.chartInstances === 'undefined') {
        window.chartInstances = {};
      }
      window.chartInstances[key] = { instance: myChart, config: config };

      setTimeout(function() { myChart.resize(); }, 350);

      window.addEventListener('resize', function() {
        myChart.resize();
      });
    }
  }

  initializeCharts();

  var sortableKpis = null, sortableChartsAndTables = null, defaultHomeEditMode = false;

  function toggleDefaultHomeEditMode() {
    defaultHomeEditMode = !defaultHomeEditMode;
    var $view = $('#default-home-view');
    if (defaultHomeEditMode) {
      $('#editLayoutBtn').addClass('hidden');
      $('#editModeActions').removeClass('hidden').addClass('flex');
      $('#dateRangeFilterContainer').addClass('hidden');
      $view.addClass('edit-mode');
      $view.find('.edit-drag-handle').removeClass('hidden');
      initDefaultHomeSortables();
    } else {
      $('#editLayoutBtn').removeClass('hidden');
      $('#editModeActions').addClass('hidden').removeClass('flex');
      $('#dateRangeFilterContainer').removeClass('hidden');
      $view.removeClass('edit-mode');
      $view.find('.edit-drag-handle').addClass('hidden');
      destroyDefaultHomeSortables();
    }
  }

  function initDefaultHomeSortables() {
    if (typeof Sortable === 'undefined') return;
    var opts = window.getHorillaDashboardSortableOptions
      ? window.getHorillaDashboardSortableOptions({ dataIdAttr: "data-id" })
      : { handle: '.edit-drag-handle', animation: 150, ghostClass: 'opacity-50', dataIdAttr: 'data-id' };
    var kpiList = document.getElementById('default-home-kpis');
    var chartsList = document.getElementById('default-home-charts-and-tables');
    if (kpiList && !sortableKpis) {
      if (window.prepareHorillaDashboardSortableContainer) {
        window.prepareHorillaDashboardSortableContainer(kpiList);
      }
      sortableKpis = Sortable.create(kpiList, opts);
    }
    if (chartsList && !sortableChartsAndTables) {
      if (window.prepareHorillaDashboardSortableContainer) {
        window.prepareHorillaDashboardSortableContainer(chartsList);
      }
      sortableChartsAndTables = Sortable.create(chartsList, opts);
    }
  }

  function destroyDefaultHomeSortables(restoreOriginal) {
    if (sortableKpis) {
      if (window.resetHorillaDashboardSortableContainer) {
        window.resetHorillaDashboardSortableContainer(
          document.getElementById('default-home-kpis'),
          restoreOriginal
        );
      }
      sortableKpis.destroy();
      sortableKpis = null;
    }
    if (sortableChartsAndTables) {
      if (window.resetHorillaDashboardSortableContainer) {
        window.resetHorillaDashboardSortableContainer(
          document.getElementById('default-home-charts-and-tables'),
          restoreOriginal
        );
      }
      sortableChartsAndTables.destroy();
      sortableChartsAndTables = null;
    }
  }

  function saveDefaultHomeOrder() {
    var kpiEl = document.getElementById('default-home-kpis');
    var mixedEl = document.getElementById('default-home-charts-and-tables');
    var order = {
      kpi: window.collectHorillaDashboardSortableOrder
        ? window.collectHorillaDashboardSortableOrder(kpiEl, sortableKpis)
        : [],
      chartsAndTables: window.collectHorillaDashboardSortableOrder
        ? window.collectHorillaDashboardSortableOrder(mixedEl, sortableChartsAndTables)
        : [],
    };
    $.ajax({
      url: DEFAULT_HOME_SAVE_URL,
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ order: order }),
      headers: { 'X-CSRFToken': DEFAULT_HOME_CSRF_TOKEN },
    }).done(function(res) {
      if (res && res.success) {
        $('#setToDefaultBtn').toggleClass('hidden', !res.is_custom);
        defaultHomeEditMode = false;
        $('#editLayoutBtn').removeClass('hidden');
        $('#editModeActions').addClass('hidden').removeClass('flex');
        $('#dateRangeFilterContainer').removeClass('hidden');
        $('#default-home-view').removeClass('edit-mode').find('.edit-drag-handle').addClass('hidden');
        destroyDefaultHomeSortables(false);
      } else {
        destroyDefaultHomeSortables(true);
        applyDefaultHomeOrder(res && res.order);
      }
      $('#reloadMessagesButton').click();
    }).fail(function() {
      destroyDefaultHomeSortables(true);
      $('#reloadMessagesButton').click();
    });
  }

  function applyDefaultHomeOrder(order) {
    if (order && order.kpi && order.chartsAndTables) {
      reorderElementsByIdList('default-home-kpis', order.kpi);
      reorderElementsByIdList('default-home-charts-and-tables', order.chartsAndTables);
    } else {
      window.location.reload();
    }
  }

  function reorderElementsByIdList(containerId, idList) {
    var container = document.getElementById(containerId);
    if (!container || !idList.length) return;
    var byId = {};
    container.querySelectorAll('[data-id]').forEach(function(n) {
      byId[n.getAttribute('data-id')] = n;
    });
    idList.forEach(function(id) {
      if (byId[id]) container.appendChild(byId[id]);
    });
  }

  function resetDefaultHomeToDefault() {
    $('#setToDefaultBtn').prop('disabled', true);
    $.ajax({
      url: DEFAULT_HOME_RESET_URL,
      method: 'POST',
      headers: { 'X-CSRFToken': DEFAULT_HOME_CSRF_TOKEN },
      success: function() {
        toggleDefaultHomeEditMode();
        window.location.reload();
      },
      complete: function() {
        $('#setToDefaultBtn').prop('disabled', false);
      },
      error: function() {
        window.location.reload();
      },
    });
  }

  // Called from inline onclick handlers in home/home.html
  window.initializeDefaultChart = initializeDefaultChart;
  window.initializeCharts = initializeCharts;
  window.toggleDefaultHomeEditMode = toggleDefaultHomeEditMode;
  window.saveDefaultHomeOrder = saveDefaultHomeOrder;
  window.resetDefaultHomeToDefault = resetDefaultHomeToDefault;
})();
