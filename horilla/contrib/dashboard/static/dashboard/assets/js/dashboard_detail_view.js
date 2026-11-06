/**
 * Dashboard detail view: select2 setup, layout (reorder) editing and chart
 * export (image and PDF).
 *
 * Loaded by dashboard_detail_view.html after jspdf.umd.min.js. Re-runs on every
 * HTMX swap of the view, like the inline script it replaces. Functions called
 * from inline onclick handlers are assigned to window explicitly.
 */
(function () {
  $(document).ready(function () {
    initializeSelect2();
    bindEventHandlers();
  });

  function initializeSelect2() {
    $("#exportFormat").select2({
      width: "100%",
      theme: "default",
    });

    $("select").on("select2:select", function (e) {
      this.dispatchEvent(new Event("change"));
    });
  }

  var sortableKpis = null;
  var sortableComponents = null;
  var editMode = false;

  function toggleEditMode() {
    editMode = !editMode;
    var $view = $("#dashboard-detail-view");
    if (editMode) {
      $("#editLayoutBtn").addClass("hidden");
      $("#editModeActions").removeClass("hidden").addClass("flex");
      $("#addComponentBtn").addClass("hidden");
      $view.addClass("edit-mode");
      $view.find(".edit-drag-handle").removeClass("hidden");
      initDragSortables();
    } else {
      $("#editLayoutBtn").removeClass("hidden");
      $("#editModeActions").addClass("hidden").removeClass("flex");
      $("#addComponentBtn").removeClass("hidden");
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


  window.toggleEditMode = toggleEditMode;
  window.saveDragOrder = saveDragOrder;

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

  // Dashboard-specific PDF export, similar to report_detail.html
  function exportDashboardChartAsPDF(componentId, filename) {
    try {
      if (!window.jspdf || !window.jspdf.jsPDF) {
        console.error('jsPDF library is not loaded.');
        alert('Failed to export PDF: jsPDF library is not loaded.');
        return;
      }

      var compKey = 'dashboard-component-' + componentId;
      var entry = window.chartInstances && window.chartInstances[compKey];

      if (!entry || !entry.instance || entry.instance.isDisposed()) {
        console.error('Chart instance not found or disposed for component ID:', componentId);
        alert('Failed to export PDF: Chart instance not available.');
        return;
      }

      var chartInstance = entry.instance;
      chartInstance.resize();

      var imgData = chartInstance.getDataURL({
        pixelRatio: 2,
        backgroundColor: '#fff',
        excludeComponents: ['toolbox']
      });

      if (!imgData) {
        console.error('Failed to generate chart image data.');
        alert('Failed to export PDF: Could not generate chart image.');
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
      pdf.save(filename + '.pdf');
    } catch (error) {
      console.error('Error exporting chart as PDF:', error);
      alert('Failed to export PDF: An error occurred.');
    }
  }

  window.exportChart = exportChart;
  window.exportDashboardChartAsPDF = exportDashboardChartAsPDF;
})();
