from datetime import datetime, time, timedelta

import streamlit as st

from flowagent.agent.formatting import format_datetime
from flowagent.clock import now_local
from flowagent.db import crud
from flowagent.db.models import Priority, Task, TaskStatus
from flowagent.db.schemas import TaskCreate
from flowagent.db.session import session_scope
from flowagent.errors import InvalidScheduleError
from flowagent.planning.scheduler import WORKDAY_START
from views.shared import (
    PRIORITY_LABELS,
    STATUS_LABELS,
    STATUS_ORDER,
    change_task_status,
    get_engine,
    load_tasks,
)

DUE_SOON_WINDOW = timedelta(days=1)
DEFAULT_DEADLINE_TIME = time(hour=23, minute=59)
TIME_PICKER_STEP = timedelta(minutes=15)


def render_deadline_banner(tasks: list[Task]) -> None:
    """Warn about overdue tasks and tasks due within the next day."""
    now = now_local()
    open_tasks = [task for task in tasks if task.status != TaskStatus.DONE and task.deadline]
    overdue = [task for task in open_tasks if task.deadline < now]
    due_soon = [task for task in open_tasks if now <= task.deadline <= now + DUE_SOON_WINDOW]
    if overdue:
        st.error(f"⏰ {len(overdue)} việc quá hạn: " + ", ".join(task.title for task in overdue))
    if due_soon:
        st.warning(
            f"🔔 {len(due_soon)} việc đến hạn trong 24 giờ: "
            + ", ".join(task.title for task in due_soon)
        )


def render_optional_datetime_input(label: str, default_time: time, key: str) -> datetime | None:
    """Render a checkbox-guarded date and time picker and return the chosen moment or None."""
    is_enabled = st.checkbox(label, key=f"{key}-enabled")
    date_column, time_column = st.columns(2)
    chosen_date = date_column.date_input("Ngày", value=now_local().date(), key=f"{key}-date")
    chosen_time = time_column.time_input(
        "Giờ", value=default_time, step=TIME_PICKER_STEP, key=f"{key}-time"
    )
    return datetime.combine(chosen_date, chosen_time) if is_enabled else None


def render_add_task_form() -> None:
    """Render a form for adding a task manually without the assistant."""
    with (
        st.expander("Thêm công việc", icon=":material/add:"),
        st.form("add_task", clear_on_submit=True),
    ):
        title = st.text_input("Tên công việc")
        priority = st.selectbox(
            "Độ ưu tiên", list(Priority), index=1, format_func=PRIORITY_LABELS.get
        )
        planned_start = render_optional_datetime_input("Có ngày bắt đầu", WORKDAY_START, "start")
        deadline = render_optional_datetime_input("Có hạn chót", DEFAULT_DEADLINE_TIME, "deadline")
        estimated_minutes = st.number_input("Thời lượng (phút)", min_value=0, value=60, step=15)
        if not st.form_submit_button("Thêm") or not title.strip():
            return
        task_in = TaskCreate(
            title=title.strip(),
            priority=priority,
            planned_start=planned_start,
            deadline=deadline,
            estimated_minutes=estimated_minutes or None,
        )
        try:
            with session_scope(get_engine()) as session:
                crud.create_task(session, task_in)
        except InvalidScheduleError as error:
            st.error(str(error))
            return
        st.rerun()


def format_schedule(task: Task) -> str:
    """Describe a task's start and deadline for its Kanban card."""
    deadline_text = f"hạn {format_datetime(task.deadline)}"
    if task.planned_start is None:
        return deadline_text
    return f"bắt đầu {format_datetime(task.planned_start)} · {deadline_text}"


def render_task_card(task: Task) -> None:
    """Render one Kanban card with buttons to move it between columns."""
    with st.container(border=True):
        st.markdown(f"**{task.title}**")
        st.caption(PRIORITY_LABELS[task.priority])
        st.caption(format_schedule(task))
        position = STATUS_ORDER.index(task.status)
        back_column, next_column = st.columns(2)
        if position > 0 and back_column.button("◀", key=f"back-{task.id}"):
            change_task_status(task.id, STATUS_ORDER[position - 1])
            st.rerun()
        if position < len(STATUS_ORDER) - 1 and next_column.button("▶", key=f"next-{task.id}"):
            change_task_status(task.id, STATUS_ORDER[position + 1])
            st.rerun()


def render_board_page() -> None:
    """Render the Kanban board with a deadline banner and a manual add form."""
    st.title("📋 Bảng công việc")
    tasks = load_tasks()
    render_deadline_banner(tasks)
    render_add_task_form()
    for column, status in zip(st.columns(len(STATUS_ORDER)), STATUS_ORDER, strict=True):
        column_tasks = [task for task in tasks if task.status == status]
        with column:
            st.subheader(f"{STATUS_LABELS[status]} ({len(column_tasks)})")
            for task in column_tasks:
                render_task_card(task)
