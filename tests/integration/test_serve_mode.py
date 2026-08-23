"""V0.3.3 --serve 模式端到端集成：真实 WS 客户端全链路（配对→token→命令→事件扇出）。

复现手机远程 P0 的主路径：SidecarRouter + demo service + WSServerMode
在同一事件循环内并行运行，stdin 语义不受影响；用真实 aiohttp WS 客户端
走完 配对 → 鉴权命令 → 事件扇出 → 撤销拒绝 全链路，不用假连接。
"""

from __future__ import annotations

import asyncio
import io
import json
import socket
from typing import Any

import aiohttp
import pytest

from pair_harness.desktop_backend.application_service import build_demo_service
from pair_harness.desktop_backend.event_fanout import EventFanout
from pair_harness.desktop_backend.router import JsonlWriter, SidecarRouter
from pair_harness.desktop_backend.ws_server import WSServerMode


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class SidecarHarness:
    """--serve 模式的进程内等价装配（__main__._run 的核心路径）。"""

    def __init__(self, tmp_path, stdout: io.StringIO) -> None:
        self.stdout = stdout
        self.writer = JsonlWriter(stdout)
        self.fanout = EventFanout(self.writer)
        self.service = build_demo_service(
            database=tmp_path / "data" / "pair_harness.db",
            project_root=tmp_path,
            event_sink=self.fanout.publish,
        )
        self.router = SidecarRouter(self.service, self.writer)
        self.port = _free_port()
        self.server = WSServerMode(
            dispatch=self.router.dispatch,
            authenticator=self.service.pairing_service,
            fanout=self.fanout,
            static_root=None,
            port=self.port,
        )
        # 与 __main__._run 相同装配：撤销 token 立即断开已建立连接（V0.3.4 缺陷 7）。
        self.service.pairing_service.add_revoke_listener(
            self.server.close_connections_for_token
        )

    async def start(self) -> None:
        await self.server.start()

    async def stop(self) -> None:
        await self.server.stop()
        await self.service.shutdown()


async def _recv_message(ws: aiohttp.ClientWebSocketResponse) -> dict[str, Any]:
    """读取下一条 WS 消息并解析为 dict；超时或非文本即失败。"""
    raw = await asyncio.wait_for(ws.receive(), timeout=5.0)
    assert raw.type == aiohttp.WSMsgType.TEXT, raw
    import json

    return json.loads(raw.data)


async def _request(
    ws: aiohttp.ClientWebSocketResponse, method: str, rid: str, *, token: str | None = None
) -> dict[str, Any]:
    frame: dict[str, Any] = {"kind": "request", "id": rid, "method": method, "params": {}}
    if token:
        frame["auth"] = {"token": token}
    await ws.send_json(frame)
    # response 之前的消息只可能是事件（本测试中不订阅事件前不应出现）
    for _ in range(10):
        message = await _recv_message(ws)
        if message.get("kind") == "response":
            return message
    raise AssertionError("10 条消息内未收到 response")


@pytest.mark.asyncio
async def test_serve_mode_full_remote_path(tmp_path) -> None:
    harness = SidecarHarness(tmp_path, io.StringIO())
    await harness.start()
    session = aiohttp.ClientSession()
    try:
        # 1. 未配对连接：业务命令被拒
        ws = await session.ws_connect(f"http://127.0.0.1:{harness.port}/ws")
        denied = await _request(ws, "app.bootstrap", "r1")
        assert denied["ok"] is False
        assert denied["error"]["code"] == "unauthorized"
        assert denied["error"]["message"] == "missing_token"

        # 2. remote.pair 白名单放行：换 token
        code = harness.service.pairing_service.issue_code()
        frame = {
            "kind": "request",
            "id": "r2",
            "method": "remote.pair",
            "params": {"code": code, "device_name": "测试手机"},
        }
        await ws.send_json(frame)
        paired = await _recv_message(ws)
        while paired.get("kind") != "response":
            paired = await _recv_message(ws)
        assert paired["ok"] is True, paired
        token = paired["result"]["token"]

        # 3. 带 token 的命令进入 dispatch，response 写回同一连接
        boot = await _request(ws, "app.bootstrap", "r3", token=token)
        assert boot["ok"] is True, boot
        assert "projects" in boot["result"]

        # 4. 鉴权完成后连接订阅事件扇出：桌面事件同时到达 stdout 与手机
        harness.service.emitter.emit("test.event", {"hello": "world"})
        event = await _recv_message(ws)
        assert event["kind"] == "event"
        assert event["event"] == "test.event"
        assert event["payload"] == {"hello": "world"}

        # 5. stdout 收到同一事件（JsonlWriter 权威路径）
        stdout_lines = [
            line for line in harness.stdout.getvalue().splitlines() if line.strip()
        ]
        import json as _json

        stdout_events = [
            _json.loads(line)
            for line in stdout_lines
            if _json.loads(line).get("kind") == "event"
        ]
        assert any(
            e.get("event") == "test.event" for e in stdout_events
        ), "stdout 未收到扇出事件"

        # 6. 错误 token 拒绝
        bad = await _request(ws, "app.bootstrap", "r4", token="forged-token")
        assert bad["ok"] is False
        assert bad["error"]["code"] == "unauthorized"

        # 7. 撤销后立即拒绝：旧连接被服务端主动关闭（V0.3.4 缺陷 7 修复行为），
        #    重连后带已撤销 token 的请求仍被拒
        harness.service.pairing_service.revoke(token)
        closed = await asyncio.wait_for(ws.receive(), timeout=5.0)
        assert closed.type == aiohttp.WSMsgType.CLOSE, closed
        assert ws.close_code == 4401
        ws = await session.ws_connect(f"http://127.0.0.1:{harness.port}/ws")
        revoked = await _request(ws, "app.bootstrap", "r5", token=token)
        assert revoked["ok"] is False
        assert revoked["error"]["code"] == "unauthorized"
        assert revoked["error"]["message"] == "revoked_token"

        await ws.close()
    finally:
        await session.close()
        await harness.stop()


@pytest.mark.asyncio
async def test_serve_mode_two_clients_event_continuity(tmp_path) -> None:
    """两台已配对手机同时在线：同一事件到达两条连接；一台断开后另一台继续收。"""
    harness = SidecarHarness(tmp_path, io.StringIO())
    await harness.start()
    session = aiohttp.ClientSession()
    try:
        tokens = []
        for i in range(2):
            code = harness.service.pairing_service.issue_code()
            token = harness.service.pairing_service.claim(code, device_name=f"手机{i}")
            tokens.append(token)
        ws1 = await session.ws_connect(f"http://127.0.0.1:{harness.port}/ws")
        ws2 = await session.ws_connect(f"http://127.0.0.1:{harness.port}/ws")
        # 两台都先完成一次鉴权命令（触发订阅）
        for ws, token, rid in ((ws1, tokens[0], "a1"), (ws2, tokens[1], "a2")):
            boot = await _request(ws, "app.bootstrap", rid, token=token)
            assert boot["ok"] is True

        # 事件同时到达两台
        harness.service.emitter.emit("test.broadcast", {"seq": 1})
        for ws in (ws1, ws2):
            event = await _recv_message(ws)
            assert event["event"] == "test.broadcast"
            assert event["payload"] == {"seq": 1}

        # 断开 ws1，事件继续到达 ws2（连接隔离）
        await ws1.close()
        await asyncio.sleep(0.05)
        harness.service.emitter.emit("test.broadcast", {"seq": 2})
        event2 = await _recv_message(ws2)
        assert event2["payload"] == {"seq": 2}

        await ws2.close()
    finally:
        await session.close()
        await harness.stop()


@pytest.mark.asyncio
async def test_serve_port_conflict_degrades_to_stdin_only(
    tmp_path, monkeypatch
) -> None:
    """端口被占时 --serve 降级：error.reported 如实上报，stdin 路径照常退出 0。"""
    import argparse
    import sys

    import pair_harness.desktop_backend.__main__ as backend_main

    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # 与 WSServerMode 的 0.0.0.0 同地址族占用；绑 127.0.0.1 在 Windows 下
    # 会被 0.0.0.0 叠加绑定而不报错，测不出端口冲突（测试刻意行为）。
    blocker.bind(("0.0.0.0", 0))  # codeql[py/bind-socket-all-network-interfaces]
    blocker.listen(1)
    port = int(blocker.getsockname()[1])
    try:
        out = io.StringIO()
        monkeypatch.setattr(sys, "stdin", io.StringIO())
        monkeypatch.setattr(sys, "stdout", out)
        args = argparse.Namespace(
            serve=port,
            demo=True,
            real=False,
            pair="phainon_ancient_machine",
            project=tmp_path,
            data_dir=tmp_path / "data",
        )
        rc = await backend_main._run(args)
        assert rc == 0

        lines = [json.loads(line) for line in out.getvalue().splitlines()]
        events = [m for m in lines if m.get("kind") == "event"]
        event_names = {m["event"] for m in events}
        # 服务正常起来，远程不可用如实上报，stdin 主路径不受影响
        assert "backend.ready" in event_names
        assert "app.shutdown" not in event_names
        error_events = [m for m in events if m["event"] == "error.reported"]
        assert len(error_events) == 1
        payload = error_events[0]["payload"]
        assert payload["code"] == "serve_start_failed"
        assert str(port) in payload["message"]
        assert payload["fatal"] is False
    finally:
        blocker.close()


@pytest.mark.asyncio
async def test_revoke_closes_established_connection(tmp_path) -> None:
    """V0.3.4 缺陷 7 回归：撤销 token 后，静默在线的已建立连接立即断开、
    不再收到任何事件；其他 token 的连接不受影响。"""
    harness = SidecarHarness(tmp_path, io.StringIO())
    await harness.start()
    session = aiohttp.ClientSession()
    try:
        code1 = harness.service.pairing_service.issue_code()
        token1 = harness.service.pairing_service.claim(code1, device_name="手机A")
        code2 = harness.service.pairing_service.issue_code()
        token2 = harness.service.pairing_service.claim(code2, device_name="手机B")

        ws1 = await session.ws_connect(f"http://127.0.0.1:{harness.port}/ws")
        ws2 = await session.ws_connect(f"http://127.0.0.1:{harness.port}/ws")
        for ws, token, rid in ((ws1, token1, "a1"), (ws2, token2, "a2")):
            boot = await _request(ws, "app.bootstrap", rid, token=token)
            assert boot["ok"] is True

        # 撤销 token1：手机A 的连接应被服务端主动关闭
        assert harness.service.pairing_service.revoke(token1) is True
        raw = await asyncio.wait_for(ws1.receive(), timeout=5.0)
        assert raw.type == aiohttp.WSMsgType.CLOSE, raw
        assert ws1.close_code == 4401

        # 撤销后手机A 静默在线也不再收到事件：下一条只可能是关闭状态而非 TEXT
        harness.service.emitter.emit("test.after_revoke", {"seq": 9})
        event = await _recv_message(ws2)
        assert event["event"] == "test.after_revoke"
        after = await asyncio.wait_for(ws1.receive(), timeout=1.0)
        assert after.type != aiohttp.WSMsgType.TEXT, after

        await ws2.close()
        await ws1.close()
    finally:
        await session.close()
        await harness.stop()


@pytest.mark.asyncio
async def test_serve_started_reports_lan_address(tmp_path, monkeypatch) -> None:
    """V0.3.4 缺陷 6：serve 启动成功后上报 serve.started（host/port），
    桌面端二维码按它生成；stdin 正常 EOF 退出 0。"""
    import argparse
    import sys

    import pair_harness.desktop_backend.__main__ as backend_main

    port = _free_port()
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(backend_main, "_detect_lan_ip", lambda: "192.168.1.42")
    args = argparse.Namespace(
        serve=port,
        demo=True,
        real=False,
        pair="phainon_ancient_machine",
        project=tmp_path,
        data_dir=tmp_path / "data",
    )
    rc = await backend_main._run(args)
    assert rc == 0

    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    serve_events = [m for m in lines if m.get("event") == "serve.started"]
    assert len(serve_events) == 1
    assert serve_events[0]["payload"] == {"host": "192.168.1.42", "port": port}


@pytest.mark.asyncio
async def test_lan_ip_probe_failure_does_not_report_fake_address(
    tmp_path, monkeypatch
) -> None:
    """V0.3.4 Codex 建议 C：局域网地址探测失败（返回 None）时如实不下发
    serve.started，桌面端保持「地址未就绪」占位，不伪造 127.0.0.1 可达地址。"""
    import argparse
    import sys

    import pair_harness.desktop_backend.__main__ as backend_main

    port = _free_port()
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(backend_main, "_detect_lan_ip", lambda: None)
    args = argparse.Namespace(
        serve=port,
        demo=True,
        real=False,
        pair="phainon_ancient_machine",
        project=tmp_path,
        data_dir=tmp_path / "data",
    )
    rc = await backend_main._run(args)
    assert rc == 0

    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    serve_events = [m for m in lines if m.get("event") == "serve.started"]
    assert serve_events == []


@pytest.mark.asyncio
async def test_sigint_routes_to_orderly_stop(tmp_path, monkeypatch) -> None:
    """V0.3.4 缺陷 5：Ctrl+C 安装为与 app.shutdown 相同的有序停机路径。

    两条安装分支（事件循环 handler / Windows 进程级 handler）触发后都应
    请求 router 停机；安装函数返回恢复回调，不污染宿主进程的 SIGINT 处理。
    """
    import signal

    import pair_harness.desktop_backend.__main__ as backend_main
    from pair_harness.desktop_backend.router import SidecarRouter

    stdout = io.StringIO()
    harness = SidecarHarness(tmp_path, stdout)
    try:
        router = SidecarRouter(harness.service, JsonlWriter(io.StringIO()))
        loop = asyncio.get_running_loop()
        previous = signal.getsignal(signal.SIGINT)
        try:
            # 分支 1：强制走 Windows 式进程级 handler
            def unsupported(sig, callback):
                raise NotImplementedError

            monkeypatch.setattr(loop, "add_signal_handler", unsupported)
            restore = backend_main._install_sigint_stop(router)
            fallback_handler = signal.getsignal(signal.SIGINT)
            assert callable(fallback_handler)
            fallback_handler(signal.SIGINT, None)
            await asyncio.wait_for(router.wait_stopped(), timeout=1.0)
            restore()
            assert signal.getsignal(signal.SIGINT) is previous

            # 分支 2：事件循环原生 handler（Unix 路径；Windows 上移除接口同样
            # 不可用，一并替换以隔离宿主事件循环）
            installed: dict[int, object] = {}
            removed: list[int] = []
            monkeypatch.setattr(
                loop, "add_signal_handler", lambda sig, cb: installed.setdefault(sig, cb)
            )
            monkeypatch.setattr(
                loop, "remove_signal_handler", lambda sig: removed.append(sig)
            )
            router2 = SidecarRouter(harness.service, JsonlWriter(io.StringIO()))
            restore2 = backend_main._install_sigint_stop(router2)
            assert signal.SIGINT in installed
            installed[signal.SIGINT]()
            await asyncio.wait_for(router2.wait_stopped(), timeout=1.0)
            restore2()
            assert removed == [signal.SIGINT]
        finally:
            signal.signal(signal.SIGINT, previous)
    finally:
        await harness.stop()
