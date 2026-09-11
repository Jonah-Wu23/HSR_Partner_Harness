"""V0.3.9 提示词装配接缝：摘要与 active 记忆必须真正进入角色 system 提示词。

三个经审查确认的缺陷都落在 ``DesktopApplicationService._resolve_character_prompt``
这条接缝上，这里逐条锁定：

1. completed 摘要必须以 core ``ConversationSummary`` 流进装配器——以 dict 流入时
   ``_summary_module`` 读 ``.status`` 抛 AttributeError，绑定卡的会话每轮都在发
   模型请求前崩；
2. 未绑定角色卡的会话在有 completed 摘要时同样要装配：投影已经按
   ``ROLE_CONTEXT_LIMIT_AFTER_SUMMARY`` 收窄原文窗口，摘要再不注入，旧历史就
   既不发原文也不发摘要；
3. active 长期记忆必须按会话作用域注入；无项目会话没有记忆作用域，按无记忆
   跳过，不让回合失败。

测试用真实 SQLite 临时库、真实装配器与真实对话适配器装配路径（不发 HTTP）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.core.contracts import (
    DialogueRequest,
    Message,
    MessageKind,
    MessageOrigin,
    MessageSource,
    ProjectRuntimeContext,
)
from pair_harness.core.summary import ConversationSummary
from pair_harness.desktop_backend.application_service import (
    ServiceError,
    build_demo_service,
)
from pair_harness.desktop_backend.commands import DesktopCommand
from pair_harness.storage.records import ConversationSummary as StorageSummary
from pair_harness.storage.records import PairMemory as StorageMemory

PAIR_ID = "phainon_ancient_machine"
CARD_DESCRIPTION = "【设定】金色麦田与不肯熄灭的火种。"
DEFAULT_TIMEOUT_S = 5.0


@pytest.fixture
def service(tmp_path: Path):
    svc = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        pair_id=PAIR_ID,
    )
    yield svc
    svc.store.close()


async def _call(service, request_id: str, method: str, **params: Any) -> Any:
    command = DesktopCommand(
        request_id=request_id, method=method, params=params, origin="desktop"
    )
    return await asyncio.wait_for(
        service.handle_command(command), timeout=DEFAULT_TIMEOUT_S
    )


async def _publish_card(service) -> str:
    created = await _call(service, "seam-draft", "card.create_draft", name="接缝角色")
    card_id = created["card_id"]
    await _call(
        service,
        "seam-update",
        "card.update",
        card_id=card_id,
        card={
            "name": "接缝角色",
            "description": CARD_DESCRIPTION,
            "first_mes": "晚上好呀。",
        },
    )
    await _call(service, "seam-publish", "card.publish", card_id=card_id)
    return card_id


async def _bind_card_conversation(service) -> str:
    """发布一张卡、选为 active 并新建绑定会话，返回 conversation_id。"""
    card_id = await _publish_card(service)
    await _call(service, "seam-select", "card.select_active", card_id=card_id)
    await _call(
        service,
        "seam-conversation",
        "conversation.create",
        project_id=service.current_project_id,
    )
    return service.current_conversation_id


def _append_role_messages(service, conversation_id: str, count: int = 2) -> None:
    """补足真实角色消息：摘要覆盖区间必须落在真实消息上。"""
    for index in range(count):
        service.orchestrator._message(
            conversation_id=conversation_id,
            source=MessageSource.USER,
            kind=MessageKind.USER_TEXT,
            text=f"第 {index + 1} 条消息",
            origin=MessageOrigin.USER,
        )


def _insert_completed_summary(
    service, conversation_id: str, *, content: dict
) -> str:
    """直接落库一条 completed 摘要（覆盖区间取会话内真实消息）。"""
    messages = service.store.load_conversation(conversation_id)["messages"]
    assert messages, "写摘要前会话必须有真实消息"
    summary_id = f"summary-{conversation_id}"
    service.store.upsert_summary(
        StorageSummary(
            summary_id=summary_id,
            conversation_id=conversation_id,
            covers_from_message_id=messages[0].message_id,
            covers_to_message_id=messages[-1].message_id,
            covers_message_count=len(messages),
            content=json.dumps(content, ensure_ascii=False, sort_keys=True),
            status="completed",
        )
    )
    return summary_id


def _store_active_memory(service, conversation_id: str, content: dict) -> None:
    """按会话权威作用域直接落库一条 active 记忆（content 为 JSON 文本）。"""
    scope = service._conversation_scope(conversation_id)
    service.store.upsert_memory(
        StorageMemory(
            account_id=scope.account_id,
            project_id=scope.project_id,
            pair_id=scope.pair_id,
            character_ref=scope.character_ref,
            assistant_identity=scope.assistant_identity,
            conversation_id=conversation_id,
            content=json.dumps(content, ensure_ascii=False, sort_keys=True),
        )
    )


def _character_system_text(service, conversation_id: str) -> str:
    """走真实对话适配器的装配路径取角色侧 system 文本（不发 HTTP 请求）。"""
    model = OpenAICompatibleDialogueModel(
        base_url="https://example.invalid/v1",
        model="test-model",
        character_prompt_resolver=service._resolve_character_prompt,
    )
    request = DialogueRequest(
        pair_id=PAIR_ID,
        conversation_id=conversation_id,
        user_message=Message(
            conversation_id=conversation_id,
            pair_id=PAIR_ID,
            source=MessageSource.USER,
            kind=MessageKind.USER_TEXT,
            text="我们之前约定了什么？",
            origin=MessageOrigin.USER,
        ),
        runtime_context=ProjectRuntimeContext(
            project_name="接缝测试项目",
            project_abs_dir="E:/seam-test",
            conversation_mode="collaboration",
        ),
    )
    return model.build_messages(request)[0]["content"]


# ---------------------------------------------------------------- 缺陷 1


async def test_bound_card_with_completed_summary_assembles_summary_module(
    service,
) -> None:
    """绑定卡 + completed 摘要：接缝返回 core 摘要对象，装配含 chat_summary。"""
    conversation_id = await _bind_card_conversation(service)
    summary_id = _insert_completed_summary(
        service, conversation_id, content={"剧情": "两人在雨夜相遇"}
    )

    latest = service._recent_completed_summary(conversation_id)
    assert isinstance(latest, ConversationSummary)
    assert latest.status == "completed"

    assembled = service._resolve_character_prompt(conversation_id)
    assert assembled is not None
    kinds = [module.kind for module in assembled.modules]
    assert "chat_summary" in kinds
    assert assembled.diagnostics["summary"]["injected"] is True
    assert assembled.diagnostics["summary"]["summary_id"] == summary_id
    assert "两人在雨夜相遇" in assembled.system_text
    assert CARD_DESCRIPTION in assembled.system_text


# ---------------------------------------------------------------- 缺陷 2


async def test_unbound_conversation_summary_reaches_model_system_prompt(
    service,
) -> None:
    """未绑定卡的会话：有 completed 摘要时用内置角色基座装配并送进模型。"""
    conversation_id = service.current_conversation_id
    assert service.store.get_conversation(conversation_id).character_card_id is None
    _append_role_messages(service, conversation_id)
    # 没有摘要时保持既有回退（resolver 返回 None，走内置 YAML 提示词）。
    assert service._resolve_character_prompt(conversation_id) is None

    _insert_completed_summary(
        service, conversation_id, content={"长期约定": "不再提旧事"}
    )

    system = _character_system_text(service, conversation_id)
    assert "长期约定" in system and "不再提旧事" in system
    # 内置角色基座 + 搭档表达配置 + 输出协议三段来源保持现状
    assert "你扮演 白厄。" in system
    assert "神秘的古代机械" in system
    assert '"type": "task"' in system


# ---------------------------------------------------------------- 缺陷 3


async def test_active_memory_reaches_bound_card_assembly(service) -> None:
    """绑定卡会话：active 记忆进入装配诊断与 system_text。"""
    conversation_id = await _bind_card_conversation(service)
    _store_active_memory(service, conversation_id, {"喜好": "安静的地方"})

    assembled = service._resolve_character_prompt(conversation_id)
    assert assembled is not None
    assert assembled.diagnostics["memory"]["injected"] is True
    assert assembled.diagnostics["memory"]["count"] == 1
    assert "安静的地方" in assembled.system_text


async def test_active_memory_reaches_unbound_conversation_prompt(service) -> None:
    """未绑定卡的会话按 builtin:<角色 id> 作用域读到同一条记忆。"""
    conversation_id = service.current_conversation_id
    scope = service._conversation_scope(conversation_id)
    assert scope.character_ref == "builtin:phainon"
    _store_active_memory(service, conversation_id, {"称呼": "并肩的伙伴"})

    system = _character_system_text(service, conversation_id)
    assert "称呼" in system and "并肩的伙伴" in system


async def test_conversation_without_project_skips_memories_without_failing(
    service,
) -> None:
    """无项目会话没有记忆作用域：按无记忆继续，装配不发模型请求就失败。"""
    conversation = service.store.create_conversation(
        pair_id=PAIR_ID,
        project_id=None,
        account_id=service.current_account_id,
    )
    # 作用域缺失本身是真实错误（记忆命令据此如实报错），装配侧只跳过记忆。
    with pytest.raises(ServiceError):
        service._conversation_scope(conversation.conversation_id)

    assert service._resolve_character_prompt(conversation.conversation_id) is None

    card_id = await _publish_card(service)
    bound = service.store.create_conversation(
        pair_id=PAIR_ID,
        project_id=None,
        account_id=service.current_account_id,
        character_card_id=card_id,
    )
    assembled = service._resolve_character_prompt(bound.conversation_id)
    assert assembled is not None
    assert assembled.diagnostics["memory"]["injected"] is False
    assert CARD_DESCRIPTION in assembled.system_text
