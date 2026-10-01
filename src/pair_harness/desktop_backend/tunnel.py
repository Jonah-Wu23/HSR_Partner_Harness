"""Cloudflare Quick Tunnel 隧道管理模块（D1）。

托管官方 cloudflared 临时隧道子进程生命周期：按需下载二进制到用户数据目录
并校验官方哈希、解析分配的 trycloudflare.com 主机名、维护五态（off / downloading /
starting / ready / failed）并派发 tunnel.* 事件与审计记录。
Sidecar 退出时联动有序关闭，不留孤儿进程。

支持平台仅 Windows 与 Linux。官方 darwin 资产是 .tgz 压缩包，需要解压流程，
产品未承诺 macOS 分发，未经真实验证不提供该路径：darwin 上探测直接报
unsupported_platform，响亮失败。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import platform
import socket
import sys
import urllib.request
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import aiohttp

from .events import EventEmitter

logger = logging.getLogger(__name__)

# 官方发布的 cloudflared 版本与 SHA256 校验和（留证来源：https://github.com/cloudflare/cloudflared/releases/tag/2026.9.0）
CLOUDFLARED_VERSION = "2026.9.0"

CLOUDFLARED_ASSETS: dict[str, dict[str, str]] = {
    "win32-x64": {
        "filename": "cloudflared-windows-amd64.exe",
        "url": f"https://github.com/cloudflare/cloudflared/releases/download/{CLOUDFLARED_VERSION}/cloudflared-windows-amd64.exe",
        "sha256": "547057326266f0e1c7d50d102dbd22ff283d740c055bd61e94f10e2c606f89af",
    },
    "win32-x86": {
        "filename": "cloudflared-windows-386.exe",
        "url": f"https://github.com/cloudflare/cloudflared/releases/download/{CLOUDFLARED_VERSION}/cloudflared-windows-386.exe",
        "sha256": "e11ee417d5bab1918c3e257c2b1f9541d6febd545091ecf87e249c3cfb7880b0",
    },
    "linux-x64": {
        "filename": "cloudflared-linux-amd64",
        "url": f"https://github.com/cloudflare/cloudflared/releases/download/{CLOUDFLARED_VERSION}/cloudflared-linux-amd64",
        "sha256": "53b7a7a5420d188758d24341294acb0d1bca54296548ac05e38811a694ac6134",
    },
    "linux-arm64": {
        "filename": "cloudflared-linux-arm64",
        "url": f"https://github.com/cloudflare/cloudflared/releases/download/{CLOUDFLARED_VERSION}/cloudflared-linux-arm64",
        "sha256": "98aca3173f73248fad6180fc75dade2d186a6e54fa807e088108cb4345de8efe",
    },
}

# 等待 cloudflared 分配 Quick Tunnel 主机名的上限（秒）。
HOSTNAME_TIMEOUT_SECONDS = 30.0
# metrics 服务尚未监听时轮询 /quicktunnel 的间隔（秒）。
METRICS_POLL_INTERVAL_SECONDS = 0.25


class TunnelError(RuntimeError):
    """隧道运行错误。"""

    def __init__(self, message: str, *, code: str = "tunnel_error") -> None:
        super().__init__(message)
        self.code = code


def detect_platform_asset() -> tuple[str, str, str]:
    """探测当前操作系统的 cloudflared 架构资产，返回 (filename, url, sha256)。"""
    plat = sys.platform
    arch = platform.machine().lower()
    if plat == "win32":
        key = "win32-arm64" if "arm" in arch else ("win32-x86" if "32" in arch or "86" in arch and "64" not in arch else "win32-x64")
        if key not in CLOUDFLARED_ASSETS:
            key = "win32-x64"
    elif plat == "darwin":
        raise TunnelError(
            "macOS 平台暂不受支持：官方 darwin 资产为 .tgz 压缩包，"
            "本产品未承诺 macOS 分发，未提供解压与校验路径",
            code="unsupported_platform",
        )
    elif plat.startswith("linux"):
        key = "linux-arm64" if "arm" in arch or "aarch64" in arch else "linux-x64"
    else:
        raise TunnelError(f"不支持的操作系统平台: {plat}", code="unsupported_platform")

    asset = CLOUDFLARED_ASSETS.get(key)
    if not asset:
        raise TunnelError(f"未找到适配当前架构的 cloudflared: {key}", code="unsupported_architecture")
    return asset["filename"], asset["url"], asset["sha256"]


def verify_file_hash(path: Path, expected_sha256: str) -> bool:
    """校验本地文件的 SHA256 哈希。"""
    if not path.is_file():
        return False
    hasher = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
    except OSError:
        return False
    return hasher.hexdigest().lower() == expected_sha256.lower()


async def default_download_file(url: str, dest_path: Path, expected_sha256: str) -> None:
    """按块下载文件至 .part 临时文件并严格校验哈希，成功后原子重命名。"""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest_path.with_suffix(".part")
    if part_path.exists():
        part_path.unlink(missing_ok=True)

    hasher = hashlib.sha256()
    loop = asyncio.get_running_loop()

    def _sync_download() -> None:
        req = urllib.request.Request(
            url, headers={"User-Agent": f"PairHarness-Sidecar/{CLOUDFLARED_VERSION}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60.0) as resp, open(part_path, "wb") as f:
                while chunk := resp.read(65536):
                    f.write(chunk)
                    hasher.update(chunk)
        except Exception:
            if part_path.exists():
                part_path.unlink(missing_ok=True)
            raise

    await loop.run_in_executor(None, _sync_download)

    actual_sha256 = hasher.hexdigest().lower()
    if actual_sha256 != expected_sha256.lower():
        if part_path.exists():
            part_path.unlink(missing_ok=True)
        raise TunnelError(
            f"哈希校验失败：期望 {expected_sha256}，实际 {actual_sha256}",
            code="hash_mismatch",
        )

    if dest_path.exists():
        dest_path.unlink(missing_ok=True)
    part_path.rename(dest_path)
    if sys.platform != "win32":
        try:
            os.chmod(dest_path, 0o755)
        except OSError:
            pass


Downloader = Callable[[str, Path, str], Awaitable[None]]


def _free_local_port() -> int:
    """取一个当前空闲的回环端口，交给 cloudflared 的 metrics 服务监听。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _read_quicktunnel_hostname(metrics_address: str) -> str:
    """从 cloudflared metrics 服务的 /quicktunnel 读取分配到的主机名。

    cloudflared 先向 trycloudflare 申请到主机名，再启动 metrics 服务，
    因此连接被拒表示仍在申请中，继续轮询；其余 HTTP 错误如实抛出。
    """
    url = f"http://{metrics_address}/quicktunnel"
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    payload = await resp.json(content_type=None)
            except aiohttp.ClientConnectionError:
                await asyncio.sleep(METRICS_POLL_INTERVAL_SECONDS)
                continue
            hostname = payload.get("hostname") if isinstance(payload, dict) else None
            if not isinstance(hostname, str) or not hostname:
                raise TunnelError(
                    f"cloudflared /quicktunnel 未返回主机名：{payload!r}",
                    code="hostname_missing",
                )
            return hostname


async def _drain_output(stream: asyncio.StreamReader | None) -> None:
    """持续读走 cloudflared 输出并写入日志：管道写满会让 cloudflared 阻塞。"""
    if stream is None:
        return
    while True:
        line = await stream.readline()
        if not line:
            return
        logger.info("cloudflared: %s", line.decode("utf-8", errors="replace").rstrip())


class TunnelManager:
    """Cloudflare Quick Tunnel 子进程管理器。

    维护五态：'off' / 'downloading' / 'starting' / 'ready' / 'failed'。
    """

    def __init__(
        self,
        *,
        data_dir: Path,
        emitter: EventEmitter,
        audit_logger: Callable[[str, str], None],
        downloader: Downloader | None = None,
        custom_binary: Path | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.emitter = emitter
        self.audit_logger = audit_logger
        self.downloader = downloader or default_download_file
        self.custom_binary = custom_binary

        self.state: str = "off"
        self.public_url: str | None = None
        self.hostname: str | None = None
        self.error: str | None = None

        self._process: asyncio.subprocess.Process | None = None
        self._monitor_task: asyncio.Task | None = None
        self._start_lock = asyncio.Lock()

    @property
    def binary_path(self) -> Path:
        if self.custom_binary is not None:
            return self.custom_binary
        bin_dir = self.data_dir / "bin"
        exe_name = "cloudflared.exe" if sys.platform == "win32" else "cloudflared"
        return bin_dir / exe_name

    def status(self) -> dict[str, Any]:
        """返回隧道当前状态。未就绪时 public_url/hostname 为 null，failed 时带 error。"""
        return {
            "state": self.state,
            "public_url": self.public_url if self.state == "ready" else None,
            "hostname": self.hostname if self.state == "ready" else None,
            "error": self.error if self.state == "failed" else None,
        }

    async def start(self, local_port: int) -> dict[str, Any]:
        """启动隧道。立即返回 {"status": "starting"}，后续状态通过事件广播。"""
        async with self._start_lock:
            if self.state in ("starting", "downloading"):
                return {"status": "starting"}
            if self.state == "ready" and self._process is not None and self._process.returncode is None:
                return {"status": "starting"}

            self.state = "starting"
            self.public_url = None
            self.hostname = None
            self.error = None

            # 启动异步生命周期协程
            self._monitor_task = asyncio.create_task(self._run_tunnel_flow(local_port))
            return {"status": "starting"}

    async def stop(self, *, reason: str = "user_requested") -> dict[str, Any]:
        """关闭隧道。立即返回 {"status": "stopping"}，若此前在运行则发出 tunnel.stopped 事件。"""
        was_running = (self.state != "off") or (self._process is not None)

        if self._monitor_task is not None and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except (asyncio.CancelledError, Exception):
                pass
            self._monitor_task = None

        if self._process is not None:
            proc = self._process
            self._process = None
            try:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            except Exception:  # noqa: BLE001
                pass

        self.state = "off"
        self.public_url = None
        self.hostname = None
        self.error = None

        if was_running:
            self.emitter.emit("tunnel.stopped", {"reason": reason})
            self.audit_logger("tunnel_stopped", f"reason={reason}")
        return {"status": "stopping"}

    async def _ensure_binary(self) -> Path:
        """确保 cloudflared 二进制存在且 SHA256 校验通过，缺失或损坏时按需下载。"""
        bin_path = self.binary_path
        filename, url, expected_sha256 = detect_platform_asset()

        if verify_file_hash(bin_path, expected_sha256):
            return bin_path

        # 需要下载
        self.state = "downloading"
        logger.info("开始下载 cloudflared: %s -> %s", url, bin_path)
        try:
            await self.downloader(url, bin_path, expected_sha256)
        except Exception as exc:
            raise TunnelError(f"cloudflared 下载或校验失败: {exc}", code="download_failed") from exc

        if not verify_file_hash(bin_path, expected_sha256):
            bin_path.unlink(missing_ok=True)
            raise TunnelError("下载后的 cloudflared 哈希校验失败", code="hash_mismatch")

        return bin_path

    async def _run_tunnel_flow(self, local_port: int) -> None:
        """执行隧道完整生命周期：下载校验 -> 启动子进程 -> 解析主机名 -> 监视退出。"""
        try:
            bin_path = await self._ensure_binary()
        except Exception as exc:
            err_msg = str(exc)
            logger.error("隧道准备失败: %s", err_msg, exc_info=True)
            self._fail(err_msg)
            return

        self.state = "starting"
        # 主机名从 metrics 服务的 /quicktunnel 读取；日志里的 URL（包括
        # 申请失败时的 https://api.trycloudflare.com/tunnel）一律不参与判定。
        metrics_address = f"127.0.0.1:{_free_local_port()}"
        cmd = [
            str(bin_path),
            "tunnel",
            "--url",
            f"http://127.0.0.1:{local_port}",
            "--metrics",
            metrics_address,
            "--no-autoupdate",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._process = proc
            logger.info(
                "cloudflared 子进程已启动 pid=%s local_port=%s", proc.pid, local_port
            )
        except Exception as exc:
            err_msg = f"启动 cloudflared 进程失败: {exc}"
            logger.error(err_msg, exc_info=True)
            self._fail(err_msg)
            return

        # 输出排空任务一直运行到进程退出：cloudflared 持续写日志，管道写满
        # 会令它阻塞在写入上，隧道假死且外部强杀无法及时触发 tunnel.failed。
        drain_tasks = [
            asyncio.create_task(_drain_output(proc.stderr)),
            asyncio.create_task(_drain_output(proc.stdout)),
        ]
        exit_task = asyncio.create_task(proc.wait())
        hostname_task = asyncio.create_task(_read_quicktunnel_hostname(metrics_address))
        try:
            try:
                done, _ = await asyncio.wait(
                    [hostname_task, exit_task],
                    timeout=HOSTNAME_TIMEOUT_SECONDS,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except asyncio.CancelledError:
                proc.kill()
                raise
            finally:
                hostname_task.cancel()
                await asyncio.gather(hostname_task, return_exceptions=True)

            if exit_task in done:
                self._fail(f"cloudflared 进程在就绪前退出 (退出码 {proc.returncode})")
                return
            if hostname_task not in done:
                self._fail(
                    f"cloudflared 主机名解析超时 ({int(HOSTNAME_TIMEOUT_SECONDS)}s)"
                )
                return
            if hostname_task.exception() is not None:
                self._fail(f"读取 cloudflared 隧道主机名失败: {hostname_task.exception()}")
                return

            hostname = hostname_task.result()
            self.hostname = hostname
            self.public_url = f"https://{hostname}"
            self.state = "ready"
            self.error = None
            logger.info("Quick Tunnel 主机名解析就绪 hostname=%s", hostname)
            self.emitter.emit(
                "tunnel.started",
                {"public_url": self.public_url, "hostname": self.hostname},
            )
            self.audit_logger("tunnel_started", f"hostname={hostname}")

            # 进程退出（含外部强杀）由 proc.wait() 检出。
            return_code = await exit_task
            if self.state in ("ready", "starting"):
                self._fail(f"隧道进程已被外部终止 (退出码 {return_code})")
        finally:
            exit_task.cancel()
            for task in drain_tasks:
                task.cancel()
            await asyncio.gather(exit_task, *drain_tasks, return_exceptions=True)

    def _fail(self, error: str) -> None:
        """进入 failed 终态并派发 tunnel.failed 事件。"""
        self.state = "failed"
        self.public_url = None
        self.hostname = None
        self.error = error
        if self._process is not None:
            try:
                self._process.kill()
            except Exception:
                pass
            self._process = None
        self.emitter.emit("tunnel.failed", {"error": error})
