import csv
import io
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from flowagent.db.models import Project, Recurrence, ScheduleEvent, Task, TaskStatus
from flowagent.planning.calendar import (
    CalendarEntry,
    EntrySource,
    build_calendar_entries,
)

ICS_LINE_LIMIT_BYTES = 75
ICS_DATETIME_FORMAT = "%Y%m%dT%H%M%SZ"
ICS_DATE_FORMAT = "%Y%m%d"
ICS_UID_DOMAIN = "flowagent"
RRULE_FREQUENCIES = {
    Recurrence.DAILY: "DAILY",
    Recurrence.WEEKLY: "WEEKLY",
    Recurrence.MONTHLY: "MONTHLY",
    Recurrence.YEARLY: "YEARLY",
}
CSV_ENCODING = "utf-8-sig"
CSV_COLUMNS = (
    "id",
    "title",
    "description",
    "project",
    "status",
    "priority",
    "planned_start",
    "deadline",
    "estimated_minutes",
    "completed_at",
)
CSV_DATETIME_FORMAT = "%Y-%m-%d %H:%M"


def escape_ics_text(text: str) -> str:
    """Escape backslashes, commas, semicolons and newlines as iCalendar text requires."""
    escaped = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return escaped.replace("\r\n", "\\n").replace("\n", "\\n")


def fold_ics_line(line: str) -> str:
    """Split a content line into 75-byte pieces joined by CRLF and a space."""
    pieces, current = [], ""
    for character in line:
        if len((current + character).encode("utf-8")) > ICS_LINE_LIMIT_BYTES:
            pieces.append(current)
            current = " "
        current += character
    return "\r\n".join([*pieces, current])


def to_utc_stamp(moment: datetime, zone: ZoneInfo) -> str:
    """Format a naive local time in the given zone as a UTC iCalendar timestamp."""
    return moment.replace(tzinfo=zone).astimezone(UTC).strftime(ICS_DATETIME_FORMAT)


def entry_time_lines(entry: CalendarEntry, zone: ZoneInfo) -> list[str]:
    """Return the DTSTART/DTEND lines: whole dates for all-day entries, UTC times otherwise."""
    if entry.all_day:
        next_day = entry.start + timedelta(days=1)
        return [
            f"DTSTART;VALUE=DATE:{entry.start:{ICS_DATE_FORMAT}}",
            f"DTEND;VALUE=DATE:{next_day:{ICS_DATE_FORMAT}}",
        ]
    end = entry.start + timedelta(minutes=entry.duration_minutes)
    return [f"DTSTART:{to_utc_stamp(entry.start, zone)}", f"DTEND:{to_utc_stamp(end, zone)}"]


def entry_alarm_lines(entry: CalendarEntry) -> list[str]:
    """Return a display alarm for timed events, mirroring the app's reminder offset."""
    if entry.source != EntrySource.EVENT or entry.all_day:
        return []
    return [
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{escape_ics_text(entry.title)}",
        f"TRIGGER:-PT{entry.reminder_minutes}M",
        "END:VALARM",
    ]


def entry_to_vevent(entry: CalendarEntry, stamp: str, zone: ZoneInfo) -> list[str]:
    """Render one calendar entry as the lines of a VEVENT block."""
    lines = [
        "BEGIN:VEVENT",
        f"UID:{entry.key.replace('#', '-')}@{ICS_UID_DOMAIN}",
        f"DTSTAMP:{stamp}",
        *entry_time_lines(entry, zone),
        f"SUMMARY:{escape_ics_text(entry.title)}",
    ]
    if entry.note:
        lines.append(f"DESCRIPTION:{escape_ics_text(entry.note)}")
    if entry.recurrence in RRULE_FREQUENCIES:
        lines.append(f"RRULE:FREQ={RRULE_FREQUENCIES[entry.recurrence]}")
    return [*lines, *entry_alarm_lines(entry), "END:VEVENT"]


def build_ics(
    events: Iterable[ScheduleEvent], tasks: Iterable[Task], now: datetime, timezone: str
) -> str:
    """Export events and open tasks as an .ics file that Google Calendar and Outlook can import."""
    zone = ZoneInfo(timezone)
    open_tasks = [task for task in tasks if task.status != TaskStatus.DONE]
    stamp = to_utc_stamp(now, zone)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//FlowAgent//VI", "CALSCALE:GREGORIAN"]
    for entry in build_calendar_entries(events, open_tasks):
        lines += entry_to_vevent(entry, stamp, zone)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_ics_line(line) for line in lines) + "\r\n"


def format_csv_datetime(moment: datetime | None) -> str:
    """Render an optional datetime for a spreadsheet cell."""
    return moment.strftime(CSV_DATETIME_FORMAT) if moment else ""


def task_to_csv_row(task: Task, project_names: dict[int, str]) -> list[str | int]:
    """Turn a task into one spreadsheet row in CSV_COLUMNS order."""
    return [
        task.id or 0,
        task.title,
        task.description,
        project_names.get(task.project_id or 0, ""),
        task.status.value,
        task.priority.value,
        format_csv_datetime(task.planned_start),
        format_csv_datetime(task.deadline),
        task.estimated_minutes or "",
        format_csv_datetime(task.completed_at),
    ]


def build_tasks_csv(tasks: Iterable[Task], projects: Sequence[Project]) -> bytes:
    """Export tasks as UTF-8 CSV with a BOM so Excel, Sheets, Notion and Trello read accents."""
    project_names = {project.id or 0: project.name for project in projects}
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    writer.writerows(task_to_csv_row(task, project_names) for task in tasks)
    return buffer.getvalue().encode(CSV_ENCODING)
