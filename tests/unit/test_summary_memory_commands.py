from __future__ import annotations

import pytest

from pair_harness.core.contracts import CharacterTurn, MemoryDraft
from pair_harness.core.orchestrator import Runtime
from pair_harness.desktop_backend.protocol import encode_message, response_ok
from pair_harness.storage.records import ConversationSummary as StorageSummary
from pair_harness.storage.records import MemoryScope as StorageMemoryScope
from tests.fakes import FixedDialogueModel
from tests.service_helpers import call, expect_service_error, wait_until

PAIR_ID = "phainon_ancient_machine"
_SCOPE_FIELDS = ("account_id", "project_id", "pair_id", "character_ref", "assistant_identity")


async def test_summary_regenerate_completes_failed_record(service) -> None:
    conversation_id = service.current_conversation_id
    for text in ("请记得我的名字", "今天有点累"):
        await service.orchestrator.submit_user_message(
            conversation_id=conversation_id, text=text, target="character", pair_id=PAIR_ID
        )
    messages = service.store.load_conversation(conversation_id).messages
    service.store.upsert_summary(
        StorageSummary(
            summary_id="s-failed-1",
            conversation_id=conversation_id,
            covers_from_message_id=messages[0].message_id,
            covers_to_message_id=messages[-1].message_id,
            covers_message_count=2,
            content="",
            status="failed",
            error_code="summary_timeout",
            error="provider timeout",
        )
    )

    result = await call(
        service,
        "summary-regenerate",
        "summary.regenerate",
        summary_id="s-failed-1",
        conversation_id=conversation_id,
    )
    assert result["status"] == "running"
    await wait_until(
        lambda: service.event_log.payloads("summary.completed"),
        message="重新生成应广播 summary.completed",
    )

    listed = await call(service, "summary-get", "summary.get", conversation_id=conversation_id)
    [summary] = listed["summaries"]
    assert (summary["summary_id"], summary["status"]) == ("s-failed-1", "completed")
    assert isinstance(summary["content"], dict) and summary["content"]
    assert summary["error_code"] is None
    encode_message(response_ok("summary-get", listed))


async def test_summary_regenerate_unknown_summary_fails(service) -> None:
    await expect_service_error(
        lambda: call(
            service,
            "summary-regenerate",
            "summary.regenerate",
            summary_id="s-not-exist",
            conversation_id=service.current_conversation_id,
        ),
        "summary_invalid",
        contains="摘要不存在",
    )


async def test_memory_commands_persist_and_broadcast(service) -> None:
    conversation_id = service.current_conversation_id
    created = await call(
        service,
        "memory-create",
        "memory.create",
        conversation_id=conversation_id,
        content={"text": "用户偏好短句"},
    )
    memory = created["memory"]
    # 协议载荷扁平携带五分量作用域，不含嵌套 scope
    assert {*_SCOPE_FIELDS, "conversation_id", "updated_at"} <= memory.keys()
    assert "scope" not in memory
    assert (memory["status"], memory["content"]) == ("active", {"text": "用户偏好短句"})
    encode_message(response_ok("memory-create", created))
    memory_id = memory["memory_id"]

    listed = await call(service, "memory-list", "memory.list", conversation_id=conversation_id)
    assert [item["memory_id"] for item in listed["memories"]] == [memory_id]

    updated = await call(
        service,
        "memory-update",
        "memory.update",
        conversation_id=conversation_id,
        memory_id=memory_id,
        content={"text": "用户偏好长句"},
    )
    assert updated["memory"]["content"] == {"text": "用户偏好长句"}
    assert [payload["content"] for payload in service.event_log.payloads("memory.updated")] == [
        {"text": "用户偏好短句"},
        {"text": "用户偏好长句"},
    ]

    deleted = await call(
        service,
        "memory-delete",
        "memory.delete",
        conversation_id=conversation_id,
        memory_id=memory_id,
    )
    assert deleted["memory"]["status"] == "deleted"
    assert [payload["memory_id"] for payload in service.event_log.payloads("memory.deleted")] == [
        memory_id
    ]
    active = await call(
        service, "memory-active", "memory.list", conversation_id=conversation_id, status="active"
    )
    assert active["memories"] == []
    removed = await call(
        service, "memory-deleted", "memory.list", conversation_id=conversation_id, status="deleted"
    )
    assert [(item["memory_id"], item["content"]) for item in removed["memories"]] == [
        (memory_id, {"text": "用户偏好长句"})
    ]


async def test_memory_list_without_status_returns_only_active(service) -> None:
    conversation_id = service.current_conversation_id
    memory_ids = []
    for index, text in enumerate(("保留", "删除")):
        created = await call(
            service,
            f"memory-create-{index}",
            "memory.create",
            conversation_id=conversation_id,
            content={"text": text},
        )
        memory_ids.append(created["memory"]["memory_id"])
    kept, removed = memory_ids
    await call(
        service, "memory-delete", "memory.delete", conversation_id=conversation_id, memory_id=removed
    )

    listed = await call(service, "memory-list", "memory.list", conversation_id=conversation_id)
    assert [item["memory_id"] for item in listed["memories"]] == [kept]


@pytest.mark.parametrize(
    ("method", "with_conversation", "params", "code"),
    [
        ("memory.create", False, {"content": {"text": "x"}}, "memory_invalid"),
        ("memory.create", True, {"content": None}, "memory_invalid"),
        ("memory.create", True, {"content": "文本"}, "memory_invalid"),
        ("memory.create", True, {"content": [1, 2]}, "memory_invalid"),
        ("memory.create", True, {"content": 3}, "memory_invalid"),
        ("memory.create", True, {"content": {}}, "memory_invalid"),
        ("memory.delete", True, {"memory_id": "not-exist"}, "memory_not_found"),
    ],
    ids=[
        "create_without_conversation",
        "create_null_content",
        "create_text_content",
        "create_list_content",
        "create_number_content",
        "create_empty_object",
        "delete_unknown_memory",
    ],
)
async def test_memory_commands_reject_invalid_requests(
    service, method: str, with_conversation: bool, params: dict, code: str
) -> None:
    conversation_id = service.current_conversation_id
    if with_conversation:
        params = {**params, "conversation_id": conversation_id}
    await expect_service_error(lambda: call(service, "memory", method, **params), code)
    listed = await call(service, "memory-list", "memory.list", conversation_id=conversation_id)
    assert listed["memories"] == []


def _finished_turn_statuses(service) -> list[str]:
    return [
        payload["turn"]["status"]
        for payload in service.event_log.payloads("turn.status_changed")
        if payload["turn"]["status"] in ("completed", "failed", "cancelled")
    ]


async def test_character_turn_memory_drafts_persist_in_conversation_scope(service) -> None:
    drafts = (
        MemoryDraft(content={"text": "用户在整理旧照片"}),
        MemoryDraft(content={"text": "用户偏好短句"}),
    )
    service.orchestrator.install_runtime(
        Runtime(
            dialogue_model=FixedDialogueModel(
                CharacterTurn(speech="记下了。", memory=drafts),
                CharacterTurn(speech="还记得。", memory=drafts),
            ),
            coding_engine=service.coding_engine,
            reviewer=None,
        )
    )
    conversation_id = service.current_conversation_id

    for index, text in enumerate(("帮我记住这些", "再说一遍"), start=1):
        await call(
            service,
            f"chat-{index}",
            "chat.submit",
            conversation_id=conversation_id,
            target="character",
            text=text,
        )
        await wait_until(
            lambda: len(_finished_turn_statuses(service)) == index,
            message="角色回合应结束",
        )
        assert _finished_turn_statuses(service) == ["completed"] * index
        listed = await call(
            service, f"memory-list-{index}", "memory.list", conversation_id=conversation_id
        )
        # 同作用域同内容重复落库不新增条目
        assert sorted(item["content"]["text"] for item in listed["memories"]) == [
            "用户偏好短句",
            "用户在整理旧照片",
        ]
        assert {item["conversation_id"] for item in listed["memories"]} == {conversation_id}

    scope = StorageMemoryScope(**{field: listed["memories"][0][field] for field in _SCOPE_FIELDS})
    assert all(record.provider for record in service.store.list_memories(scope))
