from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


DESKTOP_COMMANDS = frozenset(
    {
        "app.bootstrap",
        "app.shutdown",
        "project.create",
        "project.select",
        "project.update_settings",
        "conversation.create",
        "conversation.select",
        "conversation.rename",
        "conversation.archive",
        "chat.submit",
        "task.cancel",
        "approval.resolve",
        "voice.vad_set",
        "voice.ptt_start",
        "voice.ptt_stop",
        "voice.tts_stop",
    }
)


class CommandValidationError(ValueError):
    """前端命令结构不符合 Sidecar 协议。"""

    def __init__(self, message: str, *, code: str = "invalid_command") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DesktopCommand:
    request_id: str
    method: str
    params: Mapping[str, Any]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "DesktopCommand":
        request_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params", {})
        if not isinstance(request_id, str) or not request_id:
            raise CommandValidationError("request.id 必须是非空字符串")
        if not isinstance(method, str) or not method:
            raise CommandValidationError("request.method 必须是非空字符串")
        if method not in DESKTOP_COMMANDS:
            raise CommandValidationError(
                f"未知桌面命令：{method}", code="unknown_method"
            )
        if not isinstance(params, Mapping):
            raise CommandValidationError("request.params 必须是对象")
        return cls(request_id=request_id, method=method, params=params)
