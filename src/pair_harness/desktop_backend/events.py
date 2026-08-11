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
    """Sidecar 事件出口；所有事件在此处分配单调递增序号。"""

    def __init__(self, sink: EventSink) -> None:
        self._sink = sink
        self._sequence = 0

    @property
    def next_sequence(self) -> int:
        return self._sequence

    def emit(self, event: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        envelope = {
            "kind": "event",
            "event": event,
            "sequence": self._sequence,
            "payload": to_jsonable(payload or {}),
        }
        self._sequence += 1
        self._sink(envelope)
        return envelope
