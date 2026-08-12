"""无 Qt 的桌面后端入口与 stdin/stdout JSONL 协议。"""

from .application_service import DesktopApplicationService, build_demo_service
from .commands import DESKTOP_COMMANDS, DesktopCommand
from .events import EventEmitter

__all__ = [
    "DESKTOP_COMMANDS",
    "DesktopApplicationService",
    "DesktopCommand",
    "EventEmitter",
    "build_demo_service",
]
