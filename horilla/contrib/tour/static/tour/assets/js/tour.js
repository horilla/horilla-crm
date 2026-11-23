(function () {
    "use strict";

    if (window.__horillaTour) { return; }
    window.__horillaTour = true;

    var script = document.currentScript;
    var ASSET_BASE = script && script.src
        ? script.src.replace(/js\/tour\.js(\?.*)?$/, "")
        : "/static/tour/assets/";
    var API = "/tour/";
    var PENDING_KEY = "horilla_tour_pending";   // "start this tour once you get there"
    var PENDING_TTL = 10 * 60 * 1000;
    var STEP_TIMEOUT = 4000;
    var EXPECTED_TIMEOUT = 10000; // a step with `only_if`: its element is known to come, a slow pop-up is not a missing one
    var READY_TIMEOUT = 8000;
    var OPEN_TIMEOUT = 20000;     // lists can be slow, and the user asked for this tour
    var STABLE_QUIET = 350;       // a step that loads content is lit once still this long
    var STABLE_MAX = 2000;
    var AUTO_START_DELAY = 800;
    var AUTO_NEXT_DELAY = 500;
    var POLL_MS = 100;
    var MIN_TARGET_SIZE = 4;      // anything smaller would be lit as a dot

    var state = {
        labels: {},
        running: false,
        finishing: false,
        busy: false,
        def: null,
        steps: [],
        index: 0,
        currentEl: null,
        startPath: null,
        autoKey: null,
        endResolve: null,
        driver: null,
        proxy: null,
        pausing: false,
        assets: null,
        token: 0,
        checking: false,
        checkedPath: null,
        card: null,
        cardTimer: null,
        pageTimer: null,
        anchorTimer: null,
        definitions: {}
    };

    /* ------------------------------------------------------------------ utils */

    function sleep(ms) {
        return new Promise(function (resolve) { setTimeout(resolve, ms); });
    }

    function api(url, body) {
        var options = { credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" } };
        if (body) {
            var csrf = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
            options.method = "POST";
            options.headers["X-CSRFToken"] = csrf ? decodeURIComponent(csrf[1]) : "";
            options.headers["Content-Type"] = "application/json";
            options.body = JSON.stringify(body);
        }
        return fetch(url, options).then(function (response) {
            if (!response.ok) { throw new Error("tour request failed: " + response.status); }
            return response.json();
        });
    }

    function format(template, values) {
        return String(template).replace(/\{(\w+)\}/g, function (all, key) {
            return values[key] !== undefined ? values[key] : all;
        });
    }

    /* The hand-off between pages. Dropped as soon as the tour starts. */
    function readPending() {
        try {
            var data = JSON.parse(sessionStorage.getItem(PENDING_KEY));
            if (data && data.key && Date.now() - data.created <= PENDING_TTL) { return data; }
            sessionStorage.removeItem(PENDING_KEY);
        } catch (e) { /* storage unavailable or unreadable */ }
        return null;
    }

    function writePending(key, clicked) {
        var data = { key: key, clicked: !!clicked, created: Date.now() };
        try { sessionStorage.setItem(PENDING_KEY, JSON.stringify(data)); } catch (e) { /* ignore */ }
        return data;
    }

    function clearPending() {
        try { sessionStorage.removeItem(PENDING_KEY); } catch (e) { /* ignore */ }
    }

    /* ----------------------------------------------------------- finding things */

    function isVisible(el) {
        var rect = el.getBoundingClientRect();
        if (rect.width < MIN_TARGET_SIZE || rect.height < MIN_TARGET_SIZE) { return false; }
        var style = window.getComputedStyle(el);
        return style.visibility !== "hidden" && style.display !== "none";
    }

    /** First *visible* element matching a (comma separated) selector, or null. */
    function findVisible(selector) {
        var list;
        try { list = document.querySelectorAll(selector); } catch (e) { return null; }
        for (var i = 0; i < list.length; i++) {
            if (isVisible(list[i])) { return list[i]; }
        }
        return null;
    }

    /** Resolve with the first truthy `test()`, or null after `timeout` ms. */
    function until(test, timeout, token) {
        return new Promise(function (resolve) {
            var started = Date.now();
            (function poll() {
                if (token !== undefined && token !== state.token) { resolve(null); return; }
                var value = null;
                try { value = test(); } catch (e) { /* not ready yet */ }
                if (value) { resolve(value); return; }
                if (Date.now() - started >= timeout) { resolve(null); return; }
                setTimeout(poll, POLL_MS);
            })();
        });
    }

    function waitFor(selector, timeout, token) {
        return until(function () { return findVisible(selector); }, timeout, token);
    }

    /**
     * Resolve once `el` stops changing (no DOM mutation or resize for `quiet` ms, or
     * after `max`). A lazily loaded tab grows and shrinks while it fills in; lighting
     * it in that state moves the spotlight and popover around, which looks like a blink.
     */
    function waitStable(el, quiet, max) {
        return new Promise(function (resolve) {
            var timer;
            var watchers = [];
            var cap = setTimeout(finish, max);
            function finish() {
                clearTimeout(timer);
                clearTimeout(cap);
                watchers.forEach(function (watcher) { watcher.disconnect(); });
                resolve();
            }
            function bump() {
                clearTimeout(timer);
                timer = setTimeout(finish, quiet);
            }
            var mutations = new MutationObserver(bump);
            mutations.observe(el, { childList: true, subtree: true, attributes: true });
            watchers.push(mutations);
            if (window.ResizeObserver) {
                var resizes = new ResizeObserver(bump);
                resizes.observe(el);
                watchers.push(resizes);
            }
            bump();
        });
    }

    /** Load driver.js (stylesheet and script) the first time a tour needs it. */
    function loadDriver() {
        if (window.driver && window.driver.js) { return Promise.resolve(); }
        if (!state.assets) {
            var link = document.createElement("link");
            link.rel = "stylesheet";
            link.href = ASSET_BASE + "vendor/driver/driver.css";
            document.head.appendChild(link);
            state.assets = new Promise(function (resolve, reject) {
                var tag = document.createElement("script");
                tag.src = ASSET_BASE + "vendor/driver/driver.js.iife.js";
                tag.onload = resolve;
                tag.onerror = function () { state.assets = null; reject(new Error("driver.js")); };
                document.head.appendChild(tag);
            });
        }
        return state.assets;
    }

    /* --------------------------------------------------------- message card */

    function removeCard() {
        clearTimeout(state.cardTimer);
        if (state.card) { state.card.remove(); }
        state.card = null;
    }

    /** Small non-blocking message ("nothing to open", "page not ready"). */
    function showCard(title, body) {
        removeCard();
        var template = document.getElementById("horilla-tour-card");
        if (!template) { return; }
        var card = template.content.firstElementChild.cloneNode(true);
        card.querySelector("[data-tour-card-title]").textContent = title;
        card.querySelector("[data-tour-card-body]").textContent = body;
        card.querySelector("button").addEventListener("click", removeCard);
        document.body.appendChild(card);
        state.card = card;
        state.cardTimer = setTimeout(removeCard, 8000);
    }

    /* ------------------------------------------------------------------ panel */

    function panelEl() { return document.getElementById("horilla-tour-panel"); }

    function isPanelOpen() {
        var panel = panelEl();
        return !!(panel && !panel.hidden);
    }

    function setPanelOpen(open) {
        var panel = panelEl();
        var button = document.getElementById("horilla-tour-launcher");
        if (panel) { panel.hidden = !open; }
        if (button) { button.setAttribute("aria-expanded", open ? "true" : "false"); }
    }

    /* ------------------------------------------------------------------ server */

    function markSeen(key) {
        api(API + "seen/", { key: key }).catch(function () { /* never interrupt the user over it */ });
    }

    function getDefinition(key) {
        if (state.definitions[key]) { return Promise.resolve(state.definitions[key]); }
        return api(API + "definition/" + encodeURIComponent(key) + "/").then(function (def) {
            state.labels = def.labels || state.labels;
            state.definitions[key] = def;
            return def;
        }).catch(function () { return null; });
    }

    function currentInfo() {
        return api(API + "current/?path=" + encodeURIComponent(window.location.pathname)).then(function (info) {
            state.labels = info.labels || state.labels;
            return info;
        });
    }

    /* ---------------------------------------------------------------- actions */

    /**
     * Press an element the way a mouse does: press, move a pixel, release, click, all at
     * the middle of the element. A calendar finds the day that was clicked from the mouse
     * position, and ignores a press and release that never moved.
     */
    function tapAt(target) {
        var box = target.getBoundingClientRect();
        var x = box.left + box.width / 2;
        var y = box.top + box.height / 2;
        [["mousedown", 0], ["mousemove", 1], ["mouseup", 1], ["click", 1]].forEach(function (step) {
            target.dispatchEvent(new MouseEvent(step[0], {
                bubbles: true, cancelable: true, button: 0, view: window,
                clientX: x + step[1], clientY: y + step[1]
            }));
        });
    }

    /**
     * Run the `before` / `after` actions of a step. An action is `{<kind>: selector}`, with
     * an optional `if_hidden` / `if_visible` selector that says when it applies. The kinds:
     *   click      a plain click
     *   mousedown  a press only: a select2 box opens on mousedown and ignores a click
     *   tap        a full mouse press at the middle of the element (a calendar day)
     */
    async function runActions(actions) {
        var list = actions || [];
        if (!list.length) { return; }
        // Let the click that got us here (Next, Back) finish first: a dropdown opened
        // while it is still being delivered would see it as a click outside and close.
        await sleep(0);
        if (list.some(function (action) { return action.tap; })) { suspendDriver(); }
        for (var i = 0; i < list.length; i++) {
            var action = list[i];
            var kind = action.tap ? "tap" : (action.click ? "click" : "mousedown");
            var target = findVisible(action[kind]);
            if (!target) { continue; }
            if (action.if_hidden && findVisible(action.if_hidden)) { continue; }
            if (action.if_visible && !findVisible(action.if_visible)) { continue; }
            if (kind === "tap") {
                tapAt(target);
            } else if (kind === "mousedown") {
                target.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, button: 0 }));
            } else {
                target.click();
            }
            await sleep(250);
        }
    }

    /* ----------------------------------------------------------------- driver */

    /**
     * Take the dark overlay and the popover off the page, without ending the tour. While
     * they are up the page ignores the pointer and an overlay covers it, so a calendar
     * cannot tell which day a scripted tap hit. The next step brings them back.
     */
    function suspendDriver() {
        if (!state.driver) { return; }
        state.pausing = true;   // cleared when the next driver is made
        try { state.driver.destroy(); } catch (e) { /* already gone */ }
        state.driver = null;
        state.currentEl = null;
        removeProxy();
    }

    function getDriver() {
        if (!state.driver) {
            state.pausing = false;
            state.driver = window.driver.js.driver({
                // A tour only explains what it points at: a click on the highlighted
                // button must not run it. The tour's own scripted clicks still work.
                disableActiveInteraction: true,
                overlayOpacity: 0.65,
                stagePadding: 6,
                stageRadius: 6,
                popoverOffset: 12,
                // A click on the dark overlay destroys the driver: treat it as "close".
                onDestroyed: function () {
                    if (state.running && !state.finishing && !state.pausing) { endTour(); }
                }
            });
        }
        return state.driver;
    }

    /**
     * The element a step needs on the page, or null when it cannot be known up front:
     * `only_if` when set, otherwise the target itself. A step that clicks something first
     * (`before`) is not checked, because its target only appears after the click.
     */
    function requiredSelector(step) {
        if (step.only_if) { return step.only_if; }
        return step.target && !(step.before && step.before.length) ? step.target : null;
    }

    /** The popover is the template in the launcher slot: driver.js only positions it. */
    function popoverFor(index, step) {
        var template = document.getElementById("horilla-tour-popover");
        // Last when no later step can appear: steps whose element is not on the page are skipped.
        var isLast = !state.steps.slice(index + 1).some(function (later) {
            var required = requiredSelector(later);
            return !required || findVisible(required);
        });
        var side = ["top", "bottom", "left", "right", "over"].indexOf(step.side) !== -1 ? step.side : "bottom";
        // A step with nothing to point at is a card in the middle of the screen. Placed
        // beside the invisible dot driver.js uses, it ends up in a corner in a short window.
        if (!step.target) { side = "over"; }
        var align = ["start", "center", "end"].indexOf(step.align) !== -1
            ? step.align
            : (side === "over" ? "center" : "start");
        return {
            side: side,
            align: align,
            popoverClass: template ? template.dataset.popoverClass : "",
            onPopoverRender: function (popover) {
                if (!template) { return; }
                var box = template.content.firstElementChild.cloneNode(true);
                box.querySelector("[data-tour-title]").textContent = step.title;
                box.querySelector("[data-tour-body]").textContent = step.body;
                box.querySelector("[data-tour-progress]").textContent =
                    format(state.labels.step_of, { current: index + 1, total: state.steps.length });
                var prev = box.querySelector("[data-tour-prev]");
                var skip = box.querySelector("[data-tour-skip]");
                var next = box.querySelector("[data-tour-next]");
                // Step 1 has nothing to go back to: it offers Skip instead.
                (index === 0 ? prev : skip).remove();
                prev.addEventListener("click", onPrev);
                skip.addEventListener("click", function () { endTour(); });
                next.addEventListener("click", onNext);
                if (isLast) { next.textContent = state.labels.finish; }
                box.querySelector("[data-tour-close]").addEventListener("click", function () { endTour(); });
                popover.wrapper.replaceChildren(popover.arrow, box);
            }
        };
    }

    /** Remove the invisible box that lights two elements as one area. */
    function removeProxy() {
        if (state.proxy && state.proxy.parentNode) { state.proxy.parentNode.removeChild(state.proxy); }
        state.proxy = null;
    }

    /**
     * What to light for a step. Usually `el`. With `also` (a button and the pop-up it
     * opens, say) it is an invisible box over both, so they are lit together: a step
     * can only light one element, and the pop-up often sits outside the button.
     */
    function litElement(el, also) {
        removeProxy();
        var extra = also ? findVisible(also) : null;
        if (!el || !extra) { return el; }
        var a = el.getBoundingClientRect();
        var b = extra.getBoundingClientRect();
        var left = Math.min(a.left, b.left);
        var top = Math.min(a.top, b.top);
        var box = document.createElement("div");
        box.setAttribute("data-tour-proxy", "");
        box.style.cssText = "position:fixed;pointer-events:none;visibility:hidden;left:" + left +
            "px;top:" + top + "px;width:" + (Math.max(a.right, b.right) - left) +
            "px;height:" + (Math.max(a.bottom, b.bottom) - top) + "px";
        document.body.appendChild(box);
        state.proxy = box;
        return box;
    }

    function highlight(index, step, el) {
        var spec = { popover: popoverFor(index, step) };
        var lit = litElement(el, step.also);
        if (lit) { spec.element = lit; }
        state.currentEl = el || null;
        getDriver().highlight(spec);
    }

    /* ------------------------------------------------------------------ steps */

    /** Show step `index`, skipping steps whose element is not there. */
    /**
     * While the next step loads, fade the Back / Next buttons and show a busy cursor, so a
     * click does not look ignored. The popover itself stays solid and readable.
     */
    function setLoading(on) {
        var popover = document.querySelector(".driver-popover");
        if (!popover) { return; }
        popover.style.cursor = on ? "progress" : "";
        popover.querySelectorAll("[data-tour-prev], [data-tour-next], [data-tour-skip]").forEach(function (button) {
            button.style.opacity = on ? "0.5" : "";
        });
    }

    async function goto(index, dir) {
        var token = state.token;
        state.busy = true;
        setLoading(true);
        try {
            for (var guard = 0; guard < 100; guard++) {
                if (token !== state.token) { return; }
                if (index >= state.steps.length) { state.busy = false; endTour("finished"); return; }
                if (index < 0) { index = 0; dir = 1; }

                var step = state.steps[index];
                var required = requiredSelector(step);
                if (required && !findVisible(required)) { index += dir; continue; }

                await runActions(step.before);
                if (token !== state.token) { return; }

                var el = null;
                if (step.target) {
                    el = await waitFor(step.target, step.only_if ? EXPECTED_TIMEOUT : STEP_TIMEOUT, token);
                    if (token !== state.token) { return; }
                    if (!el) {
                        await runActions(step.after);   // undo what the step opened, then move on
                        index += dir;
                        continue;
                    }
                    if (step.before && step.before.length) {
                        await waitStable(el, STABLE_QUIET, STABLE_MAX);
                        if (token !== state.token) { return; }
                        el = findVisible(step.target) || el;
                    }
                }

                state.index = index;
                highlight(index, step, el);
                if (state.autoKey) {
                    markSeen(state.autoKey);   // only once the user has actually seen it start
                    state.autoKey = null;
                }
                return;
            }
        } finally {
            state.busy = false;
            setLoading(false);
        }
    }

    async function leaveStep() {
        var step = state.steps[state.index];
        if (step) { await runActions(step.after); }
    }

    async function move(dir) {
        if (state.busy || !state.running) { return; }
        await leaveStep();
        goto(state.index + dir, dir);
    }

    function onNext() { return move(1); }
    function onPrev() { return move(-1); }

    /* ------------------------------------------------------------ tour lifecycle */

    /** End the tour: `reason` is "finished" after the last step, otherwise it is a close. */
    async function endTour(reason) {
        if (!state.running || state.finishing) { return; }
        state.finishing = true;
        state.token++;
        state.running = false;

        try { await leaveStep(); } catch (e) { /* best effort */ }
        try { if (state.driver) { state.driver.destroy(); } } catch (e) { /* already gone */ }
        state.driver = null;
        state.currentEl = null;
        removeProxy();
        state.autoKey = null;
        clearPending();
        state.finishing = false;

        var resolve = state.endResolve;
        state.endResolve = null;
        if (resolve) { resolve(reason === "finished" ? "finished" : "closed"); }
    }

    /** options.auto: the tour started by itself, so remember that it was shown. */
    async function startTour(def, options) {
        if (state.running) { return; }
        var auto = !!(options && options.auto);
        removeCard();
        setPanelOpen(false);
        state.token++;
        state.running = true;
        state.finishing = false;
        state.def = def;
        state.autoKey = auto ? def.key : null;
        state.steps = def.steps || [];
        state.index = 0;
        state.startPath = window.location.pathname;
        clearPending();   // a reload in the middle of a tour must not restart it

        try {
            await loadDriver();
        } catch (e) {
            state.running = false;
            return;
        }

        var token = state.token;
        if (def.ready) {
            var ready = await waitFor(def.ready, READY_TIMEOUT, token);
            if (token !== state.token) { return; }
            if (!ready) {
                state.running = false;
                state.autoKey = null;
                if (!auto) { showCard(def.title, state.labels.not_ready); }
                return;
            }
        }
        goto(0, 1);
    }

    /** Run one automatic tour and resolve with "finished", "closed" or "failed". */
    async function runAutoTour(def) {
        if (state.running) { return "failed"; }
        var ended = new Promise(function (resolve) { state.endResolve = resolve; });
        await startTour(def, { auto: true });
        if (!state.running) {   // it never got going: the page it needs is not there
            state.endResolve = null;
            return "failed";
        }
        return ended;
    }

    /**
     * Run the page's automatic tours one after another. Closing one (x, Esc, leaving
     * the page) means "not now": the rest are marked as shown too and stay in the panel.
     */
    async function runAutoTours(keys, path) {
        for (var i = 0; i < keys.length; i++) {
            var def = await getDefinition(keys[i]);
            if (!def) { continue; }
            await sleep(i === 0 ? AUTO_START_DELAY : AUTO_NEXT_DELAY);
            if (state.running || window.location.pathname !== path) { return; }
            if (await runAutoTour(def) === "closed") {
                keys.slice(i + 1).forEach(markSeen);
                return;
            }
        }
    }

    /* ----------------------------------------- start / hand-off across pages */

    /**
     * Start a tour from anywhere. On (or one click away from) the tour's screen it
     * starts in place, otherwise the browser goes to its start URL (`?tour=<key>`).
     */
    async function launch(key) {
        var def = await getDefinition(key);
        if (!def) { return; }
        var info;
        try { info = await currentInfo(); } catch (e) { info = {}; }
        var here = def.match.indexOf(info.view_name) !== -1 ||
            !!(def.open_with && info.view_name === def.open_with.from);
        if (here) {
            writePending(key);
            state.checkedPath = null;
            pageCheck();
        } else if (def.start_url) {
            window.location.href = def.start_url;
        }
    }

    /**
     * Click `selector` for the user and check it took effect (`done()`), clicking again
     * if not: a click can land before htmx has bound the row, and nothing says so.
     * Resolves false if there is nothing to click or it never took effect.
     */
    async function clickUntil(selector, done, attempts, settleMs) {
        for (var i = 0; i < attempts; i++) {
            var el = await waitFor(selector, OPEN_TIMEOUT);
            if (!el) { return false; }
            el.click();
            if (await until(done, settleMs)) { return true; }
        }
        return false;
    }

    /** Decide what to do with the page that just settled. */
    async function pageCheck() {
        if (state.running || state.checking) { return; }
        var path = window.location.pathname;
        if (path.indexOf(API) === 0) { clearPending(); return; }

        var params = new URLSearchParams(window.location.search);
        var requested = params.get("tour");
        var pending = readPending();

        if (requested) {
            pending = writePending(requested);
            params.delete("tour");
            var query = params.toString();
            try {
                window.history.replaceState(window.history.state, "",
                    path + (query ? "?" + query : "") + window.location.hash);
            } catch (e) { /* ignore */ }
        }

        if (!pending && state.checkedPath === path) { return; }

        var autoKeys = null;
        state.checking = true;
        try {
            var info = await currentInfo();
            state.checkedPath = path;

            if (!pending) {
                // First visit to a page that has automatic tours.
                if (info.auto && info.auto.length) { autoKeys = info.auto; }
                return;
            }

            var def = await getDefinition(pending.key);
            if (!def) { clearPending(); return; }

            var open = def.open_with;
            if (def.match.indexOf(info.view_name) !== -1) {
                if (open && def.ready && !findVisible(def.ready) && !pending.clicked) {
                    writePending(pending.key, true);
                    var opened = await clickUntil(open.click, function () { return findVisible(def.ready); }, 3, 4000);
                    if (!opened) {
                        clearPending();
                        showCard(def.title, state.labels.cannot_open);
                        return;
                    }
                }
                await startTour(def);
            } else if (open && info.view_name === open.from) {
                if (pending.clicked) { return; }
                writePending(pending.key, true);
                var moved = await clickUntil(open.click, function () { return window.location.pathname !== path; }, 3, 4000);
                if (!moved) {
                    clearPending();
                    showCard(def.title, state.labels.cannot_open);
                    return;
                }
                schedulePageCheck();   // the navigation settles on the tour's page: check that page
            } else {
                clearPending();
            }
        } catch (e) {
            /* offline, logged out, or an unexpected payload: stay silent */
        } finally {
            state.checking = false;
            // Not awaited (it lasts as long as the tours), and started after the lock is released.
            if (autoKeys) { runAutoTours(autoKeys, path); }
        }
    }

    function schedulePageCheck() {
        clearTimeout(state.pageTimer);
        state.pageTimer = setTimeout(pageCheck, 400);
    }

    /* ----------------------------------------- stay anchored while running */

    /** After an htmx swap, re-resolve the highlighted element or leave the tour. */
    async function reanchor() {
        if (!state.running || state.busy || state.finishing) { return; }

        if (window.location.pathname !== state.startPath) {
            var info;
            try { info = await currentInfo(); } catch (e) { info = null; }
            if (info && state.def.match.indexOf(info.view_name) === -1) {
                endTour();
                return;
            }
            state.startPath = window.location.pathname;
        }

        var step = state.steps[state.index];
        if (!step || !step.target) { return; }
        var el = findVisible(step.target);
        if (el && el === state.currentEl && !step.also) {
            if (state.driver) { state.driver.refresh(); }
        } else if (el) {
            highlight(state.index, step, el);
        } else {
            goto(state.index, 1);
        }
    }

    /* ------------------------------------------------------------------- boot */

    document.addEventListener("htmx:afterSettle", function () {
        if (state.running) {
            clearTimeout(state.anchorTimer);
            state.anchorTimer = setTimeout(reanchor, 300);
        } else {
            schedulePageCheck();
        }
    });

    // The Product Tours button loads the panel with htmx (see header.html): open it with
    // the request, close it again and say so if the list cannot be loaded.
    function fromLauncher(event) { return event.detail.elt.id === "horilla-tour-launcher"; }

    document.addEventListener("htmx:beforeRequest", function (event) {
        if (fromLauncher(event)) { removeCard(); setPanelOpen(true); }
    });

    ["htmx:responseError", "htmx:sendError"].forEach(function (name) {
        document.addEventListener(name, function (event) {
            if (!fromLauncher(event)) { return; }
            setPanelOpen(false);
            showCard(document.getElementById("tour-panel-title").textContent, state.labels.panel_error || "");
        });
    });

    // Delegated: the launcher and panel are rendered after this script runs, and the
    // panel's content is replaced as it is used.
    document.addEventListener("click", function (event) {
        var target = event.target;
        // A handler that ran first may have removed the clicked element: not "outside".
        if (!target || !target.closest || !target.isConnected) { return; }

        if (target.closest("#horilla-tour-launcher")) {
            // The item sits in the profile dropdown: close the dropdown behind the panel.
            target.closest(".dropdown-wrapper").classList.remove("active");
            return;
        }

        var start = target.closest("[data-tour-start]");
        if (start) {
            event.preventDefault();
            setPanelOpen(false);
            launch(start.getAttribute("data-tour-start"));
            return;
        }

        if (target.closest("[data-tour-panel-close]")) { setPanelOpen(false); return; }
        if (isPanelOpen() && !target.closest("#horilla-tour-panel, #horilla-tour-card")) {
            setPanelOpen(false);
        }
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
            if (state.running && !state.finishing) {
                endTour();   // as well as driver.js, so Esc always closes the tour
            } else if (isPanelOpen()) {
                setPanelOpen(false);
            }
            return;
        }
        // Arrow keys move through a running tour (driver.js does not, as we drive it one step at a time).
        var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName) || event.target.isContentEditable;
        if (!state.running || typing) { return; }
        if (event.key === "ArrowRight") { onNext(); }
        if (event.key === "ArrowLeft" && state.index > 0) { onPrev(); }
    });

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", schedulePageCheck);
    } else {
        schedulePageCheck();
    }
})();
