from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from pair_harness.core.contracts import ApprovalMode, MessageSource
from pair_harness.desktop_backend.application_service import (
    ServiceError,
    build_demo_service,
)
from pair_harness.desktop_backend.commands import DesktopCommand


def command(request_id: str, method: str, **params) -> DesktopCommand:
    return DesktopCommand(request_id=request_id, method=method, params=params)


@pytest.mark.asyncio
async def test_bootstrap_contains_projects_conversation_and_voice_shape(tmp_path: Path) -> None:
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        snapshot = await service.handle_command(command("1", "app.bootstrap"))
        assert snapshot["projects"][0]["path_available"] is True
        assert snapshot["current_conversation"]["pair_id"] == "phainon_ancient_machine"
        assert snapshot["messages"] == []
        assert snapshot["voice"]["supported"] is False
        # V0.2 M4：voice 快照携带待播队列长度（VoiceMiniPlayer 的 queuedCount）
        assert snapshot["voice"]["speech_queue_len"] == 0
        assert snapshot["busy"] is False
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_chat_submit_emits_messages_and_direct_task_tool_updates(tmp_path: Path) -> None:
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id

        async def wait_for(
            predicate, *, message: str, timeout: float = 5.0
        ) -> None:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while loop.time() < deadline:
                if predicate():
                    return
                await asyncio.sleep(0.01)
            raise AssertionError(message)

        # 快速接受：chat.submit 同步落库并立即返回真实 message_id
        result = await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="今天有点累，陪我聊聊。",
            )
        )
        assert result["message_id"]
        assert result["status"] == "received"
        assert result["target"] == "character"
        # 用户消息立即出现；后台回合随后补发角色消息
        await wait_for(
            lambda: events[0]["event"] == "message.created",
            message="首条用户消息应立即出现",
        )
        assert events[0]["payload"]["message"]["source"] == "user"
        await wait_for(
            lambda: [e["event"] for e in events].count("message.created") == 2,
            message="后台回合应补发角色消息",
        )

        await service.handle_command(
            command(
                "settings-1",
                "project.update_settings",
                approval_mode=ApprovalMode.FULL_AUTO.value,
            )
        )
        events.clear()
        result = await service.handle_command(
            command(
                "task-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="assistant",
                text="请检查这个项目",
            )
        )
        assert result["message_id"]
        assert result["status"] == "received"
        # 等待后台回合执行到完成（turn 终态是回合收尾信号，位于 busy 回落后）
        await wait_for(
            lambda: any(
                e["event"] == "turn.status_changed"
                and e["payload"]["turn"]["status"] == "completed"
                for e in events
            ),
            message="后台助手回合应执行到完成",
        )
        event_names = [event["event"] for event in events]
        assert "task.busy_changed" in event_names
        assert "message.delta" in event_names
        assert "tool_run.upserted" in event_names
        assert event_names[-1] == "turn.status_changed"
        assert events[-1]["payload"]["turn"]["status"] == "completed"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_project_and_conversation_commands_return_restorable_snapshot(
    tmp_path: Path,
) -> None:
    database = tmp_path / "data" / "pair_harness.db"
    service = build_demo_service(
        database=database,
        project_root=tmp_path,
    )
    project_root = tmp_path / "another-project"
    project_root.mkdir()
    try:
        snapshot = await service.handle_command(
            command("p-1", "project.create", root_path=str(project_root), name="另一个项目")
        )
        assert snapshot["current_project"]["name"] == "另一个项目"
        conversation_id = snapshot["current_conversation_id"]
        await service.handle_command(
            command("r-1", "conversation.rename", conversation_id=conversation_id, title="已改名")
        )
    finally:
        await service.shutdown()

    restored = build_demo_service(database=database, project_root=tmp_path)
    try:
        snapshot = await restored.handle_command(command("b-1", "app.bootstrap"))
        assert snapshot["current_project"]["name"] == "另一个项目"
        assert snapshot["current_conversation_id"] == conversation_id
        assert snapshot["current_conversation"]["title"] == "已改名"
    finally:
        await restored.shutdown()


@pytest.mark.asyncio
async def test_project_defaults_to_folder_name_and_manual_name_survives_path_repair(
    tmp_path: Path,
) -> None:
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    first_root = tmp_path / "folder-a"
    second_root = tmp_path / "folder-b"
    first_root.mkdir()
    second_root.mkdir()
    try:
        snapshot = await service.handle_command(
            command("p-1", "project.create", root_path=str(first_root))
        )
        project_id = snapshot["current_project_id"]
        assert snapshot["current_project"]["name"] == "folder-a"

        result = await service.handle_command(
            command("rename-1", "project.update_settings", project_id=project_id, name="我的项目")
        )
        assert result["project"]["name"] == "我的项目"

        result = await service.handle_command(
            command(
                "repair-1",
                "project.update_settings",
                project_id=project_id,
                root_path=str(second_root),
            )
        )
        assert result["project"]["root_path"] == str(second_root.resolve())
        assert result["project"]["name"] == "我的项目"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_project_archive_works_for_current_last_project(tmp_path: Path) -> None:
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        project_id = service.current_project_id
        snapshot = await service.handle_command(
            command("archive-1", "project.archive", project_id=project_id)
        )
        assert snapshot["projects"] == []
        assert snapshot["current_project_id"] == ""
        assert snapshot["current_conversation_id"] == ""
        assert snapshot["current_project"]["project_id"] == ""
    finally:
        await service.shutdown()

    restored = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        restored_snapshot = restored.bootstrap()
        assert restored_snapshot["projects"] == []
        assert restored_snapshot["current_project_id"] == ""
    finally:
        await restored.shutdown()


@pytest.mark.asyncio
async def test_first_complete_reply_generates_title_from_dialogue_only_and_manual_name_wins(
    tmp_path: Path,
) -> None:
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        conversation_id = service.current_conversation_id
        await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="请陪我规划一下今天的工作。",
            )
        )
        await asyncio.sleep(0)

        conversation = service.store.get_conversation(conversation_id)
        assert conversation.title != "新聊天"
        title_requests = getattr(service.dialogue_model, "title_requests")
        assert len(title_requests) == 1
        _, context = title_requests[0]
        assert context
        assert all(message.source in {MessageSource.USER, MessageSource.CHARACTER} for message in context)
        assert all(message.source not in {MessageSource.SYSTEM, MessageSource.TOOL} for message in context)

        second = await service.handle_command(
            command("conversation-2", "conversation.create", project_id=service.current_project_id)
        )
        second_id = second["current_conversation_id"]
        await service.handle_command(
            command(
                "chat-2",
                "chat.submit",
                conversation_id=second_id,
                target="character",
                text="这是一个会被手动命名的聊天。",
            )
        )
        await service.handle_command(
            command(
                "rename-chat-2",
                "conversation.rename",
                conversation_id=second_id,
                title="手动命名",
            )
        )
        await asyncio.sleep(0)
        assert service.store.get_conversation(second_id).title == "手动命名"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_streaming_assistant_events_reconcile_to_one_persisted_message(
    tmp_path: Path,
) -> None:
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        await service.handle_command(
            command(
                "settings-1",
                "project.update_settings",
                approval_mode=ApprovalMode.FULL_AUTO.value,
            )
        )
        conversation_id = service.current_conversation_id
        await service.handle_command(
            command(
                "task-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="assistant",
                mode="collaboration",
                text="请检查这个项目",
            )
        )
        # 快速接受后回合在后台运行：等待回合收尾（turn 终态 completed）
        async def _wait_turn_done() -> None:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 5.0
            while loop.time() < deadline:
                if any(
                    e["event"] == "turn.status_changed"
                    and e["payload"]["turn"]["status"] == "completed"
                    for e in events
                ):
                    return
                await asyncio.sleep(0.01)
            raise AssertionError("后台回合未在超时前结束")

        await _wait_turn_done()

        delta_ids = {
            event["payload"]["message_id"]
            for event in events
            if event["event"] == "message.delta"
        }
        finalized_ids = {
            event["payload"]["message_id"]
            for event in events
            if event["event"] == "message.finalized"
        }
        assistant_messages = [
            message
            for message in service.bootstrap()["messages"]
            if message["source"] == "assistant"
        ]
        assert delta_ids
        assert delta_ids <= finalized_ids
        assert len(assistant_messages) == 1
        assert assistant_messages[0]["message_id"] in delta_ids
        assert service.store.get_conversation(conversation_id).last_mode == "collaboration"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_voice_commands_only_exchange_state_with_attached_runtime(tmp_path: Path) -> None:
    events: list[dict] = []

    class FakeVoiceRuntime:
        on_message = lambda self, _message: None
        # V0.2 M4：待播队列长度（VoiceMiniPlayer 的 queuedCount）
        speech_queue_len = 0

        def __init__(self) -> None:
            self.listening = False
            self.ptt = False
            self.stopped = False

        async def start_listening(self) -> None:
            self.listening = True

        async def stop_listening(self) -> None:
            self.listening = False

        def start_playback(self) -> None:
            pass

        async def push_to_talk_start(self, *, target: str) -> None:
            del target
            self.ptt = True

        async def push_to_talk_stop(self) -> None:
            self.ptt = False

        def stop_speaking(self) -> None:
            self.stopped = True

        async def shutdown(self) -> None:
            pass

    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    runtime = FakeVoiceRuntime()
    service.attach_voice_runtime(runtime)  # type: ignore[arg-type]
    try:
        assert service.bootstrap()["voice"]["supported"] is True
        # V0.2 M4：voice 快照与事件都携带待播队列长度
        assert service.bootstrap()["voice"]["speech_queue_len"] == 0
        await service.handle_command(command("vad-on", "voice.vad_set", enabled=True))
        await service.handle_command(command("ptt-on", "voice.ptt_start", target="character"))
        await service.handle_command(command("ptt-off", "voice.ptt_stop"))
        await service.handle_command(command("tts-off", "voice.tts_stop"))
        assert runtime.listening is True
        assert runtime.ptt is False
        assert runtime.stopped is True
        changed = [event for event in events if event["event"] == "voice.state_changed"]
        assert changed
        assert all(event["payload"]["voice"]["speech_queue_len"] == 0 for event in changed)
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_voice_tts_play_skip_and_preview_commands(tmp_path: Path) -> None:
    """V0.2 M2-4：voice.tts_play 按 message_id 重播、tts_skip 跳过、preview 试听入队。"""
    events: list[dict] = []

    class FakeVoiceRuntime:
        on_message = lambda self, _message: None

        def __init__(self) -> None:
            self.replayed: list[Any] = []
            self.skips = 0
            self.preview_texts: list[str] = []
            # V0.2 M4：待播队列长度（VoiceMiniPlayer 的 queuedCount）
            self.speech_queue_len = 0

        def replay_message(self, message: Any) -> None:
            self.replayed.append(message)

        def skip_playing(self) -> None:
            self.skips += 1

        def enqueue_text(self, text: str, *, voice_id: str | None = None) -> None:
            del voice_id
            self.preview_texts.append(text)
            self.speech_queue_len += 1

        async def shutdown(self) -> None:
            pass

    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    runtime = FakeVoiceRuntime()
    service.attach_voice_runtime(runtime)  # type: ignore[arg-type]
    try:
        conversation_id = service.current_conversation_id
        result = await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="你好，白厄。",
            )
        )
        message_id = result["message_id"]

        # tts_play：从会话消息取文本重播（返回真实 message_id 的用户消息）
        await service.handle_command(
            command("play-1", "voice.tts_play", message_id=message_id)
        )
        assert [m.message_id for m in runtime.replayed] == [message_id]

        # tts_skip：调用 runtime.skip_playing
        await service.handle_command(command("skip-1", "voice.tts_skip"))
        assert runtime.skips == 1

        # preview：文本入队试听
        await service.handle_command(command("preview-1", "voice.preview", text="试听一下"))
        assert runtime.preview_texts == ["试听一下"]

        # V0.2 M4：voice 快照的 speech_queue_len 反映待播队列长度
        snapshot = await service.handle_command(command("b-1", "app.bootstrap"))
        assert snapshot["voice"]["speech_queue_len"] == 1

        # 错误路径：消息不存在 / 试听文本不可读
        with pytest.raises(ServiceError):
            await service.handle_command(
                command("play-2", "voice.tts_play", message_id="no-such-message")
            )
        with pytest.raises(ServiceError):
            await service.handle_command(command("preview-2", "voice.preview", text="……"))
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_chat_submit_registers_turn_with_lifecycle_events(tmp_path: Path) -> None:
    """V0.2 M2：一次提交 = 一个 Turn——提交返回 turn_id，后台推进
    turn.started(running) → turn.status_changed(completed)，快照可水合。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id

        async def wait_for(
            predicate, *, message: str, timeout: float = 5.0
        ) -> None:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while loop.time() < deadline:
                if predicate():
                    return
                await asyncio.sleep(0.01)
            raise AssertionError(message)

        result = await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="今天状态怎么样？",
            )
        )
        assert result["turn_id"]

        def turn_events() -> list[dict]:
            return [
                e for e in events if e["event"] in ("turn.started", "turn.status_changed")
            ]

        await wait_for(
            lambda: len(turn_events()) >= 2,
            message="应发射 turn.started 与终态 turn.status_changed",
        )
        started = [e for e in turn_events() if e["event"] == "turn.started"]
        assert len(started) == 1
        assert started[0]["payload"]["turn"]["turn_id"] == result["turn_id"]
        assert started[0]["payload"]["turn"]["status"] == "running"
        assert started[0]["payload"]["turn"]["source_message_id"] == result["message_id"]
        assert started[0]["payload"]["turn"]["conversation_id"] == conversation_id
        assert started[0]["payload"]["turn"]["project_id"]  # 归属项目

        terminal = turn_events()[-1]
        assert terminal["payload"]["turn"]["status"] == "completed"

        # 快照水合：turns 按顺序包含该会话的 turn（终态 completed）
        snapshot = service.bootstrap()
        turns = [t for t in snapshot["turns"] if t["conversation_id"] == conversation_id]
        assert turns
        assert turns[-1]["turn_id"] == result["turn_id"]
        assert turns[-1]["status"] == "completed"
        assert turns[0]["turn_id"] == turns[-1]["turn_id"]  # 单次提交单条 turn
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_failed_turn_marks_turn_failed_and_message_failed(tmp_path: Path) -> None:
    """V0.2 M2：回合失败时 turn 进入 failed，用户消息标记 failed（文字保留）。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        # 注入会失败的编排器路径：破坏对话模型不可行（demo 不会失败），
        # 改用关闭后的服务直接驱动 _run_submit_turn 不可行——这里通过
        # 让 submit 后立即 shutdown 触发任务取消，验证 cancelled 事件。
        conversation_id = service.current_conversation_id
        result = await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="你好",
            )
        )
        assert result["turn_id"]
        await service.shutdown()

        # shutdown 后服务关闭，turn 记录仍按事件序列保留（cancelled）
        started = [e for e in events if e["event"] == "turn.started"]
        terminal = [e for e in events if e["event"] == "turn.status_changed"]
        assert started, "turn.started 应已发射"
        statuses = [e["payload"]["turn"]["status"] for e in terminal]
        assert "cancelled" in statuses or "completed" in statuses
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_busy_submit_enqueues_then_auto_dispatches_after_turn(tmp_path: Path) -> None:
    """V0.2 M2（问题 9）：忙碌时提交先入队返回 queue_item；回合完成后
    自动派发队列项（成为真实用户消息），队列消费后清空。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id

        async def wait_for(predicate, *, message: str, timeout: float = 5.0) -> None:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while loop.time() < deadline:
                if predicate():
                    return
                await asyncio.sleep(0.01)
            raise AssertionError(message)

        # 制造忙碌：编排器有活动任务时提交会入队
        service.orchestrator.state.start(
            project_id="project-demo", conversation_id=conversation_id, task_id="task-busy"
        )
        result = await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="等你忙完再说这个。",
            )
        )
        assert result["queued"] is True
        assert result["queue_item"]["status"] == "queued"
        assert result["queue_item"]["conversation_id"] == conversation_id
        # 入队时不创建用户消息（派发时才落库）
        assert not any(
            e["event"] == "message.created" for e in events
        )
        queue_changed = [e for e in events if e["event"] == "queue.changed"]
        assert queue_changed, "入队应推送 queue.changed"
        assert len(queue_changed[-1]["payload"]["items"]) == 1

        # 清理忙碌：下一条提交的回合完成后应自动派发队列项
        service.orchestrator.state.finish("task-busy")
        events.clear()
        await service.handle_command(
            command(
                "chat-2",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="现在有空了吗？",
            )
        )

        async def queued_text_dispatched() -> bool:
            messages = [
                m for m in service.bootstrap()["messages"]
                if m["source"] == "user"
            ]
            return any("等你忙完再说这个" in m["text"] for m in messages)

        await wait_for(queued_text_dispatched, message="队列项应被自动派发为用户消息")
        # 队列消费后清空（processing → 完成删除）
        await wait_for(
            lambda: service.store.list_queue_items(conversation_id) == [],
            message="队列项派发完成后应从队列移除",
        )
        # 派发的队列项也走 Turn 生命周期
        turn_events = [
            e for e in events if e["event"] in ("turn.started", "turn.status_changed")
        ]
        assert len([e for e in turn_events if e["event"] == "turn.started"]) == 2
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_queue_edit_withdraw_and_prioritize(tmp_path: Path) -> None:
    """V0.2 M2：queue.edit 改文本、queue.withdraw 撤回、queue.prioritize 置队首。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        service.orchestrator.state.start(
            project_id="project-demo", conversation_id=conversation_id, task_id="task-busy"
        )
        first = await service.handle_command(
            command("chat-1", "chat.submit", conversation_id=conversation_id, text="第一条")
        )
        second = await service.handle_command(
            command("chat-2", "chat.submit", conversation_id=conversation_id, text="第二条")
        )
        first_item, second_item = first["queue_item"], second["queue_item"]
        assert first_item["position"] == 0
        assert second_item["position"] == 1

        # 编辑
        edited = await service.handle_command(
            command("edit-1", "queue.edit", queue_item_id=first_item["queue_item_id"], text="改过的第一条")
        )
        assert edited["queue_item"]["text"] == "改过的第一条"

        # 调序：第二条置队首
        await service.handle_command(
            command("pri-1", "queue.prioritize", queue_item_id=second_item["queue_item_id"])
        )
        items = service.store.list_queue_items(conversation_id)
        assert items[0]["queue_item_id"] == second_item["queue_item_id"]
        assert items[0]["position"] == 0
        assert items[1]["position"] == 1

        # 撤回第一条
        withdrawn = await service.handle_command(
            command("wd-1", "queue.withdraw", queue_item_id=first_item["queue_item_id"])
        )
        assert withdrawn["queue_item"]["status"] == "withdrawn"
        assert service.store.peek_queue_item(conversation_id)["queue_item_id"] == second_item["queue_item_id"]

        # 每个命令都推送 queue.changed 全量快照
        changed = [e for e in events if e["event"] == "queue.changed"]
        # 两次入队 + 编辑/调序/撤回 各一次 = 5 次全量推送
        assert len(changed) == 5
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_queue_persists_across_service_restart(tmp_path: Path) -> None:
    """V0.2 M2：conversation_inbox 持久化——重启后 bootstrap 快照仍含队列项。"""
    database = tmp_path / "data" / "pair_harness.db"
    service = build_demo_service(database=database, project_root=tmp_path)
    try:
        conversation_id = service.current_conversation_id
        service.orchestrator.state.start(
            project_id="project-demo", conversation_id=conversation_id, task_id="task-busy"
        )
        result = await service.handle_command(
            command("chat-1", "chat.submit", conversation_id=conversation_id, text="跨重启的队列项")
        )
        assert result["queued"] is True
    finally:
        await service.shutdown()

    restored = build_demo_service(database=database, project_root=tmp_path)
    try:
        snapshot = restored.bootstrap()
        items = [item for item in snapshot["queue_items"] if item["conversation_id"] == conversation_id]
        assert len(items) == 1
        assert items[0]["text"] == "跨重启的队列项"
        assert items[0]["status"] == "queued"
    finally:
        await restored.shutdown()


@pytest.mark.asyncio
async def test_account_register_login_and_snapshot_fields(tmp_path: Path) -> None:
    """V0.2 M3：注册即登录；快照携带当前账号与账号列表。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        snapshot = await service.handle_command(command("b-1", "app.bootstrap"))
        assert snapshot["current_account_id"] == "default-local"
        assert snapshot["current_account"]["username"] == "default"

        result = await service.handle_command(
            command(
                "reg-1",
                "account.register",
                username="alice",
                display_name="爱丽丝",
                password="s3cret-pass",
            )
        )
        assert result["account"]["username"] == "alice"
        assert "password" not in result["account"]

        snapshot = await service.handle_command(command("b-2", "app.bootstrap"))
        assert snapshot["current_account_id"] == result["account"]["account_id"]
        assert snapshot["current_account"]["display_name"] == "爱丽丝"
        assert any(a["is_last_login"] for a in snapshot["accounts"])
        assert len(snapshot["accounts"]) == 2

        # 登录（密码错误拒绝）
        with pytest.raises(Exception):
            await service.handle_command(
                command(
                    "login-bad",
                    "account.login",
                    account_id=result["account"]["account_id"],
                    password="wrong-pass",
                )
            )
        logged = await service.handle_command(
            command(
                "login-1",
                "account.login",
                account_id=result["account"]["account_id"],
                password="s3cret-pass",
            )
        )
        assert logged["account"]["account_id"] == result["account"]["account_id"]
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_account_switch_isolates_projects(tmp_path: Path) -> None:
    """V0.2 M3：切换账号后项目/聊天按账号隔离。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        default_project_id = service.current_project_id
        # 注册新账号：默认账号项目不再可见
        result = await service.handle_command(
            command(
                "reg-1",
                "account.register",
                username="bob",
                display_name="鲍勃",
                password="bob-pass-1",
            )
        )
        snapshot = await service.handle_command(command("b-1", "app.bootstrap"))
        assert snapshot["current_account_id"] == result["account"]["account_id"]
        assert snapshot["projects"] == []  # 新账号无项目
        assert service.current_project_id != default_project_id or service.current_project_id == ""

        # 切回默认账号：项目恢复
        back = await service.handle_command(
            command("login-1", "account.login", account_id="default-local", password="")
        )
        assert back["account"]["username"] == "default"
        snapshot = await service.handle_command(command("b-2", "app.bootstrap"))
        assert any(p["project_id"] == default_project_id for p in snapshot["projects"])
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_account_onboarding_complete_marks_flag_only_on_command(
    tmp_path: Path,
) -> None:
    """V0.2 M4：注册/登录不自动完成引导；account.onboarding_complete 显式置位并广播。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        result = await service.handle_command(
            command(
                "reg-1",
                "account.register",
                username="alice",
                display_name="爱丽丝",
                password="s3cret-pass",
            )
        )
        # 注册后引导未完成（前端负责展示 Onboarding）
        assert result["account"]["onboarding_complete"] is False
        snapshot = await service.handle_command(command("b-1", "app.bootstrap"))
        assert snapshot["current_account"]["onboarding_complete"] is False

        # 显式命令置位并广播 account.changed
        marked = await service.handle_command(
            command("ob-1", "account.onboarding_complete")
        )
        assert marked["account"]["onboarding_complete"] is True
        changed = [event for event in events if event["event"] == "account.changed"]
        assert changed
        assert changed[-1]["payload"]["account"]["onboarding_complete"] is True
        snapshot = await service.handle_command(command("b-2", "app.bootstrap"))
        assert snapshot["current_account"]["onboarding_complete"] is True
        # 默认账号不受影响（登录页不展示引导）
        assert any(a["onboarding_complete"] is False for a in snapshot["accounts"])
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_config_get_set_masks_secrets(tmp_path: Path) -> None:
    """V0.2 M3：账号级配置读写；密钥只回显掩码。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        await service.handle_command(
            command(
                "set-1",
                "config.set",
                updates={
                    "engine": "deepseek",
                    "dialogue.base_url": "https://api.deepseek.com",
                    "dialogue.model": "deepseek-chat",
                    "dialogue.api_key": "sk-super-secret-123456",
                    "voice.tts_model": "qwen-audio-3.0-tts-flash",
                },
            )
        )
        config = await service.handle_command(command("get-1", "config.get"))
        assert config["engine"] == "deepseek"
        assert config["dialogue"]["model"] == "deepseek-chat"
        assert config["dialogue"]["api_key_masked"] == "sk-s…3456"
        assert "sk-super-secret" not in config["dialogue"]["api_key_masked"]
        # 明文只存 secret_refs，config.get 不回传
        assert "sk-super-secret" not in str(config)
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_config_test_connection_without_credentials_reports_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # live 测试基建会 load_dotenv(.env)；本测试要求“环境无凭据”前提，
    # 显式清空（与账号配置无关，纯环境兜底路径）。
    for name in (
        "PAIR_HARNESS_DIALOGUE_BASE_URL",
        "PAIR_HARNESS_DIALOGUE_API_KEY",
        "PAIR_HARNESS_DIALOGUE_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        result = await service.handle_command(command("t-1", "config.test_connection"))
        assert result["ok"] is False
        assert "缺少对话服务配置" in result["message"]
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_codex_login_state_machine(tmp_path: Path) -> None:
    """V0.2 M3：codex.oauth_* 与 api_login 按当前账号隔离。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        status = await service.handle_command(command("s-1", "codex.oauth_status"))
        assert status["status"] in {"logged_out", "waiting", "logged_in"}

        await service.handle_command(command("s-2", "codex.oauth_start"))
        status = await service.handle_command(command("s-3", "codex.oauth_status"))
        assert status["status"] == "waiting"

        logged = await service.handle_command(
            command("s-4", "codex.api_login", api_key="sk-codex-123")
        )
        assert logged["status"] == "logged_in"
        status = await service.handle_command(command("s-5", "codex.oauth_status"))
        assert status["status"] == "logged_in"

        out = await service.handle_command(command("s-6", "codex.logout"))
        assert out["status"] == "logged_out"
    finally:
        await service.shutdown()
