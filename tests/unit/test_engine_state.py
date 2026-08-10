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


def test_global_state_allows_only_one_active_turn() -> None:
    state = GlobalEngineState()
    state.start(project_id="p1", conversation_id="c1", task_id="t1")

    with pytest.raises(BusyTurnError):
        state.start(project_id="p2", conversation_id="c2", task_id="t2")

    state.finish("t1")
    assert state.active is None

