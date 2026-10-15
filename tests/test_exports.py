import csv
import io
from datetime import datetime

from flowagent.db.models import Project, Recurrence, ScheduleEvent, Task, TaskStatus
from flowagent.exports import CSV_COLUMNS, build_ics, build_tasks_csv, fold_ics_line
from tests.conftest import FIXED_NOW

TIMEZONE = "Asia/Ho_Chi_Minh"


def unfold(ics_text: str) -> list[str]:
    """Undo iCalendar line folding and split the text into content lines."""
    return ics_text.replace("\r\n ", "").split("\r\n")


def test_ics_exports_recurring_event_in_utc_with_alarm() -> None:
    """A daily 18:00 gym session becomes an 11:00 UTC event with RRULE and a reminder."""
    gym = ScheduleEvent(
        id=7,
        title="Tập gym, chân",
        start_at=datetime(2026, 10, 15, 18, 0),
        duration_minutes=90,
        recurrence=Recurrence.DAILY,
        reminder_minutes=15,
    )
    lines = unfold(build_ics([gym], [], FIXED_NOW, TIMEZONE))
    assert "DTSTART:20261015T110000Z" in lines
    assert "DTEND:20261015T123000Z" in lines
    assert "RRULE:FREQ=DAILY" in lines
    assert "TRIGGER:-PT15M" in lines
    assert "SUMMARY:Tập gym\\, chân" in lines
    assert "UID:event:7@flowagent" in lines


def test_ics_exports_all_day_event_and_skips_done_tasks() -> None:
    """All-day events use whole dates; finished tasks are left out."""
    holiday = ScheduleEvent(id=1, title="Nghỉ lễ", start_at=datetime(2026, 10, 20), all_day=True)
    open_task = Task(id=2, title="Viết báo cáo", deadline=datetime(2026, 10, 21, 23, 59))
    done_task = Task(id=3, title="Đã xong", deadline=datetime(2026, 10, 21), status=TaskStatus.DONE)
    lines = unfold(build_ics([holiday], [open_task, done_task], FIXED_NOW, TIMEZONE))
    assert "DTSTART;VALUE=DATE:20261020" in lines
    assert "DTEND;VALUE=DATE:20261021" in lines
    assert any("Viết báo cáo" in line for line in lines)
    assert not any("Đã xong" in line for line in lines)


def test_fold_ics_line_keeps_lines_within_75_bytes() -> None:
    """Long Vietnamese summaries are folded without splitting a UTF-8 character."""
    folded = fold_ics_line("SUMMARY:" + "Chuẩn bị tài liệu họp " * 10)
    assert all(len(part.encode("utf-8")) <= 75 for part in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == "SUMMARY:" + "Chuẩn bị tài liệu họp " * 10


def test_tasks_csv_has_bom_header_and_project_name() -> None:
    """The CSV opens in Excel with accents intact and names each task's project."""
    project = Project(id=1, name="Website", goal="Bán hàng")
    task = Task(id=5, title="Thiết kế giao diện", project_id=1, estimated_minutes=120)
    data = build_tasks_csv([task], [project])
    assert data.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    assert tuple(rows[0]) == CSV_COLUMNS
    assert rows[1][:4] == ["5", "Thiết kế giao diện", "", "Website"]


def test_ics_escapes_line_breaks_in_notes() -> None:
    """A multi-line note stays on one DESCRIPTION line with escaped breaks."""
    meeting = ScheduleEvent(
        id=1, title="Họp", note="Phòng A\nTầng 2", start_at=datetime(2026, 10, 15, 9)
    )
    lines = unfold(build_ics([meeting], [], FIXED_NOW, TIMEZONE))
    assert "DESCRIPTION:Phòng A\\nTầng 2" in lines
