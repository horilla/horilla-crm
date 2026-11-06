/**
 * Timeline view behaviour (bar positioning, axis, group selection).
 *
 * Loaded by timeline_view.html. The script tag carries the container id in
 * data-view-id and data-has-groups="true" when a grouped left column exists.
 * Re-runs on every HTMX swap of the timeline fragment, like the inline scripts
 * it replaces; global listeners are guarded by window flags.
 */
(function () {
  var script = document.currentScript;
  var viewId = (script && script.dataset.viewId) || "";
  var hasGroups = !!script && script.dataset.hasGroups === "true";

  if (hasGroups) {
  (function () {
      if (window._timelineGroupSelectDelegation) return;
      window._timelineGroupSelectDelegation = true;

      function setActiveGroup(container, index) {
          var blocks = container.querySelectorAll(".js-timeline-group-block");
          var rows = container.querySelectorAll(".js-timeline-left-group");
          var activeIndex = parseInt(index, 10);

          if (isNaN(activeIndex) || activeIndex < 0) {
              activeIndex = 0;
          }

          blocks.forEach(function (block, i) {
              block.style.display = i === activeIndex ? "" : "none";
          });

          rows.forEach(function (row, i) {
              if (i === activeIndex) {
                  row.classList.add("text-primary-600");
                  row.classList.remove("text-slate-600", "dark:text-slate-400");
              } else {
                  row.classList.remove("text-primary-600");
                  if (!row.classList.contains("text-slate-600")) {
                      row.classList.add("text-slate-600", "dark:text-slate-400");
                  }
              }
          });
      }

      document.addEventListener("click", function (e) {
          var leftRow = e.target.closest(".js-timeline-left-group");
          if (!leftRow) return;

          var container = leftRow.closest(".js-timeline-container");
          if (!container) return;

          var index = leftRow.getAttribute("data-group-index");
          if (index === null) return;

          setActiveGroup(container, index);
      });

      document.addEventListener("DOMContentLoaded", function () {
          var container = document.getElementById(viewId);
          if (!container) return;
          setActiveGroup(container, 0);
      });
  })();
  }

  (function () {
      /* Tailwind classes for injected nodes — must appear in source so purge keeps them (dark: variants for theme) */
      var TL = {
          /* Grid lines use mainSession palette (secondary) — bg stays white; only line colour matches session */
          /* Neutral gray grid — secondary-* follows brand (red); gray matches Ubuntu-like subtle lines */
          gridLine:
              "timeline-grid-line pointer-events-none absolute top-0 bottom-0 w-px bg-gray-200 dark:bg-gray-600",
          gridLinePct:
              "timeline-grid-line pointer-events-none absolute top-0 bottom-0 w-px bg-gray-200 dark:bg-gray-600",
          /* timeline-axis-* classes + timeline-view.css — cross-OS parity (Windows = Ubuntu-like) */
          daySpan:
              "timeline-axis-cell box-border border-l border-gray-200 dark:border-gray-600 text-center py-0.5 px-0.5 flex flex-col justify-start bg-white dark:bg-gray-950",
          dayMonth:
              "timeline-axis-day-month leading-tight whitespace-nowrap overflow-hidden text-ellipsis",
          dayNum: "timeline-axis-day-num leading-tight",
          weekSpan:
              "timeline-axis-cell shrink-0 box-border text-center py-1.5 px-0.5 leading-tight overflow-hidden text-ellipsis whitespace-nowrap bg-white dark:bg-gray-950 border-l border-gray-200 dark:border-gray-600 flex items-center justify-center",
          monthSpan:
              "flex-1 min-w-[96px] text-center py-0 px-1.5 box-border border-l border-gray-200 dark:border-gray-600",
          quarterSpan:
              "flex-1 min-w-[120px] text-center py-0 px-1.5 box-border border-l border-gray-200 dark:border-gray-600",
      };

      function fmtYmd(d) {
          return (
              d.getFullYear() +
              "-" +
              String(d.getMonth() + 1).padStart(2, "0") +
              "-" +
              String(d.getDate()).padStart(2, "0")
          );
      }

      /**
       * Calendar behind the axis: where month/quarter columns start and how
       * every label reads. Gregorian by default. A calendar extension sets
       * window.horillaTimelineCalendar to override any of these keys; bars
       * keep the Gregorian ISO dates the server sends.
       */
      var GREGORIAN_CALENDAR = {
          monthStart: function (d) {
              return new Date(d.getFullYear(), d.getMonth(), 1);
          },
          addMonths: function (monthStart, count) {
              return new Date(monthStart.getFullYear(), monthStart.getMonth() + count, 1);
          },
          /* First quarter column starts at the range's first month */
          quarterStart: function (d) {
              return this.monthStart(d);
          },
          formatDate: fmtYmd,
          formatDay: function (d) {
              return d.getDate();
          },
          formatMonth: function (d) {
              return d.toLocaleDateString(undefined, {
                  month: "short",
                  year: "numeric",
              });
          },
          formatWeek: function (d) {
              return d.getDate() + " " + d.toLocaleDateString(undefined, { month: "short" });
          },
          formatQuarter: function (monthStart) {
              var quarter = Math.floor(monthStart.getMonth() / 3) + 1;
              return "Q" + quarter + " " + monthStart.getFullYear().toString().slice(-2);
          },
          /* (start, end) -> header text; null keeps the server-rendered range */
          formatRange: null,
      };

      function getTimelineCalendar() {
          return Object.assign({}, GREGORIAN_CALENDAR, window.horillaTimelineCalendar || {});
      }

      function positionTimelineBars(viewId) {
          var track = document.getElementById("timeline-track-" + viewId);
          var axisLabels = document.getElementById("timeline-axis-labels-" + viewId);
          if (!track || !axisLabels) return;

          function clearTimelineWidths() {
              var ids = [
                  "timeline-axis-" + viewId,
                  "timeline-axis-underline-" + viewId,
                  "timeline-inner-" + viewId,
                  "timeline-track-" + viewId,
                  "timeline-axis-labels-" + viewId,
                  "timeline-grid-" + viewId,
              ];

              ids.forEach(function (id) {
                  var el = document.getElementById(id);
                  if (!el) return;
                  el.style.minWidth = "";
                  el.style.width = "";
              });
          }

          clearTimelineWidths();

          function parseYmdLocal(ymd) {
              if (!ymd || typeof ymd !== "string") return null;
              var part = ymd.split("T")[0];
              var p = part.split("-");
              if (p.length !== 3) return null;

              var y = parseInt(p[0], 10);
              var m = parseInt(p[1], 10) - 1;
              var d = parseInt(p[2], 10);
              if (isNaN(y) || isNaN(m) || isNaN(d)) return null;

              return new Date(y, m, d, 0, 0, 0, 0);
          }

          function exclusiveEndAfterLastDay(ymdLocalMidnight) {
              if (!ymdLocalMidnight) return null;
              var x = new Date(ymdLocalMidnight.getTime());
              x.setDate(x.getDate() + 1);
              return x;
          }

          var cal = getTimelineCalendar();
          var rangeStartDate = parseYmdLocal(track.dataset.rangeStart || "");
          var rangeEndDate = parseYmdLocal(track.dataset.rangeEnd || "");

          if (!rangeStartDate || !rangeEndDate || rangeEndDate < rangeStartDate) {
              var t = new Date();
              rangeStartDate = new Date(t.getFullYear(), t.getMonth(), t.getDate() - 90, 0, 0, 0, 0);
              rangeEndDate = new Date(t.getFullYear(), t.getMonth(), t.getDate() + 30, 0, 0, 0, 0);
          } else if (cal.formatRange) {
              var rangeLabel = document.getElementById("timeline-range-label-" + viewId);
              if (rangeLabel) {
                  rangeLabel.textContent = cal.formatRange(rangeStartDate, rangeEndDate);
              }
          }

          var rangeStart = rangeStartDate;
          var rangeEndExclusive = exclusiveEndAfterLastDay(rangeEndDate);
          var totalMs = rangeEndExclusive - rangeStart;
          if (totalMs <= 0) return;

          var scale = track.dataset.scale || "months";
          var dayMs = 24 * 60 * 60 * 1000;
          var totalDays = Math.max(1, Math.round(totalMs / dayMs));

          /* RTL: the axis row runs right to left, so bars and grid lines are offset from the right */
          var isRtl = getComputedStyle(track).direction === "rtl";
          var startEdge = isRtl ? "right" : "left";

          var DAY_COL_PX = 56;
          var WEEK_COL_PX = 120;
          var MONTH_MIN_PX = 96;

          function countDaysInclusive(startD, endD) {
              var n = 0;
              var d = new Date(startD.getFullYear(), startD.getMonth(), startD.getDate());
              var end = new Date(endD.getFullYear(), endD.getMonth(), endD.getDate());

              while (d <= end) {
                  n++;
                  d.setDate(d.getDate() + 1);
              }

              return Math.max(1, n);
          }

          var rangeEndInclusiveForCount = new Date(rangeEndExclusive.getTime());
          rangeEndInclusiveForCount.setDate(rangeEndInclusiveForCount.getDate() - 1);

          var axisTotalPx;
          var usePixelBars = false;
          var weekColPx = WEEK_COL_PX;
          var weekColumnLayout = null;

          if (scale === "days") {
              var dayCountForAxis = countDaysInclusive(rangeStart, rangeEndInclusiveForCount);
              var nominalDayPx = dayCountForAxis * DAY_COL_PX;
              var scrollElDay = document.getElementById("timeline-scroll-" + viewId);
              var viewportWDay = scrollElDay ? scrollElDay.clientWidth : 0;
              if (viewportWDay < 80 && scrollElDay) {
                  viewportWDay = scrollElDay.getBoundingClientRect().width;
              }

              /* Few days → stretch to viewport so no empty strip at right (same as weeks/months/quarters) */
              axisTotalPx = viewportWDay > nominalDayPx ? viewportWDay : nominalDayPx;
              usePixelBars = true;
          } else if (scale === "weeks") {
              var w0 = new Date(
                  rangeStart.getFullYear(),
                  rangeStart.getMonth(),
                  rangeStart.getDate()
              );
              var wEnd = new Date(
                  rangeEndInclusiveForCount.getFullYear(),
                  rangeEndInclusiveForCount.getMonth(),
                  rangeEndInclusiveForCount.getDate()
              );
              var weekCount = 0;
              var ws = new Date(w0.getTime());

              while (ws <= wEnd) {
                  weekCount++;
                  ws.setDate(ws.getDate() + 7);
              }

              weekCount = Math.max(weekCount, 1);

              var scrollElWeek = document.getElementById("timeline-scroll-" + viewId);
              var viewportW = scrollElWeek ? scrollElWeek.clientWidth : 0;
              if (viewportW < 80 && scrollElWeek) {
                  viewportW = scrollElWeek.getBoundingClientRect().width;
              }

              var nominalWeekPx = weekCount * WEEK_COL_PX;
              axisTotalPx = viewportW > nominalWeekPx ? viewportW : nominalWeekPx;
              weekColPx = axisTotalPx / weekCount;
              usePixelBars = true;

              /**
               * Week columns: same as axis — equal width per week bucket from rangeStart, +7 days each.
               * Bars must use this layout or linear time misaligns (same class of bug as months).
               */
              weekColumnLayout = [];

              var wStartBuild = new Date(
                  rangeStart.getFullYear(),
                  rangeStart.getMonth(),
                  rangeStart.getDate()
              );
              var rangeEndInclusiveWBuild = new Date(
                  rangeEndInclusiveForCount.getFullYear(),
                  rangeEndInclusiveForCount.getMonth(),
                  rangeEndInclusiveForCount.getDate()
              );
              var wkBuild = 0;
              var wsCount = new Date(wStartBuild.getTime());

              while (wsCount <= rangeEndInclusiveWBuild) {
                  wkBuild++;
                  wsCount.setDate(wsCount.getDate() + 7);
              }

              wkBuild = Math.max(wkBuild, 1);

              var baseWBuild = Math.floor(axisTotalPx / wkBuild);
              var remWBuild = axisTotalPx - baseWBuild * wkBuild;
              var cumWBuild = 0;
              wStartBuild = new Date(
                  rangeStart.getFullYear(),
                  rangeStart.getMonth(),
                  rangeStart.getDate()
              );
              var wiBuild = 0;

              while (wStartBuild <= rangeEndInclusiveWBuild) {
                  var wEndBuild = new Date(
                      wStartBuild.getFullYear(),
                      wStartBuild.getMonth(),
                      wStartBuild.getDate() + 6
                  );
                  if (wEndBuild > rangeEndInclusiveWBuild) {
                      wEndBuild = new Date(rangeEndInclusiveWBuild.getTime());
                  }

                  var colWB = baseWBuild + (wiBuild < remWBuild ? 1 : 0);
                  var spanDaysW = countDaysInclusive(wStartBuild, wEndBuild);
                  weekColumnLayout.push({
                      start: new Date(wStartBuild.getTime()),
                      end: new Date(wEndBuild.getTime()),
                      left: cumWBuild,
                      width: colWB,
                      spanDays: spanDaysW,
                  });

                  cumWBuild += colWB;
                  wStartBuild.setDate(wStartBuild.getDate() + 7);
                  wiBuild++;
              }
          } else if (scale === "quarters") {
              var qCount = 0;
              var qq = cal.quarterStart(rangeStart);
              var qEnd = cal.monthStart(rangeEndInclusiveForCount);

              while (qq <= qEnd) {
                  qCount++;
                  qq = cal.addMonths(qq, 3);
              }

              qCount = Math.max(qCount, 1);

              var QUARTER_COL_PX = 120;
              var nominalQPx = qCount * QUARTER_COL_PX;
              var scrollElQ = document.getElementById("timeline-scroll-" + viewId);
              var viewportWQ = scrollElQ ? scrollElQ.clientWidth : 0;
              if (viewportWQ < 80 && scrollElQ) {
                  viewportWQ = scrollElQ.getBoundingClientRect().width;
              }

              /* Few quarters → stretch to viewport so no empty strip at right (same as weeks) */
              axisTotalPx = viewportWQ > nominalQPx ? viewportWQ : nominalQPx;
              usePixelBars = true;
          } else {
              var mm = cal.monthStart(rangeStart);
              var mEnd = cal.monthStart(rangeEndInclusiveForCount);
              var monthCount = 0;

              while (mm <= mEnd) {
                  monthCount++;
                  mm = cal.addMonths(mm, 1);
              }

              monthCount = Math.max(monthCount, 1);

              var nominalMPx = monthCount * MONTH_MIN_PX;
              var scrollElM = document.getElementById("timeline-scroll-" + viewId);
              var viewportWM = scrollElM ? scrollElM.clientWidth : 0;
              if (viewportWM < 80 && scrollElM) {
                  viewportWM = scrollElM.getBoundingClientRect().width;
              }

              axisTotalPx = viewportWM > nominalMPx ? viewportWM : nominalMPx;
              usePixelBars = true;
          }

          /**
           * Months (and quarters) axis uses equal-width columns per calendar month/quarter.
           * Bar geometry must use the same coordinate system — linear time ratios would place
           * e.g. March 11 under February because February has fewer days but equal column width.
           */
          var monthColumnLayout = null;
          var quarterColumnLayout = null;

          if (scale === "months" && usePixelBars && axisTotalPx > 0) {
              monthColumnLayout = [];
              var mBuild = cal.monthStart(rangeStart);
              var rangeEndInclusiveMBuild = new Date(rangeEndExclusive.getTime());
              rangeEndInclusiveMBuild.setDate(rangeEndInclusiveMBuild.getDate() - 1);
              var mkBuild = 0;
              var mCount = mBuild;

              while (mCount <= rangeEndInclusiveMBuild) {
                  mkBuild++;
                  mCount = cal.addMonths(mCount, 1);
              }

              mkBuild = Math.max(mkBuild, 1);

              var baseMBuild = Math.floor(axisTotalPx / mkBuild);
              var remMBuild = axisTotalPx - baseMBuild * mkBuild;
              var cumMBuild = 0;

              while (mBuild <= rangeEndInclusiveMBuild) {
                  var colMB = baseMBuild + (monthColumnLayout.length < remMBuild ? 1 : 0);
                  var nextMB = cal.addMonths(mBuild, 1);

                  monthColumnLayout.push({
                      start: mBuild,
                      end: nextMB,
                      left: cumMBuild,
                      width: colMB,
                      daysInMonth: Math.round((nextMB - mBuild) / dayMs),
                  });

                  cumMBuild += colMB;
                  mBuild = nextMB;
              }
          }

          if (scale === "quarters" && usePixelBars && axisTotalPx > 0) {
              quarterColumnLayout = [];
              var qBuild = cal.quarterStart(rangeStart);
              var rangeEndInclusiveQBuild = new Date(rangeEndExclusive.getTime());
              rangeEndInclusiveQBuild.setDate(rangeEndInclusiveQBuild.getDate() - 1);
              var qkBuild = 0;
              var qCount = qBuild;

              while (qCount <= rangeEndInclusiveQBuild) {
                  qkBuild++;
                  qCount = cal.addMonths(qCount, 3);
              }

              qkBuild = Math.max(qkBuild, 1);

              var baseQBuild = Math.floor(axisTotalPx / qkBuild);
              var remQBuild = axisTotalPx - baseQBuild * qkBuild;
              var cumQBuild = 0;

              while (qBuild <= rangeEndInclusiveQBuild) {
                  var colQB = baseQBuild + (quarterColumnLayout.length < remQBuild ? 1 : 0);
                  var nextQB = cal.addMonths(qBuild, 3);
                  var qDays = Math.max(1, Math.round((nextQB - qBuild) / dayMs));

                  quarterColumnLayout.push({
                      start: qBuild,
                      end: nextQB,
                      left: cumQBuild,
                      width: colQB,
                      daysApprox: qDays,
                  });

                  cumQBuild += colQB;
                  qBuild = nextQB;
              }
          }

          /* Column holding d, and d's 0-based day index inside it */
          function findMonthColumn(d) {
              for (var i = 0; i < monthColumnLayout.length; i++) {
                  var c = monthColumnLayout[i];
                  if (d >= c.start && d < c.end) {
                      return { column: c, dayIndex: Math.round((d - c.start) / dayMs) };
                  }
              }
              return null;
          }

          function dateToPxMonths(d) {
              if (!monthColumnLayout || monthColumnLayout.length === 0) return null;

              var hit = findMonthColumn(d);
              if (hit) {
                  return hit.column.left + (hit.dayIndex / hit.column.daysInMonth) * hit.column.width;
              }

              var first = monthColumnLayout[0];
              if (d < first.start) return first.left;

              var last = monthColumnLayout[monthColumnLayout.length - 1];
              return last.left + last.width;
          }

          function dateToPxQuarters(d) {
              if (!quarterColumnLayout || quarterColumnLayout.length === 0) return null;

              for (var i = 0; i < quarterColumnLayout.length; i++) {
                  var c = quarterColumnLayout[i];

                  if (d >= c.start && d < c.end) {
                      var daysFromStart = Math.max(
                          0,
                          Math.round((d - c.start) / dayMs)
                      );
                      return c.left + (daysFromStart / c.daysApprox) * c.width;
                  }
              }

              var lastQ = quarterColumnLayout[quarterColumnLayout.length - 1];
              return lastQ.left + lastQ.width;
          }

          function dateToPxWeeks(d) {
              if (!weekColumnLayout || weekColumnLayout.length === 0) return null;

              var d0 = new Date(d.getFullYear(), d.getMonth(), d.getDate());

              for (var i = 0; i < weekColumnLayout.length; i++) {
                  var seg = weekColumnLayout[i];
                  var s0 = new Date(
                      seg.start.getFullYear(),
                      seg.start.getMonth(),
                      seg.start.getDate()
                  );
                  var e0 = new Date(
                      seg.end.getFullYear(),
                      seg.end.getMonth(),
                      seg.end.getDate()
                  );

                  if (d0 >= s0 && d0 <= e0) {
                      var n = countDaysInclusive(s0, d0);
                      var span = Math.max(1, seg.spanDays);
                      return seg.left + ((n - 1) / span) * seg.width;
                  }
              }

              var firstW = weekColumnLayout[0];
              if (
                  d0 <
                  new Date(
                      firstW.start.getFullYear(),
                      firstW.start.getMonth(),
                      firstW.start.getDate()
                  )
              ) {
                  return firstW.left;
              }

              var lastW = weekColumnLayout[weekColumnLayout.length - 1];
              return lastW.left + lastW.width;
          }

          function setBarGeometry(bar, start, endExclusive) {
              var leftPx;
              var widthPx;

              if (scale === "weeks" && weekColumnLayout && weekColumnLayout.length > 0) {
                  var startPxW = dateToPxWeeks(start);
                  if (startPxW == null) startPxW = 0;

                  var endDateInclusiveW = new Date(endExclusive.getTime());
                  endDateInclusiveW.setDate(endDateInclusiveW.getDate() - 1);
                  if (endDateInclusiveW < start) {
                      endDateInclusiveW = new Date(start.getTime());
                  }

                  var d0e = new Date(
                      endDateInclusiveW.getFullYear(),
                      endDateInclusiveW.getMonth(),
                      endDateInclusiveW.getDate()
                  );
                  var endPxW = dateToPxWeeks(endDateInclusiveW);

                  for (var iw = 0; iw < weekColumnLayout.length; iw++) {
                      var segw = weekColumnLayout[iw];
                      var s0e = new Date(
                          segw.start.getFullYear(),
                          segw.start.getMonth(),
                          segw.start.getDate()
                      );
                      var e0e = new Date(
                          segw.end.getFullYear(),
                          segw.end.getMonth(),
                          segw.end.getDate()
                      );

                      if (d0e >= s0e && d0e <= e0e) {
                          var nEnd = countDaysInclusive(s0e, d0e);
                          var spanEnd = Math.max(1, segw.spanDays);
                          endPxW = segw.left + (nEnd / spanEnd) * segw.width;
                          break;
                      }
                  }

                  leftPx = startPxW;
                  widthPx = Math.max(endPxW - leftPx, 0);
              } else if (
                  scale === "months" &&
                  monthColumnLayout &&
                  monthColumnLayout.length > 0
              ) {
                  var startPx = dateToPxMonths(start);
                  if (startPx == null) startPx = 0;

                  var endDateInclusive = new Date(endExclusive.getTime());
                  endDateInclusive.setDate(endDateInclusive.getDate() - 1);
                  if (endDateInclusive < start) {
                      endDateInclusive = new Date(start.getTime());
                  }

                  var endPx = dateToPxMonths(endDateInclusive);
                  var endHit = findMonthColumn(endDateInclusive);
                  if (endHit) {
                      endPx =
                          endHit.column.left +
                          ((endHit.dayIndex + 1) / endHit.column.daysInMonth) *
                              endHit.column.width;
                  }

                  leftPx = startPx;
                  widthPx = Math.max(endPx - leftPx, 0);
              } else if (
                  scale === "quarters" &&
                  quarterColumnLayout &&
                  quarterColumnLayout.length > 0
              ) {
                  var startPxQ = dateToPxQuarters(start);
                  var endDateInclusiveQ = new Date(endExclusive.getTime());
                  endDateInclusiveQ.setDate(endDateInclusiveQ.getDate() - 1);
                  if (endDateInclusiveQ < start) {
                      endDateInclusiveQ = new Date(start.getTime());
                  }

                  var endPxQ = dateToPxQuarters(endDateInclusiveQ);
                  endPxQ += (1 / 96) * (axisTotalPx / quarterColumnLayout.length);
                  leftPx = startPxQ;
                  widthPx = Math.max(endPxQ - leftPx, 0);
              } else {
                  var leftRatio = (start - rangeStart) / totalMs;
                  var widthRatio = (endExclusive - start) / totalMs;
                  if (widthRatio < 0) widthRatio = 0;
                  if (leftRatio < 0) {
                      widthRatio += leftRatio;
                      leftRatio = 0;
                  }
                  if (leftRatio + widthRatio > 1) {
                      widthRatio = 1 - leftRatio;
                  }

                  leftPx = leftRatio * axisTotalPx;
                  widthPx = widthRatio * axisTotalPx;
              }

              if (usePixelBars && axisTotalPx > 0) {
                  /* Weeks: readable min; months/quarters: min so label can show */
                  var minPx;
                  if (scale === "weeks") {
                      minPx = Math.max(20, Math.round(weekColPx / 6));
                  } else if (scale === "days") {
                      minPx = Math.max(
                          20,
                          Math.round(axisTotalPx / Math.max(totalDays, 1) / 6)
                      );
                  } else if (scale === "months" || scale === "quarters") {
                      minPx = Math.max(56, Math.round(axisTotalPx / 80));
                  } else {
                      minPx = 3;
                  }

                  if (widthPx < minPx) widthPx = minPx;
                  bar.style[startEdge] = leftPx + "px";
                  bar.style.width = widthPx + "px";
              } else {
                  var leftRatio2 = (start - rangeStart) / totalMs;
                  var widthRatio2 = (endExclusive - start) / totalMs;
                  if (widthRatio2 < 0) widthRatio2 = 0;
                  if (leftRatio2 < 0) {
                      widthRatio2 += leftRatio2;
                      leftRatio2 = 0;
                  }
                  if (leftRatio2 + widthRatio2 > 1) {
                      widthRatio2 = 1 - leftRatio2;
                  }

                  var leftPct = leftRatio2 * 100;
                  var widthPct = Math.max(widthRatio2 * 100, 0.5);
                  if (widthPct < 3) widthPct = 3;
                  bar.style[startEdge] = leftPct + "%";
                  bar.style.width = widthPct + "%";
              }
          }

          var bars = track.querySelectorAll(".timeline-bar");
          bars.forEach(function (bar) {
              var start = parseYmdLocal(bar.dataset.start || "");
              var endDateInner = parseYmdLocal(bar.dataset.end || "");

              if (!start) start = rangeStart;
              if (!endDateInner) endDateInner = start;
              if (endDateInner < start) endDateInner = start;

              var endExclusive = exclusiveEndAfterLastDay(endDateInner);
              setBarGeometry(bar, start, endExclusive);
          });

          var axisHtml = "";
          var gridHtml = "";

          if (scale === "days") {
              /* Collect each day in range, then equal-width columns so stretched layout aligns with bars */
              var dayLabels = [];
              var d = new Date(
                  rangeStart.getFullYear(),
                  rangeStart.getMonth(),
                  rangeStart.getDate()
              );
              var rangeEndInclusive = new Date(
                  rangeEndInclusiveForCount.getFullYear(),
                  rangeEndInclusiveForCount.getMonth(),
                  rangeEndInclusiveForCount.getDate()
              );
              var prevMonthStart = null;

              while (d <= rangeEndInclusive) {
                  var monthStartTime = cal.monthStart(d).getTime();
                  var showMonth = monthStartTime !== prevMonthStart;
                  prevMonthStart = monthStartTime;

                  var monthLine = showMonth ? cal.formatMonth(d) : "\u00a0";

                  dayLabels.push({
                      title: cal.formatDate(d),
                      monthLine: monthLine,
                      dayNum: cal.formatDay(d),
                  });

                  d.setDate(d.getDate() + 1);
              }

              var dk = dayLabels.length;
              if (dk === 0) {
                  dayLabels.push({ title: "", monthLine: "\u00a0", dayNum: "" });
                  dk = 1;
              }

              var baseD = Math.floor(axisTotalPx / dk);
              var remD = axisTotalPx - baseD * dk;
              var cumD = 0;

              for (var di = 0; di < dk; di++) {
                  var colW = baseD + (di < remD ? 1 : 0);
                  gridHtml +=
                      '<div class="' +
                      TL.gridLine +
                      '" style="' +
                      startEdge +
                      ":" +
                      cumD +
                      'px"></div>';

                  var dl = dayLabels[di];
                  axisHtml +=
                      '<span class="' +
                      TL.daySpan +
                      '" style="flex:0 0 ' +
                      colW +
                      "px;width:" +
                      colW +
                      "px;min-width:" +
                      colW +
                      "px;max-width:" +
                      colW +
                      'px" title="' +
                      dl.title +
                      '">' +
                      '<div class="' +
                      TL.dayMonth +
                      '">' +
                      dl.monthLine +
                      "</div>" +
                      '<div class="' +
                      TL.dayNum +
                      '">' +
                      dl.dayNum +
                      "</div>" +
                      "</span>";

                  cumD += colW;
              }

              gridHtml +=
                  '<div class="' +
                  TL.gridLine +
                  '" style="' +
                  startEdge +
                  ":" +
                  cumD +
                  'px"></div>';
              axisLabels.classList.add("flex-nowrap", "items-stretch");
          } else if (scale === "weeks") {
              var wStart = new Date(
                  rangeStart.getFullYear(),
                  rangeStart.getMonth(),
                  rangeStart.getDate()
              );
              var rangeEndInclusiveW = new Date(
                  rangeEndInclusiveForCount.getFullYear(),
                  rangeEndInclusiveForCount.getMonth(),
                  rangeEndInclusiveForCount.getDate()
              );
              var weekLabels = [];

              while (wStart <= rangeEndInclusiveW) {
                  var wEnd = new Date(
                      wStart.getFullYear(),
                      wStart.getMonth(),
                      wStart.getDate() + 6
                  );
                  if (wEnd > rangeEndInclusiveW) {
                      wEnd = new Date(rangeEndInclusiveW.getTime());
                  }

                  var label = cal.formatWeek(wStart);
                  var titleRange = cal.formatDate(wStart) + " – " + cal.formatDate(wEnd);

                  weekLabels.push({ label: label, title: titleRange });
                  wStart.setDate(wStart.getDate() + 7);
              }

              var wk = weekLabels.length;
              if (wk === 0) {
                  weekLabels.push({ label: "\u00a0", title: "" });
                  wk = 1;
              }

              var baseW = Math.floor(axisTotalPx / wk);
              var rem = axisTotalPx - baseW * wk;
              var cum = 0;

              for (var wi = 0; wi < wk; wi++) {
                  var colW2 = baseW + (wi < rem ? 1 : 0);
                  gridHtml +=
                      '<div class="' +
                      TL.gridLine +
                      '" style="' +
                      startEdge +
                      ":" +
                      cum +
                      'px"></div>';

                  var wl = weekLabels[wi];
                  axisHtml +=
                      '<span class="' +
                      TL.weekSpan +
                      '" style="flex:0 0 ' +
                      colW2 +
                      "px;width:" +
                      colW2 +
                      "px;min-width:" +
                      colW2 +
                      "px;max-width:" +
                      colW2 +
                      'px" title="' +
                      wl.title +
                      '">' +
                      wl.label +
                      "</span>";

                  cum += colW2;
              }

              gridHtml +=
                  '<div class="' +
                  TL.gridLine +
                  '" style="' +
                  startEdge +
                  ":" +
                  cum +
                  'px"></div>';
              axisLabels.classList.add("flex-nowrap", "items-stretch");
          } else if (scale === "quarters") {
              var QUARTER_COL_PX2 = 120;
              var qLabels = [];
              var q = cal.quarterStart(rangeStart);
              var rangeEndInclusiveQ = new Date(rangeEndExclusive.getTime());
              rangeEndInclusiveQ.setDate(rangeEndInclusiveQ.getDate() - 1);

              while (q <= rangeEndInclusiveQ) {
                  qLabels.push(cal.formatQuarter(q));
                  q = cal.addMonths(q, 3);
              }

              if (qLabels.length === 0) qLabels.push("\u00a0");

              var qk = qLabels.length;
              var baseQ = Math.floor(axisTotalPx / qk);
              var remQ = axisTotalPx - baseQ * qk;
              var cumQ = 0;

              for (var qi = 0; qi < qk; qi++) {
                  var colQ = baseQ + (qi < remQ ? 1 : 0);
                  gridHtml +=
                      '<div class="' +
                      TL.gridLine +
                      '" style="' +
                      startEdge +
                      ":" +
                      cumQ +
                      'px"></div>';
                  axisHtml +=
                      '<span class="' +
                      TL.weekSpan +
                      '" style="flex:0 0 ' +
                      colQ +
                      "px;width:" +
                      colQ +
                      "px;min-width:" +
                      colQ +
                      "px;max-width:" +
                      colQ +
                      'px">' +
                      qLabels[qi] +
                      "</span>";
                  cumQ += colQ;
              }

              gridHtml +=
                  '<div class="' +
                  TL.gridLine +
                  '" style="' +
                  startEdge +
                  ":" +
                  cumQ +
                  'px"></div>';
              axisLabels.classList.add("flex-nowrap", "items-stretch");
          } else {
              /* Months: equal-width columns + pixel grid — header lines align with body (same as weeks) */
              var monthLabels = [];
              var mInner = cal.monthStart(rangeStart);
              var rangeEndInclusiveM = new Date(rangeEndExclusive.getTime());
              rangeEndInclusiveM.setDate(rangeEndInclusiveM.getDate() - 1);

              while (mInner <= rangeEndInclusiveM) {
                  monthLabels.push(cal.formatMonth(mInner));
                  mInner = cal.addMonths(mInner, 1);
              }

              if (monthLabels.length === 0) monthLabels.push("\u00a0");

              var mk = monthLabels.length;
              var baseM = Math.floor(axisTotalPx / mk);
              var remM = axisTotalPx - baseM * mk;
              var cumM = 0;

              for (var mi = 0; mi < mk; mi++) {
                  var colM = baseM + (mi < remM ? 1 : 0);
                  gridHtml +=
                      '<div class="' +
                      TL.gridLine +
                      '" style="' +
                      startEdge +
                      ":" +
                      cumM +
                      'px"></div>';
                  axisHtml +=
                      '<span class="' +
                      TL.weekSpan +
                      '" style="flex:0 0 ' +
                      colM +
                      "px;width:" +
                      colM +
                      "px;min-width:" +
                      colM +
                      "px;max-width:" +
                      colM +
                      'px">' +
                      monthLabels[mi] +
                      "</span>";
                  cumM += colM;
              }

              gridHtml +=
                  '<div class="' +
                  TL.gridLine +
                  '" style="' +
                  startEdge +
                  ":" +
                  cumM +
                  'px"></div>';
              axisLabels.classList.add("flex-nowrap", "items-stretch");
          }

          axisLabels.innerHTML = axisHtml;
          axisLabels.classList.add("flex");

          if (
              scale !== "days" &&
              scale !== "weeks" &&
              scale !== "months" &&
              scale !== "quarters"
          ) {
              axisLabels.classList.remove("flex-nowrap", "items-stretch");
          }

          var innerEl = document.getElementById("timeline-inner-" + viewId);
          if (usePixelBars && axisTotalPx > 0) {
              axisLabels.style.minWidth = axisTotalPx + "px";
              axisLabels.style.width = axisTotalPx + "px";

              var axisSticky = document.getElementById("timeline-axis-" + viewId);
              if (axisSticky) {
                  axisSticky.style.minWidth = axisTotalPx + "px";
                  axisSticky.style.width = axisTotalPx + "px";
              }

              var axisUnderline = document.getElementById(
                  "timeline-axis-underline-" + viewId
              );
              if (axisUnderline) {
                  axisUnderline.style.width = axisTotalPx + "px";
                  axisUnderline.style.minWidth = axisTotalPx + "px";
              }

              if (innerEl) {
                  innerEl.style.minWidth = axisTotalPx + "px";
                  innerEl.style.width = axisTotalPx + "px";
              }

              track.style.minWidth = axisTotalPx + "px";
              track.style.width = axisTotalPx + "px";
          } else {
              axisLabels.style.minWidth = "";
              axisLabels.style.width = "";

              var axisStickyClear = document.getElementById(
                  "timeline-axis-" + viewId
              );
              if (axisStickyClear) {
                  axisStickyClear.style.minWidth = "";
                  axisStickyClear.style.width = "";
              }

              var axisUnderlineClear = document.getElementById(
                  "timeline-axis-underline-" + viewId
              );
              if (axisUnderlineClear) {
                  axisUnderlineClear.style.width = "";
                  axisUnderlineClear.style.minWidth = "";
              }

              var trackWidthFallback = Math.max(totalDays * 10, 800);

              if (axisStickyClear) {
                  axisStickyClear.style.minWidth = trackWidthFallback + "px";
              }

              if (axisUnderlineClear) {
                  axisUnderlineClear.style.width = trackWidthFallback + "px";
                  axisUnderlineClear.style.minWidth = trackWidthFallback + "px";
              }

              if (innerEl) {
                  innerEl.style.minWidth = trackWidthFallback + "px";
                  innerEl.style.width = "";
              }

              track.style.minWidth = trackWidthFallback + "px";
              track.style.width = "";
          }

          var gridEl = document.getElementById("timeline-grid-" + viewId);
          if (gridEl) {
              gridEl.innerHTML = gridHtml;
              if (usePixelBars && axisTotalPx > 0) {
                  gridEl.style.width = axisTotalPx + "px";
                  gridEl.style.minWidth = axisTotalPx + "px";
              } else {
                  /* Month/quarter bars use % — grid must fill track width or % lines collapse */
                  gridEl.style.width = "100%";
                  gridEl.style.minWidth = "100%";
              }

              function sizeGridToTrack() {
                  var h = track.scrollHeight || track.offsetHeight;
                  if (h > 0) gridEl.style.minHeight = h + "px";
              }

              sizeGridToTrack();
              requestAnimationFrame(function () {
                  sizeGridToTrack();
                  setTimeout(sizeGridToTrack, 0);
              });
          }

          var scrollElForRetry = document.getElementById(
              "timeline-scroll-" + viewId
          );
          if (scrollElForRetry && scrollElForRetry.clientWidth < 80) {
              [0, 50, 150, 300, 600].forEach(function (ms) {
                  setTimeout(function () {
                      positionTimelineBars(viewId);
                  }, ms);
              });
          }

          var scrollEl = document.getElementById("timeline-scroll-" + viewId);
          /* RTL scrollLeft is 0 at the right edge and negative towards the left */
          var scrollSign = isRtl ? -1 : 1;
          if (scrollEl) {
              if (usePixelBars && axisTotalPx > 0) {
                  var earliestLeftPx = axisTotalPx;
                  bars.forEach(function (bar) {
                      var leftStr = bar.style[startEdge] || "";
                      if (leftStr.indexOf("px") !== -1) {
                          var leftPx = parseFloat(leftStr);
                          if (!isNaN(leftPx) && leftPx < earliestLeftPx) {
                              earliestLeftPx = leftPx;
                          }
                      } else {
                          var leftPct2 = parseFloat(leftStr);
                          if (!isNaN(leftPct2)) {
                              var leftPx2 = (leftPct2 / 100) * axisTotalPx;
                              if (leftPx2 < earliestLeftPx) {
                                  earliestLeftPx = leftPx2;
                              }
                          }
                      }
                  });

                  scrollEl.scrollLeft = scrollSign * Math.max(earliestLeftPx - 40, 0);
              } else {
                  var trackWidthFallback2 = Math.max(totalDays * 10, 800);
                  var earliestLeftPct = 100;

                  bars.forEach(function (bar) {
                      var leftStr = (bar.style[startEdge] || "").replace("%", "");
                      var leftVal = parseFloat(leftStr);
                      if (!isNaN(leftVal) && leftVal < earliestLeftPct) {
                          earliestLeftPct = leftVal;
                      }
                  });

                  scrollEl.scrollLeft =
                      scrollSign *
                      Math.max((earliestLeftPct / 100) * trackWidthFallback2 - 40, 0);
              }
          }
      }

          if (document.readyState === "complete") {
          setTimeout(function () {
              positionTimelineBars(viewId);
          }, 0);
      } else {
          window.addEventListener("load", function () {
              setTimeout(function () {
                  positionTimelineBars(viewId);
              }, 0);
          });
      }

      if (
          typeof document.body.addEventListener === "function" &&
          !window._timelineBarPositionRegistered
      ) {
          window._timelineBarPositionRegistered = true;
          document.body.addEventListener("htmx:afterSwap", function (evt) {
              var target = evt.detail && evt.detail.target;
              if (!target) return;

              var container =
                  target.classList &&
                  target.classList.contains("js-timeline-container")
                      ? target
                      : typeof target.querySelector === "function"
                        ? target.querySelector(".js-timeline-container")
                        : null;

              if (!container || !container.id) return;

              var cid = container.id;
              positionTimelineBars(cid);
              [0, 50, 150, 300].forEach(function (ms) {
                  setTimeout(function () {
                      positionTimelineBars(cid);
                  }, ms);
              });
          });
      }
  })();
})();
