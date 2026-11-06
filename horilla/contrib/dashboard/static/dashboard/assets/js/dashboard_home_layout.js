/**
 * Custom dashboard home view: layout (reorder) editing and chart export.
 *
 * Loaded by home/home.html when is_default_home is false. The script tag
 * carries the translated failure message in data-reset-failed-message. Reorder
 * and reset URLs/CSRF token are read from the #dashboard-detail-view element,
 * as before. Re-runs on every HTMX swap of the home view, like the inline
 * script it replaces.
 */
(function () {
  var script = document.currentScript;
  var resetFailedMessage =
    (script && script.dataset.resetFailedMessage) ||
    "Failed to reset layout to default.";

  var sortableKpis = null;
  var sortableComponents = null;
  var editMode = false;

  function toggleEditMode() {
    editMode = !editMode;
    var $view = $("#dashboard-detail-view");
    if (editMode) {
      $("#editLayoutBtn").addClass("hidden");
      $("#editModeActions").removeClass("hidden").addClass("flex");
      $("#dateRangeFilterContainer").addClass("hidden");
      $view.addClass("edit-mode");
      $view.find(".edit-drag-handle").removeClass("hidden");
      initDragSortables();
    } else {
      $("#editLayoutBtn").removeClass("hidden");
      $("#editModeActions").addClass("hidden").removeClass("flex");
      $("#dateRangeFilterContainer").removeClass("hidden");
      $view.removeClass("edit-mode");
      $view.find(".edit-drag-handle").addClass("hidden");
      destroyDragSortables();
    }
  }

  function initDragSortables() {
    if (typeof Sortable === "undefined") return;
    var kpiList = document.getElementById("reorderable-kpis");
    var compList = document.getElementById("reorderable-components");
    var opts = window.getHorillaDashboardSortableOptions
      ? window.getHorillaDashboardSortableOptions({ dataIdAttr: "data-component-id" })
      : { handle: ".edit-drag-handle", animation: 150, ghostClass: "opacity-50", dataIdAttr: "data-component-id" };
    if (kpiList && !sortableKpis) {
      if (window.prepareHorillaDashboardSortableContainer) {
        window.prepareHorillaDashboardSortableContainer(kpiList);
      }
      sortableKpis = Sortable.create(kpiList, opts);
    }
    if (compList && !sortableComponents) {
      if (window.prepareHorillaDashboardSortableContainer) {
        window.prepareHorillaDashboardSortableContainer(compList);
      }
      sortableComponents = Sortable.create(compList, opts);
    }
  }

  function destroyDragSortables(restoreOriginal) {
    if (sortableKpis) {
      if (window.resetHorillaDashboardSortableContainer) {
        window.resetHorillaDashboardSortableContainer(
          document.getElementById("reorderable-kpis"),
          restoreOriginal
        );
      }
      sortableKpis.destroy();
      sortableKpis = null;
    }
    if (sortableComponents) {
      if (window.resetHorillaDashboardSortableContainer) {
        window.resetHorillaDashboardSortableContainer(
          document.getElementById("reorderable-components"),
          restoreOriginal
        );
      }
      sortableComponents.destroy();
      sortableComponents = null;
    }
  }

  function saveDragOrder() {
    var $view = $("#dashboard-detail-view");
    var url = $view.data("reorder-url");
    var csrfToken = $view.data("csrf-token");
    if (!url) return;

    function postOrder(reorderType, order) {
      var formData = new FormData();
      formData.append("csrfmiddlewaretoken", csrfToken);
      formData.append("reorder_type", reorderType);
      order.forEach(function(id) { formData.append("component_order", id); });
      return $.ajax({
        url: url,
        method: "POST",
        data: formData,
        processData: false,
        contentType: false,
        headers: { "X-CSRFToken": csrfToken }
      });
    }

    var kpiList = document.getElementById("reorderable-kpis");
    var compList = document.getElementById("reorderable-components");
    var kpiIds = window.collectHorillaDashboardSortableOrder
      ? window.collectHorillaDashboardSortableOrder(kpiList, sortableKpis)
      : [];
    var compIds = window.collectHorillaDashboardSortableOrder
      ? window.collectHorillaDashboardSortableOrder(compList, sortableComponents)
      : [];

    if (!kpiIds.length && !compIds.length) {
      toggleEditMode();
      return;
    }
    $("#saveOrderBtn").prop("disabled", true);
    var p = $.Deferred().resolve();
    if (kpiIds.length) p = p.then(function() { return postOrder("kpi", kpiIds); });
    if (compIds.length) p = p.then(function() { return postOrder("components", compIds); });
    p.done(function() {
      editMode = false;
      destroyDragSortables(false);
      window.location.reload();
    }).fail(function() {
      destroyDragSortables(true);
      window.location.reload();
    }).always(function() {
      $("#saveOrderBtn").prop("disabled", false);
    });
  }

  function resetDashboardToDefault() {
    var $view = $("#dashboard-detail-view");
    var url = $view.data("reset-order-url");
    var csrfToken = $view.data("csrf-token");
    if (!url) return;
    $("#setToDefaultBtn").prop("disabled", true);
    $.ajax({
      url: url,
      method: "POST",
      data: { csrfmiddlewaretoken: csrfToken },
      headers: { "X-CSRFToken": csrfToken },
      success: function() {
        toggleEditMode();
        window.location.reload();
      },
      error: function() {
        alert(resetFailedMessage);
      },
      complete: function() {
        $("#setToDefaultBtn").prop("disabled", false);
      }
    });
  }

  window.toggleEditMode = toggleEditMode;
  window.saveDragOrder = saveDragOrder;
  window.resetDashboardToDefault = resetDashboardToDefault;

  function exportChart(chartId, chartName, format) {
    const $chartDom = $("#" + chartId);

    if ($chartDom.length === 0) {
      console.error("Chart DOM element not found for ID:", chartId);
      alert("Failed to export chart: Chart element not found.");
      return;
    }

    if (
      typeof EChartsConfig === "undefined" ||
      typeof echarts === "undefined"
    ) {
      console.error("EChartsConfig or echarts not available");
      alert("Failed to export chart: Required libraries are not available.");
      return;
    }

    const myChart = echarts.getInstanceByDom($chartDom[0]);

    if (myChart) {
      EChartsConfig.exportChart(myChart, chartName, format);
    } else {
      console.error("Chart instance not found for ID:", chartId);
      alert("Failed to export chart: Chart instance not found.");
    }
  }

  window.exportChart = exportChart;
})();
