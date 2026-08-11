from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

if __package__:
    from .application_service import ServiceError, build_configured_service
    from .router import JsonlWriter, run_stdin
else:
    # PyInstaller 以脚本入口运行时没有 package 上下文，改用绝对导入。
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from pair_harness.desktop_backend.application_service import (
        ServiceError,
        build_configured_service,
    )
    from pair_harness.desktop_backend.router import JsonlWriter, run_stdin


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pair Harness Python desktop sidecar")
    parser.add_argument("--demo", action="store_true", help="使用不联网测试适配器")
    parser.add_argument("--real", action="store_true", help="使用环境变量中的真实模型")
    parser.add_argument("--pair", default="phainon_ancient_machine")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--data-dir", type=Path)
    return parser


async def _run(args: argparse.Namespace) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    writer = JsonlWriter(sys.stdout)
    service = None

    def sink(message: dict) -> None:
        writer.write(message)

    try:
        service = build_configured_service(
            database=(args.data_dir / "pair_harness.db") if args.data_dir else None,
            project_root=args.project,
            pair_id=args.pair,
            event_sink=sink,
            demo=not args.real,
        )
    except ServiceError as exc:
        writer.write(
            {
                "kind": "event",
                "event": "error.reported",
                "sequence": 0,
                "payload": {"code": exc.code, "message": str(exc)},
            }
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - 启动失败仍输出可识别事件
        logging.getLogger(__name__).exception("sidecar startup failed")
        writer.write(
            {
                "kind": "event",
                "event": "error.reported",
                "sequence": 0,
                "payload": {"code": "startup_error", "message": str(exc)},
            }
        )
        return 1

    service.emitter.emit(
        "backend.ready",
        {"pid": os.getpid(), "demo": not args.real},
    )
    await service.start_voice()
    try:
        await run_stdin(service, stdin=sys.stdin, stdout=sys.stdout)
    finally:
        if service is not None and not service._shutdown:
            await service.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
