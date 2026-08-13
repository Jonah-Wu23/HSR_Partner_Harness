"""V0.2 M3：DeepSeek 编程助手（Reasonix ACP）适配器（方案 §M3-5）。

用内存 JSONL 连接模拟 ``reasonix acp`` 进程，验证会话打开、事件映射、
权限回复与取消。真机联调需要本地构建的 reasonix 二进制（见交付文档）。
"""

import asyncio
import json
from collections import deque

import pytest

from pair_harness.adapters.acp.engine import AcpCodingEngine
from pair_harness.adapters.codex.transport import JsonlProcessTransport
from pair_harness.core.contracts import (
    ApprovalDecision,
    EngineEventType,
    EngineSessionRef,
    ProjectRef,
    TaskRequest,
)


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
    """接管连接与请求/通知分发，模拟 ACP 服务端。"""

    def __init__(self) -> None:
        self.connection = FakeAcpConnection()
        self._next_request = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._notifications: asyncio.Queue = asyncio.Queue()
        self.server: "FakeAcpServer | None" = None

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
            # 脚本：先推消息与工具事件（session/update 形状），再返回 stop reason
            await self.transport._notifications.put(
                {
                    "method": "session/update",
                    "params": {
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "我先看一下项目结构。"},
                        }
                    },
                }
            )
            await self.transport._notifications.put(
                {
                    "method": "session/update",
                    "params": {
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
            await self.transport._notifications.put(
                {
                    "method": "session/update",
                    "params": {
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


@pytest.mark.asyncio
async def test_run_turn_maps_permission_request(engine_and_server) -> None:
    engine, transport, server = engine_and_server
    ref = await engine.open_session(
        ProjectRef(project_id="p1", name="项目", root_path="C:/project")
    )

    async def inject_permission() -> None:
        await asyncio.sleep(0.01)
        await transport._notifications.put(
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
