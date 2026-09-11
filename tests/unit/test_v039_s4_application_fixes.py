"""V0.3.9 S4 修复批次：application_service 车道回归测试。

覆盖 V039-S4-001（只读命令结果不可序列化）：
- 记录层持有 datetime，协议载荷必须按 ISO 8601 文本导出，否则
  ``encode_message`` 抛 ProtocolError；
- Router 在响应不可序列化时必须回执真实失败，而不是把请求静默丢弃
  让调用方等到 backend_timeout。
"""

from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest

from pair_harness.desktop_backend.application_service import build_demo_service
from pair_harness.desktop_backend.commands import DesktopCommand
from pair_harness.desktop_backend.protocol import encode_message, response_ok
from pair_harness.desktop_backend.router import JsonlWriter, SidecarRouter
from pair_harness.storage.records import ConversationSummary


def command(request_id: str, method: str, **params: Any) -> DesktopCommand:
    return DesktopCommand(request_id=request_id, method=method, params=params)


async def _wait_until(predicate, *, message: str, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(message)


async def _run_demo_turn(service, events: list[dict]) -> str:
    conversation_id = service.current_conversation_id
    await service.handle_command(
        command(
            "chat-1",
            "chat.submit",
            conversation_id=conversation_id,
            target="character",
            text="今天有点累，陪我聊聊。",
        )
    )
    await _wait_until(
        lambda: [e["event"] for e in events].count("message.created") >= 2,
        message="后台回合应补发角色消息",
    )
    await asyncio.sleep(0.05)
    return conversation_id


async def test_metrics_query_result_is_protocol_encodable(tmp_path: Path) -> None:
    """metrics.query 结果必须能编码成协议帧：时间戳为 ISO 文本，缺失为 null。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = await _run_demo_turn(service, events)
        result = await service.handle_command(
            command("metrics-1", "metrics.query", conversation_id=conversation_id)
        )
        assert result["metrics"], "真实回合应写入指标"
        metric = result["metrics"][0]
        # 根因：记录层 datetime 直接进载荷 → json.dumps 抛 TypeError。
        assert isinstance(metric["started_at"], str), "started_at 必须是 ISO 文本"
        datetime.fromisoformat(metric["started_at"])
        assert metric["completed_at"] is None or isinstance(
            metric["completed_at"], str
        )
        # 协议帧必须真实可编码（失败会抛 ProtocolError）。
        encode_message(response_ok("metrics-1", result))
    finally:
        await service.shutdown()


async def test_summary_get_result_is_protocol_encodable(tmp_path: Path) -> None:
    """summary.get 结果必须能编码成协议帧（A02 曾整条 30 秒超时）。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = await _run_demo_turn(service, events)
        loaded = service.store.load_conversation(conversation_id)
        messages = loaded["messages"]
        assert len(messages) >= 2
        stored = service.store.upsert_summary(
            ConversationSummary(
                conversation_id=conversation_id,
                covers_from_message_id=messages[0].message_id,
                covers_to_message_id=messages[1].message_id,
                covers_message_count=2,
                content='{"text":"真实模型对语料的概括"}',
                provider="deepseek",
                model="deepseek-v4-flash",
                status="completed",
            )
        )
        result = await service.handle_command(
            command("summary-1", "summary.get", conversation_id=conversation_id)
        )
        assert [item["summary_id"] for item in result["summaries"]] == [
            stored.summary_id
        ]
        payload = result["summaries"][0]
        assert isinstance(payload["created_at"], str)
        assert isinstance(payload["updated_at"], str)
        datetime.fromisoformat(payload["created_at"])
        assert payload["content"] == {"text": "真实模型对语料的概括"}
        encode_message(response_ok("summary-1", result))
    finally:
        await service.shutdown()


async def test_memory_update_result_is_protocol_encodable(tmp_path: Path) -> None:
    """memory.* 响应与 summary/metrics 同源：有数据时同样必须可编码。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = await _run_demo_turn(service, events)
        scope = service._conversation_scope(conversation_id)
        memory = service.store.upsert_memory(
            _memory_for(scope, conversation_id)
        )
        result = await service.handle_command(
            command(
                "memory-1",
                "memory.update",
                conversation_id=conversation_id,
                memory_id=memory.memory_id,
                content={"text": "用户偏好短句"},
            )
        )
        payload = result["memory"]
        assert isinstance(payload["updated_at"], str)
        datetime.fromisoformat(payload["updated_at"])
        encode_message(response_ok("memory-1", result))
    finally:
        await service.shutdown()


def _memory_for(scope, conversation_id: str):
    from pair_harness.storage.records import PairMemory

    return PairMemory(
        account_id=scope.account_id,
        project_id=scope.project_id,
        pair_id=scope.pair_id,
        character_ref=scope.character_ref,
        assistant_identity=scope.assistant_identity,
        content='{"text":"初始记忆"}',
    )


async def test_prompt_assembly_reports_unbound_reason(tmp_path: Path) -> None:
    """V039-S4-011：未绑定卡的会话必须给出可判定原因，不能只有空列表。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        result = await service.handle_command(
            command(
                "diag-unbound",
                "diagnostics.prompt_assembly",
                conversation_id=conversation_id,
            )
        )
        assert result["modules"] == []
        assert result["reason"] == "character_card_unbound"
        assert any("未绑定角色卡" in line for line in result["diagnostics"])
        encode_message(response_ok("diag-unbound", result))
    finally:
        await service.shutdown()


async def test_prompt_assembly_distinguishes_bound_empty_from_unbound(
    tmp_path: Path,
) -> None:
    """V039-S4-011：绑定卡但装配为空必须与未绑定卡可区分。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        draft = await service.handle_command(
            command("card-1", "card.create_draft", name="空草稿卡")
        )
        await service.handle_command(
            command(
                "conv-1",
                "conversation.create",
                character_card_id=draft["card_id"],
            )
        )
        conversation_id = service.current_conversation_id
        conversation = service.store.get_conversation(conversation_id)
        assert conversation.character_card_id == draft["card_id"], (
            "conversation.create 必须绑定 character_card_id，否则本用例无效"
        )
        bound = await service.handle_command(
            command(
                "diag-bound",
                "diagnostics.prompt_assembly",
                conversation_id=conversation_id,
            )
        )
        assert bound["reason"] == "assembly_empty"
        assert bound["reason"] != "character_card_unbound"
        assert any("装配结果为空" in line for line in bound["diagnostics"])
        encode_message(response_ok("diag-bound", bound))
    finally:
        await service.shutdown()


async def test_prompt_assembly_reports_archived_card_reason(tmp_path: Path) -> None:
    """V039-S4-011：绑定卡被归档后必须报「已归档」，不得与「未绑定」混同。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        cards = await service.handle_command(command("cards", "card.list"))
        builtin = next(
            item
            for item in cards["cards"]
            if str(item["card_id"]).startswith("builtin:")
        )
        copy = await service.handle_command(
            command("dup", "card.duplicate", card_id=builtin["card_id"])
        )
        await service.handle_command(
            command(
                "conv-1",
                "conversation.create",
                character_card_id=copy["card_id"],
            )
        )
        conversation_id = service.current_conversation_id
        assert (
            service.store.get_conversation(conversation_id).character_card_id
            == copy["card_id"]
        )
        await service.handle_command(
            command("arch", "card.archive", card_id=copy["card_id"])
        )
        archived = await service.handle_command(
            command(
                "diag-archived",
                "diagnostics.prompt_assembly",
                conversation_id=conversation_id,
            )
        )
        assert archived["modules"] == []
        assert archived["reason"] == "character_card_archived"
        assert any("已归档" in line for line in archived["diagnostics"])
        encode_message(response_ok("diag-archived", archived))
    finally:
        await service.shutdown()


async def test_auto_summary_records_provider_and_model(tmp_path: Path) -> None:
    """V039-S4-013：摘要完成后落库记录与 summary.completed 事件都必须带真实
    供应商与模型标识（未配置模型时按与对话同一口径取供应商默认模型）。"""
    from pair_harness.core.contracts import (
        MessageKind,
        MessageOrigin,
        MessageSource,
    )

    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        for index in range(80):
            service.orchestrator._message(
                conversation_id=conversation_id,
                source=MessageSource.USER,
                kind=MessageKind.USER_TEXT,
                text=f"消息 {index}",
                origin=MessageOrigin.USER,
            )
        await _wait_until(
            lambda: any(e["event"] == "summary.completed" for e in events),
            message="80 条消息应触发自动压缩并广播 completed",
        )
        stored = [
            item
            for item in service.store.list_summaries(conversation_id)
            if item.status == "completed"
        ]
        assert stored, "自动压缩必须落库 completed 记录"
        record = stored[0]
        assert record.provider, "落库摘要必须标注实际供应商"
        assert record.model, "落库摘要必须标注实际模型"
        event = next(e for e in events if e["event"] == "summary.completed")
        assert event["payload"]["provider"] == record.provider
        assert event["payload"]["model"] == record.model
        # 事件载荷与落库同源，必须能真实进入协议帧。
        encode_message(event)
    finally:
        await service.shutdown()


async def test_test_connection_reports_the_probed_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V039-S4-014：探测结论必须可归属——回传实际探测的 provider/base_url/model。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    probed: list[tuple[str, str, str]] = []

    async def fake_probe(base_url: str, api_key: str, model: str) -> dict:
        probed.append((base_url, api_key, model))
        return {"ok": True, "message": "连接正常（延迟 1 ms）"}

    monkeypatch.setattr(service, "_probe_dialogue_connection", fake_probe)
    try:
        await service.handle_command(
            command(
                "cfg-1",
                "config.set",
                updates={
                    "dialogue.provider": "deepseek",
                    "dialogue.base_url": "https://api.deepseek.com",
                    "dialogue.model": "deepseek-v4-flash",
                    "dialogue.api_key": "sk-probe",
                },
            )
        )
        # 演示模式拒绝给出连接结论（V039-S4-002），真实探测另测。
        demo_result = await service.handle_command(
            command("probe-demo", "config.test_connection")
        )
        assert demo_result["ok"] is False
        assert demo_result["provider"] == "demo"
        assert "演示模式" in demo_result["message"]
        assert probed == [], "演示模式不得发起真实探测"

        service._demo = False
        result = await service.handle_command(command("probe-1", "config.test_connection"))
        assert result["ok"] is True
        # 结论必须带上探测目标，否则「连接正常」无法归属到具体端点。
        assert result["base_url"] == "https://api.deepseek.com"
        assert result["provider"] == "deepseek"
        assert result["model"] == "deepseek-v4-flash"
        assert probed == [("https://api.deepseek.com", "sk-probe", "deepseek-v4-flash")]
        encode_message(response_ok("probe-1", result))
    finally:
        service._demo = True
        await service.shutdown()


async def test_incompatible_base_url_write_is_rejected_and_not_dropped(
    tmp_path: Path,
) -> None:
    """V039-S4-014：端点与供应商不一致时必须如实拒绝，且不得留下半写入状态。"""
    from pair_harness.desktop_backend.application_service import ServiceError

    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        await service.handle_command(
            command(
                "cfg-1",
                "config.set",
                updates={
                    "dialogue.provider": "deepseek",
                    "dialogue.base_url": "https://api.deepseek.com",
                    "dialogue.model": "deepseek-v4-flash",
                    "dialogue.api_key": "sk-probe",
                },
            )
        )
        with pytest.raises(ServiceError) as exc:
            await service.handle_command(
                command(
                    "cfg-2",
                    "config.set",
                    updates={
                        "dialogue.provider": "deepseek",
                        "dialogue.base_url": "https://127.0.0.1:1",
                    },
                )
            )
        assert exc.value.code == "provider_endpoint_mismatch"
        # 拒绝就是拒绝：数据库必须保持原值，不存在「返回成功却丢弃字段」。
        assert (
            service.store.get_config(service.current_account_id, "dialogue.base_url")
            == "https://api.deepseek.com"
        )
    finally:
        await service.shutdown()


async def test_rejected_runtime_candidate_reports_config_rejected(
    tmp_path: Path,
) -> None:
    """V039-S4-014：真实模式下候选运行时被拒必须回结构化错误码，不得是 internal_error。"""
    from pair_harness.desktop_backend.application_service import ServiceError

    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        await service.handle_command(
            command(
                "cfg-1",
                "config.set",
                updates={
                    "dialogue.provider": "deepseek",
                    "dialogue.base_url": "https://api.deepseek.com",
                    "dialogue.model": "deepseek-v4-flash",
                    "dialogue.api_key": "sk-probe",
                },
            )
        )
        # 真实模式的候选构建分支：用桩替换，避免任何真实运行时或网络。
        service._demo = False

        def explode(config: dict) -> dict:
            raise RuntimeError("codex 引擎要求 Responses API 后端（桩）")

        service._build_runtime_candidate = explode  # type: ignore[method-assign]
        with pytest.raises(ServiceError) as exc:
            await service.handle_command(
                command(
                    "cfg-2",
                    "config.set",
                    updates={"dialogue.reasoning_effort": "high"},
                )
            )
        assert exc.value.code == "config_rejected"
        assert "Responses API" in str(exc.value)
        assert (
            service.store.get_config(
                service.current_account_id, "dialogue.reasoning_effort"
            )
            is None
        )
    finally:
        service._demo = True
        await service.shutdown()


async def _claim_control(service, device_key: str) -> None:
    claimed = await service.handle_command(
        DesktopCommand(
            request_id=f"claim-{device_key}",
            method="remote.claim_control",
            params={},
            origin="remote",
            connection_key=f"conn-{device_key}",
            remote_device_key=device_key,
        )
    )
    assert claimed == {"claimed": True, "active_controllers": 1}


def _playback_command(method: str, *, origin: str, device_key: str | None) -> DesktopCommand:
    return DesktopCommand(
        request_id=f"play-{method}",
        method=method,
        params={"text": "试听一句话。"} if method != "voice.tts_play" else {"message_id": "m-1"},
        origin=origin,
        connection_key=f"conn-{device_key}" if device_key else None,
        remote_device_key=device_key,
    )


@pytest.mark.parametrize(
    "method", ["voice.tts_play", "voice.preview", "voice.card_preview"]
)
async def test_playback_guard_rejects_desktop_and_other_remote(
    tmp_path: Path, method: str
) -> None:
    """V039-S4-016：租约有效期内，桌面与其他远程设备被拒，持权端不被拒。"""
    from pair_harness.desktop_backend.application_service import ServiceError

    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        await _claim_control(service, "device-holder")

        # 桌面调用方：如实拒绝，且不得把远程端一律称「手机」。
        with pytest.raises(ServiceError) as held:
            await service.handle_command(
                _playback_command(method, origin="desktop", device_key=None)
            )
        assert held.value.code == "remote_playback_active"
        assert "手机" not in str(held.value)

        # 另一台远程设备：不得指向它自己的控制权。
        with pytest.raises(ServiceError) as other:
            await service.handle_command(
                _playback_command(method, origin="remote", device_key="device-other")
            )
        assert other.value.code == "remote_playback_active"
        assert "另一台远程设备" in str(other.value)

        # 租约持有者：守卫放行，后续失败只能是真实原因（演示环境无语音运行时）。
        with pytest.raises(ServiceError) as holder:
            await service.handle_command(
                _playback_command(method, origin="remote", device_key="device-holder")
            )
        assert holder.value.code != "remote_playback_active"
    finally:
        await service.shutdown()


async def test_playback_guard_allows_desktop_after_lease_released(
    tmp_path: Path,
) -> None:
    """V039-S4-016：释放租约后桌面起播恢复（守卫只看调用方与租约）。"""
    from pair_harness.desktop_backend.application_service import ServiceError

    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        await _claim_control(service, "device-holder")
        await service.handle_command(
            DesktopCommand(
                request_id="release-1",
                method="remote.release_control",
                params={},
                origin="remote",
                connection_key="conn-device-holder",
                remote_device_key="device-holder",
            )
        )
        with pytest.raises(ServiceError) as exc:
            await service.handle_command(
                _playback_command("voice.preview", origin="desktop", device_key=None)
            )
        assert exc.value.code == "voice_unavailable"
    finally:
        await service.shutdown()


async def test_memory_create_persists_and_broadcasts(tmp_path: Path) -> None:
    """V039-S4-003：memory.create 是真实写入路径，作用域由会话权威解析。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        created = await service.handle_command(
            command(
                "mem-1",
                "memory.create",
                conversation_id=conversation_id,
                content={"text": "用户偏好短句"},
            )
        )
        payload = created["memory"]
        # 协议载荷是扁平五分量（与前端 TS 对齐），不含嵌套 scope。
        for field in (
            "memory_id",
            "account_id",
            "project_id",
            "pair_id",
            "character_ref",
            "assistant_identity",
            "conversation_id",
            "status",
            "content",
            "updated_at",
        ):
            assert field in payload, f"协议载荷缺少 {field}"
        assert "scope" not in payload
        assert payload["content"] == {"text": "用户偏好短句"}
        assert isinstance(payload["updated_at"], str)
        # 真实写入：读回可见，且广播 memory.updated。
        listed = await service.handle_command(
            command("mem-2", "memory.list", conversation_id=conversation_id)
        )
        assert [item["memory_id"] for item in listed["memories"]] == [
            payload["memory_id"]
        ]
        updated = [e for e in events if e["event"] == "memory.updated"]
        assert len(updated) == 1
        assert updated[0]["payload"]["memory_id"] == payload["memory_id"]
        encode_message(response_ok("mem-1", created))
    finally:
        await service.shutdown()


async def test_memory_create_rejects_missing_or_non_object_content(
    tmp_path: Path,
) -> None:
    """V039-S4-003：缺 conversation_id / content 非对象一律 memory_invalid。"""
    from pair_harness.desktop_backend.application_service import ServiceError

    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        with pytest.raises(ServiceError) as no_conversation:
            await service.handle_command(
                command("mem-1", "memory.create", content={"text": "x"})
            )
        assert no_conversation.value.code == "memory_invalid"
        for bad in (None, "文本", [1, 2], 3, {}):
            with pytest.raises(ServiceError) as bad_content:
                await service.handle_command(
                    command(
                        "mem-2",
                        "memory.create",
                        conversation_id=conversation_id,
                        content=bad,
                    )
                )
            assert bad_content.value.code == "memory_invalid"
        assert service.store.list_memories(
            service._conversation_scope(conversation_id)
        ) == []
    finally:
        await service.shutdown()


async def test_model_memory_drafts_persist_in_conversation_scope(
    tmp_path: Path,
) -> None:
    """V039-S4-003：角色轮产出的记忆条目按会话作用域落库并广播。"""
    from pair_harness.core.contracts import MemoryDraft

    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        drafts = (
            MemoryDraft(content={"text": "用户在写 V0.3.9 修复批次"}),
            MemoryDraft(content={"text": "用户偏好短句"}),
        )
        service._persist_memory_drafts(conversation_id, drafts)
        scope = service._conversation_scope(conversation_id)
        stored = service.store.list_memories(scope)
        assert len(stored) == 2
        assert all(item.status == "active" for item in stored)
        assert all(item.conversation_id == conversation_id for item in stored)
        assert all(item.provider for item in stored)
        assert len([e for e in events if e["event"] == "memory.updated"]) == 2
        # 幂等：同作用域同内容重复落库不新增条目。
        service._persist_memory_drafts(conversation_id, drafts)
        assert len(service.store.list_memories(scope)) == 2
        # 空内容整批拒绝：前面合法条目也不得部分写入。
        partial = (
            MemoryDraft(content={"text": "这条合法"}),
            MemoryDraft.model_construct(content={}),
        )
        before = len(service.store.list_memories(scope))
        service._persist_memory_drafts(conversation_id, partial)
        assert len(service.store.list_memories(scope)) == before
        warnings = [e for e in events if e["event"] == "diagnostic.warning"]
        assert warnings and warnings[-1]["payload"]["source"] == "memory"
    finally:
        await service.shutdown()


async def test_model_memory_without_scope_warns_and_does_not_fail(
    tmp_path: Path,
) -> None:
    """V039-S4-003：无记忆作用域时不得静默丢弃，也不得让整轮失败。"""
    from pair_harness.core.contracts import MemoryDraft

    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    
        event_sink=events.append,
    )
    try:
        # 作用域解析失败（会话不存在）与无项目聊天走同一分支。
        service._persist_memory_drafts(
            "missing-conversation", (MemoryDraft(content={"text": "x"}),)
        )
        warnings = [e for e in events if e["event"] == "diagnostic.warning"]
        assert len(warnings) == 1
        assert warnings[0]["payload"]["source"] == "memory"
        assert warnings[0]["payload"]["count"] == 1
        encode_message(warnings[0])
    finally:
        await service.shutdown()


async def test_runtime_context_exposes_memory_boundary(tmp_path: Path) -> None:
    """V039-S4-003：记忆协议只在有项目的会话提供。"""
    from pair_harness.core.contracts import ProjectRuntimeContext

    # 默认关闭：协议是显式开启的边界，不是默认行为。
    assert ProjectRuntimeContext(conversation_mode="chat").memory_enabled is False
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        context = service.orchestrator._build_runtime_context(
            service.current_conversation_id
        )
        assert context.memory_enabled is True
    finally:
        await service.shutdown()


def test_failure_reason_never_returns_empty_shell() -> None:
    """V039-S4-015：异常自述为空时回落到类型名与结构化字段，不产出空壳。"""
    from pair_harness.desktop_backend.application_service import _failure_reason

    class _Coded(RuntimeError):
        def __init__(self) -> None:
            super().__init__()
            self.code = "provider_error"

    assert _failure_reason(RuntimeError("古代机械未返回最终回复")) == (
        "古代机械未返回最终回复"
    )
    assert _failure_reason(RuntimeError()) == "RuntimeError"
    assert _failure_reason(_Coded()) == "_Coded | code=provider_error"


async def test_turn_failure_notice_carries_real_reason(tmp_path: Path) -> None:
    """V039-S4-015：回合失败提示必须携带真实原因，不能是「本次回复失败：」。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id

        async def explode(**_kwargs):
            raise RuntimeError()

        service.orchestrator.process_character_turn = explode  # type: ignore[assignment]
        await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="这句会失败。",
            )
        )
        await _wait_until(
            lambda: any(
                item["event"] == "turn.status_changed"
                and item["payload"]["turn"].get("status") == "failed"
                for item in events
            ),
            message="回合应进入 failed 终态",
        )
        messages = service.store.load_conversation(conversation_id)["messages"]
        notices = [
            item for item in messages if str(item.kind) == "system.status"
        ]
        assert notices, "失败回合必须留下可见系统提示"
        text = notices[-1].text
        assert text.startswith("本次回复失败：")
        assert text != "本次回复失败："
        assert "RuntimeError" in text
    finally:
        await service.shutdown()


async def test_assistant_segment_requires_content_to_be_persisted(tmp_path: Path) -> None:
    """V039-S4-008：只有思考的段保留为可折叠气泡；两者皆空的段根本不落库。"""
    from pair_harness.core.orchestrator import _SegmentState

    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        pair_id = service.pair_config.pair_id

        def finalize(state) -> Any:
            return service.orchestrator._finalize_segment(
                state,
                conversation_id=conversation_id,
                task_id="task-1",
                engine_turn_id=None,
                pair_id=pair_id,
                delegation_id=None,
                origin=None,
            )

        def assistant_messages() -> list[Any]:
            return [
                item
                for item in service.store.load_conversation(conversation_id)[
                    "messages"
                ]
                if str(item.kind) == "assistant.natural_language"
            ]

        # 正文与思考都为空：不产生消息（历史上被读成「空助手气泡」的那类）。
        blank = _SegmentState(index=0, order=1)
        blank.final_override = ""
        assert finalize(blank) is None
        assert assistant_messages() == []

        # 只有思考：保留为可折叠气泡，payload 携带真实 thinking 文本。
        thinking = _SegmentState(index=1, order=2)
        thinking.final_override = ""
        thinking.reasoning_content.append("先列目录，再写文件")
        assert finalize(thinking) == ""
        kept = assistant_messages()
        assert len(kept) == 1
        assert kept[0].text == ""
        assert kept[0].payload["reasoning"] == "先列目录，再写文件"
        assert str(kept[0].status) == "done"
    finally:
        await service.shutdown()


async def test_remote_serve_address_is_recoverable_and_reported(tmp_path: Path) -> None:
    """V039-S4-004：接入地址随 bootstrap 恢复，并由 remote.issue_code 一并返回。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        # 未监听时：显式 None，调用方不会把「没地址」读成「已就绪」。
        assert service.bootstrap()["remote_serve"] is None
        before = await service.handle_command(command("code-1", "remote.issue_code"))
        assert before["serve_address"] is None
        assert before["code"] and before["ttl_seconds"] == 300

        # 启动路径写入地址后：快照与配对码同源，事件丢失也能恢复。
        address = {"host": "192.168.1.20", "port": 8765}
        service.remote_serve_address = dict(address)
        assert service.bootstrap()["remote_serve"] == address
        after = await service.handle_command(command("code-2", "remote.issue_code"))
        assert after["serve_address"] == address
        encode_message(response_ok("code-2", after))

        # 已监听但无局域网地址：端口保留、host 为 null、附真实原因码，
        # 不伪装成「未启动」。
        no_lan = {"host": None, "port": 8765, "reason": "no_lan_address"}
        service.remote_serve_address = dict(no_lan)
        assert service.bootstrap()["remote_serve"] == no_lan
    finally:
        await service.shutdown()


async def test_voice_error_is_cleared_when_state_recovers(tmp_path: Path) -> None:
    """V039-S4-012：合成恢复与语音关闭都必须清除旧错误，识别错误不受影响。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        # 合成失败：状态机先置 failed，再上报错误 → 记为合成来源。
        service._on_tts_state("failed")
        service._on_voice_error("语音合成失败：Requests rate limit exceeded")
        assert service._voice_snapshot()["error"].startswith("语音合成失败")

        # 真实恢复：新的合成进入播放态，旧限流报文必须消失。
        service._on_tts_state("playing")
        assert service._voice_snapshot()["error"] is None

        # 识别错误不因合成状态变化被抹掉。
        service._on_voice_error("语音识别失败：连接中断")
        service._on_tts_state("idle")
        assert service._voice_snapshot()["error"] == "语音识别失败：连接中断"

        # 语音总开关变化：旧错误不再描述当前状态，一并清除。
        await service.handle_command(
            command("cfg-voice", "config.set", updates={"voice.enabled": "false"})
        )
        assert service._voice_snapshot()["error"] is None
        assert service._voice_snapshot()["enabled"] is False
    finally:
        await service.shutdown()


async def test_mobile_tts_preemption_is_not_reported_as_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V039-S4-018：抢占/停止是正常控制流，不得广播 voice.mobile_tts_failed。"""
    from types import SimpleNamespace

    import pair_harness.adapters.audio.qwen_tts as qwen_tts_module
    from pair_harness.core.contracts import (
        Message,
        MessageKind,
        MessageOrigin,
        MessageSource,
        MessageStatus,
    )

    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    published: list[tuple[str, dict]] = []
    message_id = "speech:test:1"
    try:
        conversation_id = service.current_conversation_id
        message = Message(
            conversation_id=conversation_id,
            pair_id=service.pair_config.pair_id,
            source=MessageSource.CHARACTER,
            kind=MessageKind.CHARACTER_SPEECH,
            text="一段足够长的角色回复。",
            origin=MessageOrigin.CHARACTER_DELEGATION,
            status=MessageStatus.DONE,
            message_id=message_id,
        )
        monkeypatch.setattr(service, "_resolve_mobile_tts_voice_id", lambda *a, **k: "voice-x")
        monkeypatch.setattr(service, "_load_account_config", lambda *a, **k: {"voice.api_key": "sk-test"})
        monkeypatch.setattr(
            service,
            "_publish_remote_only",
            lambda name, payload: published.append((name, payload)),
        )

        class _FakeSynthesizer:
            def __init__(self, **_kwargs) -> None:
                pass

            async def synthesize(self, _request):
                yield SimpleNamespace(pcm=b"\x00\x01")
                # 第二片之前发生抢占：sequencer 已被 stop。
                service._mobile_tts.stop(message_id)
                yield SimpleNamespace(pcm=b"\x02\x03")

            async def aclose(self) -> None:
                return None

        monkeypatch.setattr(qwen_tts_module, "QwenSpeechSynthesizer", _FakeSynthesizer)

        with pytest.raises(asyncio.CancelledError):
            await service._relay_mobile_tts_task(message)
        names = [name for name, _payload in published]
        assert "voice.mobile_tts_failed" not in names
        # 中断前已下发的分片照常保留（真实发生过的事实不撤回）。
        assert names == ["voice.mobile_tts_chunk"]
    finally:
        await service.shutdown()


async def test_mobile_tts_begin_failure_is_reported_not_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V039-S4-018 收尾：begin 抛错必须走同一失败上报路径，不再无人观察地结束。"""
    from types import SimpleNamespace

    import pair_harness.adapters.audio.qwen_tts as qwen_tts_module
    from pair_harness.core.contracts import (
        Message,
        MessageKind,
        MessageOrigin,
        MessageSource,
        MessageStatus,
    )
    from pair_harness.desktop_backend.mobile_audio import MobileAudioError

    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    published: list[tuple[str, dict]] = []
    try:
        conversation_id = service.current_conversation_id
        message = Message(
            conversation_id=conversation_id,
            pair_id=service.pair_config.pair_id,
            source=MessageSource.CHARACTER,
            kind=MessageKind.CHARACTER_SPEECH,
            text="重复 id 的角色回复。",
            origin=MessageOrigin.CHARACTER_DELEGATION,
            status=MessageStatus.DONE,
            message_id="speech:dup:1",
        )
        monkeypatch.setattr(service, "_resolve_mobile_tts_voice_id", lambda *a, **k: "voice-x")
        monkeypatch.setattr(service, "_load_account_config", lambda *a, **k: {"voice.api_key": "sk-test"})
        monkeypatch.setattr(service, "_publish_remote_only", lambda name, payload: published.append((name, payload)))

        def explode(*_args, **_kwargs) -> None:
            raise MobileAudioError("voice_tts_message_exists", "TTS 消息已存在")

        monkeypatch.setattr(service._mobile_tts, "begin", explode)

        class _FakeSynthesizer:
            def __init__(self, **_kwargs) -> None:
                pass

            async def synthesize(self, _request):
                yield SimpleNamespace(pcm=b"\x00\x01")

            async def aclose(self) -> None:
                return None

        monkeypatch.setattr(qwen_tts_module, "QwenSpeechSynthesizer", _FakeSynthesizer)

        # 不抛异常：失败被如实上报，调用方（移动端）据此退出播放状态。
        await service._relay_mobile_tts_task(message)
        assert [name for name, _ in published] == ["voice.mobile_tts_failed"]
        assert "TTS 消息已存在" in published[0][1]["error"]
    finally:
        await service.shutdown()


class _UnserializableService:
    """返回不可编码结果的桩服务：模拟记录层 datetime 泄漏到协议层。"""

    async def handle_command(self, command: DesktopCommand) -> Mapping[str, Any]:
        return {"leaked": datetime.now(timezone.utc)}


async def test_router_reports_unserializable_response_instead_of_timeout() -> None:
    """响应不可序列化时必须回执 encode_error，不得静默丢弃请求。"""
    stream = io.StringIO()
    router = SidecarRouter(_UnserializableService(), JsonlWriter(stream))
    await router.handle_line('{"kind":"request","id":"r-1","method":"ping","params":{}}')
    line = stream.getvalue().strip()
    assert line, "不可序列化响应必须留下回执帧"
    import json

    frame = json.loads(line)
    assert frame["kind"] == "response"
    assert frame["id"] == "r-1"
    assert frame["ok"] is False
    assert frame["error"]["code"] == "encode_error"
    assert "datetime" in frame["error"]["message"]
