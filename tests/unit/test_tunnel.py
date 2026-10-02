from __future__ import annotations

import asyncio
import hashlib
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from aiohttp import web

from pair_harness.desktop_backend.events import EventEmitter
from pair_harness.desktop_backend.tunnel import (
    TunnelError,
    TunnelManager,
    detect_platform_asset,
    verify_file_hash,
)
from pair_harness.desktop_backend.ws_server import RemoteServe
from tests.service_helpers import EventLog, call, expect_service_error, wait_until

HOSTNAME = "test-random-tunnel.trycloudflare.com"


# ============================================================
# 官方资产与哈希校验
# ============================================================


@pytest.mark.parametrize(
    ("platform_name", "machine", "filename"),
    [
        ("win32", "AMD64", "cloudflared-windows-amd64.exe"),
        ("win32", "x86", "cloudflared-windows-386.exe"),
        ("linux", "x86_64", "cloudflared-linux-amd64"),
        ("linux", "aarch64", "cloudflared-linux-arm64"),
    ],
)
def test_detect_platform_asset(
    monkeypatch: pytest.MonkeyPatch, platform_name: str, machine: str, filename: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform_name)
    monkeypatch.setattr("platform.machine", lambda: machine)
    detected, url, _sha256 = detect_platform_asset()
    assert detected == filename
    assert url.endswith(f"/{filename}")


@pytest.mark.parametrize(
    ("platform_name", "machine", "code"),
    [
        ("darwin", "arm64", "unsupported_platform"),
        ("freebsd", "amd64", "unsupported_platform"),
        ("win32", "ARM64", "unsupported_architecture"),
    ],
)
def test_detect_platform_asset_rejects_unsupported(
    monkeypatch: pytest.MonkeyPatch, platform_name: str, machine: str, code: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform_name)
    monkeypatch.setattr("platform.machine", lambda: machine)
    with pytest.raises(TunnelError) as exc:
        detect_platform_asset()
    assert exc.value.code == code


def test_verify_file_hash(tmp_path: Path) -> None:
    content = b"cloudflared binary content"
    digest = hashlib.sha256(content).hexdigest()
    path = tmp_path / "cloudflared.bin"
    assert verify_file_hash(path, digest) is False
    path.write_bytes(content)
    assert verify_file_hash(path, digest) is True
    assert verify_file_hash(path, digest.upper()) is True
    assert verify_file_hash(path, "0" * 64) is False


# ============================================================
# TunnelManager 生命周期
# ============================================================


async def _unexpected_download(url: str, dest: Path) -> None:
    raise AssertionError(f"校验通过时不应下载：{url}")


class _OutputStream:
    """按行回放 cloudflared 输出；进程退出后返回 EOF。"""

    def __init__(self, lines: list[bytes]) -> None:
        self.lines = list(lines)
        self._wakeup = asyncio.Event()
        self._eof = False

    def feed(self, lines: list[bytes]) -> None:
        self.lines.extend(lines)
        self._wakeup.set()

    def close(self) -> None:
        self._eof = True
        self._wakeup.set()

    async def readline(self) -> bytes:
        while True:
            if self.lines:
                return self.lines.pop(0)
            if self._eof:
                return b""
            await self._wakeup.wait()
            self._wakeup.clear()


class _FakeCloudflared:
    """按 cloudflared 协议回放的子进程：在 --metrics 地址提供 /quicktunnel，输出按行回放。

    hostname 为 None 时表示申请主机名失败，metrics 服务不监听。
    """

    pid = 4242

    def __init__(
        self, args: tuple[str, ...], *, hostname: str | None, stderr: list[bytes]
    ) -> None:
        self.args = list(args)
        self.stderr = _OutputStream(stderr)
        self.stdout = _OutputStream([])
        self.returncode: int | None = None
        self.terminated = False
        self._hostname = hostname
        self._exited = asyncio.Event()
        self._metrics: web.AppRunner | None = None

    def arg(self, flag: str) -> str:
        return self.args[self.args.index(flag) + 1]

    async def serve_metrics(self) -> None:
        if self._hostname is None:
            return
        hostname = self._hostname

        async def quicktunnel(request: web.Request) -> web.Response:
            return web.json_response({"hostname": hostname})

        app = web.Application()
        app.router.add_get("/quicktunnel", quicktunnel)
        self._metrics = web.AppRunner(app)
        await self._metrics.setup()
        host, port = self.arg("--metrics").rsplit(":", 1)
        await web.TCPSite(self._metrics, host, int(port)).start()

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def exit(self, code: int) -> None:
        if self.returncode is not None:
            return
        self.returncode = code
        self.stderr.close()
        self.stdout.close()
        self._exited.set()

    def terminate(self) -> None:
        self.terminated = True
        self.exit(1)

    def kill(self) -> None:
        self.exit(-9)

    async def close(self) -> None:
        if self._metrics is not None:
            await self._metrics.cleanup()


@pytest.fixture
async def cloudflared(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[dict]:
    """替换子进程启动为回放的 cloudflared。

    官方二进制的 SHA-256 无法在离线测试中复现，校验结果在这里固定为通过；
    TunnelManager 没有资产表与进程工厂的注入点。
    """
    state: dict = {"hostname": HOSTNAME, "stderr": [], "spawned": []}

    async def create_subprocess_exec(*args: str, **kwargs) -> _FakeCloudflared:
        proc = _FakeCloudflared(args, hostname=state["hostname"], stderr=state["stderr"])
        await proc.serve_metrics()
        state["spawned"].append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)
    monkeypatch.setattr(
        "pair_harness.desktop_backend.tunnel.verify_file_hash", lambda path, sha256: True
    )
    yield state
    for proc in state["spawned"]:
        await proc.close()


def _manager(tmp_path: Path, log: EventLog, downloader=_unexpected_download) -> TunnelManager:
    return TunnelManager(data_dir=tmp_path, emitter=EventEmitter(log), downloader=downloader)


async def _wait_state(mgr: TunnelManager, state: str) -> None:
    await wait_until(lambda: mgr.state == state, message=f"隧道未进入 {state}：{mgr.status()}")


async def test_start_reads_hostname_from_metrics_and_stop_terminates(
    tmp_path: Path, cloudflared: dict
) -> None:
    cloudflared["stderr"] = [
        b"2026-09-11T08:00:00Z INF Requesting new quick Tunnel on trycloudflare.com...\n"
    ]
    log = EventLog()
    mgr = _manager(tmp_path, log)
    off = {"state": "off", "public_url": None, "hostname": None, "error": None}
    assert mgr.status() == off

    assert await mgr.start(local_port=8765) == {"status": "starting"}
    await _wait_state(mgr, "ready")
    public_url = f"https://{HOSTNAME}"
    assert mgr.status() == {
        "state": "ready",
        "public_url": public_url,
        "hostname": HOSTNAME,
        "error": None,
    }
    proc = cloudflared["spawned"][0]
    assert proc.arg("--url") == "http://127.0.0.1:8765"
    assert log.payloads("tunnel.started") == [{"public_url": public_url, "hostname": HOSTNAME}]

    assert await mgr.stop(reason="user_requested") == {"status": "stopping"}
    assert proc.terminated is True
    assert mgr.status() == off
    assert log.payloads("tunnel.stopped") == [{"reason": "user_requested"}]


async def test_process_exit_before_hostname_fails(tmp_path: Path, cloudflared: dict) -> None:
    """cloudflared 申请主机名失败后退出：日志里的 URL 不参与判定，隧道如实进入 failed。"""
    cloudflared["hostname"] = None
    cloudflared["stderr"] = [
        b'2026-09-11T08:00:00Z ERR failed to request quick Tunnel: Post '
        b'"https://api.trycloudflare.com/tunnel": dial tcp: i/o timeout\n'
    ]
    log = EventLog()
    mgr = _manager(tmp_path, log)
    await mgr.start(local_port=8765)
    await wait_until(lambda: cloudflared["spawned"], message="cloudflared 未启动")
    assert mgr.state == "starting"

    cloudflared["spawned"][0].exit(1)
    await _wait_state(mgr, "failed")
    assert "退出码 1" in mgr.error
    assert log.payloads("tunnel.started") == []
    assert log.payloads("tunnel.failed") == [{"error": mgr.error}]


async def test_external_kill_after_ready_fails(tmp_path: Path, cloudflared: dict) -> None:
    log = EventLog()
    mgr = _manager(tmp_path, log)
    await mgr.start(local_port=8765)
    await _wait_state(mgr, "ready")

    cloudflared["spawned"][0].exit(137)
    await _wait_state(mgr, "failed")
    assert "137" in mgr.error
    assert log.payloads("tunnel.failed") == [{"error": mgr.error}]


async def test_output_keeps_draining_after_ready(tmp_path: Path, cloudflared: dict) -> None:
    """就绪后持续读走 cloudflared 输出，避免管道写满让子进程阻塞。"""
    mgr = _manager(tmp_path, EventLog())
    await mgr.start(local_port=8765)
    await _wait_state(mgr, "ready")

    proc = cloudflared["spawned"][0]
    proc.stderr.feed(
        [f"2026-09-11T08:00:00Z INF request #{i} served\n".encode() for i in range(64)]
    )
    await wait_until(lambda: not proc.stderr.lines, message="就绪后的输出没有被读走")
    assert mgr.state == "ready"


async def test_download_failure_fails_tunnel(tmp_path: Path) -> None:
    async def offline_download(url: str, dest: Path) -> None:
        # urllib 的网络错误都是 OSError
        raise OSError("网络不可达")

    log = EventLog()
    mgr = _manager(tmp_path, log, downloader=offline_download)
    await mgr.start(local_port=8765)
    await _wait_state(mgr, "failed")
    assert "cloudflared 下载失败" in mgr.error
    assert "网络不可达" in mgr.error
    assert log.payloads("tunnel.failed") == [{"error": mgr.error}]


async def test_downloaded_binary_failing_hash_check_is_deleted(tmp_path: Path) -> None:
    """下载内容与官方 SHA-256 不符时删除文件并失败，不启动子进程。"""
    downloads: list[str] = []

    async def tampered_download(url: str, dest: Path) -> None:
        downloads.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"not the official cloudflared")

    log = EventLog()
    mgr = _manager(tmp_path, log, downloader=tampered_download)
    await mgr.start(local_port=8765)
    await _wait_state(mgr, "failed")
    assert downloads == [detect_platform_asset()[1]]
    assert not mgr.binary_path.exists()
    assert mgr.error == "下载后的 cloudflared 哈希校验失败"
    assert log.payloads("tunnel.failed") == [{"error": mgr.error}]


# ============================================================
# 应用服务的隧道命令
# ============================================================


async def test_tunnel_start_requires_registered_serve(service) -> None:
    """--serve 未成功监听时 remote.tunnel_start 如实拒绝，不回退默认端口。"""
    assert (await call(service, "status", "remote.tunnel_status"))["state"] == "off"
    await expect_service_error(
        lambda: call(service, "start", "remote.tunnel_start"), "serve_not_started"
    )


async def test_service_shutdown_stops_running_tunnel(service) -> None:
    """Sidecar 退出时关闭隧道并上报 sidecar_exit。"""
    release = asyncio.Event()

    async def pending_download(url: str, dest: Path) -> None:
        await release.wait()

    # 替换网络下载边界，隧道停在 downloading
    service.tunnel_manager.downloader = pending_download
    service.attach_remote_serve(RemoteServe(port=8765, lan=False, host="127.0.0.1"))
    await call(service, "start", "remote.tunnel_start")
    await wait_until(
        lambda: service.tunnel_manager.state == "downloading", message="隧道未开始下载"
    )

    await service.shutdown()
    assert service.event_log.payloads("tunnel.stopped") == [{"reason": "sidecar_exit"}]
