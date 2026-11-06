(function () {
    function getPrimaryColor() {
        /* Read the computed color from an existing primary-colored element in the DOM
           (the pivot table header always has text-primary-600 applied by Tailwind) */
        var header = document.querySelector('#pivot-table-wrap thead th');
        if (header) {
            return getComputedStyle(header).color;
        }
        /* Fallback: create a temporary text-primary-600 element */
        var tmp = document.createElement('div');
        tmp.className = 'text-primary-600';
        tmp.style.cssText = 'position:absolute;width:0;height:0;visibility:hidden';
        document.body.appendChild(tmp);
        var color = getComputedStyle(tmp).color;
        document.body.removeChild(tmp);
        return color;
    }

    function applyActiveStyle(cell, primaryColor) {
        cell.style.outline = '1px solid ' + primaryColor;
        cell.style.outlineOffset = '-2px';
        cell.style.color = primaryColor;
        cell.style.fontWeight = '600';
    }

    function clearActiveStyle(cell) {
        cell.style.outline = '';
        cell.style.outlineOffset = '';
        cell.style.color = '';
        cell.style.fontWeight = '';
    }

    // True when the cell sits in an aggregate column: its column value equals one of the aggregate names
    function isAggregateCell(cell) {
        try {
            var q = new URL(cell.getAttribute('hx-get'), window.location.origin).searchParams;
            var names = q.getAll('aggregate');
            if (!names.length) return false;
            return ['col', 'col1', 'col2'].some(function (k) {
                var v = q.get(k);
                return v && names.indexOf(v.split('||')[0]) > -1;
            });
        } catch (e) { return false; }
    }

    function initPivotCellTracking() {
        var pivotWrap = document.getElementById('pivot-table-wrap');
        if (!pivotWrap || pivotWrap._pivotTracking) return;
        pivotWrap._pivotTracking = true;
        pivotWrap.querySelectorAll('[hx-target="#details-table"]').forEach(function (c) {
            if (isAggregateCell(c)) c.style.cursor = 'default';
        });

        var badge = document.getElementById('pivot-filter-badge');
        var badgeLabel = document.getElementById('pivot-filter-badge-label');
        var clearBtn = document.getElementById('pivot-filter-clear');
        var activeCell = null;

        function clearActive() {
            if (activeCell) {
                clearActiveStyle(activeCell);
                activeCell = null;
            }
            if (badge) badge.classList.remove('visible');
        }

        pivotWrap.addEventListener('htmx:beforeRequest', function (evt) {
            var cell = evt.target;
            if (cell.getAttribute('hx-target') !== '#details-table') return;
            // Cells of an aggregate column (sum / avg / ...) are not drill-downs
            if (isAggregateCell(cell)) { evt.preventDefault(); return; }
            clearActive();
            var primaryColor = getPrimaryColor();
            applyActiveStyle(cell, primaryColor);
            activeCell = cell;

            if (badge && badgeLabel) {
                // Describe the cell by what it stands for (row / column values), not just its number
                var label = '';
                try {
                    var q = new URL(cell.getAttribute('hx-get'), window.location.origin).searchParams;
                    var parts = [];
                    ['row_group1', 'row_group2', 'row_group3', 'col', 'col1', 'col2'].forEach(function (k) {
                        var v = q.get(k);
                        if (v) parts.push(v.split('||')[0]);
                    });
                    label = parts.join(' · ');
                } catch (e) {}
                if (!label) {
                    var rowHead = cell.parentElement && cell.parentElement.firstElementChild;
                    label = (rowHead && rowHead !== cell && rowHead.innerText.trim()) || pivotWrap.getAttribute('data-all-label');
                }
                var count = cell.innerText.trim();
                badgeLabel.textContent = count ? label + ' (' + count + ')' : label;
                badge.classList.add('visible');
            }
        });

        if (clearBtn) {
            clearBtn.addEventListener('click', function () {
                clearActive();
                var resetUrl = pivotWrap.getAttribute('data-reset-url');
                if (resetUrl) {
                    htmx.ajax('GET', resetUrl, { target: '#details-table', swap: 'innerHTML' });
                }
            });
        }
    }

    if (!window.reportPivotTrackingBound) {
        window.reportPivotTrackingBound = true;
        document.addEventListener('DOMContentLoaded', initPivotCellTracking);
        document.addEventListener('htmx:afterSettle', initPivotCellTracking);
    }
    initPivotCellTracking();
})();
