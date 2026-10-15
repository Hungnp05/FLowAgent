from collections.abc import Sequence
from datetime import datetime

from flowagent.db.models import Project, Recurrence, ScheduleEvent, Task
from flowagent.planning.alerts import Conflict, RiskKind, TaskRisk
from flowagent.planning.calendar import EN_DASH, Occurrence
from flowagent.planning.progress import ProgressReport, ReportPeriod
from flowagent.planning.scheduler import DailyPlan, PlannedTask, TimelinePlan, TimeSlot

DISPLAY_DATETIME_FORMAT = "%Y-%m-%d %H:%M"
NO_TASKS_MESSAGE = "Không có công việc nào phù hợp."
NO_EVENTS_MESSAGE = "Không có lịch trình nào phù hợp."
NO_ALERTS_MESSAGE = "Không có lịch trùng giờ và không có việc nào có nguy cơ trễ hạn."
EMPTY_SECTION = "- (không có)"
MINUTES_PER_HOUR = 60
PERIOD_NAMES = {ReportPeriod.DAY: "hôm nay", ReportPeriod.WEEK: "tuần này"}
RECURRENCE_LABELS = {
    Recurrence.NONE: "Không lặp",
    Recurrence.DAILY: "Hằng ngày",
    Recurrence.WEEKLY: "Hằng tuần",
    Recurrence.MONTHLY: "Hằng tháng",
    Recurrence.YEARLY: "Hằng năm",
}


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


def format_event(event: ScheduleEvent) -> str:
    """Render a calendar event as one compact line the LLM can read and quote back."""
    when = (
        f"{event.start_at:%Y-%m-%d} (cả ngày)"
        if event.all_day
        else (f"{format_datetime(event.start_at)} ({event.duration_minutes} phút)")
    )
    return (
        f"#{event.id} | {event.title} | {when} | lặp: {RECURRENCE_LABELS[event.recurrence]}"
        f" | nhắc trước {event.reminder_minutes} phút | ưu tiên {event.priority.value}"
    )


def format_events(events: Sequence[ScheduleEvent]) -> str:
    """Render a list of calendar events, one per line."""
    return "\n".join(format_event(event) for event in events) if events else NO_EVENTS_MESSAGE


def format_occurrence(occurrence: Occurrence) -> str:
    """Render an occurrence as its title and clock range."""
    return f"'{occurrence.entry.title}' {occurrence.start:%H:%M}{EN_DASH}{occurrence.end:%H:%M}"


def format_conflict(conflict: Conflict) -> str:
    """Render one clash between two calendar entries."""
    return (
        f"- {conflict.first.start:%Y-%m-%d}: {format_occurrence(conflict.first)} "
        f"trùng với {format_occurrence(conflict.second)}"
    )


def format_risk(risk: TaskRisk) -> str:
    """Render why a task is overdue or likely to miss its deadline."""
    task = risk.task
    if risk.kind == RiskKind.OVERDUE:
        return f"- #{task.id} {task.title}: đã quá hạn từ {format_datetime(task.deadline)}"
    return (
        f"- #{task.id} {task.title}: cần {task.estimated_minutes} phút nhưng chỉ còn "
        f"{risk.work_minutes_left} phút làm việc trước hạn {format_datetime(task.deadline)}"
    )


def format_schedule_alerts(conflicts: Sequence[Conflict], risks: Sequence[TaskRisk]) -> str:
    """Render schedule clashes and deadline risks, or say that everything looks fine."""
    if not conflicts and not risks:
        return NO_ALERTS_MESSAGE
    lines = []
    if conflicts:
        lines += ["Lịch trùng giờ:", *(format_conflict(conflict) for conflict in conflicts)]
    if risks:
        lines += ["Việc trễ hoặc có nguy cơ trễ hạn:", *(format_risk(risk) for risk in risks)]
    return "\n".join(lines)


def format_conflict_note(conflicts: Sequence[Conflict]) -> str:
    """Append a warning about clashes to a create or update confirmation, if there are any."""
    if not conflicts:
        return ""
    return "\nTrùng giờ (cần xem lại):\n" + "\n".join(
        format_conflict(conflict) for conflict in conflicts
    )


def format_reschedule(changes: Sequence[tuple[Task, TimeSlot]]) -> str:
    """Render each task's old and new start and deadline."""
    return "\n".join(
        f"- #{task.id} {task.title}: bắt đầu {format_datetime(task.planned_start)} -> "
        f"{format_datetime(slot.start)}, hạn {format_datetime(task.deadline)} -> "
        f"{format_datetime(slot.end)}"
        for task, slot in changes
    )


def format_deadline_fit(plan: TimelinePlan, finish_by: datetime | None) -> str:
    """Explain how many hours a day the plan needs, or warn that it misses the target date."""
    if finish_by is None or not plan.slots:
        return ""
    hours_per_day = plan.daily_work_minutes / MINUTES_PER_HOUR
    if not plan.fits_deadline:
        return (
            f"\nCảnh báo: không kịp hạn {format_datetime(finish_by)}: "
            f"dù làm {hours_per_day:g} giờ/ngày vẫn xong lúc "
            f"{format_datetime(plan.slots[-1].end)}. Nên bớt bước hoặc lùi hạn."
        )
    return f"\nĐể kịp hạn {format_datetime(finish_by)}: làm {hours_per_day:g} giờ/ngày."


def format_report_section(title: str, lines: Sequence[str]) -> list[str]:
    """Render one titled section of the progress report."""
    return [f"### {title}", *(lines or [EMPTY_SECTION]), ""]


def format_progress_report(report: ProgressReport) -> str:
    """Render the progress report as Markdown for the chat, a download or an email."""
    period = PERIOD_NAMES[report.period]
    lines = [
        f"## Báo cáo tiến độ {period} ({report.period_start:%d/%m}"
        f"{EN_DASH}{report.generated_at:%d/%m/%Y})",
        f"- Đã hoàn thành: {len(report.completed)} (đúng hạn {report.on_time_count})",
        f"- Đang làm: {len(report.in_progress)}",
        f"- Trễ hạn: {len(report.overdue)}",
        f"- Đến hạn trong 7 ngày tới: {len(report.upcoming)}",
        f"- Việc mới tạo {period}: {report.created_count}",
        "",
    ]
    lines += format_report_section(
        "Đã hoàn thành",
        [
            f"- {task.title} (xong {format_datetime(task.completed_at)})"
            for task in report.completed
        ],
    )
    lines += format_report_section("Đang làm", [f"- {task.title}" for task in report.in_progress])
    lines += format_report_section(
        "Trễ hạn",
        [f"- {task.title} (hạn {format_datetime(task.deadline)})" for task in report.overdue],
    )
    lines += format_report_section(
        "Sắp đến hạn",
        [f"- {task.title} (hạn {format_datetime(task.deadline)})" for task in report.upcoming],
    )
    return "\n".join(lines).strip()
