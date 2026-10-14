from datetime import datetime

import pytest
from sqlmodel import Session

from flowagent.db import crud
from flowagent.db.models import Priority, TaskStatus
from flowagent.db.schemas import TaskCreate, TaskFilter, TaskUpdate
from flowagent.errors import InvalidScheduleError, ProjectExistsError, TaskNotFoundError


def test_create_and_get_task(session: Session) -> None:
    """A created task gets an id and can be read back."""
    created = crud.create_task(session, TaskCreate(title="Viết báo cáo", priority=Priority.HIGH))
    assert crud.get_task(session, created.id).title == "Viết báo cáo"


def test_get_missing_task_raises(session: Session) -> None:
    """Reading an unknown id raises TaskNotFoundError."""
    with pytest.raises(TaskNotFoundError):
        crud.get_task(session, 999)


def test_list_tasks_orders_by_deadline_with_undated_last(session: Session) -> None:
    """Tasks come back by ascending deadline and tasks without deadline go last."""
    crud.create_task(session, TaskCreate(title="Không hạn"))
    crud.create_task(session, TaskCreate(title="Muộn", deadline=datetime(2026, 10, 20)))
    crud.create_task(session, TaskCreate(title="Sớm", deadline=datetime(2026, 10, 15)))
    titles = [task.title for task in crud.list_tasks(session)]
    assert titles == ["Sớm", "Muộn", "Không hạn"]


def test_list_tasks_filters_by_keyword_and_excludes_done(session: Session) -> None:
    """Keyword search matches title text and include_done=False hides finished tasks."""
    open_task = crud.create_task(session, TaskCreate(title="Ôn thi toán"))
    done_task = crud.create_task(session, TaskCreate(title="Ôn thi văn"))
    crud.update_task(session, done_task.id, TaskUpdate(status=TaskStatus.DONE))
    found = crud.list_tasks(session, TaskFilter(keyword="Ôn thi", include_done=False))
    assert [task.id for task in found] == [open_task.id]


def test_update_task_sets_and_clears_completed_at(session: Session) -> None:
    """Marking a task done stamps completed_at and reopening it clears the stamp."""
    task = crud.create_task(session, TaskCreate(title="Nộp bài"))
    assert crud.update_task(session, task.id, TaskUpdate(status=TaskStatus.DONE)).completed_at
    reopened = crud.update_task(session, task.id, TaskUpdate(status=TaskStatus.TODO))
    assert reopened.completed_at is None


def test_delete_task_removes_row(session: Session) -> None:
    """A deleted task can no longer be read."""
    task = crud.create_task(session, TaskCreate(title="Tạm"))
    crud.delete_task(session, task.id)
    with pytest.raises(TaskNotFoundError):
        crud.get_task(session, task.id)


def test_create_project_rejects_duplicate_name(session: Session) -> None:
    """Project names are unique."""
    crud.create_project(session, "Website")
    with pytest.raises(ProjectExistsError):
        crud.create_project(session, "Website")


def test_create_task_rejects_start_after_deadline(session: Session) -> None:
    """A task cannot start after its deadline."""
    with pytest.raises(InvalidScheduleError):
        crud.create_task(
            session,
            TaskCreate(
                title="Sai lịch",
                planned_start=datetime(2026, 10, 20, 9, 0),
                deadline=datetime(2026, 10, 18, 17, 0),
            ),
        )


def test_update_task_rejects_deadline_before_existing_start(session: Session) -> None:
    """Moving the deadline before the existing start is rejected."""
    task = crud.create_task(
        session, TaskCreate(title="Ôn thi", planned_start=datetime(2026, 10, 20, 9, 0))
    )
    with pytest.raises(InvalidScheduleError):
        crud.update_task(session, task.id, TaskUpdate(deadline=datetime(2026, 10, 19, 9, 0)))
