"""M4 回归测试：持久化拒绝工具、委派纠偏、会话绑定与产品边界。

只覆盖 M4 范围内不依赖真实外部服务的状态机与协议逻辑。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    CharacterTurn,
    MessageOrigin,
    MessageSource,
    ProjectRef,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.desktop_backend.application_service import ServiceError, build_demo_service
from pair_harness.desktop_backend.commands import DesktopCommand
from pair_harness.storage.sqlite_store import SQLiteStore
from tests.fakes import FixedDialogueModel


def _command(request_id: str, method: str, **params: object) -> DesktopCommand:
    return DesktopCommand(request_id=request_id, method=method, params=params)


def _make_orchestrator(
    store: SQLiteStore,
    tmp_path: Path,
    *turns: CharacterTurn,
    approval_mode: ApprovalMode = ApprovalMode.FULL_AUTO,
    approval_callback=None,
) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="P", root_path=str(tmp_path)),
        dialogue_model=FixedDialogueModel(*turns),
        coding_engine=ScriptedCodingEngine(),
        store=store,
        approval_mode=approval_mode,
        approval_callback=approval_callback,
    )


@pytest.mark.asyncio
async def test_m41_denied_tool_run_is_persisted(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(project_id="p", name="P", root_path=str(tmp_path))
        store.create_conversation(
            project_id="p",
            pair_id="phainon_ancient_machine",
            conversation_id="c",
        )

        async def deny_callback(_op, _approval_id, _reason, _conversation_id="", _task_id=""):
            return ApprovalDecision.DENY

        orchestrator = _make_orchestrator(
            store,
            tmp_path,
            CharacterTurn(
                speech="交给古代机械。",
                delegation=TaskRequestDraft(instructions="执行任务"),
            ),
            CharacterTurn(speech="任务结束。"),
            approval_mode=ApprovalMode.REQUEST_APPROVAL,
            approval_callback=deny_callback,
        )
        outcome = await orchestrator.handle_character_input(
            conversation_id="c", text="执行任务"
        )

        denied = [run for run in outcome.tool_runs if run.status == "denied"]
        assert denied
        assert denied[0].conversation_id == "c"
        assert denied[0].tool_call_id

        snapshot = store.load_conversation("c")
        persisted = [run for run in snapshot["tool_runs"] if run.status == "denied"]
        assert len(persisted) == len(denied)
        assert persisted[0].tool_call_id == denied[0].tool_call_id
        assert persisted[0].details


@pytest.mark.asyncio
async def test_m42_delegation_correction_replaces_original_role_message(
    tmp_path: Path,
) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(project_id="p", name="P", root_path=str(tmp_path))
        store.create_conversation(
            project_id="p",
            pair_id="phainon_ancient_machine",
            conversation_id="c",
        )
        orchestrator = _make_orchestrator(
            store,
            tmp_path,
            CharacterTurn(speech="第一次没形成委派。", delegation_missed=True),
            CharacterTurn(
                speech="纠偏后的正式委派。",
                delegation=TaskRequestDraft(instructions="查看项目"),
            ),
            CharacterTurn(speech="做完了。"),
        )
        outcome = await orchestrator.handle_character_input(
            conversation_id="c", text="帮我看看项目"
        )

        history = orchestrator._history["c"]
        # 纠偏目标气泡使用 speech: 前缀；执行结果轮的独立角色回应不算重复。
        character_messages = [
            message
            for message in history
            if message.source == MessageSource.CHARACTER
            and message.message_id.startswith("speech:")
        ]
        assert len(character_messages) == 1
        assert character_messages[0].text == "纠偏后的正式委派。"
        assert len(
            [
                message
                for message in history
                if message.message_id == character_messages[0].message_id
            ]
        ) == 1
        assert outcome.receipt is not None
        assert outcome.receipt.status == "completed"

        snapshot = store.load_conversation("c")
        persisted_character = [
            message
            for message in snapshot["messages"]
            if message.source == MessageSource.CHARACTER
            and message.message_id.startswith("speech:")
        ]
        assert len(persisted_character) == 1
        assert persisted_character[0].text == "纠偏后的正式委派。"


@pytest.mark.asyncio
async def test_m44_chat_mode_rejects_assistant_target(tmp_path: Path) -> None:
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        conversation_id = service.current_conversation_id
        with pytest.raises(ServiceError) as exc_info:
            await service.handle_command(
                _command(
                    "chat-1",
                    "chat.submit",
                    conversation_id=conversation_id,
                    target="assistant",
                    text="执行任务",
                )
            )
        assert exc_info.value.code == "assistant_not_allowed_in_chat_mode"
        assert service.orchestrator.state.active_tasks() == []
        assert service.store.load_conversation(conversation_id)["messages"] == ()
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_m43_review_event_uses_payload_conversation_id(tmp_path: Path) -> None:
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        service._on_review_event(
            "review.started",
            {"conversation_id": "task-conv", "summary": "检查命令"},
        )
        assert events[-1]["event"] == "review.started"
        assert events[-1]["payload"]["conversation_id"] == "task-conv"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_m43_voice_submission_uses_ptt_captured_context(tmp_path: Path) -> None:
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        captured: dict[str, str] = {}

        async def fake_chat_submit(params: dict) -> None:
            captured.update({str(k): str(v) for k, v in params.items()})

        service._chat_submit = fake_chat_submit  # type: ignore[method-assign]
        service._ptt_voice_context = {
            "conversation_id": "captured-conv",
            "target": "character",
            "pair_id": "phainon_ancient_machine",
        }
        await service._submit_voice_input("语音文本", "assistant")
        assert captured == {
            "conversation_id": "captured-conv",
            "target": "character",
            "text": "语音文本",
        }

        with pytest.raises(ServiceError) as exc_info:
            await service.handle_command(
                _command("ptt-1", "voice.ptt_start", target="system")
            )
        assert exc_info.value.code == "invalid_target"
    finally:
        await service.shutdown()


def test_m45_archived_project_directory_restores_existing_record(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(project_id="p", name="P", root_path=str(tmp_path))
        store.archive_project("p")

        found = store.find_project_by_root_path(str(tmp_path))
        assert found is not None
        assert found.project_id == "p"
        assert found.archived is True

        restored = store.unarchive_project("p")
        assert restored.archived is False
        assert len(store.list_projects()) == 1
        assert len(store.list_projects(include_archived=True)) == 1


def test_m45_recent_projects_sort_old_and_iso_time_formats(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(project_id="old-space", name="旧格式", root_path=str(tmp_path / "a"))
        store.create_project(project_id="iso-plus", name="ISO", root_path=str(tmp_path / "b"))
        store.connection.execute(
            "UPDATE projects SET last_opened_at = ? WHERE project_id = ?",
            ("2026-08-01 10:00:00", "old-space"),
        )
        store.connection.execute(
            "UPDATE projects SET last_opened_at = ? WHERE project_id = ?",
            ("2026-08-01T11:00:00+00:00", "iso-plus"),
        )
        store.connection.commit()

        assert [p.project_id for p in store.list_projects()] == ["iso-plus", "old-space"]
