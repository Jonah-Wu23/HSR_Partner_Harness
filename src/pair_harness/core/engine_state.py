from __future__ import annotations

from dataclasses import dataclass

from .contracts import TaskStatus


class InvalidTaskTransition(RuntimeError):
    pass


class BusyTurnError(RuntimeError):
    pass


_ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.AMENDMENT_PENDING,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.AMENDMENT_PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


@dataclass
class TaskLifecycle:
    task_id: str
    status: TaskStatus = TaskStatus.PENDING

    def transition(self, next_status: TaskStatus) -> None:
        if next_status not in _ALLOWED_TRANSITIONS[self.status]:
            raise InvalidTaskTransition(f"{self.status} -> {next_status} is not allowed")
        self.status = next_status


@dataclass(frozen=True)
class ActiveTurn:
    project_id: str
    conversation_id: str
    task_id: str
    engine_turn_id: str | None = None


class GlobalEngineState:
    def __init__(self) -> None:
        self.active: ActiveTurn | None = None

    def start(self, *, project_id: str, conversation_id: str, task_id: str) -> ActiveTurn:
        if self.active is not None:
            raise BusyTurnError(
                f"task {self.active.task_id} is already running in conversation "
                f"{self.active.conversation_id}"
            )
        self.active = ActiveTurn(
            project_id=project_id,
            conversation_id=conversation_id,
            task_id=task_id,
        )
        return self.active

    def bind_engine_turn(self, engine_turn_id: str) -> None:
        if self.active is None:
            raise RuntimeError("no active turn")
        self.active = ActiveTurn(
            project_id=self.active.project_id,
            conversation_id=self.active.conversation_id,
            task_id=self.active.task_id,
            engine_turn_id=engine_turn_id,
        )

    def finish(self, task_id: str) -> None:
        if self.active is None or self.active.task_id != task_id:
            raise RuntimeError("cannot finish a task that is not active")
        self.active = None

