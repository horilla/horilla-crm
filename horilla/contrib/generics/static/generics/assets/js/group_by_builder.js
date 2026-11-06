// Group-by field builder (rows of field selects above the grouped table).
// The URL query parameter name is passed via data-group-by-param on the script tag.
(function (groupByParam) {
  var $rows = $("#groupByRows");
  var suppressChangeHandler = false;

  // Master list of every group-by field, captured once from the
  // template's fully-populated option set - refreshOptionAvailability
  // rebuilds each row's <select> from this rather than incrementally
  // removing options, so a field freed up by unpicking/removing a row
  // has somewhere to be restored from. The blank placeholder is added
  // here explicitly (the server-rendered first row never has one, since
  // it always starts with a real field picked) so a freshly added row
  // rebuilt from this list still has a "nothing chosen yet" option -
  // without it, the browser silently auto-selects the first real option.
  var placeholderText = $("#groupByRowTemplate").html()
    ? $($("#groupByRowTemplate").html()).find("option[value='']").text()
    : "";
  var allFieldOptions = [{ value: "", text: placeholderText }].concat(
    $rows.find(".groupby-field-select").first().find("option")
      .filter(function () { return this.value; })
      .map(function () {
        return { value: this.value, text: this.textContent };
      }).get()
  );

  function initSelect2($select) {
    if ($select.hasClass("select2-hidden-accessible")) {
      $select.select2("destroy");
    }
    $select.select2({ width: "resolve" });
  }

  function refreshOptionAvailability() {
    var chosen = [];
    $rows.find(".groupby-field-select").each(function () {
      var v = $(this).val();
      if (v) {
        chosen.push(v);
      }
    });
    $rows.find(".groupby-field-select").each(function () {
      var $select = $(this);
      var mine = $select.val();
      // select2 still lists a disabled option in its open dropdown
      // (greyed, non-clickable) - rebuilding from the master list
      // with chosen-elsewhere fields left out is what actually makes
      // them disappear, while still allowing a field freed up by
      // another row changing/removing to come back.
      var html = allFieldOptions.filter(function (opt) {
        return !opt.value || opt.value === mine || chosen.indexOf(opt.value) === -1;
      }).map(function (opt) {
        var selectedAttr = opt.value === mine ? " selected" : "";
        return "<option value=\"" + opt.value + "\"" + selectedAttr + ">" + opt.text + "</option>";
      }).join("");
      $select.html(html);
      suppressChangeHandler = true;
      $select.trigger("change.select2");
      suppressChangeHandler = false;
    });
  }

  function submitGroupBy() {
    var values = [];
    $rows.find(".groupby-field-select").each(function () {
      var v = $(this).val();
      if (v) {
        values.push(v);
      }
    });
    if (!values.length) {
      return;
    }
    document.getElementById("groupByValue").value = values.join(",");
    // The group-by request itself doesn't push a URL (it targets the view
    // fragment, not the page), so mirror the choice into the page URL.
    // A reload then forwards group_by to the fragment and keeps every level.
    try {
      var pageUrl = new URL(window.location.href);
      pageUrl.searchParams.set(groupByParam, values.join(","));
      window.history.replaceState(window.history.state, "", pageUrl.toString());
    } catch (err) {
      /* URL sync is best-effort */
    }
    htmx.trigger("#groupByValue", "change");
  }

  function updateAddButtonVisibility() {
    var totalFields = allFieldOptions.filter(function (opt) { return opt.value; }).length;
    var rowCount = $rows.find(".groupby-row").length;
    $("#groupByAddRow").toggle(rowCount < totalFields);
  }

  $rows.find(".groupby-field-select").each(function () {
    initSelect2($(this));
  });
  refreshOptionAvailability();
  updateAddButtonVisibility();

  $rows.on("change", ".groupby-field-select", function () {
    if (suppressChangeHandler) {
      return;
    }
    refreshOptionAvailability();
    submitGroupBy();
  });

  $rows.on("click", ".groupby-remove-row", function () {
    $(this).closest(".groupby-row").remove();
    refreshOptionAvailability();
    updateAddButtonVisibility();
    submitGroupBy();
  });

  $("#groupByAddRow").on("click", function () {
    var $tpl = $($("#groupByRowTemplate").html());
    $rows.append($tpl);
    initSelect2($tpl.find(".groupby-field-select"));
    refreshOptionAvailability();
    updateAddButtonVisibility();
    // No submit here - a fresh row has no field picked yet, so there's
    // nothing new to group by until the user actually selects one.
  });

  // The reload swaps out this whole view (including these rows), so a
  // click that lands while a prior reload is still in flight targets a
  // node that's about to be destroyed and silently loses that pick.
  // Disable every row + the add button for the duration of the request.
  document.body.addEventListener("htmx:beforeRequest", function (e) {
    if (e.detail.elt && e.detail.elt.id === "groupByValue") {
      $rows.find(".groupby-field-select").each(function () {
        $(this).prop("disabled", true).trigger("change.select2");
      });
      $("#groupByAddRow").prop("disabled", true);
    }
  });
})(document.currentScript.dataset.groupByParam);
