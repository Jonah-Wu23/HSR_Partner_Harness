"""S4 真机批次的协议级客户端（连接候选真实 WS 通道，使用真实鉴权 token）。

设计约束（来自《V0.3.9-真机验证补充测试.md》§5）：
- 只走候选自身的 ``GET /ws`` 通道与 ``kind=request`` 帧，不直接写数据库、不调用非产品接口。
- 鉴权 token 由 ``remote.pair`` 用桌面端签发的六位配对码换取，不绕过鉴权。
- 每帧（上行/下行）带单调时钟与墙上时间戳，落 ``*-frames.log``；token 只记 SHA256 前缀。

用法（库）：
    async with Harness(url, token, frames_log=..., events_log=...) as h:
        result = await h.call("conversation.create", {"pair_id": "..."})
        await h.wait_event("message.created", timeout=30)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiohttp

MONO = time.monotonic


def _redact(token: str | None) -> str | None:
    if not token:
        return None
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def event_fields(envelope: dict) -> dict:
    """事件字段在 envelope 的 ``payload`` 下（kind/event/stream_id/sequence 在外层）。"""
    payload = envelope.get("payload")
    return payload if isinstance(payload, dict) else {}


def now_iso() -> str:
    return (
        time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        + f".{int((time.time() % 1) * 1000):03d}Z"
    )


class HarnessError(RuntimeError):
    """候选返回的结构化错误（response.ok=False）。"""

    def __init__(self, code: str, message: str, details: Any = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details


class Harness:
    """一条已鉴权的候选 WS 连接。"""

    def __init__(
        self,
        url: str,
        token: str | None = None,
        *,
        frames_log: str | Path | None = None,
        events_log: str | Path | None = None,
        device_name: str = "s4-probe",
    ) -> None:
        self.url = url
        self.token = token
        self.device_name = device_name
        self.events: list[dict] = []
        self._pending: dict[str, asyncio.Future] = {}
        # 先到而尚未被 wait_response 认领的响应；send_async 场景下响应可能
        # 早于等待者注册到达，丢弃会造成假超时（本批次曾因此误判一次）。
        self._unclaimed: dict[str, dict] = {}
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._reader: asyncio.Task | None = None
        self._event_waiters: list[tuple[Callable[[dict], bool], asyncio.Future]] = []
        self._frames_log = Path(frames_log) if frames_log else None
        self._events_log = Path(events_log) if events_log else None
        for path in (self._frames_log, self._events_log):
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")

    # —— 连接生命周期 ——

    async def __aenter__(self) -> "Harness":
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def connect(self) -> None:
        self._session = aiohttp.ClientSession()
        self._ws = await self._session.ws_connect(self.url, heartbeat=30.0)
        self._reader = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):
                pass
            self._reader = None
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        if self._session is not None:
            await self._session.close()
            self._session = None

    # —— 收发 ——

    async def _read_loop(self) -> None:
        assert self._ws is not None
        async for raw in self._ws:
            if raw.type != aiohttp.WSMsgType.TEXT:
                continue
            received = MONO()
            try:
                envelope = json.loads(raw.data)
            except ValueError:
                self._log_frame("down", raw.data, received)
                continue
            self._log_frame("down", envelope, received)
            if envelope.get("kind") == "response":
                request_id = envelope.get("id")
                future = self._pending.pop(request_id, None)
                if future is not None and not future.done():
                    future.set_result(envelope)
                else:
                    self._unclaimed[request_id] = envelope
                    if len(self._unclaimed) > 512:
                        self._unclaimed.pop(next(iter(self._unclaimed)))
                continue
            self.events.append(envelope)
            self._log_event(envelope, received)
            for predicate, waiter in list(self._event_waiters):
                if waiter.done():
                    self._event_waiters.remove((predicate, waiter))
                    continue
                try:
                    matched = predicate(envelope)
                except Exception:  # noqa: BLE001 - 断言函数异常不应吞掉事件流
                    matched = False
                if matched:
                    waiter.set_result(envelope)
                    self._event_waiters.remove((predicate, waiter))

    def _log_frame(self, direction: str, payload: Any, mono: float) -> None:
        if self._frames_log is None:
            return
        record = {
            "ts": now_iso(),
            "mono": round(mono, 6),
            "dir": direction,
        }
        if isinstance(payload, dict) and direction == "up":
            record["method"] = payload.get("method")
            record["id"] = payload.get("id")
            record["params"] = payload.get("params")
            record["auth"] = _redact(self.token)
        else:
            record["frame"] = payload
        with self._frames_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _log_event(self, envelope: dict, mono: float) -> None:
        if self._events_log is None:
            return
        record = {
            "ts": now_iso(),
            "mono": round(mono, 6),
            "event": envelope.get("event"),
            "sequence": envelope.get("sequence"),
            "payload": envelope,
        }
        with self._events_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def call(
        self,
        method: str,
        params: dict | None = None,
        *,
        timeout: float = 30.0,
        token: str | None = None,
    ) -> Any:
        """发一条请求并等待同 id 的响应；返回 result，失败抛 HarnessError。"""
        if self._ws is None:
            raise RuntimeError("连接尚未建立")
        request_id = uuid.uuid4().hex
        effective_token = token if token is not None else self.token
        frame: dict[str, Any] = {
            "kind": "request",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        if effective_token:
            frame["auth"] = {"token": effective_token}
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        sent = MONO()
        self._log_frame("up", frame, sent)
        await self._ws.send_str(json.dumps(frame, ensure_ascii=False))
        try:
            envelope = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise
        if envelope.get("ok"):
            return envelope.get("result")
        error = envelope.get("error") or {}
        raise HarnessError(
            str(error.get("code", "unknown_error")),
            str(error.get("message", "")),
            error.get("details"),
        )

    async def send_async(self, method: str, params: dict | None = None) -> tuple[str, float]:
        """只发不等（用于并发提交测量）；返回请求 id 与发送时刻。"""
        if self._ws is None:
            raise RuntimeError("连接尚未建立")
        request_id = uuid.uuid4().hex
        frame: dict[str, Any] = {
            "kind": "request",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        if self.token:
            frame["auth"] = {"token": self.token}
        sent = MONO()
        self._log_frame("up", frame, sent)
        await self._ws.send_str(json.dumps(frame, ensure_ascii=False))
        return request_id, sent

    async def wait_response(self, request_id: str, *, timeout: float = 30.0) -> Any:
        buffered = self._unclaimed.pop(request_id, None)
        if buffered is not None:
            if buffered.get("ok"):
                return buffered.get("result")
            error = buffered.get("error") or {}
            raise HarnessError(
                str(error.get("code", "unknown_error")),
                str(error.get("message", "")),
                error.get("details"),
            )
        future = self._pending.get(request_id)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self._pending[request_id] = future
        envelope = await asyncio.wait_for(future, timeout=timeout)
        if envelope.get("ok"):
            return envelope.get("result")
        error = envelope.get("error") or {}
        raise HarnessError(
            str(error.get("code", "unknown_error")),
            str(error.get("message", "")),
            error.get("details"),
        )

    async def wait_event(
        self,
        event_name: str,
        *,
        timeout: float = 30.0,
        predicate: Callable[[dict], bool] | None = None,
    ) -> dict:
        def matches(envelope: dict) -> bool:
            if envelope.get("event") != event_name:
                return False
            return predicate(envelope) if predicate else True

        for envelope in self.events:
            if matches(envelope):
                return envelope
        waiter: asyncio.Future = asyncio.get_running_loop().create_future()
        self._event_waiters.append((matches, waiter))
        try:
            return await asyncio.wait_for(waiter, timeout=timeout)
        finally:
            entry = (matches, waiter)
            if entry in self._event_waiters:
                self._event_waiters.remove(entry)

    def events_named(self, event_name: str) -> list[dict]:
        return [item for item in self.events if item.get("event") == event_name]


async def pair(url: str, code: str, device_name: str) -> tuple[str, str]:
    """用配对码换 token（remote.pair 是唯一免鉴权命令）。"""
    session = aiohttp.ClientSession()
    try:
        ws = await session.ws_connect(url, heartbeat=30.0)
        try:
            frame = {
                "kind": "request",
                "id": uuid.uuid4().hex,
                "method": "remote.pair",
                "params": {"code": code, "device_name": device_name},
            }
            await ws.send_str(json.dumps(frame, ensure_ascii=False))
            async for raw in ws:
                if raw.type != aiohttp.WSMsgType.TEXT:
                    continue
                envelope = json.loads(raw.data)
                if envelope.get("kind") != "response":
                    continue
                if envelope.get("ok"):
                    return str(envelope["result"]["token"]), ""
                error = envelope.get("error") or {}
                return "", str(error.get("message") or error.get("code") or "配对失败")
            return "", "连接在配对完成前关闭"
        finally:
            await ws.close()
    finally:
        await session.close()
