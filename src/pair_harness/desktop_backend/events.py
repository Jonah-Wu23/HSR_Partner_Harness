from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

from pydantic import BaseModel


def to_jsonable(value: Any) -> Any:
    """把核心模型转换成协议可传输的 JSON 值。"""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [to_jsonable(item) for item in value]
    return value


EventSink = Callable[[dict[str, Any]], None]


class EventEmitter:
    """Sidecar 事件出口；所有事件在此处分配代次内单调递增序号并携带 stream_id。"""

    def __init__(self, sink: EventSink, *, stream_id: str = "local") -> None:
        self._sink = sink
        self._sequence = 0
        self._stream_id = stream_id

    @property
    def next_sequence(self) -> int:
        return self._sequence

    def allocate_sequence(self) -> int:
        """消费并返回下一个序号（V0.3.5）。

        供不经 ``emit`` 的事件通道（手机语音 remote-only 音频分片）使用，
        保证全站事件序号单调不重不漏：所有下行事件都必须经由本方法或
        :meth:`emit` 消费序号，禁止直接读取 ``next_sequence``。
        """
        sequence = self._sequence
        self._sequence += 1
        return sequence

    @property
    def stream_id(self) -> str:
        return self._stream_id

    def emit(self, event: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        envelope = {
            "kind": "event",
            "event": event,
            "stream_id": self._stream_id,
            "sequence": self._sequence,
            "payload": to_jsonable(payload or {}),
        }
        self._sequence += 1
        self._sink(envelope)
        return envelope
