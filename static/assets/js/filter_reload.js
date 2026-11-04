// Handles reloading sidebar/parent view and cleaning URLs
// after filter clear/remove actions in Horilla list views.

(function () {
  // Require HTMX to be present
  if (typeof window === "undefined" || typeof window.htmx === "undefined") {
    return;
  }

  // Keep the navbar filter count badge in sync with the list that was just rendered
  // (the navbar isn't part of list responses). A MutationObserver is used because
  // htmx events don't reliably reach document after outerHTML swaps.
  if (!window._filterBadgeObserverAdded) {
    window._filterBadgeObserverAdded = true;
    let lastUrl = null;
    let lastHasBadge = null;
    const syncBadge = function () {
      const reloadEl = document.querySelector("#mainSession [data-filter-reload-url]");
      const wrapper = document.getElementById("filterToggleWrapper");
      if (!reloadEl || !wrapper) return;
      const reloadUrl = reloadEl.getAttribute("data-filter-reload-url");
      const hasBadge = !!wrapper.querySelector(".filter-count-badge");
      if (reloadUrl === lastUrl && hasBadge === lastHasBadge) return;
      let params;
      try {
        params = new URL(reloadUrl, window.location.origin).searchParams;
      } catch (e) {
        return;
      }
      const operators = params.getAll("operator");
      let count = 0;
      params.getAll("field").forEach(function (f, i) {
        if (f && operators[i]) count++;
      });
      if ((params.get("search") || "").trim()) count++;
      let badge = wrapper.querySelector(".filter-count-badge");
      if (!count) {
        if (badge) badge.remove();
        lastUrl = reloadUrl;
        lastHasBadge = false;
        return;
      }
      if (!badge) {
        badge = document.createElement("span");
        badge.className =
          "filter-count-badge absolute -top-2 lg:-top-1 bg-red-500 text-white text-[10px] leading-none rounded-full min-w-[16px] h-4 flex items-center justify-center font-medium pt-0.5";
        wrapper.appendChild(badge);
      }
      badge.textContent = count;
      lastUrl = reloadUrl;
      lastHasBadge = true;
    };
    new MutationObserver(syncBadge).observe(document.body, {
      childList: true,
      subtree: true,
    });
  }

  if (!window._filterReloadHandlerAdded) {
    window._filterReloadHandlerAdded = true;
    window._filterReloadInProgress = false;

    const handler = function (event) {
      // Only trigger for mainSession swap, and only once
      if (window._filterReloadInProgress) return;
      if (!event || !event.target || event.target.id !== "mainSession") return;

      // Prevent infinite loop - only respond to clear/remove filter requests
      const requestPath =
        (event.detail &&
          event.detail.pathInfo &&
          event.detail.pathInfo.requestPath) ||
        "";
      const isFromFilterClear =
        requestPath.includes("clear_all_filters") ||
        requestPath.includes("remove_filter");

      if (!isFromFilterClear) return;

      // Also check if the target element has our marker
      if (
        event.detail &&
        event.detail.elt &&
        event.detail.elt.hasAttribute("data-filter-reload")
      ) {
        return;
      }

      window._filterReloadInProgress = true;

      // Prefer URL provided by the rendered list view (cleaned query params)
      let url = null;
      try {
        const mainSession = event.target;
        if (mainSession) {
          const container = mainSession.querySelector(
            "[data-filter-reload-url]"
          );
          if (container) {
            url = container.getAttribute("data-filter-reload-url");
          }
        }
      } catch (e) {
        // Ignore and fall back to window.location
      }

      if (!url) {
        const base = window.location.pathname || "";
        const qs = window.location.search || "";
        url = base + qs;
      }

      const sidebar = document.getElementById("settings-sidebar");
      const parentView = document.querySelector(
        "[id$='-view']:not(#mainSession):not(#navBar)"
      );

      // Use setTimeout to ensure this happens after current swap completes
      setTimeout(function () {
        let reloadCount = 0;
        const maxReloads = 2; // sidebar + parentView

        const checkComplete = function () {
          reloadCount++;
          if (reloadCount >= maxReloads) {
            setTimeout(function () {
              window._filterReloadInProgress = false;
            }, 500);
          }
        };

        if (sidebar && !sidebar.hasAttribute("data-reloading")) {
          sidebar.setAttribute("data-reloading", "true");
          sidebar.setAttribute("data-filter-reload", "true");
          window.htmx
            .ajax("GET", url, {
              target: "#settings-sidebar",
              select: "#settings-sidebar",
              swap: "outerHTML",
              headers: { "X-Filter-Reload": "true" },
            })
            .then(function () {
              setTimeout(function () {
                sidebar.removeAttribute("data-reloading");
                sidebar.removeAttribute("data-filter-reload");
              }, 200);
              checkComplete();
            })
            .catch(function () {
              sidebar.removeAttribute("data-reloading");
              sidebar.removeAttribute("data-filter-reload");
              checkComplete();
            });
        } else {
          checkComplete();
        }

        if (parentView && !parentView.hasAttribute("data-reloading")) {
          parentView.setAttribute("data-reloading", "true");
          parentView.setAttribute("data-filter-reload", "true");

          // Update hx-get attributes instead of reloading entire parent view
          // This prevents triggering hx-trigger="load" on navBar and mainSession
          const navBar = parentView.querySelector("#navBar");
          const mainSessionEl = parentView.querySelector("#mainSession");
          const queryParams = url.indexOf("?") !== -1 ? url.split("?")[1] : "";

          if (navBar) {
            const current = navBar.getAttribute("hx-get") || "";
            const navUrl = current.split("?")[0] || "";
            navBar.setAttribute(
              "hx-get",
              navUrl + (queryParams ? "?" + queryParams : "")
            );
          }
          if (mainSessionEl) {
            const current = mainSessionEl.getAttribute("hx-get") || "";
            const listUrl = current.split("?")[0] || "";
            mainSessionEl.setAttribute(
              "hx-get",
              listUrl + (queryParams ? "?" + queryParams : "")
            );
          }

          // Update any text nodes showing request.GET.urlencode
          const walker = document.createTreeWalker(
            parentView,
            NodeFilter.SHOW_TEXT,
            null,
            false
          );
          let node;
          // eslint-disable-next-line no-cond-assign
          while ((node = walker.nextNode())) {
            const text = (node.textContent || "").trim();
            if (
              text &&
              (text.includes("search=") ||
                text.includes("field=") ||
                text.includes("clear_all_filters") ||
                text.includes("operator=") ||
                text.includes("value="))
            ) {
              node.textContent = queryParams || "";
            }
          }

          parentView.removeAttribute("data-reloading");
          parentView.removeAttribute("data-filter-reload");
          checkComplete();
        } else {
          checkComplete();
        }
      }, 100);
    };

    document.addEventListener("htmx:afterSwap", handler);
  }

  // Clean up URL immediately if clear_all_filters or remove_filter is present
  // This prevents filter operation params from persisting in subsequent requests
  const cleanupUrl = function () {
    const search = window.location.search || "";
    const urlParams = new URLSearchParams(search);
    const hasFilterOps =
      urlParams.has("clear_all_filters") || urlParams.has("remove_filter");

    if (!hasFilterOps) {
      return;
    }

    // Remove filter operation params from URL immediately
    urlParams.delete("clear_all_filters");
    urlParams.delete("remove_filter");
    const cleanedParams = urlParams.toString();
    const baseUrl = window.location.pathname;
    const cleanedUrl =
      baseUrl + (cleanedParams ? "?" + cleanedParams : "");

    // Update browser URL immediately without page reload
    window.history.replaceState({}, "", cleanedUrl);

    // Update search input hx-get attribute
    const searchInput = document.getElementById("searchInput");
    if (searchInput) {
      const hxGet = searchInput.getAttribute("hx-get");
      if (hxGet) {
        const hxGetBase = hxGet.split("?")[0];
        const hxGetParams = new URLSearchParams(
          hxGet.includes("?") ? hxGet.split("?")[1] : ""
        );
        hxGetParams.delete("clear_all_filters");
        hxGetParams.delete("remove_filter");
        const cleanedHxGetParams = hxGetParams.toString();
        searchInput.setAttribute(
          "hx-get",
          hxGetBase + (cleanedHxGetParams ? "?" + cleanedHxGetParams : "")
        );
      }
    }

    // Update all sidebar links
    const sidebar = document.getElementById("settings-sidebar");
    if (sidebar) {
      const sidebarLinks = sidebar.querySelectorAll("a[hx-get]");
      sidebarLinks.forEach(function (link) {
        const hxGet = link.getAttribute("hx-get");
        if (hxGet && hxGet.includes("?")) {
          const linkBase = hxGet.split("?")[0];
          const linkParams = new URLSearchParams(hxGet.split("?")[1]);
          linkParams.delete("clear_all_filters");
          linkParams.delete("remove_filter");
          const linkCleanedParams = linkParams.toString();
          link.setAttribute(
            "hx-get",
            linkBase + (linkCleanedParams ? "?" + linkCleanedParams : "")
          );
        }
      });
    }
  };

  // Run immediately (before any HTMX requests)
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", cleanupUrl);
  } else {
    cleanupUrl();
  }

  // Also run after HTMX events
  document.addEventListener("htmx:beforeRequest", function () {
    // Clean URL before any request to prevent filter ops from being sent
    cleanupUrl();
  });
  document.addEventListener("htmx:afterSwap", cleanupUrl);
  document.addEventListener("htmx:afterSettle", cleanupUrl);
})();
