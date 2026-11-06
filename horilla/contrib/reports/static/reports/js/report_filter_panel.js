// Open/close the floating panel (same behaviour as the list filter panel).
window.toggleReportFilterPanel = function (open) {
    var p = document.getElementById("filterpanel");
    if (!p) return;
    var show = (typeof open === "boolean") ? open : p.classList.contains("hidden");
    if (show) {
        p.classList.remove("hidden");
        void p.offsetHeight;
        p.classList.add("visible");
        setTimeout(function () {
            $(p).find("select.js-example-basic-single").each(function () {
                var $s = $(this);
                if ($s.hasClass("select2-hidden-accessible")) { $s.select2("destroy"); }
                $s.select2({ width: "100%" });
            });
        }, 50);
    } else {
        p.classList.remove("visible");
        setTimeout(function () { p.classList.add("hidden"); }, 300);
    }
};
// Remove a row; the row that becomes first must not show AND/OR.
window.removeReportFilterRow = function (btn) {
    var row = btn.closest(".rf-row");
    var rows = document.getElementById("rf-rows");
    if (row) row.remove();
    var first = rows && rows.querySelector(".rf-row");
    var closeBtn = first && first.querySelector(":scope > button");
    if (closeBtn) closeBtn.remove();  // the first row cannot be removed
    var box = first && first.querySelector(":scope > .w-20");
    if (box) {
        var sel = box.querySelector("select");
        var hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = sel ? sel.name : "";
        hidden.value = "and";
        box.replaceWith(hidden);
    }
};
// The global script only wires drag / resize / expand-shrink for panels present at
// page load; this panel arrives later through htmx, so wire it here.
var filterPanelEl = document.getElementById("filterpanel");
if (filterPanelEl && !filterPanelEl.dataset.panelInit) setTimeout(function () {
    filterPanelEl.dataset.panelInit = "true";
    if (typeof initFilterPanelDrag === "function") initFilterPanelDrag();
    if (typeof initFilterPanelResize === "function") initFilterPanelResize();
    if (typeof initFilterPanelSizeControls === "function") initFilterPanelSizeControls();
}, 0);
// Show only the value widget that fits the chosen operator.
(function () {
    var noValue = ["isnull", "isnotnull", "today", "yesterday", "this_week", "this_month", "this_year", "this_fiscal_period", "this_fiscal_quarter", "this_fiscal_year"];
    $(document).off("change.reportFilter").on("change.reportFilter", "#report-filter-form .report-filter-operator", function () {
        var op = $(this).val();
        var box = $(this).closest(".rf-row").find(".report-filter-values");
        var kind = op === "between" ? "between" : (noValue.indexOf(op) > -1 ? "none" : "value");
        box.children("[data-section]").each(function () {
            $(this).toggle($(this).data("section") === kind);
        });
    });
})();
