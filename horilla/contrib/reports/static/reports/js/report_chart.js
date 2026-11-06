(function() {
    const reportConfig = document.getElementById('report-detail-config');
    if (!reportConfig || reportConfig.dataset.chartInit) return;
    reportConfig.dataset.chartInit = 'true';
    const REPORT_ID = reportConfig.dataset.reportId;

    function readConfigJson(id) {
        const el = document.getElementById(id);
        let value = el ? JSON.parse(el.textContent) : null;
        if (typeof value === 'string') value = JSON.parse(value);
        return value;
    }
    const CHART_CONTAINER_ID = `chart-${REPORT_ID}`;
    const CHART_INSTANCE_KEY = `reportChartInstance_${REPORT_ID}`;

    let initializationAttempts = 0;
    const MAX_ATTEMPTS = 10;
    const RETRY_DELAY = 200;

    // Function to export chart as PDF
    window.exportChartAsPDF = function(chartId, filename) {
        try {
            if (!window.jspdf || !window.jspdf.jsPDF) {
                console.error('jsPDF library is not loaded.');
                alert('Failed to export PDF: jsPDF library is not loaded.');
                return;
            }

            const chartInstance = window[`reportChartInstance_${chartId.split('-')[1]}`];
            if (!chartInstance || chartInstance.isDisposed()) {
                console.error('Chart instance not found or disposed for ID:', chartId);
                alert('Failed to export PDF: Chart instance not available.');
                return;
            }

            chartInstance.resize();

            const imgData = chartInstance.getDataURL({
                pixelRatio: 2,
                backgroundColor: '#fff',
                excludeComponents: ['toolbox']
            });

            if (!imgData) {
                console.error('Failed to generate chart image data.');
                alert('Failed to export PDF: Could not generate chart image.');
                return;
            }

            const { jsPDF } = window.jspdf;
            const pdf = new jsPDF({
                orientation: 'landscape',
                unit: 'px',
                format: [800, 400]
            });

            const imgProps = pdf.getImageProperties(imgData);
            const pdfWidth = pdf.internal.pageSize.getWidth();
            const pdfHeight = pdf.internal.pageSize.getHeight();
            const imgWidth = 700;
            const imgHeight = (imgProps.height * imgWidth) / imgProps.width;

            const x = (pdfWidth - imgWidth) / 2;
            const y = (pdfHeight - imgHeight) / 2;

            pdf.addImage(imgData, 'PNG', x, y, imgWidth, imgHeight);
            pdf.save(`${filename}.pdf`);
        } catch (error) {
            console.error('Error exporting chart as PDF:', error);
            alert('Failed to export PDF: An error occurred.');
        }
    };

    const REPORT_CHART_KEY = 'report-chart-' + REPORT_ID;

    function cleanupChart() {
        if (window.chartInstances && window.chartInstances[REPORT_CHART_KEY]) {
            delete window.chartInstances[REPORT_CHART_KEY];
        }
        // Clean up existing chart instance
        if (window[CHART_INSTANCE_KEY]) {
            try {
                if (!window[CHART_INSTANCE_KEY].isDisposed()) {
                    window[CHART_INSTANCE_KEY].dispose();
                }
            } catch (e) {
                console.warn('Error disposing chart:', e);
            }
            window[CHART_INSTANCE_KEY] = null;
        }
    }

    function initChart() {
        if (reportConfig.dataset.chartError !== 'true') {
            const chartContainer = document.getElementById(CHART_CONTAINER_ID);

            // Check if container exists and is visible
            if (!chartContainer) {
                console.warn(`Chart container #${CHART_CONTAINER_ID} not found. Attempt ${initializationAttempts + 1}/${MAX_ATTEMPTS}`);

                if (initializationAttempts < MAX_ATTEMPTS) {
                    initializationAttempts++;
                    setTimeout(initChart, RETRY_DELAY);
                }
                return false;
            }

            // Check if required libraries are loaded
            if (typeof echarts === 'undefined' || typeof EChartsConfig === 'undefined') {
                console.warn(`ECharts or EChartsConfig not loaded. Attempt ${initializationAttempts + 1}/${MAX_ATTEMPTS}`);

                if (initializationAttempts < MAX_ATTEMPTS) {
                    initializationAttempts++;
                    setTimeout(initChart, RETRY_DELAY);
                }
                return false;
            }

            try {
                // Clean up any existing instance
                cleanupChart();

                // Initialize new chart instance
                const chartInstance = echarts.init(chartContainer);
                window[CHART_INSTANCE_KEY] = chartInstance;

                const chartConfig = {
                    type: reportConfig.dataset.chartType,
                    labels: readConfigJson('report-chart-labels'),
                    data: readConfigJson('report-chart-data'),
                    colors: EChartsConfig.getDynamicColors(Number(reportConfig.dataset.labelCount)),
                    labelField: reportConfig.dataset.labelField,
                    stackedData: readConfigJson('report-chart-stacked-data'),
                    hasMultipleGroups: reportConfig.dataset.hasMultipleGroups === 'true',
                    urls : readConfigJson('report-chart-urls')
                };

                const option = EChartsConfig.getChartOption(chartConfig);
                chartInstance.setOption(option, true);

                if (typeof window.chartInstances === 'undefined') {
                    window.chartInstances = {};
                }
                window.chartInstances[REPORT_CHART_KEY] = { instance: chartInstance, config: chartConfig };

                const chartUrls = readConfigJson('report-chart-urls');
                if (chartConfig.type === 'treemap' || chartConfig.type === 'sankey' ||
                    chartConfig.type === 'stacked_vertical' || chartConfig.type === 'stacked_horizontal' ||
                    chartConfig.type === 'heatmap' || (chartConfig.type === 'radar' && chartConfig.stackedData && chartConfig.stackedData.series && chartConfig.stackedData.series.length) ||
                    (chartUrls && chartUrls.length > 0)) {
                    EChartsConfig.attachClickHandler(chartInstance, chartUrls || [], chartConfig);
                }

                // Force resize after a short delay
                setTimeout(() => {
                    if (chartInstance && !chartInstance.isDisposed()) {
                        chartInstance.resize();
                    }
                }, 100);

                console.log('Chart initialized successfully');
                initializationAttempts = 0; // Reset counter on success
                return true;

            } catch (error) {
                console.error('Error initializing chart:', error);
                if (initializationAttempts < MAX_ATTEMPTS) {
                    initializationAttempts++;
                    setTimeout(initChart, RETRY_DELAY);
                }
                return false;
            }
        }
    }

    // Resize chart when container size changes (e.g. when edit panel opens/closes)
    let resizeTimeout;
    function scheduleChartResize() {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
            const chartInstance = window[CHART_INSTANCE_KEY];
            if (chartInstance && !chartInstance.isDisposed()) {
                chartInstance.resize();
            }
        }, 250);
    }
    function handleResize() { scheduleChartResize(); }

    window.removeEventListener('resize', handleResize);
    window.addEventListener('resize', handleResize);

    // When edit panel opens/closes, chart container width changes — observe and resize
    const chartContainerEl = document.getElementById(CHART_CONTAINER_ID);
    if (chartContainerEl && typeof ResizeObserver !== 'undefined') {
        var resizeObserver = new ResizeObserver(function() { scheduleChartResize(); });
        resizeObserver.observe(chartContainerEl);
    }

    // Initialize chart on page load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initChart);
    } else {
        initChart();
    }

    // Reinitialize chart after HTMX updates
    document.body.addEventListener('htmx:afterSettle', function(event) {
        if (event.target.id === 'report-content' ||
            event.target.id === 'mainContent' ||
            event.target.id === 'chart-container') {

            initializationAttempts = 0; // Reset counter
            setTimeout(initChart, 150);
        }
    });

    // Handle before swap to clean up
    document.body.addEventListener('htmx:beforeSwap', function(event) {
        if (event.target.id === 'report-content' || event.target.id === 'mainContent') {
            cleanupChart();
        }
    });


})();

// Export dropdown handler
document.addEventListener('DOMContentLoaded', function() {
    const dropdownButton = document.getElementById('exportDropdownButton');
    const dropdownMenu = document.getElementById('exportDropdown');

    if (dropdownButton && dropdownMenu) {
        dropdownButton.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            dropdownMenu.classList.toggle('hidden');
        });

        document.addEventListener('click', function(e) {
            if (!dropdownButton.contains(e.target) && !dropdownMenu.contains(e.target)) {
                dropdownMenu.classList.add('hidden');
            }
        });
    }
});
