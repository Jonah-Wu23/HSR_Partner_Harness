from __future__ import annotations

import argparse
import asyncio
import faulthandler
import logging
import os
import signal
import socket
import sys
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

from pair_harness.desktop_backend.application_service import (
    DesktopApplicationService,
    ServiceError,
    build_configured_service,
)
from pair_harness.desktop_backend.event_fanout import EventFanout
from pair_harness.desktop_backend.router import JsonlWriter, SidecarRouter, run_stdin
from pair_harness.desktop_backend.ws_server import RemoteServe, WSServerMode

logger = logging.getLogger(__name__)

# 环境变量开关的取值；其余取值按启动配置错误处理。
_FLAG_VALUES = {
    "1": True,
    "true": True,
    "yes": True,
    "on": True,
    "0": False,
    "false": False,
    "no": False,
    "off": False,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pair Harness Python desktop sidecar")
    # 模式与局域网直连由 Sidecar 判定：命令行优先，其次是环境变量（含 .env）。
    # 实际采用的模式与来源随 backend.ready 的 demo / mode_source 上报。
    parser.add_argument("--demo", action="store_true", help="使用不联网测试适配器")
    parser.add_argument("--real", action="store_true", help="使用真实模型（账号级配置优先于环境变量）")
    parser.add_argument("--pair", default="phainon_ancient_machine")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument(
        "--serve",
        type=int,
        metavar="PORT",
        help="在该端口开启手机远程 WS 服务器，与 stdin 循环并行",
    )
    parser.add_argument(
        "--lan",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="允许局域网设备直连（绑定 0.0.0.0）；未声明时读 PAIR_HARNESS_LAN，默认只绑定 127.0.0.1",
    )
    return parser


def _detect_lan_ip() -> str | None:
    """探测本机在局域网中的源地址（UDP connect 不发包）；探测不到返回 None。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(0)
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    except OSError:
        return None
    finally:
        sock.close()


def _env_file() -> Path:
    """PAIR_HARNESS_ENV_FILE（桌面端总会设置），未设置时取源码仓库根目录的 .env。"""
    configured = os.getenv("PAIR_HARNESS_ENV_FILE")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / ".env"


def _env_flag(name: str) -> bool | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    value = _FLAG_VALUES.get(raw.lower())
    if value is None:
        raise ServiceError(
            f"{name} 取值无效：{raw}（可用 1/0、true/false、yes/no、on/off）",
            code="invalid_start_flag",
        )
    return value


def _resolve_startup_mode(args: argparse.Namespace) -> tuple[bool, str]:
    """决定启动接线，返回 ``(demo, 来源)``。

    命令行 ``--real`` / ``--demo`` 优先，其次是 PAIR_HARNESS_REAL /
    PAIR_HARNESS_DEMO 环境变量（含 .env）；都没声明时默认真实接线，来源
    ``default_real``，没有 Key 也能启动并进入首次引导。同一来源里两条
    声明指向不同模式时报 ``conflicting_start_mode``。
    """
    if args.real and args.demo:
        raise ServiceError(
            "--real 与 --demo 不能同时声明", code="conflicting_start_mode"
        )
    if args.demo:
        return True, "explicit_demo"
    if args.real:
        return False, "explicit_real"
    real = _env_flag("PAIR_HARNESS_REAL")
    demo = _env_flag("PAIR_HARNESS_DEMO")
    declared = {flag for flag in (None if real is None else not real, demo) if flag is not None}
    if len(declared) > 1:
        raise ServiceError(
            "PAIR_HARNESS_REAL 与 PAIR_HARNESS_DEMO 指向不同模式",
            code="conflicting_start_mode",
        )
    if declared:
        demo_mode = declared.pop()
        return demo_mode, "explicit_demo" if demo_mode else "explicit_real"
    return False, "default_real"


def _resolve_lan(args: argparse.Namespace) -> bool:
    """局域网直连：命令行 --lan / --no-lan 优先，其次 PAIR_HARNESS_LAN，默认关闭。"""
    if args.lan is not None:
        return args.lan
    return bool(_env_flag("PAIR_HARNESS_LAN"))


def _install_sigint_stop(router: SidecarRouter) -> Callable[[], None]:
    """Ctrl+C 与 app.shutdown 同路径：转为有序停机请求，不硬打断事件循环。

    事件循环原生信号处理（Unix）不可用时退回进程级同步 handler（Windows）；
    两者都只触发 router.request_stop，二次 Ctrl+C 仍是幂等的停机请求。
    返回停机后恢复原 SIGINT 处理的回调（进程级 handler 不随事件循环关闭还原）。
    """
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        loop.call_soon_threadsafe(router.request_stop)

    try:
        loop.add_signal_handler(signal.SIGINT, request_stop)
    except NotImplementedError:
        # Windows 事件循环不支持 add_signal_handler。
        previous = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, lambda signum, frame: request_stop())

        def restore_signal() -> None:
            signal.signal(signal.SIGINT, previous)

        return restore_signal

    def remove_loop_handler() -> None:
        loop.remove_signal_handler(signal.SIGINT)

    return remove_loop_handler


async def _start_remote_serve(
    service: DesktopApplicationService,
    router: SidecarRouter,
    fanout: EventFanout,
    *,
    port: int,
    lan: bool,
) -> WSServerMode | None:
    """启动手机远程 WS 服务器并登记接入信息。

    端口被占等环境失败时上报非致命的 serve_start_failed 并返回 None，
    桌面 stdin 路径照常运行。
    """
    pwa_env = os.getenv("PAIR_HARNESS_PWA_DIR", "").strip()
    static_root = Path(pwa_env) if pwa_env else None
    if static_root is not None and not static_root.is_dir():
        # 静态目录配置错误时 / 返回 404，并在日志里写明原因。
        logger.warning(
            "PAIR_HARNESS_PWA_DIR 指向的目录不存在，PWA 静态伺服禁用: %s",
            static_root,
        )
        static_root = None
    # 手机语音事件经 fanout 的 remote-only 通道下发。
    service.attach_event_fanout(fanout)
    ws_server = WSServerMode(
        dispatch=router.dispatch,
        authenticator=service.pairing_service,
        fanout=fanout,
        static_root=static_root,
        port=port,
        host="0.0.0.0" if lan else "127.0.0.1",
        on_disconnect=service.handle_remote_disconnect,
    )
    try:
        await ws_server.start()
    except OSError as exc:
        logger.error("WS 服务器启动失败，远程功能不可用 port=%s: %s", port, exc)
        service.emitter.emit(
            "error.reported",
            {
                "code": "serve_start_failed",
                "message": f"远程服务启动失败（端口 {port}）：{exc}",
                "severity": "error",
                "fatal": False,
                "source": "sidecar",
            },
        )
        return None
    serve = RemoteServe(
        port=port, lan=lan, host=_detect_lan_ip() if lan else "127.0.0.1"
    )
    logger.info(
        "WS 服务器模式已启动 port=%s host=%s lan=%s", port, serve.host, lan
    )
    # 撤销设备时立即断开该设备仍在线的连接。
    service.pairing_service.add_revoke_listener(ws_server.close_connections_for_device)
    service.attach_remote_serve(serve)
    return ws_server


async def _run(args: argparse.Namespace) -> int:
    stream_id = os.getenv("PAIR_HARNESS_STREAM_ID", "local")
    writer = JsonlWriter(sys.stdout)
    service = None

    # --serve 时事件先写 stdout，再扇出到已鉴权的远程连接。
    fanout = EventFanout(writer) if args.serve else None

    def sink(message: dict) -> None:
        if fanout is not None:
            fanout.publish(message)
        else:
            writer.write(message)

    def report_startup_error(code: str, message: str) -> None:
        writer.write(
            {
                "kind": "event",
                "event": "error.reported",
                "stream_id": stream_id,
                "sequence": 0,
                "payload": {
                    "code": code,
                    "message": message,
                    "severity": "fatal",
                    "fatal": True,
                    "source": "sidecar",
                },
            }
        )

    try:
        # .env 不覆盖已存在的进程环境变量；模式与局域网开关可以写在其中。
        load_dotenv(_env_file(), encoding="utf-8-sig")
        demo, mode_source = _resolve_startup_mode(args)
        lan = _resolve_lan(args)
        logger.info("启动接线 demo=%s 来源=%s lan=%s", demo, mode_source, lan)
        service = build_configured_service(
            database=(args.data_dir / "pair_harness.db") if args.data_dir else None,
            project_root=args.project,
            pair_id=args.pair,
            event_sink=sink,
            demo=demo,
            stream_id=stream_id,
        )
    except ServiceError as exc:
        # 退出码 2 表示启动配置错误，Rust 据此停止自动重连。
        report_startup_error(exc.code, str(exc))
        return 2
    except Exception as exc:  # noqa: BLE001 - 启动失败仍输出可识别事件
        # 未预期异常按崩溃退出，Rust 按退避重连。
        logger.exception("sidecar startup failed")
        report_startup_error("startup_error", str(exc))
        return 1

    service.emitter.emit(
        "backend.ready",
        {"pid": os.getpid(), "demo": demo, "mode_source": mode_source},
    )
    await service.start_voice()
    # WS 服务器与 stdin 循环共用同一个 Router。
    router = SidecarRouter(service, writer)
    ws_server: WSServerMode | None = None
    restore_sigint: Callable[[], None] = lambda: None
    try:
        if fanout is not None:
            ws_server = await _start_remote_serve(
                service, router, fanout, port=args.serve, lan=lan
            )
        restore_sigint = _install_sigint_stop(router)
        await run_stdin(service, writer=writer, stdin=sys.stdin, router=router)
    finally:
        restore_sigint()
        if ws_server is not None:
            await ws_server.stop()
        if not service._shutdown:
            await service.shutdown()
    return 0


def _configure_logging() -> None:
    # 默认 WARNING；排查 mobile-tts 等下发链路时可用 PAIR_HARNESS_LOG_LEVEL 调到 INFO/DEBUG。
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, os.getenv("PAIR_HARNESS_LOG_LEVEL", "WARNING").upper(), logging.WARNING),
    )
    # 隧道的下载、哈希校验、子进程与主机名日志固定写入 sidecar.stderr.log。
    logging.getLogger("pair_harness.desktop_backend.tunnel").setLevel(logging.INFO)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    faulthandler.enable(file=sys.stderr, all_threads=True)
    _configure_logging()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
