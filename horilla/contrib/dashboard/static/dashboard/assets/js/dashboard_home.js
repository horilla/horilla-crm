/**
 * Home page select2 setup.
 *
 * Loaded by home/home.html (after horilla_charts.js). Re-runs on every HTMX
 * swap of the home view, like the inline script it replaces.
 */
(function () {
  function initializeSelect2() {
    $("#exportFormat").select2({
      width: "100%",
      theme: "default",
    });

    $("select").on("select2:select", function () {
      this.dispatchEvent(new Event("change"));
    });
  }

  window.initializeSelect2 = initializeSelect2;

  $(document).ready(function () {
    initializeSelect2();
  });
})();
