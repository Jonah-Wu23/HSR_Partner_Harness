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
    cancellation_requested: bool = False


class GlobalEngineState:
    """V0.3.2 M4：并发单位是 conversation。

    - 不同聊天的任务同时 active，互不阻塞（同一账号内）；
    - 同一聊天最多一个活动任务，第二个 start 被拒绝（BusyTurnError）；
    - 取消、engine turn 绑定和 finish 全部按 task 精确归属。
    """

    def __init__(self) -> None:
        self.active_by_conversation: dict[str, ActiveTurn] = {}
        self.active_by_task: dict[str, ActiveTurn] = {}

    def start(self, *, project_id: str, conversation_id: str, task_id: str) -> ActiveTurn:
        existing = self.active_by_conversation.get(conversation_id)
        if existing is not None:
            raise BusyTurnError(
                f"task {existing.task_id} is already running in conversation "
                f"{existing.conversation_id}"
            )
        turn = ActiveTurn(
            project_id=project_id,
            conversation_id=conversation_id,
            task_id=task_id,
        )
        self.active_by_conversation[conversation_id] = turn
        self.active_by_task[task_id] = turn
        return turn

    def get_for_conversation(self, conversation_id: str) -> ActiveTurn | None:
        return self.active_by_conversation.get(conversation_id)

    def get_for_task(self, task_id: str) -> ActiveTurn | None:
        return self.active_by_task.get(task_id)

    def active_tasks(self) -> list[ActiveTurn]:
        """V0.3.2 M4：当前全部活动任务（快照/事件用）。"""
        return list(self.active_by_task.values())

    def bind_engine_turn(self, task_id: str, engine_turn_id: str) -> None:
        turn = self.active_by_task.get(task_id)
        if turn is None:
            raise RuntimeError(f"no active turn for task {task_id}")
        updated = ActiveTurn(
            project_id=turn.project_id,
            conversation_id=turn.conversation_id,
            task_id=turn.task_id,
            engine_turn_id=engine_turn_id,
            cancellation_requested=turn.cancellation_requested,
        )
        self._store(updated)

    def request_cancel(self, task_id: str) -> None:
        turn = self.active_by_task.get(task_id)
        if turn is None:
            raise RuntimeError(f"no active turn for task {task_id}")
        self._store(
            ActiveTurn(
                project_id=turn.project_id,
                conversation_id=turn.conversation_id,
                task_id=turn.task_id,
                engine_turn_id=turn.engine_turn_id,
                cancellation_requested=True,
            )
        )

    def mark_cancel_sent(self, task_id: str) -> None:
        turn = self.active_by_task.get(task_id)
        if turn is None:
            return
        self._store(
            ActiveTurn(
                project_id=turn.project_id,
                conversation_id=turn.conversation_id,
                task_id=turn.task_id,
                engine_turn_id=turn.engine_turn_id,
                cancellation_requested=False,
            )
        )

    def _store(self, turn: ActiveTurn) -> None:
        self.active_by_conversation[turn.conversation_id] = turn
        self.active_by_task[turn.task_id] = turn

    def finish(self, task_id: str) -> None:
        turn = self.active_by_task.get(task_id)
        if turn is None:
            raise RuntimeError("cannot finish a task that is not active")
        self.active_by_task.pop(task_id, None)
        if self.active_by_conversation.get(turn.conversation_id) is turn:
            self.active_by_conversation.pop(turn.conversation_id, None)
