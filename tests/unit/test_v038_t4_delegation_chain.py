"""V0.3.8 T4：委派执行链修复的回归测试（真机验收 C4）。

覆盖（docs/plans/V0.3.8-修复实施计划.md §2 T4、契约 §14.1/§14.6）：
- 模型供给断点（方案 B）：codex 引擎拒绝非 Responses 兼容后端；OPENAI_BASE_URL
  误配注入移除（codex-cli 不跟随该变量，注入只会静默打向不可达端点）。
- 可观测性：回合无进展 60s 节流 diagnostic.warning；idle 超时错误携带
  app-server stderr 摘要；codec 未识别 method 结构化 WARNING。
- 审批超时（approval_timeout）：释放 pending，迟到应答如实报不存在。
- 队列前进（契约 §14.1）：cancelled/failed 终态后队列立即派发下一条，
  排队项不回退 queued；task.cancel 不清空队列。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from pair_harness.adapters.codex.codec import CodexCodec, EventBinding
from pair_harness.adapters.codex.engine import (
    NO_PROGRESS_ALERT_INTERVAL_S,
    CodexAppServerEngine,
)
from pair_harness.adapters.acp.engine import AcpCodingEngine
from pair_harness.core.contracts import EngineEventType, PendingOperation
from pair_harness.desktop_backend import application_service as app_service_module
from pair_harness.desktop_backend.application_service import ServiceError
from pair_harness.desktop_backend.engine_factory import (
    build_codex_transport,
    build_coding_engine,
)

# 复用 test_v035_wiring 的 command 辅助与 service 夹具（pytest 同目录导入）
from test_v035_wiring import command, service  # noqa: F401


# ---- 模型供给断点（方案 B） ----


class _RecordingCreate:
    """捕获 SubprocessJsonLineConnection.create 的调用参数。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, executable: str, args=None, env=None, **kwargs: Any):
        self.calls.append({"executable": executable, "args": args, "env": env})

        class _FakeConnection:
            async def read_line(self) -> bytes:
                await asyncio.sleep(3600)
                return b""

            async def write_line(self, data: bytes) -> None:
                return None

            async def close(self) -> None:
                return None

        return _FakeConnection()


def test_codex_engine_rejects_non_responses_backend() -> None:
    """codex 引擎 × DeepSeek 端点必须装配失败并说明处置建议，不得静默误配。"""
    with pytest.raises(RuntimeError) as excinfo:
        build_coding_engine(
            engine_choice="codex",
            codex_auth=_FakeCodexAuth(),
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            api_key="sk-test",
        )
    message = str(excinfo.value)
    assert "Responses" in message
    assert "reasonix" in message


def test_codex_engine_allows_openai_official_backend() -> None:
    """OpenAI 官方端点（Responses 兼容）不拦截。"""
    engine = build_coding_engine(
        engine_choice="codex",
        codex_auth=_FakeCodexAuth(),
        base_url="https://api.openai.com/v1",
    )
    assert isinstance(engine, CodexAppServerEngine)


def test_codex_engine_allows_empty_base_url_for_oauth() -> None:
    """base_url 为空表示走 codex 自身 OAuth 登录态，放行。"""
    engine = build_coding_engine(engine_choice="codex", codex_auth=_FakeCodexAuth())
    assert isinstance(engine, CodexAppServerEngine)


@pytest.mark.asyncio
async def test_codex_transport_no_longer_injects_openai_env(monkeypatch) -> None:
    """OPENAI_BASE_URL/OPENAI_API_KEY 不再注入（codex 0.147 不跟随，纯误导）。"""
    recorder = _RecordingCreate()
    monkeypatch.setattr(
        "pair_harness.adapters.codex.transport.SubprocessJsonLineConnection.create",
        recorder,
    )
    transport = build_codex_transport(
        codex_auth=_FakeCodexAuth(),
        base_url="https://api.deepseek.com",
        api_key="sk-test",
    )
    await transport.start()
    env = recorder.calls[0]["env"]
    assert "OPENAI_BASE_URL" not in env
    assert "OPENAI_API_KEY" not in env


def test_build_coding_engine_forwards_diagnostic_callback() -> None:
    """诊断回调从装配方透传到 CodexAppServerEngine（契约 §14.6）。"""
    received: list[dict[str, Any]] = []
    engine = build_coding_engine(
        engine_choice="codex",
        codex_auth=_FakeCodexAuth(),
        diagnostic_callback=received.append,
    )
    assert isinstance(engine, CodexAppServerEngine)
    engine.diagnostic_callback({"code": "engine_no_progress", "message": "x"})
    assert received == [{"code": "engine_no_progress", "message": "x"}]


def test_deepseek_engine_forwards_diagnostic_callback() -> None:
    """DeepSeek 实际装配路径同样透传无进展诊断出口。"""
    received: list[dict[str, Any]] = []
    engine = build_coding_engine(
        engine_choice="deepseek",
        codex_auth=_FakeCodexAuth(),
        diagnostic_callback=received.append,
        codex_idle_timeout=123.0,
    )
    engine.diagnostic_callback({"code": "engine_no_progress", "message": "x"})
    assert received == [{"code": "engine_no_progress", "message": "x"}]
    assert engine.idle_timeout == 123.0


class _SilentAcpSubscription:
    async def next(self) -> dict[str, Any]:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    def close(self) -> None:
        return None


class _SilentAcpTransport:
    generation = 1

    def __init__(self) -> None:
        self.cancellations: list[dict[str, Any]] = []

    def subscribe_session(self, session_id: str) -> _SilentAcpSubscription:
        assert session_id == "session-1"
        return _SilentAcpSubscription()

    async def request(
        self, method: str, params: dict[str, Any] | None = None, timeout=None
    ) -> dict[str, Any]:
        assert method == "session/prompt"
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        assert method == "session/cancel"
        self.cancellations.append(params)

    def stderr_tail(self, limit: int = 6) -> str:
        return "reasonix upstream retrying"


@pytest.mark.asyncio
async def test_deepseek_no_progress_alerts_then_idle_timeout(monkeypatch) -> None:
    """Reasonix 静默时持续告警，达到上限后取消真实回合并失败。"""
    monkeypatch.setattr(
        "pair_harness.adapters.acp.engine.NO_PROGRESS_ALERT_INTERVAL_S", 0.05
    )
    transport = _SilentAcpTransport()
    diagnostics: list[dict[str, Any]] = []
    engine = AcpCodingEngine(
        transport,
        idle_timeout=0.16,
        diagnostic_callback=diagnostics.append,
    )
    from pair_harness.core.contracts import TaskRequest

    events = [
        event
        async for event in engine.run_turn(
            engine._encode_ref("session-1"),
            TaskRequest(
                conversation_id="conv",
                origin_message_id="msg",
                instructions="执行委派",
            ),
        )
    ]

    assert len(diagnostics) >= 2
    assert all(item["source"] == "reasonix-acp" for item in diagnostics)
    assert events[-1].type == EngineEventType.TURN_FAILED
    assert events[-1].payload["original_error"] == "idle timeout"
    assert events[-1].payload["stderr_tail"] == "reasonix upstream retrying"
    assert transport.cancellations == [{"sessionId": "session-1"}]


class _FakeCodexAuth:
    """build_coding_engine 只需要 base_dir/account_id 与 env_overrides。"""

    def __init__(self) -> None:
        from pathlib import Path

        self.base_dir = Path(".")
        self.account_id = "test-account"

    @property
    def env_overrides(self) -> dict[str, str]:
        return {"CODEX_HOME": "unused"}


# ---- 回合无进展告警 + idle 超时携带 stderr ----


class _HangingTransport:
    """next_notification 永久挂起的 fake transport（模拟 app-server 静默）。"""

    generation = 1

    def __init__(self) -> None:
        self.interrupts: list[dict[str, Any]] = []
        self.stderr = ""

    async def request(
        self, method: str, params: dict[str, Any] | None = None, timeout=None
    ) -> dict[str, Any]:
        if method == "turn/start":
            return {"turn": {"id": "native-1"}}
        if method == "turn/interrupt":
            self.interrupts.append(params or {})
            return {}
        raise AssertionError(f"unexpected request: {method}")

    async def next_notification(self) -> dict[str, Any]:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    def stderr_tail(self, limit: int = 6) -> str:
        return self.stderr


def _make_engine(
    transport: _HangingTransport,
    idle_timeout: float,
    diagnostics: list[dict[str, Any]],
) -> CodexAppServerEngine:
    return CodexAppServerEngine(
        transport,  # type: ignore[arg-type]
        model="test-model",
        idle_timeout=idle_timeout,
        diagnostic_callback=diagnostics.append,
    )


async def _drain_turn(engine: CodexAppServerEngine) -> list[Any]:
    from pair_harness.core.contracts import EngineSessionRef, TaskRequest

    ref = engine._encode_ref("thread-1")
    request = TaskRequest(
        conversation_id="conv",
        origin_message_id="msg-1",
        instructions="测试指令",
    )
    events = []
    async for event in engine.run_turn(ref, request):
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_no_progress_alerts_fire_every_interval_then_idle(
    monkeypatch,
) -> None:
    """每 60s（测试压缩为 0.1s）无事件发一次 diagnostic.warning，节流可预期。"""
    monkeypatch.setattr(
        "pair_harness.adapters.codex.engine.NO_PROGRESS_ALERT_INTERVAL_S", 0.1
    )
    transport = _HangingTransport()
    diagnostics: list[dict[str, Any]] = []
    engine = _make_engine(transport, idle_timeout=0.35, diagnostics=diagnostics)

    events = await _drain_turn(engine)

    assert [d["code"] for d in diagnostics] == ["engine_no_progress"] * 3
    assert diagnostics[0]["source"] == "codex-app-server"
    assert diagnostics[0]["detail"]["engine_turn_id"] == "native-1"
    assert events[-1].type == EngineEventType.TURN_FAILED
    assert "idle timeout" in events[-1].payload["original_error"]


@pytest.mark.asyncio
async def test_idle_timeout_payload_carries_stderr_tail(monkeypatch) -> None:
    """idle 超时错误必须携带 app-server stderr 摘要，不再只写 idle timeout。"""
    monkeypatch.setattr(
        "pair_harness.adapters.codex.engine.NO_PROGRESS_ALERT_INTERVAL_S", 0.1
    )
    transport = _HangingTransport()
    transport.stderr = "ERROR: model supply misconfigured | retrying upstream"
    diagnostics: list[dict[str, Any]] = []
    engine = _make_engine(transport, idle_timeout=0.1, diagnostics=diagnostics)

    events = await _drain_turn(engine)

    failed = events[-1]
    assert failed.type == EngineEventType.TURN_FAILED
    assert "app-server 最近输出" in failed.payload["error"]
    assert failed.payload["stderr_tail"] == transport.stderr
    # interrupt 请求成功时没有 interrupt_error 键；interrupt 已真实发出。
    assert "interrupt_error" not in failed.payload
    assert transport.interrupts, "idle 超时必须先向 app-server 请求 interrupt"


@pytest.mark.asyncio
async def test_transport_stderr_tail_forwards_connection() -> None:
    """JsonlProcessTransport.stderr_tail 转发连接尾部；无连接如实返回空。"""
    from pair_harness.adapters.codex.transport import JsonlProcessTransport

    class _ConnWithTail:
        def stderr_tail(self, limit: int = 6) -> str:
            return "line-a | line-b"

    bare = JsonlProcessTransport("codex", connection_factory=None)
    assert bare.stderr_tail() == ""

    transport = JsonlProcessTransport("codex", connection_factory=None)
    transport._connection = _ConnWithTail()
    assert transport.stderr_tail() == "line-a | line-b"


# ---- codec 未识别 method 防线 ----


def _binding() -> EventBinding:
    return EventBinding(
        conversation_id="conv", task_id="task", engine_turn_id="native-1"
    )


def test_codec_warns_once_per_unknown_method(caplog) -> None:
    """未识别 method 首次结构化 WARNING（协议漂移痕迹），同 method 不刷屏。"""
    codec = CodexCodec()
    binding = _binding()
    with caplog.at_level(logging.WARNING, logger="pair_harness.adapters.codex.codec"):
        first = codec.map_notification(
            {"method": "item/futureThing", "params": {"turnId": "native-1"}}, binding
        )
        second = codec.map_notification(
            {"method": "item/futureThing", "params": {"turnId": "native-1"}}, binding
        )
    assert first is None and second is None
    warnings = [
        r for r in caplog.records if "item/futureThing" in r.getMessage()
    ]
    assert len(warnings) == 1
    assert "已忽略" in warnings[0].getMessage()


def test_codec_mismatched_turn_id_stays_silent(caplog) -> None:
    """native_turn_id 不匹配是正常过滤（别的回合的事件），不产生告警。"""
    codec = CodexCodec()
    with caplog.at_level(logging.WARNING, logger="pair_harness.adapters.codex.codec"):
        result = codec.map_notification(
            {"method": "item/started", "params": {"turnId": "other-turn"}}, _binding()
        )
    assert result is None
    assert not [r for r in caplog.records if "未识别" in r.getMessage()]


# ---- 审批超时（approval_timeout） ----


@pytest.mark.asyncio
async def test_approval_request_times_out_and_releases_pending(monkeypatch, service) -> None:
    """审批无裁决满 600s（测试压缩为 0.1s）如实失败，pending 释放。

    V0.3.9 契约 §6：超时是终态——广播 approval.resolved(timeout)，迟到应答
    拿到带真实终态的 approval_already_resolved（不再是笼统的 not_found）。
    """
    monkeypatch.setattr(app_service_module, "APPROVAL_TIMEOUT_S", 0.1)
    operation = PendingOperation(
        tool_kind="shell", command="echo hi", paths=(), summary="测试操作"
    )

    with pytest.raises(ServiceError) as excinfo:
        await service.approval_broker.request(
            operation=operation,
            approval_id="appr-1",
            reason="测试审批",
            conversation_id="conv-1",
            task_id="task-1",
        )
    assert excinfo.value.code == "approval_timeout"
    assert "审批超时未裁决" in str(excinfo.value)
    assert "appr-1" not in service.approval_broker.pending

    resolved = service.event_log.payloads("approval.resolved")
    assert len(resolved) == 1
    assert resolved[0]["approval_id"] == "appr-1"
    assert resolved[0]["decision"] == "timeout"
    assert resolved[0]["resolved_by"] == "system"
    assert resolved[0]["actor"] == "system"
    assert resolved[0]["error_code"] == "approval_timeout"
    assert resolved[0]["resolved_at"]

    with pytest.raises(ServiceError) as late:
        service.approval_broker.resolve("appr-1", "allow")
    assert late.value.code == "approval_already_resolved"
    assert late.value.details["decision"] == "timeout"
    assert late.value.details["resolved_by"] == "system"
    assert late.value.details["error_code"] == "approval_timeout"


@pytest.mark.asyncio
async def test_approval_request_resolves_before_timeout(monkeypatch, service) -> None:
    """正常裁决路径不受超时影响。"""
    operation = PendingOperation(tool_kind="shell", command="echo hi", summary="测试")

    async def resolve_later() -> None:
        print("RESOLVE-TASK-START", flush=True)
        await asyncio.sleep(0.01)
        service.approval_broker.resolve("appr-ok", "allow")
        print("RESOLVE-TASK-DONE", flush=True)

    task = asyncio.create_task(resolve_later())
    decision = await asyncio.wait_for(
        service.approval_broker.request(
            operation=operation,
            approval_id="appr-ok",
            reason="测试审批",
            conversation_id="conv-1",
            task_id="task-1",
        ),
        timeout=20,
    )
    await task
    print("DECISION", decision, flush=True)
    assert decision.value == "allow"


# ---- 队列前进（契约 §14.1） ----


def _enqueue(service, conversation_id: str, text: str) -> dict[str, Any]:
    return service.store.enqueue_queue_item(
        conversation_id=conversation_id, target="assistant", text=text
    )


def _conversation_id(service) -> str:
    conversations = service.store.list_conversations(service.current_project_id)
    assert conversations, "demo service 必须自带初始会话"
    return conversations[0].conversation_id


@pytest.mark.asyncio
async def test_queue_advances_after_failed_turn(service, monkeypatch) -> None:
    """failed 终态后队列立即派发下一条，排队项删除且不回退 queued。"""
    conversation_id = _conversation_id(service)
    first = _enqueue(service, conversation_id, "第一条（将失败）")
    second = _enqueue(service, conversation_id, "第二条（应被派发）")

    statuses: list[str] = ["failed", "completed"]

    async def fake_run_submit_turn(conversation_id, user_message, target, turn_id, exec_context=None):
        return statuses.pop(0)

    monkeypatch.setattr(service, "_run_submit_turn", fake_run_submit_turn)

    await service._dispatch_from_inbox(conversation_id)

    assert service.store.list_queue_items(conversation_id) == []
    assert first["queue_item_id"] and second["queue_item_id"]


@pytest.mark.asyncio
async def test_queue_advances_after_cancelled_turn(service, monkeypatch) -> None:
    """cancelled 终态同样放行队列——task.cancel 只取消当前回合不清空队列。"""
    conversation_id = _conversation_id(service)
    _enqueue(service, conversation_id, "将被取消的")
    _enqueue(service, conversation_id, "取消后仍要执行的")

    async def fake_run_submit_turn(conversation_id, user_message, target, turn_id, exec_context=None):
        return "cancelled"

    monkeypatch.setattr(service, "_run_submit_turn", fake_run_submit_turn)

    await service._dispatch_from_inbox(conversation_id)

    assert service.store.list_queue_items(conversation_id) == []


@pytest.mark.asyncio
async def test_queue_unknown_turn_status_exposes_protocol_violation(
    service, monkeypatch
) -> None:
    """回合返回未知终态是协议违规：如实抛错，不允许冒充正常派发。"""
    conversation_id = _conversation_id(service)
    _enqueue(service, conversation_id, "未知终态项")

    async def fake_run_submit_turn(conversation_id, user_message, target, turn_id, exec_context=None):
        return "half_done"

    monkeypatch.setattr(service, "_run_submit_turn", fake_run_submit_turn)

    with pytest.raises(RuntimeError) as excinfo:
        await service._dispatch_from_inbox(conversation_id)
    assert "half_done" in str(excinfo.value)


@pytest.mark.asyncio
async def test_task_cancel_keeps_queue_intact(service) -> None:
    """task.cancel 不清空队列（无活动回合时应答 cancelled=False 且队列原样）。"""
    conversation_id = _conversation_id(service)
    _enqueue(service, conversation_id, "取消后仍在队列的")

    result = await service.handle_command(
        command("1", "task.cancel", conversation_id=conversation_id)
    )
    assert result["cancelled"] is False
    remaining = service.store.list_queue_items(conversation_id)
    assert [item["text"] for item in remaining] == ["取消后仍在队列的"]


# ---- V0.3.8 T1（契约 §14.3）：ping 心跳命令 ----


@pytest.mark.asyncio
async def test_ping_returns_server_time(service) -> None:
    """ping 返回可解析的 ISO8601 server_time，无副作用。"""
    result = await service.handle_command(command("1", "ping"))
    assert "server_time" in result
    from datetime import datetime

    parsed = datetime.fromisoformat(result["server_time"])
    assert parsed.tzinfo is not None
