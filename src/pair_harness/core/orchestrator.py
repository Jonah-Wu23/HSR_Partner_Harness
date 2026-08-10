from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

from .context import recent_roleplay_context
from .contracts import (
    CharacterResultSummary,
    DialogueRequest,
    EngineEvent,
    EngineEventType,
    EngineSessionRef,
    ExecutionReceipt,
    Message,
    MessageKind,
    MessageSource,
    ProjectRef,
    TaskAmendment,
    TaskAmendmentDraft,
    TaskRequest,
    TaskRequestDraft,
    TaskStatus,
    ToolRun,
)
from .engine_state import GlobalEngineState, TaskLifecycle
from .ports import CodingEngine, DialogueModel, StateStore
from .voice_policy import is_tts_eligible


@dataclass(frozen=True)
class ConversationOutcome:
    messages: tuple[Message, ...]
    engine_events: tuple[EngineEvent, ...] = ()
    tool_runs: tuple[ToolRun, ...] = ()
    task: TaskRequest | None = None
    receipt: ExecutionReceipt | None = None


class ConversationOrchestrator:
    def __init__(
        self,
        *,
        pair_id: str,
        project: ProjectRef,
        dialogue_model: DialogueModel,
        coding_engine: CodingEngine,
        state: GlobalEngineState | None = None,
        store: StateStore | None = None,
    ) -> None:
        self.pair_id = pair_id
        self.project = project
        self.dialogue_model = dialogue_model
        self.coding_engine = coding_engine
        self.state = state or GlobalEngineState()
        self.store = store
        self._history: dict[str, list[Message]] = {}
        self._sessions: dict[str, EngineSessionRef] = {}
        self._active_lifecycle: TaskLifecycle | None = None

    def _message(
        self,
        *,
        conversation_id: str,
        source: MessageSource,
        kind: MessageKind,
        text: str,
        turn_id: str | None = None,
        payload: dict | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            pair_id=self.pair_id,
            turn_id=turn_id,
            source=source,
            kind=kind,
            text=text,
            payload=payload or {},
            tts_eligible=is_tts_eligible(source, kind),
        )
        self._history.setdefault(conversation_id, []).append(message)
        if self.store is not None:
            self.store.save_message(message)
        return message

    async def handle_character_input(
        self, *, conversation_id: str, text: str
    ) -> ConversationOutcome:
        user = self._message(
            conversation_id=conversation_id,
            source=MessageSource.USER,
            kind=MessageKind.USER_TEXT,
            text=text,
        )
        request = DialogueRequest(
            pair_id=self.pair_id,
            conversation_id=conversation_id,
            user_message=user,
            recent_messages=recent_roleplay_context(self._history[conversation_id][:-1]),
        )
        character_turn = None
        async for event in self.dialogue_model.stream_reply(request):
            if event.type == "character.final":
                character_turn = event.turn
        if character_turn is None:
            raise RuntimeError("dialogue model ended without character.final")
        character = self._message(
            conversation_id=conversation_id,
            source=MessageSource.CHARACTER,
            kind=MessageKind.CHARACTER_SPEECH,
            text=character_turn.speech,
        )
        messages = [user, character]

        if isinstance(character_turn.delegation, TaskRequestDraft):
            task = TaskRequest(
                conversation_id=conversation_id,
                origin_message_id=user.message_id,
                instructions=character_turn.delegation.instructions,
                constraints=character_turn.delegation.constraints,
            )
            execution = await self._execute(task)
            messages.extend(execution.messages)
            return ConversationOutcome(
                messages=tuple(messages),
                engine_events=execution.engine_events,
                tool_runs=execution.tool_runs,
                task=task,
                receipt=execution.receipt,
            )

        if isinstance(character_turn.delegation, TaskAmendmentDraft):
            await self._apply_amendment(user.message_id, character_turn.delegation)
        return ConversationOutcome(messages=tuple(messages))

    async def handle_direct_input(
        self, *, conversation_id: str, text: str, constraints: tuple[str, ...] = ()
    ) -> ConversationOutcome:
        user = self._message(
            conversation_id=conversation_id,
            source=MessageSource.USER,
            kind=MessageKind.USER_TEXT,
            text=text,
        )
        task = TaskRequest(
            conversation_id=conversation_id,
            origin_message_id=user.message_id,
            instructions=text,
            constraints=constraints,
        )
        execution = await self._execute(task)
        return ConversationOutcome(
            messages=(user, *execution.messages),
            engine_events=execution.engine_events,
            tool_runs=execution.tool_runs,
            task=task,
            receipt=execution.receipt,
        )

    async def _apply_amendment(
        self, origin_message_id: str, draft: TaskAmendmentDraft
    ) -> None:
        active = self.state.active
        if active is None or active.engine_turn_id is None:
            raise RuntimeError("no running task can accept an amendment")
        if draft.target_task_id is not None and draft.target_task_id != active.task_id:
            raise ValueError("amendment target does not match active task")
        if self._active_lifecycle is None:
            raise RuntimeError("active task lifecycle is missing")
        self._active_lifecycle.transition(TaskStatus.AMENDMENT_PENDING)
        amendment = TaskAmendment(
            target_task_id=active.task_id,
            origin_message_id=origin_message_id,
            revision=draft.revision or 1,
            instructions=draft.instructions,
        )
        session = self._sessions[active.conversation_id]
        await self.coding_engine.amend_turn(session, active.engine_turn_id, amendment)
        self._active_lifecycle.transition(TaskStatus.RUNNING)

    async def _execute(self, task: TaskRequest) -> ConversationOutcome:
        self.state.start(
            project_id=self.project.project_id,
            conversation_id=task.conversation_id,
            task_id=task.task_id,
        )
        lifecycle = TaskLifecycle(task_id=task.task_id)
        lifecycle.transition(TaskStatus.RUNNING)
        self._active_lifecycle = lifecycle
        events: list[EngineEvent] = []
        assistant_text = ""
        tool_runs: dict[str, ToolRun] = {}
        failed = False
        cancelled = False
        errors: list[str] = []
        changed_files: list[str] = []
        checks: list[str] = []
        engine_turn_id = "unavailable"
        try:
            session = self._sessions.get(task.conversation_id)
            session = await self.coding_engine.open_session(self.project, session)
            self._sessions[task.conversation_id] = session
            if self.store is not None:
                self.store.save_engine_session(task.conversation_id, session)

            async for raw_event in self.coding_engine.run_turn(session, task):
                event = raw_event.model_copy(
                    update={
                        "conversation_id": task.conversation_id,
                        "task_id": task.task_id,
                    }
                )
                events.append(event)
                engine_turn_id = event.engine_turn_id
                if self.state.active and self.state.active.engine_turn_id is None:
                    self.state.bind_engine_turn(engine_turn_id)
                if event.type == EngineEventType.ASSISTANT_FINAL:
                    assistant_text = str(event.payload.get("text", ""))
                elif event.type == EngineEventType.FILE_PATCH:
                    path = event.payload.get("path")
                    if path:
                        changed_files.append(str(path))
                elif event.type == EngineEventType.TOOL_FINISHED:
                    status = str(event.payload.get("status", "succeeded"))
                    if status == "failed":
                        failed = True
                        if event.payload.get("error"):
                            errors.append(str(event.payload["error"]))
                    if event.payload.get("check"):
                        checks.append(str(event.payload["check"]))
                    if event.tool_call_id:
                        tool_runs[event.tool_call_id] = ToolRun(
                            tool_call_id=event.tool_call_id,
                            conversation_id=task.conversation_id,
                            task_id=task.task_id,
                            engine_turn_id=engine_turn_id,
                            sequence=event.sequence,
                            status=status,  # type: ignore[arg-type]
                            title=str(event.payload.get("title", "工具")),
                            summary=str(event.payload.get("summary", "")),
                            details=str(event.payload.get("details", "")),
                        )
                elif event.type == EngineEventType.TURN_FAILED:
                    failed = True
                    error = event.payload.get("error")
                    if error:
                        errors.append(str(error))
                elif event.type == EngineEventType.TURN_COMPLETED:
                    cancelled = event.payload.get("status") == "cancelled"

            status = "cancelled" if cancelled else "failed" if failed else "completed"
            lifecycle.transition(TaskStatus(status))
            summary = assistant_text or ("任务执行失败" if failed else "任务执行完成")
            receipt = ExecutionReceipt(
                task_id=task.task_id,
                engine_turn_id=engine_turn_id,
                status=status,  # type: ignore[arg-type]
                summary=summary,
                changed_files=tuple(changed_files),
                checks=tuple(checks),
                errors=tuple(errors),
            )
            messages: list[Message] = []
            if assistant_text:
                messages.append(
                    self._message(
                        conversation_id=task.conversation_id,
                        source=MessageSource.ASSISTANT,
                        kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE,
                        text=assistant_text,
                        turn_id=engine_turn_id,
                    )
                )
            for tool_run in tool_runs.values():
                if self.store is not None:
                    self.store.save_tool_run(tool_run)

            result_summary = CharacterResultSummary(
                task_id=task.task_id,
                status=receipt.status,
                summary=receipt.summary,
                user_visible_changes=tuple(PurePath(path).name for path in changed_files),
                limitations=receipt.errors,
                pending_questions=receipt.pending_questions,
            )
            synthetic = Message(
                conversation_id=task.conversation_id,
                pair_id=self.pair_id,
                source=MessageSource.SYSTEM,
                kind=MessageKind.SYSTEM_STATUS,
                text="execution-result",
            )
            dialogue_request = DialogueRequest(
                pair_id=self.pair_id,
                conversation_id=task.conversation_id,
                user_message=synthetic,
                recent_messages=recent_roleplay_context(
                    self._history.get(task.conversation_id, [])
                ),
                result_summary=result_summary,
            )
            result_turn = None
            async for dialogue_event in self.dialogue_model.stream_reply(dialogue_request):
                if dialogue_event.type == "character.final":
                    result_turn = dialogue_event.turn
            if result_turn is not None:
                messages.append(
                    self._message(
                        conversation_id=task.conversation_id,
                        source=MessageSource.CHARACTER,
                        kind=MessageKind.CHARACTER_SPEECH,
                        text=result_turn.speech,
                        turn_id=engine_turn_id,
                    )
                )
            return ConversationOutcome(
                messages=tuple(messages),
                engine_events=tuple(events),
                tool_runs=tuple(tool_runs.values()),
                task=task,
                receipt=receipt,
            )
        finally:
            self.state.finish(task.task_id)
            self._active_lifecycle = None

