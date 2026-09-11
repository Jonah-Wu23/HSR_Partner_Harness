"""V0.3.3 --serve 模式端到端集成：真实 WS 客户端全链路（配对→token→命令→事件扇出）。

复现手机远程 P0 的主路径：SidecarRouter + demo service + WSServerMode
在同一事件循环内并行运行，stdin 语义不受影响；用真实 aiohttp WS 客户端
走完 配对 → 鉴权命令 → 事件扇出 → 撤销拒绝 全链路，不用假连接。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import socket
import sys
import threading
from typing import Any

import aiohttp
import pytest

from pair_harness.adapters.demo import ScriptedDialogueModel
from pair_harness.desktop_backend.application_service import build_demo_service
from pair_harness.desktop_backend.event_fanout import EventFanout
from pair_harness.desktop_backend.router import JsonlWriter, SidecarRouter
from pair_harness.desktop_backend.ws_server import WSServerMode
from pair_harness.storage.records import TurnMetricQuery


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


class _BlockingStdin(io.StringIO):
    """可手动放行的 stdin：readline 阻塞到 release()。

    run_stdin 在独立线程里读 stdin，阻塞读取不会卡住事件循环，
    因此用例可以在服务运行期间查询命令，再放行 EOF 走正常停机。
    """

    def __init__(self) -> None:
        super().__init__()
        self._released = threading.Event()

    def readline(self, *args, **kwargs) -> str:  # type: ignore[override]
        self._released.wait()
        return ""

    def release(self) -> None:
        self._released.set()


async def _wait_until(predicate, *, message: str, timeout: float = 10.0) -> None:
    """轮询等待条件成立；超时直接失败，不静默跳过。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(message)


def _run_args(tmp_path, *, serve: int | None = None, demo: bool = True, real: bool = False):
    """__main__._run 的启动参数（与 Rust 侧实际传入的字段一致）。"""
    import argparse

    return argparse.Namespace(
        serve=serve,
        demo=demo,
        real=real,
        pair="phainon_ancient_machine",
        project=tmp_path,
        data_dir=tmp_path / "data",
    )


def _capture_service(monkeypatch, backend_main) -> dict[str, Any]:
    """包住 build_configured_service，拿到 _run 内部真正构造的服务实例。"""
    captured: dict[str, Any] = {}
    original = backend_main.build_configured_service

    def wrapper(**kwargs):
        service = original(**kwargs)
        captured["service"] = service
        captured["demo"] = kwargs.get("demo")
        return service

    monkeypatch.setattr(backend_main, "build_configured_service", wrapper)
    return captured



@pytest.mark.asyncio
async def test_serve_started_reports_lan_address(tmp_path, monkeypatch) -> None:
    """V0.3.4 缺陷 6 / V039-S4-004：serve 启动成功后上报 serve.started（host/port），
    桌面端二维码按它生成；同一事实同时落在 service.remote_serve_address，
    服务层可按需读取（不必只依赖一次性事件）；stdin 正常 EOF 退出 0。"""
    import pair_harness.desktop_backend.__main__ as backend_main

    port = _free_port()
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(backend_main, "_detect_lan_ip", lambda: "192.168.1.42")
    captured = _capture_service(monkeypatch, backend_main)
    rc = await backend_main._run(_run_args(tmp_path, serve=port))
    assert rc == 0

    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    serve_events = [m for m in lines if m.get("event") == "serve.started"]
    assert len(serve_events) == 1
    assert serve_events[0]["payload"] == {"host": "192.168.1.42", "port": port}
    assert captured["service"].remote_serve_address == {
        "host": "192.168.1.42",
        "port": port,
    }


@pytest.mark.asyncio
async def test_lan_ip_probe_failure_reports_started_without_address(
    tmp_path, monkeypatch
) -> None:
    """V039-S4-004 事件契约：服务确已监听、只是探测不到局域网地址时，
    serve.started 仍下发且 host 为 null、reason 为 no_lan_address
    （不伪造 127.0.0.1 / 0.0.0.0 等不可达地址），同时不下发
    serve_start_failed——桌面端据此把「已启动但无局域网地址」与
    「--serve 未启动/启动失败」区分开。"""
    import pair_harness.desktop_backend.__main__ as backend_main

    port = _free_port()
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(backend_main, "_detect_lan_ip", lambda: None)
    captured = _capture_service(monkeypatch, backend_main)
    rc = await backend_main._run(_run_args(tmp_path, serve=port))
    assert rc == 0

    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    serve_events = [m for m in lines if m.get("event") == "serve.started"]
    assert len(serve_events) == 1
    expected = {"host": None, "port": port, "reason": "no_lan_address"}
    assert serve_events[0]["payload"] == expected
    assert captured["service"].remote_serve_address == expected
    failures = [
        m for m in lines
        if m.get("event") == "error.reported"
        and m["payload"].get("code") == "serve_start_failed"
    ]
    assert failures == [], "服务已监听时不得上报启动失败"


def _isolate_from_dev_env(monkeypatch, tmp_path) -> None:
    """把用例与开发机环境隔离：无 .env、无进程级对话配置。"""
    monkeypatch.setenv("PAIR_HARNESS_ENV_FILE", str(tmp_path / "absent.env"))
    for key in (
        "PAIR_HARNESS_DIALOGUE_BASE_URL",
        "PAIR_HARNESS_DIALOGUE_API_KEY",
        "PAIR_HARNESS_DIALOGUE_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.asyncio
async def test_explicit_demo_startup_stays_scripted(tmp_path, monkeypatch) -> None:
    """V039-S4-002：显式声明 --demo 时按脚本化适配器启动，
    backend.ready 如实上报 demo=True 与来源 explicit_demo。"""
    import pair_harness.desktop_backend.__main__ as backend_main

    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setattr(sys, "stdout", out)
    captured = _capture_service(monkeypatch, backend_main)
    rc = await backend_main._run(_run_args(tmp_path, demo=True))
    assert rc == 0

    ready = _events(out, "backend.ready")[0]["payload"]
    assert ready["demo"] is True
    assert ready["mode_source"] == "explicit_demo"
    assert captured["demo"] is True
    assert isinstance(captured["service"].dialogue_model, ScriptedDialogueModel)


@pytest.mark.asyncio
async def test_conflicting_mode_flags_fail_startup(tmp_path, monkeypatch) -> None:
    """同时声明 --real 与 --demo 是调用方的矛盾输入：如实报启动错误并退出 2，
    不挑一个模式执行。"""
    import pair_harness.desktop_backend.__main__ as backend_main

    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setattr(sys, "stdout", out)
    rc = await backend_main._run(_run_args(tmp_path, demo=True, real=True))
    assert rc == 2

    errors = _events(out, "error.reported")
    assert len(errors) == 1
    assert errors[0]["payload"]["code"] == "conflicting_start_mode"
    assert errors[0]["payload"]["fatal"] is True
    assert _events(out, "backend.ready") == []


@pytest.mark.asyncio
async def test_undeclared_mode_without_key_reaches_onboarding(
    tmp_path, monkeypatch
) -> None:
    """V039-S4-002 主路径：没有 .env、也没有声明模式（默认真实接线）时，
    账号未配 Key 也必须照常起来并进入首次引导，不能因为没配 Key 就崩溃；
    config.test_connection 如实报「缺少对话服务配置」，不合成成功，
    也不退回演示数据。"""
    import pair_harness.desktop_backend.__main__ as backend_main
    from pair_harness.desktop_backend.commands import DesktopCommand

    out = io.StringIO()
    stdin = _BlockingStdin()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", out)
    _isolate_from_dev_env(monkeypatch, tmp_path)
    captured = _capture_service(monkeypatch, backend_main)
    task = asyncio.create_task(
        backend_main._run(_run_args(tmp_path, demo=False, real=False))
    )
    try:
        await _wait_until(lambda: "service" in captured, message="服务未构造")
        await _wait_until(
            lambda: "backend.ready" in out.getvalue(),
            message="backend.ready 未上报",
        )
        ready = _events(out, "backend.ready")[0]["payload"]
        assert ready["demo"] is False
        assert ready["mode_source"] == "default_real"
        fatal = [
            m for m in _events(out, "error.reported") if m["payload"].get("fatal")
        ]
        assert fatal == [], "未配 Key 不得变成启动失败"

        service = captured["service"]
        bootstrap = await service.handle_command(
            DesktopCommand(request_id="boot-1", method="app.bootstrap", params={})
        )
        current = bootstrap["current_account"]
        assert current["account_id"] == "default-local"
        assert current["onboarding_complete"] is False
        # 未配供应商时如实报缺配置（离线判定，不发起真实请求）
        probe = await service.handle_command(
            DesktopCommand(
                request_id="probe-1", method="config.test_connection", params={}
            )
        )
        assert probe["ok"] is False
        assert "缺少对话服务配置" in probe["message"]
    finally:
        stdin.release()
        assert await asyncio.wait_for(task, timeout=15) == 0


def _events(out: io.StringIO, name: str) -> list[dict[str, Any]]:
    """按事件名筛出 stdout JSONL 里的事件。"""
    return [
        message
        for message in (json.loads(line) for line in out.getvalue().splitlines())
        if message.get("event") == name
    ]


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


@pytest.mark.asyncio
async def test_remote_submit_metric_records_origin_and_device(tmp_path) -> None:
    """V0.3.9 §5：手机经 WS 提交的回合，指标如实记录 remote 来源与设备。

    全链路：真实 WS 客户端 → WSServerMode 鉴权 → Router 注入
    origin/device_key/device_name → chat.submit → TurnMetric。
    """
    harness = SidecarHarness(tmp_path, io.StringIO())
    await harness.start()
    session = aiohttp.ClientSession()
    try:
        code = harness.service.pairing_service.issue_code()
        token = harness.service.pairing_service.claim(code, device_name="指标手机")
        conversation_id = harness.service.current_conversation_id
        ws = await session.ws_connect(f"http://127.0.0.1:{harness.port}/ws")
        await ws.send_json(
            {
                "kind": "request",
                "id": "m1",
                "method": "chat.submit",
                "params": {
                    "conversation_id": conversation_id,
                    "target": "character",
                    "text": "来自手机的消息",
                },
                "auth": {"token": token},
            }
        )
        # response 之前可能有本回合的事件先到，按 kind 过滤直到拿到 response。
        deadline = asyncio.get_running_loop().time() + 5.0
        response: dict[str, Any] | None = None
        while response is None:
            remaining = deadline - asyncio.get_running_loop().time()
            assert remaining > 0, "未在超时内收到 chat.submit response"
            message = await asyncio.wait_for(_recv_message(ws), timeout=remaining)
            if message.get("kind") == "response":
                response = message
        assert response["ok"] is True, response
        turn_id = response["result"]["turn_id"]

        def metric():
            page = harness.service.store.query_turn_metrics(
                TurnMetricQuery(conversation_id=conversation_id, limit=50)
            )
            return next((m for m in page.items if m.turn_id == turn_id), None)

        await _wait_until(lambda: metric() is not None, message="回合终态应写入指标")
        record = metric()
        assert record is not None
        assert record.origin == "remote"
        assert record.remote_device_key == hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()
        assert record.remote_device_name == "指标手机"
        await ws.close()
    finally:
        await session.close()
        await harness.stop()
