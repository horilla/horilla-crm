/**
 * Fixed-position black pill for any element with a non-empty title (no extra class).
 * title is read then removed while the pill is visible to avoid double tooltips;
 * restored on mouseleave / blur.
 *
 * Opt out: title="" or data-native-tooltip on the element keeps native tooltip only.
 *
 * Placement (optional on trigger):
 *   data-tooltip-placement="bottom" | "top" | "left" | "right"
 * Default: below trigger, centered; flips above if no room. With placement set,
 * position is fixed to that side and clamped to the viewport.
 */
(function () {
    var TOOLTIP_ID = "horilla-action-tooltip";
    var GAP = 6;
    var currentTrigger = null;

    // Tailwind-friendly base; wrapping via inline styles so it works without JIT on this file
    // Above #calendarPopup (10050) and FullCalendar popovers so pills show on calendar actions
    var TOOLTIP_CLASS =
        "fixed z-[10060] pointer-events-none opacity-0 transition-opacity duration-200 " +
        "py-[6px] px-[12px] bg-[#000000] text-[.7rem] rounded-[5px] text-white shadow-md";

    function getEl() {
        var el = document.getElementById(TOOLTIP_ID);
        if (!el) {
            el = document.createElement("div");
            el.id = TOOLTIP_ID;
            el.setAttribute("role", "tooltip");
            el.style.left = "0";
            el.style.top = "0";
            el.setAttribute("aria-hidden", "true");
            document.body.appendChild(el);
        }
        el.className = TOOLTIP_CLASS;
        // Lengthy titles: wrap into 2–3 lines (max width + normal whitespace)
        el.style.maxWidth = "280px";
        el.style.whiteSpace = "normal";
        el.style.overflowWrap = "break-word";
        el.style.wordBreak = "break-word";
        // Follow the text: Persian/Arabic titles read right to left, English left to right
        el.dir = "auto";
        el.style.textAlign = "start";
        el.style.lineHeight = "1.4";
        return el;
    }

    function getText(el) {
        if (!el || !el.getAttribute) return "";
        if (el.getAttribute("data-native-tooltip") === "true") return "";
        var t = (el.getAttribute("title") || "").trim();
        if (t) return t;
        return (el.getAttribute("aria-label") || "").trim() ||
            (el.getAttribute("data-tooltip") || "").trim();
    }

    /** Walk up from node to first element with tooltip text (title or aria-label; skip pill). */
    function findTrigger(node) {
        if (!node || node.nodeType !== 1) return null;
        if (node.id === TOOLTIP_ID) return null;
        var n = node;
        while (n && n !== document.documentElement) {
            if (n.id === TOOLTIP_ID) return null;
            if (n.getAttribute && n.getAttribute("data-native-tooltip") === "true")
                return null;
            if (getText(n)) return n;
            n = n.parentElement;
        }
        return null;
    }

    var titleBackup = null;
    var titleBackupEl = null;

    function show(trigger) {
        var text = getText(trigger);
        if (!text) return;
        var el = getEl();
        el.textContent = text;

        if (trigger.hasAttribute("title")) {
            titleBackup = trigger.getAttribute("title");
            titleBackupEl = trigger;
            trigger.removeAttribute("title");
        }

        currentTrigger = trigger;
        el.classList.remove("opacity-0");
        el.setAttribute("aria-hidden", "false");

        var rect = trigger.getBoundingClientRect();
        var tw = el.offsetWidth;
        var th = el.offsetHeight;
        var vw = window.innerWidth;
        var vh = window.innerHeight;
        var placement = (trigger.getAttribute("data-tooltip-placement") || "")
            .toLowerCase()
            .trim();
        var left, top;

        if (placement === "top") {
            left = rect.left + rect.width / 2 - tw / 2;
            top = rect.top - th - GAP;
        } else if (placement === "left") {
            left = rect.left - tw - GAP;
            top = rect.top + rect.height / 2 - th / 2;
        } else if (placement === "right") {
            left = rect.right + GAP;
            top = rect.top + rect.height / 2 - th / 2;
        } else if (placement === "bottom") {
            left = rect.left + rect.width / 2 - tw / 2;
            top = rect.bottom + GAP;
        } else {
            // Auto: prefer below, flip above if no room
            left = rect.left + rect.width / 2 - tw / 2;
            top = rect.bottom + GAP;
            if (top + th > vh - 8) top = rect.top - th - GAP;
            if (top < 8) top = rect.bottom + GAP;
        }

        // Viewport clamp
        if (left < 8) left = 8;
        if (left + tw > vw - 8) left = Math.max(8, vw - tw - 8);
        if (top < 8) top = 8;
        if (top + th > vh - 8) top = Math.max(8, vh - th - 8);

        el.style.left = left + "px";
        el.style.top = top + "px";
        el.style.visibility = "visible";
    }

    function hide() {
        var el = document.getElementById(TOOLTIP_ID);
        if (el) {
            el.classList.add("opacity-0");
            el.setAttribute("aria-hidden", "true");
            // Fully hide so no black strip remains after leave (opacity-0 alone can still paint)
            el.style.visibility = "hidden";
            el.textContent = "";
            el.style.left = "-9999px";
            el.style.top = "-9999px";
        }
        if (titleBackupEl) {
            // Prefer the live aria-label over the stale backup string: app
            // code may have updated the label while the tooltip pill was
            // showing (e.g. a toggle button's label changing on click), and
            // restoring the pre-hover backup would stomp that update. Fall
            // back to the original backup for elements with no aria-label.
            var restoreText = (titleBackupEl.getAttribute("aria-label") || "").trim() || titleBackup;
            if (restoreText) {
                titleBackupEl.setAttribute("title", restoreText);
            }
            titleBackupEl = null;
            titleBackup = null;
        }
        currentTrigger = null;
    }

    function onPointerOver(e) {
        var t = findTrigger(e.target);
        if (!t) {
            if (currentTrigger && (!e.relatedTarget || !currentTrigger.contains(e.relatedTarget)))
                hide();
            return;
        }
        if (t === currentTrigger) return;
        hide();
        show(t);
    }

    function onPointerOut(e) {
        if (!currentTrigger) return;
        var to = e.relatedTarget;
        if (!to || !currentTrigger.contains(to)) hide();
    }

    document.addEventListener("mouseover", onPointerOver, true);
    document.addEventListener("mouseout", onPointerOut, true);

    document.addEventListener("focusin", function (e) {
        var t = findTrigger(e.target);
        if (t) {
            hide();
            show(t);
        }
    }, true);

    document.addEventListener("focusout", function () {
        hide();
    }, true);
})();
