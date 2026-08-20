"""V0.2 M3：DeepSeek 编程助手（Reasonix ACP）适配器（方案 §M3-5）。

用内存 JSONL 连接模拟 ``reasonix acp`` 进程，验证会话打开、事件映射、
权限回复与取消。真机联调需要本地构建的 reasonix 二进制（见交付文档）。
"""

import asyncio
import json
from collections import deque
from contextlib import aclosing

import pytest

from pair_harness.adapters.acp.engine import AcpCodingEngine, AcpCodec
from pair_harness.adapters.codex.transport import JsonlProcessTransport
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    CharacterTurn,
    EngineEventType,
    EngineSessionRef,
    MessageSource,
    ProjectRef,
    TaskRequest,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import FixedDialogueModel


class FakeAcpConnection:
    """内存 ACP 进程：按脚本应答请求，可注入通知。"""

    def __init__(self) -> None:
        self.writes: list[dict] = []
        self.notifications: deque[dict] = deque()
        self.prompt_result: dict | None = None
        self._cancelled = False

    async def read_line(self) -> bytes:
        # 测试直接驱动通知队列，不在这里阻塞
        await asyncio.sleep(3600)

    async def write_line(self, data: bytes) -> None:
        message = json.loads(data.decode("utf-8"))
        self.writes.append(message)

    async def close(self) -> None:
        pass


class FakeTransport(JsonlProcessTransport):
    """接管连接与请求/通知分发，模拟 ACP 服务端。

    V0.3.2 M3：通知按真实协议携带 ``params.sessionId``，经
    ``_emit_notification`` 走 transport 的 session 路由；无 session
    标识的旧形状继续进入通用队列。
    """

    def __init__(self) -> None:
        super().__init__("unused", connection_factory=None)
        self.connection = FakeAcpConnection()
        self._next_request = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._notifications: asyncio.Queue = asyncio.Queue()
        self.server: "FakeAcpServer | None" = None

    async def _emit_notification(self, message: dict) -> None:
        if not self._route_session_message(message):
            await self._notifications.put(message)

    async def start(self) -> None:
        return

    @property
    def is_running(self) -> bool:
        return True

    async def request(self, method: str, params=None, *, timeout=None) -> dict:
        del timeout
        assert self.server is not None, "server not attached"
        result = await self.server.handle_request(method, params or {})
        if isinstance(result, BaseException):
            raise result
        return result

    async def next_notification(self) -> dict:
        return await self._notifications.get()

    async def respond(self, request_id: int, result: dict) -> None:
        assert self.server is not None
        await self.server.handle_response(request_id, result)

    async def notify(self, method: str, params: dict | None = None) -> None:
        assert self.server is not None
        await self.server.handle_notify(method, params or {})

    async def close(self) -> None:
        return


class FakeAcpServer:
    """ACP 服务端脚本（reasonix v1.24 实测形状：session/update 封装）。"""

    def __init__(self, transport: FakeTransport) -> None:
        self.transport = transport
        self.requests: list[tuple[str, dict]] = []
        self.notifications: list[tuple[str, dict]] = []
        self.responses: list[tuple[int, dict]] = []
        self.sessions: dict[str, str] = {}
        self.current_session = ""
        self.delayed_completion_task: asyncio.Task | None = None
        self.completion_delay = 0.0

    async def _put_completion(self) -> None:
        if self.completion_delay:
            await asyncio.sleep(self.completion_delay)
        session_id = self.current_session
        await self.transport._emit_notification(
            {
                "method": "session/update",
                "params": {
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "tool-1",
                        "status": "completed",
                        "content": [
                            {"type": "content", "content": {"type": "text", "text": "列出 3 个文件"}}
                        ],
                    }
                },
            }
        )

    async def handle_request(self, method: str, params: dict) -> dict:
        self.requests.append((method, params))
        if method == "initialize":
            return {"protocolVersion": 1, "agentCapabilities": {}}
        if method == "session/new":
            session_id = f"acp-session-{len(self.sessions) + 1}"
            self.sessions[session_id] = str(params.get("cwd", ""))
            return {"sessionId": session_id}
        if method == "session/resume":
            return {"sessionId": params.get("sessionId")}
        if method == "session/set_config_option":
            return {"configOptions": []}
        if method == "session/prompt":
            session_id = str(params.get("sessionId") or "")
            self.current_session = session_id
            # 脚本：先推消息与工具事件（session/update 形状），再返回 stop reason
            await self.transport._emit_notification(
                {
                    "method": "session/update",
                    "params": {
                        "sessionId": session_id,
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "我先看一下项目结构。"},
                        }
                    },
                }
            )
            await self.transport._emit_notification(
                {
                    "method": "session/update",
                    "params": {
                        "sessionId": session_id,
                        "update": {
                            "sessionUpdate": "tool_call",
                            "toolCallId": "tool-1",
                            "title": "list",
                            "kind": "read",
                            "rawInput": {"path": "."},
                        }
                    },
                }
            )
            if self.completion_delay:
                self.delayed_completion_task = asyncio.create_task(self._put_completion())
            else:
                await self._put_completion()
            return {"stopReason": "end_turn", "sessionId": session_id}
        if method == "_reasonix.io/session/steer":
            return {"itemId": "inbox-1", "disposition": "steer_accepted"}
        raise RuntimeError(f"unknown method: {method}")

    async def handle_notify(self, method: str, params: dict) -> None:
        self.notifications.append((method, params))

    async def handle_response(self, request_id: int, result: dict) -> None:
        self.responses.append((request_id, result))


@pytest.fixture
def engine_and_server() -> tuple[AcpCodingEngine, FakeTransport, FakeAcpServer]:
    transport = FakeTransport()
    server = FakeAcpServer(transport)
    transport.server = server
    return AcpCodingEngine(transport), transport, server


@pytest.mark.asyncio
async def test_open_session_initializes_and_creates_acp_session(
    engine_and_server,
) -> None:
    engine, _transport, server = engine_and_server
    ref = await engine.open_session(
        ProjectRef(project_id="p1", name="项目", root_path="C:/project")
    )
    assert ref.engine_type == "acp"
    methods = [m for m, _ in server.requests]
    assert "initialize" in methods
    assert "session/new" in methods
    params = dict(server.requests)[methods.index("session/new")]["params"] if False else None
    del params
    assert engine._decode_ref(ref) == "acp-session-1"

    # 恢复路径：resume 不重开
    resumed = await engine.open_session(
        ProjectRef(project_id="p1", name="项目", root_path="C:/project"), stored_ref=ref
    )
    assert resumed == ref


@pytest.mark.asyncio
async def test_run_turn_maps_acp_events_to_engine_events(engine_and_server) -> None:
    engine, _transport, _server = engine_and_server
    ref = await engine.open_session(
        ProjectRef(project_id="p1", name="项目", root_path="C:/project")
    )
    request = TaskRequest(
        conversation_id="c1",
        origin_message_id="m1",
        instructions="检查项目文件",
    )
    events = [event async for event in engine.run_turn(ref, request)]

    types = [event.type for event in events]
    assert types[0] == EngineEventType.ASSISTANT_DELTA
    assert types[1] == EngineEventType.TOOL_STARTED
    assert types[2] == EngineEventType.TOOL_FINISHED
    assert types[-1] == EngineEventType.TURN_COMPLETED
    tool_finished = events[2]
    assert tool_finished.tool_call_id == "tool-1"
    assert tool_finished.payload["status"] == "succeeded"
    assert events[0].payload["text"] == "我先看一下项目结构。"
    finals = [event for event in events if event.type == EngineEventType.ASSISTANT_FINAL]
    assert len(finals) == 1
    assert finals[0].payload["text"] == "我先看一下项目结构。"


@pytest.mark.asyncio
async def test_run_turn_drains_tool_completion_after_prompt_response(engine_and_server) -> None:
    """prompt 响应先到时，短暂延后的工具回执仍进入事件流。"""
    engine, _transport, server = engine_and_server
    server.completion_delay = 0.08
    ref = await engine.open_session(
        ProjectRef(project_id="p1", name="项目", root_path="C:/project")
    )
    events = [
        event
        async for event in engine.run_turn(
            ref,
            TaskRequest(conversation_id="c1", origin_message_id="m1", instructions="检查项目文件"),
        )
    ]
    assert [event.type for event in events].count(EngineEventType.TOOL_FINISHED) == 1
    tool_finished_index = next(
        index
        for index, event in enumerate(events)
        if event.type == EngineEventType.TOOL_FINISHED
    )
    assert tool_finished_index < next(
        index
        for index, event in enumerate(events)
        if event.type == EngineEventType.ASSISTANT_FINAL
    )
    assert events[-1].type == EngineEventType.TURN_COMPLETED
    if server.delayed_completion_task is not None:
        await server.delayed_completion_task


class LegacyShapedServer(FakeAcpServer):
    """真实联调出现的兼容形状：snake_case 字段、dict 结果文本、rejected 状态。"""

    async def handle_request(self, method: str, params: dict) -> dict:
        if method == "session/prompt":
            session_id = str(params.get("sessionId") or "")
            self.current_session = session_id
            await self.transport._emit_notification(
                {
                    "method": "session/update",
                    "params": {
                        "sessionId": session_id,
                        "update": {
                            "sessionUpdate": "tool_call",
                            "tool_call_id": "tool-legacy-1",
                            "title": "list",
                            "kind": "read",
                            "rawInput": {"path": "."},
                        }
                    },
                }
            )
            await self.transport._emit_notification(
                {
                    "method": "session/update",
                    "params": {
                        "sessionId": session_id,
                        "update": {
                            "sessionUpdate": "tool_call_update",
                            "tool_call_id": "tool-legacy-1",
                            "state": "rejected",
                            "result": {"text": "权限不足"},
                        }
                    },
                }
            )
            return {"stopReason": "end_turn", "sessionId": session_id}
        return await super().handle_request(method, params)


class MissingStopReasonServer(FakeAcpServer):
    """真实 ACP 成功响应的兼容形状：session/prompt 只返回 sessionId。"""

    async def handle_request(self, method: str, params: dict) -> dict:
        result = await super().handle_request(method, params)
        if method == "session/prompt":
            result.pop("stopReason", None)
        return result


class ErrorStopReasonAfterSuccessServer(FakeAcpServer):
    """Reasonix v1.24.2 的真实形状：成功事件后返回 stopReason=error。"""

    async def handle_request(self, method: str, params: dict) -> dict:
        result = await super().handle_request(method, params)
        if method == "session/prompt":
            result["stopReason"] = "error"
        return result


@pytest.mark.asyncio
async def test_run_turn_accepts_snake_case_fields_and_rejected_status(
    engine_and_server,
) -> None:
    """codec 兼容分支：snake_case 字段、dict 结果文本、rejected → failed。"""
    engine, transport, _server = engine_and_server
    transport.server = LegacyShapedServer(transport)
    ref = await engine.open_session(
        ProjectRef(project_id="p1", name="项目", root_path="C:/project")
    )
    events = [
        event
        async for event in engine.run_turn(
            ref,
            TaskRequest(conversation_id="c1", origin_message_id="m1", instructions="检查项目文件"),
        )
    ]
    started = [event for event in events if event.type == EngineEventType.TOOL_STARTED]
    finished = [event for event in events if event.type == EngineEventType.TOOL_FINISHED]
    assert started and started[0].tool_call_id == "tool-legacy-1"
    assert finished
    assert finished[0].tool_call_id == "tool-legacy-1"
    # rejected 状态归一为 failed；dict 形态结果文本进入 summary
    assert finished[0].payload["status"] == "failed"
    assert finished[0].payload["summary"] == "权限不足"
    # 终态由 stopReason 决定（end_turn → completed）；工具失败经
    # TOOL_FINISHED status=failed 表达，编排器据此计算失败回执
    assert events[-1].type == EngineEventType.TURN_COMPLETED


class CancelledStopReasonAfterSuccessServer(FakeAcpServer):
    """Reasonix 在成功工具与助手正文后返回 stopReason=cancelled。"""

    async def handle_request(self, method: str, params: dict) -> dict:
        result = await super().handle_request(method, params)
        if method == "session/prompt":
            result["stopReason"] = "cancelled"
        return result


@pytest.mark.asyncio
async def test_run_turn_keeps_completed_status_for_cancelled_after_success(
    engine_and_server,
) -> None:
    """工具与正文均成功后 stopReason=cancelled：状态保持完成，附真实 stop_reason 警告。

    已有 recoverable 逻辑只覆盖 error/fail；V0.3.3 把「工具与正文均已成功」
    的 cancelled 也纳入，避免角色把已完成的任务转述成「取消」。
    """
    engine, transport, _server = engine_and_server
    transport.server = CancelledStopReasonAfterSuccessServer(transport)
    ref = await engine.open_session(
        ProjectRef(project_id="p1", name="项目", root_path="C:/project")
    )
    events = [
        event
        async for event in engine.run_turn(
            ref,
            TaskRequest(conversation_id="c1", origin_message_id="m1", instructions="检查项目文件"),
        )
    ]
    assert events[-1].type == EngineEventType.TURN_COMPLETED
    assert events[-1].payload["stop_reason"] == "cancelled"
    assert events[-1].payload["warning"] == "cancelled"


@pytest.mark.asyncio
async def test_run_turn_recovers_error_stop_reason_after_successful_tools(
    engine_and_server,
) -> None:
    """成功工具与助手终稿齐全时保留终态警告，但任务仍为 completed。"""
    engine, transport, _server = engine_and_server
    transport.server = ErrorStopReasonAfterSuccessServer(transport)
    ref = await engine.open_session(
        ProjectRef(project_id="p1", name="项目", root_path="C:/project")
    )
    events = [
        event
        async for event in engine.run_turn(
            ref,
            TaskRequest(conversation_id="c1", origin_message_id="m1", instructions="检查项目文件"),
        )
    ]
    assert events[-1].type == EngineEventType.TURN_COMPLETED
    assert events[-1].payload["warning"] == "error"


@pytest.mark.asyncio
async def test_run_turn_treats_missing_stop_reason_without_error_as_completed(
    engine_and_server,
) -> None:
    """ACP 成功响应缺省 stopReason 时不应把已完成回合标成失败。"""
    engine, transport, _server = engine_and_server
    transport.server = MissingStopReasonServer(transport)
    ref = await engine.open_session(
        ProjectRef(project_id="p1", name="项目", root_path="C:/project")
    )
    events = [
        event
        async for event in engine.run_turn(
            ref,
            TaskRequest(conversation_id="c1", origin_message_id="m1", instructions="检查项目文件"),
        )
    ]
    assert events[-1].type == EngineEventType.TURN_COMPLETED


@pytest.mark.asyncio
async def test_run_turn_maps_permission_request(engine_and_server) -> None:
    engine, transport, server = engine_and_server
    ref = await engine.open_session(
        ProjectRef(project_id="p1", name="项目", root_path="C:/project")
    )

    async def inject_permission() -> None:
        await asyncio.sleep(0.01)
        await transport._emit_notification(
            {
                "id": 42,
                "method": "session/request_permission",
                "params": {
                    "sessionId": "acp-session-1",
                    "toolCall": {
                        "toolCallId": "gate-9",
                        "title": "bash",
                        "kind": "execute",
                        "status": "pending",
                        "rawInput": {"command": "rm -rf"},
                        "_meta": {
                            "reasonix.io": {
                                "approvalId": "a1",
                                "tool": "bash",
                                "subject": "rm -rf",
                                "fresh": True,
                                "reason": "高风险删除",
                            }
                        },
                    },
                    "options": [
                        {"optionId": "allow_once", "name": "Allow", "kind": "allow_once"},
                        {"optionId": "reject_once", "name": "Reject", "kind": "reject_once"},
                    ],
                },
            }
        )

    inject_task = asyncio.create_task(inject_permission())
    events = [event async for event in engine.run_turn(ref, TaskRequest(
        conversation_id="c1", origin_message_id="m1", instructions="执行清理"
    ))]
    await inject_task

    approval_events = [e for e in events if e.type == EngineEventType.APPROVAL_REQUESTED]
    assert len(approval_events) == 1
    assert approval_events[0].payload["approval_id"] == "42"
    assert approval_events[0].payload["command"] == "rm -rf"
    assert approval_events[0].payload["tool_kind"] == "shell"
    assert approval_events[0].payload["reason"] == "高风险删除"


@pytest.mark.asyncio
async def test_approval_resolve_responds_to_acp_request(engine_and_server) -> None:
    engine, _transport, server = engine_and_server
    ref = await engine.open_session(
        ProjectRef(project_id="p1", name="项目", root_path="C:/project")
    )
    await engine.resolve_approval(ref, "42", ApprovalDecision.ALLOW)
    assert server.responses == [
        (42, {"outcome": {"outcome": "selected", "optionId": "allow_once"}})
    ]
    await engine.resolve_approval(ref, "43", ApprovalDecision.ALLOW_FOR_CONVERSATION)
    assert server.responses[-1] == (
        43,
        {"outcome": {"outcome": "selected", "optionId": "allow_always"}},
    )
    await engine.resolve_approval(ref, "44", ApprovalDecision.DENY)
    assert server.responses[-1] == (
        44,
        {"outcome": {"outcome": "selected", "optionId": "reject_once"}},
    )


@pytest.mark.asyncio
async def test_cancel_turn_sends_notification(engine_and_server) -> None:
    engine, _transport, server = engine_and_server
    ref = await engine.open_session(
        ProjectRef(project_id="p1", name="项目", root_path="C:/project")
    )
    await engine.cancel_turn(ref, "engine-turn-1")
    assert server.notifications == [("session/cancel", {"sessionId": "acp-session-1"})]


@pytest.mark.asyncio
async def test_amend_turn_uses_steer_extension(engine_and_server) -> None:
    engine, _transport, server = engine_and_server
    ref = await engine.open_session(
        ProjectRef(project_id="p1", name="项目", root_path="C:/project")
    )
    from pair_harness.core.contracts import TaskAmendment

    await engine.amend_turn(
        ref,
        "engine-turn-1",
        TaskAmendment(
            target_task_id="t1", origin_message_id="m2", revision=2, instructions="改用表格"
        ),
    )
    steer_calls = [params for m, params in server.requests if m == "_reasonix.io/session/steer"]
    assert len(steer_calls) == 1
    assert steer_calls[0]["prompt"][0]["text"] == "改用表格"


def test_codec_failed_tool_carries_command_and_stderr() -> None:
    """V0.3.3：失败工具回执附带命令摘要与 stderr/error 文本，诊断不再
    只有退出码（真实 Reasonix 失败只给 "command exited: exit status 1"）。"""
    codec = AcpCodec()
    binding = {
        "conversation_id": "c1",
        "task_id": "t1",
        "engine_turn_id": "e1",
        "acp_session_id": "s1",
    }
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
                        {"type": "stderr", "text": "ModuleNotFoundError: No module named 'x'"},
                    ],
                },
            },
        },
        binding,
    )
    assert finished is not None and finished.type == EngineEventType.TOOL_FINISHED
    assert finished.payload["status"] == "failed"
    # summary 保留工具结果原文；details/error 附上命令摘要与 stderr 尾部
    assert finished.payload["summary"] == (
        "Traceback (most recent call last)\nModuleNotFoundError: No module named 'x'"
    )
    assert "命令：python fix_script.py" in finished.payload["details"]
    assert "ModuleNotFoundError" in finished.payload["details"]
    assert "命令：python fix_script.py" in finished.payload["error"]


class OutOfSandboxServer(FakeAcpServer):
    """工具目标路径在项目目录之外——触发编排器 TOOL_STARTED 分支的沙箱 break。"""

    async def handle_request(self, method: str, params: dict) -> dict:
        if method == "session/prompt":
            session_id = str(params.get("sessionId") or "")
            self.current_session = session_id
            await self.transport._emit_notification(
                {
                    "method": "session/update",
                    "params": {
                        "sessionId": session_id,
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "我看一下那份 3D 计划。"},
                        }
                    },
                }
            )
            await self.transport._emit_notification(
                {
                    "method": "session/update",
                    "params": {
                        "sessionId": session_id,
                        "update": {
                            "sessionUpdate": "tool_call",
                            "toolCallId": "tool-outside",
                            "title": "read",
                            "kind": "read",
                            "rawInput": {"path": "C:/outside/3d_plan.txt"},
                        }
                    },
                }
            )
            return {"stopReason": "end_turn", "sessionId": session_id}
        return await super().handle_request(method, params)


@pytest.mark.asyncio
async def test_aclose_releases_session_subscription_after_mid_turn_break(
    engine_and_server,
) -> None:
    """V0.3.3：消费方在 TOOL_STARTED 后 aclose() 回合，订阅槽位必须归还。

    编排器用 contextlib.aclosing 包裹 run_turn 的 async for；break/异常/
    取消都会触发 aclose()。若 engine 的 ``except BaseException`` 分支吞掉
    GeneratorExit，aclose() 会抛 RuntimeError，订阅器滞留，同一 session
    的再次 run_turn 立即撞 "already has an active notification subscriber"。
    """
    engine, _transport, _server = engine_and_server
    ref = await engine.open_session(
        ProjectRef(project_id="p1", name="项目", root_path="C:/project")
    )

    async def break_after_tool_started() -> None:
        async with aclosing(
            engine.run_turn(
                ref,
                TaskRequest(
                    conversation_id="c1", origin_message_id="m1", instructions="检查项目文件"
                ),
            )
        ) as stream:
            async for event in stream:
                if event.type == EngineEventType.TOOL_STARTED:
                    break

    await break_after_tool_started()
    # 订阅槽位已随 aclose 释放：同一 session 能再次进入 run_turn 并完整收尾
    events = [
        event
        async for event in engine.run_turn(
            ref,
            TaskRequest(
                conversation_id="c1", origin_message_id="m2", instructions="继续检查"
            ),
        )
    ]
    assert events[-1].type == EngineEventType.TURN_COMPLETED


@pytest.mark.asyncio
async def test_sandbox_denial_break_does_not_leak_session_subscription() -> None:
    """V0.3.3 回归：沙箱拒绝 break 不再泄漏 ACP 会话订阅器。

    复现路径：TOOL_STARTED 目标路径越界 → orchestrator 在 TOOL_STARTED
    分支 break 跳出事件循环。修复前 break 不关闭异步生成器，run_turn 的
    finally 不执行，订阅槽位滞留；同一聊天第二次委派复用同一 ACP session，
    open_session(resume) 立即撞 "already has an active notification
    subscriber"，每次重试都死在同一步。
    """
    transport = FakeTransport()
    server = OutOfSandboxServer(transport)
    transport.server = server
    engine = AcpCodingEngine(transport)
    orchestrator = ConversationOrchestrator(
        pair_id="march7_fourth_mirror",
        project=ProjectRef(project_id="p", name="p", root_path="C:\\project"),
        dialogue_model=FixedDialogueModel(
            CharacterTurn(speech="被拦住了。", delegation=None),
            CharacterTurn(speech="再试一次。", delegation=None),
        ),
        coding_engine=engine,
        store=None,
        approval_mode=ApprovalMode.REQUEST_APPROVAL,
    )

    first = await orchestrator.handle_direct_input(
        conversation_id="c", text="查一下 C 盘那份 3D 计划"
    )
    assert first.receipt is not None
    assert first.receipt.status == "failed"
    assert any("路径越界" in err for err in first.receipt.errors)
    # 沙箱拒绝卡片附可操作提示（不改动沙箱边界）
    card_texts = [m.text for m in first.messages if m.source == MessageSource.SYSTEM]
    assert any(
        "路径在绑定项目之外" in text and "移入项目目录" in text for text in card_texts
    )

    # 同聊天第二次委派复用同一 ACP session；订阅器若泄漏，此处直接抛
    # RuntimeError("session ... already has an active notification subscriber")
    second = await orchestrator.handle_direct_input(
        conversation_id="c", text="再查一次那份 3D 计划"
    )
    assert second.receipt is not None
    assert second.receipt.status == "failed"
    assert any("路径越界" in err for err in second.receipt.errors)
