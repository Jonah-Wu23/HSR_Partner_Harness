import asyncio
import copy
from contextlib import aclosing

import pytest

from pair_harness.adapters.acp.engine import AcpCodingEngine, AcpCodec, AcpProtocolError
from pair_harness.adapters.codex.transport import JsonlProcessTransport
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    CharacterTurn,
    EngineEvent,
    EngineEventType,
    EngineSessionRef,
    MessageSource,
    ProjectRef,
    TaskAmendment,
    TaskRequest,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import FixedDialogueModel, direct_input, make_context, unexpected_approval
from tests.fixtures.jsonl_connection import QueueJsonLineConnection
from tests.service_helpers import wait_until

PROJECT = ProjectRef(project_id="p1", name="项目", root_path="C:/project")


def session_update(update: dict) -> dict:
    """session/update 通知；sessionId 由 FakeReasonixAcp 发送时填入。"""
    return {"method": "session/update", "params": {"update": update}}


def agent_message_chunk(text: str) -> dict:
    return session_update(
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}
    )


# 读目录的回合：助手正文、ls 工具开始与完成、回合末的上下文占用。
LIST_FILES_TURN = [
    agent_message_chunk("我先看一下项目结构。"),
    session_update(
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "call-1",
            "title": "ls",
            "kind": "read",
            "status": "pending",
            "rawInput": {"path": "."},
        }
    ),
    session_update(
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "call-1",
            "status": "completed",
            "content": [{"type": "content", "content": {"type": "text", "text": "列出 3 个文件"}}],
        }
    ),
    session_update({"sessionUpdate": "usage_update", "used": 1200, "size": 128000}),
]


class FakeReasonixAcp:
    """内存中的 reasonix acp 进程，经 JsonlProcessTransport 按 ACP v1 JSON-RPC 行协议应答。

    session/prompt 期间按序写出 turn 里的消息，再以 prompt_reply 响应；turn 中带 id
    的 session/request_permission 等客户端回复后才继续。prompt_reply 为 None 时
    session/prompt 永不应答。
    """

    def __init__(self) -> None:
        self.turn: list[dict] = LIST_FILES_TURN
        self.prompt_reply: dict | None = {"result": {"stopReason": "end_turn"}}
        self.stderr_tail = ""
        self.received: list[dict] = []
        self.connection: QueueJsonLineConnection | None = None
        self._sessions = 0
        self._replies: dict[int, asyncio.Future[dict]] = {}
        self._tasks: set[asyncio.Task] = set()

    async def connect(self) -> QueueJsonLineConnection:
        """transport 的 connection_factory，每次调用相当于启动一个新进程。"""
        self.connection = QueueJsonLineConnection(stderr_tail=self.stderr_tail)
        self._spawn(self._serve(self.connection))
        return self.connection

    def requests(self, method: str) -> list[dict]:
        """客户端发来的某个方法的请求或通知参数。"""
        return [message["params"] for message in self.received if message.get("method") == method]

    def replies(self) -> list[dict]:
        """客户端对服务端请求的回复。"""
        return [message for message in self.received if "method" not in message]

    async def exit(self) -> None:
        """当前进程退出，stdout 结束。"""
        await self.connection.server_to_client.put(b"")

    async def aclose(self) -> None:
        for task in tuple(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _serve(self, connection: QueueJsonLineConnection) -> None:
        while True:
            message = await connection.receive()
            self.received.append(message)
            if "method" not in message:
                self._replies.pop(message["id"]).set_result(message)
            elif "id" in message:
                # 请求各自处理，prompt 执行期间仍能收到审批回复与 session/cancel
                self._spawn(self._answer(connection, message))

    async def _answer(self, connection: QueueJsonLineConnection, request: dict) -> None:
        method = request["method"]
        params = request["params"]
        if method == "session/prompt":
            await self._run_prompt(connection, request)
            return
        if method == "initialize":
            result = {
                "protocolVersion": 1,
                "agentCapabilities": {
                    "loadSession": True,
                    "sessionCapabilities": {"resume": {}},
                    "promptCapabilities": {"image": True, "audio": False, "embeddedContext": True},
                    "mcpCapabilities": {"http": True, "sse": False},
                },
                "agentInfo": {"name": "reasonix", "version": "test"},
                "authMethods": [],
            }
        elif method == "session/new":
            self._sessions += 1
            result = {"sessionId": f"acp-session-{self._sessions}"}
        elif method == "session/resume":
            result = {}
        elif method == "session/set_config_option":
            result = {
                "configOptions": [
                    {
                        "id": params["configId"],
                        "name": "Tool Approval",
                        "category": "tool_approval",
                        "type": "select",
                        "currentValue": params["value"],
                        "options": [],
                    }
                ]
            }
        elif method == "_reasonix.io/session/steer":
            result = {"itemId": "inbox-1", "disposition": "steer_accepted"}
        else:
            await connection.send(
                {"id": request["id"], "error": {"code": -32601, "message": f"unknown method {method}"}}
            )
            return
        await connection.send({"id": request["id"], "result": result})

    async def _run_prompt(self, connection: QueueJsonLineConnection, request: dict) -> None:
        if self.prompt_reply is None:
            return
        for item in self.turn:
            message = copy.deepcopy(item)
            message["params"]["sessionId"] = request["params"]["sessionId"]
            if "id" in message:
                reply = asyncio.get_running_loop().create_future()
                self._replies[message["id"]] = reply
                await connection.send(message)
                await reply
            else:
                await connection.send(message)
        await connection.send({"id": request["id"], **self.prompt_reply})


@pytest.fixture
async def reasonix():
    server = FakeReasonixAcp()
    yield server
    await server.aclose()


@pytest.fixture
async def engine(reasonix: FakeReasonixAcp):
    engine = AcpCodingEngine(JsonlProcessTransport(reasonix.connect))
    yield engine
    await engine.aclose()


async def open_session(engine: AcpCodingEngine) -> EngineSessionRef:
    return await engine.open_session(PROJECT, approval_mode=ApprovalMode.REQUEST_APPROVAL)


def task_request(instructions: str = "检查项目文件") -> TaskRequest:
    return TaskRequest(conversation_id="c1", origin_message_id="m1", instructions=instructions)


async def run_turn(engine: AcpCodingEngine, ref: EngineSessionRef) -> list[EngineEvent]:
    return [event async for event in engine.run_turn(ref, task_request())]


@pytest.mark.asyncio
async def test_open_session_creates_session_and_resumes_after_reasonix_restart(
    engine: AcpCodingEngine, reasonix: FakeReasonixAcp
) -> None:
    ref = await open_session(engine)
    assert ref.engine_type == "acp"
    assert reasonix.requests("session/new") == [{"cwd": "C:/project", "mcpServers": []}]

    # 同一进程内会话仍在，不重复 resume
    reopened = await engine.open_session(
        PROJECT, stored_ref=ref, approval_mode=ApprovalMode.FULL_AUTO
    )
    assert reopened == ref
    assert reasonix.requests("session/resume") == []

    await reasonix.exit()
    await wait_until(lambda: not engine.transport.is_running)
    resumed = await engine.open_session(
        PROJECT, stored_ref=ref, approval_mode=ApprovalMode.FULL_AUTO
    )

    # 新进程重新握手并恢复同一会话
    assert resumed == ref
    assert reasonix.requests("initialize") == [{"protocolVersion": 1}] * 2
    assert reasonix.requests("session/resume") == [
        {"sessionId": "acp-session-1", "cwd": "C:/project", "mcpServers": []}
    ]
    # 新建与恢复的会话都把 tool_approval 设为 ask，所有工具先经编排器裁决
    assert reasonix.requests("session/set_config_option") == [
        {"sessionId": "acp-session-1", "configId": "tool_approval", "value": "ask"}
    ] * 2


@pytest.mark.asyncio
async def test_run_turn_maps_acp_updates_to_engine_events(
    engine: AcpCodingEngine, reasonix: FakeReasonixAcp
) -> None:
    events = await run_turn(engine, await open_session(engine))

    assert reasonix.requests("session/prompt") == [
        {"sessionId": "acp-session-1", "prompt": [{"type": "text", "text": "检查项目文件"}]}
    ]
    assert [event.type for event in events] == [
        EngineEventType.ASSISTANT_DELTA,
        EngineEventType.TOOL_STARTED,
        EngineEventType.TOOL_FINISHED,
        EngineEventType.USAGE,
        EngineEventType.ASSISTANT_FINAL,
        EngineEventType.TURN_COMPLETED,
    ]
    delta, started, finished, usage, final, completed = events
    assert delta.payload["text"] == "我先看一下项目结构。"
    assert started.tool_call_id == finished.tool_call_id == "call-1"
    assert started.payload["tool_kind"] == "file_write"
    assert started.payload["paths"] == ["."]
    assert finished.payload["status"] == "succeeded"
    assert finished.payload["summary"] == "列出 3 个文件"
    # ACP v1 usage_update 只报告上下文窗口占用
    assert usage.payload == {"context_used": 1200, "context_size": 128000}
    assert final.payload == {"text": "我先看一下项目结构。"}
    assert completed.payload["stop_reason"] == "end_turn"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt_result", "terminal_type", "status", "error"),
    [
        ({"stopReason": "cancelled"}, EngineEventType.TURN_COMPLETED, "cancelled", None),
        ({"stopReason": "error"}, EngineEventType.TURN_FAILED, None, "error"),
        ({"stopReason": "max_turn_requests"}, EngineEventType.TURN_FAILED, None, "max_turn_requests"),
        ({"stopReason": "some_new_reason"}, EngineEventType.TURN_FAILED, None, "some_new_reason"),
        # ACP v1 的 PromptResponse.stopReason 是必填字段
        ({}, EngineEventType.TURN_FAILED, None, "session/prompt 响应缺少 stopReason"),
    ],
)
async def test_run_turn_terminal_follows_stop_reason_after_successful_tools(
    engine: AcpCodingEngine,
    reasonix: FakeReasonixAcp,
    prompt_result: dict,
    terminal_type: EngineEventType,
    status: str | None,
    error: str | None,
) -> None:
    reasonix.prompt_reply = {"result": prompt_result}
    events = await run_turn(engine, await open_session(engine))

    terminal = events[-1]
    assert terminal.type == terminal_type
    assert terminal.payload["stop_reason"] == prompt_result.get("stopReason", "")
    assert terminal.payload.get("status") == status
    assert terminal.payload.get("error") == error
    # 终态只取决于 stopReason，正文与成功的工具回执照常送达
    assert any(event.type == EngineEventType.ASSISTANT_FINAL for event in events)
    finished = [event for event in events if event.type == EngineEventType.TOOL_FINISHED]
    assert finished[0].payload["status"] == "succeeded"


@pytest.mark.asyncio
async def test_run_turn_reports_prompt_json_rpc_error_as_turn_failed(
    engine: AcpCodingEngine, reasonix: FakeReasonixAcp
) -> None:
    # Reasonix 的供应商失败以 -32603 返回
    reasonix.prompt_reply = {
        "error": {"code": -32603, "message": "provider 502", "data": {"status": 502}}
    }
    events = await run_turn(engine, await open_session(engine))

    assert events[-1].type == EngineEventType.TURN_FAILED
    assert "provider 502" in events[-1].payload["error"]
    assert events[-1].payload["code"] == -32603
    assert events[-1].payload["data"] == {"status": 502}


PERMISSION_REQUEST = {
    "id": 42,
    "method": "session/request_permission",
    "params": {
        "toolCall": {
            "toolCallId": "gate-a1",
            "title": "bash rm -rf build",
            "kind": "execute",
            "status": "pending",
            "rawInput": {"command": "rm -rf build"},
            "_meta": {
                "reasonix.io": {
                    "approvalId": "a1",
                    "tool": "bash",
                    "subject": "rm -rf build",
                    "fresh": False,
                    "reason": "高风险删除",
                }
            },
        },
        "options": [
            {"optionId": "allow_once", "name": "Allow", "kind": "allow_once"},
            {"optionId": "allow_always", "name": "Allow for this session", "kind": "allow_always"},
            {"optionId": "reject_once", "name": "Reject", "kind": "reject_once"},
        ],
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "option_id"),
    [
        (ApprovalDecision.ALLOW, "allow_once"),
        # 本对话内允许由 ApprovalManager 缓存，对 Reasonix 只放行这一次
        (ApprovalDecision.ALLOW_FOR_CONVERSATION, "allow_once"),
        (ApprovalDecision.DENY, "reject_once"),
    ],
)
async def test_permission_request_is_answered_with_decision_option(
    engine: AcpCodingEngine,
    reasonix: FakeReasonixAcp,
    decision: ApprovalDecision,
    option_id: str,
) -> None:
    reasonix.turn = [PERMISSION_REQUEST]
    ref = await open_session(engine)
    events = []
    async for event in engine.run_turn(ref, task_request("执行清理")):
        events.append(event)
        if event.type == EngineEventType.APPROVAL_REQUESTED:
            await engine.resolve_approval(ref, event.payload["approval_id"], decision)

    approval = events[0]
    assert approval.type == EngineEventType.APPROVAL_REQUESTED
    assert approval.tool_call_id == "gate-a1"
    assert approval.payload["approval_id"] == "42"
    assert approval.payload["command"] == "rm -rf build"
    assert approval.payload["tool_kind"] == "shell"
    assert approval.payload["reason"] == "高风险删除"
    assert reasonix.replies() == [
        {"id": 42, "result": {"outcome": {"outcome": "selected", "optionId": option_id}}}
    ]
    assert events[-1].type == EngineEventType.TURN_COMPLETED


@pytest.mark.asyncio
async def test_cancel_turn_sends_session_cancel(
    engine: AcpCodingEngine, reasonix: FakeReasonixAcp
) -> None:
    ref = await open_session(engine)
    await engine.cancel_turn(ref, "acp-t1")
    await wait_until(
        lambda: reasonix.requests("session/cancel") == [{"sessionId": "acp-session-1"}],
        message="Reasonix 没有收到 session/cancel",
    )


@pytest.mark.asyncio
async def test_amend_turn_uses_steer_extension(
    engine: AcpCodingEngine, reasonix: FakeReasonixAcp
) -> None:
    ref = await open_session(engine)
    await engine.amend_turn(
        ref,
        "acp-t1",
        TaskAmendment(
            target_task_id="t1", origin_message_id="m2", revision=2, instructions="改用表格"
        ),
    )
    assert reasonix.requests("_reasonix.io/session/steer") == [
        {"sessionId": "acp-session-1", "prompt": [{"type": "text", "text": "改用表格"}]}
    ]


@pytest.mark.asyncio
async def test_silent_turn_alerts_then_cancels_with_stderr_tail(
    reasonix: FakeReasonixAcp, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reasonix 静默时按间隔告警，达到空闲超时后取消回合，失败回执带 stderr 尾部。"""
    # 缩短告警间隔，回合在 0.2s 内走完告警与超时
    monkeypatch.setattr("pair_harness.adapters.acp.engine.NO_PROGRESS_ALERT_INTERVAL_S", 0.05)
    reasonix.prompt_reply = None
    reasonix.stderr_tail = "reasonix upstream retrying"
    diagnostics: list[dict] = []
    engine = AcpCodingEngine(
        JsonlProcessTransport(reasonix.connect),
        idle_timeout=0.16,
        diagnostic_callback=diagnostics.append,
    )
    try:
        events = await run_turn(engine, await open_session(engine))
    finally:
        await engine.aclose()

    assert len(diagnostics) >= 2
    assert {item["code"] for item in diagnostics} == {"engine_no_progress"}
    assert events[-1].type == EngineEventType.TURN_FAILED
    assert events[-1].payload["original_error"] == "idle timeout"
    assert events[-1].payload["stderr_tail"] == "reasonix upstream retrying"
    await wait_until(
        lambda: reasonix.requests("session/cancel") == [{"sessionId": "acp-session-1"}],
        message="空闲超时后 Reasonix 没有收到 session/cancel",
    )


def test_codec_failed_tool_carries_command_and_output() -> None:
    """失败工具回执附带命令与错误输出；Reasonix 的失败输出常常只有退出码。"""
    codec = AcpCodec()
    binding = _codec_binding()
    started = codec.map_notification(
        {
            "method": "session/update",
            "params": {
                "sessionId": "s1",
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "tool-x",
                    "title": "bash",
                    "kind": "execute",
                    "status": "pending",
                    "rawInput": {"command": "python fix_script.py"},
                },
            },
        },
        binding,
    )
    assert started is not None and started.type == EngineEventType.TOOL_STARTED

    finished = codec.map_notification(
        {
            "method": "session/update",
            "params": {
                "sessionId": "s1",
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "tool-x",
                    "status": "failed",
                    "content": [
                        {
                            "type": "content",
                            "content": {"type": "text", "text": "Traceback (most recent call last)"},
                        },
                        {
                            "type": "content",
                            "content": {
                                "type": "text",
                                "text": "ModuleNotFoundError: No module named 'x'",
                            },
                        },
                    ],
                },
            },
        },
        binding,
    )
    assert finished is not None and finished.type == EngineEventType.TOOL_FINISHED
    assert finished.payload["status"] == "failed"
    # summary 保留工具结果原文，details 与 error 附上命令
    assert finished.payload["summary"] == (
        "Traceback (most recent call last)\nModuleNotFoundError: No module named 'x'"
    )
    assert "命令：python fix_script.py" in finished.payload["details"]
    assert "ModuleNotFoundError" in finished.payload["details"]
    assert "命令：python fix_script.py" in finished.payload["error"]


@pytest.mark.asyncio
async def test_aclose_mid_turn_releases_session_subscription(
    engine: AcpCodingEngine,
) -> None:
    """消费方在 TOOL_STARTED 后关闭回合，同一 session 能再次订阅并完整跑完下一轮。"""
    ref = await open_session(engine)
    async with aclosing(engine.run_turn(ref, task_request())) as stream:
        async for event in stream:
            if event.type == EngineEventType.TOOL_STARTED:
                break

    events = await run_turn(engine, ref)
    assert events[-1].type == EngineEventType.TURN_COMPLETED


@pytest.mark.asyncio
async def test_sandbox_denial_releases_session_for_next_delegation(
    engine: AcpCodingEngine, reasonix: FakeReasonixAcp
) -> None:
    """工具路径越界时编排器中断回合，同一聊天的下一次委派仍能使用同一 ACP session。"""
    reasonix.turn = [
        agent_message_chunk("我看一下那份 3D 计划。"),
        session_update(
            {
                "sessionUpdate": "tool_call",
                "toolCallId": "call-outside",
                "title": "read_file",
                "kind": "read",
                "status": "pending",
                "rawInput": {"path": "C:/outside/3d_plan.txt"},
                "locations": [{"path": "C:/outside/3d_plan.txt"}],
            }
        ),
    ]
    orchestrator = ConversationOrchestrator(
        dialogue_model=FixedDialogueModel(
            CharacterTurn(speech="被拦住了。", delegation=None),
            CharacterTurn(speech="再试一次。", delegation=None),
        ),
        coding_engine=engine,
        store=None,
        approval_callback=unexpected_approval,
    )
    context = make_context(
        ProjectRef(project_id="p", name="p", root_path="C:\\project"),
        conversation_id="c",
        pair_id="march7_fourth_mirror",
        approval_mode=ApprovalMode.REQUEST_APPROVAL,
    )

    first = await direct_input(
        orchestrator,
        conversation_id="c",
        text="查一下 C 盘那份 3D 计划",
        context=context,
    )
    assert first.receipt is not None
    assert first.receipt.status == "failed"
    assert any("路径越界" in err for err in first.receipt.errors)
    # 沙箱拒绝卡片附可操作提示
    card_texts = [m.text for m in first.messages if m.source == MessageSource.SYSTEM]
    assert any(
        "路径在绑定项目之外" in text and "移入项目目录" in text for text in card_texts
    )

    # 订阅器若未随中断释放，这里会因 session 已有订阅器而抛 RuntimeError
    second = await direct_input(
        orchestrator,
        conversation_id="c",
        text="再查一次那份 3D 计划",
        context=context,
    )
    assert second.receipt is not None
    assert second.receipt.status == "failed"
    assert any("路径越界" in err for err in second.receipt.errors)


def _codec_binding() -> dict:
    return {
        "conversation_id": "c1",
        "task_id": "t1",
        "engine_turn_id": "e1",
    }


def _tool_update(update: dict) -> dict:
    return {
        "method": "session/update",
        "params": {"sessionId": "s1", "update": {"sessionUpdate": "tool_call_update", **update}},
    }


def test_codec_only_completed_or_failed_finishes_tool() -> None:
    codec = AcpCodec()
    in_progress = codec.map_notification(
        _tool_update({"toolCallId": "tool-x", "status": "in_progress"}), _codec_binding()
    )
    assert in_progress is not None and in_progress.type == EngineEventType.TOOL_PROGRESS
    content_only = codec.map_notification(
        _tool_update(
            {
                "toolCallId": "tool-x",
                "content": [{"type": "content", "content": {"type": "text", "text": "进行中"}}],
            }
        ),
        _codec_binding(),
    )
    assert content_only is not None and content_only.type == EngineEventType.TOOL_PROGRESS
    assert content_only.payload == {"summary": "进行中"}
    with pytest.raises(AcpProtocolError, match="rejected"):
        codec.map_notification(
            _tool_update({"toolCallId": "tool-x", "status": "rejected"}), _codec_binding()
        )


def test_codec_permission_paths_come_from_locations_and_write_access_directories() -> None:
    codec = AcpCodec()
    event = codec.map_notification(
        {
            "id": 7,
            "method": "session/request_permission",
            "params": {
                "sessionId": "s1",
                "toolCall": {
                    "toolCallId": "gate-a7",
                    "title": "edit_file C:/project/a.py",
                    "kind": "edit",
                    "status": "pending",
                    "rawInput": {"path": "a.py", "old_string": "x", "new_string": "y"},
                    "locations": [{"path": "C:/project/a.py"}],
                    "_meta": {
                        "reasonix.io": {
                            "approvalId": "a7",
                            "tool": "edit_file",
                            "kind": "write_access",
                            "directories": ["D:/elsewhere"],
                        }
                    },
                },
            },
        },
        _codec_binding(),
    )
    assert event is not None and event.type == EngineEventType.APPROVAL_REQUESTED
    assert event.payload["tool_kind"] == "file_write"
    assert event.payload["paths"] == ["C:/project/a.py", "D:/elsewhere"]


def test_codec_move_file_paths_come_from_tool_arguments() -> None:
    codec = AcpCodec()
    event = codec.map_notification(
        {
            "id": 8,
            "method": "session/request_permission",
            "params": {
                "sessionId": "s1",
                "toolCall": {
                    "toolCallId": "gate-a8",
                    "title": "move_file a.txt",
                    "kind": "edit",
                    "rawInput": {"source_path": "a.txt", "destination_path": "C:/outside/a.txt"},
                    "_meta": {"reasonix.io": {"approvalId": "a8", "tool": "move_file"}},
                },
            },
        },
        _codec_binding(),
    )
    assert event is not None
    assert event.payload["paths"] == ["a.txt", "C:/outside/a.txt"]
