from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    # router 依赖 application_service，运行时导入会形成循环。
    from .router import JsonlWriter

RemoteEventWriter = Callable[[dict], None]


class _Subscription:
    """可退订的订阅句柄；unsubscribe 幂等。"""

    def __init__(self, fanout: EventFanout, writer: RemoteEventWriter) -> None:
        self._fanout = fanout
        self.writer = writer

    def unsubscribe(self) -> None:
        self._fanout._remove(self)


class EventFanout:
    """事件扇出：先写 stdout，再写全部已订阅的远程连接。

    stdout 的 BrokenPipe 语义由 JsonlWriter 承担。远程订阅者的写回调只是入队，
    连接断开由连接自己的写任务处理。
    """

    def __init__(self, stdout: JsonlWriter) -> None:
        self.stdout = stdout
        self._subscriptions: list[_Subscription] = []

    def subscribe(self, writer: RemoteEventWriter) -> _Subscription:
        sub = _Subscription(self, writer)
        self._subscriptions.append(sub)
        return sub

    def _remove(self, sub: _Subscription) -> None:
        if sub in self._subscriptions:
            self._subscriptions.remove(sub)

    def publish(self, envelope: dict, *, remote_only: bool = False) -> None:
        """扇出一条事件；``remote_only`` 的事件（手机语音分片等）不写 stdout。"""
        if not remote_only:
            self.stdout.write(envelope)
        for sub in list(self._subscriptions):
            sub.writer(envelope)

    def has_remote_subscribers(self) -> bool:
        """是否存在已订阅的远程连接（手机 TTS 只在有在线端时合成）。"""
        return bool(self._subscriptions)