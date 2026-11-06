/**
 * Dashboard component form: live chart preview, columns select2 and the
 * file-input name display.
 *
 * Loaded by dashboard_component_form.html. The script tag carries the preview
 * endpoint in data-preview-url. File inputs are marked in the template with
 * data-file-input-id (the input's id); each one is initialised once.
 *
 * Re-runs whenever the form is loaded or swapped by HTMX. The document level
 * listeners and shared preview state must exist only once per page, so they
 * are guarded by window._dashboardComponentFormInit. The per-render setup at
 * the bottom runs on every load.
 */
(function () {
  var script = document.currentScript;
  var previewUrl = (script && script.dataset.previewUrl) || "";

  function initFileInputs() {
    document
      .querySelectorAll("[data-file-input-id]:not([data-file-input-initialised])")
      .forEach(function (holder) {
        holder.setAttribute("data-file-input-initialised", "true");
        var id = holder.dataset.fileInputId;
        const input = document.getElementById(id);
        const fileName = document.getElementById(id + "-name");
        if (input && fileName) {
          input.addEventListener("change", function () {
            if (this.files && this.files.length > 0) {
              fileName.textContent = this.files[0].name;
            } else {
              fileName.textContent = "No file chosen";
            }
          });
        }
      });
  }

  if (!window._dashboardComponentFormInit) {
    window._dashboardComponentFormInit = true;

    function getModuleValue() {
      const moduleSelect = document.getElementById('id_module');
      if (!moduleSelect) return '';
      /* Use option value (registry key / content type id), not label - avoids wrong model choices */
      return moduleSelect.value || '';
    }

    function updatePreviewAfterFormSwap() {
      window.pendingPreviewUpdate = true;
    }

    let previewUpdateTimeout = null;
    let isUpdatingPreview = false;

    function updatePreview() {
      const previewContainer = document.querySelector('#preview-container');
      if (!previewContainer) {
        return;
      }

      if (isUpdatingPreview) {
        return;
      }

      if (previewUpdateTimeout) {
        clearTimeout(previewUpdateTimeout);
      }

      previewUpdateTimeout = setTimeout(() => {
        isUpdatingPreview = true;

        const componentTypeField = document.querySelector('[name="component_type"]');
        const chartTypeField = document.querySelector('[name="chart_type"]');

        const params = new URLSearchParams();

        if (componentTypeField && componentTypeField.value) {
          params.append('component_type', componentTypeField.value);
        }
        if (chartTypeField && chartTypeField.value) {
          params.append('chart_type', chartTypeField.value);
        }

        const formElement = document.querySelector('#dashboardcomponent-form-view');
        if (formElement) {
          const formData = new FormData(formElement);
          for (let [key, value] of formData.entries()) {
            if (!params.has(key) && key !== 'csrfmiddlewaretoken') {
              params.append(key, value);
            }
          }
        }

        const url = previewUrl + (params.toString() ? '?' + params.toString() : '');

        htmx.ajax('GET', url, {
          target: '#preview-container',
          swap: 'innerHTML'
        }).then(() => {
          setTimeout(() => {
            isUpdatingPreview = false;
          }, 100);
        });

        previewUpdateTimeout = null;
      }, 150);
    }

    document.addEventListener('htmx:afterSwap', function(event) {
      if (event.detail.target.id && event.detail.target.id.includes('dashboardcomponent-form-view-container') && window.pendingPreviewUpdate) {
        window.pendingPreviewUpdate = false;
        setTimeout(updatePreview, 150);
      }
    });

    document.addEventListener('DOMContentLoaded', function() {
      setTimeout(updatePreview, 200);
    });

    $(document).on('htmx:afterSwap', function(event) {
      const formContainer = document.querySelector('#dashboardcomponent-form-view-container');
      if (!formContainer) {
        return;
      }

      const columns = $("#id_columns");
      if (!columns.is(":hidden")) {
        columns.select2();
      }

      if (event.target && (
        event.target.id === 'dashboardcomponent-form-view-container' ||
        (event.target.closest && event.target.closest('#dashboardcomponent-form-view-container') && event.target.id !== 'preview-container')
      )) {
        const selectEl = document.querySelector('.component_type');
        if (selectEl && selectEl.value) {
          setTimeout(() => {
            updatePreview();
          }, 100);
        }
      }
    });

    $(document).on('htmx:afterSettle', function(event) {
      const columns = $("#id_columns");
      if (!columns.is(":hidden")) {
        columns.select2();
      }
    });

    // Reachable from inline onchange handlers and other scripts
    window.getModuleValue = getModuleValue;
    window.updatePreviewAfterFormSwap = updatePreviewAfterFormSwap;
    window.updatePreview = updatePreview;
  }

  // Per-render setup (runs every time the form is loaded)
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initFileInputs);
  } else {
    initFileInputs();
  }

  $(document).ready(function () {
    const columns = $("#id_columns");
    if (!columns.is(":hidden")) {
      columns.select2();
    }

    const selectEl = document.querySelector('.component_type');
    if (selectEl && selectEl.value) {
      setTimeout(() => {
        window.updatePreview();
      }, 100);
    }
  });
})();
