// Function to select first 3 items
window.selectFirstThree = function(viewId, maxSelection) {
    // Use global tableData if available, otherwise create window.tableData
    const tableDataMap = (typeof tableData !== 'undefined' && tableData instanceof Map) ? tableData : (window.tableData || new Map());
    if (!window.tableData && typeof tableData === 'undefined') {
        window.tableData = tableDataMap;
    }

    let table = tableDataMap.get(viewId);
    if (!table) {
        table = { selectedRecordIds: [], allRecordIds: [], allSelected: false };
        tableDataMap.set(viewId, table);
    }

    // Wait a bit to ensure DOM is ready, especially after redirect
    setTimeout(function() {
        const checkboxes = document.querySelectorAll(`#table-container-${viewId} input[data-role='row-select']`);
        const selectedIds = [];

        if (checkboxes.length === 0) {
            // If no checkboxes found, try again after a short delay
            setTimeout(function() {
                window.selectFirstThree(viewId, maxSelection);
            }, 200);
            return;
        }

        // Uncheck all first
        checkboxes.forEach(function(checkbox) {
            checkbox.checked = false;
            // Use jQuery if available to ensure proper update
            if (typeof $ !== 'undefined') {
                $(checkbox).prop('checked', false);
            }
        });

        // Select first maxSelection checkboxes
        Array.from(checkboxes).slice(0, maxSelection).forEach(function(checkbox) {
            const recordId = checkbox.getAttribute('data-record-id') || checkbox.value;
            checkbox.checked = true;
            // Use jQuery if available to ensure proper update
            if (typeof $ !== 'undefined') {
                $(checkbox).prop('checked', true).trigger('change');
            } else {
                // Trigger change event to ensure UI updates
                checkbox.dispatchEvent(new Event('change', { bubbles: true }));
            }
            if (recordId && !selectedIds.includes(recordId)) {
                selectedIds.push(recordId);
            }
        });

        // Update table data
        table.selectedRecordIds = selectedIds;
        table.allSelected = false;
        if (typeof sessionStorage !== 'undefined') {
            sessionStorage.setItem(`selectedRecordIds_${viewId}`, JSON.stringify(selectedIds));
        }

        // Update UI - force update button visibility immediately
        if (typeof $ !== 'undefined') {
            const hasSelections = selectedIds.length > 0;

            // Show/hide unselect button
            $(`#unselect-all-btn-${viewId}`).toggle(hasSelections);
            if (hasSelections) {
                $(`#unselect-text-${viewId}`).text(selectedIds.length);
            }

            // Show/hide all bulk action buttons (including merge)
            $(`[id^="bulk-action-"][id$="-${viewId}"]`).each(function() {
                $(this).toggle(hasSelections);
            });

            // Also call the global function if available (it's debounced, so call it after a small delay)
            if (typeof updateActionButtonsVisibility === 'function') {
                // Call it immediately and also after a small delay to ensure it runs
                updateActionButtonsVisibility(viewId);
                setTimeout(function() {
                    updateActionButtonsVisibility(viewId);
                }, 150);
            }
        }
    }, 100); // Small delay to ensure DOM is ready
};

// Limit selection to maxSelection and update button visibility
(function() {
    const config = document.currentScript.dataset;
    const viewId = config.viewId;
    const maxSelection = Number(config.maxSelection);
    const objectId = config.objectId;
    const contentTypeId = config.contentTypeId;
    const limitMessage = config.limitMessagePrefix + ' ' + maxSelection + ' ' + config.limitMessageSuffix;

    // Initialize tableData if not exists
    if (!window.tableData) window.tableData = new Map();
    if (!window.tableData.get(viewId)) {
        window.tableData.set(viewId, { selectedRecordIds: [], allRecordIds: [] });
    }

    // Function to update selected IDs in tableData
    function updateSelectedIds(viewId) {
        // Use global tableData if available, otherwise window.tableData
        const tableDataMap = (typeof tableData !== 'undefined' && tableData instanceof Map) ? tableData : (window.tableData || new Map());
        if (!window.tableData && typeof tableData === 'undefined') {
            window.tableData = tableDataMap;
        }

        let table = tableDataMap.get(viewId);
        if (!table) {
            table = { selectedRecordIds: [], allRecordIds: [], allSelected: false };
            tableDataMap.set(viewId, table);
        }

        const checkboxes = document.querySelectorAll(`#table-container-${viewId} input[data-role='row-select']`);
        const selectedIds = [];

        checkboxes.forEach(function(checkbox) {
            if (checkbox.checked) {
                const recordId = checkbox.getAttribute('data-record-id') || checkbox.value;
                if (recordId) {
                    selectedIds.push(recordId);
                }
            }
        });

        // Ensure we don't exceed the limit - uncheck extras if needed
        if (selectedIds.length > maxSelection) {
            // Uncheck checkboxes beyond the limit
            let checkedCount = 0;
            checkboxes.forEach(function(checkbox) {
                if (checkbox.checked) {
                    checkedCount++;
                    if (checkedCount > maxSelection) {
                        checkbox.checked = false;
                        const recordId = checkbox.getAttribute('data-record-id') || checkbox.value;
                        const index = selectedIds.indexOf(recordId);
                        if (index > -1) {
                            selectedIds.splice(index, 1);
                        }
                    }
                }
            });
        }

        table.selectedRecordIds = selectedIds;
        if (typeof sessionStorage !== 'undefined') {
            sessionStorage.setItem(`selectedRecordIds_${viewId}`, JSON.stringify(selectedIds));
        }

        // Update button visibility
        if (typeof updateActionButtonsVisibility === 'function') {
            updateActionButtonsVisibility(viewId);
        } else if (typeof $ !== 'undefined') {
            // Fallback: manually show/hide buttons
            const hasSelections = selectedIds.length > 0;
            $(`#unselect-all-btn-${viewId}, [id^="bulk-action-"][id$="-${viewId}"]`).toggle(hasSelections);
            if (hasSelections) {
                $(`#unselect-text-${viewId}`).text(selectedIds.length);
            } else {
                $(`#unselect-text-${viewId}`).text('0');
            }
        }
    }

    // Handle change event to check limit and update count
    document.addEventListener('change', function(e) {
        if (e.target.matches(`#table-container-${viewId} input[data-role='row-select']`)) {
            const checkbox = e.target;
            const checkboxes = document.querySelectorAll(`#table-container-${viewId} input[data-role='row-select']:checked`);

            // Check if limit exceeded
            if (checkboxes.length > maxSelection) {
                // Uncheck the checkbox that caused the limit to be exceeded
                checkbox.checked = false;

                // Use SweetAlert instead of alert
                if (typeof Swal !== 'undefined') {
                    Swal.fire({
                        html: limitMessage,
                        icon: "warning",
                        confirmButtonColor: "#008000",
                        confirmButtonText: typeof horillaMessages !== 'undefined' ? horillaMessages.ok || 'OK' : 'OK',
                        showClass: {
                            popup: `animate__animated animate__fadeInUp animate__faster`
                        },
                        hideClass: {
                            popup: `animate__animated animate__fadeOutDown animate__faster`
                        }
                    });
                }
                updateSelectedIds(viewId);
                return;
            }

            // Only update selected IDs and button visibility if limit not exceeded
            updateSelectedIds(viewId);
        }
    });

    // Also listen using jQuery if available
    if (typeof $ !== 'undefined') {
        $(document).on('change', `#table-container-${viewId} input[data-role='row-select']`, function(e) {
            const $checkbox = $(this);
            const checkboxes = $(`#table-container-${viewId} input[data-role='row-select']:checked`);

            // Check if limit exceeded
            if (checkboxes.length > maxSelection) {
                // Uncheck the checkbox that caused the limit to be exceeded
                $checkbox.prop('checked', false);

                // Use SweetAlert instead of alert
                if (typeof Swal !== 'undefined') {
                    Swal.fire({
                        html: limitMessage,
                        icon: "warning",
                        confirmButtonColor: "#008000",
                        confirmButtonText: typeof horillaMessages !== 'undefined' ? horillaMessages.ok || 'OK' : 'OK',
                        showClass: {
                            popup: `animate__animated animate__fadeInUp animate__faster`
                        },
                        hideClass: {
                            popup: `animate__animated animate__fadeOutDown animate__faster`
                        }
                    });
                } else if (typeof hxConfirm === 'function') {
                    // Fallback to hxConfirm if Swal not available
                    hxConfirm($checkbox[0], limitMessage);
                } else {
                    // Final fallback to alert
                    alert(limitMessage);
                }

                // Immediately recalculate to fix the count
                updateSelectedIds(viewId);
                return false;
            }

            // Only update selected IDs and button visibility if limit not exceeded
            updateSelectedIds(viewId);
        });
    }

    // Update merge button hx-vals to include selected_ids
    document.body.addEventListener('htmx:configRequest', function(event) {
        const target = event.detail.target;
        if (target && (target.id && target.id.includes('bulk-action-merge-' + viewId) || (target.closest && target.closest('#bulk-action-merge-' + viewId)))) {
            const currentVals = event.detail.parameters || {};
            currentVals.object_id = objectId;
            currentVals.content_type_id = contentTypeId;

            // Get selected IDs from tableData or checkboxes
            let selectedIds = [];
            if (typeof tableData !== 'undefined' && tableData instanceof Map) {
                const table = tableData.get(viewId);
                if (table && table.selectedRecordIds) {
                    selectedIds = table.selectedRecordIds;
                }
            } else if (window.tableData && window.tableData instanceof Map) {
                const table = window.tableData.get(viewId);
                if (table && table.selectedRecordIds) {
                    selectedIds = table.selectedRecordIds;
                }
            }

            // If no IDs in tableData, get from checkboxes
            if (selectedIds.length === 0) {
                const checkboxes = document.querySelectorAll(`#table-container-${viewId} input[data-role='row-select']:checked`);
                checkboxes.forEach(function(checkbox) {
                    const recordId = checkbox.getAttribute('data-record-id') || checkbox.value;
                    if (recordId) {
                        selectedIds.push(recordId);
                    }
                });
            }

            // Add selected_ids as JSON string
            if (selectedIds.length > 0) {
                currentVals.selected_ids = JSON.stringify(selectedIds);
            }

            event.detail.parameters = currentVals;
        }
    });

    // Initialize button visibility on page load
    setTimeout(function() {
        updateSelectedIds(viewId);
    }, 100);
})();
