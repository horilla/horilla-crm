const _cfg = document.getElementById("booking-form-config").dataset;
const _12hr = _cfg.label12hr;
const _24hr = _cfg.label24hr;
const _noSlotsAvailableDay = _cfg.noSlotsAvailableDay;
const _dayBlockedReasons = {
    unavailable: _cfg.dayUnavailable,
    booked: _cfg.dayBooked,
};
const _hostUnavailableSlot = _cfg.hostUnavailableSlot;
const _slotBooked = _cfg.slotBooked;
const _failedToLoadSlots = _cfg.failedToLoadSlots;
const _noAvailableSlots = _cfg.noAvailableSlots;
const SLOTS_URL          = _cfg.slotsUrl;
const DURATION_MIN       = Number(_cfg.duration);
const BOOKING_WIN        = Number(_cfg.bookingWindow);
const ADVANCE_MIN        = Number(_cfg.advanceNotice);
const AVAIL_DAYS         = JSON.parse(_cfg.availDays);
const BLOCKED_DATES = JSON.parse(_cfg.blockedDates);
const FULLY_BOOKED_DATES = new Set(Object.keys(BLOCKED_DATES));

let currentYear, currentMonth;
let selectedDate = null;
let selectedTime = null;
let allSlots     = [];
let bookedSlots  = [];
let unavailableSlots = [];
let timeFmt      = '12';   // '12' or '24'

// ── Timezone ─────────────────────────────────────────────────────
const TZ_LIST = Intl.supportedValuesOf
    ? Intl.supportedValuesOf("timeZone")
    : ["UTC","America/New_York","Europe/London","Asia/Kolkata","Asia/Tokyo","Australia/Sydney"];

function buildTimezoneSelect() {
    const userTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const $sel   = $("#timezone-select");
    TZ_LIST.forEach(tz => {
        const opt = new Option(tz.replace(/_/g, " "), tz, tz === userTz, tz === userTz);
        $sel.append(opt);
    });
    $sel.select2({
        placeholder: "Select Timezone",
        allowClear: false,
        width: "resolve",
        dropdownParent: $sel.parent(),
    });
    $sel.on("change", () => {
        updateHeaderTzLabel();
        if (selectedDate) {
            selectedTime = null;
            loadSlots(selectedDate);
        }
    });
    updateHeaderTzLabel();
}
function getSelectedTz() {
    return $("#timezone-select").val()
        || Intl.DateTimeFormat().resolvedOptions().timeZone;
}
function updateHeaderTzLabel() {
    const el = document.getElementById("header-tz-label");
    if (el) {
        el.textContent = getSelectedTz().replace(/_/g, " ");
    }
}

// ── Date helpers ─────────────────────────────────────────────────
const MONTH_NAMES   = ["January","February","March","April","May","June",
                       "July","August","September","October","November","December"];
const WEEKDAY_SHORT = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
const WEEKDAY_LONG  = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
const DAY_KEYS      = ["sun","mon","tue","wed","thu","fri","sat"];

function toIso(d) {
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
}

function isDateAvailable(iso) {
    const d = new Date(iso + "T00:00:00");
    const today = new Date(); today.setHours(0,0,0,0);
    const maxD  = new Date(today); maxD.setDate(today.getDate() + BOOKING_WIN);
    if (d < today || d > maxD) return false;
    if (d.toDateString() === today.toDateString()) {
        // If whole day falls within advance notice window, mark unavailable
        const midnight = new Date(iso + "T23:59:00");
        if (midnight.getTime() - Date.now() < ADVANCE_MIN * 60000) return false;
    }
    return AVAIL_DAYS.includes(DAY_KEYS[d.getDay()]);
}

const VISIBLE    = 14;  // cards shown at once (7 per row × 2 rows)
let   dateOffset = 0;   // 0-based index of first visible day in month

// ── Date strip ───────────────────────────────────────────────────
function renderDateStrip() {
    const strip = document.getElementById("date-strip");
    strip.innerHTML = "";

    for (let i = 0; i < VISIBLE; i++) {
        // Use Date arithmetic so days beyond month-end overflow into next month
        const d   = new Date(currentYear, currentMonth, dateOffset + 1 + i);
        const iso = toIso(d);
        const ok  = isDateAvailable(iso);
        const full = ok && FULLY_BOOKED_DATES.has(iso);
        const card = document.createElement("div");
        if (full) {
            card.className = "date-card full";
        } else {
            card.className = "date-card" + (ok ? "" : " disabled");
        }
        if (iso === selectedDate) card.classList.add("active");
        card.innerHTML =
            `<div class="dc-day">${WEEKDAY_SHORT[d.getDay()]}</div>` +
            `<div class="dc-num">${d.getDate()}</div>` +
            `<div class="dc-mon">${MONTH_NAMES[d.getMonth()].slice(0,3)}</div>`;
        if (ok && !full) {
            card.onclick = () => onDateClick(iso, d);
        } else if (full) {
            card.title = _dayBlockedReasons[BLOCKED_DATES[iso]] || _noSlotsAvailableDay;
        }
        strip.appendChild(card);
    }

    // Update month label — show a range when the visible window spans two months
    const firstVisible = new Date(currentYear, currentMonth, dateOffset + 1);
    const lastVisible  = new Date(currentYear, currentMonth, dateOffset + VISIBLE);
    const monthLabelEl = document.getElementById("month-label");
    if (firstVisible.getMonth() === lastVisible.getMonth()
        && firstVisible.getFullYear() === lastVisible.getFullYear()) {
        monthLabelEl.textContent =
            `${MONTH_NAMES[firstVisible.getMonth()]} ${firstVisible.getFullYear()}`;
    } else if (firstVisible.getFullYear() === lastVisible.getFullYear()) {
        monthLabelEl.textContent =
            `${MONTH_NAMES[firstVisible.getMonth()]} – ${MONTH_NAMES[lastVisible.getMonth()]} ${lastVisible.getFullYear()}`;
    } else {
        monthLabelEl.textContent =
            `${MONTH_NAMES[firstVisible.getMonth()]} ${firstVisible.getFullYear()} – `
            + `${MONTH_NAMES[lastVisible.getMonth()]} ${lastVisible.getFullYear()}`;
    }

    const now = new Date();
    const atFirstMonth = currentYear === now.getFullYear() && currentMonth <= now.getMonth();
    document.getElementById("prev-month-btn").disabled = atFirstMonth && dateOffset <= 0;
    document.getElementById("prev-date-btn").disabled  = atFirstMonth && dateOffset <= 0;

    // Disable "next" once the whole visible window is past the booking window —
    // there is nothing bookable left to scroll to.
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const maxBookable = new Date(today); maxBookable.setDate(today.getDate() + BOOKING_WIN);
    const pastWindow = firstVisible > maxBookable;
    document.getElementById("next-date-btn").disabled = pastWindow;
    document.getElementById("next-month-btn").disabled = pastWindow;
}

function shiftDates(delta) {
    // Plain week-at-a-time step. Past/disabled days within a month
    // are already greyed out by isDateAvailable(), so there is no
    // need to skip ahead to today — just don't go negative.
    dateOffset = Math.max(0, dateOffset + delta);
    renderDateStrip();
}

function changeMonth(delta) {
    currentMonth += delta;
    if (currentMonth > 11) { currentMonth = 0; currentYear++; }
    if (currentMonth < 0)  { currentMonth = 11; currentYear--; }
    // Always land on day 1 of the target month — today's date is only
    // the starting point on initial page load, not on every navigation.
    dateOffset = 0;
    renderDateStrip();
}

function onDateClick(iso, dateObj) {
    selectedDate = iso;
    selectedTime = null;
    renderDateStrip();
    document.getElementById("step2-date-label").textContent =
        `${WEEKDAY_LONG[dateObj.getDay()]}, ${MONTH_NAMES[dateObj.getMonth()]} ${dateObj.getDate()}`;
    loadSlots(iso);
    goStep(2);
}

// ── Slot loading ─────────────────────────────────────────────────
function loadSlots(iso) {
    const c = document.getElementById("slots-container");
    c.innerHTML = `<div class="flex justify-center py-8"><div class="w-6 h-6 rounded-full border-2 border-gray-200 animate-spin" style="border-top-color:var(--brand);"></div></div>`;
    fetch(`${SLOTS_URL}?date=${iso}&timezone=${encodeURIComponent(getSelectedTz())}`)
        .then(r => r.json())
        .then(data => { allSlots = data.slots || []; bookedSlots = data.booked_slots || []; unavailableSlots = data.unavailable_slots || []; renderSlots(); })
        .catch(() => {
            c.innerHTML = `<p class="text-center text-sm text-red-400 py-6">${_failedToLoadSlots}</p>`;
        });
}

// ── Time format toggle ───────────────────────────────────────────
function setFmt(fmt) {
    timeFmt = fmt;
    document.getElementById("fmt12").className = fmt === '12' ? 'on' : '';
    document.getElementById("fmt24").className = fmt === '24' ? 'on' : '';
    renderSlots();
    // If a slot is already selected, refresh summary too
    if (selectedTime) updateSummary();
}

function fmtTime(hhmm) {
    const [h, m] = hhmm.split(":").map(Number);
    if (timeFmt === '24') return `${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}`;
    const ap  = h >= 12 ? "PM" : "AM";
    const h12 = h % 12 || 12;
    return `${h12}:${String(m).padStart(2,"0")} ${ap}`;
}

function renderSlots() {
    const c = document.getElementById("slots-container");
    if (!allSlots.length && !bookedSlots.length && !unavailableSlots.length) {
        c.innerHTML = `<p class="text-center text-sm text-gray-400 py-8">${_noAvailableSlots}</p>`;
        return;
    }
    const grid = document.createElement("div");
    grid.className = "grid grid-cols-4 gap-2";

    const bookedSet = new Set(bookedSlots);
    const unavailableSet = new Set(unavailableSlots);
    const allMerged = [...allSlots, ...bookedSlots, ...unavailableSlots].sort();

    allMerged.forEach(slot => {
        const isBooked = bookedSet.has(slot);
        const btn = document.createElement("div");
        if (isBooked) {
            btn.className = "slot-btn booked";
            btn.title = _slotBooked;
        } else if (unavailableSet.has(slot)) {
            btn.className = "slot-btn booked";
            btn.title = _hostUnavailableSlot;
        } else {
            btn.className = "slot-btn" + (slot === selectedTime ? " active" : "");
            btn.onclick = () => onSlotClick(slot);
        }
        btn.textContent = fmtTime(slot);
        grid.appendChild(btn);
    });

    c.innerHTML = "";
    c.appendChild(grid);
}

function onSlotClick(slot) {
    selectedTime = slot;
    renderSlots();
    updateSummary();
    goStep(3);
}

function updateSummary() {
    const [h, mn]  = selectedTime.split(":").map(Number);
    const endMin   = h * 60 + mn + DURATION_MIN;
    const endH     = Math.floor(endMin / 60), endM = endMin % 60;
    const endSlot  = `${String(endH).padStart(2,"0")}:${String(endM).padStart(2,"0")}`;
    const dateObj  = new Date(selectedDate + "T00:00:00");
    document.getElementById("summary-date").textContent =
        `${WEEKDAY_LONG[dateObj.getDay()]}, ${MONTH_NAMES[dateObj.getMonth()]} ${dateObj.getDate()}, ${dateObj.getFullYear()}`;
    document.getElementById("summary-time").textContent =
        `${fmtTime(selectedTime)} – ${fmtTime(endSlot)}  (${DURATION_MIN} min)`;
    document.getElementById("summary-tz").textContent = getSelectedTz();
    document.getElementById("form-date").value = selectedDate;
    document.getElementById("form-time").value = selectedTime;
    document.getElementById("form-tz").value   = getSelectedTz();
}

// ── Step navigation ──────────────────────────────────────────────
function goStep(n) {
    document.querySelectorAll(".step-panel").forEach((el, i) => {
        el.classList.toggle("visible", i + 1 === n);
    });
    // Update circles
    for (let i = 1; i <= 3; i++) {
        const sc = document.getElementById(`sc-${i}`);
        const sl = document.getElementById(`sl-${i}`);
        sc.className = "step-circle" + (i < n ? " done" : i === n ? " active" : "");
        sl.className = "step-label"  + (i < n ? " done" : i === n ? " active" : "");
    }
    // Update connectors
    for (let i = 1; i <= 2; i++) {
        const conn = document.getElementById(`conn-${i}`);
        conn.className = "step-connector" + (i < n ? " done" : "");
    }
}

// ── Init ──────────────────────────────────────────────────────────
(function init() {
    const now    = new Date();
    currentYear  = now.getFullYear();
    currentMonth = now.getMonth();
    // Start the strip on today so every visible card is bookable.
    dateOffset = now.getDate() - 1;
    buildTimezoneSelect();
    renderDateStrip();
    goStep(1);

    if (_cfg.selectedDate && _cfg.selectedTime) {
        selectedDate = _cfg.selectedDate;
        selectedTime = _cfg.selectedTime;
        updateSummary();
        goStep(3);
    }
})();
