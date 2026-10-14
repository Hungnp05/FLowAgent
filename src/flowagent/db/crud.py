from collections.abc import Sequence

from sqlmodel import Session, col, select

from flowagent.clock import now_local
from flowagent.db.models import Project, Task, TaskStatus
from flowagent.db.schemas import TaskCreate, TaskFilter, TaskUpdate
from flowagent.errors import (
    InvalidScheduleError,
    ProjectExistsError,
    ProjectNotFoundError,
    TaskNotFoundError,
)


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
    if task_filter.keyword:
        pattern = f"%{task_filter.keyword}%"
        query = query.where(col(Task.title).ilike(pattern) | col(Task.description).ilike(pattern))
    query = query.order_by(col(Task.deadline).is_(None), col(Task.deadline), col(Task.id))
    return session.exec(query).all()


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
