/**
 * Export Data settings page behaviour (columns modal, select-all toggles, blob download).
 *
 * Loaded by export/export_view.html. The script tag carries the translated
 * button labels in data-select-all-label / data-unselect-all-label. Functions
 * used by inline handlers (onclick/onchange/on_close) stay global.
 */
function closeExportColumnsModal() {
  ModalManager.close("exportColumnsModal", "exportColumnsBox", false);
}

function toggleExportAccordion(button) {
  var header = button.closest('.export-fields-header');
  var content = header ? header.nextElementSibling : button.nextElementSibling;
  var svg = button.querySelector('svg');
  if (content) content.classList.toggle('open');
  if (svg) svg.classList.toggle('rotate-90');
}

var EXPORT_SCRIPT_DATA = (document.currentScript && document.currentScript.dataset) || {};
var EXPORT_SELECT_ALL_LABEL = EXPORT_SCRIPT_DATA.selectAllLabel || "Select All";
var EXPORT_UNSELECT_ALL_LABEL = EXPORT_SCRIPT_DATA.unselectAllLabel || "Unselect All";

function getExportFieldBlocks(scope) {
  var $scope = $(scope);
  return $scope.hasClass('export-fields-block')
    ? $scope
    : $scope.find('.export-fields-block').not('.hidden');
}

function syncGlobalExportToggleState() {
  var $visible = $('.export-fields-block').not('.hidden');
  var $fields = $visible.find('.export-field-checkbox');
  var total = $fields.length;
  var checkedCount = $fields.filter(':checked').length;
  $('#globalExportToggleBtn').text(
    total > 0 && checkedCount === total ? EXPORT_UNSELECT_ALL_LABEL : EXPORT_SELECT_ALL_LABEL
  );
}

function toggleAllExportFieldsChecked(button, scope) {
  var $btn = $(button);
  var checked = $btn.text().trim() === EXPORT_SELECT_ALL_LABEL;
  var $blocks = getExportFieldBlocks(scope);
  $blocks.find('.export-field-checkbox').prop('checked', checked);
  $blocks.find('.module-select-all').prop('checked', checked).prop('indeterminate', false);
  $btn.text(checked ? EXPORT_UNSELECT_ALL_LABEL : EXPORT_SELECT_ALL_LABEL);
}

function toggleModuleFieldsChecked(checkbox) {
  var $block = $(checkbox).closest('.export-fields-block');
  var checked = checkbox.checked;
  $block.find('.export-field-checkbox').prop('checked', checked);
  syncGlobalExportToggleState();
}

function syncModuleSelectAllState(checkbox) {
  var $block = $(checkbox).closest('.export-fields-block');
  var $fields = $block.find('.export-field-checkbox');
  var total = $fields.length;
  var checkedCount = $fields.filter(':checked').length;
  var $selectAll = $block.find('.module-select-all');

  $selectAll.prop('checked', checkedCount === total);
  $selectAll.prop('indeterminate', checkedCount > 0 && checkedCount < total);
  syncGlobalExportToggleState();
}

$(document).ready(function() {
  function updateExportFieldsVisibility() {
    var selected = $('select[name="module"]').val() || [];
    $('.export-fields-block').each(function() {
      var moduleName = $(this).data('export-fields');
      $(this).toggleClass('hidden', selected.indexOf(moduleName) === -1);
    });
    syncGlobalExportToggleState();
  }

  $(document).off('.exportView');

  $(document).on('change.exportView', 'select[name="module"]', updateExportFieldsVisibility);
  updateExportFieldsVisibility();

  $(document).on('click.exportView', '#openExportColumnsBtn', function() {
    var modules = $('select[name="module"]').val() || [];
    var format = $('select[name="export_format"]').val();
    if (modules.length === 0 || !format) {
      $('#exportform')[0].reportValidity();
      return;
    }
    updateExportFieldsVisibility();
    $('.export-fields-error').addClass('hidden');
    ModalManager.open("exportColumnsModal", "exportColumnsBox", false);
  });

  $(document).on('click.exportView', '#submitExportColumnsBtn', function() {
    var hasEmptyModule = false;
    $('.export-fields-block').not('.hidden').each(function() {
      var $block = $(this);
      var isEmpty = $block.find('.export-field-checkbox:checked').length === 0;
      $block.find('.export-fields-error').toggleClass('hidden', !isEmpty);
      if (isEmpty) hasEmptyModule = true;
    });

    if (hasEmptyModule) return;

    closeExportColumnsModal();
    $('#exportform').trigger('submit');
  });

  $(document).on('submit.exportView', '#exportform', function(e) {
    e.preventDefault();

    var form = $(this)[0];
    var formData = new FormData(form);
    $('#exportColumnsBox input[type="checkbox"][form="exportform"]:checked').each(function() {
      formData.append(this.name, this.value);
    });

    $.ajax({
      url: form.action,
      type: 'POST',
      data: formData,
      processData: false,
      contentType: false,
      xhrFields: {
        responseType: 'blob'
      },
      success: function(blob, status, xhr) {
        var url = window.URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;

        var contentDisposition = xhr.getResponseHeader('Content-Disposition');
        var filename = 'exported_data.zip';
        if (contentDisposition) {
          var filenameMatch = contentDisposition.match(/filename="(.+)"/);
          if (filenameMatch && filenameMatch[1]) {
            filename = filenameMatch[1];
          }
        }

        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();

        $('#reloadMessagesButton').click();
        $('#reloadButton').click();
      },

    });
  });
});
