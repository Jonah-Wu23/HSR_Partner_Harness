from __future__ import annotations

import json
from typing import Any, Mapping

from .commands import CommandValidationError, DesktopCommand


class ProtocolError(ValueError):
    """一行 JSONL 无法解析或不是请求对象。"""

    def __init__(self, message: str, *, code: str = "invalid_json") -> None:
        super().__init__(message)
        self.code = code


def encode_message(message: Mapping[str, Any]) -> str:
    """编码单行协议消息；调用方负责追加换行并 flush。"""
    try:
        return json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"协议消息不可序列化：{exc}", code="encode_error") from exc


def parse_request(line: str) -> DesktopCommand:
    if not line.strip():
        raise ProtocolError("空行不是协议请求", code="empty_line")
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"JSON 解析失败：{exc.msg}") from exc
    if not isinstance(payload, Mapping):
        raise ProtocolError("协议消息必须是 JSON 对象", code="invalid_message")
    if payload.get("kind") != "request":
        raise ProtocolError("协议消息 kind 必须为 request", code="invalid_kind")
    try:
        return DesktopCommand.from_payload(payload)
    except CommandValidationError as exc:
        raise ProtocolError(str(exc), code=exc.code) from exc


def response_ok(request_id: str, result: Any) -> dict[str, Any]:
    return {"kind": "response", "id": request_id, "ok": True, "result": result}


def response_error(
    request_id: str | None, code: str, message: str
) -> dict[str, Any]:
    return {
        "kind": "response",
        "id": request_id,
        "ok": False,
        "error": {"code": code, "message": message},
    }


def protocol_error(
    code: str, message: str, *, request_id: str | None = None
) -> dict[str, Any]:
    """返回协议层错误；能识别请求 id 时让桌面端按请求失败回收。"""
    payload: dict[str, Any] = {
        "kind": "error",
        "error": {"code": code, "message": message},
    }
    if request_id:
        payload["id"] = request_id
    return payload
