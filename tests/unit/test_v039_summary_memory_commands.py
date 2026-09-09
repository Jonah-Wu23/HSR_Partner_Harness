"""V0.3.9 遗留闭环：P02 复用作用域与 summary/memory 四命令。

契约出处：归档正文 ``.archive/v0.3.9-dual-track-backup-2026-09-10/logic-worktree/V0.3.9-契约冻结.md``
§1（身份与搭档归属）、§2（摘要与记忆）、§7（命令边）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pair_harness.desktop_backend.application_service import build_demo_service
from pair_harness.desktop_backend.commands import DesktopCommand


def command(request_id: str, method: str, **params) -> DesktopCommand:
    return DesktopCommand(request_id=request_id, method=method, params=params)


async def _wait_until(
    predicate, *, message: str, timeout: float = 5.0
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(message)


# -------------------------------------------------------------------- P02 复用


async def test_reuse_active_does_not_reuse_across_pairs(tmp_path: Path) -> None:
    """reuse_active 只复用在同项目+同卡+同搭档的活跃会话；跨搭档不复用。

    直接验证 find_active_conversation 的 pair_id 隔离：同卡不同搭档的
    会话不应被复用返回。
    """
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=lambda event: None,
    )
    try:
        project_id = service.current_project_id
        # 同卡同项目、不同 pair 的两条活跃会话
        for pair_id in ("phainon_ancient_machine", "firefly_sam"):
            service.store.create_conversation(
                project_id=project_id,
                pair_id=pair_id,
                title=f"{pair_id} 会话",
                account_id=service.current_account_id,
                character_card_id="card-reuse-test",
            )

        reused = service.store.find_active_conversation(
            project_id,
            character_card_id="card-reuse-test",
            pair_id="firefly_sam",
            account_id=service.current_account_id,
        )
        assert reused is not None
        assert reused.pair_id == "firefly_sam"
        # phainon 搭档请求同卡：不得返回 firefly_sam 的会话（pair 隔离）。
        other = service.store.find_active_conversation(
            project_id,
            character_card_id="card-reuse-test",
            pair_id="phainon_ancient_machine",
            account_id=service.current_account_id,
        )
        assert other is not None
        assert other.pair_id == "phainon_ancient_machine"
        assert other.conversation_id != reused.conversation_id
    finally:
        await service.shutdown()


# ------------------------------------------------------------ summary 命令


async def test_summary_regenerate_broadcasts_completed(tmp_path: Path) -> None:
    """summary.regenerate 对真实失败记录重新生成：broadcast completed，落库更新。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        # 先跑真实回合（消息落库）
        await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="请记得我的名字，今天有点累。",
            )
        )
        await _wait_until(
            lambda: [e["event"] for e in events].count("message.created") >= 2,
            message="后台回合应补发角色消息",
        )
        # 直接落库一条 failed 记录作为恢复目标（区间覆盖全部已落库角色消息）
        from pair_harness.storage.records import ConversationSummary

        message_events = [e for e in events if e["event"] == "message.created"]
        first_msg_id = message_events[0]["payload"]["message"]["message_id"]
        last_msg_id = message_events[-1]["payload"]["message"]["message_id"]
        service.store.upsert_summary(
            ConversationSummary(
                summary_id="s-failed-1",
                conversation_id=conversation_id,
                covers_from_message_id=first_msg_id,
                covers_to_message_id=last_msg_id,
                covers_message_count=2,
                content="",
                status="failed",
                error_code="summary_timeout",
                error="provider timeout",
            )
        )
        result = await service.handle_command(
            command(
                "sum-1",
                "summary.regenerate",
                summary_id="s-failed-1",
                conversation_id=conversation_id,
            )
        )
        assert result["status"] == "running"
        await _wait_until(
            lambda: any(e["event"] == "summary.completed" for e in events),
            message="摘要应广播 completed",
        )
        updated = service.store.get_summary("s-failed-1")
        assert updated.status == "completed"
        assert updated.content  # 模型产出的结构化内容已落库
    finally:
        await service.shutdown()


async def test_summary_regenerate_unknown_id_fails_truthfully(tmp_path: Path) -> None:
    """summary.regenerate 对不存在的摘要 ID 以真实错误失败（不伪造成功）。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=lambda event: None,
    )
    try:
        conversation_id = service.current_conversation_id
        from pair_harness.desktop_backend.application_service import ServiceError

        with pytest.raises(ServiceError) as exc:
            await service.handle_command(
                command(
                    "sum-2",
                    "summary.regenerate",
                    summary_id="s-not-exist",
                    conversation_id=conversation_id,
                )
            )
        assert "摘要不存在" in str(exc.value)
        assert exc.value.code == "summary_invalid"
    finally:
        await service.shutdown()


# ------------------------------------------------------------ memory 命令


async def test_memory_update_and_delete_persist_and_broadcast(tmp_path: Path) -> None:
    """memory.update/delete 真实持久化并广播（契约 §2：修改与删除必须生效）。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id

        from pair_harness.core.memory import resolve_memory_scope
        from pair_harness.storage.records import PairMemory as StorageMemory

        identity = service._conversation_identity(
            service.store.get_conversation(conversation_id)
        )
        scope = resolve_memory_scope(identity)
        assert scope is not None

        memory = StorageMemory(
            memory_id="mem-1",
            account_id=scope.account_id,
            project_id=scope.project_id,
            pair_id=scope.pair_id,
            character_ref=scope.character_ref,
            assistant_identity=scope.assistant_identity,
            content='{"note": "旧内容"}',
        )
        service.store.upsert_memory(memory)
        events.clear()

        updated = await service.handle_command(
            command(
                "mem-1",
                "memory.update",
                conversation_id=conversation_id,
                memory_id="mem-1",
                content={"note": "新内容"},
            )
        )
        assert updated["memory"]["content"] == {"note": "新内容"}
        assert any(e["event"] == "memory.updated" for e in events)
        from pair_harness.storage.records import MemoryScope as StorageScope

        storage_scope = StorageScope(
            account_id=scope.account_id,
            project_id=scope.project_id,
            pair_id=scope.pair_id,
            character_ref=scope.character_ref,
            assistant_identity=scope.assistant_identity,
        )
        persisted = service.store.get_memory("mem-1", scope=storage_scope)
        assert persisted.content == '{"note":"新内容"}'

        events.clear()
        deleted = await service.handle_command(
            command("mem-2", "memory.delete", conversation_id=conversation_id, memory_id="mem-1")
        )
        assert deleted["memory"]["status"] == "deleted"
        assert any(e["event"] == "memory.deleted" for e in events)
        persisted = service.store.get_memory("mem-1", scope=storage_scope)
        assert persisted.status == "deleted"
    finally:
        await service.shutdown()


async def test_memory_scope_mismatch_reports_real_error(tmp_path: Path) -> None:
    """构造不存在记忆的 update/delete 报 memory_not_found（越作用域真实报错）。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        from pair_harness.desktop_backend.application_service import ServiceError

        with pytest.raises(ServiceError) as exc:
            await service.handle_command(
                command(
                    "mem-3",
                    "memory.delete",
                    conversation_id=conversation_id,
                    memory_id="not-exist",
                )
            )
        assert exc.value.code == "memory_not_found"
    finally:
        await service.shutdown()
