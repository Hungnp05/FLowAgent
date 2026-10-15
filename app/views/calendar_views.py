import html
from collections.abc import Callable
from datetime import date, timedelta

import streamlit as st

from flowagent.db.models import Priority, shift_priority
from flowagent.planning.calendar import (
    FULL_WEEKDAYS,
    MONTH_GRID_DAYS,
    MONTHS_PER_YEAR,
    SHORT_WEEKDAYS,
    CalendarEntry,
    Occurrence,
    assign_lanes,
    month_grid_start,
    occurrences_by_day,
    week_start,
)
from views.calendar_widgets import (
    PRIORITY_COLORS,
    TODAY_COLOR,
    chip_html,
    drawn_minutes,
    entry_colors,
    entry_html,
    mini_month_html,
    priority_badge_html,
    time_label,
)

MAX_ENTRIES_PER_WEEK_DAY = 4
MAX_CHIPS_PER_MONTH_DAY = 2
MAX_STRIP_DOTS = 3
HOUR_HEIGHT_PX = 48
TIME_LABEL_WIDTH_PX = 54
TIMELINE_VIEWPORT_PX = 620
DEFAULT_SCROLL_HOUR = 7
YEAR_GRID_COLUMNS = 3

OpenDay = Callable[[date], None]
OpenEntry = Callable[[CalendarEntry], None]
ChangePriority = Callable[[CalendarEntry, Priority], None]


def render_week_strip(days: list[date], by_day: dict, today: date, open_day: OpenDay) -> None:
    """Draw the 7-day strip; each day opens the day view and shows up to three dots."""
    for column, day in zip(st.columns(len(days)), days, strict=True):
        label = f"{SHORT_WEEKDAYS[day.weekday()]} · {day.day}"
        if column.button(
            label,
            key=f"strip-{day}",
            type="primary" if day == today else "secondary",
            width="stretch",
        ):
            open_day(day)
        dots = "•" * min(len(by_day.get(day, [])), MAX_STRIP_DOTS)
        column.markdown(
            f"<div style='text-align:center;color:{TODAY_COLOR}'>{dots or '&nbsp;'}</div>",
            unsafe_allow_html=True,
        )


def render_entry_row(
    occurrence: Occurrence, row_key: str, open_entry: OpenEntry, change_priority: ChangePriority
) -> None:
    """Draw one entry with an edit button and the Giảm [priority] Tăng stepper."""
    entry = occurrence.entry
    body, edit, lower, badge, raise_ = st.columns(
        [7, 0.8, 0.8, 1.6, 0.8], vertical_alignment="center"
    )
    body.markdown(entry_html(occurrence), unsafe_allow_html=True)
    if edit.button("", icon=":material/edit:", key=f"edit-{row_key}", help="Xem / sửa"):
        open_entry(entry)
    if lower.button(
        "",
        icon=":material/remove:",
        key=f"lower-{row_key}",
        help="Giảm ưu tiên",
        disabled=entry.priority == Priority.LOW,
    ):
        change_priority(entry, shift_priority(entry.priority, -1))
    badge.markdown(priority_badge_html(entry.priority), unsafe_allow_html=True)
    if raise_.button(
        "",
        icon=":material/add:",
        key=f"raise-{row_key}",
        help="Tăng ưu tiên",
        disabled=entry.priority == Priority.URGENT,
    ):
        change_priority(entry, shift_priority(entry.priority, 1))


def render_week_day_card(
    day: date,
    occurrences: list[Occurrence],
    is_today: bool,
    open_day: OpenDay,
    open_entry: OpenEntry,
    change_priority: ChangePriority,
) -> None:
    """Draw one day of the week list with up to four entries and a link to its day view."""
    with st.container(border=True):
        date_column, entries_column = st.columns([1, 9])
        color = TODAY_COLOR if is_today else "inherit"
        date_column.markdown(
            f"<div class='fa-muted'>{SHORT_WEEKDAYS[day.weekday()]}</div>"
            f"<div class='fa-day-number' style='color:{color}'>{day.day}</div>",
            unsafe_allow_html=True,
        )
        if date_column.button(
            "Mở",
            icon=":material/open_in_new:",
            key=f"open-{day}",
            type="tertiary",
            help="Mở lịch ngày",
        ):
            open_day(day)
        with entries_column:
            if not occurrences:
                st.markdown(
                    "<div class='fa-muted' style='padding-top:8px'>Không có lịch</div>",
                    unsafe_allow_html=True,
                )
            for index, occurrence in enumerate(occurrences[:MAX_ENTRIES_PER_WEEK_DAY]):
                render_entry_row(occurrence, f"{day}-{index}", open_entry, change_priority)
            if len(occurrences) > MAX_ENTRIES_PER_WEEK_DAY:
                st.caption(f"+{len(occurrences) - MAX_ENTRIES_PER_WEEK_DAY} lịch khác")


def render_week_view(
    anchor: date,
    entries: list[CalendarEntry],
    today: date,
    open_day: OpenDay,
    open_entry: OpenEntry,
    change_priority: ChangePriority,
) -> None:
    """Draw the week: a day strip on top and one card per day below."""
    monday = week_start(anchor)
    days = [monday + timedelta(days=offset) for offset in range(7)]
    by_day = occurrences_by_day(entries, days[0], days[-1])
    render_week_strip(days, by_day, today, open_day)
    st.divider()
    for day in days:
        render_week_day_card(
            day, by_day.get(day, []), day == today, open_day, open_entry, change_priority
        )


def render_month_cell(
    column, day: date, anchor: date, occurrences: list[Occurrence], today: date, open_day: OpenDay
) -> None:
    """Draw one month cell: a day button (filled today, faint outside the month) and title chips."""
    button_type = (
        "primary" if day == today else "secondary" if day.month == anchor.month else "tertiary"
    )
    if column.button(str(day.day), key=f"month-{day}", type=button_type, width="stretch"):
        open_day(day)
    chips = "".join(chip_html(occurrence) for occurrence in occurrences[:MAX_CHIPS_PER_MONTH_DAY])
    if len(occurrences) > MAX_CHIPS_PER_MONTH_DAY:
        chips += f"<div class='fa-chip' style='color:{TODAY_COLOR}'>+{len(occurrences) - 2}</div>"
    column.markdown(chips or "&nbsp;", unsafe_allow_html=True)


def render_month_view(
    anchor: date, entries: list[CalendarEntry], today: date, open_day: OpenDay
) -> None:
    """Draw a 6-week month grid starting on Monday."""
    grid_start = month_grid_start(anchor)
    by_day = occurrences_by_day(
        entries, grid_start, grid_start + timedelta(days=MONTH_GRID_DAYS - 1)
    )
    for column, label in zip(st.columns(7), SHORT_WEEKDAYS, strict=True):
        column.markdown(
            f"<div class='fa-muted' style='text-align:center'>{label}</div>", unsafe_allow_html=True
        )
    for week in range(MONTH_GRID_DAYS // 7):
        for column, offset in zip(st.columns(7), range(7), strict=True):
            day = grid_start + timedelta(days=week * 7 + offset)
            render_month_cell(column, day, anchor, by_day.get(day, []), today, open_day)


def render_year_view(
    year: int, entries: list[CalendarEntry], today: date, open_month: Callable[[date], None]
) -> None:
    """Draw twelve mini months; clicking a month title opens that month."""
    busy_days = set(occurrences_by_day(entries, date(year, 1, 1), date(year, 12, 31)))
    months = [date(year, month, 1) for month in range(1, MONTHS_PER_YEAR + 1)]
    for row_start in range(0, MONTHS_PER_YEAR, YEAR_GRID_COLUMNS):
        row_months = months[row_start : row_start + YEAR_GRID_COLUMNS]
        for column, month_start in zip(st.columns(YEAR_GRID_COLUMNS), row_months, strict=True):
            is_current = (month_start.year, month_start.month) == (today.year, today.month)
            if column.button(
                f"Tháng {month_start.month}",
                key=f"year-{month_start}",
                type="primary" if is_current else "secondary",
                width="stretch",
            ):
                open_month(month_start)
            column.markdown(mini_month_html(month_start, busy_days, today), unsafe_allow_html=True)


def timeline_event_html(occurrence: Occurrence, lane: int, lane_count: int) -> str:
    """Position one timed occurrence on the 24-hour timeline, in its lane."""
    start_minute = occurrence.start.hour * 60 + occurrence.start.minute
    background, foreground = entry_colors(occurrence.entry.key)
    border = PRIORITY_COLORS[occurrence.entry.priority]
    width = f"(100% - {TIME_LABEL_WIDTH_PX + 6}px) / {lane_count}"
    return (
        f'<div style="position:absolute;top:{start_minute * HOUR_HEIGHT_PX / 60}px;'
        f"left:calc({TIME_LABEL_WIDTH_PX + 2}px + {width} * {lane});width:calc({width} - 3px);"
        f"height:{drawn_minutes(occurrence) * HOUR_HEIGHT_PX / 60 - 2}px;background:{background};"
        f"color:{foreground};border:2px solid {border};border-radius:6px;padding:2px 6px;"
        f'overflow:hidden;box-sizing:border-box;font-family:sans-serif">'
        f'<div style="font-size:13px;font-weight:600">{html.escape(occurrence.entry.title)}</div>'
        f'<div style="font-size:11px">{time_label(occurrence)}</div></div>'
    )


def timeline_html(timed: list[Occurrence], now_minute: int | None) -> str:
    """Build the scrollable 24-hour grid with lane-split events and a red current-time line."""
    hour_rows = "".join(
        f'<div style="height:{HOUR_HEIGHT_PX}px;border-top:1px solid #e3e3e8;font:11px sans-serif;'
        f'color:#777;padding-left:6px">{hour:02d}:00</div>'
        for hour in range(24)
    )
    lanes = assign_lanes(timed)
    lane_count = max(lanes.values(), default=0) + 1
    events = "".join(
        timeline_event_html(occurrence, lanes[occurrence], lane_count) for occurrence in timed
    )
    now_line = ""
    if now_minute is not None:
        now_line = (
            f'<div style="position:absolute;left:{TIME_LABEL_WIDTH_PX}px;right:0;height:2px;'
            f'background:#B3261E;top:{now_minute * HOUR_HEIGHT_PX / 60}px"></div>'
        )
    scroll_hour = (
        max((now_minute or 0) // 60 - 1, 0) if now_minute is not None else DEFAULT_SCROLL_HOUR
    )
    return (
        f'<div id="fa-scroll" style="height:{TIMELINE_VIEWPORT_PX}px;overflow-y:auto">'
        f'<div style="position:relative;height:{HOUR_HEIGHT_PX * 24}px">'
        f"{hour_rows}{events}{now_line}</div></div><script>"
        f"document.getElementById('fa-scroll').scrollTop={scroll_hour * HOUR_HEIGHT_PX};</script>"
    )


def render_day_view(
    day: date,
    entries: list[CalendarEntry],
    now_minute: int | None,
    open_entry: OpenEntry,
    add_at_hour: Callable[[int], None],
) -> None:
    """Draw one day: all-day chips, the hour timeline, an entry list to edit, and quick add."""
    occurrences = occurrences_by_day(entries, day, day).get(day, [])
    all_day = [occurrence for occurrence in occurrences if occurrence.entry.all_day]
    timed = [occurrence for occurrence in occurrences if not occurrence.entry.all_day]
    if all_day:
        st.markdown(
            "<span class='fa-muted'>Cả ngày</span> "
            + "".join(chip_html(occurrence) for occurrence in all_day),
            unsafe_allow_html=True,
        )
    st.iframe(timeline_html(timed, now_minute), height=TIMELINE_VIEWPORT_PX + 10)
    hour_column, button_column, _ = st.columns([2, 2, 6], vertical_alignment="bottom")
    hour = hour_column.selectbox(
        "Khung giờ", range(24), index=9, format_func=lambda h: f"{h:02d}:00"
    )
    if button_column.button("Thêm lịch lúc này", icon=":material/add:", key="add-at-hour"):
        add_at_hour(hour)
    st.markdown(f"**Lịch trong ngày — {FULL_WEEKDAYS[day.weekday()]}**")
    if not occurrences:
        st.caption("Không có lịch")
    for index, occurrence in enumerate(occurrences):
        body, edit = st.columns([9, 1], vertical_alignment="center")
        body.markdown(entry_html(occurrence), unsafe_allow_html=True)
        if edit.button("", icon=":material/edit:", key=f"day-edit-{index}", help="Xem / sửa"):
            open_entry(occurrence.entry)
