from __future__ import annotations

from collections.abc import AsyncIterator

from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.core.contracts import CharacterTurn, DialogueEvent, DialogueRequest
from pair_harness.core.ports import DialogueModel


class FixedDialogueModel(DialogueModel):
    def __init__(self, *turns: CharacterTurn) -> None:
        self.turns = list(turns)
        self.requests: list[DialogueRequest] = []

    async def stream_reply(self, request: DialogueRequest) -> AsyncIterator[DialogueEvent]:
        self.requests.append(request)
        turn = self.turns.pop(0)
        yield DialogueEvent(type="speech.delta", delta=turn.speech)
        yield DialogueEvent(type="character.final", turn=turn)


class RecordingCodingEngine(ScriptedCodingEngine):
    pass

