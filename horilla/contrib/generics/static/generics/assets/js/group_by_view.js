// Group-by grouped table behaviour (collapse/expand, group cards, Expand All,
// row virtualization, group-level selection). Re-executed on every HTMX swap of the
// view, so it must stay free of top-level let/const. The view id is passed via
// data-view-id on the script tag and must be read synchronously.
var gbViewId = document.currentScript.dataset.viewId;

// Collapse/expand a group-by divider row.
// data-group-parent only points one level up, so a grandchild has no way
// to know its grandparent (not its direct parent) just collapsed/expanded.
// Both directions walk the whole subtree instead of stopping at direct
// children: collapsing force-hides every descendant regardless of depth;
// expanding re-derives each descendant's visibility from its OWN
// remembered row-expanded state, so a grandchild the user had opened
// before stays open once its ancestors reopen, and one they'd left
// closed stays closed.
function directChildren(groupId) {
  return document.querySelectorAll('[data-group-parent="' + groupId + '"]');
}

function collapseSubtree(groupId) {
  directChildren(groupId).forEach(function (el) {
    el.classList.add("row-collapsed");
    if (el.tagName === "TR") {
      collapseSubtree(el.id);
    }
  });
}

function expandSubtree(groupId) {
  directChildren(groupId).forEach(function (el) {
    el.classList.remove("row-collapsed");
    if (el.tagName === "TR" && el.classList.contains("row-expanded")) {
      expandSubtree(el.id);
    }
  });
}

// When a first-level group is open, draw one continuous border around
// its header, sub-group strips and rows (like an approval rule card).
// Rows live in separate <tbody>s and keep their own list-cell-border
// shadows, so the card edges are added as classes on the first/last cell
// of each visible row and removed again on every refresh.
// Colours are read from the live theme (Tailwind generates the classes at
// runtime, so border colours cannot be hard-coded or built from class names).
function groupCardColors() {
  var probe = document.createElement("span");
  probe.className = "border border-primary-300";
  probe.style.cssText = "position:absolute;visibility:hidden";
  document.body.appendChild(probe);
  var accent = getComputedStyle(probe).borderTopColor;
  document.body.removeChild(probe);
  var rowLine = getComputedStyle(document.documentElement).getPropertyValue("--list-border-color-strong").trim() || "#efefef";
  return { accent: accent, row: rowLine };
}

function groupCardShadow(edge, isLast, isFirst, c) {
  var P = c.accent;
  var parts = [];
  if (isFirst) {
    parts.push("inset 0 1px 0 0 " + P);
  }
  if (edge === "first" || edge === "both") {
    parts.push("inset 1px 0 0 0 " + P);
  }
  if (edge === "last" || edge === "both") {
    parts.push("inset -1px 0 0 0 " + P);
  }
  if (isLast) {
    parts.push("inset 0 -1px 0 0 " + P);
  }
  return parts.join(", ");
}

// Coalesce bursts (Expand All fires many swaps/settles) into one pass
// per frame; each pass walks every row, so running it per event lags.
var gbCardRefreshQueued = false;
function refreshGroupCards() {
  if (gbCardRefreshQueued) {
    return;
  }
  gbCardRefreshQueued = true;
  requestAnimationFrame(function () {
    gbCardRefreshQueued = false;
    refreshGroupCardsNow();
  });
}

function refreshGroupCardsNow() {
  document.querySelectorAll("[data-gcard]").forEach(function (cell) {
    cell.style.removeProperty("--gc-shadow");
    cell.style.removeProperty("--gc-radius");
    cell.removeAttribute("data-gcard");
  });
  var table = document.querySelector("#" + gbViewId + " table");
  if (!table) {
    return;
  }
  var cards = [];
  var current = null;
  Array.prototype.forEach.call(table.tBodies, function (tbody) {
    var tbodyHidden = tbody.classList.contains("row-collapsed");
    Array.prototype.forEach.call(tbody.rows, function (tr) {
      if (tr.classList.contains("group-by-lvl-0")) {
        current = { open: tr.classList.contains("row-expanded"), rows: [] };
        cards.push(current);
      } else if (current && !tbodyHidden && !tr.classList.contains("row-collapsed")) {
        current.rows.push(tr);
      }
    });
  });
  var colors = groupCardColors();
  cards.forEach(function (card) {
    if (!card.open || !card.rows.length) {
      return;
    }
    card.rows.forEach(function (tr, i) {
      var cells = tr.cells;
      if (!cells.length) {
        return;
      }
      var isLast = i === card.rows.length - 1;
      var isFirst = i === 0;
      for (var k = 0; k < cells.length; k++) {
        var edge = cells.length === 1 ? "both" : k === 0 ? "first" : k === cells.length - 1 ? "last" : "mid";
        // Middle cells only need a line on the first row (header
        // separator) or the last row (card bottom).
        if (edge === "mid" && !isFirst && !isLast) {
          continue;
        }
        var cell = cells[k];
        cell.style.setProperty("--gc-shadow", groupCardShadow(edge, isLast, isFirst, colors));
        if (isLast && edge === "first") {
          cell.style.setProperty("--gc-radius", "0 0 0 0.375rem");
        } else if (isLast && edge === "last") {
          cell.style.setProperty("--gc-radius", "0 0 0.375rem 0");
        } else if (isLast && edge === "both") {
          cell.style.setProperty("--gc-radius", "0 0 0.375rem 0.375rem");
        }
        cell.setAttribute("data-gcard", "1");
      }
    });
  });
}

// Expand All is viewport-driven: only the group rows on (or just below)
// the screen are opened and fetched. Every other group row is watched and
// opened as the user scrolls it into view, so a click never has to touch
// (or load) the whole table at once. Opening a group reveals its direct
// children only; each child group row then goes through the same watch.
var gbExpandAllActive = false;
var gbExpandObserver = null;

function gbExpandNow(row) {
  if (!gbExpandAllActive || row.classList.contains("row-expanded")) {
    return;
  }
  row.classList.add("row-expanded");
  if (row.hasAttribute("hx-get") && !row.dataset.gbLoaded) {
    // Children arrive via htmx; the afterSwap handler continues from there.
    if (!row.dataset.gbRequested && window.htmx) {
      row.dataset.gbRequested = "1";
      htmx.trigger(row, "click");
    }
  } else {
    gbRevealChildren(row);
  }
  refreshGroupCards();
}

function gbRevealChildren(row) {
  directChildren(row.id).forEach(function (el) {
    el.classList.remove("row-collapsed");
    if (el.tagName === "TR" && el.classList.contains("group-by-divider-row")) {
      gbWatchRow(el);
    }
  });
}

function gbWatchRow(row) {
  if (row.classList.contains("row-expanded")) {
    // Already open (e.g. by hand): just make sure its subtree is shown.
    if (row.dataset.gbLoaded || !row.hasAttribute("hx-get")) {
      gbRevealChildren(row);
    }
    return;
  }
  var container = document.getElementById("table-container-" + gbViewId);
  if (!window.IntersectionObserver || !container) {
    gbExpandNow(row);
    return;
  }
  if (!gbExpandObserver) {
    gbExpandObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          gbExpandObserver.unobserve(entry.target);
          gbExpandNow(entry.target);
        }
      });
    }, { root: container, rootMargin: "300px 0px" });
  }
  gbExpandObserver.observe(row);
}

function collapseAllGroups() {
  gbExpandAllActive = false;
  if (gbExpandObserver) {
    gbExpandObserver.disconnect();
  }
  document.querySelectorAll("tr.group-by-divider-row.row-expanded").forEach(function (row) {
    row.classList.remove("row-expanded");
  });
  document.querySelectorAll("[data-group-parent]").forEach(function (el) {
    el.classList.add("row-collapsed");
  });
  refreshGroupCards();
}

function expandAllGroups() {
  gbExpandAllActive = true;
  // Only top-level rows are visible; deeper rows are watched as they appear.
  document.querySelectorAll("tr.group-by-divider-row.group-by-lvl-0").forEach(gbWatchRow);
}

function toggleGroupRow(rowEl) {
  var groupId = rowEl.id;
  var icon = rowEl.querySelector(".group-by-toggle-icon");
  var expanding = !rowEl.classList.contains("row-expanded");
  rowEl.classList.toggle("row-expanded", expanding);
  if (icon) {
    // Chevron flip is pure CSS: .row-expanded rotates .group-by-toggle-icon
    // (see group_by_view.css), so nothing to toggle on the icon itself.
  }
  if (expanding) {
    expandSubtree(groupId);
  } else {
    collapseSubtree(groupId);
  }
  refreshGroupCards();
}

// A row with hx-get (needs_fetch) has no children yet at click time,
// so the expandSubtree() call above finds nothing to reveal. Once its
// htmx request resolves and the fetched children land in the DOM
// (already row-collapsed, same as any other freshly-rendered
// sub-level), re-run expandSubtree for that row so content the user
// already asked to expand doesn't silently stay hidden.
// hx-target is the divider row's tbody wrapper (not the row itself -
// see group_by_node.html for why), so find the row inside it.
document.body.addEventListener("htmx:afterSwap", function (e) {
  var target = e.detail.elt;
  var rowEl = target && target.classList && target.classList.contains("group-by-divider-row")
    ? target
    : target && target.querySelector(".group-by-divider-row");
  if (rowEl && rowEl.classList) {
    rowEl.dataset.gbLoaded = "1";
    if (rowEl.classList.contains("row-expanded")) {
      if (gbExpandAllActive) {
        gbRevealChildren(rowEl);
      } else {
        expandSubtree(rowEl.id);
      }
    }
  }
  refreshGroupCards();
});
document.body.addEventListener("htmx:afterSettle", function () {
  refreshGroupCards();
  // Rows of a group fetched after "Select all" arrive unchecked; re-apply
  // the stored selection to them.
  if (typeof updateCheckboxStates === "function") {
    updateCheckboxStates(gbViewId);
  }
});
refreshGroupCards();

// Row virtualization: with every group open the table holds thousands of
// rows (each with sticky cells), which makes scrolling lag. Data bodies
// that are far off-screen are swapped for one fixed-height spacer row and
// their rows are restored as they approach the viewport.
var gbVirtObserver = null;
function gbVirtualize(tbody, height) {
  if (tbody.classList.contains("gb-virt") || !height) {
    return;
  }
  var spacer = document.createElement("tr");
  spacer.className = "gb-spacer";
  var td = document.createElement("td");
  td.colSpan = 99;
  td.style.cssText = "padding:0;border:0;height:" + Math.round(height) + "px";
  spacer.appendChild(td);
  tbody.appendChild(spacer);
  tbody.classList.add("gb-virt");
}
function gbDevirtualize(tbody) {
  if (!tbody.classList.contains("gb-virt")) {
    return;
  }
  tbody.classList.remove("gb-virt");
  tbody.querySelectorAll(":scope > tr.gb-spacer").forEach(function (el) { el.remove(); });
  refreshGroupCards();
}
function observeGroupBodies() {
  if (!window.IntersectionObserver) {
    return;
  }
  var container = document.getElementById("table-container-" + gbViewId);
  if (!container) {
    return;
  }
  if (!gbVirtObserver) {
    gbVirtObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var tbody = entry.target;
        if (entry.isIntersecting) {
          gbDevirtualize(tbody);
        } else if (!tbody.classList.contains("row-collapsed")) {
          gbVirtualize(tbody, entry.boundingClientRect.height);
        }
      });
      refreshGroupCards();
    }, { root: container, rootMargin: "1200px 0px" });
  }
  document.querySelectorAll("#" + gbViewId + " tbody[id^='data-container-']").forEach(function (tbody) {
    if (!tbody.dataset.gbObs) {
      tbody.dataset.gbObs = "1";
      gbVirtObserver.observe(tbody);
    }
  });
}
document.body.addEventListener("htmx:afterSettle", observeGroupBodies);
observeGroupBodies();

// Group-level select checkboxes: tick = select every record in the group
// (ids come from the server, so collapsed / not-yet-loaded rows count too);
// the box shows checked / partial / empty from the shared selection state.
function syncGroupSelectChecks() {
  var viewId = gbViewId;
  var chosen = new Set((typeof selectedRecordIds === "function" ? selectedRecordIds(viewId) : []).map(String));
  document.querySelectorAll("input[data-role='group-select']").forEach(function (box) {
    var ids = [];
    try { ids = JSON.parse(box.getAttribute("data-group-ids") || "[]").map(String); } catch (err) { ids = []; }
    var n = ids.filter(function (id) { return chosen.has(id); }).length;
    box.checked = ids.length > 0 && n === ids.length;
    box.indeterminate = n > 0 && n < ids.length;
  });
}

document.addEventListener("change", function (e) {
  var box = e.target;
  if (!(box instanceof HTMLInputElement)) {
    return;
  }
  var viewId = gbViewId;
  if (box.dataset.role === "group-select") {
    var table = typeof tableData !== "undefined" ? tableData.get(viewId) : null;
    if (!table) {
      return;
    }
    var ids = JSON.parse(box.getAttribute("data-group-ids") || "[]").map(String);
    var set = new Set(table.selectedRecordIds);
    ids.forEach(function (id) { box.checked ? set.add(id) : set.delete(id); });
    table.selectedRecordIds = Array.from(set);
    table.allSelected = table.allRecordIds.length > 0 && table.selectedRecordIds.length === table.allRecordIds.length;
    sessionStorage.setItem("selectedRecordIds_" + viewId, JSON.stringify(table.selectedRecordIds));
    updateCheckboxStates(viewId);
    updateActionButtonsVisibility(viewId);
    syncGroupSelectChecks();
  } else if (box.dataset.role === "row-select" || box.dataset.role === "select-all") {
    setTimeout(syncGroupSelectChecks, 0);
  }
});
document.addEventListener("click", function (e) {
  if (e.target.closest("[id^='select-all-btn-'], [id^='unselect-all-btn-']")) {
    setTimeout(syncGroupSelectChecks, 0);
  }
});
document.body.addEventListener("htmx:afterSettle", function () {
  syncGroupSelectChecks();
});

// Visible width of the scroll container, exposed as a CSS variable so group
// headers (sticky, see group_by_node.html) stay as wide as what is on screen.
// The container is looked up on every call and the width is refreshed on
// load, resize and after each htmx swap, so it is also correct on first paint
// (not only after the first expand).
var gbResizeObserved = null;
function setGroupViewportWidth() {
  var container = document.getElementById("table-container-" + gbViewId);
  if (!container) {
    return;
  }
  if (container.clientWidth) {
    container.style.setProperty("--gb-viewport-width", container.clientWidth + "px");
  }
  if (window.ResizeObserver && gbResizeObserved !== container) {
    gbResizeObserved = container;
    new ResizeObserver(setGroupViewportWidth).observe(container);
  }
}
setGroupViewportWidth();
requestAnimationFrame(setGroupViewportWidth);
setTimeout(setGroupViewportWidth, 250);
window.addEventListener("load", setGroupViewportWidth);
window.addEventListener("resize", setGroupViewportWidth);
document.body.addEventListener("htmx:afterSettle", setGroupViewportWidth);

// Register this view's record ids for the shared select / bulk-action
// helpers (global.js only does this for list-style data containers).
(function () {
  var container = document.getElementById("table-container-" + gbViewId);
  if (container && typeof initializeRecordIds === "function") {
    initializeRecordIds(JSON.parse(container.getAttribute("data-record-ids") || "[]"), gbViewId);
  }
  syncGroupSelectChecks();
})();

// Called from inline onclick handlers (group_by_node.html, the toolbar buttons).
window.toggleGroupRow = toggleGroupRow;
window.expandAllGroups = expandAllGroups;
window.collapseAllGroups = collapseAllGroups;
