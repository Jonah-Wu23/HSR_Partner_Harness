from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Literal, cast

from .approval import ApprovalManager, ApprovalRequired, GateOutcome
from .context import recent_roleplay_context
from .contracts import (
    ApprovalDecision,
    ApprovalMode,
    CharacterProgressSummary,
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
        # O3.3：活动任务的执行进度（_execute 期间填充，结束时清理）
        self._progress: dict[str, _TaskProgress] = {}
        self._active_lifecycle: TaskLifecycle | None = None
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
        # B2.6：消息监听器列表（VoiceRuntime 挂 TTS 用），在消息持久化后逐个调用
        self._message_listeners: list[Callable[[Message], None]] = []

    def set_approval_mode(self, mode: ApprovalMode) -> None:
        """切换项目级审批模式（计划 A5：输入区下拉框切换）。"""
        self.approval_mode = mode
        for manager in self._approval_managers.values():
            manager.mode = mode

    def add_message_listener(self, callback: Callable[[Message], None]) -> None:
        """注册消息监听器：消息持久化完成后同步调用（供 VoiceRuntime 挂 TTS）。

        与 ``on_message`` 单回调并存互不影响：UI 桥走 on_message，
        语音运行时走监听器列表。
        """
        if callback not in self._message_listeners:
            self._message_listeners.append(callback)

    def _engine_policy(self) -> dict[str, str | None]:
        """B1：应用层审批模式 → app-server thread/start 策略映射（设计 §14.6）。

        - 请求批准 / 帮我审核：``on-request`` + ``read-only`` 沙箱。真实联调
          确认 workspace-write 下工作区写操作不发起 requestApproval（B1 联调
          记录），改用 read-only 让一切写操作执行前挂起，由 ApprovalManager
          裁决后经 resolve_approval 回复——三种审批模式真实差异化拦截；
        - 完全允许运行：``never`` + ``workspace-write``（引擎不发起审批请求，
          写操作直接执行，工具事件照常持久化）；
        - ``approvalsReviewer`` 固定 ``"user"``——应用层审查智能体负责裁决，
          不启用原生 auto_review（§14.6 备注，B1 联调可评估切换）。
        """
        approval_policy = (
            "never"
            if self.approval_mode == ApprovalMode.FULL_AUTO
            else "on-request"
        )
        sandbox = (
            "workspace-write"
            if self.approval_mode == ApprovalMode.FULL_AUTO
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
        if session_ref is not None:
            self._sessions[conversation_id] = session_ref

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
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            pair_id=self.pair_id,
            engine_turn_id=engine_turn_id,
            source=source,
            kind=kind,
            text=text,
            payload=payload or {},
            tts_eligible=is_tts_eligible(source, kind),
        )
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

    async def handle_character_input(
        self, *, conversation_id: str, text: str
    ) -> ConversationOutcome:
        # O2.5：聊天轮（用户消息+角色台词）在会话锁内整体落库，轮内顺序
        # 固定为用户→角色，不与其他轮交错；委派处理（_execute/修改路由）
        # 在锁外进行，执行期间到达的聊天轮可与运行中任务并发。
        async with self._conversation_lock(conversation_id):
            user = self._message(
                conversation_id=conversation_id,
                source=MessageSource.USER,
                kind=MessageKind.USER_TEXT,
                text=text,
            )
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
                user_message=user,
                recent_messages=recent_roleplay_context(self._history[conversation_id][:-1]),
                progress_summary=progress_summary,
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
            try:
                execution = await self._execute(task)
            except BusyTurnError as exc:
                # O2.4：任务运行中角色再委派新任务——冲突转为用户可见的
                # 系统提示，不再静默失败；用户直接指令不受影响（走修改路由）。
                notice = self._message(
                    conversation_id=conversation_id,
                    source=MessageSource.SYSTEM,
                    kind=MessageKind.SYSTEM_STATUS,
                    text=f"任务仍在执行，本次委派暂未受理：{exc}",
                )
                return ConversationOutcome(messages=(user, character, notice))
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
                await self._apply_amendment(user.message_id, character_turn.delegation)
            except (RuntimeError, ValueError) as exc:
                # O2.4：角色建议的修改无法路由（无活动任务、生命周期已终态等）
                # 时同样转为可见系统提示，不静默
                notice = self._message(
                    conversation_id=conversation_id,
                    source=MessageSource.SYSTEM,
                    kind=MessageKind.SYSTEM_STATUS,
                    text=f"修改未能应用：{exc}",
                )
                return ConversationOutcome(messages=(user, character, notice))
        return ConversationOutcome(messages=tuple(messages))

    async def handle_direct_input(
        self, *, conversation_id: str, text: str, constraints: tuple[str, ...] = ()
    ) -> ConversationOutcome:
        # O2.5：直接输入的用户消息同样在会话锁内落库，避免拆散进行中的
        # 聊天轮；后续任务执行/修改路由在锁外进行。
        async with self._conversation_lock(conversation_id):
            user = self._message(
                conversation_id=conversation_id,
                source=MessageSource.USER,
                kind=MessageKind.USER_TEXT,
                text=text,
            )
        if self.state.active is not None:
            # O2.4：设计 §3.2——运行中用户直接发给助手的新指令拥有最高优先级，
            # 归一为 TaskAmendment 走 amend_turn，来源标记 user 与角色建议区分
            try:
                amendment = TaskAmendment(
                    target_task_id=self.state.active.task_id,
                    origin_message_id=user.message_id,
                    revision=1,
                    instructions=text,
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
                return ConversationOutcome(messages=(user, notice))
            # 修改已交给运行中的任务，本次直接输入不再开启新任务
            return ConversationOutcome(messages=(user,))
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
        # O3.1：已被原生审批请求（requestApproval）裁决过的工具操作集合。
        # 引擎侧挂起时已裁决并回复，后续到达的 tool.started 不再重复门控。
        adjudicated_tool_ids: set[str] = set()
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
        # O3.3：执行期间的活动任务进度（事件驱动更新，结束时清理）
        progress = self._progress.setdefault(task.conversation_id, _TaskProgress())
        try:
            session = self._sessions.get(task.conversation_id)
            # B1：按审批模式映射 app-server 策略（设计 §14.6）。
            # 仅新开线程时生效；恢复线程沿用线程既有设置。
            policy = self._engine_policy()
            session = await self.coding_engine.open_session(
                self.project,
                session,
                approval_policy=policy["approvalPolicy"],
                sandbox=policy["sandbox"],
                approvals_reviewer=policy["approvalsReviewer"],
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
                        if self.approval_mode == ApprovalMode.REVIEW
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
                        denied_event = self._deny_tool_event(
                            event, f"沙箱拦截：{exc}", sequence
                        )
                        sequence += 1
                        events.append(denied_event)
                        self._emit_event(denied_event)
                        failed = True
                        errors.append(str(exc))
                        self._message(
                            conversation_id=task.conversation_id,
                            source=MessageSource.SYSTEM,
                            kind=MessageKind.SYSTEM_STATUS,
                            text=f"沙箱拦截：{exc}",
                            engine_turn_id=engine_turn_id,
                        )
                        continue
                    outcome = await approval.adjudicate(
                        op,
                        requested_event=event,
                        conversation_id=task.conversation_id,
                        task_id=task.task_id,
                        engine_turn_id=engine_turn_id,
                        tool_call_id=event.tool_call_id,
                        # 计划 A3：审查智能体需要近期上下文（最近 3 条）
                        context=self._history.get(task.conversation_id, [])[-3:],
                        request_decision=self._request_approval,
                    )
                    for gate_event in outcome.events:
                        gate_event = gate_event.model_copy(update={"sequence": sequence})
                        sequence += 1
                        events.append(gate_event)
                        self._emit_event(gate_event)
                    # 设计 §4.3：裁决结果以 system 卡片留在消息时间线
                    notice = self._approval_notice(outcome)
                    if notice is not None:
                        self._message(
                            conversation_id=task.conversation_id,
                            source=MessageSource.SYSTEM,
                            kind=MessageKind.APPROVAL,
                            text=notice,
                            engine_turn_id=engine_turn_id,
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
                        denied_event = self._deny_tool_event(
                            event, str(exc), sequence
                        )
                        sequence += 1
                        events.append(denied_event)
                        self._emit_event(denied_event)
                        failed = True
                        errors.append(str(exc))
                        self._message(
                            conversation_id=task.conversation_id,
                            source=MessageSource.SYSTEM,
                            kind=MessageKind.SYSTEM_STATUS,
                            text=f"沙箱拦截：{exc}",
                            engine_turn_id=engine_turn_id,
                        )
                        break

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
                                # 计划 A3：审查智能体需要近期上下文（最近 3 条）
                                context=self._history.get(task.conversation_id, [])[-3:],
                            )
                            for gate_event in outcome.events:
                                gate_event = gate_event.model_copy(
                                    update={"sequence": sequence}
                                )
                                sequence += 1
                                events.append(gate_event)
                                self._emit_event(gate_event)
                            # 设计 §4.3：裁决结果以 system 卡片留在消息时间线
                            notice = self._approval_notice(outcome)
                            if notice is not None:
                                self._message(
                                    conversation_id=task.conversation_id,
                                    source=MessageSource.SYSTEM,
                                    kind=MessageKind.APPROVAL,
                                    text=notice,
                                    engine_turn_id=engine_turn_id,
                                )
                            if outcome.decision == ApprovalDecision.DENY:
                                denied_event = self._deny_tool_event(
                                    event, "审批否决", sequence
                                )
                                sequence += 1
                                events.append(denied_event)
                                self._emit_event(denied_event)
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
                            )
                            if decision == ApprovalDecision.DENY:
                                denied_event = self._deny_tool_event(
                                    event, "用户否决", sequence
                                )
                                sequence += 1
                                events.append(denied_event)
                                self._emit_event(denied_event)
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
                        failed = True
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
                    failed = True
                    error = event.payload.get("error")
                    if error:
                        errors.append(str(error))
                elif event.type == EngineEventType.TURN_COMPLETED:
                    cancelled = event.payload.get("status") == "cancelled"

            # O2.3：取消链路接通后，生命周期可能已被 cancel_active_task
            # 先行落到 CANCELLED（终态），这里只做去重转移——目标状态与
            # 当前相同就不再 transition，避免 InvalidTaskTransition。
            target_status = (
                "cancelled"
                if cancelled or lifecycle.status == TaskStatus.CANCELLED
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
            elif failed:
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
            if assistant_text:
                self._message(
                    conversation_id=task.conversation_id,
                    source=MessageSource.ASSISTANT,
                    kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE,
                    text=assistant_text,
                    engine_turn_id=engine_turn_id,
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
                    engine_turn_id=engine_turn_id,
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
