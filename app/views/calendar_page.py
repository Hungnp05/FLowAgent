from datetime import date, datetime, time, timedelta

import streamlit as st
from pydantic import ValidationError

from flowagent.agent.formatting import format_datetime
from flowagent.clock import now_local
from flowagent.db import crud
from flowagent.db.models import MINUTES_PER_DAY, Priority, Recurrence, ScheduleEvent, TaskStatus
from flowagent.db.schemas import ScheduleEventCreate, TaskUpdate
from flowagent.db.session import session_scope
from flowagent.planning.calendar import (
    CalendarEntry,
    CalendarMode,
    EntrySource,
    period_label,
    reminder_time,
    shift_anchor,
    upcoming_reminders,
)
from flowagent.schedule_queries import read_calendar_entries
from views.alerts import render_schedule_alerts
from views.calendar_views import (
    render_day_view,
    render_month_view,
    render_week_view,
    render_year_view,
)
from views.calendar_widgets import (
    PRIORITY_NAMES,
    RECURRENCE_NAMES,
    inject_calendar_css,
    priority_badge_html,
    time_label,
)
from views.shared import STATUS_LABELS, get_engine

MODE_KEY, ANCHOR_KEY, RETURN_MODE_KEY = "calendar_mode", "calendar_anchor", "calendar_return_mode"
MODE_LABELS = {CalendarMode.WEEK: "Tuần", CalendarMode.MONTH: "Tháng", CalendarMode.YEAR: "Năm"}
REMINDER_OPTIONS = {
    0: "Đúng giờ",
    5: "Trước 5 phút",
    15: "Trước 15 phút",
    30: "Trước 30 phút",
    60: "Trước 1 giờ",
    1440: "Trước 1 ngày",
}
REMINDER_HORIZON = timedelta(hours=24)
MAX_REMINDERS_SHOWN = 5
DEFAULT_START = time(hour=9)
LAST_MINUTE = time(hour=23, minute=59)
FORM_KEY_PREFIX = "event-form-"
DIALOG_KEY = "calendar_dialog"


def init_calendar_state() -> None:
    """Start on the current week the first time the page opens."""
    st.session_state.setdefault(MODE_KEY, CalendarMode.WEEK)
    st.session_state.setdefault(ANCHOR_KEY, now_local().date())
    st.session_state.setdefault(RETURN_MODE_KEY, CalendarMode.WEEK)


def set_view(mode: CalendarMode, anchor: date) -> None:
    """Switch the calendar to a mode and anchor date, then redraw."""
    st.session_state[MODE_KEY], st.session_state[ANCHOR_KEY] = mode, anchor
    st.rerun()


def open_day(day: date) -> None:
    """Open the day view, remembering which view to return to."""
    if st.session_state[MODE_KEY] != CalendarMode.DAY:
        st.session_state[RETURN_MODE_KEY] = st.session_state[MODE_KEY]
    set_view(CalendarMode.DAY, day)


def close_day() -> None:
    """Leave the day view and go back to the week, month or year it was opened from."""
    set_view(st.session_state[RETURN_MODE_KEY], st.session_state[ANCHOR_KEY])


def load_calendar_entries() -> list[CalendarEntry]:
    """Read calendar events and tasks and turn them into drawable entries."""
    with session_scope(get_engine()) as session:
        return read_calendar_entries(session)


def change_entry_priority(entry: CalendarEntry, priority: Priority) -> None:
    """Save a new priority on the underlying event or task, as the Giảm / Tăng buttons do."""
    with session_scope(get_engine()) as session:
        if entry.source == EntrySource.TASK:
            crud.update_task(session, entry.source_id, TaskUpdate(priority=priority))
        else:
            crud.change_event_priority(session, entry.source_id, priority)
    st.rerun()


def clear_form_state() -> None:
    """Forget the editor's widget values so the next dialog starts from the event's data."""
    for key in [key for key in st.session_state if str(key).startswith(FORM_KEY_PREFIX)]:
        del st.session_state[key]


def read_event_form(event: ScheduleEvent | None, day: date, start: time) -> dict:
    """Render the editor fields and return the values the user entered."""
    form = FORM_KEY_PREFIX
    values = {
        "title": st.text_input("Tiêu đề", event.title if event else "", key=f"{form}title"),
        "note": st.text_area(
            "Ghi chú (địa điểm, phòng...)",
            event.note if event else "",
            height=68,
            key=f"{form}note",
        ),
        "day": st.date_input(
            "Ngày", event.start_at.date() if event else day, format="DD/MM/YYYY", key=f"{form}day"
        ),
        "all_day": st.toggle("Cả ngày", event.all_day if event else False, key=f"{form}all_day"),
    }
    if not values["all_day"]:
        default_start = event.start_at.time() if event else start
        default_end = (
            datetime.combine(day, default_start)
            + timedelta(minutes=event.duration_minutes if event else 60)
        ).time()
        start_column, end_column = st.columns(2)
        values["start"] = start_column.time_input(
            "Bắt đầu", default_start, step=300, key=f"{form}start"
        )
        values["end"] = end_column.time_input(
            "Kết thúc",
            min(default_end, LAST_MINUTE) if default_end > default_start else LAST_MINUTE,
            step=300,
            key=f"{form}end",
        )
    values.update(read_event_choices(event, values["all_day"]))
    return values


def read_event_choices(event: ScheduleEvent | None, is_all_day: bool) -> dict:
    """Render the recurrence, reminder and priority pills and return the selections."""
    form = FORM_KEY_PREFIX
    recurrence = st.pills(
        "Lặp lại",
        list(Recurrence),
        format_func=RECURRENCE_NAMES.get,
        default=event.recurrence if event else Recurrence.NONE,
        key=f"{form}recurrence",
    )
    if is_all_day:
        st.caption("Thông báo lúc 07:00 sáng ngày diễn ra")
        reminder = 0
    else:
        reminder = st.pills(
            "Thông báo",
            list(REMINDER_OPTIONS),
            format_func=REMINDER_OPTIONS.get,
            default=event.reminder_minutes if event else 0,
            key=f"{form}reminder",
        )
    priority = st.pills(
        "Độ ưu tiên",
        list(Priority),
        format_func=PRIORITY_NAMES.get,
        default=event.priority if event else Priority.MEDIUM,
        key=f"{form}priority",
    )
    if event and event.recurrence != Recurrence.NONE:
        st.caption("Thay đổi áp dụng cho mọi lần lặp của lịch này")
    return {
        "recurrence": recurrence or Recurrence.NONE,
        "reminder": reminder or 0,
        "priority": priority or Priority.MEDIUM,
    }


def build_event(values: dict) -> ScheduleEventCreate:
    """Turn the form values into a validated event, raising ValueError with a Vietnamese message."""
    if not values["title"].strip():
        raise ValueError("Hãy nhập tiêu đề")
    if values["all_day"]:
        start_at, duration = datetime.combine(values["day"], time.min), MINUTES_PER_DAY
    else:
        start_at = datetime.combine(values["day"], values["start"])
        duration = int(
            (datetime.combine(values["day"], values["end"]) - start_at).total_seconds() // 60
        )
        if duration <= 0:
            raise ValueError("Giờ kết thúc phải sau giờ bắt đầu")
    return ScheduleEventCreate(
        title=values["title"].strip(),
        note=values["note"].strip(),
        start_at=start_at,
        duration_minutes=duration,
        all_day=values["all_day"],
        recurrence=values["recurrence"],
        reminder_minutes=values["reminder"],
        priority=values["priority"],
    )


def save_event(event: ScheduleEvent | None, values: dict) -> None:
    """Create or overwrite the event from the form, showing validation errors inline."""
    try:
        event_in = build_event(values)
    except (ValueError, ValidationError) as error:
        st.error(str(error).splitlines()[0])
        return
    with session_scope(get_engine()) as session:
        if event:
            crud.replace_event(session, event.id, event_in)
        else:
            crud.create_event(session, event_in)
    close_dialog()
    st.rerun()


def event_editor(event: ScheduleEvent | None, day: date, start: time) -> None:
    """Show the add/edit form with Lưu, Xóa and Hủy actions."""
    values = read_event_form(event, day, start)
    save_column, delete_column, cancel_column = st.columns(3)
    if save_column.button("Lưu", icon=":material/save:", type="primary", width="stretch"):
        save_event(event, values)
    if event and delete_column.button("Xóa", icon=":material/delete:", width="stretch"):
        with session_scope(get_engine()) as session:
            crud.delete_event(session, event.id)
        close_dialog()
        st.rerun()
    if cancel_column.button("Hủy", icon=":material/close:", width="stretch"):
        close_dialog()
        st.rerun()


def close_dialog() -> None:
    """Forget which dialog is open and the values typed into it."""
    st.session_state.pop(DIALOG_KEY, None)
    clear_form_state()


def open_dialog(**dialog: object) -> None:
    """Remember a dialog to show, so it stays open across the reruns its buttons trigger."""
    clear_form_state()
    st.session_state[DIALOG_KEY] = dialog
    st.rerun()


def open_event_editor(event_id: int | None, day: date, start: time = DEFAULT_START) -> None:
    """Open the add dialog (no id) or the edit dialog for an event."""
    open_dialog(kind="event", event_id=event_id, day=day, start=start)


@st.dialog("Thêm lịch trình", width="large", on_dismiss=close_dialog)
def add_event_dialog(day: date, start: time) -> None:
    """Dialog for adding a new calendar event."""
    event_editor(None, day, start)


@st.dialog("Sửa lịch trình", width="large", on_dismiss=close_dialog)
def edit_event_dialog(event_id: int) -> None:
    """Dialog for editing or deleting an existing calendar event."""
    with session_scope(get_engine()) as session:
        event = crud.get_event(session, event_id)
    event_editor(event, event.start_at.date(), event.start_at.time())


def task_details(task_id: int) -> None:
    """Show a task opened from the calendar, with a shortcut to mark it done."""
    with session_scope(get_engine()) as session:
        task = crud.get_task(session, task_id)
    st.markdown(f"### {task.title}")
    st.markdown(
        priority_badge_html(task.priority) + f" &nbsp; {STATUS_LABELS[task.status]}",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"Bắt đầu: {format_datetime(task.planned_start)}  \nHạn: {format_datetime(task.deadline)}"
        f"  \nThời lượng: {task.estimated_minutes or '-'} phút"
    )
    if task.description:
        st.caption(task.description)
    st.caption("Sửa chi tiết ở trang Bảng công việc hoặc nhờ Trợ lý.")
    if task.status != TaskStatus.DONE and st.button(
        "Đánh dấu hoàn thành", icon=":material/check_circle:", type="primary"
    ):
        with session_scope(get_engine()) as session:
            crud.update_task(session, task_id, TaskUpdate(status=TaskStatus.DONE))
        close_dialog()
        st.rerun()


@st.dialog("Công việc", on_dismiss=close_dialog)
def task_dialog(task_id: int) -> None:
    """Dialog showing a task that was clicked on the calendar."""
    task_details(task_id)


def render_open_dialog() -> None:
    """Show whichever dialog is remembered in the session, if any."""
    dialog = st.session_state.get(DIALOG_KEY)
    if dialog is None:
        return
    if dialog["kind"] == "task":
        task_dialog(dialog["task_id"])
    elif dialog["event_id"] is None:
        add_event_dialog(dialog["day"], dialog["start"])
    else:
        edit_event_dialog(dialog["event_id"])


def open_entry(entry: CalendarEntry) -> None:
    """Open a task's details or an event's editor, depending on where the entry came from."""
    if entry.source == EntrySource.TASK:
        open_dialog(kind="task", task_id=entry.source_id)
    else:
        open_event_editor(entry.source_id, entry.start.date())


def render_header(mode: CalendarMode, anchor: date) -> None:
    """Draw the mode switch (or back button), Hôm nay, add button and the period navigator."""
    switch_column, today_column, add_column = st.columns([5, 1.2, 2], vertical_alignment="center")
    if mode == CalendarMode.DAY:
        if switch_column.button("Quay lại", icon=":material/arrow_back:"):
            close_day()
    else:
        selected = switch_column.segmented_control(
            "Chế độ xem",
            list(MODE_LABELS),
            default=mode,
            format_func=MODE_LABELS.get,
            label_visibility="collapsed",
        )
        if selected and selected != mode:
            set_view(selected, anchor)
    if today_column.button("Hôm nay", icon=":material/today:", width="stretch"):
        set_view(mode, now_local().date())
    if add_column.button("Thêm lịch trình", icon=":material/add:", type="primary", width="stretch"):
        open_event_editor(None, anchor)
    previous_column, label_column, next_column = st.columns([1, 8, 1], vertical_alignment="center")
    if previous_column.button(
        "", icon=":material/chevron_left:", key="period-previous", help="Trước", width="stretch"
    ):
        set_view(mode, shift_anchor(mode, anchor, -1))
    label_column.markdown(
        f"<h4 style='text-align:center;margin:0'>{period_label(mode, anchor)}</h4>",
        unsafe_allow_html=True,
    )
    if next_column.button(
        "", icon=":material/chevron_right:", key="period-next", help="Sau", width="stretch"
    ):
        set_view(mode, shift_anchor(mode, anchor, 1))


def render_reminders(entries: list[CalendarEntry], now: datetime) -> None:
    """List events whose reminder falls within the next 24 hours, replacing phone notifications."""
    upcoming = upcoming_reminders(entries, now, REMINDER_HORIZON)[:MAX_REMINDERS_SHOWN]
    if upcoming:
        lines = [
            f"**{occurrence.start:%d/%m %H:%M}** · {occurrence.entry.title} "
            f"({time_label(occurrence)}, nhắc lúc {reminder_time(occurrence):%H:%M})"
            for occurrence in upcoming
        ]
        st.info(
            "**Sắp tới trong 24 giờ**  \n" + "  \n".join(lines), icon=":material/notifications:"
        )


def render_calendar_page() -> None:
    """Render the schedule page with week, month, year and day views like MobiAssistant."""
    st.title("Lịch trình")
    inject_calendar_css()
    init_calendar_state()
    mode, anchor, now = st.session_state[MODE_KEY], st.session_state[ANCHOR_KEY], now_local()
    render_header(mode, anchor)
    entries = load_calendar_entries()
    render_reminders(entries, now)
    render_schedule_alerts()
    if mode == CalendarMode.WEEK:
        render_week_view(anchor, entries, now.date(), open_day, open_entry, change_entry_priority)
    elif mode == CalendarMode.MONTH:
        render_month_view(anchor, entries, now.date(), open_day)
    elif mode == CalendarMode.YEAR:
        render_year_view(
            anchor.year,
            entries,
            now.date(),
            lambda month_start: set_view(CalendarMode.MONTH, month_start),
        )
    else:
        now_minute = now.hour * 60 + now.minute if anchor == now.date() else None
        render_day_view(
            anchor,
            entries,
            now_minute,
            open_entry,
            lambda hour: open_event_editor(None, anchor, time(hour=hour)),
        )
    render_open_dialog()
