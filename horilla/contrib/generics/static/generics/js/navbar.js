// Toggle the filter panel from the navbar filter button. Inside a tabbed view several
// #filterpanel / #filtercontainer elements may exist (one per loaded tab); only the one
// in the currently visible tab panel is relevant.
function toggleFilterPanel() {
    function getActive(id) {
        const all = document.querySelectorAll(id);
        if (all.length === 1) return all[0];
        for (const el of all) {
            const tabPanel = el.closest("[role='tabpanel']");
            if (!tabPanel || !tabPanel.classList.contains("hidden")) return el;
        }
        return all[0];
    }
    const filterPanel = getActive("#filterpanel");
    const filterContainer = getActive("#filtercontainer");
    if (!filterPanel || !filterContainer) return;
    const storageKey = "filterPanelVisible:" + window.location.pathname;

    if (filterPanel.classList.contains("hidden")) {
        filterPanel.classList.remove("hidden");
        filterContainer.classList.remove("hidden");
        void filterPanel.offsetHeight; // reflow
        filterPanel.classList.add("visible");
        filterContainer.classList.add("visible");
        // Opening clears any persisted 'closed' state so server defaults apply
        try { localStorage.removeItem(storageKey); } catch (e) {}
        // Reinitialize Select2 after the panel is visible so widths are computed correctly
        setTimeout(function () {
            filterPanel.querySelectorAll("select.js-example-basic-single").forEach(function (sel) {
                const $sel = $(sel);
                if ($sel.hasClass("select2-hidden-accessible")) {
                    $sel.select2("destroy");
                    $sel.removeData("select2-initialized");
                }
                $sel.select2({ width: "100%" });
            });
            // Paginated (ajax) selects need their ajax config and selection restored
            filterPanel.querySelectorAll("select.select2-pagination").forEach(function (sel) {
                const $sel = $(sel);
                if ($sel.hasClass("select2-hidden-accessible")) {
                    $sel.select2("destroy");
                    $sel.removeData("select2-initialized");
                }
            });
            initializeSelect2Pagination();
        }, 50);
    } else {
        filterPanel.classList.remove("visible");
        filterContainer.classList.remove("visible");
        try { localStorage.setItem(storageKey, "closed"); } catch (e) {}
        setTimeout(function () {
            filterPanel.classList.add("hidden");
        }, 300);
    }
}

/* ==========================================================================
   Navbar view type select
   ========================================================================== */
function syncViewTypeSelect(fallback) {
    const $select = $('select[name="view_type"]');
    if (!$select.length) return;
    const serverViewType = $select.attr("data-server-view-type");
    $select.val(serverViewType || fallback || "all");
    if ($select.hasClass("js-example-basic-single")) {
        if (!$select.data("select2")) {
            $select.select2({ width: "100%" });
        }
        $select.trigger("change.select2");
    }
}

$(document).ready(function () {
    if ($.fn.select2) {
        $(".js-example-basic-single").select2({ width: "100%" });
    }
    syncViewTypeSelect();
});

if (!window.__navbarViewTypeBound) {
    window.__navbarViewTypeBound = true;

    $(document).on("htmx:beforeSwap", function () {
        const $select = $('select[name="view_type"]');
        if ($select.length) {
            sessionStorage.setItem("currentViewType", $select.val());
        }
    });

    $(document).on("htmx:afterSwap", function () {
        syncViewTypeSelect(sessionStorage.getItem("currentViewType"));
    });
}
