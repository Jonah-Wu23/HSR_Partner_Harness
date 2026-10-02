from __future__ import annotations

import httpx
import pytest

from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.core.orchestrator import Runtime
from pair_harness.desktop_backend.application_service import build_demo_service
from pair_harness.desktop_backend.protocol import encode_message
from tests.service_helpers import wait_until

PAIR_ID = "phainon_ancient_machine"


async def _submit_user_messages(service, texts: list[str]) -> None:
    """经编排器落库用户消息（不跑角色回合）；每条落库后服务做一次自动压缩判定。"""
    for text in texts:
        await service.orchestrator.submit_user_message(
            conversation_id=service.current_conversation_id,
            text=text,
            target="character",
            pair_id=PAIR_ID,
        )


def _chat_completion_transport(content: str) -> httpx.MockTransport:
    """回放非流式 Chat Completions 响应，choices[0].message.content 为给定正文。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-summary",
                "object": "chat.completion",
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(
    "texts",
    [
        [f"消息 {index}" for index in range(81)],
        # 单条约 12 KiB，第 22 条越过 256 KiB，其后两条落在压缩在途期间
        [f"{index}:" + "字" * 4096 for index in range(24)],
    ],
    ids=["message_count", "utf8_bytes"],
)
async def test_auto_summary_runs_once_at_threshold_and_records_model(
    service, texts: list[str]
) -> None:
    await _submit_user_messages(service, texts)
    await wait_until(
        lambda: service.event_log.payloads("summary.completed"),
        message="达到阈值后自动压缩应广播 summary.completed",
    )
    # 压缩在途期间到达的消息不重复触发
    assert len(service.event_log.payloads("summary.started")) == 1
    conversation_id = service.current_conversation_id
    [record] = service.store.list_summaries(conversation_id, status="completed")
    assert record.provider and record.model
    completed = next(
        item for item in service.event_log.items if item["event"] == "summary.completed"
    )
    assert completed["payload"]["provider"] == record.provider
    assert completed["payload"]["model"] == record.model
    encode_message(completed)
    assert service.orchestrator.summary_coverage(conversation_id) == record.covers_to_message_id


async def test_auto_summary_failure_keeps_provider_error(service) -> None:
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1/v1", transport=_chat_completion_transport("null")
    ) as client:
        service.orchestrator.install_runtime(
            Runtime(
                dialogue_model=OpenAICompatibleDialogueModel(
                    base_url="http://127.0.0.1/v1", model="test-model", client=client
                ),
                coding_engine=service.coding_engine,
                reviewer=None,
            )
        )
        await _submit_user_messages(service, [f"消息 {index}" for index in range(80)])
        await wait_until(
            lambda: service.event_log.payloads("summary.failed"),
            message="模型正文不是 JSON 对象时应广播 summary.failed",
        )
    [failed] = service.event_log.payloads("summary.failed")
    assert failed["error_code"] == "summary_provider_error"
    assert "不是 JSON 对象" in failed["error"]
    assert service.orchestrator.summary_coverage(service.current_conversation_id) is None


async def test_summary_coverage_is_restored_after_restart(service) -> None:
    await _submit_user_messages(service, [f"消息 {index}" for index in range(80)])
    await wait_until(
        lambda: service.event_log.payloads("summary.completed"),
        message="自动压缩应完成",
    )
    conversation_id = service.current_conversation_id
    covered_to = service.orchestrator.summary_coverage(conversation_id)
    assert covered_to is not None
    await service.shutdown()

    restarted = build_demo_service(
        database=service.tmp_path / "data" / "pair_harness.db",
        project_root=service.tmp_path,
    )
    try:
        assert restarted.orchestrator.summary_coverage(conversation_id) == covered_to
    finally:
        await restarted.shutdown()
