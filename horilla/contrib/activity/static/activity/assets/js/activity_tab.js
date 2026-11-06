(function () {
  const scriptEl = document.currentScript;
  const previousElement = scriptEl?.previousElementSibling;
  const root =
    previousElement && previousElement.id === "styled-activity"
      ? previousElement
      : document.querySelectorAll("#styled-activity")[
          document.querySelectorAll("#styled-activity").length - 1
        ];
  if (!root) return;

  const DEFAULT_TOP_TAB = "tab-tasks";

  const TAB_SUBTAB_MAP = {
    "tab-tasks": "activity-followup-tabs",
    "tab-meetings": "activity-followup-tabs1",
    "tab-calls": "activity-followup-tabs2",
    "tab-email": "activity-followup-tabs3",
    "tab-events": "activity-followup-tabs4",
  };

  const initializedGroups = new Set();

  // initialSubTabDataTab: the data-tab value of the sub-tab to activate (e.g. "pending", "completed", "draft")
  function setupTabGroup(tabListId, initialSubTabDataTab) {
    if (initializedGroups.has(tabListId)) return;
    initializedGroups.add(tabListId);

    const subTabButtons = root.querySelectorAll(`#${tabListId} .fu-tab-btn`);

    subTabButtons.forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        subTabButtons.forEach((b) => {
          b.classList.remove("bg-primary-600", "text-white");
          b.classList.add("bg-primary-200", "text-primary-600");
        });
        btn.classList.remove("bg-primary-200", "text-primary-600");
        btn.classList.add("bg-primary-600", "text-white");
      });
    });

    const targetBtn = initialSubTabDataTab
      ? root.querySelector(`#${tabListId} .fu-tab-btn[data-tab="${initialSubTabDataTab}"]`)
      : null;
    const btnToClick = targetBtn || subTabButtons[0];
    if (btnToClick) {
      // Update active styles immediately
      subTabButtons.forEach((b) => {
        b.classList.remove("bg-primary-600", "text-white");
        b.classList.add("bg-primary-200", "text-primary-600");
      });
      btnToClick.classList.remove("bg-primary-200", "text-primary-600");
      btnToClick.classList.add("bg-primary-600", "text-white");

      // Use htmx.ajax() directly — element.click() fails during HTMX's
      // swap phase because listeners aren't attached yet, and hx-trigger="revealed"
      // only re-checks after scroll events (HTMX 2.x interval+scroll pattern).
      const hxGet = btnToClick.getAttribute("hx-get") || btnToClick.getAttribute("data-hx-get");
      const hxTarget = btnToClick.getAttribute("hx-target") || btnToClick.getAttribute("data-hx-target");
      if (hxGet && hxTarget) {
        htmx.ajax("GET", hxGet, { target: hxTarget, swap: "innerHTML" });
      } else {
        btnToClick.click();
      }
    }
  }

  const tabButtons = root.querySelectorAll("#activity-custom-tabs .tab-btn");
  const getTopTabContents = () =>
    root.querySelectorAll("#activity-tab-contents > .tab-content");

  const setActiveTopTab = (id, initialSubTabDataTab) => {
    const target = root.querySelector(`#${id}`);
    if (!target) return;

    tabButtons.forEach((b) => {
      b.classList.remove("bg-primary-600", "text-white");
      b.classList.add("bg-transparent", "text-[#3d3d3d]");
    });
    const topTabContents = getTopTabContents();
    topTabContents.forEach((c) => {
      c.classList.remove("block");
      c.classList.add("hidden");
      c.style.display = "none";
    });

    target.classList.remove("hidden");
    target.classList.add("block");
    target.style.display = "flex";
    const selectedButton = root.querySelector(`#activity-custom-tabs .tab-btn[data-tab="${id}"]`);
    if (selectedButton) {
      selectedButton.classList.remove("bg-transparent", "text-[#3d3d3d]");
      selectedButton.classList.add("bg-primary-600", "text-white");
    }

    const subTabListId = TAB_SUBTAB_MAP[id];
    if (subTabListId) {
      setupTabGroup(subTabListId, initialSubTabDataTab);
    }
  };

  const activateDefaultTopTab = () => {
    const savedTab = localStorage.getItem("horilla_active_activity_tab");
    // horilla_active_activity_subtab: set explicitly by the delete view (e.g. email sub-tabs)
    // horilla_pending_activity_subtab: captured from the DOM at delete-click time (pending/completed)
    const savedSubTab = localStorage.getItem("horilla_active_activity_subtab")
      || localStorage.getItem("horilla_pending_activity_subtab");
    localStorage.removeItem("horilla_active_activity_tab");
    localStorage.removeItem("horilla_active_activity_subtab");
    localStorage.removeItem("horilla_pending_activity_subtab");

    if (savedTab && root.querySelector(`#${savedTab}`)) {
      setActiveTopTab(savedTab, savedSubTab || null);
      return;
    }
    if (root.querySelector(`#${DEFAULT_TOP_TAB}`)) {
      setActiveTopTab(DEFAULT_TOP_TAB);
      return;
    }
    const firstTabId = tabButtons[0]?.getAttribute("data-tab");
    if (firstTabId) {
      setActiveTopTab(firstTabId);
    }
  };

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      const id = btn.getAttribute("data-tab");
      setActiveTopTab(id);
    });
  });

  // Before any HTMX request within the activity area, snapshot the active sub-tab
  // so it can be restored if the response triggers a full page reload.
  root.addEventListener("htmx:beforeRequest", () => {
    const activeMainBtn = root.querySelector("#activity-custom-tabs .tab-btn.bg-primary-600");
    if (!activeMainBtn) return;
    const subTabListId = TAB_SUBTAB_MAP[activeMainBtn.getAttribute("data-tab")];
    if (!subTabListId) return;
    const activeSubBtn = root.querySelector(`#${subTabListId} .fu-tab-btn.bg-primary-600`);
    if (activeSubBtn) {
      localStorage.setItem("horilla_pending_activity_subtab", activeSubBtn.getAttribute("data-tab") || "pending");
    }
  });

  activateDefaultTopTab();

  // Re-sync when the parent "Activity" tab is opened again.
  const parentActivityTabButton = document.getElementById("tab-activity");
  if (parentActivityTabButton) {
    // The parent tab button persists across re-renders of this fragment, so drop
    // the listener bound by a previous run instead of stacking another one.
    if (parentActivityTabButton._activityTabResync) {
      parentActivityTabButton.removeEventListener("click", parentActivityTabButton._activityTabResync);
    }
    parentActivityTabButton._activityTabResync = () => {
      requestAnimationFrame(activateDefaultTopTab);
    };
    parentActivityTabButton.addEventListener("click", parentActivityTabButton._activityTabResync);
  }
})();
