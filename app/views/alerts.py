from datetime import timedelta

import streamlit as st

from flowagent.agent.formatting import format_schedule_alerts
from flowagent.clock import now_local
from flowagent.db import crud
from flowagent.db.schemas import TaskFilter
from flowagent.db.session import session_scope
from flowagent.planning.alerts import ALERT_HORIZON_DAYS, find_at_risk_tasks, find_conflicts
from flowagent.schedule_queries import read_calendar_entries
from views.shared import get_engine


def render_schedule_alerts() -> None:
    """Show clashes and deadline risks for the coming week in a collapsible warning."""
    now = now_local()
    with session_scope(get_engine()) as session:
        entries = read_calendar_entries(session, include_done=False)
        open_tasks = list(crud.list_tasks(session, TaskFilter(include_done=False)))
    last_day = now.date() + timedelta(days=ALERT_HORIZON_DAYS)
    conflicts = find_conflicts(entries, now.date(), last_day)
    risks = find_at_risk_tasks(open_tasks, now)
    if not conflicts and not risks:
        return
    label = f"Cần chú ý: {len(conflicts)} lịch trùng giờ · {len(risks)} việc trễ hoặc sắp trễ"
    with st.expander(label, icon=":material/warning:"):
        st.markdown(format_schedule_alerts(conflicts, risks))
