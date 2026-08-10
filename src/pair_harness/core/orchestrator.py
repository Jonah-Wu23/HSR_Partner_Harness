from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path, PurePath

from .approval import ApprovalManager, ApprovalRequired, GateOutcome
from .context import recent_roleplay_context
from .contracts import (
    ApprovalDecision,
    ApprovalMode,
    CharacterResultSummary,
    DialogueRequest,
    EngineEvent,
    EngineEventType,
    EngineSessionRef,
    ExecutionReceipt,
    Message,
    MessageKind,
    MessageSource,
    PendingOperation,
    ProjectRef,
    TaskAmendment,
    TaskAmendmentDraft,
    TaskRequest,
    TaskRequestDraft,
    TaskStatus,
    ToolRun,
)
from .engine_state import GlobalEngineState, TaskLifecycle
from .ports import CodingEngine, DialogueModel, Reviewer, StateStore
from .risk_rules import RiskRules, default_risk_rules
from .sandbox import ProjectSandbox, SandboxViolation
from .voice_policy import is_tts_eligible


@dataclass(frozen=True)
class ConversationOutcome:
    messages: tuple[Message, ...]
    engine_events: tuple[EngineEvent, ...] = ()
    tool_runs: tuple[ToolRun, ...] = ()
    task: TaskRequest | None = None
    receipt: ExecutionReceipt | None = None


ApprovalCallback = Callable[[PendingOperation], Awaitable[ApprovalDecision]]


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
        approval_mode: ApprovalMode = ApprovalMode.REQUEST_APPROVAL,
        risk_rules: RiskRules | None = None,
        reviewer: Reviewer | None = None,
        approval_callback: ApprovalCallback | None = None,
    ) -> None:
        self.pair_id = pair_id
        self.project = project
        self.dialogue_model = dialogue_model
        self.coding_engine = coding_engine
        self.state = state or GlobalEngineState()
        self.store = store
        self.approval_mode = approval_mode
        self.risk_rules = risk_rules or default_risk_rules()
        self.reviewer = reviewer
        self.approval_callback = approval_callback
        self._history: dict[str, list[Message]] = {}
        self._sessions: dict[str, EngineSessionRef] = {}
        self._approval_managers: dict[str, ApprovalManager] = {}
        self._active_lifecycle: TaskLifecycle | None = None
        # 执行生命周期回调（O1.4）：busy 状态由任务开始/结束驱动，UI 不做文本猜测
        self.on_execution_started: Callable[[], None] | None = None
        self.on_execution_finished: Callable[[], None] | None = None

    def set_approval_mode(self, mode: ApprovalMode) -> None:
        """切换项目级审批模式（计划 A5：输入区下拉框切换）。"""
        self.approval_mode = mode
        for manager in self._approval_managers.values():
            manager.mode = mode

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
        if self.on_execution_started is not None:
            self.on_execution_started()
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
        sequence = 0
        # 本次执行产生的新消息（含沙箱与审批 system 卡片）从这里开始
        history_start = len(self._history.get(task.conversation_id, []))
        sandbox = ProjectSandbox(Path(self.project.root_path))
        approval = self._approval_managers.setdefault(
            task.conversation_id,
            ApprovalManager(
                mode=self.approval_mode,
                rules=self.risk_rules,
                reviewer=self.reviewer,
            ),
        )
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
                engine_turn_id = event.engine_turn_id
                sequence = max(sequence, event.sequence + 1)
                if self.state.active and self.state.active.engine_turn_id is None:
                    self.state.bind_engine_turn(engine_turn_id)

                if event.type == EngineEventType.TOOL_STARTED:
                    op = self._operation_from_event(event)
                    try:
                        self._check_sandbox(sandbox, op)
                    except SandboxViolation as exc:
                        denied_event = self._deny_tool_event(
                            event, str(exc), sequence
                        )
                        sequence += 1
                        events.append(denied_event)
                        failed = True
                        errors.append(str(exc))
                        self._message(
                            conversation_id=task.conversation_id,
                            source=MessageSource.SYSTEM,
                            kind=MessageKind.SYSTEM_STATUS,
                            text=f"沙箱拦截：{exc}",
                            turn_id=engine_turn_id,
                        )
                        break

                    try:
                        outcome = await approval.gate(
                            op,
                            conversation_id=task.conversation_id,
                            task_id=task.task_id,
                            engine_turn_id=engine_turn_id,
                            sequence=sequence,
                            tool_call_id=event.tool_call_id,
                            # 计划 A3：审查智能体需要近期上下文（最近 3 条）
                            context=self._history.get(task.conversation_id, [])[-3:],
                        )
                        events.extend(outcome.events)
                        sequence += len(outcome.events)
                        # 设计 §4.3：裁决结果以 system 卡片留在消息时间线
                        notice = self._approval_notice(outcome)
                        if notice is not None:
                            self._message(
                                conversation_id=task.conversation_id,
                                source=MessageSource.SYSTEM,
                                kind=MessageKind.APPROVAL,
                                text=notice,
                                turn_id=engine_turn_id,
                            )
                        if outcome.decision == ApprovalDecision.DENY:
                            denied_event = self._deny_tool_event(
                                event, "审批否决", sequence
                            )
                            sequence += 1
                            events.append(denied_event)
                            failed = True
                            errors.append("审批否决")
                            break
                    except ApprovalRequired as req:
                        events.append(req.event)
                        sequence += 1
                        decision = await self._request_approval(req.op)
                        op = approval.resolve(req.approval_id, decision)
                        resolved_event = self._approval_resolved_event(
                            req.event, decision, "user", op
                        )
                        events.append(resolved_event)
                        sequence += 1
                        # 设计 §4.3：用户裁决以 system 卡片留在消息时间线
                        self._message(
                            conversation_id=task.conversation_id,
                            source=MessageSource.SYSTEM,
                            kind=MessageKind.APPROVAL,
                            text=self._decision_text(decision),
                            turn_id=engine_turn_id,
                        )
                        if decision == ApprovalDecision.DENY:
                            denied_event = self._deny_tool_event(
                                event, "用户否决", sequence
                            )
                            sequence += 1
                            events.append(denied_event)
                            failed = True
                            errors.append("用户否决")
                            break

                events.append(event)
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
            for tool_run in tool_runs.values():
                if self.store is not None:
                    self.store.save_tool_run(tool_run)
            if assistant_text:
                self._message(
                    conversation_id=task.conversation_id,
                    source=MessageSource.ASSISTANT,
                    kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE,
                    text=assistant_text,
                    turn_id=engine_turn_id,
                )

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
                self._message(
                    conversation_id=task.conversation_id,
                    source=MessageSource.CHARACTER,
                    kind=MessageKind.CHARACTER_SPEECH,
                    text=result_turn.speech,
                    turn_id=engine_turn_id,
                )
            # 本次执行的全部新消息：审批 system 卡片、助手说明与角色回应
            messages = self._history.get(task.conversation_id, [])[history_start:]
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
            if self.on_execution_finished is not None:
                self.on_execution_finished()

    @staticmethod
    def _operation_from_event(event: EngineEvent) -> PendingOperation:
        payload = event.payload
        tool_kind = payload.get("tool_kind", "shell")
        return PendingOperation(
            tool_kind=tool_kind,
            command=payload.get("command"),
            paths=[str(p) for p in payload.get("paths", [])] or ([payload["path"]] if payload.get("path") else []),
            patch_file_count=payload.get("patch_file_count")
            or len(payload.get("paths", [])),
            summary=payload.get("title", "") or payload.get("summary", "") or "工具操作",
        )

    @staticmethod
    def _check_sandbox(sandbox: ProjectSandbox, op: PendingOperation) -> None:
        for path in op.paths:
            sandbox.resolve_write_path(path)
        if op.command is not None and op.tool_kind == "shell":
            sandbox.enforce_cwd(None)

    async def _request_approval(self, op: PendingOperation) -> ApprovalDecision:
        if self.approval_callback is None:
            return ApprovalDecision.DENY
        return await self.approval_callback(op)

    @staticmethod
    def _deny_tool_event(
        event: EngineEvent, reason: str, sequence: int
    ) -> EngineEvent:
        return EngineEvent(
            conversation_id=event.conversation_id,
            task_id=event.task_id,
            engine_turn_id=event.engine_turn_id,
            sequence=sequence,
            type=EngineEventType.TOOL_FINISHED,
            tool_call_id=event.tool_call_id,
            payload={
                # 计划 A3：沙箱越界与审批否决的工具操作以 denied 状态收尾，
                # 与 ToolRun.status 的 "denied" 枚举值对齐；任务本身仍标记失败。
                "status": "denied",
                "title": event.payload.get("title", "工具"),
                "summary": reason,
                "details": reason,
                "error": reason,
            },
        )

    @staticmethod
    def _approval_resolved_event(
        requested: EngineEvent,
        decision: ApprovalDecision,
        actor: str,
        op: PendingOperation,
    ) -> EngineEvent:
        return EngineEvent(
            conversation_id=requested.conversation_id,
            task_id=requested.task_id,
            engine_turn_id=requested.engine_turn_id,
            sequence=requested.sequence + 1,
            type=EngineEventType.APPROVAL_RESOLVED,
            tool_call_id=requested.tool_call_id,
            payload={
                "approval_id": requested.payload.get("approval_id"),
                "decision": decision.value,
                "actor": actor,
                "reason": op.summary,
                "suggestion": "",
            },
        )

    @staticmethod
    def _decision_text(decision: ApprovalDecision) -> str:
        """用户裁决的 system 卡片文案。"""
        return {
            ApprovalDecision.ALLOW: "审批结果：允许",
            ApprovalDecision.ALLOW_FOR_CONVERSATION: "审批结果：本对话内允许",
            ApprovalDecision.DENY: "审批结果：否决",
        }[decision]

    @staticmethod
    def _approval_notice(outcome: GateOutcome) -> str | None:
        """从审批门控结果生成时间线 system 卡片文案。

        - 完全允许运行与审查模式低风险直接放行不产生提示（返回 None）；
        - 审查智能体的裁决记录理由与调整建议；
        - 请求批准模式的“本对话内允许”缓存命中也留一条提示。
        """
        if outcome.decision == ApprovalDecision.ALLOW and not outcome.events:
            return None
        resolved = [e for e in outcome.events if e.type == "approval.resolved"]
        if resolved and resolved[-1].payload.get("actor") == "reviewer":
            payload = resolved[-1].payload
            text = "审查结果：" + (
                "允许" if payload.get("decision") == "allow" else "否决"
            )
            if payload.get("reason"):
                text += f"（{payload['reason']}）"
            if payload.get("suggestion"):
                text += f"；调整建议：{payload['suggestion']}"
            return text
        return ConversationOrchestrator._decision_text(outcome.decision)
