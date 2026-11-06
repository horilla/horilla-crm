// View tabs (Chart / Pivot / Details).
(function () {
    var reportConfig = document.getElementById('report-detail-config');
    if (!reportConfig) return;
    function apply() {
        var sec = document.querySelector('.sec1');
        if (!sec) return;
        var present = {};
        document.querySelectorAll('[data-rpt-section]').forEach(function (el) { present[el.getAttribute('data-rpt-section')] = true; });
        var view = window.reportView;
        if (!present[view]) view = present.pivot ? 'pivot' : (present.detail ? 'detail' : 'chart');
        window.reportView = view;
        document.querySelectorAll('[data-rpt-section]').forEach(function (el) {
            el.classList.toggle('rpt-active', el.getAttribute('data-rpt-section') === view);
        });
        document.querySelectorAll('.rpt-tab').forEach(function (t) {
            var on = t.getAttribute('data-view') === view;
            t.setAttribute('aria-selected', on ? 'true' : 'false');
            t.style.background = on ? '#E54F38' : 'transparent';
            t.style.color = on ? '#fff' : '#3b4150';
        });
        var inst = window['reportChartInstance_' + reportConfig.dataset.reportId];
        if (inst && inst.resize) setTimeout(function () { inst.resize(); }, 60);
    }
    if (!window.reportCollapseBound) {
        window.reportCollapseBound = true;
        document.addEventListener('click', function (e) {
            var tab = e.target.closest('.rpt-tab');
            if (tab) { window.reportView = tab.getAttribute('data-view'); window.reportApplyFocus(); return; }
            var chip = e.target.closest('[data-edit-tab]');
            if (chip) {
                // Open the edit panel on the clicked tab (Columns / Grouping / Filter).
                var name = chip.getAttribute('data-edit-tab');
                try { sessionStorage.setItem('activeReportTab', name); } catch (err) {}
                var tabBtn = document.querySelector('#panel .tab-button[data-tab-name="' + name + '"]');
                if (tabBtn) { tabBtn.click(); return; }
                var edit = document.getElementById('toggleBtn');
                if (edit) edit.click();
            }
        });
        document.body.addEventListener('htmx:afterSettle', function () { window.reportApplyFocus(); });
        // Clicking a pivot cell loads its rows into the detail table: show the Details tab.
        document.body.addEventListener('htmx:afterSwap', function (e) {
            var t = e.detail && e.detail.target;
            if (t && t.id === 'details-table' && document.querySelector('[data-rpt-section="detail"]')) {
                window.reportView = 'detail';
                window.reportApplyFocus();
            }
        });
    }
    window.reportApplyFocus = apply;
    apply();
})();
