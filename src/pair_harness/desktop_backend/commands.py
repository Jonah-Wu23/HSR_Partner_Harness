from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


DESKTOP_COMMANDS = frozenset(
    {
        "app.bootstrap",
        "app.shutdown",
        "app.reconnect",
        "project.create",
        "project.select",
        "project.update_settings",
        "project.archive",
        "conversation.create",
        "conversation.select",
        "conversation.open",
        "conversation.rename",
        "conversation.archive",
        "conversation.set_mode",
        "chat.submit",
        "queue.edit",
        "queue.withdraw",
        "queue.prioritize",
        "task.cancel",
        "approval.resolve",
        "voice.vad_set",
        "voice.ptt_start",
        "voice.ptt_stop",
        "voice.tts_stop",
        "voice.tts_play",
        "voice.tts_skip",
        "voice.preview",
        "voice.provision",
        "account.list",
        "account.register",
        "account.login",
        "account.logout",
        "account.switch",
        "account.update_profile",
        "account.change_password",
        "account.onboarding_complete",
        "config.get",
        "config.set",
        "config.test_connection",
        "codex.oauth_start",
        "codex.oauth_status",
        "codex.logout",
        "codex.api_login",
        "codex.oauth_start",
        "codex.oauth_status",
        "codex.logout",
        "codex.api_login",
        "card.list",
        "card.get",
        "card.create_draft",
        "card.update",
        "card.duplicate",
        "card.archive",
        "card.delete",
        "card.select_active",
        "card.peek_import_json",
        "card.import_json",
        "card.export_json",
        "card.publish",
        "card.set_avatar",
        "card.remove_avatar",
        "voice.card_bind_reference",
        "voice.card_create",
        "voice.card_unbind",
        "voice.card_preview",
        "voice.mobile_ptt_start",
        "voice.mobile_audio_chunk",
        "voice.mobile_ptt_stop",
        "voice.mobile_tts_stop",
        "remote.issue_code",
        "remote.pair",
        "remote.list_devices",
        "remote.revoke",
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
    # V0.3.5：命令来源由传输层注入（stdin=desktop、WS=remote），不信任
    # 前端参数；审批仲裁用 resolved_by 如实区分双端应答。默认 desktop。
    origin: str = "desktop"

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
