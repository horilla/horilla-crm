// Dropdown under a list's search box. Two kinds of choice:
//   - a field to search: added to the page URL as sf=<field>:<text> and the list is
//     reloaded through the search input's own htmx request;
//   - a quick filter (My Records, Created Today, ...): an ordinary filter row
//     (field, operator, value) added to the page URL and applied exactly like the
//     filter panel's Apply, so the filter engine, the tag and saved lists treat it as
//     any other filter.
// What is applied is shown, and removed, by the navbar's applied-filter tag. The
// dropdown HTML comes from the list view (search_suggest), with counts.
(function () {
    "use strict";

    var RECENT_MAX = 5;
    // Columns of the filter rows; every row has one value in each, in the same order
    var ROW_KEYS = ["field", "operator", "value", "start_value", "end_value", "logic"];
    // Parameters the search input's hx-get leaves out: the filter panel (or the
    // search itself) supplies them, so repeating them would duplicate rows.
    var OWNED_BY_INPUT = ROW_KEYS.concat(["apply_filter", "remove_filter", "search"]);
    var DROP = ["page", "search_suggest", "hx_trigger", "clear_all_filters"];

    function init() {
        var root = document.getElementById("listSearch");
        if (!root || root.dataset.ready) return;
        root.dataset.ready = "1";

        var input = document.getElementById("searchInput");
        var dd = document.getElementById("listSearchDd");
        var suggestUrl = root.dataset.suggestUrl;
        var mainUrl = root.dataset.mainUrl;
        var recentKey = root.dataset.recentKey || "horilla_list_recent";
        var timer = null;
        var requestId = 0;
        var selected = 0;

        function getRecent() {
            try {
                return JSON.parse(localStorage.getItem(recentKey)) || [];
            } catch (e) {
                return [];
            }
        }
        function saveRecent(text) {
            text = (text || "").trim();
            if (!text) return;
            var list = getRecent().filter(function (x) {
                return x.toLowerCase() !== text.toLowerCase();
            });
            list.unshift(text);
            try {
                localStorage.setItem(recentKey, JSON.stringify(list.slice(0, RECENT_MAX)));
            } catch (e) {}
        }
        function clearRecent() {
            try {
                localStorage.removeItem(recentKey);
            } catch (e) {}
        }

        function rows() {
            return dd.querySelectorAll(".list-search-row");
        }
        function highlight() {
            rows().forEach(function (row, index) {
                row.classList.toggle("bg-slate-100", index === selected);
                if (index === selected && row.scrollIntoView) row.scrollIntoView({ block: "nearest" });
            });
        }
        function openDropdown() {
            dd.classList.toggle("hidden", !dd.innerHTML.trim());
        }
        function closeDropdown() {
            dd.classList.add("hidden");
        }

        // Recent searches (kept in this browser) are shown above the quick filters
        function recentHtml() {
            var recent = getRecent();
            if (!recent.length) return null;
            var wrap = document.createElement("div");
            var head = document.createElement("div");
            head.className = "flex justify-between px-3 pt-2 pb-1 text-[11px] font-semibold uppercase tracking-wider text-dark-400";
            var title = document.createElement("span");
            title.textContent = root.dataset.recentLabel || "Recent Searches";
            var clear = document.createElement("button");
            clear.type = "button";
            clear.dataset.clearRecent = "1";
            clear.className = "normal-case tracking-normal font-medium text-primary-600";
            clear.textContent = root.dataset.clearLabel || "Clear";
            head.appendChild(title);
            head.appendChild(clear);
            wrap.appendChild(head);
            recent.forEach(function (text) {
                var row = document.createElement("div");
                row.className = "list-search-row flex items-center gap-2 px-3 py-1.5 mx-1 rounded-md text-[13px] text-slate-800 cursor-pointer hover:bg-slate-100";
                row.dataset.type = "recent";
                row.dataset.text = text;
                var icon = document.createElement("i");
                icon.className = "fas fa-history text-xs text-dark-400";
                var label = document.createElement("span");
                label.className = "truncate";
                label.textContent = text;
                row.appendChild(icon);
                row.appendChild(label);
                wrap.appendChild(row);
            });
            return wrap;
        }

        // The page URL is the source of truth: what the tag shows is what is applied
        function suggestParams(text) {
            var params = new URLSearchParams(window.location.search);
            DROP.concat(["search", "quick_filters"]).forEach(function (key) {
                params.delete(key);
            });
            params.set("search_suggest", text);
            // Quick filters are filter rows, so only offer them where there is a filter panel
            if (root.dataset.quickFilters) params.set("quick_filters", "true");
            return params;
        }

        function loadSuggestions() {
            var text = input.value.trim();
            var id = ++requestId;
            var url = suggestUrl + (suggestUrl.indexOf("?") > -1 ? "&" : "?") + suggestParams(text).toString();
            fetch(url, {
                credentials: "same-origin",
                headers: { "HX-Request": "true", "X-Requested-With": "XMLHttpRequest" },
            })
                .then(function (response) {
                    return response.ok ? response.text() : "";
                })
                .then(function (html) {
                    if (id !== requestId) return; // a newer request replaced this one
                    dd.innerHTML = html;
                    if (!text) {
                        var recent = recentHtml();
                        if (recent) dd.insertBefore(recent, dd.firstChild);
                    }
                    selected = 0;
                    highlight();
                    openDropdown();
                })
                .catch(function () {});
        }

        // Add a filter row to the page URL and send the same request the filter panel's
        // Apply sends: same target and swap, with the navbar refreshed so the
        // applied-filter tag shows it. The element only carries those htmx attributes.
        function applyFilterRow(field, operator, value) {
            var current = new URLSearchParams(window.location.search);
            var columns = {};
            ROW_KEYS.forEach(function (key) {
                columns[key] = current.getAll(key);
            });
            var rowsKept = [];
            columns.field.forEach(function (name, index) {
                if (name && columns.operator[index]) {
                    rowsKept.push(
                        ROW_KEYS.map(function (key) {
                            return columns[key][index] || (key === "logic" ? "AND" : "");
                        })
                    );
                }
            });
            rowsKept.push([field, operator, value, "", "", "AND"]);

            var params = new URLSearchParams();
            current.forEach(function (paramValue, key) {
                if (ROW_KEYS.indexOf(key) < 0 && DROP.concat(["apply_filter", "remove_filter"]).indexOf(key) < 0) {
                    params.append(key, paramValue);
                }
            });
            rowsKept.forEach(function (row) {
                ROW_KEYS.forEach(function (key, index) {
                    params.append(key, row[index]);
                });
            });
            params.set("apply_filter", "true");

            var source = document.createElement("span");
            source.hidden = true;
            ["hx-target", "hx-select", "hx-swap", "hx-push-url"].forEach(function (name) {
                if (input.getAttribute(name)) source.setAttribute(name, input.getAttribute(name));
            });
            source.setAttribute("hx-select-oob", "#navBar");
            root.appendChild(source);
            closeDropdown();
            if (window.htmx) {
                window.htmx.process(source);
                window.htmx.ajax("GET", mainUrl + "?" + params.toString(), {
                    source: source,
                    target: input.getAttribute("hx-target"),
                    swap: "outerHTML",
                });
            }
            setTimeout(function () {
                source.remove();
            }, 1000);
        }

        // Add a field search to the page URL and reload the list the way typing does:
        // point the input's hx-get at the new URL, then fire its "search" trigger.
        function apply(name, value) {
            var params = new URLSearchParams(window.location.search);
            var hadField = params.getAll("field").some(Boolean); // a filter row is filled in
            DROP.concat(OWNED_BY_INPUT).forEach(function (key) {
                params.delete(key);
            });
            params.append(name, value);
            if (hadField) params.set("apply_filter", "true");
            input.setAttribute("hx-get", mainUrl + "?" + params.toString());
            input.value = "";
            closeDropdown();
            if (window.htmx) {
                window.htmx.process(input);
                window.htmx.trigger(input, "search");
            }
        }

        function choose(row) {
            var type = row.dataset.type;
            if (type === "field") {
                var text = row.dataset.text;
                saveRecent(text);
                if (row.dataset.field === "all") {
                    // Search every field with the typed text
                    closeDropdown();
                    if (window.htmx) window.htmx.trigger(input, "search");
                } else {
                    apply("sf", row.dataset.field + ":" + text);
                }
            } else if (type === "filter") {
                applyFilterRow(row.dataset.field, row.dataset.operator, row.dataset.value);
            } else if (type === "recent") {
                input.value = row.dataset.text;
                input.focus();
                if (window.htmx) window.htmx.trigger(input, "search");
                loadSuggestions();
            }
        }

        input.addEventListener("input", function () {
            clearTimeout(timer);
            timer = setTimeout(loadSuggestions, 150);
        });
        input.addEventListener("focus", loadSuggestions);
        input.addEventListener("keydown", function (event) {
            var all = rows();
            if (event.key === "ArrowDown") {
                event.preventDefault();
                if (dd.classList.contains("hidden")) return loadSuggestions();
                selected = Math.min(selected + 1, all.length - 1);
                highlight();
            } else if (event.key === "ArrowUp") {
                event.preventDefault();
                selected = Math.max(selected - 1, 0);
                highlight();
            } else if (event.key === "Enter") {
                event.preventDefault();
                if (!input.value.trim()) {
                    // Nothing typed: Enter must not pick a quick filter. If a search is
                    // applied, an empty box clears it.
                    closeDropdown();
                    if (new URLSearchParams(window.location.search).get("search") && window.htmx) {
                        window.htmx.trigger(input, "search");
                    }
                } else if (all[selected] && !dd.classList.contains("hidden")) {
                    choose(all[selected]);
                } else {
                    saveRecent(input.value);
                    if (window.htmx) window.htmx.trigger(input, "search");
                }
            } else if (event.key === "Escape") {
                closeDropdown();
            }
        });

        // Mouse: keep focus in the input while using the dropdown
        dd.addEventListener("mousedown", function (event) {
            event.preventDefault();
        });
        dd.addEventListener("click", function (event) {
            if (event.target.closest("[data-clear-recent]")) {
                clearRecent();
                loadSuggestions();
                return;
            }
            var row = event.target.closest(".list-search-row");
            if (row) choose(row);
        });
        document.addEventListener("click", function (event) {
            if (!root.contains(event.target)) closeDropdown();
        });
    }

    document.addEventListener("DOMContentLoaded", init);
    document.addEventListener("htmx:load", init);
    init();
})();
