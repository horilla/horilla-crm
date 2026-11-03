/**
 * Horilla FullCalendar — Jalali calendar integration (Phase 2).
 *
 * Step 1: Shamsi titles + RTL shell.
 * Step 2: Jalali day-view column header.
 * Step 3: Jalali week-view column headers.
 * Step 4: Jalali day numbers in month-view cells.
 * Month gray-out: fade grid cells outside the active Shamsi month (display only).
 * Month view: an isolated dayGrid view with a true Shamsi month range.
 * Year view: twelve exact Shamsi month profiles rendered by FullCalendar's
 * native responsive multi-month component.
 * Step 6: Popover dates, Jalali today highlight, modal picker hooks.
 * Timeline view: Shamsi month/season columns via window.horillaTimelineCalendar.
 * Events stay Gregorian ISO in the API/DB.
 */
(function (window) {
    "use strict";

    var PERSIAN_LOCALE = {
        code: "fa",
        direction: "rtl",
        buttonText: {
            prev: "قبلی",
            next: "بعدی",
            today: "امروز",
            month: "ماه",
            week: "هفته",
            day: "روز",
            list: "لیست",
            year: "سال",
        },
        weekText: "هف",
        allDayText: "تمام‌روز",
        moreLinkText: "بیشتر",
        noEventsText: "رویدادی برای نمایش نیست",
        week: { dow: 6, doy: 12 },
    };

    var JALALI_MONTH_VIEW_TYPE = "dayGridJalaliMonth";
    var JALALI_YEAR_VIEW_TYPE = "multiMonthJalaliYear";
    var JALALI_WEEK_START = 6;
    var DAY_IN_MILLISECONDS = 86400000;
    var jalaliMultiMonthViewComponent = null;

    /** Active Shamsi month for month-view outside-day fading ({ year, month } strings). */
    var activeJalaliMonthContext = null;

    function usesJalaliCalendar() {
        return document.body && document.body.dataset.useJalaliCalendar === "true";
    }

    function registerPersianLocale() {
        if (!window.FullCalendar || !window.FullCalendar.globalLocales) {
            return;
        }
        var locales = window.FullCalendar.globalLocales;
        var exists = locales.some(function (loc) {
            return loc.code === "fa";
        });
        if (!exists) {
            locales.push(PERSIAN_LOCALE);
        }
    }

    function padDatePart(value) {
        return String(value).padStart(2, "0");
    }

    function gregorianToJalaliParts(gy, gm, gd) {
        var gDaysInMonth = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
        var jy = gy <= 1600 ? 0 : 979;
        gy -= gy <= 1600 ? 621 : 1600;
        var gy2 = gm > 2 ? gy + 1 : gy;
        var days =
            365 * gy +
            Math.floor((gy2 + 3) / 4) -
            Math.floor((gy2 + 99) / 100) +
            Math.floor((gy2 + 399) / 400) -
            80 +
            gd +
            gDaysInMonth[gm - 1];
        jy += 33 * Math.floor(days / 12053);
        days %= 12053;
        jy += 4 * Math.floor(days / 1461);
        days %= 1461;
        if (days > 365) {
            jy += Math.floor((days - 1) / 365);
            days = (days - 1) % 365;
        }
        var jm = days < 186 ? 1 + Math.floor(days / 31) : 7 + Math.floor((days - 186) / 30);
        var jd = 1 + (days < 186 ? days % 31 : (days - 186) % 30);
        return { year: jy, month: jm, day: jd };
    }

    function jalaliToGregorianParts(jy, jm, jd) {
        var salA = jy > 979 ? 979 : 0;
        var gy = jy > 979 ? 1600 : 621;
        jy -= salA;
        var days =
            365 * jy +
            Math.floor(jy / 33) * 8 +
            Math.floor(((jy % 33) + 3) / 4) +
            78 +
            jd +
            (jm < 7 ? (jm - 1) * 31 : (jm - 7) * 30 + 186);
        gy += 400 * Math.floor(days / 146097);
        days %= 146097;
        if (days > 36524) {
            gy += 100 * Math.floor(--days / 36524);
            days %= 36524;
            if (days >= 365) {
                days += 1;
            }
        }
        gy += 4 * Math.floor(days / 1461);
        days %= 1461;
        if (days > 365) {
            gy += Math.floor((days - 1) / 365);
            days = (days - 1) % 365;
        }
        var gd = days + 1;
        var monthDays = [
            0,
            31,
            (gy % 4 === 0 && gy % 100 !== 0) || gy % 400 === 0 ? 29 : 28,
            31,
            30,
            31,
            30,
            31,
            31,
            30,
            31,
            30,
            31,
        ];
        var gm = 0;
        while (gm < 13 && gd > monthDays[gm]) {
            gd -= monthDays[gm];
            gm += 1;
        }
        return { year: gy, month: gm, day: gd };
    }

    function getJalaliPartsFromDate(date) {
        if (!date) {
            return null;
        }
        return gregorianToJalaliParts(
            date.getFullYear(),
            date.getMonth() + 1,
            date.getDate()
        );
    }

    /**
     * FullCalendar's internal date markers store calendar fields in UTC,
     * independently of the browser timezone.
     */
    function getJalaliPartsFromUtcMarker(marker) {
        if (!marker) {
            return null;
        }
        return gregorianToJalaliParts(
            marker.getUTCFullYear(),
            marker.getUTCMonth() + 1,
            marker.getUTCDate()
        );
    }

    function addJalaliMonths(year, month, amount) {
        var index = year * 12 + (month - 1) + amount;
        var targetYear = Math.floor(index / 12);
        return {
            year: targetYear,
            month: index - targetYear * 12 + 1,
        };
    }

    function gregorianPartsToUtcTime(parts) {
        return Date.UTC(parts.year, parts.month - 1, parts.day);
    }

    function addGregorianDays(parts, amount) {
        var date = new Date(gregorianPartsToUtcTime(parts));
        date.setUTCDate(date.getUTCDate() + amount);
        return {
            year: date.getUTCFullYear(),
            month: date.getUTCMonth() + 1,
            day: date.getUTCDate(),
        };
    }

    function getGregorianWeekday(parts) {
        return new Date(gregorianPartsToUtcTime(parts)).getUTCDay();
    }

    function formatGregorianIsoDate(parts) {
        return (
            parts.year +
            "-" +
            padDatePart(parts.month) +
            "-" +
            padDatePart(parts.day)
        );
    }

    function getJalaliMonthLength(year, month) {
        var next = addJalaliMonths(year, month, 1);
        var startParts = jalaliToGregorianParts(year, month, 1);
        var endParts = jalaliToGregorianParts(next.year, next.month, 1);
        return Math.round(
            (gregorianPartsToUtcTime(endParts) -
                gregorianPartsToUtcTime(startParts)) /
                DAY_IN_MILLISECONDS
        );
    }

    /**
     * FullCalendar only builds a seven-column dayGrid when its range unit is a
     * week/month/year. Return date-only ISO boundaries for exactly six
     * Saturday-to-Saturday weeks, matching dayGridMonth's stable 6x7 layout.
     */
    function getJalaliMonthVisibleRange(year, month) {
        var next = addJalaliMonths(year, month, 1);
        var startParts = jalaliToGregorianParts(year, month, 1);
        var endParts = jalaliToGregorianParts(next.year, next.month, 1);
        var daysBeforeMonth =
            (getGregorianWeekday(startParts) - JALALI_WEEK_START + 7) % 7;
        var daysAfterMonth =
            (JALALI_WEEK_START - getGregorianWeekday(endParts) + 7) % 7;
        var gridStartParts = addGregorianDays(startParts, -daysBeforeMonth);
        var gridEndParts = addGregorianDays(endParts, daysAfterMonth);
        var renderedDayCount = Math.round(
            (gregorianPartsToUtcTime(gridEndParts) -
                gregorianPartsToUtcTime(gridStartParts)) /
                DAY_IN_MILLISECONDS
        );
        gridEndParts = addGregorianDays(
            gridEndParts,
            42 - renderedDayCount
        );

        return {
            start: formatGregorianIsoDate(gridStartParts),
            end: formatGregorianIsoDate(gridEndParts),
        };
    }

    function jalaliMonthVisibleRange(currentDate) {
        var parts = getJalaliPartsFromDate(currentDate);
        if (!parts) {
            return null;
        }
        setActiveJalaliMonthContext(currentDate);
        return getJalaliMonthVisibleRange(parts.year, parts.month);
    }

    function jalaliYearVisibleRange(currentDate) {
        var parts = getJalaliPartsFromDate(currentDate);
        if (!parts) {
            return null;
        }
        return {
            start: formatGregorianIsoDate(
                jalaliToGregorianParts(parts.year, 1, 1)
            ),
            end: formatGregorianIsoDate(
                jalaliToGregorianParts(parts.year + 1, 1, 1)
            ),
        };
    }

    function isJalaliMonthViewType(viewType) {
        return viewType === JALALI_MONTH_VIEW_TYPE;
    }

    function isJalaliYearViewType(viewType) {
        return viewType === JALALI_YEAR_VIEW_TYPE;
    }

    function getMonthViewType() {
        return usesJalaliCalendar()
            ? JALALI_MONTH_VIEW_TYPE
            : "dayGridMonth";
    }

    function getBaseMultiMonthViewComponent() {
        if (
            !window.FullCalendar ||
            !window.FullCalendar.globalPlugins
        ) {
            return null;
        }

        var plugins = window.FullCalendar.globalPlugins;
        var fallback = null;
        for (var index = 0; index < plugins.length; index += 1) {
            var plugin = plugins[index];
            var view =
                plugin &&
                plugin.views &&
                plugin.views.multiMonth;
            if (view && view.component) {
                if (plugin.name === "@fullcalendar/multimonth") {
                    return view.component;
                }
                fallback = fallback || view.component;
            }
        }
        return fallback;
    }

    /**
     * The stock MultiMonthView always splits its range into Gregorian months.
     * Supply twelve precise Jalali month profiles instead, while reusing the
     * stock SingleMonth renderer for events, links, popovers, and sizing.
     */
    function splitJalaliYearDateProfiles(
        dateProfileGenerator,
        dateProfile,
        dateEnv,
        fixedWeekCount,
        showNonCurrentDates
    ) {
        var currentParts = getJalaliPartsFromUtcMarker(
            dateProfile.currentDate
        );
        if (!currentParts) {
            return [];
        }

        var internal = window.FullCalendar.Internal;
        var monthProfiles = [];
        for (var month = 1; month <= 12; month += 1) {
            var next = addJalaliMonths(currentParts.year, month, 1);
            var currentRange = {
                start: dateEnv.createMarker(
                    formatGregorianIsoDate(
                        jalaliToGregorianParts(
                            currentParts.year,
                            month,
                            1
                        )
                    )
                ),
                end: dateEnv.createMarker(
                    formatGregorianIsoDate(
                        jalaliToGregorianParts(
                            next.year,
                            next.month,
                            1
                        )
                    )
                ),
            };
            var visibleRange = getJalaliMonthVisibleRange(
                currentParts.year,
                month
            );
            var renderRange = {
                start: dateEnv.createMarker(visibleRange.start),
                end: dateEnv.createMarker(visibleRange.end),
            };
            var activeRange = dateProfile.activeRange
                ? internal.intersectRanges(
                      dateProfile.activeRange,
                      showNonCurrentDates
                          ? renderRange
                          : currentRange
                  )
                : null;

            monthProfiles.push({
                currentDate: dateProfile.currentDate,
                isValid: dateProfile.isValid,
                validRange: dateProfile.validRange,
                renderRange: renderRange,
                activeRange: activeRange,
                currentRange: currentRange,
                currentRangeUnit: "month",
                isRangeAllDay: true,
                dateIncrement: dateProfile.dateIncrement,
                slotMinTime: dateProfile.slotMinTime,
                slotMaxTime: dateProfile.slotMaxTime,
            });
        }
        return monthProfiles;
    }

    function getJalaliMultiMonthViewComponent() {
        if (jalaliMultiMonthViewComponent) {
            return jalaliMultiMonthViewComponent;
        }
        if (
            !window.FullCalendar ||
            !window.FullCalendar.Internal
        ) {
            return null;
        }

        var BaseMultiMonthView = getBaseMultiMonthViewComponent();
        if (!BaseMultiMonthView) {
            return null;
        }

        var internal = window.FullCalendar.Internal;
        jalaliMultiMonthViewComponent = class extends BaseMultiMonthView {
            constructor() {
                super(...arguments);
                this.splitDateProfileByMonth = internal.memoize(
                    splitJalaliYearDateProfiles
                );
            }

            updateSize() {
                var scrollEl =
                    this.scrollElRef && this.scrollElRef.current;
                var firstMonthEl =
                    this.firstMonthElRef && this.firstMonthElRef.current;
                if (scrollEl) {
                    this.setState({
                        clientWidth: scrollEl.clientWidth,
                        clientHeight: scrollEl.clientHeight,
                    });
                }
                if (
                    firstMonthEl &&
                    firstMonthEl.firstChild &&
                    scrollEl &&
                    this.state.monthHPadding == null
                ) {
                    this.setState({
                        monthHPadding:
                            scrollEl.clientWidth -
                            firstMonthEl.firstChild.offsetWidth,
                    });
                }
            }

            /**
             * The stock method searches by Gregorian YYYY-MM and throws when
             * that cell is missing (common while switching into Shamsi year
             * view). Scroll by Jalali month index instead.
             */
            flushScrollReset() {
                if (
                    !this.needsScrollReset ||
                    this.state.monthHPadding == null
                ) {
                    return;
                }

                var scrollEl =
                    this.scrollElRef && this.scrollElRef.current;
                var firstMonthEl =
                    this.firstMonthElRef && this.firstMonthElRef.current;
                var currentParts = getJalaliPartsFromUtcMarker(
                    this.props.dateProfile &&
                        this.props.dateProfile.currentDate
                );
                if (scrollEl && firstMonthEl && currentParts) {
                    var monthEls = scrollEl.getElementsByClassName(
                        "fc-multimonth-month"
                    );
                    var monthEl =
                        monthEls[currentParts.month - 1] ||
                        monthEls[0];
                    if (monthEl) {
                        scrollEl.scrollTop =
                            monthEl.getBoundingClientRect().top -
                            firstMonthEl.getBoundingClientRect().top;
                    }
                }
                this.needsScrollReset = false;
            }
        };
        return jalaliMultiMonthViewComponent;
    }

    function getYearViewType() {
        return usesJalaliCalendar() &&
            getJalaliMultiMonthViewComponent()
            ? JALALI_YEAR_VIEW_TYPE
            : "multiMonthYear";
    }

    /**
     * FullCalendar cannot increment a non-Gregorian month itself. Preserve the
     * current Shamsi day where possible and move to the adjacent Shamsi month.
     */
    function navigateJalaliMonth(calendar, amount) {
        if (
            !calendar ||
            !calendar.view ||
            !isJalaliMonthViewType(calendar.view.type) ||
            typeof calendar.getDate !== "function"
        ) {
            return false;
        }

        var currentParts = getJalaliPartsFromDate(calendar.getDate());
        if (!currentParts) {
            return false;
        }

        var target = addJalaliMonths(
            currentParts.year,
            currentParts.month,
            amount
        );
        var targetDay = Math.min(
            currentParts.day,
            getJalaliMonthLength(target.year, target.month)
        );
        var targetGregorian = jalaliToGregorianParts(
            target.year,
            target.month,
            targetDay
        );
        calendar.gotoDate(formatGregorianIsoDate(targetGregorian));
        return true;
    }

    /**
     * Preserve the current Jalali month/day while moving by a logical
     * Jalali year. Clip Esfand 30 when the destination year is not leap.
     */
    function navigateJalaliYear(calendar, amount) {
        if (
            !calendar ||
            !calendar.view ||
            !isJalaliYearViewType(calendar.view.type) ||
            typeof calendar.getDate !== "function"
        ) {
            return false;
        }

        var currentParts = getJalaliPartsFromDate(calendar.getDate());
        if (!currentParts) {
            return false;
        }

        var targetYear = currentParts.year + amount;
        var targetDay = Math.min(
            currentParts.day,
            getJalaliMonthLength(targetYear, currentParts.month)
        );
        var targetGregorian = jalaliToGregorianParts(
            targetYear,
            currentParts.month,
            targetDay
        );
        calendar.gotoDate(formatGregorianIsoDate(targetGregorian));
        return true;
    }

    function formatWithPersianCalendar(date, options) {
        if (!date) {
            return null;
        }
        try {
            var fmtOptions = Object.assign({ numberingSystem: "latn" }, options || {});
            return new Intl.DateTimeFormat("fa-IR-u-ca-persian", fmtOptions).format(date);
        } catch (err) {
            return null;
        }
    }

    function getJalaliMonthName(date) {
        return formatWithPersianCalendar(date, { month: "long" });
    }

    function getJalaliWeekdayName(date, style) {
        return formatWithPersianCalendar(date, { weekday: style || "long" });
    }

    /** e.g. یکشنبه ۲۱ مرداد 1405 */
    function formatJalaliDayHeaderFull(date) {
        var weekday = getJalaliWeekdayName(date, "long");
        var day = getJalaliDayNumber(date);
        var month = getJalaliMonthName(date);
        var year = formatWithPersianCalendar(date, { year: "numeric" });
        if (weekday && day && month && year) {
            return weekday + " " + day + " " + month + " " + year;
        }
        return null;
    }

    function getJalaliDayNumber(date) {
        return formatWithPersianCalendar(date, {
            day: "numeric",
            numberingSystem: "arabext",
        });
    }

    /** e.g. یکشنبه ۲۱ مرداد */
    function formatJalaliDayHeaderWeek(date) {
        var weekday = getJalaliWeekdayName(date, "long");
        var day = getJalaliDayNumber(date);
        var month = getJalaliMonthName(date);
        if (weekday && day && month) {
            return weekday + " " + day + " " + month;
        }
        return null;
    }

    function getJalaliMonthYearParts(date) {
        if (!date) {
            return null;
        }
        var year = formatWithPersianCalendar(date, { year: "numeric" });
        var month = formatWithPersianCalendar(date, { month: "numeric" });
        if (!year || !month) {
            return null;
        }
        return { year: year, month: month };
    }

    function setActiveJalaliMonthContext(date) {
        activeJalaliMonthContext = getJalaliMonthYearParts(date);
    }

    function isOutsideActiveJalaliMonth(cellDate) {
        if (!activeJalaliMonthContext || !cellDate) {
            return false;
        }
        var parts = getJalaliMonthYearParts(cellDate);
        if (!parts) {
            return false;
        }
        return (
            parts.year !== activeJalaliMonthContext.year ||
            parts.month !== activeJalaliMonthContext.month
        );
    }

    function syncActiveJalaliMonthFromCalendar(calendar) {
        if (
            !usesJalaliCalendar() ||
            !calendar ||
            !calendar.view ||
            !isJalaliMonthViewType(calendar.view.type)
        ) {
            activeJalaliMonthContext = null;
            return;
        }
        var anchor =
            typeof calendar.getDate === "function"
                ? calendar.getDate()
                : calendar.view.currentStart;
        if (anchor) {
            setActiveJalaliMonthContext(anchor);
        }
    }

    function getJalaliDateKey(date) {
        if (!date) {
            return null;
        }
        return formatWithPersianCalendar(date, {
            year: "numeric",
            month: "numeric",
            day: "numeric",
        });
    }

    function isSameJalaliDay(left, right) {
        if (!left || !right) {
            return false;
        }
        var leftKey = getJalaliDateKey(left);
        var rightKey = getJalaliDateKey(right);
        return Boolean(leftKey && rightKey && leftKey === rightKey);
    }

    function isJalaliToday(date) {
        return isSameJalaliDay(date, new Date());
    }

    /** Fallback popup datetime when API display string is missing. */
    function formatDateTimeDisplay(date) {
        if (!date) {
            return null;
        }
        var dayPart = formatWithPersianCalendar(date, {
            day: "numeric",
            month: "long",
            year: "numeric",
        });
        var timePart = formatWithPersianCalendar(date, {
            hour: "numeric",
            minute: "2-digit",
            hour12: false,
        });
        if (dayPart && timePart) {
            return dayPart + ", " + timePart;
        }
        return dayPart || timePart || null;
    }

    function dayPopoverFormat(date) {
        if (!usesJalaliCalendar() || !date) {
            return date ? date.toString() : "";
        }
        return formatJalaliDayHeaderFull(date) || date.toString();
    }

    function dayCellClassNames(arg) {
        if (!usesJalaliCalendar() || !arg || !arg.date) {
            return [];
        }
        var classes = [];
        if (arg.view && isJalaliMonthViewType(arg.view.type)) {
            var cal = arg.view.calendar || window.calendarInstance;
            if (cal) {
                syncActiveJalaliMonthFromCalendar(cal);
            }
            if (isOutsideActiveJalaliMonth(arg.date)) {
                classes.push("horilla-jalali-outside-month");
            }
        }
        if (isJalaliToday(arg.date)) {
            classes.push("horilla-jalali-today");
        }
        return classes;
    }

    function dayHeaderClassNames(arg) {
        if (!usesJalaliCalendar() || !arg || !arg.date) {
            return [];
        }
        if (isJalaliToday(arg.date)) {
            return ["horilla-jalali-today"];
        }
        return [];
    }

    function dayHeaderContent(arg) {
        if (!usesJalaliCalendar() || !arg || !arg.date) {
            return undefined;
        }
        if (arg.view.type === "timeGridDay") {
            return formatJalaliDayHeaderFull(arg.date) || arg.text;
        }
        if (arg.view.type === "timeGridWeek") {
            return formatJalaliDayHeaderWeek(arg.date) || arg.text;
        }
        if (
            isJalaliMonthViewType(arg.view.type) ||
            isJalaliYearViewType(arg.view.type)
        ) {
            return getJalaliWeekdayName(arg.date, "long") || arg.text;
        }
        return arg.text;
    }

    function dayCellContent(arg) {
        if (!usesJalaliCalendar() || !arg || !arg.date) {
            return undefined;
        }
        if (
            isJalaliMonthViewType(arg.view.type) ||
            isJalaliYearViewType(arg.view.type)
        ) {
            return getJalaliDayNumber(arg.date) || arg.dayNumberText;
        }
        return arg.dayNumberText;
    }

    function endExclusiveToInclusive(endDate) {
        if (!endDate) {
            return null;
        }
        return new Date(endDate.getTime() - 86400000);
    }

    function formatJalaliMonthYearTitle(date, options) {
        if (!date) {
            return "";
        }
        var fmtOptions = options || {};
        var month = formatWithPersianCalendar(
            date,
            Object.assign({ month: "long" }, fmtOptions)
        );
        var year = formatWithPersianCalendar(
            date,
            Object.assign({ year: "numeric" }, fmtOptions)
        );
        if (month && year) {
            return month + " " + year;
        }
        return month || year || "";
    }

    function formatCalendarTitle(calendar) {
        if (!calendar || !calendar.view) {
            return "";
        }

        var view = calendar.view;
        var start = view.currentStart;
        var endInclusive = endExclusiveToInclusive(view.currentEnd);
        var isLogicalJalaliRange =
            isJalaliMonthViewType(view.type) ||
            isJalaliYearViewType(view.type) ||
            view.type === "multiMonthYear";
        var anchorDate =
            isLogicalJalaliRange &&
            typeof calendar.getDate === "function"
                ? calendar.getDate()
                : start;
        var title = "";

        switch (view.type) {
            case "timeGridDay":
                title = formatJalaliDayHeaderFull(start);
                break;
            case "timeGridWeek":
                if (start && endInclusive) {
                    var weekStart = formatJalaliDayHeaderWeek(start);
                    var weekEnd = formatJalaliDayHeaderFull(endInclusive);
                    if (weekStart && weekEnd) {
                        title = weekStart + " – " + weekEnd;
                    }
                }
                break;
            case JALALI_YEAR_VIEW_TYPE:
            case "multiMonthYear":
                title = formatWithPersianCalendar(anchorDate, {
                    year: "numeric",
                });
                break;
            case JALALI_MONTH_VIEW_TYPE:
            case "dayGridMonth":
            default:
                title = formatJalaliMonthYearTitle(anchorDate);
                break;
        }

        if (title) {
            return title;
        }

        return view.title || "";
    }

    function getDayGridMonthOptions() {
        if (!usesJalaliCalendar()) {
            return {};
        }
        return {
            type: "dayGrid",
            visibleRange: jalaliMonthVisibleRange,
            fixedWeekCount: false,
        };
    }

    function formatJalaliMultiMonthTitle(arg) {
        var marker =
            arg &&
            arg.date &&
            arg.date.marker;
        if (!marker) {
            return "";
        }
        return formatJalaliMonthYearTitle(marker, { timeZone: "UTC" });
    }

    function getMultiMonthYearOptions() {
        if (!usesJalaliCalendar()) {
            return {};
        }
        var component = getJalaliMultiMonthViewComponent();
        if (!component) {
            return {};
        }
        return {
            type: "multiMonth",
            component: component,
            visibleRange: jalaliYearVisibleRange,
            fixedWeekCount: true,
            showNonCurrentDates: false,
            multiMonthTitleFormat: formatJalaliMultiMonthTitle,
        };
    }

    function getCalendarOptions() {
        if (!usesJalaliCalendar()) {
            return {};
        }
        registerPersianLocale();
        return {
            locale: "fa",
            direction: "rtl",
            firstDay: JALALI_WEEK_START,
            dayHeaderContent: dayHeaderContent,
            dayHeaderClassNames: dayHeaderClassNames,
            dayCellContent: dayCellContent,
            dayCellClassNames: dayCellClassNames,
            dayPopoverFormat: dayPopoverFormat,
        };
    }

    function updateTitleElement(calendar, titleEl) {
        if (!titleEl || !calendar) {
            return;
        }
        syncActiveJalaliMonthFromCalendar(calendar);
        if (usesJalaliCalendar()) {
            titleEl.textContent = formatCalendarTitle(calendar);
            return;
        }
        if (calendar.view && calendar.view.title) {
            titleEl.textContent = calendar.view.title;
        }
    }

    function cloneViews(source) {
        var views = {};
        if (!source) {
            return views;
        }
        Object.keys(source).forEach(function (key) {
            views[key] = source[key];
        });
        return views;
    }

    function normalizeInitialView(viewType) {
        if (
            !viewType ||
            viewType === "dayGridMonth" ||
            viewType === JALALI_MONTH_VIEW_TYPE
        ) {
            return getMonthViewType();
        }
        if (
            viewType === "multiMonthYear" ||
            viewType === JALALI_YEAR_VIEW_TYPE
        ) {
            return getYearViewType();
        }
        return viewType;
    }

    function remapChangeViewArg(viewType) {
        if (
            viewType === "dayGridMonth" ||
            viewType === JALALI_MONTH_VIEW_TYPE
        ) {
            return getMonthViewType();
        }
        if (
            viewType === "multiMonthYear" ||
            viewType === JALALI_YEAR_VIEW_TYPE
        ) {
            return getYearViewType();
        }
        return viewType;
    }

    function isMultiDayCalendarView(viewType) {
        return (
            viewType === "timeGridWeek" ||
            viewType === "dayGridMonth" ||
            isJalaliMonthViewType(viewType) ||
            viewType === "multiMonthYear" ||
            isJalaliYearViewType(viewType)
        );
    }

    function navigateCalendarToDayView(calendar, date) {
        if (!calendar || !date || typeof calendar.changeView !== "function") {
            return;
        }
        calendar.changeView("timeGridDay", date);
        window.currentView = "timeGridDay";
        try {
            localStorage.setItem("calendarView", "timeGridDay");
        } catch (err) {}
        setCalendarTabActive("dayView");
        scheduleTitleSync(calendar);
    }

    function wrapDateClickForDayNavigation(options) {
        var wrapped = Object.assign({}, options || {});
        var originalDateClick = wrapped.dateClick;
        wrapped.navLinkDayClick = function (date) {
            navigateCalendarToDayView(
                window.calendarInstance || this,
                date
            );
        };
        wrapped.dateClick = function (info) {
            if (
                info &&
                info.view &&
                isMultiDayCalendarView(info.view.type)
            ) {
                navigateCalendarToDayView(
                    info.view.calendar || window.calendarInstance,
                    info.date
                );
                return;
            }
            if (typeof originalDateClick === "function") {
                originalDateClick(info);
            }
        };
        return wrapped;
    }

    function prepareJalaliCalendarOptions(options) {
        options = wrapDateClickForDayNavigation(options);
        if (!usesJalaliCalendar()) {
            return options;
        }
        var views = cloneViews(options.views);
        var monthOpts = getDayGridMonthOptions();
        var yearOpts = getMultiMonthYearOptions();
        views[getMonthViewType()] = Object.assign({}, monthOpts);
        if (yearOpts && yearOpts.component) {
            // Do not merge stock multiMonthYear — its duration: { years: 1 }
            // makes FullCalendar ignore visibleRange and breaks live
            // changeView into/out of the Shamsi year grid.
            views[JALALI_YEAR_VIEW_TYPE] = Object.assign({}, yearOpts);
            views.multiMonthYear = Object.assign({}, yearOpts);
        }
        return Object.assign({}, options, getCalendarOptions(), {
            views: views,
            initialView: normalizeInitialView(options.initialView),
        });
    }

    function syncCanonicalViewName(instance) {
        if (!instance || !instance.view) {
            return;
        }
        var type = instance.view.type;
        if (isJalaliMonthViewType(type)) {
            window.currentView = "dayGridMonth";
            try {
                localStorage.setItem("calendarView", "dayGridMonth");
            } catch (err) {}
        } else if (isJalaliYearViewType(type)) {
            window.currentView = "multiMonthYear";
            try {
                localStorage.setItem("calendarView", "multiMonthYear");
            } catch (err) {}
        }
    }

    function scheduleTitleSync(instance) {
        var sync = function () {
            syncCanonicalViewName(instance);
            updateTitleElement(
                instance,
                document.getElementById("calendarTitle")
            );
        };
        if (typeof queueMicrotask === "function") {
            queueMicrotask(sync);
            return;
        }
        setTimeout(sync, 0);
    }

    function decorateJalaliCalendarInstance(instance, el) {
        if (!usesJalaliCalendar() || !instance) {
            return instance;
        }
        if (el && el.classList) {
            el.classList.add("horilla-calendar-jalali");
        }
        if (instance.__horillaJalaliDecorated) {
            return instance;
        }
        instance.__horillaJalaliDecorated = true;

        var origPrev = instance.prev.bind(instance);
        instance.prev = function () {
            if (
                navigateJalaliMonth(instance, -1) ||
                navigateJalaliYear(instance, -1)
            ) {
                return;
            }
            return origPrev();
        };

        var origNext = instance.next.bind(instance);
        instance.next = function () {
            if (
                navigateJalaliMonth(instance, 1) ||
                navigateJalaliYear(instance, 1)
            ) {
                return;
            }
            return origNext();
        };

        var origChangeView = instance.changeView.bind(instance);
        instance.changeView = function (viewType, dateOrRange) {
            origChangeView(remapChangeViewArg(viewType), dateOrRange);
            if (typeof instance.updateSize === "function") {
                requestAnimationFrame(function () {
                    try {
                        instance.updateSize();
                    } catch (err) {}
                });
            }
        };

        var origRender = instance.render.bind(instance);
        instance.render = function () {
            origRender();
            syncCanonicalViewName(instance);
            updateTitleElement(
                instance,
                document.getElementById("calendarTitle")
            );
            scheduleTitleSync(instance);
        };

        if (typeof instance.on === "function") {
            instance.on("datesSet", function () {
                scheduleTitleSync(instance);
            });
        }
        return instance;
    }

    function installFullCalendarHook() {
        if (!window.FullCalendar || !window.FullCalendar.Calendar) {
            return false;
        }
        if (window.FullCalendar.__horillaJalaliPatched) {
            return true;
        }
        var OriginalCalendar = window.FullCalendar.Calendar;
        function HorillaJalaliCalendar(el, options) {
            var instance = new OriginalCalendar(
                el,
                prepareJalaliCalendarOptions(options || {})
            );
            return decorateJalaliCalendarInstance(instance, el);
        }
        HorillaJalaliCalendar.prototype = OriginalCalendar.prototype;
        try {
            Object.setPrototypeOf(HorillaJalaliCalendar, OriginalCalendar);
        } catch (err) {}
        window.FullCalendar.Calendar = HorillaJalaliCalendar;
        window.FullCalendar.__horillaJalaliPatched = true;
        return true;
    }

    function isRtlPage() {
        return (
            document.documentElement &&
            document.documentElement.getAttribute("dir") === "rtl"
        );
    }

    function fixCalendarNavChevrons() {
        if (!isRtlPage()) {
            return;
        }
        var prevIcon = document.querySelector("#prevBtn i");
        var nextIcon = document.querySelector("#nextBtn i");
        if (prevIcon) {
            prevIcon.classList.remove("fa-chevron-left", "fa-chevron-right");
            prevIcon.classList.add("fa-chevron-right");
        }
        if (nextIcon) {
            nextIcon.classList.remove("fa-chevron-left", "fa-chevron-right");
            nextIcon.classList.add("fa-chevron-left");
        }
    }

    function getCalendarTypePanel() {
        var master = document.getElementById("masterCheckbox");
        if (!master) {
            return null;
        }
        return master.closest(".col-span-6") || master.closest("[class*='col-span']");
    }

    function restoreInlineStyle(element, property, value, priority) {
        if (value) {
            element.style.setProperty(property, value, priority);
        } else {
            element.style.removeProperty(property);
        }
    }

    function measureCalendarSidebarDropdown(content) {
        var rect = content.getBoundingClientRect();
        if (rect.width && rect.height) {
            return rect;
        }

        var display = content.style.getPropertyValue("display");
        var displayPriority = content.style.getPropertyPriority("display");
        var visibility = content.style.getPropertyValue("visibility");
        var visibilityPriority =
            content.style.getPropertyPriority("visibility");

        content.style.setProperty("display", "block", "important");
        content.style.setProperty("visibility", "hidden", "important");
        rect = content.getBoundingClientRect();

        restoreInlineStyle(
            content,
            "display",
            display,
            displayPriority
        );
        restoreInlineStyle(
            content,
            "visibility",
            visibility,
            visibilityPriority
        );
        return rect;
    }

    function positionCalendarSidebarDropdown(wrapper) {
        var content = wrapper && wrapper.querySelector(".dropdown-content");
        var trigger = wrapper && wrapper.querySelector("button");
        if (!content || !trigger) {
            return;
        }
        if (!isRtlPage()) {
            return;
        }

        var triggerRect = trigger.getBoundingClientRect();
        var gap = 4;
        content.classList.add("horilla-calendar-sidebar-dropdown");
        content.style.setProperty("position", "fixed", "important");
        content.style.setProperty("right", "auto", "important");
        content.style.setProperty("inset-inline-start", "auto", "important");
        content.style.setProperty("inset-inline-end", "auto", "important");
        content.style.setProperty("transform", "none", "important");
        content.style.setProperty("z-index", "80", "important");

        var menuRect = measureCalendarSidebarDropdown(content);
        var left = triggerRect.right + gap;
        var top = triggerRect.bottom + gap;
        if (left + menuRect.width > window.innerWidth - 8) {
            left = Math.max(8, window.innerWidth - menuRect.width - 8);
        }
        if (top + menuRect.height > window.innerHeight - 8) {
            top = Math.max(8, triggerRect.top - menuRect.height - gap);
        }
        content.style.setProperty("left", left + "px", "important");
        content.style.setProperty("top", top + "px", "important");
    }

    function prepareCalendarSidebarDropdowns(panel) {
        if (!panel) {
            return;
        }
        panel
            .querySelectorAll(".dropdown-wrapper")
            .forEach(function (wrapper) {
                positionCalendarSidebarDropdown(wrapper);
            });
    }

    function wireCalendarSidebarDropdowns() {
        if (
            document.documentElement.dataset.horillaCalendarSidebarDropdowns ===
            "true"
        ) {
            return;
        }
        document.documentElement.dataset.horillaCalendarSidebarDropdowns =
            "true";

        var prepareClickedDropdown = function (event) {
            var panel = getCalendarTypePanel();
            var target = event.target;
            if (
                !panel ||
                !target ||
                typeof target.closest !== "function"
            ) {
                return;
            }
            var wrapper = target.closest(".dropdown-wrapper");
            if (wrapper && panel.contains(wrapper)) {
                positionCalendarSidebarDropdown(wrapper);
            }
        };

        /*
         * Position on pointerdown, before core's click handler adds `active`.
         * This prevents one painted frame at the old off-screen position.
         * The click fallback also supports keyboard-triggered buttons.
         */
        document.addEventListener(
            "pointerdown",
            prepareClickedDropdown,
            true
        );
        document.addEventListener("click", prepareClickedDropdown, true);

        var repositionOpenDropdown = function () {
            var panel = getCalendarTypePanel();
            if (!panel) {
                return;
            }
            panel
                .querySelectorAll(".dropdown-wrapper.active")
                .forEach(function (wrapper) {
                    positionCalendarSidebarDropdown(wrapper);
                });
        };
        window.addEventListener("resize", repositionOpenDropdown);
        window.addEventListener("scroll", repositionOpenDropdown, true);
    }

    function fixCalendarSidebar() {
        var panel = getCalendarTypePanel();
        if (panel) {
            panel.classList.add("calendar-sidebar");
            prepareCalendarSidebarDropdowns(panel);
        }
        var grid = document.getElementById("calendarGrid");
        if (!grid) {
            return;
        }
        var row = grid.closest(".grid");
        if (!row) {
            return;
        }
        var columns = row.children;
        for (var i = 0; i < columns.length; i += 1) {
            if (columns[i].contains(grid) && columns[i + 1]) {
                columns[i + 1].classList.add("calendar-sidebar");
                return;
            }
        }
    }

    function setCalendarTabActive(activeId) {
        document.querySelectorAll(".tab-btn").forEach(function (btn) {
            if (btn.id === activeId) {
                btn.classList.add("bg-primary-600", "text-white");
                btn.classList.remove("bg-primary-300", "text-primary-600");
            } else if (
                btn.id === "dayView" ||
                btn.id === "weekView" ||
                btn.id === "monthView" ||
                btn.id === "yearView"
            ) {
                btn.classList.add("bg-primary-300", "text-primary-600");
                btn.classList.remove("bg-primary-600", "text-white");
            }
        });
    }

    function switchJalaliCalendarView(buttonId) {
        var calendar = window.calendarInstance;
        if (!calendar || typeof calendar.changeView !== "function") {
            return false;
        }
        var viewType = "dayGridMonth";
        var storedView = "dayGridMonth";
        if (buttonId === "yearView") {
            viewType = getYearViewType();
            storedView = "multiMonthYear";
        } else if (buttonId === "monthView") {
            viewType = getMonthViewType();
            storedView = "dayGridMonth";
        } else if (buttonId === "dayView") {
            viewType = "timeGridDay";
            storedView = viewType;
        } else if (buttonId === "weekView") {
            viewType = "timeGridWeek";
            storedView = viewType;
        } else {
            return false;
        }
        calendar.changeView(viewType);
        window.currentView = storedView;
        try {
            localStorage.setItem("calendarView", storedView);
        } catch (err) {}
        setCalendarTabActive(buttonId);
        return true;
    }

    function wireJalaliViewTabs() {
        if (!usesJalaliCalendar() || document.documentElement.dataset.horillaJalaliTabs === "true") {
            return;
        }
        document.documentElement.dataset.horillaJalaliTabs = "true";
        document.addEventListener(
            "click",
            function (event) {
                if (!usesJalaliCalendar()) {
                    return;
                }
                var button = event.target.closest(
                    "#yearView, #monthView, #dayView, #weekView"
                );
                if (!button || !window.calendarInstance) {
                    return;
                }
                event.preventDefault();
                event.stopImmediatePropagation();
                switchJalaliCalendarView(button.id);
            },
            true
        );
    }

    function applyCalendarPageFixes() {
        if (!document.getElementById("calendarGrid")) {
            return;
        }
        fixCalendarNavChevrons();
        fixCalendarSidebar();
        wireCalendarSidebarDropdowns();
        wireJalaliViewTabs();
        if (
            window.calendarInstance &&
            !window.calendarInstance.__horillaJalaliDecorated
        ) {
            decorateJalaliCalendarInstance(
                window.calendarInstance,
                document.getElementById("calendarGrid")
            );
        }
    }

    var JALALI_MONTH_NAMES = [
        "فروردین",
        "اردیبهشت",
        "خرداد",
        "تیر",
        "مرداد",
        "شهریور",
        "مهر",
        "آبان",
        "آذر",
        "دی",
        "بهمن",
        "اسفند",
    ];
    var JALALI_SEASON_NAMES = ["بهار", "تابستان", "پاییز", "زمستان"];

    function toPersianDigits(value) {
        return String(value).replace(/\d/g, function (digit) {
            return "۰۱۲۳۴۵۶۷۸۹".charAt(Number(digit));
        });
    }

    /** Local-midnight Date for a Shamsi day (the timeline compares local dates). */
    function jalaliPartsToLocalDate(year, month, day) {
        var parts = jalaliToGregorianParts(year, month, day);
        return new Date(parts.year, parts.month - 1, parts.day);
    }

    /** e.g. ۱۱ آبان ۱۴۰۵ */
    function formatJalaliDayMonthYear(date) {
        var parts = getJalaliPartsFromDate(date);
        return toPersianDigits(
            parts.day + " " + JALALI_MONTH_NAMES[parts.month - 1] + " " + parts.year
        );
    }

    /**
     * Calendar for the generic timeline view (timeline_view.html): Shamsi
     * month and season columns, Persian labels. Bars stay on the
     * Gregorian ISO dates the server sends.
     */
    var JALALI_TIMELINE_CALENDAR = {
        monthStart: function (date) {
            var parts = getJalaliPartsFromDate(date);
            return jalaliPartsToLocalDate(parts.year, parts.month, 1);
        },
        addMonths: function (monthStart, count) {
            var parts = getJalaliPartsFromDate(monthStart);
            var target = addJalaliMonths(parts.year, parts.month, count);
            return jalaliPartsToLocalDate(target.year, target.month, 1);
        },
        /* Quarter columns are whole seasons: Farvardin, Tir, Mehr, Dey. */
        quarterStart: function (date) {
            var parts = getJalaliPartsFromDate(date);
            var seasonMonth = Math.floor((parts.month - 1) / 3) * 3 + 1;
            return jalaliPartsToLocalDate(parts.year, seasonMonth, 1);
        },
        formatDate: function (date) {
            var parts = getJalaliPartsFromDate(date);
            return toPersianDigits(
                parts.year + "/" + padDatePart(parts.month) + "/" + padDatePart(parts.day)
            );
        },
        formatDay: function (date) {
            return toPersianDigits(getJalaliPartsFromDate(date).day);
        },
        formatMonth: function (date) {
            var parts = getJalaliPartsFromDate(date);
            return toPersianDigits(JALALI_MONTH_NAMES[parts.month - 1] + " " + parts.year);
        },
        formatWeek: function (date) {
            var parts = getJalaliPartsFromDate(date);
            return toPersianDigits(parts.day + " " + JALALI_MONTH_NAMES[parts.month - 1]);
        },
        formatQuarter: function (monthStart) {
            var parts = getJalaliPartsFromDate(monthStart);
            var season = JALALI_SEASON_NAMES[Math.floor((parts.month - 1) / 3)];
            return toPersianDigits(season + " " + parts.year);
        },
        formatRange: function (start, end) {
            return formatJalaliDayMonthYear(start) + " – " + formatJalaliDayMonthYear(end);
        },
    };

    if (usesJalaliCalendar()) {
        window.horillaTimelineCalendar = JALALI_TIMELINE_CALENDAR;
    }

    window.HorillaCalendarJalali = {
        usesJalaliCalendar: usesJalaliCalendar,
        getCalendarOptions: getCalendarOptions,
        getDayGridMonthOptions: getDayGridMonthOptions,
        getMultiMonthYearOptions: getMultiMonthYearOptions,
        getMonthViewType: getMonthViewType,
        getYearViewType: getYearViewType,
        navigateJalaliMonth: navigateJalaliMonth,
        navigateJalaliYear: navigateJalaliYear,
        formatCalendarTitle: formatCalendarTitle,
        formatJalaliDayHeaderFull: formatJalaliDayHeaderFull,
        formatDateTimeDisplay: formatDateTimeDisplay,
        formatEventDateForPopup: function (displayValue, eventDate) {
            if (displayValue) {
                return displayValue;
            }
            if (eventDate && usesJalaliCalendar()) {
                return formatDateTimeDisplay(eventDate) || eventDate.toLocaleString();
            }
            return eventDate ? eventDate.toLocaleString() : "—";
        },
        initCalendarModals: function (root) {
            if (window.initHorillaJalaliInputs) {
                window.initHorillaJalaliInputs(root || document.getElementById("modalBox") || document);
            }
        },
        updateTitleElement: updateTitleElement,
        registerPersianLocale: registerPersianLocale,
        installFullCalendarHook: installFullCalendarHook,
        applyCalendarPageFixes: applyCalendarPageFixes,
    };

    installFullCalendarHook();
    applyCalendarPageFixes();

    document.addEventListener("DOMContentLoaded", applyCalendarPageFixes);
    document.body.addEventListener("htmx:afterSettle", function (event) {
        applyCalendarPageFixes();
        if (
            window.initHorillaJalaliInputs &&
            event.detail &&
            event.detail.target &&
            event.detail.target.id === "modalBox"
        ) {
            window.initHorillaJalaliInputs(event.detail.target);
        }
    });
})(window);
