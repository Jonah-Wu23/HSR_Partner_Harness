from __future__ import annotations

import asyncio
import logging
import time as time_module
from collections.abc import Awaitable, Callable, Iterable
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path, PurePath
from typing import Literal, cast

from .approval import ApprovalManager, GateOutcome
from .context import ExecutionContext
from .projection import role_context_window
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
    MemoryDraft,
    Message,
    MessageKind,
    MessageOrigin,
    MessageSource,
    MessageStatus,
    MessageTarget,
    PendingOperation,
    ProjectRuntimeContext,
    TaskAmendment,
    TaskAmendmentDraft,
    TaskRequest,
    TaskRequestDraft,
    TaskStatus,
    ToolRun,
    next_created_at,
)
from .engine_state import ActiveTurn, BusyTurnError, GlobalEngineState, TaskLifecycle
from .ports import CodingEngine, DialogueModel, Reviewer, StateStore
from .repository import ConversationSnapshot
from .risk_rules import RiskRules, default_risk_rules
from .sandbox import ProjectSandbox, SandboxViolation
from .voice_policy import is_tts_eligible

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Runtime:
    """一套整体替换的模型运行时：角色对话模型、编程助手引擎与审查智能体。"""

    dialogue_model: DialogueModel
    coding_engine: CodingEngine
    reviewer: Reviewer | None


@dataclass(frozen=True)
class ConversationOutcome:
    messages: tuple[Message, ...] = ()
    # 本轮角色要求写入的长期记忆条目。持久化与作用域解析由调用方
    # （application_service）负责，编排器不接触存储。
    memory_drafts: tuple[MemoryDraft, ...] = ()
    engine_events: tuple[EngineEvent, ...] = ()
    tool_runs: tuple[ToolRun, ...] = ()
    task: TaskRequest | None = None
    receipt: ExecutionReceipt | None = None
    # 任务失败的结果轮里角色立即重新委派的草稿。编排器据此自动重试
    # 一次；达到重试上限时不再执行并给出可见系统提示。
    retry_delegation: TaskRequestDraft | None = None


@dataclass
class _TaskProgress:
    """执行期间的活动任务进度。

    只保存中性描述（当前步骤标签、已完成步骤数），不保存命令、路径与
    输出原文。进度状态只在工具事件到达时更新，摘要只在执行期间的聊天轮
    到达时生成，不逐事件注入。
    """

    current_step: str = "任务准备中"
    completed_steps: int = 0


@dataclass
class _SegmentState:
    """单次任务内的助手分段累加器。

    思考与正文 delta 持续进入当前段；第一个工具事件到达时定稿当前段，
    工具后再次出现的 delta 开新段。消息 id 为
    ``assistant:{conversation_id}:{task_id}:{segment_index}``。
    """

    index: int = -1
    order: int | None = None
    text_parts: list[str] = field(default_factory=list)
    reasoning_content: list[str] = field(default_factory=list)
    reasoning_summary: list[str] = field(default_factory=list)
    # ASSISTANT_FINAL 的完整正文覆盖当前段的流式累积
    final_override: str | None = None
    finalized_count: int = 0

    def is_open(self) -> bool:
        return self.index >= 0


ApprovalCallback = Callable[
    [PendingOperation, str, str, str, str], Awaitable[ApprovalDecision]
]
"""审批回调签名：操作、approval_id、理由、conversation_id、task_id。

裁决按 approval_id 对应到 UI 审批队列中的条目。
"""

# ToolRun.status 与 ExecutionReceipt.status 的枚举值在事件循环里以 str
# 流动，出口处用 cast 收敛到字面量类型。
ToolRunStatus = Literal["running", "succeeded", "failed", "denied"]
ReceiptStatus = Literal["completed", "failed", "cancelled"]


def _conversation_turn_index(history: list[Message]) -> int:
    """计算本轮序号（用户发起消息累计数，1 起算）。

    入参为当前用户消息之前的历史。只统计 source==USER 且 origin==USER
    的用户真实发言；角色、助手、工具、系统消息与开场白都不计入。
    返回值 = 1 + 上述用户消息条数（当前回合占 +1）。
    """
    user_messages = sum(
        1
        for m in history
        if m.source == MessageSource.USER and m.origin == MessageOrigin.USER
    )
    return 1 + user_messages


class ConversationOrchestrator:
    def __init__(
        self,
        *,
        dialogue_model: DialogueModel,
        coding_engine: CodingEngine,
        approval_callback: ApprovalCallback,
        state: GlobalEngineState | None = None,
        store: StateStore | None = None,
        risk_rules: RiskRules | None = None,
        reviewer: Reviewer | None = None,
    ) -> None:
        self.dialogue_model = dialogue_model
        self.coding_engine = coding_engine
        self.state = state or GlobalEngineState()
        self.store = store
        self.risk_rules = risk_rules or default_risk_rules()
        self.reviewer = reviewer
        self.approval_callback = approval_callback
        self._history: dict[str, list[Message]] = {}
        self._sessions: dict[str, EngineSessionRef] = {}
        self._approval_managers: dict[str, ApprovalManager] = {}
        # 活动任务的执行进度（_execute 期间填充，结束时清理）
        self._progress: dict[str, _TaskProgress] = {}
        # 活动任务生命周期按 task_id 索引；不同聊天并发时各自独立推进，
        # 一个任务结束只清理自己的生命周期。
        self._active_lifecycles: dict[str, TaskLifecycle] = {}
        # 每个聊天单调递增的时间线序号，全部消息与工具记录共用同一计数器。
        # restore_conversation 从历史最大值恢复。
        self._timeline_counters: dict[str, int] = {}
        # 角色流式回复开始时为 speech:{conversation_id}:{user_message_id}
        # 预留的序号；同 id 的最终角色消息落库时取回。
        self._speech_orders: dict[str, int] = {}
        # 每会话入口锁：聊天轮（用户消息+角色台词）在锁内整体落库，轮内
        # 顺序固定为用户→角色且不与其他轮交错。任务执行刻意不在锁内，
        # 执行期间到达的聊天轮与执行产生的系统、助手消息按落库先后交错，
        # 运行中的直接输入与修改仍可并发 steer 活动 turn。
        self._conversation_locks: dict[str, asyncio.Lock] = {}
        # 会话级搭档登记表：消息与系统提示必须使用该聊天自己的搭档 id。
        # 由 restore_conversation 与执行上下文登记。
        self._conversation_pairs: dict[str, str] = {}
        # 会话最近一次成功摘要的覆盖终点。触发摘要后角色上下文只保留最近
        # 12 条原文；未登记时沿用触发前上限。
        self._summary_coverage: dict[str, str] = {}
        # 执行生命周期回调：busy 状态由任务开始与结束驱动，回调携带完整
        # ActiveTurn。
        self.on_execution_started: Callable[[ActiveTurn], None] | None = None
        self.on_execution_finished: Callable[[ActiveTurn], None] | None = None
        # 流式事件通道：消息与引擎事件产生时即推送，UI 增量渲染；
        # ConversationOutcome 是最终汇总。角色接受委派的台词先于执行事件
        # 到达界面。
        self.on_message: Callable[[Message], None] | None = None
        self.on_engine_event: Callable[[EngineEvent], None] | None = None
        # 消息生命周期状态变更回调（message.status_changed）。on_message
        # 管创建，本回调管状态推进。
        self.on_message_status_changed: Callable[[Message], None] | None = None
        # 对话增量事件通道（角色思考与正文 delta），由桌面桥转发为
        # message.delta 的 reasoning 与 speech 通道；末参是该角色回复的
        # 时间线序号。
        self.on_dialogue_event: (
            Callable[[str, Message, DialogueEvent, int], None] | None
        ) = None
        # 审查智能体生命周期事件（review.started/completed/failed），只有
        # 真正调用审查智能体时才触发。
        self.on_review_event: Callable[[str, dict], None] | None = None
        # 消息监听器列表（VoiceRuntime 挂 TTS 用），在消息持久化后逐个调用
        self._message_listeners: list[Callable[[Message], None]] = []

    def install_runtime(self, runtime: Runtime) -> Runtime:
        """整体替换对话模型、编程助手引擎与审查智能体，返回被替换的旧运行时。"""
        previous = Runtime(
            dialogue_model=self.dialogue_model,
            coding_engine=self.coding_engine,
            reviewer=self.reviewer,
        )
        self.dialogue_model = runtime.dialogue_model
        self.coding_engine = runtime.coding_engine
        self.reviewer = runtime.reviewer
        return previous

    def forget_sessions(self, conversation_ids: Iterable[str] | None = None) -> None:
        """丢弃内存中的引擎会话引用（None 表示全部），下一次任务新开 session。"""
        if conversation_ids is None:
            self._sessions.clear()
            return
        for conversation_id in conversation_ids:
            self._sessions.pop(conversation_id, None)

    def set_project_approval_mode(self, project_id: str, mode: ApprovalMode) -> None:
        """把项目审批模式应用到该项目正在运行的任务。

        尚未开始的任务在提交时从项目设置解析审批模式，这里只更新运行中
        任务的审批管理器，其他项目的任务不受影响。
        """
        for active in self.state.active_tasks():
            if active.project_id == project_id:
                self._approval_managers[active.conversation_id].mode = mode

    def _pair_id_for(self, conversation_id: str, explicit: str | None) -> str:
        """解析消息归属的搭档 id：显式传入优先，其次是该聊天登记的搭档。"""
        if explicit:
            return explicit
        registered = self._conversation_pairs.get(conversation_id)
        if registered is None:
            raise RuntimeError(f"会话 {conversation_id} 没有登记搭档，无法确定消息归属")
        return registered

    def set_summary_coverage(
        self, conversation_id: str, covers_to_message_id: str | None
    ) -> None:
        """登记该聊天最近一次成功摘要的覆盖终点。

        接线方在 ``summary.completed`` 与 ``restore_conversation`` 时调用；
        传 None 表示该聊天没有成功摘要（退回触发前窗口）。
        """
        if covers_to_message_id:
            self._summary_coverage[conversation_id] = covers_to_message_id
        else:
            self._summary_coverage.pop(conversation_id, None)

    def summary_coverage(self, conversation_id: str) -> str | None:
        """该聊天已成功摘要覆盖到的消息 id（无则 None）。"""
        return self._summary_coverage.get(conversation_id)

    def _roleplay_context(
        self, conversation_id: str, *, exclude_message_id: str | None = None
    ) -> tuple[Message, ...]:
        """进入角色上下文的原文窗口（主角色轮与任务结果轮共用）。

        过滤与窗口规则见 ``projection.role_context_window``：触发摘要后
        保留最近 12 条角色消息原文，未触发时沿用触发前上限。
        """
        history = self._history.get(conversation_id, ())
        if exclude_message_id is not None:
            history = tuple(
                message
                for message in history
                if message.message_id != exclude_message_id
            )
        return role_context_window(
            history,
            covered_to_message_id=self._summary_coverage.get(conversation_id),
        )

    def _turn_index_for(self, conversation_id: str, source_message_id: str) -> int:
        """当前用户回合的序号（世界书 atDepth 与确定性触发用）。

        以该用户消息之前的用户真实发言数为基准 +1，主角色轮与任务结果轮
        对同一回合得到同一个值。用户消息由 ``_message`` 落进历史后才进入
        回合处理，找不到即为调用方错误。
        """
        history = self._history.get(conversation_id, [])
        for index, message in enumerate(history):
            if message.message_id == source_message_id:
                return _conversation_turn_index(history[:index])
        raise RuntimeError(
            f"回合源消息 {source_message_id} 不在聊天 {conversation_id} 的历史中"
        )

    def _dialogue_request(
        self,
        *,
        conversation_id: str,
        user_message: Message,
        pair_id: str,
        runtime_context: ProjectRuntimeContext,
        turn_index: int,
        exclude_message_id: str | None = None,
        progress_summary: CharacterProgressSummary | None = None,
        result_summary: CharacterResultSummary | None = None,
    ) -> DialogueRequest:
        """角色装配点共用的 DialogueRequest 构造。

        主角色轮与任务结果轮使用同一份上下文窗口、同一回合序号与同一
        项目运行上下文。
        """
        return DialogueRequest(
            pair_id=pair_id,
            conversation_id=conversation_id,
            user_message=user_message,
            recent_messages=self._roleplay_context(
                conversation_id, exclude_message_id=exclude_message_id
            ),
            progress_summary=progress_summary,
            result_summary=result_summary,
            runtime_context=runtime_context,
            turn_index=turn_index,
        )

    @staticmethod
    def _build_runtime_context(context: ExecutionContext) -> ProjectRuntimeContext:
        """构造项目运行上下文（名称、目录、时间、时区、对话模式）。"""
        project = context.project
        now = datetime.now().astimezone()
        tz_abbr = time_module.tzname[0] if time_module.tzname else now.tzname() or ""
        return ProjectRuntimeContext(
            project_name=project.name,
            project_abs_dir=project.root_path,
            local_time=now.strftime("%Y-%m-%d %H:%M:%S"),
            timezone=tz_abbr or str(now.utcoffset() or ""),
            conversation_mode=context.conversation_mode,
            memory_enabled=bool((project.root_path or "").strip()),
        )

    def mark_message_failed(
        self, conversation_id: str, message_id: str, reason: str
    ) -> Message | None:
        """把一条已落库消息标记为失败（保留文字，可重试）。

        处理失败后文字仍在，前端可按真实 id 对账并重试。同时更新内存历史
        与 SQLite，并推送 ``message.status_changed``。
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
            if status == MessageStatus.DONE:
                # 完成态不保留更早失败或取消留下的原因。
                payload.pop("error", None)
                payload.pop("cancelled_reason", None)
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

    def report_system_status(
        self, conversation_id: str, text: str, *, pair_id: str | None = None
    ) -> Message:
        """把运行时错误作为可见且可恢复的系统消息写入目标聊天。

        ``pair_id`` 缺省时使用该聊天登记的搭档。
        """
        return self._message(
            conversation_id=conversation_id,
            source=MessageSource.SYSTEM,
            kind=MessageKind.SYSTEM_STATUS,
            text=text,
            pair_id=pair_id,
        )

    def add_message_listener(self, callback: Callable[[Message], None]) -> None:
        """注册消息监听器：消息持久化完成后同步调用（供 VoiceRuntime 挂 TTS）。

        与 ``on_message`` 单回调并存互不影响：UI 桥走 on_message，
        语音运行时走监听器列表。
        """
        if callback not in self._message_listeners:
            self._message_listeners.append(callback)

    def remove_message_listener(self, callback: Callable[[Message], None]) -> None:
        """移除消息监听器（替换 VoiceRuntime 时清理旧回调）。"""
        while callback in self._message_listeners:
            self._message_listeners.remove(callback)

    def restore_conversation(self, snapshot: ConversationSnapshot) -> None:
        """打开旧聊天时回填消息历史、搭档、摘要覆盖与引擎会话引用。

        - ``messages`` 回填 ``_history``，恢复后角色上下文不再为空；
        - 快照里的会话搭档是该聊天的权威身份；
        - 只有 completed 摘要才收窄角色上下文窗口；
        - 引擎类型一致的 ``engine_session`` 回填 ``_sessions``，后续
          ``open_session`` 收到已保存的 ``stored_ref`` 并恢复引擎会话。
        """
        conversation = snapshot.conversation
        conversation_id = conversation.conversation_id
        self._history[conversation_id] = list(snapshot.messages)
        self._conversation_pairs[conversation_id] = conversation.pair_id
        summary = snapshot.summary
        self.set_summary_coverage(
            conversation_id,
            summary.covers_to_message_id
            if summary is not None and summary.status == "completed"
            else None,
        )
        session_ref = snapshot.engine_session
        if (
            session_ref is not None
            and session_ref.engine_type == self.coding_engine.engine_type
        ):
            self._sessions[conversation_id] = session_ref
        else:
            self._sessions.pop(conversation_id, None)
        # 恢复时间线计数器：取历史消息与工具记录的最大序号，且不低于内存里
        # 已分配的值（运行中的任务可能已分配尚未落库的序号）。
        restored_orders = [
            value
            for value in (
                *(m.timeline_order for m in snapshot.messages),
                *(r.timeline_order for r in snapshot.tool_runs),
            )
            if value is not None
        ]
        self._timeline_counters[conversation_id] = max(
            [self._timeline_counters.get(conversation_id, 0), *restored_orders]
        )

    def close_conversation(self, conversation_id: str) -> None:
        """聊天结束或切换时清理该会话的“本对话内允许”缓存。

        会话没有运行中任务时同时移除审批管理器，下次使用该会话时新建；
        运行中任务的管理器保留登记，项目审批模式切换仍能作用到它。
        未打开过的会话调用是空操作。
        """
        manager = self._approval_managers.get(conversation_id)
        if manager is None:
            return
        manager.clear_session_cache()
        if self.state.get_for_conversation(conversation_id) is None:
            del self._approval_managers[conversation_id]

    def _conversation_lock(self, conversation_id: str) -> asyncio.Lock:
        """获取会话级入口锁（首次访问时惰性创建）。

        不同会话的入口互不阻塞；同一会话的聊天轮按到达顺序串行。
        """
        lock = self._conversation_locks.get(conversation_id)
        if lock is None:
            lock = asyncio.Lock()
            self._conversation_locks[conversation_id] = lock
        return lock

    def _next_timeline_order(self, conversation_id: str) -> int:
        """分配该聊天单调递增的工作台序号。"""
        value = self._timeline_counters.get(conversation_id, 0) + 1
        self._timeline_counters[conversation_id] = value
        return value

    def _finalize_segment(
        self,
        state: _SegmentState,
        *,
        conversation_id: str,
        task_id: str,
        engine_turn_id: str | None,
        pair_id: str,
        delegation_id: str | None,
        origin: MessageOrigin | None,
    ) -> str | None:
        """定稿当前助手 segment 并持久化为独立消息。

        消息 id 为 ``assistant:{conversation_id}:{task_id}:{segment_index}``。
        没有打开的段、或段内既无正文也无思考时不产生消息；只有思考的段
        保留为可折叠气泡。返回刚定稿 segment 的正文，供回执摘要使用。
        """
        if not state.is_open():
            return None
        text = (
            state.final_override
            if state.final_override is not None
            else "".join(state.text_parts)
        )
        reasoning = "".join(state.reasoning_content).strip() or "".join(
            state.reasoning_summary
        ).strip()
        index = state.index
        order = state.order
        state.index = -1
        state.order = None
        state.text_parts = []
        state.reasoning_content = []
        state.reasoning_summary = []
        state.final_override = None
        state.finalized_count = index + 1
        if not text.strip() and not reasoning:
            return None
        self._message(
            conversation_id=conversation_id,
            source=MessageSource.ASSISTANT,
            kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE,
            text=text,
            engine_turn_id=engine_turn_id,
            message_id=f"assistant:{conversation_id}:{task_id}:{index}",
            pair_id=pair_id,
            delegation_id=delegation_id,
            origin=origin or MessageOrigin.USER,
            payload=({"reasoning": reasoning} if reasoning else None),
            task_id=task_id,
            timeline_order=order,
        )
        return text

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
        task_id: str | None = None,
        timeline_order: int | None = None,
    ) -> Message:
        history = self._history.setdefault(conversation_id, [])
        reserved = (
            self._speech_orders.pop(message_id, None) if message_id is not None else None
        )
        if timeline_order is None:
            # 更新已有消息沿用原序号；角色回复取流式开始时预留的序号；
            # 其余新消息分配下一个序号。
            existing = next(
                (m for m in history if message_id is not None and m.message_id == message_id),
                None,
            )
            if existing is not None:
                timeline_order = existing.timeline_order
            elif reserved is not None:
                timeline_order = reserved
            else:
                timeline_order = self._next_timeline_order(conversation_id)
        message_values = {
            "conversation_id": conversation_id,
            "pair_id": self._pair_id_for(conversation_id, pair_id),
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
            "task_id": task_id,
            "timeline_order": timeline_order,
        }
        if message_id is not None:
            message_values["message_id"] = message_id
        # 同一回合内的角色台词与委派卡片可能落在同一个微秒；持久化按
        # (created_at, message_id) 排序，并列会让重开后的顺序由随机的
        # message_id 决定，与内存创建顺序不一致。这里按会话做严格单调。
        latest = max((m.created_at for m in history), default=None)
        message_values["created_at"] = next_created_at(latest)
        message = Message(**message_values)
        for index, existing in enumerate(history):
            if existing.message_id == message.message_id:
                # 同一 message_id 表示更新原消息。内存历史与 SQLite 保持
                # 同一条记录，前端按 id 对账。
                history[index] = message
                break
        else:
            history.append(message)
        if self.store is not None:
            self.store.save_message(message)
        # 消息持久化后逐个调用监听器（VoiceRuntime TTS 入口）
        for listener in self._message_listeners:
            listener(message)
        # 消息产生即推送，UI 增量渲染不等整轮任务结束
        if self.on_message is not None:
            self.on_message(message)
        return message

    def _recent_user_messages(self, conversation_id: str) -> list[Message]:
        """返回当前聊天中真实用户输入的最后三条消息。

        角色委派在工作台写入的 origin=character_delegation 镜像消息不是
        用户直接输入，不进入审查上下文。
        """
        return [
            message
            for message in self._history.get(conversation_id, [])
            if message.source == MessageSource.USER
            and message.origin != MessageOrigin.CHARACTER_DELEGATION
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
        """把角色对话增量事件转发给桌面桥。

        聊天模式也照常转发思考与正文 delta；委派等结构信息等
        character.final 解析。首个事件为这条角色回复预留时间线序号，
        流式占位与最终消息共用。
        """
        speech_id = f"speech:{conversation_id}:{user_message.message_id}"
        order = self._speech_orders.get(speech_id)
        if order is None:
            existing = next(
                (m for m in self._history.get(conversation_id, ()) if m.message_id == speech_id),
                None,
            )
            order = (
                existing.timeline_order
                if existing is not None
                else self._next_timeline_order(conversation_id)
            )
            self._speech_orders[speech_id] = order
        if self.on_dialogue_event is not None:
            self.on_dialogue_event(conversation_id, user_message, event, order)

    def _forward_review_event(
        self, event: str, payload: dict, *, conversation_id: str
    ) -> None:
        """把 ApprovalManager 的审查生命周期事件转发给桌面桥。

        conversation_id 在任务开始时捕获，不读取切换后的当前聊天。
        """
        if self.on_review_event is not None:
            self.on_review_event(event, {**payload, "conversation_id": conversation_id})

    async def handle_character_input(
        self,
        *,
        conversation_id: str,
        text: str,
        context: ExecutionContext,
    ) -> ConversationOutcome:
        """完整角色回合入口（CLI 使用）：落库用户消息后处理角色回合。"""
        user = await self.submit_user_message(
            conversation_id=conversation_id,
            text=text,
            target="character",
            pair_id=context.pair_id,
        )
        return await self.process_character_turn(
            conversation_id=conversation_id, user_message=user, context=context
        )

    async def submit_user_message(
        self,
        *,
        conversation_id: str,
        text: str,
        target: str,
        pair_id: str,
    ) -> Message:
        """同步落库用户消息并立即返回真实 id。

        只负责保存与发出 ``message.created``；回合处理由调用方随后在后台
        启动。断线或重启后可从快照恢复，处理失败后文字仍在且可重试。
        """
        target_value = MessageTarget(target)
        async with self._conversation_lock(conversation_id):
            return self._message(
                conversation_id=conversation_id,
                source=MessageSource.USER,
                kind=MessageKind.USER_TEXT,
                text=text,
                pair_id=pair_id,
                target=target_value,
                origin=MessageOrigin.USER,
            )

    async def process_character_turn(
        self,
        *,
        conversation_id: str,
        user_message: Message,
        context: ExecutionContext,
    ) -> ConversationOutcome:
        """在后台运行角色回合（用户消息已落库）。

        角色台词在会话锁内串行产生；委派处理（任务执行与修改路由）在锁外
        进行。``context`` 是提交时解析的不可变执行上下文，聊天模式下角色
        输出的 delegation 一律不执行。
        """
        exec_context = context
        self._conversation_pairs[conversation_id] = exec_context.pair_id
        async with self._conversation_lock(conversation_id):
            # 任务执行期间注入压缩进度摘要；任务结束后 _progress 已清理，
            # 聊天轮回到纯角色对话。
            progress = self._progress.get(conversation_id)
            progress_summary = None
            if progress is not None:
                progress_summary = CharacterProgressSummary(
                    current_step=progress.current_step,
                    completed_steps=progress.completed_steps,
                )
            # 当前用户消息由 user_message 承载，按 id 从上下文窗口排除。
            request = self._dialogue_request(
                conversation_id=conversation_id,
                user_message=user_message,
                pair_id=exec_context.pair_id,
                runtime_context=self._build_runtime_context(exec_context),
                turn_index=self._turn_index_for(
                    conversation_id, user_message.message_id
                ),
                exclude_message_id=user_message.message_id,
                progress_summary=progress_summary,
            )
            character_turn = None
            async for event in self.dialogue_model.stream_reply(request):
                # 增量事件先转发（思考与正文 delta），UI 流式显示
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
                pair_id=exec_context.pair_id,
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

        # 聊天模式是角色能力边界：后端按提交时的对话模式一律不执行委派，
        # 不依赖按钮禁用或角色提示词。
        if exec_context.conversation_mode == "chat" and character_turn.delegation is not None:
            notice = self._message(
                conversation_id=conversation_id,
                source=MessageSource.SYSTEM,
                kind=MessageKind.SYSTEM_STATUS,
                text="当前是聊天模式，角色不能读取或操作项目。切换协作模式后再让它处理项目任务。",
                pair_id=exec_context.pair_id,
            )
            return ConversationOutcome(
                messages=tuple((*messages, notice)),
                memory_drafts=tuple(character_turn.memory),
            )

        if character_turn.delegation_missed:
            # 模型自报 delegate=true 却没有返回结构化 delegation 是协议违规，
            # 如实暴露给用户与日志，不重试也不替模型补全委派。
            logger.warning(
                "角色自报委派但没有返回结构化 delegation（conversation=%s message=%s）",
                conversation_id,
                user_message.message_id,
            )
            notice = self._message(
                conversation_id=conversation_id,
                source=MessageSource.SYSTEM,
                kind=MessageKind.SYSTEM_STATUS,
                text="角色声明要委派，但没有返回结构化委派，本次没有任务交给助手执行。",
                pair_id=exec_context.pair_id,
            )
            return ConversationOutcome(
                messages=tuple((*messages, notice)),
                memory_drafts=tuple(character_turn.memory),
            )

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
                    context=exec_context,
                )
            except BusyTurnError as exc:
                # 任务运行中角色再委派新任务：冲突转为用户可见的系统提示。
                # 用户直接指令走修改路由，不受影响。
                notice = self._message(
                    conversation_id=conversation_id,
                    source=MessageSource.SYSTEM,
                    kind=MessageKind.SYSTEM_STATUS,
                    text=f"任务仍在执行，本次委派暂未受理：{exc}",
                    pair_id=exec_context.pair_id,
                )
                return ConversationOutcome(
                    messages=(user_message, character, notice),
                    memory_drafts=tuple(character_turn.memory),
                )
            messages.extend(execution.messages)
            return ConversationOutcome(
                messages=tuple(messages),
                memory_drafts=tuple(character_turn.memory),
                engine_events=execution.engine_events,
                tool_runs=execution.tool_runs,
                task=task,
                receipt=execution.receipt,
            )

        if isinstance(character_turn.delegation, TaskAmendmentDraft):
            draft = character_turn.delegation
            active = self.state.get_for_conversation(conversation_id)
            blocker = self._amendment_blocker(active, draft.target_task_id)
            if blocker is not None:
                notice = self._message(
                    conversation_id=conversation_id,
                    source=MessageSource.SYSTEM,
                    kind=MessageKind.SYSTEM_STATUS,
                    text=f"修改未能应用：{blocker}",
                    pair_id=exec_context.pair_id,
                )
                return ConversationOutcome(
                    messages=(user_message, character, notice),
                    memory_drafts=tuple(character_turn.memory),
                )
            await self._steer_turn(
                active,
                TaskAmendment(
                    target_task_id=active.task_id,
                    origin_message_id=user_message.message_id,
                    revision=draft.revision or 1,
                    instructions=draft.instructions,
                    # 角色建议的修改，来源与用户直接指令区分
                    origin="character",
                ),
            )
        return ConversationOutcome(
            messages=tuple(messages),
            memory_drafts=tuple(character_turn.memory),
        )

    async def process_direct_input(
        self,
        *,
        conversation_id: str,
        user_message: Message,
        context: ExecutionContext,
    ) -> ConversationOutcome:
        """后台处理直发助手的用户消息（消息已落库）。

        本聊天无活动任务时新建任务执行；有活动任务时把消息作为
        TaskAmendment 发给运行中的引擎 turn。并发按聊天划分，其他聊天
        是否忙碌不影响本聊天。
        """
        exec_context = context
        self._conversation_pairs[conversation_id] = exec_context.pair_id
        active = self.state.get_for_conversation(conversation_id)
        if active is not None:
            # 运行中直接发给助手的新指令归一为 TaskAmendment 走 amend_turn，
            # 来源标记 user 与角色建议区分
            blocker = self._amendment_blocker(active, None)
            if blocker is not None:
                notice = self._message(
                    conversation_id=conversation_id,
                    source=MessageSource.SYSTEM,
                    kind=MessageKind.SYSTEM_STATUS,
                    text=f"修改未能应用：{blocker}",
                    pair_id=exec_context.pair_id,
                )
                return ConversationOutcome(messages=(user_message, notice))
            await self._steer_turn(
                active,
                TaskAmendment(
                    target_task_id=active.task_id,
                    origin_message_id=user_message.message_id,
                    revision=1,
                    instructions=user_message.text,
                    origin="user",
                ),
            )
            # 修改已交给运行中的任务，本次直接输入不再开启新任务
            return ConversationOutcome(messages=(user_message,))
        task = TaskRequest(
            conversation_id=conversation_id,
            origin_message_id=user_message.message_id,
            instructions=user_message.text,
        )
        execution = await self._execute(task, context=exec_context)
        return ConversationOutcome(
            messages=(user_message, *execution.messages),
            engine_events=execution.engine_events,
            tool_runs=execution.tool_runs,
            task=task,
            receipt=execution.receipt,
        )

    def _amendment_blocker(
        self, active: ActiveTurn | None, target_task_id: str | None
    ) -> str | None:
        """活动任务暂时不能接收修改的原因；可以接收时返回 None。"""
        if active is None:
            return "当前聊天没有运行中的助手任务"
        if active.engine_turn_id is None:
            return "助手任务还在启动，请稍后再发"
        if self._active_lifecycles[active.task_id].status != TaskStatus.RUNNING:
            return "助手任务正在取消"
        if target_task_id is not None and target_task_id != active.task_id:
            return f"指定的任务 {target_task_id} 不是运行中的任务"
        return None

    async def _steer_turn(self, active: ActiveTurn, amendment: TaskAmendment) -> None:
        """把 amendment 发给运行中的引擎 turn，引擎错误原样上抛。

        角色建议与用户直接指令共用此路径；调用方先用
        ``_amendment_blocker`` 确认任务可以接收修改。
        """
        await self.coding_engine.amend_turn(
            self._sessions[active.conversation_id], active.engine_turn_id, amendment
        )

    async def cancel_active_task(
        self, conversation_id: str, task_id: str | None = None
    ) -> bool:
        """定向取消聊天的活动任务。

        传入 ``task_id`` 时还要求它就是该聊天的活动任务，用户切换聊天后
        旧按钮不得取消新任务。引擎 turn 尚未绑定时记录取消意图，绑定后由
        事件循环立即发送 interrupt；已绑定则直接发送。无活动任务或生命
        周期已离开运行态时返回 False。
        """
        active = self.state.get_for_conversation(conversation_id)
        if active is None or (task_id is not None and active.task_id != task_id):
            return False
        lifecycle = self._active_lifecycles[active.task_id]
        if lifecycle.status != TaskStatus.RUNNING:
            return False
        lifecycle.transition(TaskStatus.CANCELLED)
        if active.engine_turn_id is None:
            self.state.request_cancel(active.task_id)
            return True
        await self.coding_engine.cancel_turn(
            self._sessions[conversation_id], active.engine_turn_id
        )
        return True

    async def _execute(
        self,
        task: TaskRequest,
        *,
        context: ExecutionContext,
        delegation_id: str | None = None,
        origin: MessageOrigin | None = None,
        delegation_retry_depth: int = 0,
    ) -> ConversationOutcome:
        """执行一次助手任务；任务失败且角色在结果轮重新委派时再执行一次。

        角色在失败结果轮返回 ``delegation.type=task`` 即表示立即重试。最多
        再执行一次；再次失败后角色的新委派不再执行，并留下可见系统提示。
        ``delegation_retry_depth`` 是当前调用链的局部计数，递归时显式 +1。
        """
        execution = await self._execute_once(
            task, delegation_id=delegation_id, origin=origin, context=context
        )
        retry_draft = execution.retry_delegation
        if retry_draft is None:
            return execution
        if delegation_retry_depth >= 1:
            notice = self._message(
                conversation_id=task.conversation_id,
                source=MessageSource.SYSTEM,
                kind=MessageKind.SYSTEM_STATUS,
                text="已自动重试一次仍未成功，角色的再次委派没有执行。",
                pair_id=context.pair_id,
            )
            return ConversationOutcome(
                messages=(*execution.messages, notice),
                engine_events=execution.engine_events,
                tool_runs=execution.tool_runs,
                task=execution.task,
                receipt=execution.receipt,
            )
        retry_task = TaskRequest(
            conversation_id=task.conversation_id,
            origin_message_id=task.origin_message_id,
            instructions=retry_draft.instructions,
            constraints=retry_draft.constraints,
        )
        retry_execution = await self._execute(
            retry_task,
            delegation_id=retry_task.task_id,
            origin=origin,
            delegation_retry_depth=delegation_retry_depth + 1,
            context=context,
        )
        return ConversationOutcome(
            messages=(*execution.messages, *retry_execution.messages),
            engine_events=(*execution.engine_events, *retry_execution.engine_events),
            tool_runs=(*execution.tool_runs, *retry_execution.tool_runs),
            task=retry_execution.task,
            receipt=retry_execution.receipt,
        )

    async def _execute_once(
        self,
        task: TaskRequest,
        *,
        context: ExecutionContext,
        delegation_id: str | None = None,
        origin: MessageOrigin | None = None,
    ) -> ConversationOutcome:
        """单次任务执行（不含失败重试路由）。

        ``delegation_id`` 与 ``origin`` 标记任务消息归属：角色委派产生的
        执行记录 origin=character_delegation 且带 delegation_id，直发助手
        的执行记录保持 user 来源。两类记录都归入工作台，委派卡通过
        delegation_id 连接角色区与工作台。
        """
        exec_context = context
        task_project = exec_context.project
        task_pair_id = exec_context.pair_id
        task_approval_mode = exec_context.approval_mode
        task_assistant_instructions = exec_context.assistant_instructions
        task_delegation_id = delegation_id or task.task_id
        state_started = False
        try:
            active_turn = self.state.start(
                project_id=task_project.project_id,
                conversation_id=task.conversation_id,
                task_id=task.task_id,
            )
            state_started = True
            if self.on_execution_started is not None:
                self.on_execution_started(active_turn)
            lifecycle = TaskLifecycle(task_id=task.task_id)
            lifecycle.transition(TaskStatus.RUNNING)
            self._active_lifecycles[task.task_id] = lifecycle
            events: list[EngineEvent] = []
            assistant_text = ""
            tool_runs: dict[str, ToolRun] = {}
            failed = False
            cancelled = False
            terminal_status: ReceiptStatus | None = None
            errors: list[str] = []
            changed_files: list[str] = []
            checks: list[str] = []
            engine_turn_id = "unavailable"
            sequence = 0
            # 本任务的 segment 累加器与工具时间线序号
            segment_state = _SegmentState()
            tool_orders: dict[str, int] = {}
            # 本次执行产生的新消息（含沙箱与审批 system 卡片）从这里开始
            history_start = len(self._history.get(task.conversation_id, []))
            sandbox = ProjectSandbox(Path(task_project.root_path))
            approval = self._approval_managers.get(task.conversation_id)
            if approval is None:
                approval = ApprovalManager(
                    mode=task_approval_mode,
                    rules=self.risk_rules,
                    on_review=partial(
                        self._forward_review_event,
                        conversation_id=task.conversation_id,
                    ),
                )
                self._approval_managers[task.conversation_id] = approval
            approval.mode = task_approval_mode
            approval.reviewer = self.reviewer
            # 执行期间的活动任务进度（事件驱动更新，结束时清理）
            progress = self._progress.setdefault(task.conversation_id, _TaskProgress())
            if origin == MessageOrigin.CHARACTER_DELEGATION:
                # 角色委派被接受时先写入工作台任务消息，作为委派的起始记录；
                # 后续执行成功或失败都关联到同一个 delegation_id。
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
        except BaseException:
            if state_started:
                self._progress.pop(task.conversation_id, None)
                self.state.finish(task.task_id)
                self._active_lifecycles.pop(task.task_id, None)
                if self.on_execution_finished is not None:
                    self.on_execution_finished(active_turn)
            raise
        try:
            session = self._sessions.get(task.conversation_id)
            session = await self.coding_engine.open_session(
                task_project,
                session,
                approval_mode=task_approval_mode,
                developer_instructions=task_assistant_instructions or None,
            )
            self._sessions[task.conversation_id] = session
            if self.store is not None:
                self.store.save_engine_session(task.conversation_id, session)

            async with aclosing(self.coding_engine.run_turn(session, task)) as turn_stream:
                async for raw_event in turn_stream:
                    # 事件序号由这里统一分配；合成事件（否决、resolved）经
                    # 同一计数器分配，出口事件流序号连续，不使用适配器自带序号。
                    event = raw_event.model_copy(
                        update={
                            "conversation_id": task.conversation_id,
                            "task_id": task.task_id,
                            "sequence": sequence,
                        }
                    )
                    sequence += 1
                    engine_turn_id = event.engine_turn_id
                    active_turn = self.state.get_for_task(task.task_id)
                    if active_turn.engine_turn_id is None:
                        self.state.bind_engine_turn(task.task_id, engine_turn_id)
                    if self.state.get_for_task(task.task_id).cancellation_requested:
                        # 取消意图在引擎 turn id 绑定后立即发送 interrupt
                        await self.coding_engine.cancel_turn(session, engine_turn_id)
                        self.state.mark_cancel_sent(task.task_id)

                    # 推送前完成分段与时间线信息：delta 打开当前 segment；
                    # tool.started 或首次观察到的工具定稿当前段，工具事件
                    # 首次观察即分配工作台序号，同一 tool_call_id 沿用原序号
                    # 并写进每个工具事件的 payload；审批请求记录决策方。
                    if event.type in (
                        EngineEventType.ASSISTANT_DELTA,
                        EngineEventType.ASSISTANT_REASONING_DELTA,
                    ):
                        if not segment_state.is_open():
                            segment_state.index = segment_state.finalized_count
                            segment_state.order = self._next_timeline_order(
                                task.conversation_id
                            )
                        payload = dict(event.payload)
                        payload["segment_index"] = segment_state.index
                        payload["timeline_order"] = segment_state.order
                        payload["message_id"] = (
                            f"assistant:{task.conversation_id}:{task.task_id}:"
                            f"{segment_state.index}"
                        )
                        event = event.model_copy(update={"payload": payload})
                    elif event.type in (
                        EngineEventType.TOOL_STARTED,
                        EngineEventType.TOOL_PROGRESS,
                        EngineEventType.TOOL_FINISHED,
                    ):
                        first_seen = (
                            event.tool_call_id is not None
                            and event.tool_call_id not in tool_orders
                        )
                        if event.type == EngineEventType.TOOL_STARTED or first_seen:
                            self._finalize_segment(
                                segment_state,
                                conversation_id=task.conversation_id,
                                task_id=task.task_id,
                                engine_turn_id=engine_turn_id,
                                pair_id=task_pair_id,
                                delegation_id=task_delegation_id,
                                origin=origin,
                            )
                        if first_seen:
                            tool_orders[event.tool_call_id] = self._next_timeline_order(
                                task.conversation_id
                            )
                        payload = dict(event.payload)
                        payload["timeline_order"] = tool_orders.get(event.tool_call_id)
                        event = event.model_copy(update={"payload": payload})
                    elif event.type == EngineEventType.APPROVAL_REQUESTED:
                        payload = dict(event.payload)
                        payload.setdefault(
                            "actor",
                            "reviewer"
                            if approval.mode == ApprovalMode.REVIEW
                            else "user",
                        )
                        event = event.model_copy(update={"payload": payload})

                    # 事件到达即推送并入列：tool.started 先于审批与沙箱结果
                    # 到达 UI，运行中的工具卡片立即出现；出口列表与推送顺序一致。
                    self._emit_event(event)
                    events.append(event)

                    if event.type == EngineEventType.APPROVAL_REQUESTED:
                        # 引擎在工具执行前挂起请求：先做沙箱检查（越界直接
                        # 否决），再由 ApprovalManager 裁决，结果经
                        # resolve_approval 回复引擎。
                        op = self._operation_from_approval_event(event)
                        approval_id = str(event.payload.get("approval_id") or "")
                        try:
                            self._check_sandbox(sandbox, op.paths)
                        except SandboxViolation as exc:
                            # 挂起中的越界操作直接否决，引擎不会执行
                            await self.coding_engine.resolve_approval(
                                session, approval_id, ApprovalDecision.DENY
                            )
                            sequence = self._deny_tool(
                                event,
                                deny_reason=f"沙箱拦截：{exc}",
                                message_text=self._sandbox_denial_text(exc),
                                sequence=sequence,
                                events=events,
                                tool_runs=tool_runs,
                                tool_orders=tool_orders,
                                pair_id=task_pair_id,
                            )
                            failed = True
                            errors.append(str(exc))
                            continue
                        outcome = await approval.adjudicate(
                            op,
                            requested_event=event,
                            context=self._recent_user_messages(task.conversation_id),
                            request_decision=partial(
                                self._request_approval,
                                conversation_id=task.conversation_id,
                                task_id=task.task_id,
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
                            # 被用户或审查否决时落 denied 工具记录，保留裁决理由。
                            resolved = outcome.events[-1].payload
                            deny_reason = str(
                                resolved["resolution_reason"] or resolved["request_reason"]
                            )
                            sequence = self._deny_tool(
                                event,
                                deny_reason=deny_reason,
                                message_text=deny_reason,
                                sequence=sequence,
                                events=events,
                                tool_runs=tool_runs,
                                tool_orders=tool_orders,
                                pair_id=task_pair_id,
                            )
                        # 裁决经 resolve_approval 回复引擎；被否决时不中断
                        # 执行循环，引擎把拒绝反馈给模型后继续 turn，任务成败
                        # 由 turn 终态决定。
                        await self.coding_engine.resolve_approval(
                            session, approval_id, outcome.decision
                        )

                    elif event.type == EngineEventType.TOOL_STARTED:
                        # 当前步骤用中性标签，不泄露命令与路径原文
                        progress.current_step = self._step_label(event)
                        try:
                            self._check_sandbox(sandbox, self._tool_paths(event))
                        except SandboxViolation as exc:
                            sequence = self._deny_tool(
                                event,
                                deny_reason=str(exc),
                                message_text=self._sandbox_denial_text(exc),
                                sequence=sequence,
                                events=events,
                                tool_runs=tool_runs,
                                tool_orders=tool_orders,
                                pair_id=task_pair_id,
                            )
                            failed = True
                            errors.append(str(exc))
                            break

                    elif event.type == EngineEventType.ASSISTANT_FINAL:
                        assistant_text = str(event.payload.get("text", ""))
                        if assistant_text.strip() and not segment_state.is_open():
                            # 只发 final、没有流式 delta 时，final 自身构成一个 segment
                            segment_state.index = segment_state.finalized_count
                            segment_state.order = self._next_timeline_order(
                                task.conversation_id
                            )
                        # final 完整正文覆盖当前段的流式累积
                        segment_state.final_override = assistant_text
                        progress.current_step = "助手整理结果"
                    elif event.type == EngineEventType.ASSISTANT_REASONING_DELTA:
                        text = str(event.payload.get("text", ""))
                        if event.payload.get("channel") == "content":
                            segment_state.reasoning_content.append(text)
                        else:
                            segment_state.reasoning_summary.append(text)
                    elif event.type == EngineEventType.ASSISTANT_DELTA:
                        segment_state.text_parts.append(str(event.payload.get("text", "")))
                    elif event.type == EngineEventType.FILE_PATCH:
                        path = event.payload.get("path")
                        if path:
                            # 同一文件多次 patch 只记一次（保持首次出现顺序）
                            text = str(path)
                            if text not in changed_files:
                                changed_files.append(text)
                    elif event.type == EngineEventType.TOOL_FINISHED:
                        status = cast(ToolRunStatus, str(event.payload["status"]))
                        if status == "failed":
                            # 单个工具步骤失败不等于整个 turn 失败：引擎可能会
                            # 重试、改用其他路径，最后正常完成。保留错误明细，
                            # 但让真实的 turn.failed / turn.completed 终态决定
                            # 任务回执状态。
                            if event.payload.get("error"):
                                errors.append(str(event.payload["error"]))
                        if event.payload.get("check"):
                            checks.append(str(event.payload["check"]))
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
                                timeline_order=tool_orders.get(event.tool_call_id),
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

            # 任务结束定稿最后一个尚未定稿的 segment（正常、失败、取消路径
            # 都只收尾本任务自己的段落）。final 未到达时，段内已累积的 delta
            # 文本就是该段最终正文。
            final_segment_text = self._finalize_segment(
                segment_state,
                conversation_id=task.conversation_id,
                task_id=task.task_id,
                engine_turn_id=engine_turn_id,
                pair_id=task_pair_id,
                delegation_id=task_delegation_id,
                origin=origin,
            )
            if not assistant_text.strip() and final_segment_text:
                assistant_text = final_segment_text

            # 生命周期可能已被 cancel_active_task 先行落到 CANCELLED（终态），
            # 此时回执按取消处理，且不再重复转移。
            if cancelled or lifecycle.status == TaskStatus.CANCELLED:
                target_status = "cancelled"
            elif terminal_status is not None:
                target_status = terminal_status
            elif failed:
                # 本地沙箱拦截中断了事件流
                target_status = "failed"
            else:
                raise RuntimeError(
                    "引擎事件流结束时没有 turn.completed 或 turn.failed 终态事件"
                    f"（engine_turn_id={engine_turn_id}）"
                )
            if target_status == "completed" and not failed and not assistant_text.strip():
                raise RuntimeError("助手未返回最终回复")
            if TaskStatus(target_status) != lifecycle.status:
                lifecycle.transition(TaskStatus(target_status))
            status = cast(ReceiptStatus, target_status)
            receipt = ExecutionReceipt(
                task_id=task.task_id,
                engine_turn_id=engine_turn_id,
                status=status,
                summary=assistant_text,
                changed_files=tuple(changed_files),
                checks=tuple(checks),
                errors=tuple(errors),
            )
            if self.store is not None:
                for tool_run in tool_runs.values():
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
                pair_id=task_pair_id,
                source=MessageSource.SYSTEM,
                kind=MessageKind.SYSTEM_STATUS,
                text=(
                    "本轮任务已经结束，请阅读系统消息中的任务结果，以角色身份"
                    "回应这次执行结果。结果成功或已取消就正常回应，不再发起新"
                    "委派；结果失败时，可以立即重新委派重试一次。"
                ),
            )
            # 结果轮使用与主角色轮相同的窗口、该任务所属用户回合的序号与
            # 项目运行上下文。
            dialogue_request = self._dialogue_request(
                conversation_id=task.conversation_id,
                user_message=synthetic,
                pair_id=task_pair_id,
                runtime_context=self._build_runtime_context(exec_context),
                turn_index=self._turn_index_for(
                    task.conversation_id, task.origin_message_id
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
            if result_turn.delegation_missed:
                logger.warning(
                    "角色在结果轮自报委派但没有返回结构化 delegation（conversation=%s task=%s）",
                    task.conversation_id,
                    task.task_id,
                )
                self._message(
                    conversation_id=task.conversation_id,
                    source=MessageSource.SYSTEM,
                    kind=MessageKind.SYSTEM_STATUS,
                    text="角色声明要委派，但没有返回结构化委派，本次没有任务交给助手执行。",
                    pair_id=task_pair_id,
                )
            # 失败结果轮里角色立即重新委派（delegation.type=task）时交给
            # _execute 再执行一次；成功、取消或修改草稿都不触发。
            retry_delegation = (
                result_turn.delegation
                if receipt.status == "failed"
                and isinstance(result_turn.delegation, TaskRequestDraft)
                else None
            )
            # 本次执行的全部新消息：审批 system 卡片、助手说明与角色回应
            messages = self._history.get(task.conversation_id, [])[history_start:]
            return ConversationOutcome(
                messages=tuple(messages),
                engine_events=tuple(events),
                tool_runs=tuple(tool_runs.values()),
                task=task,
                receipt=receipt,
                retry_delegation=retry_delegation,
            )
        finally:
            # 异常中断也要保留已到达的部分 segment。主异常继续传播，定稿
            # 自身的失败单独记录日志。
            if segment_state.is_open():
                try:
                    self._finalize_segment(
                        segment_state,
                        conversation_id=task.conversation_id,
                        task_id=task.task_id,
                        engine_turn_id=engine_turn_id,
                        pair_id=task_pair_id,
                        delegation_id=task_delegation_id,
                        origin=origin,
                    )
                except Exception:  # noqa: BLE001 - 只记录定稿失败，原异常照常传播
                    logger.exception(
                        "任务异常收尾时定稿助手 segment 失败（task=%s）",
                        task.task_id,
                    )
            # 任务结束清理进度，后续聊天轮不再注入摘要
            self._progress.pop(task.conversation_id, None)
            self.state.finish(task.task_id)
            self._active_lifecycles.pop(task.task_id, None)
            if self.on_execution_finished is not None:
                self.on_execution_finished(active_turn)

    def _emit_event(self, event: EngineEvent) -> None:
        """把引擎事件立即推送给 UI（流式通道）。"""
        if self.on_engine_event is not None:
            self.on_engine_event(event)

    @staticmethod
    def _step_label(event: EngineEvent) -> str:
        """工具步骤的中性标签（不含命令、路径与输出原文）。

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
    def _tool_paths(event: EngineEvent) -> list[str]:
        """工具开始事件里上报的目标路径。"""
        payload = event.payload
        return [str(p) for p in payload.get("paths", [])] or (
            [str(payload["path"])] if payload.get("path") else []
        )

    @staticmethod
    def _operation_from_approval_event(event: EngineEvent) -> PendingOperation:
        """从审批请求事件构造待裁决操作。

        适配器已把工具字段归一进 payload（tool_kind、command、paths、
        summary），这里直接透传。
        """
        payload = event.payload
        return PendingOperation(
            tool_kind=payload.get("tool_kind", "shell"),
            command=payload.get("command"),
            paths=[str(p) for p in payload.get("paths", []) or []],
            summary=str(
                payload.get("summary") or payload.get("reason") or "工具操作"
            ),
        )

    @staticmethod
    def _sandbox_denial_text(exc: SandboxViolation) -> str:
        """沙箱拒绝卡片的文案：保留真实拦截原因，并给出可操作的建议。"""
        return (
            f"沙箱拦截：{exc}。"
            "路径在绑定项目之外；把文件移入项目目录后再试，"
            "或重新选择项目路径。"
        )

    @staticmethod
    def _check_sandbox(sandbox: ProjectSandbox, paths: Iterable[str]) -> None:
        for path in paths:
            sandbox.resolve_write_path(path)

    async def _request_approval(
        self,
        op: PendingOperation,
        approval_id: str,
        reason: str,
        *,
        conversation_id: str,
        task_id: str,
    ) -> ApprovalDecision:
        return await self.approval_callback(
            op, approval_id, reason, conversation_id, task_id
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
        """裁决事件统一计数入列并推送，返回递增后的序号。

        裁决结果以 system 卡片留在消息时间线。
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

    def _deny_tool(
        self,
        event: EngineEvent,
        *,
        deny_reason: str,
        message_text: str,
        sequence: int,
        events: list[EngineEvent],
        tool_runs: dict[str, ToolRun],
        tool_orders: dict[str, int],
        pair_id: str,
    ) -> int:
        """以 denied 状态收尾被沙箱或审批拦下的工具，返回递增后的序号。

        合成 denied 的 tool.finished 事件入列推送、落 system 状态卡，并把
        ToolRun 写入 ``tool_runs``，任务结束时随其他工具记录一起持久化。
        工具还没有工作台序号时（审批请求先于 tool.started 到达）当场分配。
        """
        tool_call_id = event.tool_call_id
        order = tool_orders.get(tool_call_id) if tool_call_id else None
        if order is None:
            order = self._next_timeline_order(event.conversation_id)
            if tool_call_id:
                tool_orders[tool_call_id] = order
        title = str(event.payload.get("title", "工具"))
        denied_event = EngineEvent(
            conversation_id=event.conversation_id,
            task_id=event.task_id,
            engine_turn_id=event.engine_turn_id,
            sequence=sequence,
            type=EngineEventType.TOOL_FINISHED,
            tool_call_id=tool_call_id,
            payload={
                "status": "denied",
                "title": title,
                "summary": deny_reason,
                "details": deny_reason,
                "error": deny_reason,
                "timeline_order": order,
            },
        )
        events.append(denied_event)
        self._emit_event(denied_event)
        self._message(
            conversation_id=event.conversation_id,
            source=MessageSource.SYSTEM,
            kind=MessageKind.SYSTEM_STATUS,
            text=message_text,
            engine_turn_id=event.engine_turn_id,
            pair_id=pair_id,
        )
        if tool_call_id:
            tool_runs[tool_call_id] = ToolRun(
                tool_call_id=tool_call_id,
                conversation_id=event.conversation_id,
                task_id=event.task_id,
                engine_turn_id=event.engine_turn_id,
                sequence=sequence,
                status="denied",
                title=title,
                summary=deny_reason,
                details=deny_reason,
                timeline_order=order,
            )
        return sequence + 1

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
        """从审批裁决结果生成时间线 system 卡片文案。

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
            if payload.get("resolution_reason"):
                text += f"（{payload['resolution_reason']}）"
            if payload.get("suggestion"):
                text += f"；调整建议：{payload['suggestion']}"
            return text
        return ConversationOrchestrator._decision_text(outcome.decision)
