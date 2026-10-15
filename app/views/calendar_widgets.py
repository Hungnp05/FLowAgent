import html
import zlib
from datetime import date

import streamlit as st

from flowagent.agent.formatting import RECURRENCE_LABELS
from flowagent.db.models import MINUTES_PER_DAY, Priority
from flowagent.planning.calendar import (
    EN_DASH,
    SHORT_WEEKDAYS,
    Occurrence,
    month_grid_start,
)

EVENT_PALETTE = (
    ("#DCE4FF", "#0E2A6B"),
    ("#FFE0EC", "#5D1133"),
    ("#DDEFD9", "#1B4314"),
    ("#FFE3D6", "#5B1E00"),
)
PRIORITY_COLORS = {
    Priority.LOW: "#8E8A96",
    Priority.MEDIUM: "#625B71",
    Priority.HIGH: "#E65100",
    Priority.URGENT: "#B3261E",
}
PRIORITY_NAMES = {
    Priority.LOW: "Thấp",
    Priority.MEDIUM: "Trung bình",
    Priority.HIGH: "Cao",
    Priority.URGENT: "Khẩn cấp",
}
RECURRENCE_NAMES = RECURRENCE_LABELS
TODAY_COLOR = "#4F46E5"
MINI_MONTH_WEEKS = 6
CALENDAR_CSS = """
<style>
.fa-entry {display:flex; border-radius:6px; overflow:hidden; margin:2px 0; min-height:38px;}
.fa-entry-bar {width:4px; flex:none;}
.fa-entry-body {padding:3px 8px; line-height:1.25; overflow:hidden;}
.fa-entry-title {font-size:13px; font-weight:600; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis;}
.fa-entry-time {font-size:11px;}
.fa-badge {display:inline-block; color:#fff; font-size:11px; border-radius:4px; padding:1px 6px;}
.fa-chip {font-size:10px; border-radius:3px; padding:0 3px; margin-top:1px;
  white-space:nowrap; overflow:hidden;}
.fa-day-number {font-size:24px; font-weight:700; line-height:1.1;}
.fa-muted {color:#8a8a8a; font-size:12px;}
.fa-mini {width:100%; border-collapse:collapse; table-layout:fixed;}
.fa-mini td {text-align:center; font-size:9px; padding:1px 0;}
.fa-mini td span {display:inline-block; width:15px; height:15px; line-height:15px;
  border-radius:50%;}
</style>
"""


def inject_calendar_css() -> None:
    """Add the calendar's stylesheet to the page."""
    st.html(CALENDAR_CSS)


def entry_colors(key: str) -> tuple[str, str]:
    """Pick a stable background/text color pair for an entry, so it looks the same in every view."""
    return EVENT_PALETTE[zlib.crc32(key.encode()) % len(EVENT_PALETTE)]


def time_label(occurrence: Occurrence) -> str:
    """Render 'Cả ngày' or 'HH:MM-HH:MM' for an occurrence."""
    if occurrence.entry.all_day:
        return "Cả ngày"
    return f"{occurrence.start:%H:%M}{EN_DASH}{occurrence.end:%H:%M}"


def entry_html(occurrence: Occurrence) -> str:
    """Render one entry as a colored row with a priority bar on the left."""
    background, foreground = entry_colors(occurrence.entry.key)
    bar = PRIORITY_COLORS[occurrence.entry.priority]
    return (
        f'<div class="fa-entry" style="background:{background};color:{foreground}">'
        f'<div class="fa-entry-bar" style="background:{bar}"></div><div class="fa-entry-body">'
        f'<div class="fa-entry-title">{html.escape(occurrence.entry.title)}</div>'
        f'<div class="fa-entry-time">{time_label(occurrence)}</div></div></div>'
    )


def priority_badge_html(priority: Priority) -> str:
    """Render the colored priority badge used next to the Giảm / Tăng buttons."""
    color = PRIORITY_COLORS[priority]
    return f'<span class="fa-badge" style="background:{color}">{PRIORITY_NAMES[priority]}</span>'


def chip_html(occurrence: Occurrence) -> str:
    """Render a tiny title chip for month cells."""
    background, foreground = entry_colors(occurrence.entry.key)
    title = html.escape(occurrence.entry.title)
    return f'<div class="fa-chip" style="background:{background};color:{foreground}">{title}</div>'


def mini_month_html(month_start: date, days_with_entries: set[date], today: date) -> str:
    """Render a small month table where days with entries are tinted and today is filled."""
    grid_start = month_grid_start(month_start)
    header = "".join(f'<td class="fa-muted">{label}</td>' for label in SHORT_WEEKDAYS)
    rows = []
    for week in range(MINI_MONTH_WEEKS):
        cells = []
        for offset in range(7):
            day = date.fromordinal(grid_start.toordinal() + week * 7 + offset)
            cells.append(mini_day_cell(day, month_start, days_with_entries, today))
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<table class="fa-mini"><tr>{header}</tr>{"".join(rows)}</table>'


def mini_day_cell(day: date, month_start: date, days_with_entries: set[date], today: date) -> str:
    """Render one day of a mini month: blank outside the month, filled for today, tinted if busy."""
    if day.month != month_start.month:
        return "<td></td>"
    style = ""
    if day == today:
        style = f"background:{TODAY_COLOR};color:#fff"
    elif day in days_with_entries:
        style = "background:#DCE4FF"
    return f'<td><span style="{style}">{day.day}</span></td>'


def drawn_minutes(occurrence: Occurrence) -> int:
    """Return how many minutes of the day an occurrence covers in the day timeline."""
    start_minute = occurrence.start.hour * 60 + occurrence.start.minute
    return min(max(occurrence.entry.duration_minutes, 30), MINUTES_PER_DAY - start_minute)
