import pytest

from pair_harness.core.contracts import TaskStatus
from pair_harness.core.engine_state import (
    BusyTurnError,
    GlobalEngineState,
    InvalidTaskTransition,
    TaskLifecycle,
)


def test_task_state_machine_allows_only_confirmed_transitions() -> None:
    lifecycle = TaskLifecycle("task")
    lifecycle.transition(TaskStatus.RUNNING)
    lifecycle.transition(TaskStatus.AMENDMENT_PENDING)
    lifecycle.transition(TaskStatus.RUNNING)
    lifecycle.transition(TaskStatus.COMPLETED)

    with pytest.raises(InvalidTaskTransition):
        lifecycle.transition(TaskStatus.RUNNING)


def test_global_state_allows_different_conversations_concurrently() -> None:
    """V0.3.2 M4：并发单位是 conversation——不同聊天同时 active，
    同一聊天第二个 start 被拒，finish 只清理自己的任务。"""
    state = GlobalEngineState()
    state.start(project_id="p1", conversation_id="c1", task_id="t1")
    second = state.start(project_id="p2", conversation_id="c2", task_id="t2")

    with pytest.raises(BusyTurnError):
        state.start(project_id="p1", conversation_id="c1", task_id="t1b")

    assert state.get_for_conversation("c2") is second
    state.finish("t1")
    assert state.get_for_conversation("c1") is None
    assert state.get_for_conversation("c2") is second
    assert state.get_for_task("t2") is second
    state.finish("t2")
    assert state.active_tasks() == []

