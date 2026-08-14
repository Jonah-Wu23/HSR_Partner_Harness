from __future__ import annotations

import asyncio
import time as time_module
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePath
from typing import Literal, cast

from .approval import ApprovalManager, ApprovalRequired, GateOutcome
from .context import recent_roleplay_context
from .contracts import (
    ApprovalDecision,
    ApprovalMode,
    CharacterProgressSummary,
    CharacterResultSummary,
    DialogueEvent,
    DialogueRequest,
    EngineEvent,
    EngineEventType,
    EngineSessionRef,
    ExecutionReceipt,
    Message,
    MessageKind,
    MessageOrigin,
    MessageSource,
    MessageStatus,
    MessageTarget,
    PendingOperation,
    ProjectRef,
    ProjectRuntimeContext,
    TaskAmendment,
    TaskAmendmentDraft,
    TaskRequest,
    TaskRequestDraft,
    TaskStatus,
    ToolRun,
)
from .engine_state import BusyTurnError, GlobalEngineState, TaskLifecycle
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


@dataclass
class _TaskProgress:
    """O3.3：执行期间的活动任务进度（事件驱动更新、按需生成摘要）。

    只保存中性描述（当前步骤标签、已完成步骤数），不保存命令、路径与
    输出原文；节流策略：进度状态只在工具事件到达时更新，摘要文本只在
    角色请求（执行期间的聊天轮）到达时生成——不逐事件注入。
    """

    current_step: str = "任务准备中"
    completed_steps: int = 0
    total_steps: int | None = None


ApprovalCallback = Callable[
    [PendingOperation, str, str], Awaitable[ApprovalDecision]
]
"""审批回调签名：操作、approval_id、真实理由（风险标签或“需要用户审批”）。

O1.7：approval_id 由编排器生成并贯通到 UI 队列，裁决按 id 对应，
不再依赖 FIFO 顺序巧合。
"""

# O4.3：状态字面量类型别名——ToolRun.status 与 ExecutionReceipt.status
# 的枚举值在事件循环里以 str 流动，出口处 cast 收敛，消除 type: ignore
ToolRunStatus = Literal["running", "succeeded", "failed", "denied"]
ReceiptStatus = Literal["completed", "failed", "cancelled"]


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
        assistant_instructions: str = "",
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
        self.assistant_instructions = assistant_instructions
        self._history: dict[str, list[Message]] = {}
        self._sessions: dict[str, EngineSessionRef] = {}
        self._approval_managers: dict[str, ApprovalManager] = {}
        # O3.3：活动任务的执行进度（_execute 期间填充，结束时清理）
        self._progress: dict[str, _TaskProgress] = {}
        self._active_lifecycle: TaskLifecycle | None = None
        # V0.2：按会话持久化的对话模式（chat/collaboration）。模式由
        # 后端权威保存；设置类命令不得回推覆盖（与推理档位/审批方式/
        # 发送对象互不覆盖的独立字段）。聊天模式是角色能力边界：不能委派。
        self._conversation_modes: dict[str, Literal["chat", "collaboration"]] = {}
        # O2.5：每会话入口锁——聊天轮（用户消息+角色台词）在锁内整体落库，
        # 轮内顺序固定为用户→角色且不与其他轮交错；任务执行（_execute）
        # 刻意不在锁内，执行期间到达的聊天轮与执行产生的系统/助手消息按
        # 落库先后交错，运行中直接输入/修改仍可并发 steer 活动 turn。
        self._conversation_locks: dict[str, asyncio.Lock] = {}
        # 执行生命周期回调（O1.4）：busy 状态由任务开始/结束驱动，UI 不做文本猜测
        self.on_execution_started: Callable[[], None] | None = None
        self.on_execution_finished: Callable[[], None] | None = None
        # O2.1：流式事件通道——消息与引擎事件产生时即推送，UI 增量渲染；
        # ConversationOutcome 保留为最终汇总（事后回放）。
        # 推送顺序约定（设计 §3.2）：角色接受委派的台词先于执行事件到达界面。
        self.on_message: Callable[[Message], None] | None = None
        self.on_engine_event: Callable[[EngineEvent], None] | None = None
        # V0.2：消息生命周期状态变更回调（message.status_changed）。
        # 与 on_message 并存：on_message 管创建，本回调管状态推进。
        self.on_message_status_changed: Callable[[Message], None] | None = None
        # V0.2：对话增量事件通道（角色思考/正文 delta），由桌面桥转发为
        # message.delta 的 reasoning/speech 通道。
        self.on_dialogue_event: Callable[[str, Message, DialogueEvent], None] | None = None
        # V0.2：审查智能体生命周期事件（review.started/completed/failed）。
        # 只有真正调用审查智能体时才触发，UI 据此显示审查状态（问题 14）。
        self.on_review_event: Callable[[str, dict], None] | None = None
        # B2.6：消息监听器列表（VoiceRuntime 挂 TTS 用），在消息持久化后逐个调用
        self._message_listeners: list[Callable[[Message], None]] = []

    def set_approval_mode(
        self, mode: ApprovalMode, *, conversation_id: str | None = None
    ) -> None:
        """切换项目级审批模式（计划 A5：输入区下拉框切换）。"""
        self.approval_mode = mode
        if conversation_id is None:
            for manager in self._approval_managers.values():
                manager.mode = mode
        elif conversation_id in self._approval_managers:
            self._approval_managers[conversation_id].mode = mode

    def select_context(
        self,
        *,
        project: ProjectRef,
        pair_id: str,
        conversation_id: str,
        approval_mode: ApprovalMode,
        assistant_instructions: str,
        conversation_mode: Literal["chat", "collaboration"] = "chat",
    ) -> None:
        """切换当前项目与聊天，保留其他聊天已恢复的历史和会话引用。"""
        self.project = project
        self.pair_id = pair_id
        self.assistant_instructions = assistant_instructions
        self.set_approval_mode(approval_mode, conversation_id=conversation_id)
        self.set_conversation_mode(conversation_id, conversation_mode)

    def set_conversation_mode(
        self, conversation_id: str, mode: Literal["chat", "collaboration"]
    ) -> None:
        """V0.2：保存当前会话的对话模式（后端权威）。

        模式是与推理档位/审批方式/发送对象互不覆盖的独立字段；
        设置类命令不得回推覆盖它。聊天模式下角色不能形成委派。
        """
        self._conversation_modes[conversation_id] = mode

    def conversation_mode(self, conversation_id: str) -> Literal["chat", "collaboration"]:
        """当前会话的持久化模式。

        桌面应用总是经 ``select_context`` 从 ``conversations.last_mode``
        显式设置；未显式设置的独立使用（CLI/语音/单测）默认协作，
        保持委派行为与历史一致。聊天模式的边界只在应用明确持久化时生效。
        """
        return self._conversation_modes.get(conversation_id, "collaboration")

    def _build_runtime_context(self, conversation_id: str) -> ProjectRuntimeContext:
        """V0.2：构造项目运行上下文（名称/目录/时间/时区/模式）。

        项目创建、选择、路径修复与账号切换时重建；注入角色与助手系统
        上下文，不显示成普通聊天消息。
        """
        mode = self.conversation_mode(conversation_id)
        now = datetime.now().astimezone()
        tz_abbr = time_module.tzname[0] if time_module.tzname else now.tzname() or ""
        return ProjectRuntimeContext(
            project_name=self.project.name,
            project_abs_dir=self.project.root_path,
            local_time=now.strftime("%Y-%m-%d %H:%M:%S"),
            timezone=tz_abbr or str(now.utcoffset() or ""),
            conversation_mode=mode,
        )

    def mark_message_failed(
        self, conversation_id: str, message_id: str, reason: str
    ) -> Message | None:
        """V0.2：把一条已落库消息标记为失败（保留文字，可重试）。

        即时回显原则：处理失败后文字仍在，前端可按真实 id 对账并重试。
        同时更新内存历史与 SQLite，并推送 ``message.status_changed``。
        """
        return self._set_message_status(
            conversation_id,
            message_id,
            MessageStatus.FAILED,
            reason=reason,
        )

    def mark_message_cancelled(
        self, conversation_id: str, message_id: str, reason: str = "用户取消"
    ) -> Message | None:
        """把尚未完成的用户消息标记为取消，保留原文供前端对账。"""
        return self._set_message_status(
            conversation_id,
            message_id,
            MessageStatus.CANCELLED,
            reason=reason,
        )

    def mark_processing_delegations_failed(
        self, conversation_id: str, reason: str
    ) -> None:
        """让委派卡与真实失败回合保持一致。"""
        for message in tuple(self._history.get(conversation_id, [])):
            if (
                message.origin == MessageOrigin.CHARACTER_DELEGATION
                and message.status == MessageStatus.PROCESSING
            ):
                self._set_message_status(
                    conversation_id,
                    message.message_id,
                    MessageStatus.FAILED,
                    reason=reason,
                )

    def mark_processing_delegations_cancelled(self, conversation_id: str) -> None:
        """让取消中的委派卡落到 cancelled，而不是伪装成 completed。"""
        for message in tuple(self._history.get(conversation_id, [])):
            if (
                message.origin == MessageOrigin.CHARACTER_DELEGATION
                and message.status == MessageStatus.PROCESSING
            ):
                self._set_message_status(
                    conversation_id,
                    message.message_id,
                    MessageStatus.CANCELLED,
                    reason="用户取消",
                )

    def _set_message_status(
        self,
        conversation_id: str,
        message_id: str,
        status: MessageStatus,
        *,
        reason: str | None = None,
    ) -> Message | None:
        history = self._history.get(conversation_id, [])
        for index, message in enumerate(history):
            if message.message_id != message_id:
                continue
            payload = dict(message.payload)
            if reason:
                payload[
                    "cancelled_reason" if status == MessageStatus.CANCELLED else "error"
                ] = reason
            updated = message.model_copy(update={"status": status, "payload": payload})
            history[index] = updated
            if self.store is not None:
                self.store.save_message(updated)
            if self.on_message_status_changed is not None:
                self.on_message_status_changed(updated)
            return updated
        return None

    def report_system_status(self, conversation_id: str, text: str) -> Message:
        """把运行时错误作为可见且可恢复的系统消息写入当前聊天。"""
        return self._message(
            conversation_id=conversation_id,
            source=MessageSource.SYSTEM,
            kind=MessageKind.SYSTEM_STATUS,
            text=text,
        )

    def add_message_listener(self, callback: Callable[[Message], None]) -> None:
        """注册消息监听器：消息持久化完成后同步调用（供 VoiceRuntime 挂 TTS）。

        与 ``on_message`` 单回调并存互不影响：UI 桥走 on_message，
        语音运行时走监听器列表。
        """
        if callback not in self._message_listeners:
            self._message_listeners.append(callback)

    def _engine_policy(
        self, approval_mode: ApprovalMode | None = None
    ) -> dict[str, str | None]:
        """B1：应用层审批模式 → app-server thread/start 策略映射（设计 §14.6）。

        - 请求批准 / 帮我审核：``untrusted`` + ``read-only`` 沙箱。真实联调
          确认 workspace-write 下工作区写操作不发起 requestApproval（B1 联调
          记录），改用 read-only 让一切写操作执行前挂起，由 ApprovalManager
          裁决后经 resolve_approval 回复——三种审批模式真实差异化拦截；
        - 完全允许运行：``never`` + ``workspace-write``（引擎不发起审批请求，
          写操作直接执行，工具事件照常持久化）；
        - ``approvalsReviewer`` 固定 ``"user"``——应用层审查智能体负责裁决，
          不启用原生 auto_review（§14.6 备注，B1 联调可评估切换）。
        """
        mode = approval_mode or self.approval_mode
        approval_policy = (
            "never"
            if mode == ApprovalMode.FULL_AUTO
            else "untrusted"
        )
        sandbox = (
            "workspace-write"
            if mode == ApprovalMode.FULL_AUTO
            else "read-only"
        )
        return {
            "approvalPolicy": approval_policy,
            "sandbox": sandbox,
            "approvalsReviewer": "user",
        }

    def restore_conversation(self, snapshot: dict) -> None:
        """O2.2：打开旧聊天时回填消息历史与会话引用。

        接受 :meth:`StateStore.load_conversation` 的返回值：
        - ``messages`` 回填 ``_history``，恢复后 ``recent_messages`` 不再为空
          （角色不失忆）；
        - ``engine_session`` 回填 ``_sessions``，后续 ``open_session`` 收到
          已保存的 ``stored_ref``，可走 thread/resume 而非 thread/start。
        """
        conversation_id = snapshot["conversation"].conversation_id
        self._history[conversation_id] = list(snapshot.get("messages", ()))
        session_ref = snapshot.get("engine_session")
        if (
            session_ref is not None
            and session_ref.engine_type == self.coding_engine.engine_type
        ):
            self._sessions[conversation_id] = session_ref
        else:
            self._sessions.pop(conversation_id, None)

    def close_conversation(self, conversation_id: str) -> None:
        """O4.2：聊天结束/切换钩子——清理该会话的审批缓存。

        “本对话内允许”缓存的生命周期是单次聊天：聊天关闭或切换后
        必须失效。这里取出会话的 :class:`ApprovalManager`，先清空
        ``_session_allow`` 缓存，再移除常驻引用（下次使用该会话时
        新建管理器，缓存与挂起请求均为空）。运行中的任务不受影响：
        ``_execute`` 在开始时已持有本地 manager 引用，收尾照常。
        未打开过的会话调用是无害空操作。
        """
        manager = self._approval_managers.pop(conversation_id, None)
        if manager is not None:
            manager.clear_session_cache()

    def _conversation_lock(self, conversation_id: str) -> asyncio.Lock:
        """O2.5：获取会话级入口锁（首次访问时惰性创建）。

        不同会话的入口互不阻塞；同一会话的聊天轮按到达顺序串行。
        """
        lock = self._conversation_locks.get(conversation_id)
        if lock is None:
            lock = asyncio.Lock()
            self._conversation_locks[conversation_id] = lock
        return lock

    def _message(
        self,
        *,
        conversation_id: str,
        source: MessageSource,
        kind: MessageKind,
        text: str,
        engine_turn_id: str | None = None,
        payload: dict | None = None,
        message_id: str | None = None,
        pair_id: str | None = None,
        target: MessageTarget | None = None,
        origin: MessageOrigin | None = None,
        delegation_id: str | None = None,
        status: MessageStatus = MessageStatus.DONE,
    ) -> Message:
        message_values = {
            "conversation_id": conversation_id,
            "pair_id": pair_id or self.pair_id,
            "engine_turn_id": engine_turn_id,
            "source": source,
            "kind": kind,
            "text": text,
            "payload": payload or {},
            "tts_eligible": is_tts_eligible(source, kind),
            "target": target or self._default_target(source),
            "origin": origin or self._default_origin(source),
            "delegation_id": delegation_id,
            "status": status,
        }
        if message_id is not None:
            message_values["message_id"] = message_id
        message = Message(**message_values)
        self._history.setdefault(conversation_id, []).append(message)
        if self.store is not None:
            self.store.save_message(message)
        # B2.6：消息持久化后逐个调用监听器（VoiceRuntime TTS 入口）
        for listener in self._message_listeners:
            listener(message)
        # O2.1：消息产生即推送，UI 增量渲染不等整轮任务结束
        if self.on_message is not None:
            self.on_message(message)
        return message

    def _recent_user_messages(self, conversation_id: str) -> list[Message]:
        """返回当前聊天中用户最后发送的三条消息。"""
        return [
            message
            for message in self._history.get(conversation_id, [])
            if message.source == MessageSource.USER
        ][-3:]

    @staticmethod
    def _default_target(source: MessageSource) -> MessageTarget | None:
        """按来源推导默认消息归属：角色→角色区，助手/工具→工作台。"""
        if source == MessageSource.CHARACTER:
            return MessageTarget.CHARACTER
        if source in (MessageSource.ASSISTANT, MessageSource.TOOL):
            return MessageTarget.ASSISTANT
        return None

    @staticmethod
    def _default_origin(source: MessageSource) -> MessageOrigin:
        if source == MessageSource.SYSTEM:
            return MessageOrigin.SYSTEM
        return MessageOrigin.USER

    def _forward_dialogue_event(
        self,
        conversation_id: str,
        user_message: Message,
        event: DialogueEvent,
    ) -> None:
        """V0.2：把角色对话增量事件转发给桌面桥。

        聊天模式也照常转发干净 delta（思考与正文流式显示与模式无关）；
        委派字段等结构信息仍等 character.final 解析。
        """
        if self.on_dialogue_event is not None:
            self.on_dialogue_event(conversation_id, user_message, event)

    def _forward_review_event(self, event: str, payload: dict) -> None:
        """V0.2：把 ApprovalManager 的审查生命周期事件转发给桌面桥。"""
        if self.on_review_event is not None:
            self.on_review_event(event, payload)

    async def handle_character_input(
        self, *, conversation_id: str, text: str
    ) -> ConversationOutcome:
        """完整角色回合入口（CLI/语音/测试使用）：快速接受 + 后台处理。"""
        user = await self.submit_user_message(
            conversation_id=conversation_id, text=text, target="character"
        )
        return await self.process_character_turn(
            conversation_id=conversation_id, user_message=user
        )

    async def submit_user_message(
        self, *, conversation_id: str, text: str, target: str
    ) -> Message:
        """V0.2 快速接受（问题 1）：同步落库用户消息并立即返回真实 id。

        只负责保存与发出 ``message.created``；回合处理由调用方随后启动
        （桌面桥在后台任务中运行，不再让 ``chat.submit`` 等待整轮完成）。
        断线或重启后可从快照恢复，处理失败后文字仍在且可重试。
        """
        target_value = MessageTarget(target)
        async with self._conversation_lock(conversation_id):
            return self._message(
                conversation_id=conversation_id,
                source=MessageSource.USER,
                kind=MessageKind.USER_TEXT,
                text=text,
                target=target_value,
                origin=MessageOrigin.USER,
            )

    async def process_character_turn(
        self, *, conversation_id: str, user_message: Message
    ) -> ConversationOutcome:
        """V0.2：在后台运行角色回合（用户消息已落库）。

        角色台词在会话锁内串行产生；委派处理（_execute/修改路由）在锁外
        进行。聊天模式下角色输出的 delegation 一律不执行（问题 4），
        后端做最终裁决并注入能力边界。
        """
        async with self._conversation_lock(conversation_id):
            # O3.3：执行期间（_execute 未结束）注入压缩进度摘要；
            # 任务结束后 _progress 已清理，聊天轮回到纯角色对话
            progress = self._progress.get(conversation_id)
            progress_summary = None
            if progress is not None:
                progress_summary = CharacterProgressSummary(
                    current_step=progress.current_step,
                    completed_steps=progress.completed_steps,
                    total_steps=progress.total_steps,
                )
            request = DialogueRequest(
                pair_id=self.pair_id,
                conversation_id=conversation_id,
                user_message=user_message,
                recent_messages=recent_roleplay_context(self._history[conversation_id][:-1]),
                progress_summary=progress_summary,
                runtime_context=self._build_runtime_context(conversation_id),
            )
            character_turn = None
            async for event in self.dialogue_model.stream_reply(request):
                # V0.2：增量事件先转发（思考/正文 delta），UI 流式显示
                self._forward_dialogue_event(conversation_id, user_message, event)
                if event.type == "character.final":
                    character_turn = event.turn
            if character_turn is None:
                raise RuntimeError("dialogue model ended without character.final")
            character = self._message(
                conversation_id=conversation_id,
                source=MessageSource.CHARACTER,
                kind=MessageKind.CHARACTER_SPEECH,
                text=character_turn.speech,
                # 桌面端的思考流和正文流共用这个 id；最终消息会覆盖临时流，
                # 时间线里只保留一个角色气泡。
                message_id=f"speech:{conversation_id}:{user_message.message_id}",
                payload=(
                    {"reasoning": character_turn.reasoning}
                    if character_turn.reasoning
                    else None
                ),
            )
            messages = [user_message, character]

        # V0.2 能力边界（问题 4）：聊天模式一律不执行委派。后端最终裁决，
        # 不依赖按钮禁用或角色提示词。
        if self.conversation_mode(conversation_id) == "chat" and (
            isinstance(character_turn.delegation, TaskRequestDraft)
            or isinstance(character_turn.delegation, TaskAmendmentDraft)
        ):
            notice = self._message(
                conversation_id=conversation_id,
                source=MessageSource.SYSTEM,
                kind=MessageKind.SYSTEM_STATUS,
                text="当前是聊天模式，角色不能读取或操作项目。切换协作模式后再让它处理项目任务。",
            )
            return ConversationOutcome(messages=tuple((*messages, notice)))

        if isinstance(character_turn.delegation, TaskRequestDraft):
            task = TaskRequest(
                conversation_id=conversation_id,
                origin_message_id=user_message.message_id,
                instructions=character_turn.delegation.instructions,
                constraints=character_turn.delegation.constraints,
            )
            try:
                execution = await self._execute(
                    task,
                    delegation_id=task.task_id,
                    origin=MessageOrigin.CHARACTER_DELEGATION,
                )
            except BusyTurnError as exc:
                # O2.4：任务运行中角色再委派新任务——冲突转为用户可见的
                # 系统提示，不再静默失败；用户直接指令不受影响（走修改路由）。
                notice = self._message(
                    conversation_id=conversation_id,
                    source=MessageSource.SYSTEM,
                    kind=MessageKind.SYSTEM_STATUS,
                    text=f"任务仍在执行，本次委派暂未受理：{exc}",
                )
                return ConversationOutcome(messages=(user_message, character, notice))
            messages.extend(execution.messages)
            return ConversationOutcome(
                messages=tuple(messages),
                engine_events=execution.engine_events,
                tool_runs=execution.tool_runs,
                task=task,
                receipt=execution.receipt,
            )

        if isinstance(character_turn.delegation, TaskAmendmentDraft):
            try:
                await self._apply_amendment(user_message.message_id, character_turn.delegation)
            except (RuntimeError, ValueError) as exc:
                # O2.4：角色建议的修改无法路由（无活动任务、生命周期已终态等）
                # 时同样转为可见系统提示，不静默
                notice = self._message(
                    conversation_id=conversation_id,
                    source=MessageSource.SYSTEM,
                    kind=MessageKind.SYSTEM_STATUS,
                    text=f"修改未能应用：{exc}",
                )
                return ConversationOutcome(messages=(user_message, character, notice))
        return ConversationOutcome(messages=tuple(messages))

    async def handle_direct_input(
        self, *, conversation_id: str, text: str, constraints: tuple[str, ...] = ()
    ) -> ConversationOutcome:
        """完整直发助手回合入口（CLI/语音/测试使用）：快速接受 + 后台处理。"""
        user = await self.submit_user_message(
            conversation_id=conversation_id, text=text, target="assistant"
        )
        return await self.process_direct_input(
            conversation_id=conversation_id, user_message=user, constraints=constraints
        )

    async def process_direct_input(
        self,
        *,
        conversation_id: str,
        user_message: Message,
        constraints: tuple[str, ...] = (),
    ) -> ConversationOutcome:
        """V0.2：后台处理直发助手的用户消息。

        用户消息已由快速接受落库；这里按当前状态路由：无活动任务时新建
        任务执行；活动任务在其他聊天时给出可见提示；活动任务在本聊天时
        归一为 TaskAmendment（M2 起默认排队，只有明确「立即插入」才 steer）。
        """
        if self.state.active is not None:
            if conversation_id != self.state.active.conversation_id:
                notice = self._message(
                    conversation_id=conversation_id,
                    source=MessageSource.SYSTEM,
                    kind=MessageKind.SYSTEM_STATUS,
                    text="另一聊天的助手任务仍在运行，当前指令没有转交。",
                )
                return ConversationOutcome(messages=(user_message, notice))
            # O2.4：设计 §3.2——运行中用户直接发给助手的新指令拥有最高优先级，
            # 归一为 TaskAmendment 走 amend_turn，来源标记 user 与角色建议区分
            try:
                amendment = TaskAmendment(
                    target_task_id=self.state.active.task_id,
                    origin_message_id=user_message.message_id,
                    revision=1,
                    instructions=user_message.text,
                    origin="user",
                )
                await self._steer_turn(amendment)
            except (RuntimeError, ValueError) as exc:
                # 冲突场景（引擎 turn 尚未绑定、生命周期已终态等）：
                # 转用户可见系统提示，不再静默失败
                notice = self._message(
                    conversation_id=conversation_id,
                    source=MessageSource.SYSTEM,
                    kind=MessageKind.SYSTEM_STATUS,
                    text=f"修改未能应用：{exc}",
                )
                return ConversationOutcome(messages=(user_message, notice))
            # 修改已交给运行中的任务，本次直接输入不再开启新任务
            return ConversationOutcome(messages=(user_message,))
        task = TaskRequest(
            conversation_id=conversation_id,
            origin_message_id=user_message.message_id,
            instructions=user_message.text,
            constraints=constraints,
        )
        execution = await self._execute(task)
        return ConversationOutcome(
            messages=(user_message, *execution.messages),
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
        amendment = TaskAmendment(
            target_task_id=active.task_id,
            origin_message_id=origin_message_id,
            revision=draft.revision or 1,
            instructions=draft.instructions,
            # O2.4：角色建议的修改，来源与用户直接指令区分
            origin="character",
        )
        await self._steer_turn(amendment)

    async def _steer_turn(self, amendment: TaskAmendment) -> None:
        """把 amendment 发送给运行中的引擎 turn，并切换生命周期状态。

        O2.4：角色建议与用户直接指令共用此路径；生命周期先转
        AMENDMENT_PENDING 再回拨 RUNNING——期间若已被取消请求落到
        CANCELLED（终态）则不再回拨，避免 InvalidTaskTransition。
        """
        active = self.state.active
        if active is None or active.engine_turn_id is None or self._active_lifecycle is None:
            raise RuntimeError("no running task can accept an amendment")
        self._active_lifecycle.transition(TaskStatus.AMENDMENT_PENDING)
        session = self._sessions[active.conversation_id]
        await self.coding_engine.amend_turn(session, active.engine_turn_id, amendment)
        if self._active_lifecycle.status == TaskStatus.AMENDMENT_PENDING:
            self._active_lifecycle.transition(TaskStatus.RUNNING)

    async def cancel_active_task(self) -> bool:
        """O2.3：请求取消当前活动任务（取消按钮入口）。

        经 ``GlobalEngineState`` 找到活动 turn，调用引擎 ``cancel_turn``
        发送 turn/interrupt；生命周期先行落到 CANCELLED（终态），
        ``_execute`` 收尾时只做去重转移，不再重复 transition。
        无活动任务、引擎 turn 尚未绑定（还没收到任何事件）、
        生命周期已终态或会话引用缺失时返回 False（按钮保持禁用兜底）。
        """
        active = self.state.active
        lifecycle = self._active_lifecycle
        if (
            active is None
            or active.engine_turn_id is None
            or lifecycle is None
            or lifecycle.status not in (TaskStatus.RUNNING, TaskStatus.AMENDMENT_PENDING)
        ):
            return False
        session = self._sessions.get(active.conversation_id)
        if session is None:
            return False
        lifecycle.transition(TaskStatus.CANCELLED)
        await self.coding_engine.cancel_turn(session, active.engine_turn_id)
        return True

    async def _execute(
        self,
        task: TaskRequest,
        *,
        delegation_id: str | None = None,
        origin: MessageOrigin | None = None,
    ) -> ConversationOutcome:
        """执行一次助手任务。

        V0.2：``delegation_id``/``origin`` 标记任务消息归属——角色委派产生
        的执行记录 origin=character_delegation 且带 delegation_id，直发
        助手的执行记录保持 user 来源。Presenter 按此把两类记录都归入工作台，
        委派卡通过 delegation_id 连接角色区与工作台。
        """
        task_project = self.project
        task_pair_id = self.pair_id
        task_approval_mode = self.approval_mode
        task_assistant_instructions = self.assistant_instructions
        task_delegation_id = delegation_id or task.task_id
        self.state.start(
            project_id=task_project.project_id,
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
        assistant_reasoning_summary = ""
        assistant_reasoning_content = ""
        tool_runs: dict[str, ToolRun] = {}
        failed = False
        cancelled = False
        terminal_status: ReceiptStatus | None = None
        errors: list[str] = []
        changed_files: list[str] = []
        checks: list[str] = []
        engine_turn_id = "unavailable"
        sequence = 0
        # O3.1：已被原生审批请求（requestApproval）裁决过的工具操作集合。
        # 引擎侧挂起时已裁决并回复，后续到达的 tool.started 不再重复门控。
        adjudicated_tool_ids: set[str] = set()
        # 本次执行产生的新消息（含沙箱与审批 system 卡片）从这里开始
        history_start = len(self._history.get(task.conversation_id, []))
        sandbox = ProjectSandbox(Path(task_project.root_path))
        approval = self._approval_managers.setdefault(
            task.conversation_id,
            ApprovalManager(
                mode=task_approval_mode,
                rules=self.risk_rules,
                reviewer=self.reviewer,
                on_review=self._forward_review_event,
            ),
        )
        approval.mode = task_approval_mode
        approval.on_review = self._forward_review_event
        # O3.3：执行期间的活动任务进度（事件驱动更新，结束时清理）
        progress = self._progress.setdefault(task.conversation_id, _TaskProgress())
        if origin == MessageOrigin.CHARACTER_DELEGATION:
            # 角色委派被接受时，先写入正式的工作台任务消息。它不是异常兜底，
            # 而是委派协议本身的起始事件；后续 Codex 成功或抛错都能关联到
            # 同一个 delegation_id。
            self._message(
                conversation_id=task.conversation_id,
                source=MessageSource.USER,
                kind=MessageKind.USER_TEXT,
                text=task.instructions,
                pair_id=task_pair_id,
                target=MessageTarget.ASSISTANT,
                origin=origin,
                delegation_id=task_delegation_id,
                message_id=f"delegation:{task.conversation_id}:{task.task_id}",
                status=MessageStatus.PROCESSING,
            )
        try:
            session = self._sessions.get(task.conversation_id)
            # B1：按审批模式映射 app-server 策略（设计 §14.6）。
            # 仅新开线程时生效；恢复线程沿用线程既有设置。
            policy = self._engine_policy(task_approval_mode)
            session = await self.coding_engine.open_session(
                task_project,
                session,
                approval_policy=policy["approvalPolicy"],
                sandbox=policy["sandbox"],
                approvals_reviewer=policy["approvalsReviewer"],
                developer_instructions=task_assistant_instructions or None,
            )
            self._sessions[task.conversation_id] = session
            if self.store is not None:
                self.store.save_engine_session(task.conversation_id, session)

            async for raw_event in self.coding_engine.run_turn(session, task):
                # O4.1：事件序号单一源头——到达事件在循环入口统一分配；
                # 合成事件（审批 gate/否决/resolved）经同一计数器分配，
                # 出口事件流序号连续无碰撞，不再信任适配器自带序号。
                event = raw_event.model_copy(
                    update={
                        "conversation_id": task.conversation_id,
                        "task_id": task.task_id,
                        "sequence": sequence,
                    }
                )
                sequence += 1
                engine_turn_id = event.engine_turn_id
                if self.state.active and self.state.active.engine_turn_id is None:
                    self.state.bind_engine_turn(engine_turn_id)

                # O2.1：原始事件到达即推送（tool.started 先于审批/沙箱结果到达 UI，
                # 保证“运行中的工具卡片”立即出现）
                self._emit_event(event)

                if event.type == EngineEventType.APPROVAL_REQUESTED:
                    # O3.1：引擎侧挂起通知（app-server requestApproval）——
                    # 操作尚未执行，这里做真正的裁决：沙箱兜底（越界直接
                    # 否决）+ ApprovalManager 裁决，结果经 resolve_approval
                    # 回复引擎。原生审批不再作为独立交互卡片直透 UI。
                    op = self._operation_from_approval_event(event)
                    if event.tool_call_id:
                        adjudicated_tool_ids.add(event.tool_call_id)
                    # 设计 §6.3：请求 payload 记录决策方（user 或 reviewer）
                    payload = dict(event.payload)
                    payload.setdefault(
                        "actor",
                        "reviewer"
                        if approval.mode == ApprovalMode.REVIEW
                        else "user",
                    )
                    event = event.model_copy(update={"payload": payload})
                    # O4.1：请求事件在分支入口先入列——出口列表与推送顺序
                    # 一致（请求→裁决→工具），沙箱否决路径（continue）也不会丢事件
                    events.append(event)
                    approval_id = str(event.payload.get("approval_id") or "")
                    try:
                        self._check_sandbox(sandbox, op)
                    except SandboxViolation as exc:
                        # 挂起中的越界操作直接否决，引擎不会执行
                        await self.coding_engine.resolve_approval(
                            session, approval_id, ApprovalDecision.DENY
                        )
                        sequence = self._deny_tool_and_notify(
                            events,
                            event,
                            deny_reason=f"沙箱拦截：{exc}",
                            message_text=f"沙箱拦截：{exc}",
                            sequence=sequence,
                            conversation_id=task.conversation_id,
                            engine_turn_id=engine_turn_id,
                            pair_id=task_pair_id,
                        )
                        failed = True
                        errors.append(str(exc))
                        continue
                    outcome = await approval.adjudicate(
                        op,
                        requested_event=event,
                        conversation_id=task.conversation_id,
                        task_id=task.task_id,
                        engine_turn_id=engine_turn_id,
                        tool_call_id=event.tool_call_id,
                        context=self._recent_user_messages(task.conversation_id),
                        request_decision=self._request_approval,
                    )
                    sequence = self._emit_gate_outcome(
                        outcome,
                        events,
                        sequence,
                        conversation_id=task.conversation_id,
                        engine_turn_id=engine_turn_id,
                        pair_id=task_pair_id,
                    )
                    # O3.1：统一经 resolve_approval 转发裁决；被否决时
                    # 不中断执行循环——引擎把拒绝反馈给模型后继续 turn，
                    # 任务成败由 turn 终态决定。
                    await self.coding_engine.resolve_approval(
                        session, approval_id, outcome.decision
                    )

                elif event.type == EngineEventType.TOOL_STARTED:
                    op = self._operation_from_event(event)
                    # O4.1：工具事件在门控处理前先入列，出口列表与推送顺序
                    # 一致（工具开始→审批裁决/否决），序号连续
                    events.append(event)
                    # O3.3：当前步骤用中性标签（不泄露命令/路径原文）
                    progress.current_step = self._step_label(event)
                    try:
                        self._check_sandbox(sandbox, op)
                    except SandboxViolation as exc:
                        sequence = self._deny_tool_and_notify(
                            events,
                            event,
                            deny_reason=str(exc),
                            message_text=f"沙箱拦截：{exc}",
                            sequence=sequence,
                            conversation_id=task.conversation_id,
                            engine_turn_id=engine_turn_id,
                            pair_id=task_pair_id,
                        )
                        failed = True
                        errors.append(str(exc))
                        break

                    # Codex 的 item/started 已表示操作开始。真实适配器只接受
                    # app-server 在执行前发出的 requestApproval，避免在这里
                    # 展示已经无法阻止执行的审批卡片。演示适配器继续走本地
                    # 门控，用于离线验证三种审批模式。
                    if self.coding_engine.native_preexecution_approval:
                        continue

                    # O3.1：该工具操作已由原生审批请求裁决并回复
                    # （adjudicated），兜底 gate 不再重复执行；
                    # 演示引擎等不产生原生请求的路径仍走完整门控。
                    if not (
                        event.tool_call_id
                        and event.tool_call_id in adjudicated_tool_ids
                    ):
                        try:
                            outcome = await approval.gate(
                                op,
                                conversation_id=task.conversation_id,
                                task_id=task.task_id,
                                engine_turn_id=engine_turn_id,
                                sequence=sequence,
                                tool_call_id=event.tool_call_id,
                                context=self._recent_user_messages(
                                    task.conversation_id
                                ),
                            )
                            sequence = self._emit_gate_outcome(
                                outcome,
                                events,
                                sequence,
                                conversation_id=task.conversation_id,
                                engine_turn_id=engine_turn_id,
                                pair_id=task_pair_id,
                            )
                            if outcome.decision == ApprovalDecision.DENY:
                                sequence = self._deny_tool_and_notify(
                                    events,
                                    event,
                                    deny_reason="审批否决",
                                    message_text="审批否决",
                                    sequence=sequence,
                                    conversation_id=task.conversation_id,
                                    engine_turn_id=engine_turn_id,
                                    pair_id=task_pair_id,
                                )
                                failed = True
                                errors.append("审批否决")
                                break
                        except ApprovalRequired as req:
                            # O4.1：req.event 也走统一计数器（gate 内相对编号
                            # 不参与出口序号，避免与后续合成事件碰撞）
                            req.event = req.event.model_copy(update={"sequence": sequence})
                            sequence += 1
                            events.append(req.event)
                            self._emit_event(req.event)
                            # O1.7：把真实理由与 approval_id 传给回调，UI 不再用
                            # 命令文本冒充理由，也不再用 FIFO 顺序猜测对应关系
                            reason = str(
                                req.event.payload.get("reason", "") or "需要用户审批"
                            )
                            decision = await self._request_approval(
                                req.op, req.approval_id, reason
                            )
                            op = approval.resolve(req.approval_id, decision)
                            resolved_event = self._approval_resolved_event(
                                req.event, decision, "user", op, sequence
                            )
                            sequence += 1
                            events.append(resolved_event)
                            self._emit_event(resolved_event)
                            # 设计 §4.3：用户裁决以 system 卡片留在消息时间线
                            self._message(
                                conversation_id=task.conversation_id,
                                source=MessageSource.SYSTEM,
                                kind=MessageKind.APPROVAL,
                                text=self._decision_text(decision),
                                engine_turn_id=engine_turn_id,
                                pair_id=task_pair_id,
                            )
                            if decision == ApprovalDecision.DENY:
                                sequence = self._deny_tool_and_notify(
                                    events,
                                    event,
                                    deny_reason="用户否决",
                                    message_text="用户否决",
                                    sequence=sequence,
                                    conversation_id=task.conversation_id,
                                    engine_turn_id=engine_turn_id,
                                    pair_id=task_pair_id,
                                )
                                failed = True
                                errors.append("用户否决")
                                break

                if event.type not in (
                    EngineEventType.APPROVAL_REQUESTED,
                    EngineEventType.TOOL_STARTED,
                ):
                    # O4.1：这两类事件已在各自分支入口入列，避免重复
                    events.append(event)
                if event.type == EngineEventType.ASSISTANT_FINAL:
                    assistant_text = str(event.payload.get("text", ""))
                    # O3.3：助手进入收尾阶段
                    progress.current_step = "助手整理结果"
                elif event.type == EngineEventType.ASSISTANT_REASONING_DELTA:
                    text = str(event.payload.get("text", ""))
                    if event.payload.get("channel") == "content":
                        assistant_reasoning_content += text
                    else:
                        assistant_reasoning_summary += text
                elif event.type == EngineEventType.FILE_PATCH:
                    path = event.payload.get("path")
                    if path:
                        # O4.3：同一文件多次 patch 只记一次（保持首次出现顺序）
                        text = str(path)
                        if text not in changed_files:
                            changed_files.append(text)
                elif event.type == EngineEventType.TOOL_FINISHED:
                    status = cast(ToolRunStatus, str(event.payload.get("status", "succeeded")))
                    if status == "failed":
                        # 单个工具步骤失败不等于整个 turn 失败：引擎可能会
                        # 重试、改用其他路径，最后正常完成。保留错误明细，
                        # 但让真实的 turn.failed / turn.completed 终态决定
                        # 任务回执状态。
                        if event.payload.get("error"):
                            errors.append(str(event.payload["error"]))
                    if event.payload.get("check"):
                        checks.append(str(event.payload["check"]))
                    # O3.3：工具步骤收尾后计数
                    progress.completed_steps += 1
                    progress.current_step = "任务收尾中"
                    if event.tool_call_id:
                        tool_runs[event.tool_call_id] = ToolRun(
                            tool_call_id=event.tool_call_id,
                            conversation_id=task.conversation_id,
                            task_id=task.task_id,
                            engine_turn_id=engine_turn_id,
                            sequence=event.sequence,
                            status=status,
                            title=str(event.payload.get("title", "工具")),
                            summary=str(event.payload.get("summary", "")),
                            details=str(event.payload.get("details", "")),
                        )
                elif event.type == EngineEventType.TURN_FAILED:
                    terminal_status = "failed"
                    error = event.payload.get("error")
                    if error:
                        errors.append(str(error))
                elif event.type == EngineEventType.TURN_COMPLETED:
                    cancelled = event.payload.get("status") == "cancelled"
                    # 最后一个终态事件决定回执；引擎可能在重试过程中
                    # 先报告一次失败，随后用 completed 收尾。
                    terminal_status = "cancelled" if cancelled else "completed"

            if (
                not assistant_text.strip()
                and terminal_status not in ("failed", "cancelled")
                and not failed
            ):
                raise RuntimeError("古代机械未返回最终回复")

            # O2.3：取消链路接通后，生命周期可能已被 cancel_active_task
            # 先行落到 CANCELLED（终态），这里只做去重转移——目标状态与
            # 当前相同就不再 transition，避免 InvalidTaskTransition。
            target_status = (
                "cancelled"
                if cancelled or lifecycle.status == TaskStatus.CANCELLED
                else terminal_status
                if terminal_status is not None
                else "failed"
                if failed
                else "completed"
            )
            if TaskStatus(target_status) != lifecycle.status:
                lifecycle.transition(TaskStatus(target_status))
            # O4.3：出口处收敛为回执状态字面量类型
            status = cast(ReceiptStatus, target_status)
            if status == "cancelled":
                # O2.3：中断的演示流程没有收尾文案，回执如实标注已取消
                summary = assistant_text or "任务已取消"
            elif status == "failed":
                summary = assistant_text or "任务执行失败"
            else:
                summary = assistant_text or "任务执行完成"
            receipt = ExecutionReceipt(
                task_id=task.task_id,
                engine_turn_id=engine_turn_id,
                status=status,
                summary=summary,
                changed_files=tuple(changed_files),
                checks=tuple(checks),
                errors=tuple(errors),
            )
            for tool_run in tool_runs.values():
                if self.store is not None:
                    self.store.save_tool_run(tool_run)
            if assistant_text.strip():
                assistant_reasoning = (
                    assistant_reasoning_content.strip()
                    or assistant_reasoning_summary.strip()
                )
                self._message(
                    conversation_id=task.conversation_id,
                    source=MessageSource.ASSISTANT,
                    kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE,
                    text=assistant_text,
                    engine_turn_id=engine_turn_id,
                    message_id=f"assistant:{task.conversation_id}:{task.task_id}",
                    pair_id=task_pair_id,
                    delegation_id=task_delegation_id,
                    origin=origin or MessageOrigin.USER,
                    payload=(
                        {"reasoning": assistant_reasoning}
                        if assistant_reasoning
                        else None
                    ),
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
                pair_id=task_pair_id,
                source=MessageSource.SYSTEM,
                kind=MessageKind.SYSTEM_STATUS,
                text="execution-result",
            )
            dialogue_request = DialogueRequest(
                pair_id=task_pair_id,
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
            if result_turn is None:
                raise RuntimeError("角色未返回委派结果回复")
            self._message(
                conversation_id=task.conversation_id,
                source=MessageSource.CHARACTER,
                kind=MessageKind.CHARACTER_SPEECH,
                text=result_turn.speech,
                engine_turn_id=engine_turn_id,
                pair_id=task_pair_id,
                delegation_id=task_delegation_id,
                origin=origin or MessageOrigin.USER,
                payload=(
                    {
                        "reasoning": result_turn.reasoning,
                        "execution_status": receipt.status,
                    }
                    if result_turn.reasoning
                    else {"execution_status": receipt.status}
                ),
            )
            if origin == MessageOrigin.CHARACTER_DELEGATION:
                delegation_status = {
                    "completed": MessageStatus.DONE,
                    "failed": MessageStatus.FAILED,
                    "cancelled": MessageStatus.CANCELLED,
                }[receipt.status]
                self._set_message_status(
                    task.conversation_id,
                    f"delegation:{task.conversation_id}:{task.task_id}",
                    delegation_status,
                    reason=receipt.errors[0] if receipt.errors else None,
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
            # O3.3：任务结束清理进度，后续聊天轮不再注入摘要
            self._progress.pop(task.conversation_id, None)
            self.state.finish(task.task_id)
            self._active_lifecycle = None
            if self.on_execution_finished is not None:
                self.on_execution_finished()

    def _emit_event(self, event: EngineEvent) -> None:
        """O2.1：把引擎事件立即推送给 UI（流式通道）。"""
        if self.on_engine_event is not None:
            self.on_engine_event(event)

    @staticmethod
    def _step_label(event: EngineEvent) -> str:
        """O3.3：工具步骤的中性标签（不含命令、路径与输出原文）。

        只区分工具类别，避免把引擎事件里的原始内容带进角色摘要。
        """
        payload = event.payload
        if payload.get("path") or payload.get("paths"):
            return "正在修改文件"
        if payload.get("command") is not None:
            return "正在执行命令"
        if payload.get("title"):
            return "正在执行工具操作"
        return "正在处理任务"

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
    def _operation_from_approval_event(event: EngineEvent) -> PendingOperation:
        """O3.1：从原生审批请求事件构造待裁决操作。

        codec 已把 requestApproval 的字段归一进 payload
        （tool_kind/command/paths/summary），这里直接透传。
        """
        payload = event.payload
        return PendingOperation(
            tool_kind=payload.get("tool_kind", "shell"),
            command=payload.get("command"),
            paths=[str(p) for p in payload.get("paths", []) or []],
            patch_file_count=None,
            summary=str(
                payload.get("summary") or payload.get("reason") or "工具操作"
            ),
        )

    @staticmethod
    def _check_sandbox(sandbox: ProjectSandbox, op: PendingOperation) -> None:
        for path in op.paths:
            sandbox.resolve_write_path(path)
        if op.command is not None and op.tool_kind == "shell":
            sandbox.enforce_cwd(None)

    async def _request_approval(
        self, op: PendingOperation, approval_id: str, reason: str
    ) -> ApprovalDecision:
        if self.approval_callback is None:
            return ApprovalDecision.DENY
        return await self.approval_callback(op, approval_id, reason)

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

    def _emit_gate_outcome(
        self,
        outcome: GateOutcome,
        events: list[EngineEvent],
        sequence: int,
        *,
        conversation_id: str,
        engine_turn_id: str | None,
        pair_id: str,
    ) -> int:
        """裁决事件统一计数入列并推送；返回递增后的序号。

        设计 §4.3：裁决结果以 system 卡片留在消息时间线。
        """
        for gate_event in outcome.events:
            gate_event = gate_event.model_copy(update={"sequence": sequence})
            sequence += 1
            events.append(gate_event)
            self._emit_event(gate_event)
        notice = self._approval_notice(outcome)
        if notice is not None:
            self._message(
                conversation_id=conversation_id,
                source=MessageSource.SYSTEM,
                kind=MessageKind.APPROVAL,
                text=notice,
                engine_turn_id=engine_turn_id,
                pair_id=pair_id,
            )
        return sequence

    def _deny_tool_and_notify(
        self,
        events: list[EngineEvent],
        event: EngineEvent,
        *,
        deny_reason: str,
        message_text: str,
        sequence: int,
        conversation_id: str,
        engine_turn_id: str | None,
        pair_id: str,
    ) -> int:
        """合成 denied 工具事件入列推送并落 system 状态卡，返回新序号。

        failed / errors 由调用方按各自循环语义处理（continue 或 break）。
        """
        denied_event = self._deny_tool_event(event, deny_reason, sequence)
        events.append(denied_event)
        self._emit_event(denied_event)
        self._message(
            conversation_id=conversation_id,
            source=MessageSource.SYSTEM,
            kind=MessageKind.SYSTEM_STATUS,
            text=message_text,
            engine_turn_id=engine_turn_id,
            pair_id=pair_id,
        )
        return sequence + 1

    @staticmethod
    def _approval_resolved_event(
        requested: EngineEvent,
        decision: ApprovalDecision,
        actor: str,
        op: PendingOperation,
        sequence: int,
    ) -> EngineEvent:
        # O4.1：sequence 由调用方（统一计数器）显式传入，
        # 不再隐式取 requested.sequence + 1
        return EngineEvent(
            conversation_id=requested.conversation_id,
            task_id=requested.task_id,
            engine_turn_id=requested.engine_turn_id,
            sequence=sequence,
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
