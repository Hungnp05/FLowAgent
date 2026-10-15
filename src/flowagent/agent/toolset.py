from langchain_core.tools import BaseTool

from flowagent.agent.tools import (
    create_event,
    create_project_plan,
    create_task,
    delete_event,
    delete_task,
    list_events,
    list_projects,
    list_tasks,
    plan_my_day,
    predict_priority,
    update_event,
    update_task,
)
from flowagent.agent.workflow_tools import (
    check_schedule,
    create_tasks_from_notes,
    progress_report,
    remember_fact,
    reschedule_tasks,
)

ALL_TOOLS: list[BaseTool] = [
    create_task,
    list_tasks,
    update_task,
    delete_task,
    plan_my_day,
    create_project_plan,
    predict_priority,
    list_projects,
    create_event,
    list_events,
    update_event,
    delete_event,
    create_tasks_from_notes,
    reschedule_tasks,
    check_schedule,
    progress_report,
    remember_fact,
]
