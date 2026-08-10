from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator

from pair_harness.core.contracts import (
    ApprovalDecision,
    EngineEvent,
    EngineEventType,
    EngineSessionRef,
    ProjectRef,
    TaskAmendment,
    TaskRequest,
)
from pair_harness.core.ports import CodingEngine

from .codec import CodexCodec, EventBinding
from .transport import JsonlProcessTransport, TransportClosed


class CodexAppServerEngine(CodingEngine):
    engine_type = "codex-app-server"

    def __init__(self, transport: JsonlProcessTransport) -> None:
        self.transport = transport

    @staticmethod
    def _encode_ref(thread_id: str) -> EngineSessionRef:
        raw = json.dumps({"thread_id": thread_id}, separators=(",", ":")).encode("utf-8")
        return EngineSessionRef(
            engine_type=CodexAppServerEngine.engine_type,
            opaque_ref=base64.urlsafe_b64encode(raw).decode("ascii"),
        )

    @staticmethod
    def _decode_ref(ref: EngineSessionRef) -> str:
        if ref.engine_type != CodexAppServerEngine.engine_type:
            raise ValueError(f"unsupported engine session type: {ref.engine_type}")
        data = json.loads(base64.urlsafe_b64decode(ref.opaque_ref.encode("ascii")))
        return str(data["thread_id"])

    async def open_session(
        self, project: ProjectRef, stored_ref: EngineSessionRef | None = None
    ) -> EngineSessionRef:
        await self.transport.start()
        if stored_ref is not None:
            thread_id = self._decode_ref(stored_ref)
            result = await self.transport.request("thread/resume", {"threadId": thread_id})
            resumed = result.get("thread") or {}
            return self._encode_ref(str(resumed.get("id") or thread_id))
        result = await self.transport.request("thread/start", {"cwd": project.root_path})
        thread = result.get("thread") or {}
        thread_id = thread.get("id")
        if not thread_id:
            raise RuntimeError("thread/start returned no thread id")
        return self._encode_ref(str(thread_id))

    async def run_turn(
        self, session_ref: EngineSessionRef, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        thread_id = self._decode_ref(session_ref)
        result = await self.transport.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": request.instructions}],
            },
        )
        turn = result.get("turn") or {}
        turn_id = str(turn.get("id") or "")
        if not turn_id:
            raise RuntimeError("turn/start returned no turn id")
        binding = EventBinding(
            conversation_id=request.conversation_id,
            task_id=request.task_id,
            engine_turn_id=turn_id,
        )
        codec = CodexCodec()
        try:
            while True:
                notification = await self.transport.next_notification()
                event = codec.map_notification(notification, binding)
                if event is None:
                    continue
                yield event
                if event.type in (EngineEventType.TURN_COMPLETED, EngineEventType.TURN_FAILED):
                    return
        except TransportClosed as exc:
            yield EngineEvent(
                conversation_id=request.conversation_id,
                task_id=request.task_id,
                engine_turn_id=turn_id,
                sequence=10**9,
                type=EngineEventType.TURN_FAILED,
                payload={"error": str(exc)},
            )

    async def cancel_turn(self, session_ref: EngineSessionRef, turn_id: str) -> None:
        await self.transport.request(
            "turn/interrupt",
            {"threadId": self._decode_ref(session_ref), "turnId": turn_id},
        )

    async def amend_turn(
        self,
        session_ref: EngineSessionRef,
        engine_turn_id: str,
        amendment: TaskAmendment,
    ) -> None:
        await self.transport.request(
            "turn/steer",
            {
                "threadId": self._decode_ref(session_ref),
                "expectedTurnId": engine_turn_id,
                "input": [{"type": "text", "text": amendment.instructions}],
            },
        )

    async def resolve_approval(
        self,
        session_ref: EngineSessionRef,
        approval_id: str,
        decision: ApprovalDecision,
    ) -> None:
        await self.transport.request(
            "item/approval/respond",
            {
                "threadId": self._decode_ref(session_ref),
                "approvalId": approval_id,
                "decision": decision,
            },
        )

