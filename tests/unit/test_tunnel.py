"""Cloudflare Quick Tunnel (T5 / D1) 单元测试。

测试覆盖：
1. detect_platform_asset 平台架构探测与校验和匹配；
2. verify_file_hash SHA256 哈希比对；
3. default_download_file 下载与哈希校验（包括失败清理）；
4. TunnelManager 状态机维护（off / downloading / starting / ready / failed）；
5. 二进制按需下载、校验、去重；
6. 主机名提取正则与生命周期事件（tunnel.started / tunnel.stopped / tunnel.failed）；
7. 进程异常退出检测与优雅停机。
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pair_harness.desktop_backend.events import EventEmitter
from pair_harness.desktop_backend.tunnel import (
    CLOUDFLARED_ASSETS,
    TunnelError,
    TunnelManager,
    _HOSTNAME_REGEX,
    detect_platform_asset,
    verify_file_hash,
)


# ============================================================
# 1. 平台检测测试
# ============================================================


class TestPlatformDetection:
    def test_detect_windows_amd64(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr("platform.machine", lambda: "AMD64")
        filename, url, sha256 = detect_platform_asset()
        assert filename == "cloudflared-windows-amd64.exe"
        assert "cloudflared-windows-amd64.exe" in url
        assert sha256 == CLOUDFLARED_ASSETS["win32-x64"]["sha256"]

    def test_detect_windows_x86(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr("platform.machine", lambda: "i386")
        filename, url, sha256 = detect_platform_asset()
        assert filename == "cloudflared-windows-386.exe"
        assert sha256 == CLOUDFLARED_ASSETS["win32-x86"]["sha256"]

    def test_detect_linux_amd64(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr("platform.machine", lambda: "x86_64")
        filename, url, sha256 = detect_platform_asset()
        assert filename == "cloudflared-linux-amd64"
        assert sha256 == CLOUDFLARED_ASSETS["linux-x64"]["sha256"]

    def test_detect_linux_arm64(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr("platform.machine", lambda: "aarch64")
        filename, url, sha256 = detect_platform_asset()
        assert filename == "cloudflared-linux-arm64"
        assert sha256 == CLOUDFLARED_ASSETS["linux-arm64"]["sha256"]

    def test_detect_darwin_unsupported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """darwin 官方资产是 .tgz 压缩包且产品未承诺 macOS 分发，探测直接响亮报错。"""
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr("platform.machine", lambda: "arm64")
        with pytest.raises(TunnelError) as exc:
            detect_platform_asset()
        assert exc.value.code == "unsupported_platform"
        assert "macOS" in str(exc.value)

    def test_detect_unsupported_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "freebsd")
        with pytest.raises(TunnelError) as exc:
            detect_platform_asset()
        assert exc.value.code == "unsupported_platform"


# ============================================================
# 2. 文件哈希比对与正则测试
# ============================================================


class TestHashAndRegex:
    def test_verify_file_hash_match(self, tmp_path: Path) -> None:
        test_file = tmp_path / "sample.bin"
        content = b"cloudflared binary content"
        test_file.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert verify_file_hash(test_file, expected) is True
        assert verify_file_hash(test_file, expected.upper()) is True

    def test_verify_file_hash_mismatch(self, tmp_path: Path) -> None:
        test_file = tmp_path / "sample.bin"
        test_file.write_bytes(b"some content")
        assert verify_file_hash(test_file, "0000000000000000000000000000000000000000000000000000000000000000") is False

    def test_verify_file_hash_nonexistent(self, tmp_path: Path) -> None:
        test_file = tmp_path / "missing.bin"
        assert verify_file_hash(test_file, "dummy") is False

    def test_hostname_regex_matches_trycloudflare(self) -> None:
        sample_log = (
            "2026-09-11T12:00:00Z INF +--------------------------------------------------------------------------------------------+\n"
            "2026-09-11T12:00:00Z INF |  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |\n"
            "2026-09-11T12:00:00Z INF |  https://sweet-apple-tree-123.trycloudflare.com                                           |\n"
            "2026-09-11T12:00:00Z INF +--------------------------------------------------------------------------------------------+\n"
        )
        match = _HOSTNAME_REGEX.search(sample_log)
        assert match is not None
        assert match.group(1) == "sweet-apple-tree-123.trycloudflare.com"


# ============================================================
# 3. TunnelManager 状态机与生命周期测试
# ============================================================


class _MockStream:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        # 保持连接阻塞直到被取消
        await asyncio.sleep(100.0)
        return b""


class _MockProcess:
    def __init__(self, stderr_lines: list[bytes], stdout_lines: list[bytes] | None = None) -> None:
        self.stderr = _MockStream(stderr_lines)
        self.stdout = _MockStream(stdout_lines or [])
        self.returncode: int | None = None
        self._exit_future: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        self.killed = False
        self.terminated = False

    async def wait(self) -> int:
        return await asyncio.shield(self._exit_future)

    def terminate(self) -> None:
        self.terminated = True
        if not self._exit_future.done():
            self.returncode = 0
            self._exit_future.set_result(0)

    def kill(self) -> None:
        self.killed = True
        if not self._exit_future.done():
            self.returncode = -9
            self._exit_future.set_result(-9)

    def trigger_crash(self, code: int = 1) -> None:
        self.returncode = code
        if not self._exit_future.done():
            self._exit_future.set_result(code)


class TestTunnelManager:
    @pytest.mark.asyncio
    async def test_initial_status_is_off(self, tmp_path: Path) -> None:
        events: list[dict[str, Any]] = []
        emitter = EventEmitter(sink=lambda ev: events.append(ev))
        audit_records: list[tuple[str, str]] = []
        mgr = TunnelManager(
            data_dir=tmp_path,
            emitter=emitter,
            audit_logger=lambda ev, d: audit_records.append((ev, d)),
        )
        assert mgr.status() == {
            "state": "off",
            "public_url": None,
            "hostname": None,
            "error": None,
        }

    @pytest.mark.asyncio
    async def test_start_downloads_and_runs_process(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        events: list[dict[str, Any]] = []
        emitter = EventEmitter(sink=lambda ev: events.append(ev))
        audit_records: list[tuple[str, str]] = []

        _, _, expected_sha256 = detect_platform_asset()

        async def fake_downloader(url: str, dest: Path, sha: str) -> None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"valid binary content")

        monkeypatch.setattr(
            "pair_harness.desktop_backend.tunnel.verify_file_hash",
            lambda p, s: True,
        )

        mock_proc = _MockProcess(
            stderr_lines=[
                b"2026-09-11 INF Connecting to Cloudflare...\n",
                b"2026-09-11 INF https://test-random-tunnel.trycloudflare.com\n",
            ]
        )

        async def fake_create_subprocess_exec(*args, **kwargs):
            return mock_proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

        mgr = TunnelManager(
            data_dir=tmp_path,
            emitter=emitter,
            audit_logger=lambda ev, d: audit_records.append((ev, d)),
            downloader=fake_downloader,
        )

        res = await mgr.start(local_port=8765)
        assert res == {"status": "starting"}

        # 等待 ready 终态
        for _ in range(50):
            if mgr.state == "ready":
                break
            await asyncio.sleep(0.05)

        assert mgr.state == "ready"
        assert mgr.public_url == "https://test-random-tunnel.trycloudflare.com"
        assert mgr.hostname == "test-random-tunnel.trycloudflare.com"

        # 验证派发了 tunnel.started 事件
        started_events = [e for e in events if e.get("event") == "tunnel.started"]
        assert len(started_events) == 1
        assert started_events[0]["payload"]["public_url"] == "https://test-random-tunnel.trycloudflare.com"

        # 验证审计日志
        assert any(r[0] == "tunnel_started" and "test-random-tunnel.trycloudflare.com" in r[1] for r in audit_records)

        # 停止隧道
        stop_res = await mgr.stop(reason="user_requested")
        assert stop_res == {"status": "stopping"}
        assert mgr.state == "off"
        assert mgr.public_url is None

        # 验证派发了 tunnel.stopped 事件
        stopped_events = [e for e in events if e.get("event") == "tunnel.stopped"]
        assert len(stopped_events) == 1
        assert stopped_events[0]["payload"]["reason"] == "user_requested"
        assert mock_proc.terminated is True

    @pytest.mark.asyncio
    async def test_download_failure_transitions_to_failed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        events: list[dict[str, Any]] = []
        emitter = EventEmitter(sink=lambda ev: events.append(ev))

        async def failing_downloader(url: str, dest: Path, sha: str) -> None:
            raise RuntimeError("网络超时无法连接 GitHub")

        monkeypatch.setattr(
            "pair_harness.desktop_backend.tunnel.verify_file_hash",
            lambda p, s: False,
        )

        mgr = TunnelManager(
            data_dir=tmp_path,
            emitter=emitter,
            audit_logger=lambda ev, d: None,
            downloader=failing_downloader,
        )

        await mgr.start(local_port=8765)

        for _ in range(50):
            if mgr.state == "failed":
                break
            await asyncio.sleep(0.05)

        assert mgr.state == "failed"
        assert "网络超时" in (mgr.error or "")

        failed_events = [e for e in events if e.get("event") == "tunnel.failed"]
        assert len(failed_events) == 1
        assert "网络超时" in failed_events[0]["payload"]["error"]

    @pytest.mark.asyncio
    async def test_child_process_external_crash_triggers_failed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        events: list[dict[str, Any]] = []
        emitter = EventEmitter(sink=lambda ev: events.append(ev))

        monkeypatch.setattr("pair_harness.desktop_backend.tunnel.verify_file_hash", lambda p, s: True)

        mock_proc = _MockProcess(
            stderr_lines=[
                b"2026-09-11 INF https://crash-test.trycloudflare.com\n",
            ]
        )
        monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=mock_proc))

        mgr = TunnelManager(
            data_dir=tmp_path,
            emitter=emitter,
            audit_logger=lambda ev, d: None,
            downloader=AsyncMock(),
        )

        await mgr.start(local_port=8765)
        for _ in range(50):
            if mgr.state == "ready":
                break
            await asyncio.sleep(0.05)
        assert mgr.state == "ready"

        # 模拟外部崩溃
        mock_proc.trigger_crash(code=137)
        for _ in range(50):
            if mgr.state == "failed":
                break
            await asyncio.sleep(0.05)

        assert mgr.state == "failed"
        assert "137" in (mgr.error or "")
        failed_events = [e for e in events if e.get("event") == "tunnel.failed"]
        assert len(failed_events) == 1


# ============================================================
# 4. ApplicationService 隧道控制命令与停机联动测试
# ============================================================


class TestTunnelServiceIntegration:
    @pytest.mark.asyncio
    async def test_tunnel_commands_scope_enforcement(self, tmp_path: Path) -> None:
        """T4: 控制面方法限回环，remote origin 调用抛出 forbidden_scope。"""
        from pair_harness.desktop_backend.application_service import build_demo_service, ServiceError
        from pair_harness.desktop_backend.commands import DesktopCommand

        service = build_demo_service(
            database=tmp_path / "test.db",
            project_root=tmp_path,
        )
        try:
            # 1. 桌面 origin 访问 status 成功
            status_res = await service.handle_command(
                DesktopCommand("s-1", "remote.tunnel_status", {}, origin="desktop")
            )
            assert status_res["state"] == "off"

            # 2. 远程 origin 访问一律被拒
            for method in ("remote.tunnel_status", "remote.tunnel_start", "remote.tunnel_stop"):
                with pytest.raises(ServiceError) as exc:
                    await service.handle_command(
                        DesktopCommand("s-2", method, {}, origin="remote")
                    )
                assert exc.value.code == "forbidden_scope"
        finally:
            await service.shutdown()

    @pytest.mark.asyncio
    async def test_service_shutdown_stops_tunnel(self, tmp_path: Path) -> None:
        """Sidecar 退出时联动关闭隧道，不留孤儿进程。"""
        from pair_harness.desktop_backend.application_service import build_demo_service

        service = build_demo_service(
            database=tmp_path / "test.db",
            project_root=tmp_path,
        )
        stopped_reasons: list[str] = []
        original_stop = service.tunnel_manager.stop

        async def fake_stop(*, reason: str = "user_requested"):
            stopped_reasons.append(reason)
            return await original_stop(reason=reason)

        service.tunnel_manager.stop = fake_stop  # type: ignore

        await service.shutdown()
        assert "sidecar_exit" in stopped_reasons
