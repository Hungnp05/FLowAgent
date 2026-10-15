from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from flowagent.db import crud
from flowagent.db.models import Project, Task
from flowagent.db.schemas import TaskFilter
from flowagent.db.session import session_scope
from flowagent.planning.scheduler import DEFAULT_TASK_MINUTES
from views.shared import STATUS_LABELS, get_engine, load_tasks

ALL_TASKS_LABEL = "Tất cả công việc"


def task_end(task: Task) -> datetime | None:
    """Return the bar end: the deadline, or start plus estimated duration when there is none."""
    if task.deadline:
        return task.deadline
    if task.planned_start is None:
        return None
    return task.planned_start + timedelta(minutes=task.estimated_minutes or DEFAULT_TASK_MINUTES)


def build_gantt_frame(tasks: list[Task]) -> pd.DataFrame:
    """Turn tasks that have a start time into the rows plotly's timeline chart expects."""
    return pd.DataFrame(
        {
            "Công việc": task.title,
            "Bắt đầu": task.planned_start,
            "Kết thúc": task_end(task),
            "Trạng thái": STATUS_LABELS[task.status],
        }
        for task in tasks
        if task.planned_start
    )


def select_project() -> Project | None:
    """Let the user pick one project, or None to show every scheduled task."""
    with session_scope(get_engine()) as session:
        projects = list(crud.list_projects(session))
    return st.selectbox(
        "Hiển thị",
        [None, *projects],
        format_func=lambda project: project.name if project else ALL_TASKS_LABEL,
    )


def render_gantt_page() -> None:
    """Render a Gantt chart for all scheduled tasks or for one selected project."""
    st.title("Biểu đồ Gantt")
    project = select_project()
    task_filter = TaskFilter(project_id=project.id) if project else None
    if project and project.goal:
        st.caption(project.goal)
    gantt_frame = build_gantt_frame(load_tasks(task_filter))
    if gantt_frame.empty:
        st.info(
            "Chưa có công việc nào có ngày bắt đầu. Hãy thêm ngày bắt đầu ở Bảng công việc"
            " hoặc nhờ trợ lý lập kế hoạch cho một mục tiêu."
        )
        return
    chart = px.timeline(
        gantt_frame, x_start="Bắt đầu", x_end="Kết thúc", y="Công việc", color="Trạng thái"
    )
    chart.update_yaxes(autorange="reversed")
    st.plotly_chart(chart, width="stretch")
