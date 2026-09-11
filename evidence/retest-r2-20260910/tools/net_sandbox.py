"""B-01 进程级网络沙盒（V0.3.9 复测计划 §4.1）。

把「断网」下沉到本机一个可控的 HTTP CONNECT 代理：候选（EXE → Sidecar 的
httpx 客户端，trust_env 默认开启）经 ``HTTPS_PROXY`` 把出站流量引到这里，
再按需要切换故障形态。全程不需要管理员权限，且可一键还原。

形态语义（对应补充测试要求的四种错误注入）：

    forward  正常 CONNECT 隧道，出站可达（基线）
    reject   停止监听：新连接被立即拒绝（ECONNREFUSED），连接阶段失败
    cut      已建立的隧道被 abort（RST），传输阶段中断
    hang     接受 CONNECT 但不建立上游、也不回应：请求悬挂至客户端超时

用法：

    python net_sandbox.py --listen 8767 --upstream api.deepseek.com:443 \
        --control 8768 --log <sandbox.log>

控制通道（本地 TCP 行协议，只接受 127.0.0.1 回环连接）：

    SET forward | SET hang | SET reject | CUT | PING | STATS

每条命令回一行 ``OK <形态> connections=<n> tunnels=<n>``，便于测试脚本留证。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

MONO = time.monotonic


class Sandbox:
    def __init__(self, listen_port: int, upstream_host: str, upstream_port: int,
                 control_port: int, log_path: Path) -> None:
        self.listen_port = listen_port
        self.upstream = (upstream_host, upstream_port)
        self.control_port = control_port
        self.log_path = log_path
        self.mode = "forward"
        self.cut_delay = 1.0  # cut_soon 的兜底延迟（秒）
        self.cut_after_bytes = 256  # cut_soon 的字节阈值（客户端已收到的响应字节）
        self.connections = 0
        self.tunnels = 0
        self._server: asyncio.AbstractServer | None = None
        self._control: asyncio.AbstractServer | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self._tasks: set[asyncio.Task] = set()
        self._cut_tasks: set[asyncio.Task] = set()

    # —— 日志 ——

    def record(self, event: str, **fields: object) -> None:
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
                 + f".{int((time.time() % 1) * 1000):03d}Z",
                 "mono": round(MONO(), 6), "event": event, "mode": self.mode, **fields}
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # —— 监听生命周期 ——

    async def start(self) -> None:
        await self.start_proxy()
        self._control = await asyncio.start_server(
            self._handle_control, "127.0.0.1", self.control_port)
        self.record("sandbox_started", listen=self.listen_port,
                    upstream=f"{self.upstream[0]}:{self.upstream[1]}",
                    control=self.control_port)

    async def start_proxy(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(
            self._handle_proxy, "127.0.0.1", self.listen_port)
        self.record("listen_started", listen=self.listen_port)

    async def stop_proxy(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        self.record("listen_stopped", listen=self.listen_port)

    async def set_mode(self, mode: str) -> None:
        if mode == "reject":
            await self.stop_proxy()
        else:
            await self.start_proxy()
        self.mode = mode
        self.record("mode_changed", next=mode)

    async def _arm_auto_cut(self, writer: asyncio.StreamWriter,
                            upstream_writer: asyncio.StreamWriter) -> None:
        """cut_soon 的兜底：隧道建立后延迟 cut_delay 秒仍未触发字节阈值时也切断。"""
        await asyncio.sleep(self.cut_delay)
        for target in (writer, upstream_writer):
            try:
                transport = target.transport
                if transport is not None:
                    transport.abort()
            except Exception:  # noqa: BLE001 - 收尾失败不应中断控制通道
                pass
        self.record("auto_cut_timeout_fired", after_seconds=self.cut_delay)

    async def cut(self) -> int:
        """abort 全部已建立连接（两端），模拟传输中断。"""
        count = 0
        for writer in list(self._writers):
            count += 1
            try:
                transport = writer.transport
                if transport is not None:
                    transport.abort()
            except Exception:  # noqa: BLE001 - 收尾失败不应中断控制通道
                pass
        self._writers.clear()
        self.record("tunnels_cut", count=count)
        return count

    # —— 代理 ——

    async def _handle_proxy(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        self._writers.add(writer)
        peer = writer.get_extra_info("peername")
        mode = self.mode
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=30.0)
        except asyncio.TimeoutError:
            self.record("client_request_timeout", peer=str(peer))
            writer.close()
            return
        request_line = line.decode("latin-1").strip()
        self.record("client_request", peer=str(peer), request=request_line)

        if not request_line.upper().startswith("CONNECT"):
            # 不走隧道的普通 HTTP 请求：沙盒只服务 CONNECT，其余如实拒绝。
            self.record("non_connect_request", request=request_line)
            writer.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            await writer.drain()
            writer.close()
            return

        if mode == "hang":
            # 不回应、不连上游：客户端一直等到自己的超时。
            self.record("hang_accepted", request=request_line)
            try:
                await asyncio.sleep(600)
            except asyncio.CancelledError:
                pass
            return

        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(*self.upstream)
        except OSError as exc:
            self.record("upstream_connect_failed", error=str(exc))
            writer.write(f"HTTP/1.1 502 Bad Gateway\r\nX-Sandbox-Error: {exc}\r\n\r\n"
                         .encode("latin-1"))
            await writer.drain()
            writer.close()
            return

        self.tunnels += 1
        self._writers.add(upstream_writer)
        # 把 CONNECT 请求头余下的行读完（客户端在 CONNECT 后通常不再发头）
        try:
            while True:
                header = await asyncio.wait_for(reader.readline(), timeout=5.0)
                if header in (b"\r\n", b"\n", b""):
                    break
        except asyncio.TimeoutError:
            pass
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        self.record("tunnel_established", request=request_line)
        if mode == "cut_soon":
            self._cut_tasks.add(asyncio.create_task(
                self._arm_auto_cut(writer, upstream_writer)))

        async def pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter,
                       direction: str) -> None:
            transferred = 0
            try:
                while True:
                    data = await src.read(65536)
                    if not data:
                        break
                    dst.write(data)
                    await dst.drain()
                    if direction == "down":
                        transferred += len(data)
                        # cut_soon：客户端已收到若干字节响应后立即切断——
                        # 这是真正的「响应传输中断」，不依赖外部脚本卡时间。
                        if mode == "cut_soon" and transferred >= self.cut_after_bytes:
                            self.record("auto_cut_fired", after_bytes=transferred)
                            for target in (writer, upstream_writer):
                                transport = target.transport
                                if transport is not None:
                                    transport.abort()
                            # 只切一次：随后自动回到 forward，使后续（重试）请求可达。
                            self.mode = "forward"
                            self.record("mode_changed", next="forward",
                                        reason="cut_soon_single_shot")
                            return
            except (OSError, asyncio.CancelledError):
                pass
            finally:
                try:
                    dst.close()
                except OSError:
                    pass

        task = asyncio.create_task(pump(reader, upstream_writer, "up"))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task = asyncio.create_task(pump(upstream_reader, writer, "down"))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # —— 控制通道 ——

    async def _handle_control(self, reader: asyncio.StreamReader,
                              writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        if peer and peer[0] != "127.0.0.1":
            writer.close()
            return
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                command = line.decode("utf-8", "replace").strip()
                reply = await self._dispatch(command)
                writer.write((reply + "\n").encode("utf-8"))
                await writer.drain()
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            try:
                writer.close()
            except OSError:
                pass

    async def _dispatch(self, command: str) -> str:
        parts = command.split()
        if not parts:
            return "ERR empty"
        head = parts[0].upper()
        if head == "SET" and len(parts) >= 2 and parts[1].lower() in {
            "forward", "hang", "reject", "cut_soon"
        }:
            if len(parts) == 3 and parts[1].lower() == "cut_soon":
                try:
                    self.cut_after_bytes = int(parts[2])
                except ValueError:
                    return f"ERR bad_bytes {parts[2]!r}"
            await self.set_mode(parts[1].lower())
        elif head == "CUT":
            await self.cut()
        elif head == "PING":
            pass
        elif head == "STATS":
            pass
        else:
            self.record("control_unknown", command=command)
            return f"ERR unknown_command {command!r}"
        return (f"OK {self.mode} connections={self.connections} "
                f"tunnels={self.tunnels}")

    async def serve_forever(self) -> None:
        await self.start()
        await asyncio.Event().wait()


async def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", type=int, default=8767)
    parser.add_argument("--upstream", default="api.deepseek.com:443")
    parser.add_argument("--control", type=int, default=8768)
    parser.add_argument("--log", required=True)
    parser.add_argument("--cut-delay", type=float, default=1.0,
                        help="cut_soon 的兜底延迟（秒）；响应先到 256 字节则立即切断")
    args = parser.parse_args()
    host, _, port = args.upstream.partition(":")
    sandbox = Sandbox(args.listen, host, int(port or 443), args.control,
                      Path(args.log))
    sandbox.cut_delay = args.cut_delay
    await sandbox.serve_forever()


if __name__ == "__main__":
    asyncio.run(_main())
