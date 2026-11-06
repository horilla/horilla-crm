(function () {
    if (!window.horillaFormLayouts) {
        window.horillaFormLayouts = {
            // Navbar Cancel: confirm if there are unsaved changes, then reload the editor.
            cancel: function (button) {
                var form = document.getElementById("form-layout-form");
                if (form && form.dataset.dirty === "true" && typeof hxConfirm === "function") {
                    hxConfirm(button, button.dataset.confirm);
                } else {
                    htmx.trigger(button, "confirmed");
                }
            },
            init: function (form) {
                if (!form || form.dataset.layoutReady === "1") {
                    return;
                }
                form.dataset.layoutReady = "1";

                var list = form.querySelector("[data-sortable-list]");
                var dirty = false;
                var sortable = null;
                var tab = "all";
                var searchBox = form.querySelector("[data-layout-search]");
                var emptyNote = form.querySelector("[data-layout-empty]");

                function optionalBoxes() {
                    return Array.prototype.slice.call(
                        list.querySelectorAll('.form-layout-item:not(.hidden) input[name="visible"]')
                    );
                }

                function isShown(item) {
                    var box = item.querySelector('input[name="visible"]');
                    return !box || box.checked;
                }

                function isFiltering() {
                    return tab !== "all" || searchBox.value.trim() !== "";
                }

                function applyFilter() {
                    var query = searchBox.value.trim().toLowerCase();
                    var items = list.querySelectorAll(".form-layout-item");
                    var matching = 0;
                    items.forEach(function (item) {
                        var shown = isShown(item);
                        var ok = (!query || item.dataset.label.indexOf(query) !== -1) &&
                            (tab === "all" || (tab === "shown") === shown);
                        item.classList.toggle("hidden", !ok);
                        if (ok) {
                            matching += 1;
                        }
                    });
                    var dragLocked = query !== "" || tab === "hidden";
                    if (sortable) {
                        sortable.option("disabled", dragLocked);
                    }
                    list.querySelectorAll(".form-layout-handle").forEach(function (handle) {
                        handle.classList.toggle("hidden", dragLocked);
                    });
                    list.classList.toggle("hidden", matching === 0);
                    emptyNote.classList.toggle("hidden", matching !== 0);
                    if (matching === 0) {
                        // Name the real reason: the search text wins over the tab.
                        var reason = query ? "textSearch" : (tab === "shown" ? "textShown" : "textHidden");
                        emptyNote.querySelector("[data-layout-empty-text]").textContent = emptyNote.dataset[reason];
                        var clear = emptyNote.querySelector("[data-layout-clear]");
                        clear.dataset.reason = query ? "search" : "tab";
                        clear.textContent = query ? clear.dataset.labelSearch : clear.dataset.labelTab;
                    }
                    refresh();
                }

                function markDirty() {
                    dirty = true;
                    form.dataset.dirty = "true";
                    var note = form.querySelector("[data-layout-dirty-note]");
                    if (note) {
                        note.classList.remove("hidden");
                        note.classList.add("inline-flex");
                    }
                }

                function refresh() {
                    var items = list.querySelectorAll(".form-layout-item");
                    var shown = 0;
                    var filtering = isFiltering();
                    items.forEach(function (item, index) {
                        item.querySelector(".form-layout-position").textContent = index + 1;
                        item.querySelector('[data-layout-move="up"]').disabled = filtering || index === 0;
                        item.querySelector('[data-layout-move="down"]').disabled = filtering || index === items.length - 1;
                        var box = item.querySelector('input[name="visible"]');
                        var visible = !box || box.checked;
                        if (visible) {
                            shown += 1;
                        }
                        item.classList.toggle("opacity-60", !visible);
                        item.classList.toggle("bg-gray-50", !visible);
                        item.classList.toggle("bg-white", visible);
                    });
                    // One bulk button: "Hide optional" while every listed optional field is on, else "Show all".
                    var boxes = optionalBoxes();
                    var bulk = form.querySelector("[data-layout-bulk]");
                    var allOn = boxes.length > 0 && boxes.every(function (box) { return box.checked; });
                    var mode = allOn ? "hide" : "show";
                    bulk.dataset.mode = mode;
                    bulk.disabled = boxes.length === 0;
                    // aria-label, not title: the global tooltip script restores a stale title after hover.
                    bulk.setAttribute("aria-label", bulk.dataset[mode === "hide" ? "titleHide" : "titleShow"]);
                    bulk.querySelector("[data-layout-bulk-label]").textContent = bulk.dataset[mode === "hide" ? "labelHide" : "labelShow"];
                    bulk.querySelector("[data-layout-bulk-icon]").className = "fas " + (mode === "hide" ? "fa-eye-slash" : "fa-eye");
                    var counts = {all: items.length, shown: shown, hidden: items.length - shown};
                    Object.keys(counts).forEach(function (key) {
                        var node = form.querySelector('[data-layout-count="' + key + '"]');
                        if (node) {
                            node.textContent = counts[key];
                        }
                    });
                }

                if (typeof Sortable !== "undefined") {
                    sortable = new Sortable(list, {
                        animation: 150,
                        handle: ".form-layout-handle",
                        draggable: ".form-layout-item",
                        forceFallback: true,
                        fallbackOnBody: true,
                        ghostClass: "opacity-40",
                        onEnd: function (event) {
                            if (event.oldIndex !== event.newIndex) {
                                markDirty();
                            }
                            refresh();
                        },
                    });
                }

                list.addEventListener("click", function (event) {
                    var button = event.target.closest("[data-layout-move]");
                    if (!button || button.disabled) {
                        return;
                    }
                    var item = button.closest(".form-layout-item");
                    if (button.dataset.layoutMove === "up" && item.previousElementSibling) {
                        list.insertBefore(item, item.previousElementSibling);
                    } else if (button.dataset.layoutMove === "down" && item.nextElementSibling) {
                        list.insertBefore(item.nextElementSibling, item);
                    }
                    markDirty();
                    refresh();
                    item.scrollIntoView({ block: "nearest" });
                    if (!button.disabled) {
                        button.focus();
                    }
                });

                // Only the rows currently listed change, so a search narrows the bulk action.
                form.addEventListener("click", function (event) {
                    var bulk = event.target.closest("[data-layout-bulk]");
                    if (!bulk || bulk.disabled) {
                        return;
                    }
                    var show = bulk.dataset.mode === "show";
                    optionalBoxes().forEach(function (box) {
                        box.checked = show;
                    });
                    markDirty();
                    refresh();
                });

                list.addEventListener("change", function (event) {
                    if (event.target.name === "visible") {
                        markDirty();
                        refresh();
                    }
                });

                searchBox.addEventListener("input", applyFilter);
                searchBox.addEventListener("keydown", function (event) {
                    if (event.key === "Enter") {
                        event.preventDefault();
                    }
                });
                form.addEventListener("click", function (event) {
                    var tabButton = event.target.closest("[data-layout-tab]");
                    if (tabButton) {
                        tab = tabButton.dataset.layoutTab;
                        form.querySelectorAll("[data-layout-tab]").forEach(function (node) {
                            node.dataset.active = node === tabButton ? "true" : "false";
                        });
                        applyFilter();
                        return;
                    }
                    var clearButton = event.target.closest("[data-layout-clear]");
                    if (clearButton) {
                        searchBox.value = "";
                        // Clearing a search keeps the tab; an empty tab goes back to All.
                        if (clearButton.dataset.reason !== "search") {
                            tab = "all";
                            form.querySelectorAll("[data-layout-tab]").forEach(function (node) {
                                node.dataset.active = node.dataset.layoutTab === "all" ? "true" : "false";
                            });
                        }
                        applyFilter();
                        searchBox.focus();
                        return;
                    }
                });

                refresh();
            },
        };
        document.addEventListener("confirmed", function (event) {
            var button = event.target.closest && event.target.closest("[data-layout-cancel]");
            if (button) {
                htmx.ajax("GET", button.dataset.cancelUrl, {
                    target: "#form-layout-editor",
                    swap: "outerHTML",
                });
            }
        });
        document.addEventListener("htmx:historyRestore", function () {
            window.horillaFormLayouts.init(document.getElementById("form-layout-form"));
        });
    }
    window.horillaFormLayouts.init(document.getElementById("form-layout-form"));
})();
