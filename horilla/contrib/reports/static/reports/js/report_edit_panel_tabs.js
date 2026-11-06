// Store active tab in sessionStorage to persist across HTMX updates
function initTabSystem() {
    const tabs = document.querySelectorAll('#panel .tab-button');
    const contents = document.querySelectorAll('#panel .tab-content');

    // Get the stored active tab or default to 'columns'
    const activeTab = sessionStorage.getItem('activeReportTab') || 'columns';

    // Function to switch tabs
    function switchTab(targetTabName) {
        tabs.forEach(tab => {
            const tabName = tab.getAttribute('data-tab-name');
            if (tabName === targetTabName) {
                tab.classList.add('text-primary-600');
                tab.classList.remove('text-[#333]');
                tab.setAttribute('aria-selected', 'true');
            } else {
                tab.classList.remove('text-primary-600');
                tab.classList.add('text-[#333]');
                tab.setAttribute('aria-selected', 'false');
            }
        });

        contents.forEach(content => {
            const contentId = content.id;
            if (
                (targetTabName === 'columns' && contentId === 'columns-tab') ||
                (targetTabName === 'grouping' && contentId === 'grouping-tab') ||
                (targetTabName === 'filter' && contentId === 'filter-tab')
            ) {
                content.classList.remove('hidden');
            } else {
                content.classList.add('hidden');
            }
        });
    }

    // Set initial active tab
    switchTab(activeTab);

    // Add click handlers
    tabs.forEach(tab => {
        tab.addEventListener('click', function(e) {
            e.preventDefault();
            const tabName = this.getAttribute('data-tab-name');
            switchTab(tabName);
            sessionStorage.setItem('activeReportTab', tabName);
        });
    });
}

// Initialize tab system when panel loads
if (document.getElementById('panel')) {
    initTabSystem();
}

// Reinitialize after HTMX updates the panel
if (!window.reportPanelTabsBound) {
    window.reportPanelTabsBound = true;
    document.body.addEventListener('htmx:afterSettle', function(event) {
        if (event.target.id === 'panel') {
            setTimeout(initTabSystem, 10);
        }
    });
}
