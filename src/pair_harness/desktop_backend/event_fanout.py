from __future__ import annotations

import logging
from typing import Callable

from .router import JsonlWriter

logger = logging.getLogger(__name__)

RemoteEventWriter = Callable[[dict], None]


class _Subscription:
    """可退订的订阅句柄；unsubscribe 幂等。"""

    def __init__(self, fanout: "EventFanout", writer: RemoteEventWriter) -> None:
        self._fanout = fanout
        self._writer = writer
        self._active = True

    @property
    def active(self) -> bool:
        return self._active

    def unsubscribe(self) -> None:
        self._fanout._remove(self)


class EventFanout:
    """事件扇出：stdout 权威 + 全部已订阅远程连接。

    publish 先写 stdout（JsonlWriter，唯一权威写入器），再逐个写已订阅连接。
    单个订阅者写失败只清理该订阅者并记 warning，不影响 stdout 与其他订阅者。
    stdout 的 BrokenPipe 语义完全由 JsonlWriter 承担，本类不拦截不改写。
    """

    def __init__(self, stdout: JsonlWriter) -> None:
        self.stdout = stdout
        self._subscriptions: list[_Subscription] = []

    def subscribe(self, writer: RemoteEventWriter) -> Subscription:
        sub = _Subscription(self, writer)
        self._subscriptions.append(sub)
        return sub

    def _remove(self, sub: Subscription) -> None:
        sub._active = False
        try:
            self._subscriptions.remove(sub)
        except ValueError:
            pass

    def publish(self, envelope: dict) -> None:
        # 先写 stdout（唯一权威）；BrokenPipe 语义由 JsonlWriter 自身承担。
        self.stdout.write(envelope)
        for sub in list(self._subscriptions):
            if not sub._active:
                continue
            try:
                sub._writer(envelope)
            except Exception:  # noqa: BLE001 - 单个订阅者失败隔离在扇出层
                logger.warning("远程订阅者写入事件失败，已退订", exc_info=True)
                self._remove(sub)