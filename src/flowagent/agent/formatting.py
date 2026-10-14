from collections.abc import Sequence
from datetime import datetime

from flowagent.db.models import Project, Task
from flowagent.planning.scheduler import DailyPlan, PlannedTask

DISPLAY_DATETIME_FORMAT = "%Y-%m-%d %H:%M"
NO_TASKS_MESSAGE = "Không có công việc nào phù hợp."


def format_datetime(value: datetime | None) -> str:
    """Render a datetime in the format the agent and UI use, or a dash when missing."""
    return value.strftime(DISPLAY_DATETIME_FORMAT) if value else "-"


def format_task(task: Task) -> str:
    """Render a task as one compact line the LLM can read and quote back."""
    minutes = f"{task.estimated_minutes} phút" if task.estimated_minutes else "chưa ước lượng"
    return (
        f"#{task.id} | {task.title} | ưu tiên {task.priority.value} | {task.status.value}"
        f" | bắt đầu {format_datetime(task.planned_start)} | hạn {format_datetime(task.deadline)}"
        f" | {minutes}"
    )


def format_tasks(tasks: Sequence[Task]) -> str:
    """Render a list of tasks, one per line."""
    return "\n".join(format_task(task) for task in tasks) if tasks else NO_TASKS_MESSAGE


def format_projects(projects: Sequence[Project]) -> str:
    """Render a list of projects, one per line."""
    if not projects:
        return "Chưa có dự án nào."
    return "\n".join(f"#{project.id} | {project.name} | {project.goal}" for project in projects)


def format_planned_task(item: PlannedTask) -> str:
    """Render one daily-plan entry with its duration and reason."""
    return f"- #{item.task_id} {item.title} ({item.minutes} phút; {item.reason})"


def format_daily_plan(plan: DailyPlan) -> str:
    """Render a daily plan with selected and deferred tasks and their reasons."""
    if not plan.selected and not plan.deferred:
        return "Không còn công việc nào cần làm."
    lines = [f"Kế hoạch hôm nay ({plan.planned_minutes}/{plan.available_minutes} phút):"]
    lines += [format_planned_task(item) for item in plan.selected]
    if plan.deferred:
        lines.append("Để sau vì không đủ thời gian:")
        lines += [format_planned_task(item) for item in plan.deferred]
    return "\n".join(lines)
