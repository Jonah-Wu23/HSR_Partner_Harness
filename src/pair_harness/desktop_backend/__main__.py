from __future__ import annotations

import argparse
import asyncio
import faulthandler
import logging
import os
import sys
from pathlib import Path

if __package__:
    from .application_service import ServiceError, build_configured_service
    from .event_fanout import EventFanout
    from .router import JsonlWriter, SidecarRouter, run_stdin
    from .ws_server import WSServerMode
else:
    # PyInstaller 以脚本入口运行时没有 package 上下文，改用绝对导入。
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from pair_harness.desktop_backend.application_service import (
        ServiceError,
        build_configured_service,
    )
    from pair_harness.desktop_backend.event_fanout import EventFanout
    from pair_harness.desktop_backend.router import (
        JsonlWriter,
        SidecarRouter,
        run_stdin,
    )
    from pair_harness.desktop_backend.ws_server import WSServerMode

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pair Harness Python desktop sidecar")
    parser.add_argument("--demo", action="store_true", help="使用不联网测试适配器")
    parser.add_argument("--real", action="store_true", help="使用环境变量中的真实模型")
    parser.add_argument("--pair", default="phainon_ancient_machine")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument(
        "--serve",
        type=int,
        metavar="PORT",
        help="同端口开启 WS 服务器模式（手机远程 P0），与 stdin 循环并行",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    stream_id = os.getenv("PAIR_HARNESS_STREAM_ID", "local")
    writer = JsonlWriter(sys.stdout)
    service = None

    # V0.3.3 --serve：事件先写 stdout（唯一权威），再扇出到已鉴权远程连接。
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
        service = build_configured_service(
            database=(args.data_dir / "pair_harness.db") if args.data_dir else None,
            project_root=args.project,
            pair_id=args.pair,
            event_sink=sink,
            demo=not args.real,
            stream_id=stream_id,
        )
    except ServiceError as exc:
        report_startup_error(exc.code, str(exc))
        return 2
    except Exception as exc:  # noqa: BLE001 - 启动失败仍输出可识别事件
        logging.getLogger(__name__).exception("sidecar startup failed")
        report_startup_error("startup_error", str(exc))
        return 2

    service.emitter.emit(
        "backend.ready",
        {"pid": os.getpid(), "demo": not args.real},
    )
    await service.start_voice()
    ws_server: WSServerMode | None = None
    router: SidecarRouter | None = None
    try:
        if args.serve and fanout is not None:
            # WS 服务器模式与 stdin 循环共享同一 service 与 Router；
            # 鉴权由 service.pairing_service 承担（配对码/token/撤销）。
            router = SidecarRouter(service, writer)
            pwa_env = os.getenv("PAIR_HARNESS_PWA_DIR", "").strip()
            static_root = Path(pwa_env) if pwa_env else None
            if static_root is not None and not static_root.is_dir():
                # 静态目录配置错误按无静态资源处理（/ 返回 404），如实暴露。
                logging.getLogger(__name__).warning(
                    "PAIR_HARNESS_PWA_DIR 指向的目录不存在，PWA 静态伺服禁用: %s",
                    static_root,
                )
                static_root = None
            ws_server = WSServerMode(
                dispatch=router.dispatch,
                authenticator=service.pairing_service,
                fanout=fanout,
                static_root=static_root,
                port=args.serve,
            )
            try:
                await ws_server.start()
            except OSError as exc:
                # 端口被占等环境失败：远程能力如实标记不可用，桌面 stdin 路径继续。
                ws_server = None
                router = None
                logging.getLogger(__name__).error(
                    "WS 服务器启动失败，远程功能不可用 port=%s: %s", args.serve, exc
                )
                service.emitter.emit(
                    "error.reported",
                    {
                        "code": "serve_start_failed",
                        "message": f"远程服务启动失败（端口 {args.serve}）：{exc}",
                        "severity": "error",
                        "fatal": False,
                        "source": "sidecar",
                    },
                )
            else:
                logging.getLogger(__name__).info(
                    "WS 服务器模式已启动 port=%s", args.serve
                )
        await run_stdin(service, writer=writer, stdin=sys.stdin, router=router)
    finally:
        if ws_server is not None:
            await ws_server.stop()
        if service is not None and not service._shutdown:
            await service.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    faulthandler.enable(file=sys.stderr, all_threads=True)
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
