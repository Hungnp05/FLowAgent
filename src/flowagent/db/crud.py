from collections.abc import Sequence

from sqlmodel import Session, col, select

from flowagent.clock import now_local
from flowagent.db.models import (
    MINUTES_PER_DAY,
    MemoryNote,
    Priority,
    Project,
    ScheduleEvent,
    Task,
    TaskStatus,
)
from flowagent.db.schemas import (
    ScheduleEventCreate,
    ScheduleEventUpdate,
    TaskCreate,
    TaskFilter,
    TaskUpdate,
)
from flowagent.errors import (
    EventNotFoundError,
    InvalidScheduleError,
    MemoryNotFoundError,
    ProjectExistsError,
    ProjectNotFoundError,
    TaskNotFoundError,
)
from flowagent.vietnamese import contains_all_words, fold_text


def ensure_start_before_deadline(task: Task) -> None:
    """Reject a task whose planned start is later than its deadline."""
    if task.planned_start and task.deadline and task.planned_start > task.deadline:
        raise InvalidScheduleError("Ngày bắt đầu phải trước hoặc bằng hạn chót.")


def create_task(session: Session, task_in: TaskCreate) -> Task:
    """Insert a new task and return it with its generated id."""
    task = Task.model_validate(task_in)
    ensure_start_before_deadline(task)
    session.add(task)
    session.flush()
    session.refresh(task)
    return task


def get_task(session: Session, task_id: int) -> Task:
    """Return the task with the given id or raise TaskNotFoundError."""
    task = session.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError(f"Không tìm thấy công việc có id={task_id}.")
    return task


def list_tasks(session: Session, task_filter: TaskFilter | None = None) -> Sequence[Task]:
    """Return tasks matching the filter, ordered by deadline with undated tasks last."""
    task_filter = task_filter or TaskFilter()
    query = select(Task)
    if task_filter.status is not None:
        query = query.where(Task.status == task_filter.status)
    elif not task_filter.include_done:
        query = query.where(Task.status != TaskStatus.DONE)
    if task_filter.priority is not None:
        query = query.where(Task.priority == task_filter.priority)
    if task_filter.project_id is not None:
        query = query.where(Task.project_id == task_filter.project_id)
    if task_filter.due_before is not None:
        query = query.where(col(Task.deadline) <= task_filter.due_before)
    query = query.order_by(col(Task.deadline).is_(None), col(Task.deadline), col(Task.id))
    tasks = session.exec(query).all()
    if not task_filter.keyword:
        return tasks
    return [
        task
        for task in tasks
        if contains_all_words(f"{task.title} {task.description}", task_filter.keyword)
    ]


def update_task(session: Session, task_id: int, changes: TaskUpdate) -> Task:
    """Apply the provided fields to a task and keep completed_at in sync with its status."""
    task = get_task(session, task_id)
    task.sqlmodel_update(changes.model_dump(exclude_unset=True))
    ensure_start_before_deadline(task)
    if changes.status is not None:
        task.completed_at = now_local() if changes.status == TaskStatus.DONE else None
    session.add(task)
    session.flush()
    session.refresh(task)
    return task


def delete_task(session: Session, task_id: int) -> Task:
    """Delete a task and return the removed row."""
    task = get_task(session, task_id)
    session.delete(task)
    session.flush()
    return task


def create_project(session: Session, name: str, goal: str = "") -> Project:
    """Insert a new project with a unique name and return it with its generated id."""
    if session.exec(select(Project).where(Project.name == name)).first() is not None:
        raise ProjectExistsError(f"Dự án '{name}' đã tồn tại, hãy chọn tên khác.")
    project = Project(name=name, goal=goal)
    session.add(project)
    session.flush()
    session.refresh(project)
    return project


def get_project_by_name(session: Session, name: str) -> Project:
    """Return the project with the given name or raise ProjectNotFoundError."""
    project = session.exec(select(Project).where(Project.name == name)).first()
    if project is None:
        raise ProjectNotFoundError(f"Không tìm thấy dự án '{name}'.")
    return project


def list_projects(session: Session) -> Sequence[Project]:
    """Return all projects, newest first."""
    return session.exec(select(Project).order_by(col(Project.created_at).desc())).all()


def create_event(session: Session, event_in: ScheduleEventCreate) -> ScheduleEvent:
    """Insert a calendar event and return it with its generated id."""
    event = ScheduleEvent.model_validate(event_in)
    session.add(event)
    session.flush()
    session.refresh(event)
    return event


def get_event(session: Session, event_id: int) -> ScheduleEvent:
    """Return the calendar event with the given id or raise EventNotFoundError."""
    event = session.get(ScheduleEvent, event_id)
    if event is None:
        raise EventNotFoundError(f"Không tìm thấy lịch trình có id={event_id}.")
    return event


def list_events(session: Session) -> Sequence[ScheduleEvent]:
    """Return every calendar event ordered by its first start time."""
    return session.exec(select(ScheduleEvent).order_by(col(ScheduleEvent.start_at))).all()


def replace_event(session: Session, event_id: int, event_in: ScheduleEventCreate) -> ScheduleEvent:
    """Overwrite all editable fields of an event, as the editor dialog saves the whole form."""
    event = get_event(session, event_id)
    event.sqlmodel_update(event_in.model_dump())
    event.created_at = now_local()
    session.add(event)
    session.flush()
    session.refresh(event)
    return event


def update_event(session: Session, event_id: int, changes: ScheduleEventUpdate) -> ScheduleEvent:
    """Apply only the provided fields to an event; all-day events span the whole start date."""
    event = get_event(session, event_id)
    event.sqlmodel_update(changes.model_dump(exclude_unset=True))
    if event.all_day:
        event.start_at = event.start_at.replace(hour=0, minute=0)
        event.duration_minutes = MINUTES_PER_DAY
    event.created_at = now_local()
    session.add(event)
    session.flush()
    session.refresh(event)
    return event


def find_events(session: Session, keyword: str | None = None) -> list[ScheduleEvent]:
    """Return events whose title or note contains every keyword word, ignoring accents."""
    events = list_events(session)
    if not keyword:
        return list(events)
    return [event for event in events if contains_all_words(f"{event.title} {event.note}", keyword)]


def change_event_priority(session: Session, event_id: int, priority: Priority) -> ScheduleEvent:
    """Set a new priority on an event."""
    event = get_event(session, event_id)
    event.priority = priority
    session.add(event)
    session.flush()
    return event


def delete_event(session: Session, event_id: int) -> None:
    """Delete a calendar event."""
    session.delete(get_event(session, event_id))
    session.flush()


def add_memory(session: Session, content: str) -> MemoryNote:
    """Store a long-term fact about the user, reusing an existing note with the same text."""
    text = content.strip()
    for note in list_memories(session):
        if fold_text(note.content) == fold_text(text):
            return note
    note = MemoryNote.model_validate({"content": text})
    session.add(note)
    session.flush()
    session.refresh(note)
    return note


def list_memories(session: Session) -> Sequence[MemoryNote]:
    """Return every remembered fact, oldest first."""
    return session.exec(select(MemoryNote).order_by(col(MemoryNote.id))).all()


def delete_memory(session: Session, memory_id: int) -> None:
    """Forget one remembered fact or raise MemoryNotFoundError."""
    note = session.get(MemoryNote, memory_id)
    if note is None:
        raise MemoryNotFoundError(f"Không tìm thấy ghi nhớ có id={memory_id}.")
    session.delete(note)
    session.flush()
