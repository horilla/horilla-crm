/* ==========================================================================
   Summernote XSS Protection - Sanitizes HTML before rendering
   ========================================================================== */
(function() {
    if (typeof DOMPurify === 'undefined' || typeof $ === 'undefined') return;

    // Dangerous CSS value patterns — block expression() and url() inside style tags/attrs.
    // DOMPurify cannot inspect CSS content, so we strip it with a pre-pass regex.
    var CSS_DANGEROUS = /expression\s*\(|url\s*\(/gi;

    // Wipe <style> tag content while keeping the tag itself, then let DOMPurify
    // handle everything else. This mirrors the server-side bleach sanitizer behaviour.
    function stripStyleTagContent(html) {
        return html.replace(/<style[^>]*>([\s\S]*?)<\/style>/gi, function(match, content) {
            return match.replace(content, '');
        });
    }

    // Remove dangerous CSS functions from inline style attributes.
    function stripDangerousInlineStyles(html) {
        return html.replace(/style\s*=\s*["']([^"']*)["']/gi, function(match, css) {
            if (CSS_DANGEROUS.test(css)) {
                CSS_DANGEROUS.lastIndex = 0;
                return 'style=""';
            }
            return match;
        });
    }

    var purifyConfig = {
        USE_PROFILES: { html: true },
        ALLOW_DATA_ATTR: true,
        FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'applet', 'link', 'svg', 'math'],
        FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover', 'onfocus', 'onblur',
            'onmouseout', 'onkeydown', 'onkeyup', 'onkeypress', 'onchange', 'onsubmit',
            'onmousedown', 'onmouseup', 'ondblclick', 'oncontextmenu', 'ondrag', 'ondrop']
    };

    function sanitize(html) {
        var result = stripStyleTagContent(html);
        result = stripDangerousInlineStyles(result);
        return DOMPurify.sanitize(result, purifyConfig);
    }

    // Function to sanitize code area content
    function sanitizeCodeArea($editor) {
        var $codeArea = $editor.find('.note-codable');
        if ($codeArea.length) {
            var rawCode = $codeArea.val();
            var sanitized = sanitize(rawCode);
            if (rawCode !== sanitized) {
                $codeArea.val(sanitized);
            }
        }
    }

    // Intercept codeview button clicks BEFORE summernote processes them
    // This ensures we sanitize the code textarea content before it gets rendered
    // Using multiple selectors to cover different Summernote versions
    $(document).on('mousedown touchstart', [
        '.note-btn[data-original-title="Code View"]',
        '.note-btn.btn-codeview',
        'button[data-tooltip="codeview"]',
        '.btn-codeview',
        '[data-name="codeview"]',
        '.note-toolbar button:contains("</>")'
    ].join(', '), function(e) {
        var $btn = $(this);
        var $editor = $btn.closest('.note-editor');
        var isInCodeView = $editor.hasClass('codeview');

        // If currently in code view and about to switch to normal view
        if (isInCodeView) {
            sanitizeCodeArea($editor);
        }
    });

    // Also catch keyboard shortcut (Ctrl+Shift+C or Cmd+Shift+C)
    $(document).on('keydown', '.note-codable', function(e) {
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'C' || e.key === 'c' || e.keyCode === 67)) {
            var $editor = $(this).closest('.note-editor');
            sanitizeCodeArea($editor);
        }
    });

    // Patch jQuery's html() method for .note-editable elements to sanitize content
    var originalHtml = $.fn.html;
    $.fn.html = function(value) {
        if (value !== undefined && this.hasClass('note-editable')) {
            value = sanitize(value);
        }
        return originalHtml.apply(this, arguments.length ? [value] : []);
    };

    // Also intercept when summernote sets content via 'code' command
    $(document).on('summernote.codeview.toggled', function(e, isCodeView) {
        if (!isCodeView) {
            var $target = $(e.target);
            setTimeout(function() {
                try {
                    var content = $target.summernote('code');
                    var sanitized = sanitize(content);
                    if (content !== sanitized) {
                        $target.summernote('code', sanitized);
                    }
                } catch(err) {}
            }, 0);
        }
    });

    // Sanitize on paste globally
    $(document).on('summernote.paste', function(e) {
        var $target = $(e.target);
        setTimeout(function() {
            try {
                var content = $target.summernote('code');
                var sanitized = sanitize(content);
                if (content !== sanitized) {
                    $target.summernote('code', sanitized);
                }
            } catch(err) {}
        }, 50);
    });

    // Summernote's toggleList() (list.js/bullet.js) converts the *entire*
    // list element the caret sits in, rather than just the current line.
    // So switching one line from UL to OL flips every sibling <li> in that
    // same list to the new marker type too. Split the list at the caret
    // first so the toggle only ever applies to an isolated single-item list.
    function splitListAtCaret(listTagToAvoid) {
        var sel = window.getSelection();
        if (!sel || !sel.rangeCount) return;
        var node = sel.getRangeAt(0).startContainer;
        var li = node.nodeType === 3 ? node.parentElement : node;
        li = li && li.closest ? li.closest('li') : null;
        if (!li) return;

        var list = li.parentElement;
        if (!list || list.tagName !== listTagToAvoid) return;

        // Nothing to split off before this <li>: it's already alone at the top.
        if (!li.previousElementSibling) return;

        var newList = document.createElement(list.tagName);
        // Move this <li> and everything after it into the new list.
        while (li.nextSibling) {
            newList.appendChild(li.nextSibling);
        }
        newList.insertBefore(li, newList.firstChild);
        list.parentNode.insertBefore(newList, list.nextSibling);

        // Re-place the caret inside the (now isolated) moved <li>.
        var range = document.createRange();
        range.selectNodeContents(li);
        range.collapse(true);
        sel.removeAllRanges();
        sel.addRange(range);
    }

    $(document).on('mousedown', '.note-btn:has(.note-icon-unorderedlist)', function() {
        splitListAtCaret('OL');
    });
    $(document).on('mousedown', '.note-btn:has(.note-icon-orderedlist)', function() {
        splitListAtCaret('UL');
    });
})();

// Internationalization messages
const horillaMessages = {
    confirm: gettext("Confirm"),
    close: gettext("Close"),
    cancel: gettext("Cancel"),
    selected: gettext("Selected"),
    downloadExcel: gettext("Do you want to download the excel file?"),
    downloadTemplate: gettext("Do you want to download the template?"),
    noRowsSelected: gettext("No rows are selected from the records."),
    confirmBulkDelete: gettext("Do you really want to delete all the selected records?"),
    confirmBulkArchive: gettext("Do you really want to archive all the selected records?"),
    confirmBulkUnArchive: gettext("Do you really want to unarchive all the selected records?"),
};


const ModalManager = {
    stack: [],
    baseZIndex: 1000,

    open(modalId, modalBoxId, clearContentOnClose = true) {
        const $modal = $(`#${modalId}`);
        const $modalBox = $(`#${modalBoxId}`);

        // Calculate and apply z-index based on stack position
        const currentZIndex = this.baseZIndex + (this.stack.length * 10);
        $modal.css('z-index', currentZIndex);

        // Add to stack
        this.stack.push({
            id: modalId,
            boxId: modalBoxId,
            zIndex: currentZIndex,
            clearContentOnClose: clearContentOnClose
        });

        // Show modal
        $modal.removeClass("hidden").addClass("flex");
        setTimeout(() => {
            $modalBox.removeClass("opacity-0 scale-95").addClass("opacity-100 scale-100");
        }, 10);

        // Lock body scroll if first modal
        if (this.stack.length === 1) {
            $('body').css('overflow', 'hidden');
        }
    },

    close(modalId, modalBoxId, clearContent = true) {
        const $modal = $(`#${modalId}`);
        const $modalBox = $(`#${modalBoxId}`);

        if (clearContent) $modalBox.html("");
        $modalBox.removeClass("opacity-100 scale-100").addClass("opacity-0 scale-95");

        setTimeout(() => {
            $modal.removeClass("flex").addClass("hidden");
            // Reset z-index when closing
            $modal.css('z-index', '');
        }, 300);

        // Remove from stack
        this.stack = this.stack.filter(m => m.id !== modalId);

        // Unlock body scroll if no modals
        if (this.stack.length === 0) {
            $('body').css('overflow', '');
        }
    },

    closeTop() {
        if (this.stack.length > 0) {
            const topModal = this.stack[this.stack.length - 1];
            this.close(topModal.id, topModal.boxId, topModal.clearContentOnClose);
        }
    },

    closeAll() {
        // Close in reverse order
        const modalsToClose = [...this.stack].reverse();
        modalsToClose.forEach(modal => {
            this.close(modal.id, modal.boxId, modal.clearContentOnClose);
        });
    }
};


// Modal functions using ModalManager
function OpenDeleteConfirmModal() { ModalManager.open("deleteConfirmModal", "deleteConfirmModalBox"); }
function CloseDeleteConfirmModal() { ModalManager.close("deleteConfirmModal", "deleteConfirmModalBox"); }
function openDynamicModal() { ModalManager.open("dynamicCreateModal", "dynamicCreateModalBox"); }
function closeDynamicModal() { ModalManager.close("dynamicCreateModal", "dynamicCreateModalBox"); }
function openContentModal() { ModalManager.open("contentModal", "contentModalBox"); }
function closeContentModal() { ModalManager.close("contentModal", "contentModalBox"); }
function openCalendarPreviewModal() { ModalManager.open("calendarPreviewModal", "calendarPreviewModalBox"); }
function closeCalendarPreviewModal() { ModalManager.close("calendarPreviewModal", "calendarPreviewModalBox"); }
function openContentModalSecond() { ModalManager.open("contentModalSecond", "contentModalBoxSecond"); }
function closeContentModalSecond() { ModalManager.close("contentModalSecond", "contentModalBoxSecond"); }
function openDetailModal() { ModalManager.open("detailModal", "detailModalBox"); }
function closeDetailModal() { ModalManager.close("detailModal", "detailModalBox"); }
function openModal() { ModalManager.open("dbmodal", "modalBox"); }
function closeModal() { ModalManager.close("dbmodal", "modalBox"); }
function openhorillaModal() { ModalManager.open("horillaModal", "horillaModalBox"); }
function closehorillaModal() { ModalManager.close("horillaModal", "horillaModalBox"); }
function openFilterModal() { ModalManager.open("filtermodal", "filtermodalBox"); }
function closeFilterModal() { ModalManager.close("filtermodal", "filtermodalBox"); }
function openDeleteModal() { ModalManager.open("deletemodal", "deleteBox"); }
function closeDeleteModal() { ModalManager.close("deletemodal", "deleteBox"); }
function openDeleteModeModal() { ModalManager.open("deleteModeModal", "deleteModeBox"); }
function closeDeleteModeModal() { ModalManager.close("deleteModeModal", "deleteModeBox"); }
function openExport(viewId) {
    if (!viewId) {
        return;
    }
    ModalManager.open(`exportModal-${viewId}`, `exportBox-${viewId}`, false);
}

function closeExport(viewId) {
    if (viewId) {
        ModalManager.close(`exportModal-${viewId}`, `exportBox-${viewId}`, false);
    } else {
        ModalManager.close("exportModal", "exportBox", false);
    }
}
document.body.addEventListener("openNotificationDetailModal", function () { openModal(); });

function closeConfirm(button) {
    const modal = button.closest(".modal-wrapper");
    modal.classList.add("hidden");
}

function toggleAccordion(button) {
    const content = button.nextElementSibling;
    const svg = button.querySelector("svg");
    content.classList.toggle("open");
    svg.classList.toggle("rotate-90");
}

function isElementVisible(element) {
    const $targetSelector = $(element).attr("hx-target");
    const $targetEl = $($targetSelector);
    const isOpen = $targetEl.css("max-height") && $targetEl.css("max-height") !== "0px";
    return !isOpen;
}

// Bulk delete with validation
function doBulkDeleteRequest(element) {
    const viewId = $(element).attr("id").replace("bulk-delete-btn-", "");
    const selectedIds = selectedRecordIds(viewId);

    if (selectedIds.length > 0) {
        htmx.trigger(element, "doRequest");
    } else {
        const modalContent = `
            <div class="p-6 text-center">
                <div class="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-red-100 text-red-600">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                              d="M12 9v2m0 4h.01M12 2a10 10 0 11-0 20 10 10 0 010-20z" />
                    </svg>
                </div>
                <h2 class="text-lg font-semibold text-gray-800 mb-2">No Rows Selected</h2>
                <p class="text-sm text-gray-500 mb-6">Please select at least one record before attempting to delete.</p>
                <button id="closeDbModal" class="px-6 py-2.5 text-sm border-[1px] border-[solid] bg-secondary-600 rounded-[5px] text-white btn-with-icon border-[#e54f38] [transition:.3s]">
                    Close
                </button>
            </div>
        `;

        $("#deleteModeBox").html(modalContent);
        $("#deleteModeModal").removeClass("hidden").addClass("flex");

        setTimeout(() => {
            $("#deleteModeBox").removeClass("opacity-0 scale-95").addClass("opacity-100 scale-100");
        }, 10);

        $("#closeDbModal").on("click", function () {
            closeDeleteModeModal();
        });
    }
}

// Select2 formatting
function formatOption(option) {
    if (!option.id) return option.text;

    var imgSrc = $(option.element).data('img');
    if (imgSrc) {
        return $('<span><img src="' + imgSrc + '" class="w-6 h-6 rounded-full inline-block me-2" /> ' + option.text + '</span>');
    }
    return option.text;
}

// Sidebar Management
const SidebarManager = {
    getAppLabelFromUrl() {
        const path = window.location.pathname;
        const pathParts = path.split('/').filter(part => part.length > 0);
        // Match against actual sidebar link IDs to skip common URL prefixes (e.g. "crm/")
        const $links = $("ul a.sidebar-link");
        for (const part of pathParts) {
            if ($links.filter(`#${CSS.escape(part)}`).length > 0) return part;
        }
        return pathParts[0] || 'core';
    },

    /** Find a subsection link whose href path matches or is a prefix of the current path, or whose base path (all but last segment) is a prefix of the current path. */
    getSubsectionLinkMatchingUrl() {
        const currentPath = window.location.pathname;
        const currentNorm = currentPath.replace(/\/+$/, "") || "/";
        let $exactFound = null;
        let exactLongest = 0;
        let $segmentFound = null;
        let segmentLongest = 0;
        $("ul a.sidebar-link").each(function () {
            const href = $(this).attr("href");
            if (!href) return;
            const linkPath = href.indexOf("?") >= 0 ? href.split("?")[0] : href;
            const path = linkPath.startsWith("http") ? new URL(linkPath).pathname : (linkPath.startsWith("/") ? linkPath : "/" + linkPath);
            const pathNorm = path.replace(/\/+$/, "") || "/";
            const exactMatch = currentNorm === pathNorm || (currentNorm.length > pathNorm.length && currentNorm.indexOf(pathNorm) === 0 && (pathNorm === "/" || currentNorm.charAt(pathNorm.length) === "/"));

            const linkSegments = pathNorm.split("/").filter(Boolean);
            const linkBasePath = linkSegments.length > 1 ? "/" + linkSegments.slice(0, -1).join("/") : null;
            const appScopeMatch = linkBasePath && (currentNorm === linkBasePath || currentNorm.startsWith(linkBasePath + "/"));
            if (exactMatch && pathNorm.length > exactLongest) {
                exactLongest = pathNorm.length;
                $exactFound = $(this);
            } else if (!exactMatch && appScopeMatch && pathNorm.length > segmentLongest) {
                segmentLongest = pathNorm.length;
                $segmentFound = $(this);
            }
        });
        return ($exactFound && $exactFound.length ? $exactFound : null) || ($segmentFound && $segmentFound.length ? $segmentFound : null);
    },

    /** App label for sidebar logic; from DOM (URL-matching link) so it works after full load and HTMX. */
    getResolvedAppLabel() {
        const $link = this.getSubsectionLinkMatchingUrl();
        if ($link && $link.length) return $link.attr("id") || this.getAppLabelFromUrl();
        return this.getAppLabelFromUrl();
    },

    getSectionFromAppLabel(appLabel) {
        const APP_SECTION_MAPPING = window.APP_SECTION_MAPPING || {};
        for (const [section, apps] of Object.entries(APP_SECTION_MAPPING)) {
            if (Array.isArray(apps) && apps.includes(appLabel)) {
                return section;
            }
        }
        const $link = $(`ul a.sidebar-link#${CSS.escape(appLabel)}`);
        if ($link.length) return $link.attr("data-section") || "home";
        return "home";
    },

    /** Settings and My Settings belong to no main section, so no main menu item is highlighted there. */
    isSettingsPage() {
        return $("#settings-sidebar, #my-settings-sidebar").length > 0;
    },

    getActiveSection() {
        const urlParams = new URLSearchParams(window.location.search);
        const sectionFromUrl = urlParams.get("section");
        if (sectionFromUrl) return sectionFromUrl;
        if (this.isSettingsPage()) return null;

        const $link = this.getSubsectionLinkMatchingUrl();
        if ($link && $link.length) return $link.attr("data-section") || "home";

        const appLabel = this.getResolvedAppLabel();
        const sectionFromApp = this.getSectionFromAppLabel(appLabel);
        return sectionFromApp || localStorage.getItem("currentActiveSection") || "home";
    },

    getSectionSpecificSubsectionId(sectionId) {
        return localStorage.getItem(`activeSidebarLinkId_${sectionId}`) || localStorage.getItem("activeSidebarLinkId");
    },

    setActiveNavLink($link, sectionId) {
        const $navLinks = $("nav a.nav-link");
        $navLinks.removeClass('bg-primary-600 hover:bg-primary-800');
        $link.addClass('bg-primary-600 hover:bg-primary-800');
        localStorage.setItem("activeNavLinkId", sectionId);
        localStorage.setItem("currentActiveSection", sectionId);

        if (sectionId === "home") {
            localStorage.setItem("sidebarClicked", "false");
            localStorage.removeItem("activeSidebarLinkId");
            localStorage.removeItem("activeSidebarLinkId_home");
        }
    },

    setActiveSubsectionLink($link, sectionId) {
        $("ul a.sidebar-link").removeClass("bg-primary-600 text-white");
        $link.addClass("bg-primary-600 text-white");

        const linkId = $link.attr("id");
        if (linkId && sectionId) {
            localStorage.setItem(`activeSidebarLinkId_${sectionId}`, linkId);
            localStorage.setItem("activeSidebarLinkId", linkId);
            localStorage.setItem("sidebarClicked", "true");
        }
    },

    activateFirstSubsectionItem(sectionId) {
        if (!sectionId) return;
        const $subsectionLinks = $("ul a.sidebar-link").filter(`[data-section="${sectionId}"]`);
        if (!$subsectionLinks.length) {
            const $allLinks = $("ul a.sidebar-link");
            if (!$allLinks.length) return;
        }

        let $activeLink = null;
        const sidebarClicked = localStorage.getItem("sidebarClicked") === "true";
        const activeSubItemId = this.getSectionSpecificSubsectionId(sectionId);
        const lastActiveSection = localStorage.getItem("lastActiveSection");
        const appLabel = this.getResolvedAppLabel();

        const isSectionSwitch = lastActiveSection && lastActiveSection !== sectionId;

        const $appLabelLink = $subsectionLinks.filter(`#${appLabel}`);
        if ($appLabelLink.length) {
            $activeLink = $appLabelLink;
        } else if (isSectionSwitch || !sidebarClicked || sectionId === "home") {
            $activeLink = $subsectionLinks.first();
            const firstLinkId = $activeLink ? $activeLink.attr("id") : null;
            if (firstLinkId) {
                localStorage.setItem(`activeSidebarLinkId_${sectionId}`, firstLinkId);
                localStorage.setItem("activeSidebarLinkId", firstLinkId);
                localStorage.setItem("sidebarClicked", "false");
            }
        } else {
            $activeLink = activeSubItemId ? $subsectionLinks.filter(`#${activeSubItemId}`) : $subsectionLinks.first();

            if (!$activeLink.length) {
                $("#hiddenReloadSidebar").click();
                console.warn("No sub-sidebar link found, triggering reload.");
                return;
            }
        }

        if ($activeLink && $activeLink.length) {
            this.setActiveSubsectionLink($activeLink, sectionId);
        } else {
            const $fallbackLink = $subsectionLinks.first() || $("ul a.sidebar-link").first();
            if ($fallbackLink.length) {
                this.setActiveSubsectionLink($fallbackLink, sectionId);
            }
        }

        localStorage.setItem("lastActiveSection", sectionId);
    },

    initFromUrl() {
        const currentSection = this.getActiveSection();
        const $navLinks = $("nav a.nav-link");
        const $sectionLink = $navLinks.filter(`#${currentSection}`);

        if ($sectionLink.length) {
            this.setActiveNavLink($sectionLink, currentSection);
        }

        const currentHref = window.location.href;
        localStorage.setItem('last-visited-url', currentHref);

        this.activateFirstSubsectionItem(currentSection);
    }
};

// Sidebar collapse/expand
function initSidebar() {
    const sideMenu = document.getElementById("sideMenu");
    const toggleBtn = document.getElementById("toggleSideMenu");
    const arrowIcon = document.getElementById("arrowIcon");
    const mainContent = document.getElementById("mainContent");
    const kanbanView = document.getElementById("kanbanview");

    if (!sideMenu || !toggleBtn || !arrowIcon || !mainContent) return;

    const isRtl = document.documentElement.dir === "rtl";
    const inlineStartProp = isRtl ? "right" : "left";
    const subSidebarMarginClass = isRtl ? "mr-[230px]" : "ml-[230px]";

    function setInlineStart(el, value) {
        el.style.left = "";
        el.style.right = "";
        el.style[inlineStartProp] = value;
    }

    // Remove the pre-paint CSS override so JS classes take over without flash
    document.documentElement.removeAttribute("data-sidebar-collapsed");

    // Suppress transition briefly so the initial state applies instantly
    sideMenu.style.transition = "none";
    requestAnimationFrame(() => { sideMenu.style.transition = ""; });

    const STORAGE_KEY = "sidebarCollapsed";
    let isCollapsed = false;

    function collapseMenu() {
        sideMenu.classList.add("w-0");
        sideMenu.classList.remove("w-[230px]");
        arrowIcon.classList.add("scale-x-[-1]");
        mainContent.classList.remove("leftspace");
        setInlineStart(toggleBtn, "calc(5rem - 10px)");

        if (kanbanView) {
            kanbanView.classList.add("w-full");
            kanbanView.classList.remove(subSidebarMarginClass);
        }
        isCollapsed = true;
    }

    function expandMenu() {
        sideMenu.classList.remove("w-0");
        sideMenu.classList.add("w-[230px]");
        arrowIcon.classList.remove("scale-x-[-1]");
        mainContent.classList.add("leftspace");
        setInlineStart(toggleBtn, "calc(5rem + 230px - 10px)");

        if (kanbanView) {
            kanbanView.classList.remove("w-full");
        }
        isCollapsed = false;
    }

    toggleBtn.onclick = () => {
        if (isCollapsed) {
            expandMenu();
        } else {
            collapseMenu();
        }
        // Persist user's manual choice only on wide screens
        if (window.innerWidth >= 992) {
            localStorage.setItem(STORAGE_KEY, isCollapsed ? "true" : "false");
        }
    };

    function adjustSidebar() {
        if (window.innerWidth < 992) {
            collapseMenu();
        } else {
            // Restore user's saved preference on wide screens
            const saved = localStorage.getItem(STORAGE_KEY);
            if (saved === "true") {
                collapseMenu();
            } else {
                expandMenu();
            }
        }
    }

    adjustSidebar();
    window.onresize = adjustSidebar;
}

function togglePassword() {
    const passwordInput = document.getElementById('passwordInput');
    const eyeIcon = document.getElementById('eyeIcon');
    const eyeHideIcon = document.getElementById('eyeHideIcon');

    if (passwordInput.type === 'password') {
        passwordInput.type = 'text';
        eyeIcon.classList.add('hidden');
        eyeHideIcon.classList.remove('hidden');
    } else {
        passwordInput.type = 'password';
        eyeIcon.classList.remove('hidden');
        eyeHideIcon.classList.add('hidden');
    }
}

// Table Management
const tableData = new Map();

function getCurrentViewId(element) {
    const $tableContainer = $(element).closest("[id^='table-container-']");
    return $tableContainer.data("view-id") || "";
}

function initializeRecordIds(recordIds, viewId) {
    if (!viewId) {
        console.warn("No viewId provided");
        return;
    }

    tableData.set(viewId, {
        allRecordIds: recordIds && Array.isArray(recordIds) && recordIds.length ? recordIds.map(String) : [],
        selectedRecordIds: [],
        allSelected: false,
    });

    const table = tableData.get(viewId);
    const $tableContainer = $(`#table-container-${viewId}`);

    if (table.allRecordIds.length) {
        $tableContainer.find(".total-count").text(table.allRecordIds.length);
        const storedSelections = sessionStorage.getItem(`selectedRecordIds_${viewId}`);
        if (storedSelections) {
            try {
                table.selectedRecordIds = JSON.parse(storedSelections).map(String);
                table.allSelected =
                    table.selectedRecordIds.length === table.allRecordIds.length &&
                    table.allRecordIds.every((id) => table.selectedRecordIds.includes(id));
            } catch (e) {
                console.error("Error parsing stored selections for viewId", viewId, e);
                table.selectedRecordIds = [];
            }
        }
        updateCheckboxStates(viewId);
        updateActionButtonsVisibility(viewId);
    }
}

function selectAll(checked, viewId) {
    if (!viewId) return;
    const table = tableData.get(viewId);
    if (!table) return;

    table.allSelected = checked;
    table.selectedRecordIds = checked ? [...table.allRecordIds] : [];
    sessionStorage.setItem(`selectedRecordIds_${viewId}`, JSON.stringify(table.selectedRecordIds));

    const $tableContainer = $(`#table-container-${viewId}`);
    $tableContainer.find("input[data-role='row-select']").prop("checked", checked);
    $tableContainer.find("input[data-role='select-all']").prop("checked", checked);

    updateActionButtonsVisibility(viewId);
}

function clearSelections(viewId) {
    if (!viewId) return;
    const table = tableData.get(viewId);
    if (!table) return;

    table.selectedRecordIds = [];
    table.allSelected = false;
    sessionStorage.removeItem(`selectedRecordIds_${viewId}`);

    const $tableContainer = $(`#table-container-${viewId}`);
    $tableContainer.find("input[data-role='row-select']").prop("checked", false);
    $tableContainer.find("input[data-role='select-all']").prop("checked", false);

    updateActionButtonsVisibility(viewId);
}

function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

const updateActionButtonsVisibility = debounce(function (viewId) {
    if (!viewId) return;
    const table = tableData.get(viewId);
    if (!table) return;

    const totalSelectedCount = table.selectedRecordIds.length;
    const hasSelections = totalSelectedCount > 0;

    $(`#export-all-btn-${viewId}, #bulk-update-btn-${viewId}, #unselect-all-btn-${viewId}, #bulk-delete-btn-${viewId}, [id^="bulk-action-"][id$="-${viewId}"]`)
        .toggle(hasSelections);

    if (hasSelections) {
        $(`#selected-text-${viewId}`).text(`${totalSelectedCount}`);
        $(`#unselect-text-${viewId}`).text(`${totalSelectedCount}`);
    }

    $(`#select-all-btn-${viewId}`).toggle(table.allRecordIds.length > 0 && !table.allSelected);
}, 100);

function updateCheckboxStates(viewId) {
    if (!viewId) return;
    const table = tableData.get(viewId);
    if (!table) return;

    const $tableContainer = $(`#table-container-${viewId}`);
    $tableContainer.find("input[data-role='row-select']").each(function () {
        const id = $(this).val();
        $(this).prop("checked", table.selectedRecordIds.includes(id));
    });

    const checkedCount = $tableContainer.find("input[data-role='row-select']:checked").length;
    const totalVisible = $tableContainer.find("input[data-role='row-select']").length;
    $tableContainer
        .find("input[data-role='select-all']")
        .prop("checked", checkedCount === totalVisible && totalVisible > 0);
}

function reorderTableRows(viewId, $rowsToAdd = []) {
    if (!viewId) return;
    const table = tableData.get(viewId);
    if (!table) return;

    const $tbody = $(`#table-container-${viewId} #data-container-${viewId}`);
    const $existingRows = $tbody.find("tr").not(".separator").get();
    const allRows = [...$existingRows, ...$rowsToAdd];

    const selectedRows = [];
    const unselectedRows = [];
    let sentinelRow = null;

    allRows.forEach((row) => {
        const $row = $(row);
        if ($row.hasClass("htmx-sentinel")) {
            sentinelRow = $row;
        } else {
            const id = $row.find("input[data-role='row-select']").val();
            if (table.selectedRecordIds.includes(id)) {
                selectedRows.push($row);
            } else {
                unselectedRows.push($row);
            }
        }
    });

    $tbody.empty();
    selectedRows.forEach(($row) => $tbody.append($row));
    unselectedRows.forEach(($row) => $tbody.append($row));
    if (sentinelRow) $tbody.append(sentinelRow);
}

function processInfiniteScrollRows(viewId, $newRows) {
    if (!viewId) return;
    const table = tableData.get(viewId);
    if (!table) return;

    $newRows.each(function () {
        const $checkbox = $(this).find("input[data-role='row-select']");
        const id = $checkbox.val();
        $checkbox.prop("checked", table.selectedRecordIds.includes(id));
    });

    reorderTableRows(viewId, $newRows);
}

function processNewRecords(viewId) {
    updateCheckboxStates(viewId);
    reorderTableRows(viewId);
    updateActionButtonsVisibility(viewId);
}

function selectedRecordIds(viewId) {
    const table = tableData.get(viewId);
    return table ? table.selectedRecordIds : [];
}

// Export functionality
function exportSelected(viewId) {
    const table = tableData.get(viewId);
    const $tableContainer = $(`#table-container-${viewId}`);
    const selectedIds = (table && table.selectedRecordIds.length > 0)
        ? table.selectedRecordIds
        : $tableContainer.find("input[data-role='row-select']:checked").map(function () {
            return $(this).val();
        }).get();

    if (selectedIds.length === 0) {
        alert("No items selected for export");
        return;
    }

    openExport(viewId);
    $(`#exportRecordIds-${viewId}`).val(JSON.stringify(selectedIds));
}

// Kanban drag and drop
let draggedColumn = null;
let kanbanRequestInFlight = false;

function drag(ev) {
    ev.dataTransfer.setData("text", ev.target.id);
}

function allowDrop(ev) {
    ev.preventDefault();
    const target = ev.target.closest(".kanban-block");
    if (target) target.classList.add("highlight");
}

function drop(ev) {
    ev.preventDefault();

    if (!ev.dataTransfer) return;
    if (kanbanRequestInFlight) return;

    const data = ev.dataTransfer.getData("text");
    const target = ev.target.closest(".kanban-block");

    if (!target) return;

    target.classList.remove("highlight");

    const currentQuery = new URLSearchParams(window.location.search);

    if (data.startsWith("column-")) {
        const kanbanView = document.getElementById("kanbanview");
        const allowColumnReorder = kanbanView.dataset.allowColumnReorder === "true";

        if (!allowColumnReorder) return;

        const columnKey = data.replace("column-", "");
        const draggedColumn = document.querySelector(`.kanban-block[data-column-key="${columnKey}"]`);

        if (draggedColumn && draggedColumn !== target) {
            const parent = target.parentNode;
            const allColumns = Array.from(parent.querySelectorAll(".kanban-block"));
            const draggedIndex = allColumns.indexOf(draggedColumn);
            const targetIndex = allColumns.indexOf(target);

            if (draggedIndex < targetIndex) {
                if (target.nextSibling) {
                    parent.insertBefore(draggedColumn, target.nextSibling);
                } else {
                    parent.appendChild(draggedColumn);
                }
            } else {
                parent.insertBefore(draggedColumn, target);
            }

            const appLabel = kanbanView.dataset.appLabel;
            const modelName = kanbanView.dataset.modelName;
            const csrfToken = kanbanView.dataset.csrfToken;
            const className = kanbanView.dataset.className;

            const newColumnOrder = Array.from(document.querySelectorAll(".kanban-block")).map(
                (col) => col.dataset.columnKey
            );

            const postValues = {
                column_order: JSON.stringify(newColumnOrder),
                app_label: appLabel,
                model_name: modelName,
                class_name: className,
            };

            currentQuery.forEach((value, key) => {
                if (postValues[key]) {
                    if (!Array.isArray(postValues[key])) {
                        postValues[key] = [postValues[key]];
                    }
                    postValues[key].push(value);
                } else {
                    postValues[key] = value;
                }
            });

            kanbanRequestInFlight = true;
            htmx.ajax("POST", `/generics/update-kanban-column-order/${appLabel}/${modelName}/`, {
                target: "#kanbancontainer",
                swap: "innerHTML",
                headers: {
                    "X-CSRFToken": csrfToken,
                },
                values: postValues,
            }).then(() => { kanbanRequestInFlight = false; }).catch(() => { kanbanRequestInFlight = false; });
        }
    } else {
        const draggedElement = document.getElementById(data);
        if (draggedElement && target) {
            target.querySelector(".items-container").appendChild(draggedElement);

            const targetColumn = target.dataset.columnKey;
            const itemId = data.split("-")[1];

            const kanbanView = document.getElementById("kanbanview");
            const appLabel = kanbanView.dataset.appLabel;
            const modelName = kanbanView.dataset.modelName;
            const csrfToken = kanbanView.dataset.csrfToken;
            const className = kanbanView.dataset.className;

            const postValues = {
                item_id: itemId,
                new_column: targetColumn,
                app_label: appLabel,
                model_name: modelName,
                class_name: className,
            };

            currentQuery.forEach((value, key) => {
                if (postValues[key]) {
                    if (!Array.isArray(postValues[key])) {
                        postValues[key] = [postValues[key]];
                    }
                    postValues[key].push(value);
                } else {
                    postValues[key] = value;
                }
            });

            kanbanRequestInFlight = true;
            htmx.ajax("POST", `/generics/update-kanban-item/${appLabel}/${modelName}/`, {
                target: "#kanbancontainer",
                swap: "innerHTML",
                headers: {
                    "X-CSRFToken": csrfToken,
                },
                values: postValues,
            }).then(() => { kanbanRequestInFlight = false; }).catch(() => { kanbanRequestInFlight = false; });
        }
    }
}

function columnDragStart(e) {
    const kanbanView = document.getElementById("kanbanview");
    const allowColumnReorder = kanbanView.dataset.allowColumnReorder === "true";

    if (!allowColumnReorder) {
        e.preventDefault();
        return;
    }

    draggedColumn = $(e.target).closest(".kanban-block");
    const event = e.originalEvent || e;
    if (event.dataTransfer) {
        const columnKey = draggedColumn.data("column-key");
        event.dataTransfer.setData("text", `column-${columnKey}`);
        event.dataTransfer.effectAllowed = "move";
    }
    setTimeout(() => draggedColumn.addClass("opacity-50"), 0);
}

function columnDragEnd(e) {
    if (draggedColumn) {
        draggedColumn.removeClass("opacity-50");
        draggedColumn = null;
    }
}

// Confirmation dialogs
function hxConfirm(element, messageText, hint) {
    const isCheckbox = element.type === 'checkbox';
    const wasChecked = isCheckbox ? element.checked : null;

    if (isCheckbox) {
        element.checked = !wasChecked;
    }

    let htmlContent = messageText;
    if (hint) {
        htmlContent += `
            <p style="margin: 10px 0; font-size:15px; font-style: italic; background: #fff8c4; padding: 6px 10px; border-radius: 4px; display: inline-block;">
                ${hint}
            </p>
        `;
    }

    Swal.fire({
        html: htmlContent,
        icon: "question",
        showCancelButton: true,
        confirmButtonColor: "#008000",
        cancelButtonColor: "#d33",
        confirmButtonText: horillaMessages.confirm,
        cancelButtonText: horillaMessages.cancel,
        reverseButtons: true,
        showClass: {
            popup: `animate__animated animate__fadeInUp animate__faster`
        },
        hideClass: {
            popup: `animate__animated animate__fadeOutDown animate__faster`
        }
    }).then((result) => {
        if (result.isConfirmed) {
            if (isCheckbox) {
                element.checked = !wasChecked;
            }
            htmx.trigger(element, 'confirmed');
        } else {
            return false;
        }
    });
}

function hxConfirmForm(element, messageText) {
    Swal.fire({
        text: messageText,
        icon: "question",
        showCancelButton: true,
        confirmButtonColor: "#008000",
        cancelButtonColor: "#d33",
        confirmButtonText: horillaMessages.confirm,
        cancelButtonText: horillaMessages.cancel,
        reverseButtons: true,
        showClass: {
            popup: `animate__animated animate__fadeInUp animate__faster`
        },
        hideClass: {
            popup: `animate__animated animate__fadeOutDown animate__faster`
        }
    }).then((result) => {
        if (result.isConfirmed) {
            htmx.trigger(element.closest('form'), 'submit');
        }
    });
}

function escapeHtml(text) {
    var map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, function(m) { return map[m]; });
}
function showMessages() {
    var messages = [];
    var seenInBatch = new Set();

    $("#messages-container .message").each(function () {
        var $message = $(this);
        var messageText = $message.data("message");
        var messageKey = $message.data("level") + "|" + messageText;

        if (!seenInBatch.has(messageKey)) {
            messages.push({
                level: $message.data("level"),
                text: messageText
            });
            seenInBatch.add(messageKey);
        }
        $message.remove();
    });

    var delay = 0;
    messages.forEach(function(msg) {
        setTimeout(function() {
            Swal.fire({
                toast: true,
                position: "top-end",
                icon: msg.level,
                title: escapeHtml(msg.text),
                showConfirmButton: false,
                timer: 4000,
                timerProgressBar: true,
                customClass: {
                    popup: `custom-toast toast-${msg.level}`
                },
                didOpen: (toast) => {
                    toast.addEventListener("mouseenter", Swal.stopTimer);
                    toast.addEventListener("mouseleave", Swal.resumeTimer);
                }
            });
        }, delay);

        delay += 4500; // 4000ms timer + 500ms gap between messages
    });
}



function isElementChecked(element) {
    let message = element.getAttribute('data-message');
    if (element.checked)
        Swal.fire({
            html: message,
            icon: "question",
            showCancelButton: true,
            confirmButtonColor: "#008000",
            cancelButtonColor: "#d33",
            confirmButtonText: horillaMessages.confirm,
            cancelButtonText: horillaMessages.cancel,
            reverseButtons: true,
            showClass: {
                popup: `animate__animated animate__fadeInUp animate__faster`
            },
            hideClass: {
                popup: `animate__animated animate__fadeOutDown animate__faster`
            }
        }).then((result) => {
            if (result.isConfirmed) {
                return true;
            }
            element.checked = false;
            return false;
        });
}

function initializeSelect2Pagination() {
    const select2Elements = $('.select2-pagination:not(.select2-hidden-accessible)');
    if (select2Elements.length === 0) return;

    select2Elements.each(function (index) {
        const $this = $(this);

        // Prevent duplicate initialization
        if ($this.data('select2-initialized')) {
            return;
        }

        const url = $this.data('url');
        const placeholder = $this.data('placeholder') || gettext("Select an Option");

        const initialData = $this.data('initial');
        const fieldName = $this.data('field-name') || `field_${index}`;

        const dependencyField = $this.data('dependency');
        const dependencyModel = $this.data('dependency-model');
        const dependencyFieldName = $this.data('dependency-field');

        // NEW: Get filter class and parent model from data attributes
        const filterClass = $this.data('filter-class');
        const parentModel = $this.data('parent-model');

        const isMultiple = $this.prop('multiple');
        const elementId = $this.attr('id') || `select2_${fieldName}_${Math.random().toString(36).substr(2, 9)}`;

        const htmxAttrs = {
            'hx-get': $this.attr('hx-get'),
            'hx-target': $this.attr('hx-target'),
            'hx-swap': $this.attr('hx-swap'),
            'hx-trigger': $this.attr('hx-trigger'),
            'hx-include': $this.attr('hx-include'),
        };

        if (!$this.attr('id')) {
            $this.attr('id', elementId);
        }

        if (!$this.is(':visible') && !$this.closest('.modal').length) {
            return;
        }

        try {
            $this.select2({
                ajax: {
                    url: url,
                    dataType: 'json',
                    delay: 250,
                    data: function (params) {
                        let dependencyValue = undefined;
                        if (dependencyField) {
                            const $dependentField = $(`#id_${dependencyField}`);
                            dependencyValue = $dependentField.length ? $dependentField.val() : undefined;
                        }

                        // Build the data object
                        const requestData = {
                            q: params.term || '',
                            page: params.page || 1,
                            field_name: fieldName,
                            form_class: $this.data('form-class'),
                            dependency_value: dependencyValue,
                            dependency_model: dependencyModel,
                            dependency_field: dependencyFieldName,
                        };

                        // NEW: Add filter_class and parent_model if available
                        if (filterClass) {
                            requestData.filter_class = filterClass;
                        }
                        if (parentModel) {
                            requestData.parent_model = parentModel;
                        }

                        // Add object_id if available (for edit forms to use object's company)
                        const objectId = $this.data('object-id');
                        if (objectId) {
                            requestData.object_id = objectId;
                        }

                        return requestData;
                    },
                    processResults: function (data, params) {
                        params.page = params.page || 1;
                        let results = data.results || [];
                        // Offer an empty choice for optional single selects so a value can be unset.
                        // Select2 hides results whose id equals the placeholder id (''), hence the stand-in id.
                        if (!isMultiple && !$this.prop('required') && params.page === 1 && !params.term) {
                            results = [{ id: '__empty__', text: '---------' }].concat(results);
                        }
                        return {
                            results: results,
                            pagination: {
                                more: data.pagination && data.pagination.more,
                            },
                        };
                    },
                    cache: false,
                },
                placeholder: placeholder,
                minimumInputLength: 0,
                theme: 'default',
                width: '100%',
                closeOnSelect: !isMultiple,
                dropdownParent: $this.closest('.modal-content').length ? $this.closest('.modal-content') : $('body'),
            });

            // Mark as initialized
            $this.data('select2-initialized', true);

            Object.keys(htmxAttrs).forEach((attr) => {
                if (htmxAttrs[attr]) {
                    $this.attr(attr, htmxAttrs[attr]);
                }
            });

            if (typeof htmx !== 'undefined') {
                htmx.process($this[0]);
            }

            // Picking the empty choice clears the field instead of selecting a value
            $this.off('select2:selecting.emptyChoice');
            $this.on('select2:selecting.emptyChoice', function (e) {
                if (e.params.args.data.id === '__empty__') {
                    e.preventDefault();
                    $(this).val(null).trigger('change');
                    $(this).select2('close');
                }
            });

            // Remove any existing handlers before binding
            $this.off('select2:select select2:unselect');
            $this.on('select2:select select2:unselect', function (e) {
                $(this).trigger('change');
                if (htmxAttrs['hx-get'] && typeof htmx !== 'undefined') {
                    htmx.trigger(this, 'change');
                }
            });

            if (initialData && initialData !== '') {
                loadInitialData($this, url, initialData, fieldName, isMultiple);
            }
        } catch (error) {
            console.error(`Error initializing Select2`, { fieldName }, error);
        }
    });
}

function loadInitialData($element, url, initialData, fieldName, isMultiple) {
    let ids = [];

    if (initialData === null || initialData === undefined || initialData === '') {
        return;
    }

    if (typeof initialData === 'string') {
        ids = isMultiple ? initialData.split(',').filter(id => id.trim()) : [initialData.trim()];
    } else if (typeof initialData === 'number') {
        ids = [initialData.toString()];
    } else if (Array.isArray(initialData)) {
        ids = initialData.map(id => id.toString()).filter(id => id.trim());
    } else if (typeof initialData === 'object') {
        if (initialData.id) {
            ids = [initialData.id.toString()];
        } else {
            return;
        }
    } else {
        return;
    }

    ids = ids.filter(id => id && id.trim() !== '');

    if (ids.length === 0) return;

    $.ajax({
        url: url,
        dataType: 'json',
        data: {
            ids: ids.join(','),
            field_name: fieldName
        },
        success: function (data) {
            if (!data.results || data.results.length === 0) return;

            if (!isMultiple) {
                $element.find('option:not([value=""])').remove();
            } else {
                $element.empty();
            }

            data.results.forEach(function (item) {
                const option = new Option(item.text, item.id, true, true);
                $element.append(option);
            });

            $element.trigger('change');
        },
    });
}

// Filter rows keep exactly one "value" param per row (fields/operators/values/logic
// are aligned by array index across the whole form), so a .filterMultiSelect's chosen
// options are never submitted directly - they're joined into the sibling hidden
// .filterValue input instead, which is what actually gets submitted as "value".
function joinMultiSelectValue(selectEl) {
    const $select = $(selectEl);
    const $hidden = $select.closest(".filter-row, .up-filter-row").find("input.filterValue");
    if (!$hidden.length) return;
    const values = $select.val() || [];
    $hidden.val(values.join(","));
}

$(document).on("change", ".filterMultiSelect", function () {
    joinMultiSelectValue(this);
});

// Condition rows (single-form views): same idea as .filterMultiSelect - join the
// chosen options into the sibling hidden .conditionValue input ("value_<row>").
$(document).on("change", ".conditionMultiSelect", function () {
    const $hidden = $(this).parent().find("input.conditionValue");
    $hidden.val(($(this).val() || []).join(","));
});

function safeInitializeSelect2() {
    const elementsToInitialize = $('.select2-pagination:not(.select2-hidden-accessible)');

    if (elementsToInitialize.length > 0) {
        initializeSelect2Pagination();

        setTimeout(function () {
            const stillNeedInit = $('.select2-pagination:not(.select2-hidden-accessible)');
            if (stillNeedInit.length > 0) {
                initializeSelect2Pagination();
            }
        }, 500);
    }
}

window.reinitializeSelect2 = function () {
    safeInitializeSelect2();
};

function initFilterPanelDrag() {
    var panel = document.getElementById("filterpanel");
    var handle = panel && panel.querySelector(".filter-panel-drag-handle");
    if (!panel || !handle) return;

    // Setup drag tooltip: show on header, but not when hovering action icons
    var dragTitle = handle.getAttribute("data-drag-title");
    if (dragTitle) {
        handle.setAttribute("title", dragTitle);
        var iconButtons = handle.querySelectorAll("#filterPanelMinBtn, #filterPanelMaxBtn, .filter-panel-close");
        iconButtons.forEach(function (btn) {
            btn.addEventListener("mouseenter", function () {
                handle.removeAttribute("title");
            });
            btn.addEventListener("mouseleave", function () {
                handle.setAttribute("title", dragTitle);
            });
        });
    }

    var startX, startY, isDragging = false;

    function onMouseMove(e) {
        if (!isDragging) return;
        panel.style.left = (e.clientX - startX) + "px";
        panel.style.top = (e.clientY - startY) + "px";
    }

    function onMouseUp() {
        if (!isDragging) return;
        isDragging = false;
        panel.classList.remove("filter-panel-dragging");
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
    }

    handle.addEventListener("mousedown", function (e) {
        if (e.button !== 0 || e.target.closest("button")) return;
        e.preventDefault();
        var rect = panel.getBoundingClientRect();
        startX = e.clientX - rect.left;
        startY = e.clientY - rect.top;
        panel.classList.add("filter-panel-dragging");
        panel.style.left = rect.left + "px";
        panel.style.top = rect.top + "px";
        panel.style.right = "auto";
        panel.style.width = rect.width + "px";
        isDragging = true;
        document.addEventListener("mousemove", onMouseMove);
        document.addEventListener("mouseup", onMouseUp);
    });
}

var FILTER_PANEL_MIN_W = 288;
var FILTER_PANEL_MIN_H = 192;
var FILTER_PANEL_MAX_H = 0.85 * (typeof window !== "undefined" ? window.innerHeight : 800);

function applyFilterPanelVisibilityPreference() {
    if (typeof window === "undefined" || typeof localStorage === "undefined") return;
    var panel = document.getElementById("filterpanel");
    var container = document.getElementById("filtercontainer");
    if (!panel || !container) return;

    var storageKey = "filterPanelVisible:" + window.location.pathname;
    var stored;
    try {
        stored = localStorage.getItem(storageKey);
    } catch (e) {
        stored = null;
    }

    if (stored === "closed") {
        panel.classList.remove("visible");
        container.classList.remove("visible");
        panel.classList.add("hidden");
    }
}

window.applyFilterPanelVisibilityPreference = applyFilterPanelVisibilityPreference;

function initFilterPanelResize() {
    var panel = document.getElementById("filterpanel");
    if (!panel) return;
    var resizeWRight = panel.querySelector(".filter-panel-resize-w:not(.filter-panel-resize-w-left)");
    var resizeWLeft = panel.querySelector(".filter-panel-resize-w-left");
    var resizeH = panel.querySelector(".filter-panel-resize-h");
    if (!resizeWRight && !resizeWLeft && !resizeH) return;

    function getMaxH() { return 0.85 * window.innerHeight; }

    if (resizeWRight) {
        resizeWRight.addEventListener("mousedown", function (e) {
            if (e.button !== 0) return;
            e.preventDefault();
            var rect = panel.getBoundingClientRect();
            var startX = e.clientX;
            var startW = rect.width;
            var maxW = window.innerWidth - rect.left - 20;

            panel.style.left = rect.left + "px";
            panel.style.right = "auto";

            function onMove(e) {
                var dx = e.clientX - startX;
                var newW = Math.max(FILTER_PANEL_MIN_W, Math.min(maxW, startW + dx));
                panel.style.width = newW + "px";
            }
            function onUp() {
                document.removeEventListener("mousemove", onMove);
                document.removeEventListener("mouseup", onUp);
                panel.classList.remove("filter-panel-resizing");
                if (window.updateFilterPanelSizeButtons) {
                    window.updateFilterPanelSizeButtons(panel);
                }
            }
            panel.classList.add("filter-panel-resizing");
            document.addEventListener("mousemove", onMove);
            document.addEventListener("mouseup", onUp);
        });
    }

    if (resizeWLeft) {
        resizeWLeft.addEventListener("mousedown", function (e) {
            if (e.button !== 0) return;
            e.preventDefault();
            var rect = panel.getBoundingClientRect();
            var startX = e.clientX;
            var startW = rect.width;
            var rightEdge = rect.right;
            var maxW = rightEdge - 20;

            panel.style.right = (window.innerWidth - rightEdge) + "px";
            panel.style.left = "auto";

            function onMove(e) {
                var dx = startX - e.clientX;
                var newW = Math.max(FILTER_PANEL_MIN_W, Math.min(maxW, startW + dx));
                panel.style.width = newW + "px";
            }
            function onUp() {
                document.removeEventListener("mousemove", onMove);
                document.removeEventListener("mouseup", onUp);
                panel.classList.remove("filter-panel-resizing");
                if (window.updateFilterPanelSizeButtons) {
                    window.updateFilterPanelSizeButtons(panel);
                }
            }
            panel.classList.add("filter-panel-resizing");
            document.addEventListener("mousemove", onMove);
            document.addEventListener("mouseup", onUp);
        });
    }

    if (resizeH) {
        resizeH.addEventListener("mousedown", function (e) {
            if (e.button !== 0) return;
            e.preventDefault();
            var rect = panel.getBoundingClientRect();
            var startY = e.clientY;
            var startH = rect.height;

            function onMove(e) {
                var dy = e.clientY - startY;
                var newH = Math.max(FILTER_PANEL_MIN_H, Math.min(getMaxH(), startH + dy));
                panel.style.height = newH + "px";
            }
            function onUp() {
                document.removeEventListener("mousemove", onMove);
                document.removeEventListener("mouseup", onUp);
                panel.classList.remove("filter-panel-resizing");
                if (window.updateFilterPanelSizeButtons) {
                    window.updateFilterPanelSizeButtons(panel);
                }
            }
            panel.classList.add("filter-panel-resizing");
            document.addEventListener("mousemove", onMove);
            document.addEventListener("mouseup", onUp);
        });
    }
}

function initFilterPanelSizeControls() {
    var panel = document.getElementById("filterpanel");
    if (!panel) return;
    var minBtn = document.getElementById("filterPanelMinBtn");
    var maxBtn = document.getElementById("filterPanelMaxBtn");
    if (!minBtn && !maxBtn) return;

    var STORAGE_KEY = "filterPanelSizeMode";

    function updateButtonsFor(panelEl, opts) {
        var el = panelEl || panel;
        if (!el) return;

        var fromClick = opts && opts.fromClick;
        var isNowMax;

        if (fromClick) {
            // When called from explicit min/max buttons, trust the classes they just set
            isNowMax = el.classList.contains("filter-panel-max");
        } else {
            // When called from drag/resize, decide based on actual width
            var rect = el.getBoundingClientRect();
            var width = rect.width || 0;
            var baseMin = (typeof FILTER_PANEL_MIN_W !== "undefined" ? FILTER_PANEL_MIN_W : 288);
            var threshold = baseMin + 40; // a bit wider than min
            isNowMax = width > threshold;
            el.classList.toggle("filter-panel-max", isNowMax);
            el.classList.toggle("filter-panel-min", !isNowMax);
        }

        // Persist mode so HTMX reloads and page refreshes keep current size
        try {
            localStorage.setItem(STORAGE_KEY, isNowMax ? "max" : "min");
        } catch (e) {
            // ignore storage issues
        }

        var isMax = isNowMax;

        if (minBtn) {
            // Show shrink only when currently in a "max" (wider) state
            minBtn.style.display = isMax ? "inline-flex" : "none";
        }
        if (maxBtn) {
            // Show expand when not already maximized
            maxBtn.style.display = isMax ? "none" : "inline-flex";
        }
    }

    // Expose so resize handlers can call it
    window.updateFilterPanelSizeButtons = updateButtonsFor;

    // Initial state: restore last mode from storage (default: min)
    var savedMode = null;
    try {
        savedMode = localStorage.getItem(STORAGE_KEY);
    } catch (e) {
        savedMode = null;
    }

    if (savedMode === "max") {
        panel.classList.add("filter-panel-max");
        panel.classList.remove("filter-panel-min");
    } else {
        panel.classList.add("filter-panel-min");
        panel.classList.remove("filter-panel-max");
    }
    updateButtonsFor(panel, { fromClick: true });

    if (minBtn) {
        minBtn.onclick = function (e) {
            e.stopPropagation();
            panel.classList.remove("filter-panel-max");
            panel.classList.add("filter-panel-min");
            // Reset inline sizing so CSS min preset takes effect
            panel.style.width = "";
            panel.style.height = "";
            updateButtonsFor(panel, { fromClick: true });
        };
    }

    if (maxBtn) {
        maxBtn.onclick = function (e) {
            e.stopPropagation();
            panel.classList.remove("filter-panel-min");
            panel.classList.add("filter-panel-max");
            panel.style.width = "";
            panel.style.height = "";
            updateButtonsFor(panel, { fromClick: true });
        };
    }
}

// Document Ready
$(document).ready(function () {
    // Initialize components
    initializeSelect2Pagination();
    safeInitializeSelect2();
    showMessages();

    // Initialize sidebar
    SidebarManager.initFromUrl();

    // Initialize all tables
    $("[id^='table-container-']").each(function () {
        const $tableContainer = $(this);
        const viewId = $tableContainer.data("view-id");
        const recordIds = JSON.parse($tableContainer.attr("data-record-ids") || "[]");
        initializeRecordIds(recordIds, viewId);
    });

    // Select2 Basic Initialization
    $('.js-example-basic-single:not(.select2-hidden-accessible)').select2({
        templateResult: formatOption,
        templateSelection: formatOption,
    });

    $('.js-example-basic-multiple:not(.select2-hidden-accessible)').each(function() {
        $(this).select2({
            placeholder: $(this).data('placeholder') || 'Select Options...',
            allowClear: true,
            closeOnSelect: false
        });
    });

    // Custom Select Dropdown
    document.querySelectorAll(".custom-select").forEach((select) => {
        const selected = select.querySelector(".selected");
        const dropdown = select.querySelector(".dropdown");
        const options = select.querySelectorAll(".option");
        const span = selected.querySelector("span");

        selected.addEventListener("click", () => {
            dropdown.classList.toggle("opacity-0");
            dropdown.classList.toggle("scale-y-95");
            dropdown.classList.toggle("pointer-events-none");
        });

        options.forEach((option) => {
            option.addEventListener("click", (e) => {
                e.preventDefault();
                span.textContent = option.textContent;
                dropdown.classList.add("opacity-0", "scale-y-95", "pointer-events-none");
            });
        });

        document.addEventListener("click", (e) => {
            if (!select.contains(e.target)) {
                dropdown.classList.add("opacity-0", "scale-y-95", "pointer-events-none");
            }
        });
    });

    // Filter panel helpers
    // Respect saved visibility (open/closed) state across reloads
    applyFilterPanelVisibilityPreference();
    initFilterPanelDrag();
    initFilterPanelResize();
    initFilterPanelSizeControls();

    // Event Listeners
    $(".filtermenu").on("click", function () {
        $("#filterpanel").toggleClass("hidden visible");
    });

    $(".closebtn").on("click", function () {
        $("#filterpanel").removeClass("visible").addClass("hidden");
    });

    initFilterPanelDrag();
    initFilterPanelResize();

    $("#tableBtn").on("click", function () {
        $("[id^='tableview']").removeClass("hidden");
        $("#kanbanview").addClass("hidden");
    });

    $("#kanbanBtn").on("click", function () {
        $("#kanbanview").removeClass("hidden");
        $("[id^='tableview']").addClass("hidden");
    });

    $("select").on("select2:select", function (e) {
        $(this).closest("select")[0].dispatchEvent(new Event("change"));
    });

    // Kanban drag handlers
    $(".kanban-block").each(function () {
        const block = $(this);

        block.on("dragover", function (e) {
            if (draggedColumn) e.preventDefault();
        });

        block.on("dragenter", function (e) {
            if (draggedColumn && block[0] !== draggedColumn[0]) {
                block.addClass("swap-highlight");
            }
        });

        block.on("dragleave", function (e) {
            block.removeClass("swap-highlight");
        });

        block.on("drop", function (e) {
            if (!draggedColumn || draggedColumn[0] === block[0]) return;

            block.removeClass("swap-highlight");

            const parent = block.parent();
            const allBlocks = parent.children();
            const draggedIndex = allBlocks.index(draggedColumn);
            const targetIndex = allBlocks.index(block);

            if (draggedIndex < targetIndex) {
                draggedColumn.insertAfter(block);
            } else {
                draggedColumn.insertBefore(block);
            }
        });
    });

    const $navLinks = $("nav a.nav-link");

    $("nav").on("click", "a.nav-link", function () {
        const $clickedLink = $(this);
        const clickedSection = $clickedLink.attr("id");
        const currentActiveSection = SidebarManager.getActiveSection();

        if (currentActiveSection) {
            localStorage.setItem("lastActiveSection", currentActiveSection);
        }

        const isClickingSameSection = currentActiveSection === clickedSection;

        SidebarManager.setActiveNavLink($clickedLink, clickedSection);

        if (isClickingSameSection) {
            localStorage.setItem("sidebarClicked", "false");
            localStorage.setItem("lastActiveSection", "temp_reset");
        }
    });

    $("body").on("click", "ul a.sidebar-link", function () {
        const $link = $(this);
        const currentSection = SidebarManager.getActiveSection();
        SidebarManager.setActiveSubsectionLink($link, currentSection);
        localStorage.setItem('last-visited-url', window.location.href);
    });

    const $tableContainer = $("#tableContainer");
    $tableContainer.on("scroll", function () {
        const scrollTop = $tableContainer.scrollTop();
        const scrollHeight = $tableContainer[0].scrollHeight;
        const clientHeight = $tableContainer[0].clientHeight;
        const threshold = 100;

        if (scrollHeight - scrollTop - clientHeight < threshold) {
            const $sentinel = $tableContainer.find("tr.htmx-sentinel");
            if ($sentinel.length && !$sentinel.hasClass("htmx-request")) {
                htmx.trigger($sentinel[0], "htmx:trigger");
            }
        }
    });

    const hiddenReloadSidebar = document.getElementById("hiddenReloadSidebar");

    if (hiddenReloadSidebar) {
        hiddenReloadSidebar.addEventListener("click", function () {
            const appLabel = this.getAttribute("data-app-label");
            const section = SidebarManager.getSectionFromAppLabel(appLabel);

            if (!section) {
                console.warn("No section found for app label:", appLabel);
                return;
            }

            const reloadUrl = `${window.location.pathname}?section=${section}`;

            htmx.ajax("GET", reloadUrl)
                .then(() => {
                    SidebarManager.activateFirstSubsectionItem(section);
                })
                .catch((err) => {
                    console.error("Failed to reload sub-sidebar for section:", section, err);
                });
        });
    }
});

// Window load event
$(window).on('load', function () {
    safeInitializeSelect2();
});


// Event Delegation
$(document).on("change", "input[data-role='row-select']", function () {
    const viewId = getCurrentViewId(this);
    const table = tableData.get(viewId);
    if (!table) return;

    const id = $(this).val();
    if ($(this).prop("checked")) {
        if (!table.selectedRecordIds.includes(id)) {
            table.selectedRecordIds.push(id);
        }
    } else {
        table.selectedRecordIds = table.selectedRecordIds.filter((selectedId) => selectedId !== id);
        table.allSelected = false;
    }

    sessionStorage.setItem(`selectedRecordIds_${viewId}`, JSON.stringify(table.selectedRecordIds));
    updateCheckboxStates(viewId);
    updateActionButtonsVisibility(viewId);
});

$(document).on("change", "input[data-role='select-all']", function () {
    const viewId = getCurrentViewId(this);
    selectAll($(this).prop("checked"), viewId);
    reorderTableRows(viewId);
});

$(document).on("click", "[id^='clear-select-btn-']", function () {
    const viewId = getCurrentViewId(this);
    clearSelections(viewId);
});

// Export form validation - each list view uses exportForm-{viewId}
$(document).on("submit", "form[id^='exportForm-']", function (e) {
    const exportFormat = $(this).find('select[name="export_format"]').val();
    if (!exportFormat) {
        alert("Please select an export format");
        e.preventDefault();
        return false;
    }
    return true;
});

function getFlowbiteDropdownPlacement(placement) {
    placement = placement || "bottom";
    if (document.documentElement.getAttribute("dir") === "rtl") {
        var rtlPlacements = {
            "right-end": "left-end",
            "right-start": "left-start",
            "left-end": "right-end",
            "left-start": "right-start"
        };
        return rtlPlacements[placement] || placement;
    }
    return placement;
}

function initFlowbiteDropdowns(root) {
    if (!window.Dropdown) {
        return;
    }
    var $toggles = root
        ? $(root).find("[data-dropdown-toggle]").addBack("[data-dropdown-toggle]")
        : $("[data-dropdown-toggle]");
    $toggles.each(function () {
        var $toggle = $(this);
        var targetId = $toggle.attr("data-dropdown-toggle");
        var $target = $("#" + targetId);
        if (!$target.length || $target.data("flowbiteInitialized")) {
            return;
        }
        new Dropdown($target[0], $toggle[0], {
            placement: getFlowbiteDropdownPlacement($toggle.attr("data-dropdown-placement"))
        });
        $target.data("flowbiteInitialized", true);
    });
}

document.addEventListener("DOMContentLoaded", function () {
    initFlowbiteDropdowns();
});

// HTMX Events
document.addEventListener("DOMContentLoaded", initSidebar);
document.body.addEventListener("htmx:afterSwap", initSidebar);
document.body.addEventListener("htmx:afterOnLoad", initSidebar);
// outerHTML swaps can fire afterSwap before the new node replaces the old one in the DOM,
// so initSidebar's collapse/expand correction misses it; afterSettle fires once the swap is final.
document.body.addEventListener("htmx:afterSettle", initSidebar);

/* ==========================================================================
   HTMX network failure → full-page connection error (ERR_CONNECTION_REFUSED)
   ========================================================================== */
(function () {
    var shown = false;

    function esc(t) {
        return String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }

    function showNetworkConnectionErrorPage() {
        if (shown) return;
        shown = true;

        var title = esc(gettext("Connection Lost"));
        var desc = esc(gettext("We can't reach the server right now. Check your internet connection and try again."));
        var offline = esc(gettext("Offline"));
        var retry = esc(gettext("Retry"));
        var errLabel = esc(gettext("Error code:"));

        if (!document.getElementById("horilla-network-error-styles")) {
            var s = document.createElement("style");
            s.id = "horilla-network-error-styles";
            s.textContent = "@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-10px)}}@keyframes pulse-glow{0%,100%{opacity:.4;transform:scale(1)}50%{opacity:.8;transform:scale(1.05)}}";
            document.head.appendChild(s);
        }

        document.body.className = "network-error-page min-h-screen w-full flex items-center justify-center relative overflow-hidden font-['Inter',_sans-serif] bg-secondary-50";
        document.body.innerHTML =
            '<div class="absolute inset-0 overflow-hidden pointer-events-none">' +
            '<div class="absolute top-10 start-10 w-80 h-80 bg-primary-600/[0.08] rounded-full blur-[100px] animate-[pulse-glow_4s_ease-in-out_infinite]"></div>' +
            '<div class="absolute bottom-10 end-10 w-[28rem] h-[28rem] bg-secondary-600/[0.06] rounded-full blur-[120px] animate-[pulse-glow_4s_ease-in-out_infinite]" style="animation-delay:2s"></div>' +
            '<div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[700px] h-[700px] bg-primary-600/[0.04] rounded-full blur-[140px]"></div></div>' +
            '<div class="absolute inset-0 opacity-[0.04]" style="background-image:radial-gradient(circle,currentColor_1px,transparent_1px);background-size:32px_32px"></div>' +
            '<div class="absolute top-16 end-20 w-2 h-2 bg-primary-600/30 rounded-full animate-[float_6s_ease-in-out_infinite]"></div>' +
            '<div class="absolute bottom-24 start-24 w-2.5 h-2.5 bg-secondary-600/25 rounded-full animate-[float_7s_ease-in-out_infinite]" style="animation-delay:1s"></div>' +
            '<div class="absolute top-1/3 start-12 w-1.5 h-1.5 bg-primary-500/30 rounded-full animate-[float_6s_ease-in-out_infinite]" style="animation-delay:2s"></div>' +
            '<div class="absolute bottom-1/3 end-16 w-2 h-2 bg-secondary-500/20 rounded-full animate-[float_7s_ease-in-out_infinite]" style="animation-delay:3s"></div>' +
            '<div class="relative z-10 bg-white border border-dark-50 rounded-3xl p-8 sm:p-12 md:p-14 max-w-md w-full mx-4 shadow-2xl shadow-dark-600/10">' +
            '<div class="flex justify-center mb-8"><div class="relative">' +
            '<div class="absolute inset-0 rounded-full border-2 border-primary-600/20 animate-[ping_3s_ease-in-out_infinite]"></div>' +
            '<div class="absolute inset-3 rounded-full border border-primary-600/10 animate-[ping_3s_ease-in-out_infinite]" style="animation-delay:.7s"></div>' +
            '<div class="relative w-24 h-24 rounded-full bg-primary-100 flex items-center justify-center border border-primary-600/20">' +
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="w-12 h-12 text-primary-600">' +
            '<path d="M5 12.55a11 11 0 0 1 14.08 0" stroke-linecap="round" stroke-linejoin="round" class="opacity-40"/>' +
            '<path d="M8.5 9.55a7 7 0 0 1 7 0" stroke-linecap="round" stroke-linejoin="round" class="opacity-60"/>' +
            '<path d="M12 6.55a3 3 0 0 1 0 0" stroke-linecap="round" stroke-linejoin="round"/>' +
            '<line x1="2" y1="2" x2="22" y2="22" stroke-linecap="round" stroke-width="2.2"/></svg></div></div></div>' +
            '<div class="flex justify-center mb-6"><span class="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-primary-100 border border-primary-600/20 text-primary-600 text-xs font-bold tracking-widest uppercase">' +
            '<span class="w-1.5 h-1.5 rounded-full bg-primary-600 animate-pulse"></span>' + offline + "</span></div>" +
            '<h1 class="text-3xl md:text-4xl font-extrabold text-dark-500 text-center mb-3 tracking-tight">' + title + "</h1>" +
            '<p class="text-dark-200 text-center text-base leading-relaxed mb-8 max-w-sm mx-auto">' + desc + "</p>" +
            '<div class="flex justify-center"><button type="button" onclick="location.reload()" class="w-full px-6 py-3.5 rounded-xl text-white font-semibold cursor-pointer border-0 bg-primary-600 hover:bg-primary-700 hover:shadow-lg hover:shadow-primary-600/30 hover:-translate-y-0.5 active:scale-[0.98] transition-all duration-300">' +
            retry + "</button></div>" +
            '<p class="text-center text-dark-100 text-xs mt-6">' + errLabel +
            ' <span class="font-mono">ERR_CONNECTION_REFUSED</span></p></div>';
    }

    function onHtmxNetworkFailure(e) {
        var d = e && e.detail;
        if (!d) return;
        if (e.type === "htmx:sendError" || (e.type === "htmx:afterRequest" && d.failed && d.xhr && d.xhr.status === 0)) {
            showNetworkConnectionErrorPage();
        }
    }

    document.addEventListener("htmx:sendError", onHtmxNetworkFailure, true);
    document.addEventListener("htmx:afterRequest", onHtmxNetworkFailure, true);
})();

// Flowbite Initialization on HTMX Load
htmx.onLoad(function(content) {
    initFlowbite();
});

document.body.addEventListener("htmx:afterSwap", function () {
    const currentSection = SidebarManager.getActiveSection();
    const $navLinks = $("nav a.nav-link");
    const $sectionLink = $navLinks.filter(`#${currentSection}`);
    if ($sectionLink.length) {
        SidebarManager.setActiveNavLink($sectionLink, currentSection);
    }

    // Settings Content Script Reload
    if (event.detail && event.detail.target && event.detail.target.id === 'settings-content') {
        const scripts = event.detail.target.querySelectorAll('script');
        scripts.forEach(script => {
            const newScript = document.createElement('script');
            newScript.textContent = script.textContent;
            document.body.appendChild(newScript);
            script.remove();
        });
    }
});

document.body.addEventListener("htmx:afterSettle", function (event) {
    const currentSection = SidebarManager.getActiveSection();
    const $navLinks = $("nav a.nav-link");
    const $sectionLink = $navLinks.filter(`#${currentSection}`);
    if ($sectionLink.length) {
        SidebarManager.setActiveNavLink($sectionLink, currentSection);
    }
    SidebarManager.activateFirstSubsectionItem(currentSection);

    if (event.detail && (event.detail.target.id === "mainSession" || event.detail.target.querySelector("#filterpanel"))) {
        applyFilterPanelVisibilityPreference();
        initFilterPanelDrag();
        initFilterPanelResize();
        initFilterPanelSizeControls();
    }

    // Reinitialize Select2 after HTMX content loads
    var target = $(event.target);

    target.find(".js-example-basic-single").each(function() {
        if ($(this).hasClass("select2-hidden-accessible")) {
            $(this).select2("destroy");
            $(this).removeData('select2-initialized');
        }
    });

    target.find(".js-example-basic-single:not(.select2-hidden-accessible)").select2({
        templateResult: formatOption,
        templateSelection: formatOption,
        width: "100%"
    });

    initializeSelect2Pagination();

    setTimeout(function() {
        showMessages();
    }, 200);

    $('.js-example-basic-multiple').each(function() {
        if ($(this).hasClass("select2-hidden-accessible")) {
            return; // Already initialized
        }
        $(this).select2({
            placeholder: $(this).data('placeholder') || 'Select Options...',
            allowClear: true,
            closeOnSelect: false
        });
    });
});

$(document).on("htmx:afterSwap", function (event) {
    const $target = $(event.target);

    let $dataContainer = null;
    let viewId = null;

    if ($target.is("[id^='data-container-']")) {
        $dataContainer = $target;
        viewId = $dataContainer.attr("id").replace("data-container-", "");
    } else {
        $dataContainer = $target.find("[id^='data-container-']");
        if ($dataContainer.length) {
            viewId = $dataContainer.attr("id").replace("data-container-", "");
        }
    }

    if ($dataContainer && $dataContainer.length && viewId) {
        const isInfiniteScroll = event.detail.elt.classList.contains("htmx-sentinel");
        if (isInfiniteScroll) {
            const $newRows = $(event.detail.xhr.response).filter("tr");
            processInfiniteScrollRows(viewId, $newRows);
        } else {
            const $tableContainer = $(`#table-container-${viewId}`);
            const recordIds = JSON.parse($tableContainer.attr("data-record-ids") || "[]");
            initializeRecordIds(recordIds, viewId);
            processNewRecords(viewId);
        }
    }


    if (window.Dropdown) {
        initFlowbiteDropdowns(event.target);
    }
});

$(document).on("htmx:afterSettle", function (e) {
    let elt = e.detail.elt;
    $(elt).find("select")
        .off("select2:select")
        .on("select2:select", function () {
            this.dispatchEvent(new Event("change"));
        });
    if ($(elt).find("select").length) {
        initializeSelect2Pagination();
    }
});


$(document).on('keydown', function (e) {
    if (e.key === "Escape" || e.keyCode === 27) {
        ModalManager.closeTop();
    }
});


// Dropdown functionality
document.addEventListener('DOMContentLoaded', function () {
    document.addEventListener('click', function (e) {
        const wrapper = e.target.closest('.dropdown-wrapper');

        if (wrapper) {
            const dropdown = wrapper.querySelector('.dropdown-content');
            const clickedDropdown = e.target.closest('.dropdown-content');

            // If clicking inside dropdown content (on links), allow it to proceed
            if (clickedDropdown) {
                // Don't stop propagation for links inside dropdown
                // Just close other dropdowns and let the click proceed
                document.querySelectorAll('.dropdown-wrapper.active').forEach(other => {
                    if (other !== wrapper) other.classList.remove('active');
                });
                return; // Let the event continue for HTMX
            }

            const trigger = Array.from(wrapper.children).find(el =>
                el !== dropdown && (el.tagName === 'BUTTON' || el.tagName === 'A' || el.querySelector('svg'))
            );

            // Only stop propagation for the dropdown BUTTON/TRIGGER, not the content
            if (trigger && trigger.contains(e.target)) {
                e.stopPropagation();
                e.preventDefault();

                document.querySelectorAll('.dropdown-wrapper.active').forEach(other => {
                    if (other !== wrapper) other.classList.remove('active');
                });

                wrapper.classList.toggle('active');
                return;
            }
        } else if (!e.target.closest('.sidebarModal')) {
            // Clicks inside a sidebar (e.g. its close arrow) are not outside clicks for dropdowns behind it
            document.querySelectorAll('.dropdown-wrapper.active').forEach(wrapper => {
                wrapper.classList.remove('active');
            });
        }
    }, true); // Keep capture phase

    document.body.addEventListener('htmx:afterRequest', function (e) {
        const wrapper = e.target.closest('.dropdown-wrapper');
        if (wrapper && wrapper.classList.contains('active')) {
            wrapper.classList.remove('active');
        }
    });

    // Filter field lists (Available / Visible) in Add column to list and Add column to details
    document.body.addEventListener('input', function (e) {
        var input = e.target;
        if (!input.matches || !input.matches('.field-list-search')) return;
        var listId = input.getAttribute('data-filter-list');
        if (!listId) return;
        var ul = document.getElementById(listId);
        if (!ul) return;
        var query = (input.value || '').trim().toLowerCase();
        var items = ul.querySelectorAll('li');
        items.forEach(function (li) {
            var text = (li.textContent || '').toLowerCase();
            li.style.display = query === '' || text.indexOf(query) !== -1 ? '' : 'none';
        });
    });

    // Add column to list: client-side move/reorder (no request until Save)
    function syncColumnSelectFromVisible(form) {
        var visibleList = document.getElementById('visibleFields');
        var select = form && form.querySelector('select[name="visible_fields"]');
        if (!visibleList || !select) return;
        var items = visibleList.querySelectorAll('li[data-field-name]');
        var order = [];
        items.forEach(function (li) {
            order.push({ value: li.getAttribute('data-field-name'), text: li.getAttribute('data-verbose-name') });
        });
        select.innerHTML = '';
        order.forEach(function (o) {
            var opt = document.createElement('option');
            opt.value = o.value;
            opt.selected = true;
            opt.textContent = o.text;
            select.appendChild(opt);
        });
    }
    function columnLiAsAvailable(li, form) {
        var fieldName = li.getAttribute('data-field-name');
        var verboseName = li.getAttribute('data-verbose-name');
        var linkClass = form.getAttribute('data-available-link-class') || 'field-list-move hover:border-primary-600 transition duration-300 hover:text-primary-600 px-[10px] py-[8px] w-full flex text-[#333] border border-[#dddddd] rounded-[5px] text-[.8rem] mb-1 text-left';
        var a = document.createElement('a');
        a.href = '#';
        a.setAttribute('role', 'button');
        a.setAttribute('data-action', 'add');
        a.className = linkClass;
        a.textContent = verboseName;
        li.innerHTML = '';
        li.setAttribute('data-field-name', fieldName);
        li.setAttribute('data-verbose-name', verboseName);
        li.appendChild(a);
    }
    function columnLiAsVisible(li, form) {
        var fieldName = li.getAttribute('data-field-name');
        var verboseName = li.getAttribute('data-verbose-name');
        var linkClass = form.getAttribute('data-visible-link-class') || 'field-list-move ps-8 pr-16 bg-primary-300 hover:border-primary-600 transition duration-300 hover:text-primary-600 px-[10px] py-[8px] w-full flex text-[#333] border border-[#dddddd] rounded-[5px] text-[.8rem]';
        var wrap = document.createElement('div');
        wrap.className = 'flex justify-between items-center relative';
        var a = document.createElement('a');
        a.href = '#';
        a.setAttribute('role', 'button');
        a.setAttribute('data-action', 'remove');
        a.className = linkClass;
        a.textContent = verboseName;
        var btnWrap = document.createElement('div');
        btnWrap.className = 'flex absolute end-0 h-full';
        var up = document.createElement('button');
        up.type = 'button';
        up.setAttribute('data-action', 'move_up');
        up.className = 'field-list-move border-[1px] border-e-[0px] border-[solid] w-8 text-primary-600 text-xs transition duration-300';
        up.innerHTML = '<i class="fa-solid fa-angle-up"></i>';
        var down = document.createElement('button');
        down.type = 'button';
        down.setAttribute('data-action', 'move_down');
        down.className = 'field-list-move border-[1px] border-[solid] w-8 text-primary-600 text-xs transition duration-300 rounded-e-[5px]';
        down.innerHTML = '<i class="fa-solid fa-angle-down"></i>';
        btnWrap.appendChild(up);
        btnWrap.appendChild(down);
        wrap.appendChild(a);
        wrap.appendChild(btnWrap);
        li.innerHTML = '';
        li.setAttribute('data-field-name', fieldName);
        li.setAttribute('data-verbose-name', verboseName);
        li.appendChild(wrap);
    }
    document.body.addEventListener('click', function (e) {
        var form = e.target.closest('#fieldSelectorForm');
        var trigger = e.target.closest('.field-list-move');
        if (!form || !trigger) return;
        e.preventDefault();
        e.stopPropagation();
        var action = trigger.getAttribute('data-action');
        var li = trigger.closest('li[data-field-name]');
        if (!li) return;
        var fieldName = li.getAttribute('data-field-name');
        var verboseName = li.getAttribute('data-verbose-name');
        var availableList = document.getElementById('availableFields');
        var visibleList = document.getElementById('visibleFields');
        var select = form.querySelector('select[name="visible_fields"]');
        if (!availableList || !visibleList || !select) return;
        if (action === 'add') {
            columnLiAsVisible(li, form);
            visibleList.appendChild(li);
            var opt = document.createElement('option');
            opt.value = fieldName;
            opt.selected = true;
            opt.textContent = verboseName;
            select.appendChild(opt);
        } else if (action === 'remove') {
            columnLiAsAvailable(li, form);
            availableList.appendChild(li);
            var opts = select.querySelectorAll('option');
            for (var i = 0; i < opts.length; i++) {
                if (opts[i].value === fieldName) { opts[i].remove(); break; }
            }
        } else if (action === 'move_up') {
            var prev = li.previousElementSibling;
            if (prev) {
                visibleList.insertBefore(li, prev);
            } else {
                visibleList.appendChild(li);
            }
            syncColumnSelectFromVisible(form);
        } else if (action === 'move_down') {
            var next = li.nextElementSibling;
            if (next) {
                visibleList.insertBefore(next, li);
            } else {
                visibleList.insertBefore(li, visibleList.firstChild);
            }
            syncColumnSelectFromVisible(form);
        }
    });

    // Detail field selector: client-side move/reorder (no request until Save)
    function syncDetailHiddenInputs(form, section) {
        var visibleListId = section === 'header' ? 'headerVisibleFields' : 'detailsVisibleFields';
        var containerId = section === 'header' ? 'header-fields-inputs' : 'details-fields-inputs';
        var visibleList = document.getElementById(visibleListId);
        var container = document.getElementById(containerId);
        if (!visibleList || !container || !form) return;
        var items = visibleList.querySelectorAll('li[data-field-name]');
        var name = section === 'header' ? 'header_fields' : 'details_fields';
        container.innerHTML = '';
        items.forEach(function (item) {
            var input = document.createElement('input');
            input.type = 'hidden';
            input.name = name;
            input.value = item.getAttribute('data-field-name');
            container.appendChild(input);
        });
    }
    function syncDetailAvailablePlaceholder(availableList) {
        if (!availableList) return;
        var hasRealFields = availableList.querySelectorAll('li[data-field-name]').length > 0;
        var placeholder = availableList.querySelector('li:not([data-field-name])');
        var emptyText = availableList.getAttribute('data-empty-text') || 'All fields added';
        if (hasRealFields && placeholder) {
            placeholder.remove();
        } else if (!hasRealFields && !placeholder) {
            var li = document.createElement('li');
            li.className = 'text-[.8rem] text-[#999] px-[10px] py-[8px]';
            li.textContent = emptyText;
            availableList.appendChild(li);
        }
    }
    function detailFieldLiAsAvailable(li, form) {
        var fieldName = li.getAttribute('data-field-name');
        var verboseName = li.getAttribute('data-verbose-name');
        var section = li.getAttribute('data-section');
        var linkClass = form.getAttribute('data-available-link-class') || 'detail-field-list-move hover:border-primary-600 transition duration-300 hover:text-primary-600 px-[10px] py-[8px] w-full flex text-[#333] border border-[#dddddd] rounded-[5px] text-[.8rem] mb-1 text-left';
        var a = document.createElement('a');
        a.href = '#';
        a.setAttribute('role', 'button');
        a.setAttribute('data-action', 'add');
        a.className = linkClass;
        a.textContent = verboseName;
        li.innerHTML = '';
        li.setAttribute('data-field-name', fieldName);
        li.setAttribute('data-verbose-name', verboseName);
        li.setAttribute('data-section', section);
        li.appendChild(a);
    }
    function detailFieldLiAsVisible(li, form) {
        var fieldName = li.getAttribute('data-field-name');
        var verboseName = li.getAttribute('data-verbose-name');
        var section = li.getAttribute('data-section');
        var linkClass = form.getAttribute('data-visible-link-class') || 'detail-field-list-move ps-8 pr-16 bg-primary-300 hover:border-primary-600 transition duration-300 hover:text-primary-600 px-[10px] py-[8px] w-full flex text-[#333] border border-[#dddddd] rounded-[5px] text-[.8rem]';
        var wrap = document.createElement('div');
        wrap.className = 'flex justify-between items-center relative';
        var a = document.createElement('a');
        a.href = '#';
        a.setAttribute('role', 'button');
        a.setAttribute('data-action', 'remove');
        a.className = linkClass;
        a.textContent = verboseName;
        var btnWrap = document.createElement('div');
        btnWrap.className = 'flex absolute end-0 h-full';
        var up = document.createElement('button');
        up.type = 'button';
        up.setAttribute('data-action', 'move_up');
        up.className = 'detail-field-list-move border-[1px] border-e-[0px] border-[solid] w-8 text-primary-600 text-xs transition duration-300';
        up.innerHTML = '<i class="fa-solid fa-angle-up"></i>';
        var down = document.createElement('button');
        down.type = 'button';
        down.setAttribute('data-action', 'move_down');
        down.className = 'detail-field-list-move border-[1px] border-[solid] w-8 text-primary-600 text-xs transition duration-300 rounded-e-[5px]';
        down.innerHTML = '<i class="fa-solid fa-angle-down"></i>';
        btnWrap.appendChild(up);
        btnWrap.appendChild(down);
        wrap.appendChild(a);
        wrap.appendChild(btnWrap);
        li.innerHTML = '';
        li.setAttribute('data-field-name', fieldName);
        li.setAttribute('data-verbose-name', verboseName);
        li.setAttribute('data-section', section);
        li.appendChild(wrap);
    }
    document.body.addEventListener('click', function (e) {
        var form = e.target.closest('#detailFieldSelectorForm');
        var trigger = e.target.closest('.detail-field-list-move');
        if (!form || !trigger) return;
        e.preventDefault();
        e.stopPropagation();
        var action = trigger.getAttribute('data-action');
        var li = trigger.closest('li[data-section][data-field-name]');
        if (!li) return;
        var section = li.getAttribute('data-section');
        var fieldName = li.getAttribute('data-field-name');
        var verboseName = li.getAttribute('data-verbose-name');
        var availableList = document.getElementById(section === 'header' ? 'headerAvailableFields' : 'detailsAvailableFields');
        var visibleList = document.getElementById(section === 'header' ? 'headerVisibleFields' : 'detailsVisibleFields');
        if (!availableList || !visibleList) return;
        if (action === 'add') {
            detailFieldLiAsVisible(li, form);
            visibleList.appendChild(li);
            syncDetailAvailablePlaceholder(availableList);
            syncDetailHiddenInputs(form, section);
        } else if (action === 'remove') {
            detailFieldLiAsAvailable(li, form);
            availableList.appendChild(li);
            syncDetailAvailablePlaceholder(availableList);
            syncDetailHiddenInputs(form, section);
        } else if (action === 'move_up') {
            var prev = li.previousElementSibling;
            if (prev && prev.matches('li[data-field-name]')) {
                visibleList.insertBefore(li, prev);
            } else {
                visibleList.appendChild(li);
            }
            syncDetailHiddenInputs(form, section);
        } else if (action === 'move_down') {
            var next = li.nextElementSibling;
            if (next && next.matches('li[data-field-name]')) {
                visibleList.insertBefore(next, li);
            } else {
                visibleList.insertBefore(li, visibleList.firstChild);
            }
            syncDetailHiddenInputs(form, section);
        }
    });

    // Sync hidden inputs right before form submit so removed/moved fields are persisted
    document.body.addEventListener('submit', function (e) {
        var form = e.target;
        if (form && form.id === 'detailFieldSelectorForm') {
            syncDetailHiddenInputs(form, 'header');
            syncDetailHiddenInputs(form, 'details');
        }
    }, true);
});

/* ==========================================================================
   Split view: active tile (red line) and sync on prev/next / HTMX load
   Uses event delegation so it works when split view is loaded via navbar (HTMX).
   ========================================================================== */
(function () {
    var ACTIVE_CLASS = 'split-view-tile-active';

    function clearTileSelection() {
        var list = document.getElementById('split-view-tiles');
        if (!list) return;
        var tiles = list.querySelectorAll('.split-view-tile');
        tiles.forEach(function (el) {
            el.classList.remove(ACTIVE_CLASS);
        });
    }

    function setTileSelected(tile) {
        if (!tile) return;
        clearTileSelection();
        tile.classList.add(ACTIVE_CLASS);
        window._splitViewSelectedId = tile.getAttribute('data-id');
    }

    function setActiveTileById(id) {
        if (!id) return;
        var list = document.getElementById('split-view-tiles');
        if (!list) return;
        var t = list.querySelector('.split-view-tile[data-id="' + id + '"]');
        if (t) {
            clearTileSelection();
            t.classList.add(ACTIVE_CLASS);
            window._splitViewSelectedId = id;
        }
    }

    // Tile click: delegate so it works when split view is loaded via HTMX (navbar)
    document.body.addEventListener('click', function (e) {
        var tile = e.target.closest('.split-view-tile');
        if (!tile) return;
        var list = document.getElementById('split-view-tiles');
        if (!list || !list.contains(tile)) return;
        if (!tile.getAttribute('hx-get')) return;
        var tileId = tile.getAttribute('data-id');
        if (!tileId) return;
        setTileSelected(tile);
    }, true);

    // Deleting from the split panel reloads the list; remember the record that
    // follows the deleted one so the panel can open it instead of the first.
    document.body.addEventListener('click', function (e) {
        if (!e.target.closest('#splitViewDetailPanel [hx-target="#deleteModeBox"]')) return;
        var fragment = document.querySelector('#splitViewDetailPanel [data-object-id]');
        var list = document.getElementById('split-view-tiles');
        if (!fragment || !list) return;
        var id = fragment.getAttribute('data-object-id');
        var tile = list.querySelector('.split-view-tile[data-id="' + id + '"]');
        var next = tile && tile.nextElementSibling;
        while (next && !next.classList.contains('split-view-tile')) {
            next = next.nextElementSibling;
        }
        window._splitViewDeletePending = {
            id: id,
            nextId: next ? next.getAttribute('data-id') : null
        };
    }, true);

    // Initial detail load after the reload: open the next record if the
    // deleted one is gone; with no next record the default (first) loads.
    document.body.addEventListener('htmx:configRequest', function (evt) {
        var el = evt.detail.elt;
        var pending = window._splitViewDeletePending;
        if (!el || el.id !== 'splitViewDetailPanel' || !pending) return;
        window._splitViewDeletePending = null;
        var list = document.getElementById('split-view-tiles');
        if (!list || !pending.nextId) return;
        if (list.querySelector('.split-view-tile[data-id="' + pending.id + '"]')) return;
        var nextTile = list.querySelector('.split-view-tile[data-id="' + pending.nextId + '"]');
        var url = nextTile && nextTile.getAttribute('hx-get');
        if (!url) return;
        evt.detail.path = url;
        window._splitViewSelectedId = pending.nextId;
    });

    // After detail panel swap: sync active tile (tile click or prev/next)
    document.body.addEventListener('htmx:afterSwap', function (evt) {
        if (evt.detail.target.id !== 'splitViewDetailPanel') return;
        var selectedId = window._splitViewSelectedId;
        window._splitViewSelectedId = null;
        clearTileSelection();
        if (!selectedId) {
            var container = evt.detail.target;
            var el = container.querySelector && container.querySelector('[data-object-id]');
            if (el) selectedId = el.getAttribute('data-object-id');
        }
        if (selectedId) {
            var list = document.getElementById('split-view-tiles');
            if (list) {
                var t = list.querySelector('.split-view-tile[data-id="' + selectedId + '"]');
                if (t) {
                    t.classList.add(ACTIVE_CLASS);
                    t.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
                }
            }
        }
    });
})();


// ─── User Picker Modal ────────────────────────────────────────────────────────
(function () {
    'use strict';

    // Selections persist across HTMX list reloads: { id: { id, text } }
    var _selected = {};

    // Re-tick checkboxes after every list swap; pre-populate on modal load
    document.body.addEventListener('htmx:afterSwap', function (evt) {
        if (!evt.detail || !evt.detail.target) return;
        var targetId = evt.detail.target.id;

        if (targetId === 'horillaModalBox') {
            _selected = {};
            _matchIds = null;
            var el = evt.detail.target.querySelector('[data-field-id]');
            if (el) {
                var $sel = $('#' + el.dataset.fieldId);
                $sel.find('option:selected').each(function () {
                    var id = $(this).val(), text = $(this).text();
                    if (id) _selected[id] = { id: id, text: text };
                });
            }
        }

        // Lazy-loaded pages swap the sentinel (outerHTML), so the target is not
        // #userPickerList itself; re-tick whenever the list exists.
        if (targetId === 'userPickerList' || (targetId !== 'horillaModalBox' && document.getElementById('userPickerList') && !evt.detail.target.isConnected)) {
            document.querySelectorAll('#userPickerList .up-row-cb').forEach(function (cb) {
                cb.checked = !!_selected[cb.value];
                var row = cb.closest('.up-list-row');
                if (row) row.classList.toggle('bg-primary-50', cb.checked);
            });
            _syncSelectAll();
            _updateCount();
            if (targetId === 'userPickerList') _loadMatchIds();
            // Destroy any Select2 accidentally applied to filter selects
            $('[data-no-select2="true"].select2-hidden-accessible').each(function () {
                $(this).select2('destroy');
            });
        }
    });

    // Comma-joined ids already chosen in the underlying field, so the server
    // can list them first when the modal opens
    window.upInitialSelected = function () {
        var el = document.querySelector('#horillaModalBox [data-field-id]');
        if (!el) return '';
        return $('#' + el.dataset.fieldId).find('option:selected').map(function () {
            return $(this).val();
        }).get().filter(Boolean).join(',');
    };

    // ── Add filter row (needs JS only to compute next row_id)
    window.upAddFilterRow = function (filterUrl) {
        var rows  = document.querySelectorAll('#up-filter-rows .up-filter-row');
        var rowId = rows.length > 0 ? parseInt(rows[rows.length - 1].dataset.rowId || '0', 10) : 0;
        htmx.ajax('GET', filterUrl + '?add_filter_row=true&row_id=' + rowId, {
            target: '#up-filter-rows', swap: 'beforeend',
        });
    };

    // ── Row click / checkbox
    window.upRowClick = function (row) {
        var cb = row.querySelector('.up-row-cb');
        if (!cb) return;
        cb.checked = !cb.checked;
        _onToggle(cb, row);
    };
    window.upCbChange = function (cb) { _onToggle(cb, cb.closest('.up-list-row')); };

    function _onToggle(cb, row) {
        var id = cb.value, text = row ? row.dataset.text : cb.value;
        if (cb.checked) {
            _selected[id] = { id: id, text: text };
            if (row) row.classList.add('bg-primary-50');
        } else {
            delete _selected[id];
            if (row) row.classList.remove('bg-primary-50');
        }
        _syncSelectAll();
        _updateCount();
    }

    // Current search + filter params (shared by select-all and the match counter)
    function _filterParams() {
        var params = new URLSearchParams();
        var search = document.getElementById('userPickerSearch');
        if (search && search.value) params.set('search', search.value);
        document.querySelectorAll(
            "#up-filter-rows [name='field'],[name='operator'],[name='value'],[name='start_value'],[name='end_value'],[name='logic']"
        ).forEach(function (input) {
            if (input.name && input.value) params.append(input.name, input.value);
        });
        params.set('all_ids', 'true');
        return params;
    }

    // Ids matching the current search/filter, so the counter can show X of Y
    var _matchIds = null;
    function _loadMatchIds() {
        var listEl = document.getElementById('userPickerList');
        var listUrl = listEl && listEl.getAttribute('hx-get');
        if (!listUrl) return;
        fetch(listUrl + (listUrl.indexOf('?') === -1 ? '?' : '&') + _filterParams().toString(), {
            headers: { 'HX-Request': 'true' },
        })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                _matchIds = (d.items || []).map(function (i) { return String(i.id); });
                _updateCount();
            })
            .catch(function () { _matchIds = null; });
    }

    // ── Select-all (acts on every item matching the current search/filter,
    //    not just the rows already lazy-loaded into the DOM)
    window.upToggleAll = function (masterCb) {
        var checked = masterCb.checked;

        // All results are already ticked but other users outside them are still
        // selected: treat the click as "keep only these results", not "untick".
        if (!checked && _matchIds && _matchIds.length) {
            var inRes = _matchIds.filter(function (id) { return _selected[id]; }).length;
            if (inRes === _matchIds.length && Object.keys(_selected).length > inRes) {
                checked = true;
                masterCb.checked = true;
            }
        }

        function applyToRenderedRows() {
            document.querySelectorAll('#userPickerList .up-row-cb').forEach(function (cb) {
                cb.checked = checked;
                var row = cb.closest('.up-list-row'), id = cb.value;
                if (checked) {
                    _selected[id] = { id: id, text: row ? row.dataset.text : id };
                    if (row) row.classList.add('bg-primary-50');
                } else {
                    delete _selected[id];
                    if (row) row.classList.remove('bg-primary-50');
                }
            });
            _updateCount();
        }

        // Checking Select All replaces the selection with the filtered results only
        if (checked) _selected = {};
        applyToRenderedRows();

        var listEl = document.getElementById('userPickerList');
        var listUrl = listEl && listEl.getAttribute('hx-get');
        if (!listUrl) return;

        var params = _filterParams();

        fetch(listUrl + (listUrl.indexOf('?') === -1 ? '?' : '&') + params.toString(), {
            headers: { 'HX-Request': 'true' },
        })
            .then(function (resp) { return resp.json(); })
            .then(function (data) {
                (data.items || []).forEach(function (item) {
                    if (checked) {
                        _selected[item.id] = { id: item.id, text: item.text };
                    } else {
                        delete _selected[item.id];
                    }
                });
                applyToRenderedRows();
            })
            .catch(function () { /* keep the DOM-scoped selection already applied */ });
    };

    function _syncSelectAll() {
        var master = document.getElementById('userPickerSelectAll');
        if (!master) return;
        var all = Array.from(document.querySelectorAll('#userPickerList .up-row-cb'));
        var n   = all.filter(function (c) { return c.checked; }).length;
        master.indeterminate = all.length > 0 && n > 0 && n < all.length;
        master.checked       = all.length > 0 && n === all.length;
    }

    function _updateCount() {
        var el = document.getElementById('userPickerCount');
        var n  = Object.keys(_selected).length;
        if (!el) return;
        var txt = n > 0 ? n + ' selected' : '';
        if (n > 0 && _matchIds) {
            var inResults = _matchIds.filter(function (id) { return _selected[id]; }).length;
            if (inResults === n) {
                // Every selected user is in the results: one figure is enough.
                if (_matchIds.length !== n) txt = n + ' of ' + _matchIds.length + ' selected';
            } else {
                txt = inResults + ' of ' + _matchIds.length + ' in results · ' + txt;
            }
        }
        el.textContent = txt;
    }

    // ── Confirm: write selections back to originating Select2 field
    window.userPickerConfirm = function () {
        var box = document.getElementById('horillaModalBox');
        var el  = box && box.querySelector('[data-field-id]');
        if (!el) return;
        var $sel = $('#' + el.dataset.fieldId);
        if (!$sel.length) return;
        Object.keys(_selected).forEach(function (id) {
            if (!$sel.find('option[value="' + id + '"]').length)
                $sel.append(new Option(_selected[id].text, id, false, false));
        });
        $sel.val(Object.keys(_selected)).trigger('change');
        closehorillaModal();
    };

}());

/* ==========================================================================
   Header - Notifications, dark mode, websocket
   ========================================================================== */
(function () {
    const _noUnreadNotifications = gettext("No unread notifications");
    const _noNotifications = gettext("No notifications");

    document.body.addEventListener('htmx:afterSwap', function(event){
        if(event.target.classList.contains('notification-list')) {
        updateNotificationCount();
        }
    });

    document.body.addEventListener('htmx:afterSwap', function(event){
        const target = event.detail.target;
        if(target && target.id && target.id.startsWith('notif-')) {
            const notifId = target.id.replace('notif-', '');
            setTimeout(function() {
                updateNotificationCount();
                toggleNotificationDot('all-notif-' + notifId);
            }, 100);
        }
    });

    document.body.addEventListener('htmx:afterRequest', function(event){
        const target = event.detail.target;
        if(target && target.id && target.id.startsWith('notif-')) {
            setTimeout(function() {
                updateNotificationCount();
            }, 150);
        }
    });

    window.toggleNotificationDot = function toggleNotificationDot(notifId) {
        const dot = document.querySelector(`#${notifId} .notif-indicator`);
        if (dot) {
        dot.classList.remove("bg-red-500");
        }
    }

    window.deleteDropdwonNotification = function deleteDropdwonNotification(notifId) {
        const notif = document.getElementById(notifId);
        if (notif) {
            notif.remove();
        }
    }

    window.markAllDotsAsRead = function markAllDotsAsRead() {
        document.querySelectorAll('.notif-indicator').forEach(dot => {
            dot.classList.remove('bg-red-500');
        });
    }

    window.updateNotificationCount = function updateNotificationCount(change = 0) {
        const badge = document.querySelector("#notification-count");
        const notifList = document.querySelector(".notification-list");

        if (!badge || !notifList) return;

        let currentCount = parseInt(badge.textContent) || 0;

        if (change === 0) {
            currentCount = notifList.querySelectorAll("li:not(.dropdown-notif-message)").length;
        } else {
            currentCount = Math.max(0, currentCount + change);
        }

        badge.textContent = currentCount;
        badge.style.display = 'flex';
        badge.classList.toggle('hidden', false);

        if (currentCount === 0) {
            notifList.innerHTML = `
            <li class="dropdown-notif-message text-center text-xs text-gray-500 py-2">
                ${_noUnreadNotifications}
            </li>
            `;
        }
    }

    window.removeOpenedNotification = function removeOpenedNotification(el) {
        if (!el || !el.id || !el.id.startsWith('notif-')) return;
        const notifId = el.id.replace('notif-', '');
        if (el.parentNode) el.remove();
        updateNotificationCount(-1);
        if (notifId) toggleNotificationDot('all-notif-' + notifId);
    }

    window.deleteAllDropdownNotifications = function deleteAllDropdownNotifications() {
        const notifList = document.querySelector('.notification-list');
        if (notifList) {
            notifList.querySelectorAll('li').forEach(item => item.remove());
        }

        if (notifList) {
        notifList.innerHTML = `<li class="dropdown-notif-message text-center text-xs text-gray-500 py-2">${_noUnreadNotifications}</li>`;
        }

        const badge = document.querySelector('#notification-count');
        if (badge) {
        badge.textContent = "0";
        }
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    let _notifAudioBuffer = null;
    let _notifAudioCtx = null;

    (function loadNotificationSound() {
        _notifAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
        fetch("/static/audio/notification-sound.wav")
            .then(function(r) { return r.arrayBuffer(); })
            .then(function(buf) { return _notifAudioCtx.decodeAudioData(buf); })
            .then(function(decoded) { _notifAudioBuffer = decoded; })
            .catch(function(e) { console.warn("Could not load notification sound:", e); });
    })();

    document.addEventListener("click", function() {
        if (_notifAudioCtx && _notifAudioCtx.state === "suspended") {
            _notifAudioCtx.resume();
        }
    }, { once: true });

    function playNotificationSound() {
        const btn = document.getElementById("notificationSoundToggle");
        if (btn && btn.getAttribute("data-muted") === "true") return;
        if (!_notifAudioBuffer || !_notifAudioCtx) return;
        if (_notifAudioCtx.state === "suspended") { _notifAudioCtx.resume(); }
        const source = _notifAudioCtx.createBufferSource();
        source.buffer = _notifAudioBuffer;
        source.connect(_notifAudioCtx.destination);
        source.start(0);
    }

    window.handleNewNotification = function handleNewNotification(data) {
        const timesince = "Just now";

        addToDropdownList(data, timesince);
        addToSidebarList(data, timesince);
        updateNotificationCount(1);
        playNotificationSound();

        if ("Notification" in window && Notification.permission === "granted") {
        new Notification("New Notification", {
            body: data.message,
            icon: "/static/favicon.ico"
        });
        }
    }

    function addToDropdownList(data, timesince) {
        const dropdownList = document.querySelector(".notification-list");
        const sidebar = document.querySelector(".notification-message")
        const dropdown = document.querySelector(".dropdown-notif-message")

        if (sidebar) {
        sidebar.remove();
        }
        if (dropdown) {
        dropdown.remove();
        }

        const newDropdownItem = document.createElement("li");
        newDropdownItem.id = `notif-${data.id}`;
        newDropdownItem.className = "mb-3 cursor-pointer";
        newDropdownItem.setAttribute("hx-get", data.open_url);
        newDropdownItem.setAttribute("hx-trigger", "click");
        newDropdownItem.setAttribute("hx-target", "#modalBox");
        newDropdownItem.setAttribute("hx-swap", "innerHTML");
        newDropdownItem.setAttribute("hx-on:click", "openModal(); (function(e){ var el = e.currentTarget; setTimeout(function(){ removeOpenedNotification(el); }, 100); })(event)");


        newDropdownItem.innerHTML = `
        <div class="flex items-center justify-between">
            <span>${data.message}</span>
            <button
                hx-post="/notifications/notifications-read/${data.id}/"
                hx-target="#notif-${data.id}"
                onclick="event.stopPropagation();"
                hx-swap="outerHTML"
                class="cursor-pointer text-xs group text-primary-600 w-6 h-6 bg-primary-100
                    hover:bg-primary-600 hover:text-white rounded-full transition duration-300 flex items-center justify-center">
                <i class="fa-solid fa-check text-[10px]"></i>
            </button>
        </div>
        <p class="text-xs text-[#777777] mt-1">
            ${timesince} by ${escapeHtml(data.sender)}
        </p>
        `;

        dropdownList.insertBefore(newDropdownItem, dropdownList.firstChild);

        const items = dropdownList.querySelectorAll("li");
        if (items.length > 5) {
        items[items.length - 1].remove();
        }

        if (window.htmx) {
        htmx.process(newDropdownItem);
        }
    }

    function addToSidebarList(data, timesince) {
        const sidebarContent = document.querySelector("#sidebarModal3 > div");
        if (!sidebarContent) {
        console.error("Sidebar content (#sidebarModal3 > div) not found");
        return;
        }


        const newSidebarItem = document.createElement("div");
        newSidebarItem.className = "border border-dark-50 p-3 rounded-md mb-2 relative";
        newSidebarItem.id = `all-notif-${data.id}`;
        newSidebarItem.innerHTML = `
        <button
            hx-post="/notifications/notification-delete/${data.id}/"
            class="delete-notification absolute top-2 end-2 text-xs"
            hx-on:click="setTimeout(() => $('#reloadMessagesButton').click(), 500)"
            hx-on:htmx:afterRequest="if(event.detail.successful) fadeAndRemoveNotification('all-notif-${data.id}')"
            data-target="#all-notif-${data.id}">
            <i class="fa-solid fa-xmark"></i>
        </button>
        <div class="flex items-start gap-2">
        <div class="w-2 h-2 bg-red-500 rounded-full mt-2 flex-shrink-0"></div>
            <div class="flex-1">
                <h5 class="text-sm font-semibold mb-2">${data.message}</h5>
                <p class="text-xs text-[#777777] mt-1">${timesince} by ${escapeHtml(data.sender)}</p>
            </div>
        </div>
        `;

        const header = sidebarContent.querySelector('.flex.justify-between');
        if (header) {
        const firstNotification = sidebarContent.querySelector('.border');
        if (firstNotification) {
            sidebarContent.insertBefore(newSidebarItem, firstNotification);
        } else {
            header.insertAdjacentElement('afterend', newSidebarItem);
        }
        } else {
        sidebarContent.insertBefore(newSidebarItem, sidebarContent.firstChild);
        }

        if (window.htmx) {
        htmx.process(newSidebarItem);
        }
    }

    function getSidebarBackdrop() {
        let backdrop = document.getElementById("sidebarBackdrop");
        if (!backdrop) {
            backdrop = document.createElement("div");
            backdrop.id = "sidebarBackdrop";
            backdrop.style.cssText = "position:fixed;inset:0;z-index:998;background:transparent;display:none;";
            document.body.appendChild(backdrop);
        }
        return backdrop;
    }

    window.openSidebar = function openSidebar(id) {
        const sidebar = document.getElementById(id);
        if (!sidebar) return;
        sidebar.classList.remove("hidden");
        setTimeout(() => sidebar.classList.add("active"), 10);
        document.body.classList.add("overflow-hidden");
        const backdrop = getSidebarBackdrop();
        backdrop.style.display = "block";
        backdrop.onclick = () => closeSidebar(id);
    }

    window.closeSidebar = function closeSidebar(id) {
        const sidebar = document.getElementById(id);
        if (!sidebar) return;
        sidebar.classList.remove("active");
        document.body.classList.remove("overflow-hidden");
        const backdrop = getSidebarBackdrop();
        backdrop.style.display = "none";
        backdrop.onclick = null;

        sidebar.addEventListener("transitionend", function hideSidebar() {
            sidebar.classList.add("hidden");
            sidebar.removeEventListener("transitionend", hideSidebar);
        });
    }

    document.addEventListener("DOMContentLoaded", () => {
        const userId = parseInt(document.body.dataset.userId, 10) || 0;
        if (userId === 0) {
        console.warn("User not authenticated, skipping WebSocket");
        return;
        }

        let socket = null;
        let reconnectAttempts = 0;
        const maxReconnectAttempts = 5;
        const reconnectInterval = 3000;

        function connectWebSocket() {
        const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        socket = new WebSocket(`${wsProtocol}//${window.location.host}/ws/notifications/`);

        socket.onopen = () => {
            reconnectAttempts = 0;
        };

        socket.onerror = (error) => {
            console.error("WebSocket error:", error);
        };

        socket.onclose = (event) => {
            if (reconnectAttempts < maxReconnectAttempts) {
            reconnectAttempts++;
            const delay = reconnectInterval * Math.pow(2, reconnectAttempts - 1);
            setTimeout(connectWebSocket, delay);
            } else {
            console.error("Max reconnection attempts reached");
            }
        };

        socket.onmessage = (event) => {
            try {
            const data = JSON.parse(event.data);
            handleNewNotification(data);
            } catch (error) {
            console.error("Error processing WebSocket message:", error);
            }
        };
        }

        connectWebSocket();

        if ("Notification" in window && Notification.permission === "default") {
        Notification.requestPermission();
        }

    });

    document.addEventListener('click', function(event) {
        const dropdowns = document.querySelectorAll('.dropdown-wrapper');
        dropdowns.forEach(dropdown => {
        const button = dropdown.querySelector('button');
        const content = dropdown.querySelector('.dropdown-content');
        if (!button || !content) return;

        if (button.contains(event.target)) {
            content.classList.toggle('hidden');
            dropdowns.forEach(otherDropdown => {
            if (otherDropdown !== dropdown) {
                const otherContent = otherDropdown.querySelector('.dropdown-content');
                if (otherContent) {
                otherContent.classList.add('hidden');
                }
            }
            });
        } else if (!dropdown.contains(event.target)) {
            content.classList.add('hidden');
        }
        });
    });

    $(document).on("htmx:afterRequest", function(event) {
        if ($(event.target).hasClass("delete-notification")) {
        const targetId = $(event.target).data("target");
        $(targetId).remove();
        updateNotificationCount(-1);

        if ($("#sidebarModal3 .border").length === 0) {
            $("#sidebarModal3").append(
            `<div class="notification-message text-center text-xs text-gray-500 py-2">${_noNotifications}</div>`
            );
        }
        }
    });

    (function initDarkMode() {
        const savedTheme = localStorage.getItem("theme");
        const html = document.documentElement;

        // Set default if not set
        if (!savedTheme) {
            localStorage.setItem("theme", "light");
        }

        // Ensure classes are correct
        if (savedTheme === "dark") {
            html.classList.add("dark");
            document.body.classList.add("dark");
            html.style.colorScheme = "dark";
        } else {
            html.classList.remove("dark");
            document.body.classList.remove("dark");
            html.style.colorScheme = "light";
        }
    })();

    // Update UI when DOM is ready
    document.addEventListener("DOMContentLoaded", () => {
        const savedTheme = localStorage.getItem("theme") || "light";
        const toggleBtn = document.getElementById("darkModeToggle");

        if (!toggleBtn) return;

        const icon = toggleBtn.querySelector(".fa-solid");

        // Update button appearance
        if (savedTheme === "dark") {
            toggleBtn.setAttribute("aria-pressed", "true");
            if (icon) {
                icon.classList.remove("fa-moon");
                icon.classList.add("fa-lightbulb");
            }
        } else {
            toggleBtn.setAttribute("aria-pressed", "false");
            if (icon) {
                icon.classList.remove("fa-lightbulb");
                icon.classList.add("fa-moon");
            }
        }

        // Toggle button handler
        toggleBtn.addEventListener("click", () => {
            const html = document.documentElement;
            const body = document.body;
            const isDark = html.classList.contains("dark");

            if (isDark) {
                // Switch to light
                html.classList.remove("dark");
                body.classList.remove("dark");
                html.style.colorScheme = "light";
                localStorage.setItem("theme", "light");
                toggleBtn.setAttribute("aria-pressed", "false");

                if (icon) {
                    icon.classList.remove("fa-lightbulb");
                    icon.classList.add("fa-moon");
                }
            } else {
                // Switch to dark
                html.classList.add("dark");
                body.classList.add("dark");
                html.style.colorScheme = "dark";
                localStorage.setItem("theme", "dark");
                toggleBtn.setAttribute("aria-pressed", "true");

                if (icon) {
                    icon.classList.remove("fa-moon");
                    icon.classList.add("fa-lightbulb");
                }
            }

            // Refresh charts
            if (typeof window.chartInstances !== "undefined") {
                Object.keys(window.chartInstances).forEach(key => {
                    const chartData = window.chartInstances[key];
                    if (chartData && chartData.instance && chartData.config) {
                        EChartsConfig.refreshChartTheme(chartData.instance, chartData.config);
                    }
                });
            }
        });
    });

    // IMPORTANT: Also handle HTMX page swaps
    document.body.addEventListener('htmx:afterSwap', function() {
        const theme = localStorage.getItem("theme");
        if (theme === "dark") {
            document.documentElement.classList.add("dark");
            document.body.classList.add("dark");
        }
    });

    function isRtlDocument() {
        return (document.documentElement.getAttribute("dir") || "").toLowerCase() === "rtl";
    }

    function getDirectSortableItems(container) {
        if (!container) {
            return [];
        }
        return Array.prototype.filter.call(container.children, function (el) {
            return el.matches("[data-component-id], [data-id]");
        });
    }

    function getSortableItemId(el) {
        return el.getAttribute("data-component-id") || el.getAttribute("data-id");
    }

    var DASHBOARD_SORTABLE_ROW_TOLERANCE = 8;

    /** Group sortable cards into visual rows (top → bottom, left → right within a row). */
    function groupSortableItemsByVisualRow(items) {
        if (!items.length) {
            return [];
        }
        var entries = items.map(function (el) {
            return { el: el, rect: el.getBoundingClientRect() };
        });
        entries.sort(function (a, b) {
            var rowDiff = a.rect.top - b.rect.top;
            if (Math.abs(rowDiff) > DASHBOARD_SORTABLE_ROW_TOLERANCE) {
                return rowDiff;
            }
            return a.rect.left - b.rect.left;
        });
        var rows = [];
        var currentRow = [];
        var rowTop = null;
        entries.forEach(function (entry) {
            if (
                rowTop === null ||
                Math.abs(entry.rect.top - rowTop) <= DASHBOARD_SORTABLE_ROW_TOLERANCE
            ) {
                currentRow.push(entry);
                if (rowTop === null) {
                    rowTop = entry.rect.top;
                }
            } else {
                rows.push(currentRow);
                currentRow = [entry];
                rowTop = entry.rect.top;
            }
        });
        if (currentRow.length) {
            rows.push(currentRow);
        }
        return rows;
    }

    function restoreDirectSortableOrder(container, ids) {
        if (!container || !ids || !ids.length) {
            return;
        }
        var items = getDirectSortableItems(container);
        var byKey = {};
        items.forEach(function (el) {
            var key = getSortableItemId(el);
            if (key) {
                byKey[key] = el;
            }
        });
        ids.forEach(function (id) {
            if (byKey[id]) {
                container.appendChild(byKey[id]);
            }
        });
    }

    /**
     * While the grid is still RTL, put each row into left→right DOM order.
     * Switching the container to dir=ltr afterwards keeps the same on-screen
     * layout so Sortable (LTR-only) can hit-test correctly.
     */
    function mirrorRtlGridRowsForLtrEdit(container) {
        var editOrder = [];
        groupSortableItemsByVisualRow(getDirectSortableItems(container)).forEach(
            function (row) {
                row.forEach(function (entry) {
                    editOrder.push(entry.el);
                });
            }
        );
        restoreDirectSortableOrder(
            container,
            editOrder.map(getSortableItemId).filter(Boolean)
        );
    }

    /** Visual left→right edit order → RTL storage order (first id = rightmost). */
    function collectRtlDashboardStorageOrder(container) {
        var ids = [];
        groupSortableItemsByVisualRow(getDirectSortableItems(container)).forEach(
            function (row) {
                var rowIds = row
                    .map(function (entry) {
                        return getSortableItemId(entry.el);
                    })
                    .filter(Boolean);
                rowIds.reverse();
                ids = ids.concat(rowIds);
            }
        );
        return ids;
    }

    /**
     * Sortable options for dashboard grid reorder.
     * In RTL, pair with prepareHorillaDashboardSortableContainer() so Sortable
     * uses LTR hit-testing without flipping the on-screen layout.
     */
    window.getHorillaDashboardSortableOptions = function (overrides) {
        var opts = {
            handle: ".edit-drag-handle",
            animation: 150,
            ghostClass: "opacity-50",
            draggable: "[data-component-id], [data-id]",
            direction: "horizontal",
            swapThreshold: 0.65,
            invertSwap: false,
            touchStartThreshold: 5,
        };
        if (overrides) {
            Object.assign(opts, overrides);
        }
        return opts;
    };

    window.prepareHorillaDashboardSortableContainer = function (container) {
        if (!container) {
            return;
        }
        container.classList.add("horilla-dashboard-sortable");
        if (!isRtlDocument()) {
            container.classList.add("is-edit-sortable");
            return;
        }
        var ids = getDirectSortableItems(container).map(getSortableItemId);
        container.dataset.horillaSortableOriginal = JSON.stringify(ids);
        container.dataset.horillaSortableRtlPrepared = "1";
        mirrorRtlGridRowsForLtrEdit(container);
        container.setAttribute("dir", "ltr");
        container.classList.add("is-edit-sortable");
    };

    window.resetHorillaDashboardSortableContainer = function (container, restoreOriginal) {
        if (!container) {
            return;
        }
        if (restoreOriginal === undefined) {
            restoreOriginal = true;
        }
        if (container.dataset.horillaSortableRtlPrepared) {
            if (restoreOriginal) {
                restoreDirectSortableOrder(
                    container,
                    JSON.parse(container.dataset.horillaSortableOriginal || "[]")
                );
            } else {
                restoreDirectSortableOrder(
                    container,
                    collectRtlDashboardStorageOrder(container)
                );
            }
            container.removeAttribute("dir");
            delete container.dataset.horillaSortableOriginal;
            delete container.dataset.horillaSortableRtlPrepared;
        }
        container.classList.remove(
            "horilla-dashboard-sortable",
            "is-edit-sortable",
            "horilla-dashboard-sortable--rtl-edit"
        );
    };

    /** Map edit-mode layout back to normal RTL dashboard order for save. */
    window.collectHorillaDashboardSortableOrder = function (container, sortableInstance) {
        if (container && container.dataset.horillaSortableRtlPrepared) {
            return collectRtlDashboardStorageOrder(container);
        }
        if (sortableInstance && typeof sortableInstance.toArray === "function") {
            return sortableInstance.toArray().filter(Boolean);
        }
        if (!container) {
            return [];
        }
        return getDirectSortableItems(container).map(getSortableItemId).filter(Boolean);
    };

    // Auto-fill any <input type="color"> that has no saved value yet with
    // the app's accent color, instead of the browser's black default.
    // Reads --split-view-active-border, which style.css always defines
    // (falls back to #E54F38) and may be overridden elsewhere at runtime.
    //
    // An input counts as "unsaved" when it has no data-saved attribute
    // value and its current value is empty or the browser default.
    (function () {
        var UNSET_VALUES = ["", "#000000"];

        function resolveAccentColor() {
            return (
                getComputedStyle(document.documentElement)
                    .getPropertyValue('--split-view-active-border')
                    .trim() || '#E54F38'
            );
        }

        function isUnsaved(input) {
            if (input.dataset.saved) {
                return false;
            }
            return UNSET_VALUES.indexOf(input.value.toLowerCase()) !== -1;
        }

        function applyAccentColorDefaults() {
            var inputs = document.querySelectorAll('input[type="color"]');
            if (!inputs.length) {
                return;
            }
            var accent = resolveAccentColor();
            inputs.forEach(function (input) {
                if (isUnsaved(input)) {
                    input.value = accent;
                }
            });
        }

        function initAccentColorDefaults() {
            // setTimeout(0): let the browser paint injected CSS vars first.
            setTimeout(applyAccentColorDefaults, 0);
        }

        document.addEventListener('DOMContentLoaded', initAccentColorDefaults);
        document.body.addEventListener('htmx:afterSwap', initAccentColorDefaults);
        document.body.addEventListener('htmx:afterSettle', initAccentColorDefaults);
    })();

      // Auto-fill any <input type="color"> that has no saved value yet with
    // the app's accent color, instead of the browser's black default.
    // Reads --split-view-active-border, which style.css always defines
    // (falls back to #E54F38) and may be overridden elsewhere at runtime.
    //
    // An input counts as "unsaved" when it has no data-saved attribute
    // value and its current value is empty or the browser default.
    (function () {
        var UNSET_VALUES = ["", "#000000"];

        function resolveAccentColor() {
            return (
                getComputedStyle(document.documentElement)
                    .getPropertyValue('--split-view-active-border')
                    .trim() || '#E54F38'
            );
        }

        function isUnsaved(input) {
            if (input.dataset.saved) {
                return false;
            }
            return UNSET_VALUES.indexOf(input.value.toLowerCase()) !== -1;
        }

        function applyAccentColorDefaults() {
            var inputs = document.querySelectorAll('input[type="color"]');
            if (!inputs.length) {
                return;
            }
            var accent = resolveAccentColor();
            inputs.forEach(function (input) {
                if (isUnsaved(input)) {
                    input.value = accent;
                }
            });
        }

        function initAccentColorDefaults() {
            // setTimeout(0): let the browser paint injected CSS vars first.
            setTimeout(applyAccentColorDefaults, 0);
        }

        document.addEventListener('DOMContentLoaded', initAccentColorDefaults);
        document.body.addEventListener('htmx:afterSwap', initAccentColorDefaults);
        document.body.addEventListener('htmx:afterSettle', initAccentColorDefaults);
    })();

    // Detail view viewport fit: [data-viewport-fit] holds a header card,
    // pipeline bar and tab session stacked vertically. Fixed pixel/vh offsets
    // for the flexible sections go stale whenever the header card's field
    // count (and therefore its natural height) changes, so instead we measure
    // the real remaining space at runtime and split it between the flexible
    // sections ([data-viewport-flex]) by their weight — growing one shrinks
    // the other, both scrolling internally instead of pushing the page.
    (function () {
        // The nearest clipping ancestor (overflow hidden/auto/scroll) is the
        // real bottom boundary of the visible area. Falling back to
        // window.innerHeight assumes the shell's layout stretches flush to
        // the viewport edge, which isn't guaranteed (e.g. .modelcontent is a
        // plain block sized by content + padding, not a flex child that
        // fills its h-screen ancestor, so it can fall short of 100vh).
        function findClipAncestor(el) {
            var node = el.parentElement;
            while (node && node !== document.body) {
                var overflowY = getComputedStyle(node).overflowY;
                if (overflowY === 'hidden' || overflowY === 'auto' || overflowY === 'scroll') {
                    return node;
                }
                node = node.parentElement;
            }
            return null;
        }


        function findViewportPinnedAncestorBottom(el) {
            var node = el.parentElement;
            while (node && node !== document.body) {
                var rect = node.getBoundingClientRect();
                if (Math.abs(rect.height - window.innerHeight) < 1 && rect.top <= 1) {
                    return rect.bottom;
                }
                node = node.parentElement;
            }
            return null;
        }

        function fitViewport(root) {
            var flexEls = root.querySelectorAll(':scope > [data-viewport-flex]');
            if (!flexEls.length) {
                return;
            }

            // Let content take its natural size first so we can measure the
            // fixed-height siblings (breadcrumbs, pipeline bar) accurately.
            flexEls.forEach(function (el) {
                el.style.height = '';
            });

            var clipAncestor = findClipAncestor(root);
            var bottomBoundary = clipAncestor
                ? clipAncestor.getBoundingClientRect().bottom
                : window.innerHeight;
            var pinnedAncestorBottom = findViewportPinnedAncestorBottom(root);
            if (pinnedAncestorBottom !== null && pinnedAncestorBottom < bottomBoundary) {
                bottomBoundary = pinnedAncestorBottom;
            }
            var available = bottomBoundary - root.getBoundingClientRect().top;
            var children = Array.prototype.slice.call(root.children);
            children.forEach(function (child) {
                var style = getComputedStyle(child);
                // Out-of-flow children (e.g. absolutely positioned loading
                // overlays stretched via inset-0) take no space in normal
                // flow, so their bounding rect must not be subtracted.
                if (style.position === 'absolute' || style.position === 'fixed') {
                    return;
                }
                available -= parseFloat(style.marginTop) + parseFloat(style.marginBottom);
                if (!child.hasAttribute('data-viewport-flex')) {
                    available -= child.getBoundingClientRect().height;
                }
            });
            available -= parseFloat(getComputedStyle(root).paddingBottom) || 0;

            var totalWeight = 0;
            flexEls.forEach(function (el) {
                totalWeight += parseFloat(el.getAttribute('data-viewport-flex')) || 1;
            });

            var minHeight = 60;
            flexEls.forEach(function (el) {
                var weight = parseFloat(el.getAttribute('data-viewport-flex')) || 1;
                var height = Math.max(minHeight, (available * weight) / totalWeight);
                el.style.height = height + 'px';
            });
        }

        function fitAllViewports() {
            document.querySelectorAll('[data-viewport-fit]').forEach(fitViewport);
        }

        var _viewportFitTimer = null;
        function scheduleViewportFit() {
            clearTimeout(_viewportFitTimer);
            _viewportFitTimer = setTimeout(fitAllViewports, 0);
        }
        window.scheduleViewportFit = scheduleViewportFit;

        document.addEventListener('DOMContentLoaded', scheduleViewportFit);
        document.body.addEventListener('htmx:afterSettle', scheduleViewportFit);
        window.addEventListener('resize', scheduleViewportFit);
    })();

}());
