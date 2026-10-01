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
        "project.archive",
        "conversation.create",
        # WS 心跳：探测传输活性，并为已鉴权的控制租约持有者续租。
        "ping",
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
        "card.list",
        "card.get",
        "card.create_draft",
        "card.update",
        "card.duplicate",
        "card.archive",
        "card.unarchive",
        "card.delete",
        "card.select_active",
        "card.peek_import",
        "card.import_json",
        "card.export_json",
        "card.import_png",
        "card.export_png",
        "card.publish",
        "card.set_avatar",
        "card.remove_avatar",
        "power.get_status",
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
        "remote.claim_control",
        "remote.release_control",
        "remote.control_status",
        "remote.tunnel_start",
        "remote.tunnel_stop",
        "remote.tunnel_status",
        "summary.regenerate",
        "summary.get",
        "memory.create",
        "memory.list",
        "memory.update",
        "memory.delete",
        "metrics.query",
        "diagnostics.prompt_assembly",
    }
)


class CommandValidationError(ValueError):
    """前端命令结构不符合 Sidecar 协议。"""

    def __init__(self, message: str, *, code: str = "invalid_command") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CommandContext:
    """传输层注入的调用方身份，handler 只从这里读取，不信任 params 里的同名字段。"""

    origin: str = "desktop"
    connection_key: str | None = None
    device_key: str | None = None
    device_name: str | None = None


@dataclass(frozen=True)
class DesktopCommand:
    request_id: str
    method: str
    params: Mapping[str, Any]
    # 以下字段由传输层注入（stdin 为 desktop，WS 为 remote），不取自请求参数。
    origin: str = "desktop"
    # WS 连接唯一 key；手机语音会话与控制租约绑定它，stdin 路径为 None。
    connection_key: str | None = None
    # 已鉴权令牌的 SHA-256 摘要，作为设备身份，重连不变。
    remote_device_key: str | None = None
    # 鉴权时登记的设备名，用于回合指标呈现来源设备。
    remote_device_name: str | None = None

    @property
    def context(self) -> CommandContext:
        return CommandContext(
            origin=self.origin,
            connection_key=self.connection_key,
            device_key=self.remote_device_key,
            device_name=self.remote_device_name,
        )

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
