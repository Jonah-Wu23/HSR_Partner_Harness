from __future__ import annotations

import argparse
import asyncio
import io
import json
import signal
import socket
import sys
from typing import Any

import aiohttp
import pytest

import pair_harness.desktop_backend.__main__ as backend_main
from pair_harness.desktop_backend.application_service import ServiceError, build_demo_service
from pair_harness.desktop_backend.event_fanout import EventFanout
from pair_harness.desktop_backend.pairing import token_key
from pair_harness.desktop_backend.router import JsonlWriter, SidecarRouter
from pair_harness.desktop_backend.ws_server import RemoteServe, WSServerMode
from pair_harness.storage.records import TurnMetricQuery
from tests.service_helpers import call, wait_until


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class SidecarHarness:
    """与 __main__._run 相同的 --serve 装配：demo 服务、Router 与 WS 服务器共用一个事件循环。"""

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
        self.url = f"http://127.0.0.1:{self.port}/ws"
        self.server = WSServerMode(
            dispatch=self.router.dispatch,
            authenticator=self.service.pairing_service,
            fanout=self.fanout,
            static_root=None,
            port=self.port,
            on_disconnect=self.service.handle_remote_disconnect,
        )
        # 撤销设备时立即断开它的已建立连接
        self.service.pairing_service.add_revoke_listener(
            self.server.close_connections_for_device
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
    return json.loads(raw.data)


async def _request(
    ws: aiohttp.ClientWebSocketResponse,
    method: str,
    rid: str,
    *,
    token: str | None = None,
    **params: Any,
) -> dict[str, Any]:
    frame: dict[str, Any] = {"kind": "request", "id": rid, "method": method, "params": params}
    if token:
        frame["auth"] = {"token": token}
    await ws.send_json(frame)
    # response 之前可能先到本次请求引起的事件帧
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5.0
    while loop.time() < deadline:
        message = await _recv_message(ws)
        if message.get("kind") == "response":
            return message
    raise AssertionError(f"{method} 未在超时内收到 response")


async def test_serve_mode_full_remote_path(tmp_path) -> None:
    """未配对拒绝、配对换令牌、鉴权命令、事件扇出、伪造令牌拒绝、撤销后断开。"""
    harness = SidecarHarness(tmp_path, io.StringIO())
    await harness.start()
    session = aiohttp.ClientSession()
    try:
        ws = await session.ws_connect(harness.url)
        denied = await _request(ws, "app.bootstrap", "r1")
        assert denied["error"] == {"code": "unauthorized", "message": "missing_token"}

        code = harness.service.pairing_service.issue_code()
        paired = await _request(ws, "remote.pair", "r2", code=code, device_name="测试手机")
        assert paired["ok"] is True, paired
        token = paired["result"]["token"]

        boot = await _request(ws, "app.bootstrap", "r3", token=token)
        assert boot["ok"] is True, boot
        assert "projects" in boot["result"]

        # 鉴权后连接订阅事件扇出：同一事件到达手机与 stdout
        harness.service.emitter.emit("test.event", {"hello": "world"})
        event = await _recv_message(ws)
        assert (event["event"], event["payload"]) == ("test.event", {"hello": "world"})
        stdout_events = [json.loads(line) for line in harness.stdout.getvalue().splitlines()]
        assert any(e.get("event") == "test.event" for e in stdout_events)

        bad = await _request(ws, "app.bootstrap", "r4", token="forged-token")
        assert bad["error"]["code"] == "unauthorized"

        # 撤销后服务端主动断开；重连后带已撤销令牌的请求仍被拒
        harness.service.pairing_service.revoke_device("测试手机")
        closed = await asyncio.wait_for(ws.receive(), timeout=5.0)
        assert closed.type == aiohttp.WSMsgType.CLOSE, closed
        assert ws.close_code == 4401
        ws = await session.ws_connect(harness.url)
        revoked = await _request(ws, "app.bootstrap", "r5", token=token)
        assert revoked["error"] == {"code": "unauthorized", "message": "revoked_token"}
        await ws.close()
    finally:
        await session.close()
        await harness.stop()


async def test_pairing_code_failure_budget_spans_connections(tmp_path) -> None:
    """同一配对码在不同连接上的错误次数累计，用尽后该码作废，正确码也无法配对。"""
    harness = SidecarHarness(tmp_path, io.StringIO())
    await harness.start()
    session = aiohttp.ClientSession()
    try:
        code = (await call(harness.service, "issue", "remote.issue_code"))["code"]
        wrong = "000000" if code != "000000" else "111111"
        errors = []
        for attempt in range(5):
            async with session.ws_connect(harness.url) as ws:
                resp = await _request(
                    ws, "remote.pair", f"p{attempt}", code=wrong, device_name="phone"
                )
            errors.append(resp["error"]["code"])
        assert errors == ["pairing_invalid_code"] * 4 + ["pairing_code_exhausted"]

        async with session.ws_connect(harness.url) as ws:
            resp = await _request(ws, "remote.pair", "valid", code=code, device_name="phone")
        assert resp["error"]["code"] == "pairing_invalid_code"
    finally:
        await session.close()
        await harness.stop()


async def test_revoke_closes_established_connection(tmp_path) -> None:
    """撤销后该设备静默在线的连接立即断开且不再收到事件，其他设备不受影响。"""
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
        assert harness.service.pairing_service.revoke_device("手机A")
        raw = await asyncio.wait_for(ws1.receive(), timeout=5.0)
        assert raw.type == aiohttp.WSMsgType.CLOSE, raw
        assert ws1.close_code == 4401

        # 撤销后手机A 不再收到事件，连接上只剩关闭状态
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


async def test_remote_serve_address_reported_and_recoverable(service) -> None:
    """接入地址随 serve.started 下发，并由 app.bootstrap 与 remote.issue_code 一并返回。"""
    assert service.bootstrap()["remote_serve"] is None
    assert (await call(service, "code-1", "remote.issue_code"))["serve_address"] is None

    # 已监听但探测不到局域网地址：端口保留，host 为 null 并附原因码
    service.attach_remote_serve(RemoteServe(port=8765, lan=True, host=None))
    no_lan = {
        "host": None,
        "port": 8765,
        "mode": "lan",
        "tls": False,
        "reason": "no_lan_address",
    }
    assert service.event_log.payloads("serve.started") == [no_lan]
    assert service.bootstrap()["remote_serve"] == no_lan
    assert (await call(service, "code-2", "remote.issue_code"))["serve_address"] == no_lan


# ------------------------------------------------------------------ Sidecar 启动


def _run_args(
    tmp_path,
    *,
    serve: int | None = None,
    lan: bool = False,
    demo: bool = True,
    real: bool = False,
) -> argparse.Namespace:
    """__main__._run 的启动参数，字段与 Rust 侧实际传入的一致。"""
    return argparse.Namespace(
        serve=serve,
        lan=lan,
        demo=demo,
        real=real,
        pair="phainon_ancient_machine",
        project=tmp_path,
        data_dir=tmp_path / "data",
    )


def _isolate_from_dev_env(monkeypatch, tmp_path) -> None:
    """隔离开发机环境：不读 .env，不带进程级模式开关与对话配置。"""
    monkeypatch.setenv("PAIR_HARNESS_ENV_FILE", str(tmp_path / "absent.env"))
    for key in (
        "PAIR_HARNESS_REAL",
        "PAIR_HARNESS_DEMO",
        "PAIR_HARNESS_LAN",
        "PAIR_HARNESS_DIALOGUE_BASE_URL",
        "PAIR_HARNESS_DIALOGUE_API_KEY",
        "PAIR_HARNESS_DIALOGUE_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


def _stdio(monkeypatch, tmp_path, *requests: tuple[str, str]) -> io.StringIO:
    """把 Sidecar 的 stdin 换成按序的协议请求加 EOF，返回接收 stdout 的缓冲区。"""
    _isolate_from_dev_env(monkeypatch, tmp_path)
    lines = "".join(
        json.dumps({"kind": "request", "id": rid, "method": method, "params": {}}) + "\n"
        for rid, method in requests
    )
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(lines))
    monkeypatch.setattr(sys, "stdout", out)
    return out


def _messages(out: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in out.getvalue().splitlines()]


def _events(out: io.StringIO, name: str) -> list[dict[str, Any]]:
    return [m for m in _messages(out) if m.get("event") == name]


def _responses(out: io.StringIO) -> dict[str, dict[str, Any]]:
    return {m["id"]: m for m in _messages(out) if m.get("kind") == "response"}


@pytest.mark.parametrize("lan", [False, True])
async def test_serve_started_reports_address(tmp_path, monkeypatch, lan: bool) -> None:
    """--serve 监听成功后上报接入地址，app.bootstrap 返回同一地址；stdin EOF 后退出 0。"""
    port = _free_port()
    out = _stdio(monkeypatch, tmp_path, ("boot", "app.bootstrap"))
    assert await backend_main._run(_run_args(tmp_path, serve=port, lan=lan)) == 0

    host = backend_main._detect_lan_ip() if lan else "127.0.0.1"
    expected = RemoteServe(port=port, lan=lan, host=host).payload()
    assert expected["mode"] == ("lan" if lan else "loopback")
    assert [m["payload"] for m in _events(out, "serve.started")] == [expected]
    assert _responses(out)["boot"]["result"]["remote_serve"] == expected
    assert _events(out, "error.reported") == []


async def test_serve_port_conflict_degrades_to_stdin_only(tmp_path, monkeypatch) -> None:
    """端口被占时如实上报非致命的 serve_start_failed，stdin 路径照常运行并退出 0。"""
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = int(blocker.getsockname()[1])
    try:
        out = _stdio(monkeypatch, tmp_path, ("boot", "app.bootstrap"))
        assert await backend_main._run(_run_args(tmp_path, serve=port)) == 0
    finally:
        blocker.close()

    errors = [m["payload"] for m in _events(out, "error.reported")]
    assert len(errors) == 1
    assert errors[0]["code"] == "serve_start_failed"
    assert str(port) in errors[0]["message"]
    assert errors[0]["fatal"] is False
    assert _events(out, "serve.started") == []
    assert _responses(out)["boot"]["ok"] is True


async def test_explicit_demo_startup_uses_scripted_runtime(tmp_path, monkeypatch) -> None:
    out = _stdio(monkeypatch, tmp_path, ("probe", "config.test_connection"))
    assert await backend_main._run(_run_args(tmp_path, demo=True)) == 0

    ready = _events(out, "backend.ready")[0]["payload"]
    assert (ready["demo"], ready["mode_source"]) == (True, "explicit_demo")
    assert _responses(out)["probe"]["result"]["provider"] == "demo"


async def test_conflicting_mode_flags_fail_startup(tmp_path, monkeypatch) -> None:
    """同时声明 --real 与 --demo 时如实报启动错误并退出 2。"""
    out = _stdio(monkeypatch, tmp_path)
    assert await backend_main._run(_run_args(tmp_path, demo=True, real=True)) == 2

    errors = [m["payload"] for m in _events(out, "error.reported")]
    assert [(e["code"], e["fatal"]) for e in errors] == [("conflicting_start_mode", True)]
    assert _events(out, "backend.ready") == []


async def test_undeclared_mode_without_key_reaches_onboarding(tmp_path, monkeypatch) -> None:
    """未声明模式时默认真实接线；没有 Key 也照常启动进入首次引导，连接测试如实报缺配置。"""
    out = _stdio(
        monkeypatch,
        tmp_path,
        ("boot", "app.bootstrap"),
        ("probe", "config.test_connection"),
    )
    assert await backend_main._run(_run_args(tmp_path, demo=False)) == 0

    ready = _events(out, "backend.ready")[0]["payload"]
    assert (ready["demo"], ready["mode_source"]) == (False, "default_real")
    assert [m for m in _events(out, "error.reported") if m["payload"]["fatal"]] == []
    responses = _responses(out)
    current = responses["boot"]["result"]["current_account"]
    assert current["onboarding_complete"] is False
    probe = responses["probe"]["result"]
    assert probe["ok"] is False
    assert "缺少对话服务配置" in probe["message"]


@pytest.mark.parametrize(
    ("argv", "env", "expected"),
    [
        (["--real"], {}, (False, "explicit_real")),
        ([], {"PAIR_HARNESS_DEMO": "1"}, (True, "explicit_demo")),
        ([], {"PAIR_HARNESS_REAL": "yes"}, (False, "explicit_real")),
        ([], {"PAIR_HARNESS_DEMO": "1", "PAIR_HARNESS_REAL": "0"}, (True, "explicit_demo")),
        (["--real"], {"PAIR_HARNESS_DEMO": "1"}, (False, "explicit_real")),
        ([], {"PAIR_HARNESS_DEMO": "1", "PAIR_HARNESS_REAL": "1"}, "conflicting_start_mode"),
        ([], {"PAIR_HARNESS_DEMO": "maybe"}, "invalid_start_flag"),
    ],
)
def test_startup_mode_resolution(monkeypatch, argv, env, expected) -> None:
    """命令行优先，其次是 PAIR_HARNESS_REAL / PAIR_HARNESS_DEMO（含 .env 载入的值）。"""
    for key in ("PAIR_HARNESS_REAL", "PAIR_HARNESS_DEMO"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    args = backend_main.build_parser().parse_args(argv)
    if isinstance(expected, str):
        with pytest.raises(ServiceError) as excinfo:
            backend_main._resolve_startup_mode(args)
        assert excinfo.value.code == expected
    else:
        assert backend_main._resolve_startup_mode(args) == expected


@pytest.mark.parametrize(
    ("argv", "env_lan", "expected"),
    [
        ([], None, False),
        ([], "on", True),
        (["--no-lan"], "on", False),
        (["--lan"], "0", True),
    ],
)
def test_lan_resolution(monkeypatch, argv, env_lan, expected) -> None:
    """--lan / --no-lan 优先，其次 PAIR_HARNESS_LAN，默认只监听回环地址。"""
    if env_lan is None:
        monkeypatch.delenv("PAIR_HARNESS_LAN", raising=False)
    else:
        monkeypatch.setenv("PAIR_HARNESS_LAN", env_lan)
    assert backend_main._resolve_lan(backend_main.build_parser().parse_args(argv)) is expected


async def test_sigint_requests_orderly_stop(service) -> None:
    """Ctrl+C 与 app.shutdown 走同一有序停机路径，恢复回调还原原有的 SIGINT 处理。"""
    router = SidecarRouter(service, JsonlWriter(io.StringIO()))
    previous = signal.getsignal(signal.SIGINT)
    restore = backend_main._install_sigint_stop(router)
    try:
        # 未安装成功时不发信号，避免 KeyboardInterrupt 中断测试进程
        assert signal.getsignal(signal.SIGINT) is not previous
        signal.raise_signal(signal.SIGINT)
        await asyncio.wait_for(router.wait_stopped(), timeout=1.0)
    finally:
        restore()
    assert signal.getsignal(signal.SIGINT) is previous


async def test_remote_submit_metric_records_origin_and_device(tmp_path) -> None:
    """手机经 WS 提交的回合，指标如实记录 remote 来源、设备身份与设备名。"""
    harness = SidecarHarness(tmp_path, io.StringIO())
    await harness.start()
    session = aiohttp.ClientSession()
    try:
        code = harness.service.pairing_service.issue_code()
        token = harness.service.pairing_service.claim(code, device_name="指标手机")
        conversation_id = harness.service.current_conversation_id
        ws = await session.ws_connect(harness.url)
        response = await _request(
            ws,
            "chat.submit",
            "m1",
            token=token,
            conversation_id=conversation_id,
            target="character",
            text="来自手机的消息",
        )
        assert response["ok"] is True, response
        turn_id = response["result"]["turn_id"]

        def metric():
            page = harness.service.store.query_turn_metrics(
                TurnMetricQuery(conversation_id=conversation_id, limit=50)
            )
            return next((m for m in page.items if m.turn_id == turn_id), None)

        await wait_until(lambda: metric() is not None, message="回合终态应写入指标")
        record = metric()
        assert record.origin == "remote"
        assert record.remote_device_key == token_key(token)
        assert record.remote_device_name == "指标手机"
        await ws.close()
    finally:
        await session.close()
        await harness.stop()
