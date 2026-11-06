(function () {
    function getFieldRow(selector) {
        var input = document.querySelector(selector);
        if (!input) return null;
        var el = input;
        for (var i = 0; i < 6; i++) {
            el = el.parentElement;
            if (!el) break;
            if (el.querySelector('label') && el.querySelector(selector)) return el;
        }
        return input.parentElement;
    }

    function applyVisibility() {
        var cb = document.getElementById('id_is_online');
        var online = cb && cb.checked;
        var providerRow = getFieldRow('#id_meeting_provider');
        if (providerRow) providerRow.style.display = online ? '' : 'none';
        var urlRow = getFieldRow('[data-online-field="true"]:not(#id_meeting_provider)');
        if (urlRow) urlRow.style.display = online ? '' : 'none';
    }

    window.toggleMeetingUrlField = function (cb) { applyVisibility(); };

    document.addEventListener('change', function(e) {
        if (e.target && e.target.id === 'id_meeting_provider') applyVisibility();
    });

    applyVisibility();
    document.addEventListener('htmx:afterSwap', applyVisibility);
})();
