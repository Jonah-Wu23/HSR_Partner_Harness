from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, cast
from urllib.parse import urlsplit
from uuid import uuid4

from pair_harness.adapters.codex.auth import CodexAuthService
from pair_harness.adapters.demo import ScriptedCodingEngine, ScriptedDialogueModel
from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.adapters.reviewer import DialogueModelReviewer
from pair_harness.app_paths import AppPaths
from pair_harness.cli import load_dotenv
from pair_harness.config.pairs import (
    PAIR_CATALOG_IDS,
    PairConfig,
    list_pair_configs,
    load_pair_config,
    load_prompt,
)
from pair_harness.config.providers import detect_provider, load_reasoning_preset
from pair_harness.config.voices import (
    ANCIENT_MACHINE_PREVIEW_TEXT,
    VoiceManifestError,
    assistant_speaker_ids,
    load_reference_voice_manifest,
)
from pair_harness.character_cards.codec import (
    CardImportError,
    dump_card_v3,
    load_card_json,
    load_card_payload,
)
from pair_harness.character_cards.models import AvatarAsset, CharacterCard
from pair_harness.character_cards.png import (
    PNG_SIGNATURE,
    PngCardError,
    png_image_dimensions,
    read_png_card,
    write_png_card,
)
from pair_harness.character_cards.repository import CharacterCardRepository
from pair_harness.character_cards.assets import (
    CharacterAssetError,
    CharacterAssetService,
)
from pair_harness.character_cards.states import CharacterVoiceState
from pair_harness.core.character_prompt_assembler import (
    AssembledPrompt,
    assemble_character_prompt,
    assemble_turn_prompt,
)
from pair_harness.core.context import ExecutionContext, assert_single_assistant_markdown
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    EngineEvent,
    EngineEventType,
    Message,
    MessageKind,
    MessageOrigin,
    MessageSource,
    ProjectRef,
    PendingOperation,
    ToolRun,
    Turn,
    TurnStatus,
    utc_now,
)
from pair_harness.storage.records import (
    ConversationSummary as StorageSummary,
    MemoryScope as StorageMemoryScope,
    PairMemory as StorageMemory,
    TurnMetric,
    TurnMetricQuery,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.core.summary import (
    SUMMARY_INVALID,
    SUMMARY_PROVIDER_ERROR,
    SUMMARY_TIMEOUT,
    ConversationSummary,
    SummaryError,
    is_final_message,
    messages_after_coverage,
    require_summary_conversation,
    role_messages,
    summary_event_payload,
    summary_trigger,
    validate_summary_coverage,
)
from pair_harness.core.memory import (
    MEMORY_INVALID,
    MEMORY_NOT_FOUND,
    MEMORY_SCOPE_MISMATCH,
    ConversationIdentity,
    MemoryError,
    MemoryScope,
    PairMemory,
    active_memories,
    require_memory_found,
    require_same_scope,
    resolve_memory_scope,
)
from pair_harness.core.voice_policy import is_readable_text
from pair_harness.core.voice_runtime import VoiceRuntime
from pair_harness.settings import Settings
from pair_harness.storage.sqlite_store import SQLiteStore
from .pairing import PairingError, PairingService
from .power import PowerStatus, PowerStatusError, read_power_status
from .tunnel import TunnelManager
from pair_harness.voice_models import VOICE_ASR_MODEL, VOICE_TTS_MODEL

from .commands import DesktopCommand
from .engine_factory import build_coding_engine
from .events import EventEmitter, EventSink, to_jsonable
from .mobile_audio import (
    MobileAsrSessionManager,
    MobileAudioError,
    MobileTtsSequencer,
)
from .voice_factory import (
    build_real_voice_runtime,
    effective_pair_config,
    resolve_effective_voice_profile,
)


def _params_card_id(params: Mapping[str, Any]) -> str | None:
    """params.character_card_id 的显式值；空/缺失返回 None（走 active 快照）。"""
    value = str(params.get("character_card_id") or "").strip()
    return value or None


def _nullable_int(value: Any) -> int | None:
    """非负整数取值，否则 None（契约 §5：未观测保持 null，不用 0 顶替）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return None


def _duration_ms(started_at: str, completed_at: str) -> int | None:
    """ISO 时间差（毫秒）；任一端不可解析时保持 None。

    同一时刻差值为真实 0，不用 None 顶替。
    """
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(completed_at)
    except (TypeError, ValueError):
        return None
    duration = (end - start).total_seconds()
    if duration < 0:
        return None
    return int(duration * 1000)


def _optional_text(params: Mapping[str, Any], key: str) -> str | None:
    """params 中可选的字符串；空串/缺失返回 None。"""
    value = params.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_datetime(params: Mapping[str, Any], key: str) -> Any:
    """params 中可选的 ISO 时间字符串；不可解析抛 ValueError（由调用方转业务错误码）。"""
    value = _optional_text(params, key)
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _diagnostics_label(value: Any) -> str:
    """诊断值转单行显示文本（列表/对象逐项展开；只做展示包装不改写含义）。"""
    if isinstance(value, (list, tuple)):
        return ", ".join(_diagnostics_label(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}={_diagnostics_label(v)}" for k, v in value.items())
    if value is None:
        return "无数据"
    return str(value)


def _failure_reason(exc: BaseException) -> str:
    """失败原因文本（V039-S4-015 回合路径 / V039-R2-001 探测路径）。

    只拼装真实可得的信息：异常自述优先；自述为空时回落到类型名与结构化
    code/category。异常自述为空（例如无参异常、只带结构化字段的异常，
    或自述为空串的 httpx.ConnectError）时原先会产出「本次回复失败：」
    「连接失败：」这样的空壳提示，用户无从定位；这里不编造任何未观测到
    的原因。
    """
    text = str(exc).strip()
    if text:
        return text
    parts = [type(exc).__name__]
    for attribute in ("code", "category"):
        value = getattr(exc, attribute, None)
        if isinstance(value, str) and value.strip():
            parts.append(f"{attribute}={value.strip()}")
    return " | ".join(parts)


def _assembly_empty_label(reason: str, card_id: str | None) -> str:
    """装配诊断为空的真实原因（V039-S4-011：区分未绑定与空装配）。"""
    if reason == "character_card_unbound":
        return "未绑定角色卡：会话未选择角色卡，无装配模块"
    if reason == "character_card_archived":
        return f"角色卡已归档：{card_id}，无装配模块"
    if reason == "character_card_missing":
        return f"角色卡不存在：{card_id}，无装配模块"
    return "已绑定角色卡但装配结果为空：无模块进入提示词"


def _speaker_label(message: Any) -> str:
    """消息展示标签（摘要输入用；只用于上下文呈现，不做语义改写）。"""
    source = getattr(message, "source", None)
    if source is None:
        source = str((message or {}).get("source", ""))
    return "用户" if str(source) == "user" else "角色"


def _message_index(messages: tuple, message_id: str) -> int | None:
    """按 message_id 找消息下标；不存在返回 None（真实失败由调用方处理）。"""
    for index, message in enumerate(messages):
        if message.message_id == message_id:
            return index
    return None


def _window_for_record(messages: tuple, record: Any) -> tuple:
    """摘要记录的 covers 区间在 messages 中的消息窗口（role 消息）。

    区间端点必须是最终落库的真实消息；端点不存在返回空元组（调用方按
    真实失败处理），不猜测、不回退。
    """
    start = _message_index(messages, record.covers_from_message_id)
    end = _message_index(messages, record.covers_to_message_id)
    if start is None or end is None or start > end:
        return ()
    return tuple(messages[start : end + 1])


def _running_summary_record(
    *,
    conversation_id: str,
    summary_id: str,
    messages: tuple,
    covered_to_message_id: str | None,
    trigger: Any,
) -> Any:
    """自动压缩的 running 起点记录：区间=触发时刻的未压缩 role 消息。

    契约 §2：covers_* 必须指向真实已落库消息；触发时消息数为 0 或区间
    异常时按 summary_invalid 失败（调用方落库前校验）。
    """
    pending = role_messages(
        messages_after_coverage(messages, covered_to_message_id)
    )
    if not pending:
        raise SummaryError("没有可摘要的新消息", code=SUMMARY_INVALID)
    covers_from = pending[0].message_id
    covers_to = pending[-1].message_id
    return StorageSummary(
        summary_id=summary_id,
        conversation_id=conversation_id,
        covers_from_message_id=covers_from,
        covers_to_message_id=covers_to,
        covers_message_count=len(pending),
        content="",
        status="running",
    )



def _iso_timestamp(value: Any) -> Any:
    """storage 记录的时间戳 → 协议载荷文本。

    契约 §5：只读查询必须可序列化；记录层持有 datetime，协议层统一为
    ISO 8601 文本（与其余载荷一致）。未观测字段保持 null，不伪造时间。
    """
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _summary_payload(summary: Any) -> dict:
    """storage 层摘要记录 → 协议载荷（content 为 JSON 文本，解析回对象）。"""
    content = getattr(summary, "content", "") or ""
    parsed: Any = None
    if isinstance(content, str) and content.strip():
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = None
    elif isinstance(content, Mapping):
        parsed = dict(content)
    return {
        "summary_id": summary.summary_id,
        "conversation_id": summary.conversation_id,
        "status": summary.status,
        "covers_from_message_id": summary.covers_from_message_id,
        "covers_to_message_id": summary.covers_to_message_id,
        "covers_message_count": summary.covers_message_count,
        "content": parsed,
        "provider": summary.provider,
        "model": summary.model,
        "error_code": summary.error_code,
        "error": summary.error,
        "created_at": _iso_timestamp(summary.created_at),
        "updated_at": _iso_timestamp(summary.updated_at),
    }


def _summary_content_text(content: Any) -> str:
    """模型返回的 JSON 对象 → 存储层 content 文本（JSON 序列化，不改写内容）。"""
    try:
        return json.dumps(dict(content), ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return ""


def _json_text(content: Any) -> str:
    """任意 JSON 对象 → 紧凑文本（存储层 content 字段用）。"""
    return json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _memory_payload(memory: Any, *, conversation_id: str | None = None) -> dict:
    """storage 层 PairMemory（扁平分量）→ 协议载荷（content 解析回对象）。

    契约 §2：事件携带五元组作用域；content 由模型负责，代码不改写。
    """
    scope = memory.scope()
    payload: dict[str, Any] = {
        "memory_id": memory.memory_id,
        "account_id": scope.account_id,
        "project_id": scope.project_id,
        "pair_id": scope.pair_id,
        "character_ref": scope.character_ref,
        "assistant_identity": scope.assistant_identity,
        "status": getattr(memory, "status", None),
        "updated_at": _iso_timestamp(memory.updated_at),
        "content": _json_load(memory.content),
    }
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    return payload


def _core_memory(memory: Any) -> PairMemory:
    """storage 层 PairMemory（扁平分量）→ core 装配用 ``PairMemory``。

    作用域五分量与 core 同构（契约 §1）；``content`` 落库时是 JSON 对象
    文本，解析回对象后交给 core 校验——形状不符如实失败，不静默跳过。
    """
    return PairMemory(
        memory_id=memory.memory_id,
        scope=MemoryScope(
            account_id=memory.account_id,
            project_id=memory.project_id,
            pair_id=memory.pair_id,
            character_ref=memory.character_ref,
            assistant_identity=memory.assistant_identity,
        ),
        content=_json_load(memory.content),
        status=memory.status,
        updated_at=memory.updated_at,
    )


def _json_load(text: str) -> Any:
    """JSON 文本 → 对象；解析失败按 None（不伪造结构）。"""
    if isinstance(text, str) and text.strip():
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    return text




logger = logging.getLogger(__name__)

# V0.3.8 T4（C4）：审批等待上限，与 codex 引擎 idle 看门狗同量级。审批发出
# 后长时间无人裁决（如手机退后台）必须如实失败并释放 busy/队列，不允许
# 任务无限期挂在 await future 上（生成器暂停在 yield 时看门狗触发不到）。
APPROVAL_TIMEOUT_S = 600.0

# V0.3.9 契约 §6：timeout 是服务端专属终态——只能由 broker 在等待超时后
# 产生，客户端提交 decision="timeout" 一律按 invalid_decision 拒绝。
APPROVAL_TIMEOUT_DECISION = "timeout"

# V0.3.9 契约 §6：远程控制租约按 device_key 独立记录。TTL 45s（持有者每
# 15s 心跳续租，3 次容错）；断连后额外宽限 15s（重连窗口），最晚 60s 回收。
CONTROL_LEASE_TTL_S = 45.0
CONTROL_LEASE_GRACE_S = 15.0
CONTROL_LEASE_SWEEP_INTERVAL_S = 5.0

# V0.3.8 T4（契约 §14.1）：回合终态集合（协议无 interrupted）。到达任一
# 终态后队列立即派发下一条；排队项不回退 queued，避免失败项无限自动重试。
_TURN_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

# V039-S4-016：共享起播守卫的三个方法——调用方身份（desktop/remote）参与判定。
_PLAYBACK_START_METHODS = frozenset(
    {"voice.tts_play", "voice.preview", "voice.card_preview"}
)

# B-03（V0.3.9）：产品只支持 OpenAI Chat Completions 兼容端点，编程助手引擎
# 只有 reasonix acp 一条路径。Codex/Responses 装配与 OpenAI OAuth 登录已从产品
# 路径移除；历史账号里可能仍保存着旧选择，读取一律如实报出并标注不受支持，
# 不静默改写成别的供应商、也不把请求发到不对应的端点。
PROGRAM_ENGINE = "reasonix"
SUPPORTED_DIALOGUE_PROVIDERS = frozenset({"deepseek", "openai_compatible"})
PROVIDER_UNAVAILABLE_CODE = "provider_unavailable"
CODEX_LOGIN_REMOVED_CODE = "codex_login_removed"


def _provider_unavailable(provider: str) -> dict[str, str] | None:
    """不受支持的供应商（当前只有历史 OpenAI OAuth）→ 可定位原因；支持则 None。"""
    if provider in SUPPORTED_DIALOGUE_PROVIDERS:
        return None
    return {
        "code": PROVIDER_UNAVAILABLE_CODE,
        "message": (
            f"供应商 {provider} 已不受支持：产品只支持 OpenAI Chat Completions "
            "兼容端点（OpenAI OAuth / Codex 登录已移除）。请在设置里重新选择"
            "供应商并保存 Base URL、模型与 API Key。"
        ),
    }


CODEX_LOGIN_REMOVED_MESSAGE = (
    "OpenAI OAuth / Codex 登录已从产品移除：产品只支持 OpenAI Chat "
    "Completions 兼容端点。请在设置里选择供应商并保存 Base URL、模型与 "
    "API Key（对话与编程助手共用同一份端点配置）。"
)


def _legacy_engine_notice(stored_engine: str) -> dict[str, str] | None:
    """历史账号里保存的 engine 值（如 PAIR_HARNESS_ENGINE/旧 config.set 写入）。

    该值不再决定装配：引擎由 dialogue.provider 推导且只有 reasonix acp。
    这里给出可定位提示，不静默改写用户已保存的配置。
    """
    if not stored_engine or stored_engine.casefold() == PROGRAM_ENGINE:
        return None
    return {
        "code": "engine_removed",
        "message": (
            f"账号配置里保存的 engine={stored_engine} 已不再生效：编程助手"
            f"统一走 {PROGRAM_ENGINE}（reasonix acp）。实际使用的端点仍取决于"
            " dialogue.provider / dialogue.base_url；重新保存一次供应商配置即可"
            "更新该字段。"
        ),
    }


class ServiceError(RuntimeError):
    """可直接返回给前端的业务错误。

    ``details``（V0.3.5）可选携带结构化附加字段，随错误响应体的
    ``error.details`` 下发；不改变 code/message 语义，前端可选读取。
    """

    def __init__(
        self, message: str, *, code: str = "service_error", details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ApprovalBroker:
    """把 Orchestrator 的异步审批等待桥接成桌面事件与命令。

    V0.3.2 M4：``request`` 显式接收 conversation_id 与 task_id（由编排器
    从执行上下文捕获），不再通过全局当前任务反查归属。
    V0.3.9 契约 §6：全部终态（allow/allow_for_conversation/deny/timeout）
    统一走 :meth:`_finish`——首个终态获胜，approval.resolved 字段齐全，
    缺失保持 null，不伪造 desktop/remote 来源。
    """

    _RESOLVED_CAPACITY = 256

    def __init__(self, emitter: EventEmitter) -> None:
        self._emitter = emitter
        self._pending: dict[str, dict[str, Any]] = {}
        # V0.3.5：已决审批的短时结果记录——双端并发应答同一审批时，后到者
        # 收到 approval_already_resolved 与先到者的真实结果，双端状态收敛
        # （docs/plans/V0.3.5-契约冻结.md §6）。容量有界，防长会话累积。
        # V0.3.9：记录携带全部终态字段与 emitted 标记（首个终态只广播一次）。
        self._resolved: dict[str, dict[str, Any]] = {}

    @property
    def pending(self) -> dict[str, dict[str, Any]]:
        return self._pending

    def resolution(self, approval_id: str) -> dict[str, Any] | None:
        """已决终态记录（未决或未知返回 None）。"""
        return self._resolved.get(approval_id)

    def mark_emitted(self, approval_id: str) -> None:
        """标记该终态的 approval.resolved 已广播（引擎路径去重用）。"""
        record = self._resolved.get(approval_id)
        if record is not None:
            record["emitted"] = True

    async def request(
        self,
        operation: PendingOperation,
        approval_id: str,
        reason: str,
        conversation_id: str,
        task_id: str,
    ) -> ApprovalDecision:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ApprovalDecision] = loop.create_future()
        self._pending[approval_id] = {
            "future": future,
            "conversation_id": conversation_id,
            "task_id": task_id,
            "operation": operation,
            "reason": reason,
        }
        self._emitter.emit(
            "approval.requested",
            {
                "approval_id": approval_id,
                "conversation_id": conversation_id,
                "task_id": task_id,
                "operation": operation,
                "reason": reason,
            },
        )
        try:
            # V0.3.8 T4（C4）：审批等待有上限——超时如实失败（approval_timeout），
            # 由回合失败链释放 busy 并放行队列。
            # V0.3.9 契约 §6：超时是终态——广播 approval.resolved(timeout) 并
            # 记入已决记录，迟到点击拿到真实终态而不是笼统的 not_found。
            return await asyncio.wait_for(future, timeout=APPROVAL_TIMEOUT_S)
        except asyncio.TimeoutError:
            if future.done() and not future.cancelled():
                # 同一事件循环 tick 内已被 resolve 完成：以真实裁决为准，
                # 不把已决审批误报成超时。
                self._pending.pop(approval_id, None)
                return future.result()
            item = self._pending.get(approval_id) or {
                "future": future,
                "conversation_id": conversation_id,
                "task_id": task_id,
                "reason": reason,
            }
            self._finish(
                approval_id,
                item,
                APPROVAL_TIMEOUT_DECISION,
                resolved_by="system",
                actor="system",
                reason="等待审批超时",
                error_code="approval_timeout",
                emit=True,
            )
            raise ServiceError(
                f"审批超时未裁决（{int(APPROVAL_TIMEOUT_S)}s）："
                "任务已按失败终止并释放，可重新发起",
                code="approval_timeout",
            ) from None
        finally:
            self._pending.pop(approval_id, None)

    def resolve(
        self, approval_id: str, decision: str, *, resolved_by: str = "desktop"
    ) -> dict[str, Any]:
        item = self._pending.get(approval_id)
        if item is None:
            prior = self._resolved.get(approval_id)
            if prior is not None:
                # 契约 §6：后到者拿到先到者的真实终态（结构化字段），
                # 双端据此收敛展示，不必解析 message 文案。
                raise ServiceError(
                    f"审批已由 {prior.get('resolved_by') or '系统'} 应答"
                    f"（{prior.get('decision')}），不能重复应答",
                    code="approval_already_resolved",
                    details=self._resolution_details(prior),
                )
            raise ServiceError(
                f"审批请求不存在或已经完成：{approval_id}",
                code="approval_not_found",
            )
        if decision == APPROVAL_TIMEOUT_DECISION:
            # 契约 §6：timeout 只能由服务端产生，客户端不可伪造。
            raise ServiceError(
                "timeout 由服务端产生，不能作为用户裁决提交",
                code="invalid_decision",
            )
        try:
            parsed = ApprovalDecision(decision)
        except ValueError as exc:
            raise ServiceError(f"未知审批决定：{decision}", code="invalid_decision") from exc
        # 用户裁决先记录终态；approval.resolved 由引擎路径统一广播
        # （避免同一审批两条事件，首个终态获胜）。
        return self._finish(
            approval_id,
            item,
            parsed.value,
            resolved_by=resolved_by,
            actor="user",
            reason=str(item.get("reason") or ""),
            emit=False,
        )

    def cancel_all(self) -> None:
        for approval_id, item in tuple(self._pending.items()):
            self._cancel_item(approval_id, item, "Sidecar 关闭，审批已取消")

    def cancel_for_conversation(self, conversation_id: str) -> None:
        """取消指定会话未决的审批并发出 resolved 事件。

        Turn 取消时调用：把正在等待用户裁决的审批按 DENY 结清，让编排器
        回调立即返回并把否决结果回复引擎；同时通知前端移除 pending。
        """
        for approval_id, item in tuple(self._pending.items()):
            if item.get("conversation_id") == conversation_id:
                self._cancel_item(
                    approval_id,
                    item,
                    "任务已取消，审批已否决",
                )

    def cancel_for_task(self, task_id: str) -> None:
        """V0.3.2 M4：只拒绝目标任务的未决审批（并发聊天互不影响）。"""
        for approval_id, item in tuple(self._pending.items()):
            if item.get("task_id") == task_id:
                self._cancel_item(
                    approval_id,
                    item,
                    "任务已取消，审批已否决",
                )

    def _finish(
        self,
        approval_id: str,
        item: dict[str, Any],
        decision: str,
        *,
        resolved_by: str | None,
        actor: str | None,
        reason: str,
        error_code: str | None = None,
        emit: bool,
    ) -> dict[str, Any]:
        """记录终态（首个终态获胜）并按需广播 approval.resolved。

        V0.3.9 契约 §6：decision/resolved_by/actor/reason/resolved_at/
        error_code 全部落进记录；缺失保持 null，不伪造来源。timeout 不是
        ApprovalDecision 成员，不向等待方回填伪造裁决（由 wait_for 超时
        路径如实失败）。
        """
        future = cast(asyncio.Future[ApprovalDecision], item["future"])
        if not future.done():
            try:
                future.set_result(ApprovalDecision(decision))
            except ValueError:
                pass
        self._pending.pop(approval_id, None)
        record: dict[str, Any] = {
            "decision": decision,
            "resolved_by": resolved_by,
            "actor": actor,
            "reason": reason,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "error_code": error_code,
            "conversation_id": item.get("conversation_id"),
            "task_id": item.get("task_id"),
            "emitted": False,
        }
        self._resolved[approval_id] = record
        while len(self._resolved) > self._RESOLVED_CAPACITY:
            self._resolved.pop(next(iter(self._resolved)))
        if emit:
            self._emit_resolved(approval_id, record)
        return {"decision": decision, "resolved_by": resolved_by}

    def _emit_resolved(self, approval_id: str, record: dict[str, Any]) -> None:
        self._emitter.emit(
            "approval.resolved",
            {
                "approval_id": approval_id,
                "conversation_id": record.get("conversation_id"),
                "task_id": record.get("task_id"),
                "decision": record.get("decision"),
                "resolved_by": record.get("resolved_by"),
                "actor": record.get("actor"),
                "reason": record.get("reason"),
                "resolved_at": record.get("resolved_at"),
                "error_code": record.get("error_code"),
            },
        )
        record["emitted"] = True

    @staticmethod
    def _resolution_details(record: dict[str, Any]) -> dict[str, Any]:
        """approval_already_resolved 的结构化真实终态（契约 §6）。"""
        return {
            "decision": record.get("decision"),
            "resolved_by": record.get("resolved_by"),
            "actor": record.get("actor"),
            "reason": record.get("reason"),
            "resolved_at": record.get("resolved_at"),
            "error_code": record.get("error_code"),
        }

    def _cancel_item(
        self, approval_id: str, item: dict[str, Any], reason: str
    ) -> None:
        self._finish(
            approval_id,
            item,
            ApprovalDecision.DENY.value,
            resolved_by="system",
            actor="system",
            reason=reason,
            emit=True,
        )

    def snapshot(self) -> list[dict[str, Any]]:
        # operation 是 PendingOperation 模型，必须过 to_jsonable；
        # 否则 bootstrap 响应在有挂起审批时编码失败，请求方永远等不到响应。
        return [
            {
                "approval_id": approval_id,
                "conversation_id": item["conversation_id"],
                "task_id": item.get("task_id"),
                "operation": to_jsonable(item["operation"]),
                "reason": item["reason"],
            }
            for approval_id, item in self._pending.items()
        ]


@dataclasses.dataclass
class _ControlLease:
    """一条远程控制租约（V0.3.9 契约 §6，按 device_key 独立记录）。

    TTL 45s 由持有者的 ping/claim 刷新；断连后额外宽限 15s（重连窗口），
    因此最晚 60s 回收。宽限只在断连期间存在（grace_expires_at 否则为 null）。
    回收判定用 monotonic 截止时刻；协议展示用续租时算好的 wall-clock 时间，
    保证同一租约的多次快照返回同一个 expires_at。
    """

    device_key: str
    granted_at: float
    last_refresh_at: float
    expires_at_wall: datetime
    connection_key: str | None = None
    disconnected_at: float | None = None
    grace_expires_at_wall: datetime | None = None
    reason: str = "claimed"

    @property
    def expires_at(self) -> float:
        return self.last_refresh_at + CONTROL_LEASE_TTL_S

    @property
    def grace_expires_at(self) -> float | None:
        if self.disconnected_at is None:
            return None
        return self.expires_at + CONTROL_LEASE_GRACE_S

    def reclaim_at(self) -> float:
        grace = self.grace_expires_at
        return grace if grace is not None else self.expires_at

    def renew(self, now: float) -> None:
        """续租：重置 TTL 与协议展示时刻，并清除断连宽限。"""
        self.last_refresh_at = now
        self.disconnected_at = None
        self.grace_expires_at_wall = None
        self.expires_at_wall = datetime.now(timezone.utc) + timedelta(
            seconds=CONTROL_LEASE_TTL_S
        )

    def mark_disconnected(self, now: float) -> None:
        """记录断连并进入重连宽限（幂等：重复断连不重复顺延）。"""
        if self.disconnected_at is not None:
            return
        self.disconnected_at = now
        self.grace_expires_at_wall = self.expires_at_wall + timedelta(
            seconds=CONTROL_LEASE_GRACE_S
        )


class DesktopApplicationService:
    """无 Qt 的桌面应用服务。

    Python 核心对象仍是唯一业务权威；此类只负责把现有能力映射到
    Sidecar 命令、快照和增量事件，不让 JSONL 层知道编排器内部细节。
    """

    def __init__(
        self,
        *,
        store: SQLiteStore,
        orchestrator: ConversationOrchestrator,
        pair_config: PairConfig,
        pair_catalog: list[PairConfig],
        emitter: EventEmitter,
        approval_broker: ApprovalBroker,
        dialogue_model: Any,
        coding_engine: Any,
        current_project_id: str,
        current_conversation_id: str,
        voice_runtime: VoiceRuntime | None = None,
    ) -> None:
        self.store = store
        # V0.3.3：角色卡仓库（迁移 9 已建表）与远程配对服务（状态存 app_state）。
        self.card_repository = CharacterCardRepository(store)
        # V0.3.5：受管理资产服务（头像/参考音频，character_assets 表首次启用）。
        self.asset_service = CharacterAssetService(
            store, store.database.parent / "character_assets"
        )
        self.pairing_service = PairingService()
        self._restore_pairing_state()
        self.tunnel_manager = TunnelManager(
            data_dir=store.database.parent,
            emitter=emitter,
            audit_logger=self.pairing_service.record_audit,
        )
        self.remote_serve_port: int | None = None
        self.orchestrator = orchestrator
        self.pair_config = pair_config
        self.pair_catalog = tuple(pair_catalog)
        self.emitter = emitter
        self.approval_broker = approval_broker
        self.dialogue_model = dialogue_model
        self.coding_engine = coding_engine
        # V0.2 M3：demo 模式无外部状态，账号切换不重建运行时
        self._demo = isinstance(dialogue_model, ScriptedDialogueModel)
        self.current_project_id = current_project_id
        self.current_conversation_id = current_conversation_id
        self.voice_runtime = voice_runtime
        self._shutdown = False
        # Router 会并发处理 JSONL 命令；PTT 的开始/结束必须按顺序执行，
        # 否则快速点击会让 stop 抢在 start 完成前进入 ASR 收尾。
        self._voice_ptt_lock = asyncio.Lock()
        # V0.3.2 M6：账号级音色生成互斥锁——同一账号同时只允许一个
        # voice.provision 任务，防止双击产生重复计费请求。
        self._voice_provision_lock = asyncio.Lock()
        # 生成中的瞬时状态按账号隔离；持久化成功状态以
        # voice.profile.<speaker>.voice_id 是否存在为准。
        self._voice_provision_states: dict[str, dict[str, dict[str, Any]]] = {}
        # M4.3：PTT 开始时捕获不可变上下文（conversation_id/target/pair_id），
        # ASR 提交使用这份上下文，避免录音期间切换会话导致文本落入错误会话。
        self._ptt_voice_context: dict[str, str] | None = None
        # M3.1：账号切换锁。切换过程与 chat.submit、配置保存互斥，防止
        # 半提交状态下新任务/新配置进入旧账号或旧运行时。
        self._account_switch_lock = asyncio.Lock()
        # M3.2：旧运行时异步关闭任务集合（避免连续保存/切换时泄漏子进程）
        self._close_runtime_tasks: set[asyncio.Task[None]] = set()
        # M1.1：chat.submit 每个会话的原子锁。锁覆盖“检查忙碌、持久化用户
        # 消息、登记 Turn、创建并登记后台任务”，防止同会话并发提交竞态。
        self._conversation_submit_locks: dict[str, asyncio.Lock] = {}
        self._tool_runs: dict[tuple[str, str], ToolRun] = {}
        self._streaming_message_ids: dict[tuple[str, str], set[str]] = {}
        # 编程助手在工具调用前发出的阶段性说明先走增量事件；在工具开始
        # 时送入语音队列，等最终回执落库时由常规消息监听接手。
        self._assistant_stream_text: dict[tuple[str, str], str] = {}
        self._title_tasks: set[asyncio.Task[None]] = set()
        # V0.3.9 §2：摘要 regenerate 后台任务（失败保留真实状态，不吞错误）。
        self._summary_tasks: set[asyncio.Task[None]] = set()
        # 自动压缩防重入：会话级在途标记（任务完成后清除）。
        self._auto_summary_in_flight: set[str] = set()
        # V039-S4-004：--serve 监听成功后由启动路径写入的局域网接入地址。
        # 三种形态：未监听 None；有地址 {host, port}；已监听但无局域网地址
        # {host: null, port, reason}（端口始终保留）。默认 None 表示尚未
        # 监听；随 bootstrap 下发，避免只依赖一次性的 serve.started 事件。
        self.remote_serve_address: dict[str, Any] | None = None
        # V0.2：后台回合任务集合（快速接受后立即返回，回合在后台推进）
        self._turn_tasks: set[asyncio.Task[None]] = set()
        # 角色对话不占用全局 coding busy 状态；用会话级任务记录阻止同一
        # 聊天在角色仍流式输出时再次并发启动，后续提交进入既有队列。
        self._conversation_turn_tasks: dict[str, asyncio.Task[None]] = {}
        self._title_generation_started: set[str] = set()
        # V0.2 M2：Turn 统一运行模型——一次提交 = 一个 Turn。运行态记录，
        # 快照随 bootstrap 水合；终态保留供前端历史展示。
        self._turns: dict[str, dict[str, Any]] = {}
        self._conversation_turn_ids: dict[str, list[str]] = {}
        # V0.3.9 §5：会话当前运行中的 turn_id——首个真实引擎/流式事件回调
        # 据此把 first_event_at 记到正确的回合上（无事件的回合保持 null）。
        self._active_turn_ids: dict[str, str] = {}
        # V0.2 M3：当前登录账号（重启后从 app_state 恢复；默认账号兜底）。
        # 账号是项目/聊天/配置/Codex 数据的隔离边界。
        self.current_account_id = (
            store.get_app_state("current_account_id") or "default-local"
        )
        if not self._account_exists(self.current_account_id):
            self.current_account_id = "default-local"
            store.set_app_state("current_account_id", "default-local")
        self.codex_auth = CodexAuthService(store.database.parent, self.current_account_id)
        # 账号级配置缓存：config.set 写库，运行时重建时读取
        self._account_config: dict[str, str] | None = None
        self._voice_state: dict[str, Any] = {
            "supported": voice_runtime is not None,
            # 语音总开关：默认随运行时启用，账号配置 voice.enabled=false 时关闭
            "enabled": voice_runtime is not None,
            # 古代机械语音必须由用户单独开启，默认关闭
            "assistant_voice_enabled": False,
            "vad": "idle",
            "vad_enabled": False,
            "ptt": False,
            "tts": "idle",
            "asr_partial": "",
            "error": None,
            # V0.2 M4：待播队列条数（VoiceMiniPlayer 的 queuedCount 数据源）
            "speech_queue_len": 0,
        }
        # V039-S4-012：error 字段的来源（tts / voice）。状态恢复时只清除
        # 已不再成立的那一类错误，不把仍然成立的识别错误一并抹掉。
        self._voice_error_scope: str | None = None

        self.orchestrator.on_message = self._on_message
        self.orchestrator.on_message_status_changed = self._on_message_status_changed
        self.orchestrator.on_dialogue_event = self._on_dialogue_event
        self.orchestrator.on_review_event = self._on_review_event
        self.orchestrator.on_engine_event = self._on_engine_event
        self.orchestrator.on_execution_started = self._on_execution_started
        self.orchestrator.on_execution_finished = self._on_execution_finished
        self._restore_current_conversation()
        # ---------------- V0.3.5（契约冻结 docs/plans/V0.3.5-契约冻结.md） ----------------
        # --serve 模式下由 __main__ 注入事件扇出；手机语音事件走 remote-only
        # 通道（只发远程连接，不写 stdout）。非 serve 模式保持 None。
        self._event_fanout: Any = None
        # 卡音色创建的每卡互斥锁（voice_card_provision_in_progress）。
        self._card_provision_locks: dict[str, asyncio.Lock] = {}
        # 手机上行转写会话（后台线程泵驱动识别器，回调需线程安全转回主循环）。
        self._mobile_asr = MobileAsrSessionManager(
            on_transcript=self._on_mobile_transcript
        )
        self._mobile_asr_conversations: dict[str, str] = {}
        self._mobile_asr_watchdogs: dict[str, asyncio.Task[None]] = {}
        # 手机下行 TTS 分片编目与在途下发任务。
        self._mobile_tts = MobileTtsSequencer()
        self._mobile_tts_tasks: dict[str, asyncio.Task[None]] = {}
        # V0.3.9 契约 §6：远程控制租约按 device_key 独立记录（TTL 45s，
        # 断连宽限 15s）；断连不立即释放，宽限结束后过期回收。
        self._control_leases: dict[str, _ControlLease] = {}
        self._control_sweeper: asyncio.Task[None] | None = None
        # 装配结果缓存（card_id → (updated_at, AssembledPrompt)）。
        self._assembled_cache: dict[str, tuple[str, AssembledPrompt]] = {}
        # V0.3.7 电源契约：--serve 模式开启远程服务（power.get_status 的
        # remote_serve_enabled 数据源；默认 False，__main__ 在 serve 模式置 True）。
        self.remote_serve_enabled: bool = False
        # V0.3.7 电源监视守护线程状态（契约 §2.1）：启动即读一次并 emit，
        # 此后每 interval 轮询，仅当关键元组变化才 emit power.status_changed。
        self._power_monitor_thread: threading.Thread | None = None
        self._power_monitor_stop = threading.Event()
        self._power_monitor_interval = 60.0
        self._power_monitor_last: tuple | None = None
        # 转写回调线程需要主循环引用做 call_soon_threadsafe；同步上下文
        # （部分测试 fixture）没有运行中的循环时置 None——该场景下无
        # remote 连接，转写事件本就无处可发，回调按无循环如实跳过。
        try:
            self._main_loop: Any = asyncio.get_running_loop()
        except RuntimeError:
            self._main_loop = None
        # 角色卡装配 resolver 后绑定：dialogue_model 在 service 构造前创建，
        # 这里把按 conversation_id 解析装配结果的回调挂进对话模型。
        if isinstance(self.dialogue_model, OpenAICompatibleDialogueModel):
            self.dialogue_model.character_prompt_resolver = (
                self._resolve_character_prompt
            )

    # ------------------------------------------------------------------ 生命周期

    async def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        if self._control_sweeper is not None and not self._control_sweeper.done():
            self._control_sweeper.cancel()
            await asyncio.gather(self._control_sweeper, return_exceptions=True)
        self._control_sweeper = None
        self.approval_broker.cancel_all()
        for task in tuple(self._title_tasks):
            task.cancel()
        if self._title_tasks:
            await asyncio.gather(*tuple(self._title_tasks), return_exceptions=True)
        for task in tuple(self._turn_tasks):
            task.cancel()
        if self._turn_tasks:
            await asyncio.gather(*tuple(self._turn_tasks), return_exceptions=True)
        # M3.2：等待已排队的旧运行时关闭任务结束，避免进程退出前泄漏。
        if self._close_runtime_tasks:
            await asyncio.gather(*tuple(self._close_runtime_tasks), return_exceptions=True)
        if self.voice_runtime is not None:
            await self.voice_runtime.shutdown()
        close_model = getattr(self.dialogue_model, "aclose", None)
        if close_model is not None:
            await close_model()
        transport = getattr(self.coding_engine, "transport", None)
        close_transport = getattr(transport, "close", None)
        if close_transport is not None:
            await close_transport()
        # V0.4.0（D1/T5）：Sidecar 退出时关闭隧道子进程，不留孤儿。
        if self.tunnel_manager is not None:
            await self.tunnel_manager.stop(reason="sidecar_exit")
        # V0.3.3：退出前持久化远程配对状态（token/撤销集合/审计）。
        self._persist_pairing_state()
        self.store.close()

    # ------------------------------------------------------------------ V0.2 M3 账号

    def _account_exists(self, account_id: str) -> bool:
        try:
            self.store.get_account(account_id)
            return True
        except KeyError:
            return False

    def _account_payload(self, account_id: str) -> dict[str, Any]:
        """AccountRecord 快照（不含密码派生结果与密钥）。"""
        account = self.store.get_account(account_id)
        return {
            "account_id": account["account_id"],
            "username": account["username"],
            "display_name": account["display_name"],
            "avatar": account["avatar"],
            "last_login_at": account["last_login_at"],
            "onboarding_complete": account["onboarding_complete"],
            "theme": account["theme"],
        }

    def _load_account_config(self, account_id: str | None = None) -> dict[str, str]:
        """账号级配置 + 密钥合并视图（api_key 保留明文供运行时使用）。"""
        account_id = account_id or self.current_account_id
        keys = (
            "engine",
            "dialogue.provider",
            "dialogue.base_url",
            "dialogue.model",
            "dialogue.api_key",
            "dialogue.reasoning_effort",
            "voice.enabled",
            "voice.base_url",
            "voice.profile.phainon.voice_id",
            "voice.profile.firefly.voice_id",
            "voice.profile.sam.voice_id",
            "voice.profile.march7.voice_id",
            "voice.profile.fourth_mirror.voice_id",
            "voice.profile.ancient_machine.voice_id",
            "assistant_voice_enabled",
            "vad_enabled",
        )
        config: dict[str, str] = {}
        for key in keys:
            value = self.store.get_config(account_id, key)
            if value is not None:
                config[key] = value
        for key in ("dialogue.api_key", "voice.api_key"):
            secret = self.store.get_secret(account_id, key)
            # None = 从未保存；空字符串 = 用户显式清空过。显式清空必须
            # 进入配置视图，阻止环境变量把旧值悄悄补回。
            if secret is not None:
                config[key] = secret
        return config

    def _masked(self, value: str | None) -> str:
        """密钥只回显掩码（方案：不回传明文）。"""
        if not value:
            return ""
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}…{value[-4:]}"

    @staticmethod
    def _redact_voice_error(value: object, api_key: str) -> str:
        """错误可见但不把当前账号 Key 带入事件或日志。"""
        text = str(value)
        if api_key:
            text = text.replace(api_key, "<REDACTED_API_KEY>")
        return text

    def _set_current_account(self, account_id: str) -> None:
        """切换当前账号并持久化；Codex 数据目录随之隔离。"""
        self.current_account_id = account_id
        self.store.set_app_state("current_account_id", account_id)
        self.codex_auth = CodexAuthService(self.store.database.parent, account_id)
        self._account_config = None

    # ------------------------------------------------------------------ 快照

    def bootstrap(self) -> dict[str, Any]:
        projects: list[dict[str, Any]] = []
        for project in self.store.list_projects_for_account(self.current_account_id):
            project_payload = dict(to_jsonable(project))
            project_payload["path_available"] = project.path_available
            project_payload["conversations"] = [
                self._conversation_payload(conversation)
                for conversation in self.store.list_conversations(
                    project.project_id, account_id=self.current_account_id
                )
            ]
            projects.append(project_payload)

        current_project = None
        if self.current_project_id:
            try:
                current_project = self.store.get_project(self.current_project_id)
                # M4.5：bootstrap 必须再次核对 current_project 的账号归属；
                # 账号切换/数据迁移后不允许把其他账号的项目当作当前项目。
                if (
                    current_project.account_id
                    and current_project.account_id != self.current_account_id
                ):
                    self.current_project_id = ""
                    current_project = None
            except KeyError:
                self.current_project_id = ""

        conversation = None
        snapshot: dict[str, Any] = {"messages": [], "tool_runs": []}
        if self.current_conversation_id:
            try:
                conversation = self.store.get_conversation(self.current_conversation_id)
                if (
                    conversation.account_id
                    and conversation.account_id != self.current_account_id
                ):
                    raise ServiceError(
                        "聊天不属于当前账号", code="conversation_account_mismatch"
                    )
                if conversation.project_id is not None:
                    self._current_account_project(
                        conversation.project_id, conversation_mismatch=True
                    )
                snapshot = self.store.load_conversation(self.current_conversation_id)
            except (KeyError, ServiceError):
                # M4.5：账号不匹配/项目不存在的当前聊天不能进入快照，
                # 清掉后由前端回到项目选择。
                self.current_conversation_id = ""
                conversation = None
                snapshot = {"messages": [], "tool_runs": []}
        # V0.3.2 M4：快照携带全部活动任务集合；active_task 保留为当前
        # 聊天的活动任务（旧前端兼容），busy 只跟当前聊天。
        active_tasks = self.orchestrator.state.active_tasks()
        active = next(
            (
                turn
                for turn in active_tasks
                if turn.conversation_id == self.current_conversation_id
            ),
            None,
        )
        return {
            "projects": projects,
            "active_tasks": to_jsonable(active_tasks),
            "current_account_id": self.current_account_id,
            "current_account": self._account_payload(self.current_account_id),
            "accounts": self._account_list_payload(),
            "current_project_id": self.current_project_id,
            "current_conversation_id": self.current_conversation_id,
            "current_project": (
                self._project_payload(current_project)
                if current_project is not None
                else self._empty_project_payload()
            ),
            "current_conversation": (
                self._conversation_payload(conversation)
                if conversation is not None
                else self._empty_conversation_payload()
            ),
            "messages": list(to_jsonable(snapshot["messages"])),
            "tool_runs": list(to_jsonable(snapshot["tool_runs"])),
            "turns": self._conversation_turns_payload(self.current_conversation_id),
            "queue_items": self.store.list_queue_items(self.current_conversation_id)
            if self.current_conversation_id
            else [],
            "active_task": to_jsonable(active),
            "busy": active is not None,
            "active_tasks": to_jsonable(active_tasks),
            "approvals": self.approval_broker.snapshot(),
            "remote_control": self._control_lease_payload(),
            # V039-S4-004：远程接入地址随快照恢复（事件丢一次也不丢状态）。
            "remote_serve": self.remote_serve_address,
            "voice": self._voice_snapshot(),
            "pair": self._pair_payload(self.pair_config),
            "pairs": [self._pair_payload(pair) for pair in self.pair_catalog],
            # 快照记录最近一条已经发出的事件；next_sequence 指向下一条待发事件。
            # 前端以该值作为 lastSequence，下一条事件必须从它递增一位。
            "sequence": self.emitter.next_sequence - 1,
            "stream_id": self.emitter.stream_id,
        }

    def approval_conversation_id(self) -> str:
        """审批归属当前展示聊天；V0.3.2 M4 起审批项自身携带聊天/任务 id。"""
        return self.current_conversation_id

    def has_active_remote_controller(self) -> bool:
        """是否存在未过期的远程控制租约（V0.3.9 契约 §6）。

        读取前先做一次惰性回收，保证过期租约不会继续阻断桌面播放。
        """
        self._sweep_control_leases()
        return bool(self._control_leases)

    def _sweep_control_leases(self, *, now: float | None = None) -> int:
        """回收已过期租约并广播 remote.control_changed，返回回收条数。"""
        current = time.monotonic() if now is None else now
        expired = [
            lease
            for lease in self._control_leases.values()
            if current > lease.reclaim_at()
        ]
        for lease in expired:
            self._control_leases.pop(lease.device_key, None)
            logger.info(
                "remote-control: 租约过期回收 key=%s reason=%s",
                lease.device_key,
                lease.reason,
            )
            self._emit_control_changed(lease, state="free", reason="expired")
        return len(expired)

    def _ensure_control_sweeper(self) -> None:
        """确保存在周期回收任务（最晚 60s 回收过期租约并广播事件）。"""
        task = self._control_sweeper
        if task is not None and not task.done():
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # 无运行中的事件循环（同步构造/测试）时只保留惰性回收。
            return
        self._control_sweeper = asyncio.create_task(
            self._control_sweep_loop(), name="remote-control-sweeper"
        )

    async def _control_sweep_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(CONTROL_LEASE_SWEEP_INTERVAL_S)
                self._sweep_control_leases()
                if not self._control_leases:
                    # 无租约时退出；下次认领会重新创建回收任务。
                    return
        except asyncio.CancelledError:
            raise

    def _control_lease_payload(self) -> dict[str, Any]:
        """remote_control 快照/状态：state/device_key/expires_at/
        grace_expires_at/reason，无值一律 null（契约 §6）。"""
        self._sweep_control_leases()
        if not self._control_leases:
            return {
                "state": "free",
                "device_key": None,
                "expires_at": None,
                "grace_expires_at": None,
                "reason": None,
            }
        lease = min(
            self._control_leases.values(),
            key=lambda item: (item.reclaim_at(), item.device_key),
        )
        return {
            "state": "held",
            "device_key": lease.device_key,
            "expires_at": lease.expires_at_wall.isoformat(),
            "grace_expires_at": (
                lease.grace_expires_at_wall.isoformat()
                if lease.grace_expires_at_wall is not None
                else None
            ),
            "reason": lease.reason,
        }

    def _emit_control_changed(
        self, lease: _ControlLease, *, state: str, reason: str
    ) -> None:
        """广播 remote.control_changed（契约 §6）。"""
        lease.reason = reason
        self.emitter.emit(
            "remote.control_changed",
            {
                "state": state,
                "device_key": lease.device_key,
                "expires_at": lease.expires_at_wall.isoformat(),
                "grace_expires_at": (
                    lease.grace_expires_at_wall.isoformat()
                    if lease.grace_expires_at_wall is not None
                    else None
                ),
                "reason": reason,
            },
        )

    def attach_voice_runtime(self, runtime: VoiceRuntime) -> None:
        self.voice_runtime = runtime
        self._voice_state["supported"] = True
        self.orchestrator.add_message_listener(self._on_message_for_voice)
        self._emit_voice_changed()

    def _on_message_for_voice(self, message: Message) -> None:
        if self.has_active_remote_controller():
            return
        if self.voice_runtime is not None:
            self.voice_runtime.on_message(message)

    async def start_voice(self) -> None:
        if self.voice_runtime is None:
            return
        config = self._load_account_config()
        enabled = config.get("voice.enabled") not in ("false", "0")
        assistant_voice_enabled = config.get("assistant_voice_enabled") in ("true", "1")
        vad_enabled = config.get("vad_enabled") in ("true", "1")
        self._voice_state["enabled"] = enabled
        self._voice_state["assistant_voice_enabled"] = assistant_voice_enabled
        self._voice_state["vad_enabled"] = vad_enabled
        self.voice_runtime.set_assistant_voice_enabled(assistant_voice_enabled)
        if not enabled:
            return
        try:
            # 麦克风采集与 VAD 分开：VAD 默认关闭时仍需启动采集，PTT 才能把
            # 音频帧送进 ASR。
            await self.voice_runtime.start_listening(vad_enabled=vad_enabled)
            self.voice_runtime.start_playback()
        except Exception as exc:  # noqa: BLE001 - 语音不可用不阻塞文本主线
            self._on_voice_error(f"语音启动失败：{exc}")

    async def _rebuild_voice_runtime_locked(self) -> None:
        """V0.3.2 M6：按当前账号语音配置重建 VoiceRuntime。

        调用方必须已持有账号切换锁（config.set / _switch_account / 启动）。
        有 Key（账号级或开发机 .env）即创建运行时——ASR 不依赖音色；TTS
        有效音色按账号生成结果 → 开发机作者音色 → 不可用 的优先级解析。
        替换失败或没有 Key 时如实清空运行时并保留错误信息，不伪造可用。
        """
        old_runtime = self.voice_runtime
        if old_runtime is not None:
            self.orchestrator.remove_message_listener(self._on_message_for_voice)
            self.voice_runtime = None
            try:
                await old_runtime.shutdown()
            except Exception as exc:  # noqa: BLE001 - 关闭失败保留真实错误
                self._on_voice_error(f"旧语音运行时关闭失败：{exc}")
        if not self._demo and self.current_conversation_id:
            config = self._load_account_config()
            settings = Settings.overlay(Settings.from_environment(), config)
            if settings.dashscope_api_key:
                voices = resolve_effective_voice_profile(
                    account_config=config,
                    settings=settings,
                    pair_config=self.pair_config,
                )
                try:
                    runtime = build_real_voice_runtime(
                        settings=settings,
                        orchestrator=self.orchestrator,
                        pair_config=self.pair_config,
                        conversation_id=self.current_conversation_id,
                        on_vad_state=self._on_voice_state,
                        on_asr_partial=self._on_asr_partial,
                        on_error=self._on_voice_error,
                        on_tts_state=self._on_tts_state,
                        on_interrupted=self._on_voice_interrupted,
                        on_text_input=self._submit_voice_input,
                        voices=voices,
                    )
                except Exception as exc:  # noqa: BLE001 - 文本功能不因语音依赖失败而退出
                    self._voice_state["supported"] = False
                    self._voice_state["enabled"] = False
                    self._on_voice_error(f"语音运行时未启用：{exc}")
                else:
                    self.attach_voice_runtime(runtime)
                    await self.start_voice()
                    return
            else:
                self._on_voice_error(
                    "真实语音未启用：未保存 DashScope API Key（语音页可保存账号 Key）"
                )
        self._voice_state["supported"] = self.voice_runtime is not None
        self._voice_state["enabled"] = self.voice_runtime is not None and (
            self._load_account_config().get("voice.enabled") not in ("false", "0")
        )
        self._emit_voice_changed()

    async def _voice_provision(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """V0.3.2 M6：按固定 manifest 在当前账号生成 6 个专属音色。

        命令不接受模型或 Key；``speaker_ids`` 只选择 manifest 中的固定项，
        ``replace_existing`` 只由显式的单项重新生成使用。默认调用只处理
        缺失/失败项，成功项不会重复计费。
        ``_account_switch_lock`` 与账号切换/配置保存共用，避免任务执行到一半
        把结果写入一个账号、却用另一个账号重建运行时。
        """
        if self._voice_provision_lock.locked():
            raise ServiceError(
                "该账号正在生成专属音色，请等待完成后再试",
                code="voice_provision_in_progress",
            )

        async with self._account_switch_lock:
            # 二次检查覆盖“等待账号切换锁期间已有 provision 开始”的竞态。
            if self._voice_provision_lock.locked():
                raise ServiceError(
                    "该账号正在生成专属音色，请等待完成后再试",
                    code="voice_provision_in_progress",
                )
            async with self._voice_provision_lock:
                account_id = self.current_account_id
                config = self._load_account_config(account_id)
                # 生成命令只允许使用当前本地账号已保存的凭据；.env
                # 仅保留给开发机运行时兼容，不得被一键生成静默采用。
                api_key = (config.get("voice.api_key") or "").strip()
                base_url = (config.get("voice.base_url") or "").strip()
                if not api_key or not base_url:
                    raise ServiceError(
                        "请先在语音页保存 DashScope API Key 与服务地址，再生成专属音色",
                        code="voice_not_configured",
                    )
                try:
                    manifest = load_reference_voice_manifest()
                except VoiceManifestError as exc:
                    # manifest/本地资源缺失是直接失败，不创建任何替代请求。
                    raise ServiceError(str(exc), code="voice_manifest_error") from exc

                from pair_harness.adapters.audio.qwen_voice_customization import (
                    QwenVoiceCustomizationClient,
                    VoiceCustomizationError,
                    audio_file_to_data_uri,
                )

                client = QwenVoiceCustomizationClient(
                    api_key=api_key, http_base_url=base_url
                )
                total = len(manifest)
                completed = sum(
                    1 for entry in manifest if config.get(entry.profile_key)
                )
                raw_speaker_ids = params.get("speaker_ids")
                if raw_speaker_ids is None:
                    # V0.3.3：一键生成默认只含角色侧说话方（助手侧已永久禁用，
                    # 不再随默认请求被整批拒绝）；显式指定助手侧仍会被拒绝。
                    requested_ids = {
                        entry.speaker_id
                        for entry in manifest
                        if entry.speaker_id not in assistant_speaker_ids()
                    }
                elif isinstance(raw_speaker_ids, (list, tuple)) and all(
                    isinstance(value, str) for value in raw_speaker_ids
                ):
                    requested_ids = set(raw_speaker_ids)
                else:
                    raise ServiceError(
                        "speaker_ids 必须是说话方 ID 字符串数组",
                        code="voice_invalid_request",
                    )
                known_ids = {entry.speaker_id for entry in manifest}
                unknown_ids = requested_ids - known_ids
                if unknown_ids:
                    raise ServiceError(
                        "speaker_ids 包含未知说话方: "
                        + ", ".join(sorted(unknown_ids)),
                        code="voice_invalid_request",
                    )
                # V0.3.3：助手永不使用 TTS——助手侧说话方一律拒绝生成专属音色。
                assistant_ids = assistant_speaker_ids()
                assistant_requested = requested_ids & assistant_ids
                if assistant_requested:
                    raise ServiceError(
                        "助手侧说话方已禁用语音，不可生成专属音色: "
                        + ", ".join(sorted(assistant_requested)),
                        code="assistant_voice_disabled",
                    )
                replace_existing = bool(params.get("replace_existing", False))
                failed = 0
                results: list[dict[str, Any]] = []
                account_states = self._voice_provision_states.setdefault(
                    account_id, {}
                )

                def emit_progress(
                    speaker_id: str,
                    state: str,
                    error: str | None,
                    voice_id: str | None = None,
                ) -> None:
                    # 事件不携带 Key / Authorization / 参考音频内容。
                    self.emitter.emit(
                        "voice.provision_changed",
                        {
                            "account_id": account_id,
                            "speaker_id": speaker_id,
                            "state": state,
                            "completed": completed,
                            "total": total,
                            "error": error,
                            "voice_id": voice_id,
                        },
                    )
                    account_states[speaker_id] = {
                        "state": state,
                        "error": error,
                        "voice_id": voice_id,
                    }

                for entry in manifest:
                    if entry.speaker_id not in requested_ids:
                        continue
                    saved = config.get(entry.profile_key) or ""
                    if saved and not replace_existing:
                        # 每个固定项都发出一次已完成状态，前端无需猜测
                        # 本次是否因为重试而跳过它。
                        emit_progress(entry.speaker_id, "completed", None, saved)
                        results.append(
                            {
                                "speaker_id": entry.speaker_id,
                                "state": "completed",
                                "voice_id": saved,
                                "error": None,
                            }
                        )
                        continue

                    emit_progress(entry.speaker_id, "pending", None)
                    emit_progress(entry.speaker_id, "creating", None)
                    try:
                        if entry.method == "clone":
                            # 真实联调已确认 qwen-audio-3.0-tts-flash 接受
                            # input.url=data:audio/*;base64,...。直接使用安装包
                            # 内参考音频，避免 DashScope 服务端拉取 GitHub 失败。
                            audio_url = audio_file_to_data_uri(entry.local_path)
                            result = await asyncio.to_thread(
                                client.create_cloned_voice,
                                prefix=entry.prefix,
                                url=audio_url,
                            )
                        else:
                            voice_prompt = entry.local_path.read_text(
                                encoding="utf-8"
                            ).strip()
                            if not voice_prompt:
                                raise VoiceCustomizationError(
                                    f"声音设计提示词为空: {entry.local_path}"
                                )
                            result = await asyncio.to_thread(
                                client.create_designed_voice,
                                prefix=entry.prefix,
                                voice_prompt=voice_prompt,
                                preview_text=ANCIENT_MACHINE_PREVIEW_TEXT,
                            )
                    except VoiceCustomizationError as exc:
                        failed += 1
                        detail = (
                            f"HTTP {exc.http_status} "
                            if exc.http_status is not None
                            else ""
                        ) + self._redact_voice_error(exc, api_key)
                        emit_progress(
                            entry.speaker_id, "failed", detail, saved or None
                        )
                        results.append(
                            {
                                "speaker_id": entry.speaker_id,
                                "state": "failed",
                                # 重新生成失败时保留旧 ID；可用音色不能被
                                # 一次失败请求清空。
                                "voice_id": saved or None,
                                "error": detail,
                            }
                        )
                        continue
                    except Exception as exc:  # noqa: BLE001 - 单项真实失败，继续后续项
                        failed += 1
                        detail = self._redact_voice_error(
                            str(exc) or type(exc).__name__, api_key
                        )
                        emit_progress(
                            entry.speaker_id, "failed", detail, saved or None
                        )
                        results.append(
                            {
                                "speaker_id": entry.speaker_id,
                                "state": "failed",
                                "voice_id": saved or None,
                                "error": detail,
                            }
                        )
                        continue

                    # 成功一项立即持久化；不合成、不猜测 voice_id。
                    self.store.set_config(account_id, entry.profile_key, result.voice_id)
                    config[entry.profile_key] = result.voice_id
                    self._account_config = None
                    if not saved:
                        completed += 1
                    emit_progress(
                        entry.speaker_id, "completed", None, result.voice_id
                    )
                    results.append(
                        {
                            "speaker_id": entry.speaker_id,
                            "state": "completed",
                            "voice_id": result.voice_id,
                            "error": None,
                        }
                    )

                # 生成结束后按最新账号音色重建语音运行时；部分成功结果
                # 已经写入 SQLite，不因其他项失败而丢失。
                await self._rebuild_voice_runtime_locked()
                return {
                    "status": "partial_failed" if failed else "completed",
                    "completed": completed,
                    "total": total,
                    "results": results,
                }

    def _voice_snapshot(self) -> dict[str, Any]:
        """voice 快照：先同步待播队列长度（VoiceMiniPlayer 的 queuedCount）。"""
        if self.voice_runtime is not None:
            self._voice_state["speech_queue_len"] = getattr(
                self.voice_runtime, "speech_queue_len", 0
            )
        return dict(self._voice_state)

    def _emit_voice_changed(self) -> None:
        """广播 voice 快照（事件与命令响应共用）。"""
        self.emitter.emit("voice.state_changed", {"voice": self._voice_snapshot()})

    def _on_voice_state(self, state: str) -> None:
        # vad 通道保持既有语义（playing=播放期间暂停监听）
        self._voice_state["vad"] = state
        self._emit_voice_changed()

    def _on_tts_state(self, state: str) -> None:
        # V0.2 M2-4：tts 状态机独立于 vad——idle/synthesizing/playing/skipping/failed
        self._voice_state["tts"] = state
        if state in ("playing", "idle"):
            # V039-S4-012：合成与播放真实恢复时清除旧的合成错误，界面不再
            # 长期展示与当前状态矛盾的旧限流报文。
            self._clear_voice_error(scope="tts")
        self._emit_voice_changed()

    def _on_voice_interrupted(
        self, conversation_id: str, message_id: str | None, reason: str
    ) -> None:
        """桌面朗读被抢占（V0.3.9 契约 §7：voice.playback_interrupted）。"""
        self.emitter.emit(
            "voice.playback_interrupted",
            {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "reason": reason,
            },
        )

    async def _interrupt_desktop_speech(self, reason: str) -> str | None:
        """抢占桌面本地朗读（契约 §6）。

        运行时未提供抢占入口（测试替身）时如实跳过：既有的
        stop_speaking_async 调用点语义不变，新增的抢占点只对真实
        VoiceRuntime 生效。
        """
        runtime = self.voice_runtime
        interrupt = getattr(runtime, "interrupt_async", None) if runtime is not None else None
        if interrupt is None:
            return None
        return await interrupt(reason)

    def _on_asr_partial(self, text: str) -> None:
        self._voice_state["asr_partial"] = text
        self.emitter.emit("voice.asr_partial", {"text": text})

    def _on_voice_error(self, message: str) -> None:
        self._voice_state["error"] = message
        # 来源判定用状态机而非文案关键词：合成失败必先置 tts=failed。
        self._voice_error_scope = (
            "tts" if self._voice_state.get("tts") == "failed" else "voice"
        )
        self._emit_voice_changed()

    def _clear_voice_error(self, *, scope: str | None = None) -> None:
        """清除已不再成立的语音错误（V039-S4-012）。

        ``scope`` 限定来源：合成恢复只清除合成错误，识别错误保持原样。
        返回是否真的清除了内容，便于调用方决定是否广播。
        """
        if self._voice_state.get("error") is None:
            return
        if scope is not None and self._voice_error_scope != scope:
            return
        self._voice_state["error"] = None
        self._voice_error_scope = None

    # ------------------------------------------------------------------ 命令路由

    async def handle_command(self, command: DesktopCommand) -> Any:
        if self._shutdown and command.method != "app.shutdown":
            raise ServiceError("Sidecar 已关闭", code="backend_shutdown")
        handlers = {
            "app.bootstrap": self._app_bootstrap,
            "app.shutdown": self._app_shutdown,
            "project.create": self._project_create,
            "project.select": self._project_select,
            "project.update_settings": self._project_update_settings,
            "project.archive": self._project_archive,
            "conversation.create": self._conversation_create,
            "ping": self._ping,
            "conversation.select": self._conversation_select,
            "conversation.open": self._conversation_open,
            "conversation.rename": self._conversation_rename,
            "conversation.archive": self._conversation_archive,
            "conversation.set_mode": self._conversation_set_mode,
            "chat.submit": self._chat_submit,
            "queue.edit": self._queue_edit,
            "queue.withdraw": self._queue_withdraw,
            "queue.prioritize": self._queue_prioritize,
            "task.cancel": self._task_cancel,
            "approval.resolve": self._approval_resolve,
            "voice.vad_set": self._voice_vad_set,
            "voice.ptt_start": self._voice_ptt_start,
            "voice.ptt_stop": self._voice_ptt_stop,
            "voice.tts_stop": self._voice_tts_stop,
            "voice.tts_play": self._voice_tts_play,
            "voice.tts_skip": self._voice_tts_skip,
            "voice.preview": self._voice_preview,
            "voice.provision": self._voice_provision,
            "account.list": self._account_list,
            "account.register": self._account_register,
            "account.login": self._account_login,
            "account.logout": self._account_logout,
            "account.switch": self._account_switch,
            "account.update_profile": self._account_update_profile,
            "account.change_password": self._account_change_password,
            "account.onboarding_complete": self._account_onboarding_complete,
            "config.get": self._config_get,
            "config.set": self._config_set,
            "config.test_connection": self._config_test_connection,
            "codex.oauth_start": self._codex_oauth_start,
            "codex.oauth_status": self._codex_oauth_status,
            "codex.logout": self._codex_logout,
            "codex.api_login": self._codex_api_login,
            "app.reconnect": self._app_reconnect,
            "card.list": self._card_list,
            "card.get": self._card_get,
            "card.create_draft": self._card_create_draft,
            "card.update": self._card_update,
            "card.duplicate": self._card_duplicate,
            "card.archive": self._card_archive,
            "card.delete": self._card_delete,
            "card.select_active": self._card_select_active,
            # V0.3.7：card.peek_import 为规范名；card.peek_import_json 保留
            # 为同一 handler 的 deprecated 别名（同一行为，既有前端不破坏）。
            "card.peek_import": self._card_peek_import,
            "card.peek_import_json": self._card_peek_import,
            "card.import_json": self._card_import_json,
            "card.export_json": self._card_export_json,
            "card.import_png": self._card_import_png,
            "card.export_png": self._card_export_png,
            "card.publish": self._card_publish,
            "card.set_avatar": self._card_set_avatar,
            "card.remove_avatar": self._card_remove_avatar,
            "power.get_status": self._power_get_status,
            "voice.card_bind_reference": self._voice_card_bind_reference,
            "voice.card_create": self._voice_card_create,
            "voice.card_unbind": self._voice_card_unbind,
            "voice.card_preview": self._voice_card_preview,
            "voice.mobile_ptt_start": self._voice_mobile_ptt_start,
            "voice.mobile_audio_chunk": self._voice_mobile_audio_chunk,
            "voice.mobile_ptt_stop": self._voice_mobile_ptt_stop,
            "voice.mobile_tts_stop": self._voice_mobile_tts_stop,
            "remote.issue_code": self._remote_issue_code,
            "remote.pair": self._remote_pair,
            "remote.list_devices": self._remote_list_devices,
            "remote.revoke": self._remote_revoke,
            "remote.claim_control": self._remote_claim_control,
            "remote.release_control": self._remote_release_control,
            "remote.control_status": self._remote_control_status,
            "remote.tunnel_start": self._remote_tunnel_start,
            "remote.tunnel_stop": self._remote_tunnel_stop,
            "remote.tunnel_status": self._remote_tunnel_status,
            # V0.3.9 §5：显式只读查询（存储层过滤，不改写状态）。
            "metrics.query": self._metrics_query,
            "diagnostics.prompt_assembly": self._diagnostics_prompt_assembly,
            "summary.regenerate": self._summary_regenerate,
            "summary.get": self._summary_get,
            "memory.create": self._memory_create,
            "memory.list": self._memory_list,
            "memory.update": self._memory_update,
            "memory.delete": self._memory_delete,
        }
        if command.method == "remote.issue_code":
            return await self._remote_issue_code(command.params, origin=command.origin)
        if command.method == "remote.list_devices":
            return await self._remote_list_devices(command.params, origin=command.origin)
        if command.method == "remote.revoke":
            return await self._remote_revoke(command.params, origin=command.origin)
        if command.method == "remote.tunnel_start":
            return await self._remote_tunnel_start(command.params, origin=command.origin)
        if command.method == "remote.tunnel_stop":
            return await self._remote_tunnel_stop(command.params, origin=command.origin)
        if command.method == "remote.tunnel_status":
            return await self._remote_tunnel_status(command.params, origin=command.origin)
        if command.method == "remote.pair":
            return await self._remote_pair(command.params, connection_key=command.connection_key)
        if command.method == "approval.resolve":
            # V0.3.5：审批应答需要命令来源做双端仲裁，其余 handler 只收 params。
            return await self._approval_resolve(
                command.params, origin=command.origin
            )
        if command.method == "chat.submit":
            # V0.3.9 §5：回合来源身份只能取传输层注入的 command 字段
            # （params 里的同名字段不可信），否则手机回合在指标里会显示
            # 成桌面。
            return await self._chat_submit(
                command.params,
                origin=command.origin,
                device_key=command.remote_device_key,
                device_name=command.remote_device_name,
            )
        if command.method == "voice.mobile_ptt_start":
            # V0.3.5：语音会话绑定传输层注入的连接 key，供断开清理。
            return await self._voice_mobile_ptt_start(
                command.params, connection_key=command.connection_key
            )
        if command.method == "voice.mobile_ptt_stop":
            # 手机语音转写提交走同一回合链；来源身份同样来自传输层。
            return await self._voice_mobile_ptt_stop(
                command.params,
                origin=command.origin,
                device_key=command.remote_device_key,
                device_name=command.remote_device_name,
            )
        if command.method == "remote.claim_control":
            return await self._remote_claim_control(
                command.params,
                device_key=self._remote_control_device_key(command),
                connection_key=command.connection_key,
            )
        if command.method == "remote.release_control":
            return await self._remote_release_control(
                command.params, device_key=self._remote_control_device_key(command)
            )
        if command.method == "ping":
            # V0.3.9 契约 §6：已鉴权持有者的心跳刷新控制租约（无事件）。
            return await self._ping(
                command.params, device_key=command.remote_device_key
            )
        handler = handlers[command.method]
        if command.method in _PLAYBACK_START_METHODS:
            # V039-S4-016：起播守卫按调用方身份判定，身份只能来自传输层。
            return await handler(
                command.params,
                origin=command.origin,
                device_key=command.remote_device_key,
            )
        return await handler(command.params)

    async def _app_bootstrap(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        return self.bootstrap()

    async def _app_shutdown(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        await self.shutdown()
        return {"stopped": True}

    async def _project_create(self, params: Mapping[str, Any]) -> dict[str, Any]:
        pair_id = self._requested_pair_id(params)
        root_value = params.get("root_path")
        if not isinstance(root_value, str) or not root_value:
            raise ServiceError("project.create 需要 root_path", code="invalid_params")
        root_path = Path(root_value).expanduser().resolve()
        # M4.5：先查所有项目（含已归档），不能对同一目录静默创建第二条记录。
        project = self.store.find_project_by_root_path(str(root_path))
        if project is None:
            project = self.store.create_project(
                project_id=str(params.get("project_id") or uuid4()),
                name=str(params.get("name") or root_path.name or root_path),
                root_path=str(root_path),
                approval_mode=str(
                    params.get("approval_mode", ApprovalMode.REQUEST_APPROVAL.value)
                ),
                reasoning_effort=str(params.get("reasoning_effort", "low")),
                account_id=self.current_account_id,
            )
        elif project.archived:
            # 再次选择已归档目录：恢复旧项目（含其聊天），而不是新建重复记录。
            project = self.store.unarchive_project(project.project_id)
        if project.account_id != self.current_account_id:
            raise ServiceError(
                "该项目目录已属于其他账号，不能静默创建重复记录",
                code="project_account_conflict",
            )
        conversation = self._find_or_create_conversation(
            project.project_id,
            pair_id=pair_id,
            character_card_id=_params_card_id(params),
        )
        await self._select_conversation_context(conversation.conversation_id, emit=True)
        return self.bootstrap()

    async def _project_select(self, params: Mapping[str, Any]) -> dict[str, Any]:
        project_id = self._required_string(params, "project_id")
        project = self._current_account_project(project_id)
        conversation_id = params.get("conversation_id")
        if isinstance(conversation_id, str):
            conversation = self.store.get_conversation(conversation_id)
            if conversation.project_id != project.project_id:
                raise ServiceError("聊天不属于指定项目", code="conversation_project_mismatch")
        else:
            conversations = self.store.list_conversations(
                project.project_id, account_id=self.current_account_id
            )
            conversation = conversations[0] if conversations else self._find_or_create_conversation(
                project.project_id, pair_id=self.pair_config.pair_id
            )
        await self._select_conversation_context(conversation.conversation_id, emit=True)
        return self.bootstrap()

    async def _project_update_settings(self, params: Mapping[str, Any]) -> dict[str, Any]:
        project_id = str(params.get("project_id") or self.current_project_id)
        project = self._current_account_project(project_id)
        root_changed = False
        if "root_path" in params:
            root_value = params.get("root_path")
            if not isinstance(root_value, str) or not root_value.strip():
                raise ServiceError("root_path 必须是非空路径", code="invalid_params")
            root_path = Path(root_value).expanduser().resolve()
            root_changed = str(root_path) != project.root_path
            if root_changed:
                self.store.update_project_root_path(project_id, str(root_path))
                default_names = {
                    Path(project.root_path).name or project.root_path,
                    project.root_path,
                }
                if "name" not in params and project.name in default_names:
                    self.store.update_project_name(
                        project_id, root_path.name or str(root_path)
                    )
        if "name" in params:
            self.store.update_project_name(
                project_id, self._required_string(params, "name")
            )
        if "approval_mode" in params:
            try:
                mode = ApprovalMode(str(params["approval_mode"]))
            except ValueError as exc:
                raise ServiceError("未知审批模式", code="invalid_approval_mode") from exc
            self.store.update_project_approval_mode(project_id, mode.value)
            self.orchestrator.set_approval_mode(mode, conversation_id=self.current_conversation_id)
        if "reasoning_effort" in params:
            effort = str(params["reasoning_effort"])
            if effort not in {"low", "medium", "high", "xhigh", "max"}:
                raise ServiceError("未知推理档位", code="invalid_reasoning_effort")
            self.store.update_project_reasoning_effort(project_id, effort)
            # M5.2：项目级 reasoning_effort 只作用于编程助手；角色模型的
            # dialogue.reasoning_effort 是独立账号配置键，不能在这里覆盖。
            # B-03：编程助手只有 reasonix acp，深度档位在运行时构建时写成
            # 账号级 dialogue.reasoning_effort，此处不再有引擎级实时改写。
        if root_changed and project_id == self.current_project_id:
            # 重建运行时上下文（项目目录变化）但不回推整份快照；旧 session
            # 引用必须失效，下一次任务在新目录新开 session。
            self._invalidate_engine_sessions()
            await self._select_conversation_context(self.current_conversation_id, emit=False)
        updated = self._project_payload(self.store.get_project(project_id))
        self.emitter.emit("project.changed", {"project": updated})
        # V0.2：设置类命令返回定向响应，不再用整份 bootstrap 覆盖未修改字段
        return {"project": updated}

    async def _project_archive(self, params: Mapping[str, Any]) -> dict[str, Any]:
        project_id = str(params.get("project_id") or self.current_project_id)
        if not project_id:
            raise ServiceError("没有可归档的项目", code="project_not_found")
        # V0.3.2 M4：并发下按项目枚举全部活动任务
        busy_turn = next(
            (
                turn
                for turn in self.orchestrator.state.active_tasks()
                if turn.project_id == project_id
            ),
            None,
        )
        if busy_turn is not None:
            raise ServiceError("项目正在执行任务，暂时不能归档", code="project_busy")

        self._current_account_project(project_id)
        was_current = project_id == self.current_project_id
        previous_conversation_id = self.current_conversation_id
        self.store.archive_project(project_id)

        if was_current:
            remaining = self.store.list_projects_for_account(self.current_account_id)
            if remaining:
                conversation = self._find_or_create_conversation(
                    remaining[0].project_id,
                    pair_id=self.pair_config.pair_id,
                )
                await self._select_conversation_context(conversation.conversation_id, emit=True)
            else:
                if previous_conversation_id:
                    self.orchestrator.close_conversation(previous_conversation_id)
                self.current_project_id = ""
                self.current_conversation_id = ""
        return self.bootstrap()

    async def _ping(
        self, params: Mapping[str, Any], *, device_key: str | None = None
    ) -> dict[str, Any]:
        """V0.3.8 T1（契约 §14.3）：WS 心跳——响应携带服务端时间作活性信号。

        客户端约 30s 收不到任何入站消息即判定半开连接，主动断开走既有重连。
        V0.3.9 契约 §6 修订：已鉴权持有者的 ping 刷新控制租约（TTL 45s），
        续租本身不发事件；非持有者的 ping 不续租、不夺权。响应形状不变。
        """
        del params
        if device_key is not None:
            lease = self._control_leases.get(device_key)
            if lease is not None:
                lease.renew(time.monotonic())
                lease.reason = "renewed"
        return {"server_time": datetime.now(timezone.utc).isoformat()}

    async def _conversation_create(self, params: Mapping[str, Any]) -> dict[str, Any]:
        pair_id = self._requested_pair_id(params)
        project_id = str(params.get("project_id") or self.current_project_id)
        project = self._current_account_project(project_id)
        title = str(params.get("title") or "新聊天")
        # V0.3.5：显式 character_card_id 优先；缺省快照当时有效的 active 卡。
        card_id = str(params.get("character_card_id") or "").strip() or None
        if card_id is None:
            card_id = self._effective_active_card_id()
        # V0.3.8 T6（契约冻结 §14.2）：reuse_active=true 时同项目 + 同角色卡
        # + 同搭档已有活跃会话则直接复用——不新建、不重复插入开场白、不改标题。
        # 无角色卡的普通会话不参与复用，普通「新建聊天」永远显式新建。
        # V0.3.9 契约 §1：搭档是会话身份的一部分，跨越搭档不得复用。
        if bool(params.get("reuse_active", False)) and card_id is not None:
            existing = self.store.find_active_conversation(
                project.project_id,
                character_card_id=card_id,
                pair_id=pair_id,
                account_id=self.current_account_id,
            )
            if existing is not None:
                await self._select_conversation_context(existing.conversation_id, emit=True)
                result = self.bootstrap()
                result["reused"] = True
                return result
        conversation = self.store.create_conversation(
            project_id=project.project_id,
            pair_id=pair_id,
            title=title,
            account_id=self.current_account_id,
            character_card_id=card_id,
        )
        if card_id:
            try:
                record = self.card_repository.get_card(card_id)
            except KeyError:
                record = None
            if record is not None:
                self._insert_character_greeting(conversation, record.card)
        await self._select_conversation_context(conversation.conversation_id, emit=True)
        result = self.bootstrap()
        result["reused"] = False
        return result

    async def _conversation_select(self, params: Mapping[str, Any]) -> dict[str, Any]:
        conversation_id = self._required_string(params, "conversation_id")
        self._current_account_conversation(conversation_id)
        await self._select_conversation_context(conversation_id, emit=True)
        return self.bootstrap()

    async def _conversation_open(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """V0.3.2 M4/M5：多窗口显式读取命令（只读装载，不改变全局导航）。

        ``view_id`` 由前端携带用于路由，Sidecar 不保存窗口导航状态；本
        命令只把目标聊天的快照（conversation/project/pair/messages/
        tool_runs/turns/queue_items/active task）返回给调用窗口，不修改
        其他窗口正在查看的聊天，也不清理任何审批或引擎会话。
        """
        # view_id 由前端携带用于路由，Sidecar 不保存窗口导航状态。
        conversation_id = self._required_string(params, "conversation_id")
        conversation = self._current_account_conversation(conversation_id)
        project = None
        if conversation.project_id is not None:
            project = self._current_account_project(
                conversation.project_id, conversation_mismatch=True
            )
        # V0.3.5：绑定卡已被删除时如实提示回退内置角色，不静默换人（契约 §4.2）。
        if conversation.character_card_id:
            try:
                self.card_repository.get_card(conversation.character_card_id)
            except KeyError:
                self.emitter.emit(
                    "conversation.card_missing",
                    {
                        "conversation_id": conversation_id,
                        "card_id": conversation.character_card_id,
                        "message": (
                            "该聊天绑定的角色卡已被删除，"
                            "本轮起回退为内置角色"
                        ),
                    },
                )
        snapshot = self.store.load_conversation(conversation_id)
        # 只读装载：恢复内存历史与工具缓存（幂等），不改写 current_*。
        # 返回体所有会话运行态都在 await 前物化；随后事件由调用端按游标重放。
        self.orchestrator.restore_conversation(snapshot)
        for tool_run in snapshot["tool_runs"]:
            self._tool_runs[
                (tool_run.conversation_id, tool_run.tool_call_id)
            ] = tool_run
        active = self.orchestrator.state.get_for_conversation(conversation_id)
        # 所有可序列化字段先物化成不可变返回体，再采样全局事件游标。
        result = {
            "conversation": self._conversation_payload(conversation),
            "project": (
                self._project_payload(project) if project is not None else None
            ),
            "pair": self._pair_payload(load_pair_config(conversation.pair_id)),
            "messages": list(to_jsonable(snapshot["messages"])),
            "tool_runs": list(to_jsonable(snapshot["tool_runs"])),
            "turns": self._conversation_turns_payload(conversation_id),
            "queue_items": self.store.list_queue_items(conversation_id),
            "active_task": to_jsonable(active),
        }
        # 会话快照与全局事件共用同一连接游标；调用端据此重放请求期间事件。
        result["sequence"] = self.emitter.next_sequence - 1
        result["stream_id"] = self.emitter.stream_id
        # 共享的物理麦克风/TTS 运行时在快照切点之后切换；期间事件序号
        # 大于 result.sequence，客户端会按目标会话重放。
        await self._focus_voice_context(conversation_id, conversation.pair_id)
        return result

    async def _conversation_rename(self, params: Mapping[str, Any]) -> dict[str, Any]:
        conversation_id = str(params.get("conversation_id") or self.current_conversation_id)
        title = self._required_string(params, "title")
        self._current_account_conversation(conversation_id)
        self.store.rename_conversation(conversation_id, title)
        self.emitter.emit(
            "conversation.changed",
            {"conversation": self._conversation_payload(self.store.get_conversation(conversation_id))},
        )
        return self.bootstrap()

    async def _conversation_archive(self, params: Mapping[str, Any]) -> dict[str, Any]:
        conversation_id = str(params.get("conversation_id") or self.current_conversation_id)
        conversation = self._current_account_conversation(conversation_id)
        # V0.3.8 T6：补建判断用被归档会话自身的项目。归档非当前项目的最后
        # 聊天不得在当前项目凭空补“新聊天”；_current_account_conversation
        # 已拒绝无项目的日常聊天，这里只做类型收窄。
        project_id = conversation.project_id
        if project_id is None:
            raise ServiceError("日常聊天尚未接入桌面迁移", code="daily_chat_unavailable")
        self.store.archive_conversation(conversation_id)
        remaining = self.store.list_conversations(
            project_id, account_id=self.current_account_id
        )
        if not remaining:
            created = self._find_or_create_conversation(
                project_id, pair_id=self.pair_config.pair_id
            )
            remaining = [created]
        if conversation_id == self.current_conversation_id:
            await self._select_conversation_context(remaining[0].conversation_id, emit=True)
        else:
            self.emitter.emit("conversation.changed", {"conversation_id": conversation_id})
        return self.bootstrap()

    async def _chat_submit(
        self,
        params: Mapping[str, Any],
        *,
        origin: str = "desktop",
        device_key: str | None = None,
        device_name: str | None = None,
    ) -> dict[str, Any]:
        """V0.2 快速接受（问题 1）：同步落库用户消息，立即返回真实 id。

        回合处理移到后台任务（``_run_submit_turn``），前端按真实
        ``message_id`` 即时回显并推进状态；处理失败后文字仍在可重试。
        ``origin``/``device_key``/``device_name``（V0.3.9 §5）由
        ``handle_command`` 从传输层注入的 DesktopCommand 透传，落进 Turn
        payload，供终态指标如实记录来源。
        """
        conversation_id = str(params.get("conversation_id") or self.current_conversation_id)
        if not conversation_id:
            raise ServiceError("请先创建或选择项目", code="no_active_conversation")
        self._current_account_conversation(conversation_id)
        target = str(params.get("target", "character"))
        text = self._required_string(params, "text")
        if target not in {"character", "assistant"}:
            raise ServiceError("target 必须是 character 或 assistant", code="invalid_target")
        # V0.3.9 契约 §6：用户发送立即停声——epoch 递增、清队列、停播放器，
        # 旧 epoch 的迟到 PCM 永不写入（排队提交同样先停声）。
        await self._interrupt_desktop_speech("user_send")
        # M3.1：chat.submit 与账号切换/配置保存互斥。锁从模式/上下文切换
        # 开始持有，避免切换过程中提交落到半旧半新的状态。
        async with self._account_switch_lock:
            # V0.3.8 T6：mode 缺省时不改写会话 last_mode（“委派”标签与
            # updated_at 不再被普通消息漂移）；显式携带 mode 的提交仍按
            # 请求持久化该会话的模式，显式切换走 conversation.set_mode。
            mode = params.get("mode")
            if mode is not None:
                if mode not in {"chat", "collaboration"}:
                    raise ServiceError("mode 必须是 chat 或 collaboration", code="invalid_mode")
                self._set_conversation_mode(conversation_id, str(mode))
            # M4.4：后端按会话持久化模式校验 assistant 目标；chat 模式
            # 直接拒绝，不能创建 Task 或队列中的助手任务。
            if target == "assistant":
                persisted_mode = self.store.get_conversation(conversation_id).last_mode
                if persisted_mode == "chat":
                    raise ServiceError(
                        "聊天模式不能直接交给助手，请先切换到协作模式",
                        code="assistant_not_allowed_in_chat_mode",
                    )
            # V0.3.2 M4：显式 conversation_id 只解析不可变执行上下文，
            # 不调用 _select_conversation_context——后台聊天的提交不得改写
            # 全局当前项目/搭档/审批模式（视图状态与业务上下文分离）。
            exec_context = self._resolve_execution_context(conversation_id)

            # M1.1：同一会话的 chat.submit 原子化。锁覆盖“检查忙碌、持久化
            # 用户消息、登记 Turn、创建并登记后台任务”，第二条提交只会进入队列。
            lock = self._conversation_submit_locks.setdefault(conversation_id, asyncio.Lock())
            async with lock:
                # V0.2 M2（问题 9）：忙碌时提交先入队（followup 追加 / steer 置队首），
                # 先持久化再向前端确认；派发由回合完成后的自动派发链处理。
                # V0.3.2 M4：忙碌判定只看本聊天；其他聊天运行不影响提交。
                active = self.orchestrator.state.get_for_conversation(conversation_id)
                turn_task = self._conversation_turn_tasks.get(conversation_id)
                conversation_busy = turn_task is not None and not turn_task.done()
                if active is not None or conversation_busy:
                    intent = str(params.get("intent", "followup"))
                    if intent not in {"followup", "steer"}:
                        raise ServiceError("intent 必须是 followup 或 steer", code="invalid_intent")
                    item = self.store.enqueue_queue_item(
                        conversation_id=conversation_id,
                        target=target,
                        text=text,
                        intent=intent,
                        account_id=self.current_account_id,
                    )
                    self._emit_queue_changed(conversation_id)
                    return {
                        "queue_item": item,
                        "queued": True,
                        "conversation_id": conversation_id,
                    }

                user_message = await self.orchestrator.submit_user_message(
                    conversation_id=conversation_id,
                    text=text,
                    target=target,
                    pair_id=exec_context.pair_id,
                )
                # V0.2 M2：同步创建 Turn（accepted），随提交返回 turn_id 供前端追踪；
                # 生命周期事件由后台任务按 started → completed/failed 推进。
                turn = self._register_turn(
                    conversation_id,
                    user_message,
                    target,
                    origin=origin,
                    device_key=device_key,
                    device_name=device_name,
                )
                task = asyncio.create_task(
                    self._run_submit_chain(
                        conversation_id,
                        user_message,
                        target,
                        turn["turn_id"],
                        exec_context,
                    ),
                    name=f"turn:{conversation_id}:{user_message.message_id}",
                )
                self._track_turn_task(conversation_id, task, turn["turn_id"], user_message)
                return {
                    "message_id": user_message.message_id,
                    "conversation_id": conversation_id,
                    "status": "received",
                    "target": target,
                    "turn_id": turn["turn_id"],
                }

    async def _submit_voice_input(self, text: str, target: str) -> None:
        """把已完成 ASR 的文本送入同一条后台 Turn 链。

        M4.3：PTT 开始后不可变上下文优先；即使用户录音期间切换会话，
        松键提交仍进入开始录音时捕获的会话与目标。
        """
        context = self._ptt_voice_context or {}
        conversation_id = context.get("conversation_id") or self.current_conversation_id
        actual_target = context.get("target") or target
        # 后台提交可能晚于 voice.ptt_stop 返回；这里消费并清除不可变上下文，
        # 避免下一次 PTT 或后续提交误用旧会话。
        self._ptt_voice_context = None
        await self._chat_submit(
            {
                "conversation_id": conversation_id,
                "target": actual_target,
                "text": text,
            }
        )

    def _track_turn_task(
        self,
        conversation_id: str,
        task: asyncio.Task[None],
        turn_id: str | None = None,
        user_message: Any = None,
    ) -> None:
        """登记后台回合，并在结束时清除对应会话的忙碌标记。

        M1.1：同一会话已有未完成任务时禁止覆盖旧引用；done callback
        只做最后一道异常观测，不能把失败改写成成功。
        """
        existing = self._conversation_turn_tasks.get(conversation_id)
        if existing is not None and not existing.done():
            raise RuntimeError(
                f"conversation {conversation_id} already has an unfinished turn task"
            )
        self._turn_tasks.add(task)
        self._conversation_turn_tasks[conversation_id] = task

        def _on_done(completed: asyncio.Task[None]) -> None:
            self._turn_tasks.discard(completed)
            if self._conversation_turn_tasks.get(conversation_id) is completed:
                self._conversation_turn_tasks.pop(conversation_id, None)
            if completed.cancelled():
                return
            exc = completed.exception()
            if exc is None:
                return
            # 正常异常处理在 _run_submit_chain/_run_submit_turn 内；这里观测
            # 漏网的异常，保留原始错误并做最终状态核对，绝不合成成功。
            logger.error(
                "后台回合任务最终异常观测（conversation=%s turn=%s）：%s",
                conversation_id,
                turn_id,
                exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            if turn_id is not None:
                self._reconcile_failed_turn(
                    conversation_id, turn_id, user_message, exc
                )

        task.add_done_callback(_on_done)

    def _register_turn(
        self,
        conversation_id: str,
        user_message: Any,
        target: str,
        *,
        origin: str = "desktop",
        device_key: str | None = None,
        device_name: str | None = None,
    ) -> dict[str, Any]:
        """创建并登记 Turn（accepted 态），返回 payload。

        V0.3.9 §5：来源身份随 Turn payload 落到运行态记录，终态指标从
        同一份记录取值，不再回落到硬编码的 desktop。
        """
        project_id = ""
        try:
            project_id = self.store.get_conversation(conversation_id).project_id or ""
        except KeyError:
            pass
        turn = Turn(
            project_id=project_id,
            conversation_id=conversation_id,
            target=target,  # type: ignore[arg-type]
            source_message_id=user_message.message_id,
            status=TurnStatus.ACCEPTED,
        )
        payload = to_jsonable(turn)
        payload["origin"] = origin
        payload["remote_device_key"] = device_key
        payload["remote_device_name"] = device_name
        self._turns[turn.turn_id] = payload
        ids = self._conversation_turn_ids.setdefault(conversation_id, [])
        if turn.turn_id not in ids:
            ids.append(turn.turn_id)
        return payload

    def _conversation_turns_payload(self, conversation_id: str) -> list[dict[str, Any]]:
        """快照用：会话内按创建顺序的 turns。"""
        return [
            dict(self._turns[turn_id])
            for turn_id in self._conversation_turn_ids.get(conversation_id, [])
            if turn_id in self._turns
        ]

    def _emit_turn_status(self, turn_id: str, status: str) -> None:
        """推进 Turn 状态并发射事件；running 首态用 turn.started。"""
        turn = self._turns.get(turn_id)
        if turn is None:
            return
        updated = {**turn, "status": status, "updated_at": utc_now().isoformat()}
        self._turns[turn_id] = updated
        self.emitter.emit(
            "turn.started" if status == "running" else "turn.status_changed",
            {"turn": updated},
        )

    async def _run_submit_chain(
        self,
        conversation_id: str,
        user_message: Any,
        target: str,
        turn_id: str,
        exec_context: ExecutionContext | None = None,
    ) -> None:
        """V0.2 M2：回合 + 队列自动派发链（问题 9）。

        M1.2：最外层 try/except/finally 保证派发前异常也把 Turn/消息推进到
        failed 或 cancelled；正常异常处理仍留在 _run_submit_turn 内。
        V0.3.2 M4：``exec_context`` 是提交时解析的不可变上下文，随链传递。
        """
        try:
            status = await self._run_submit_turn(
                conversation_id, user_message, target, turn_id, exec_context
            )
            if status == "completed":
                # 首次完整回复已经落库后再生成标题，保证命名上下文至少包含
                # 一问一答。失败回合不命名，后续成功回合仍可再次尝试。
                self._schedule_title_generation(conversation_id, target)
            # V0.3.8 T4（契约 §14.1）：任一终态都放行队列——cancelled/failed
            # 照常呈现真实终态与原因，不阻塞后续排队消息。
            if status in _TURN_TERMINAL_STATUSES:
                await self._dispatch_from_inbox(conversation_id)
        except asyncio.CancelledError:
            self._ensure_turn_terminal(turn_id, "cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 - 最后一道状态兜底
            logger.exception("后台回合链异常：%s", conversation_id)
            self._reconcile_failed_turn(conversation_id, turn_id, user_message, exc)
            raise

    def _ensure_turn_terminal(self, turn_id: str, status: str) -> None:
        """若 Turn 尚未终态则推进到指定终态（幂等）。"""
        turn = self._turns.get(turn_id)
        if turn is None or turn.get("status") in {"completed", "failed", "cancelled"}:
            return
        self._emit_turn_status(turn_id, status)

    def _reconcile_failed_turn(
        self,
        conversation_id: str,
        turn_id: str,
        user_message: Any,
        exc: BaseException,
    ) -> None:
        """把漏网的回合异常对账为 failed Turn/失败消息（幂等，不吞错误）。

        若 Turn 已经进入终态（例如派发队列项时异常发生在当前已完成的回合
        之后），不得反向把已完成回合的消息改写成失败。
        """
        turn = self._turns.get(turn_id)
        if turn is not None and turn.get("status") in {
            "completed",
            "failed",
            "cancelled",
        }:
            return
        self._ensure_turn_terminal(turn_id, "failed")
        if user_message is not None:
            self.orchestrator.mark_message_failed(
                conversation_id, user_message.message_id, str(exc)
            )
            self._finalize_streaming_for_conversation(
                conversation_id, user_message.message_id
            )

    async def _dispatch_from_inbox(self, conversation_id: str) -> None:
        """V0.2 M2：持久化队列自动派发——processing → 回合 → 终态删除。

        V0.3.8 T4（契约 §14.1）：回合到达任一终态（completed/failed/
        cancelled）即删除该项并派发下一条；真实终态与原因已在消息流与回合
        记录中呈现，排队项不再回退 queued（避免失败项无限自动重试）。
        M1.2：回合异常（CancelledError 等，无终态回执）在 finally 中把仍为
        processing 的项目退回 queued——该路径没有回合终态呈现，删除会静默
        丢失用户输入。
        """
        while True:
            item = self.store.peek_queue_item(conversation_id)
            if item is None:
                return
            queue_item_id = item["queue_item_id"]
            self.store.set_queue_item_status(queue_item_id, "processing")
            self._emit_queue_changed(conversation_id)
            try:
                exec_context = self._resolve_execution_context(
                    item["conversation_id"]
                )
                user_message = await self.orchestrator.submit_user_message(
                    conversation_id=item["conversation_id"],
                    text=item["text"],
                    target=item["target"],
                    pair_id=exec_context.pair_id,
                )
                turn = self._register_turn(
                    item["conversation_id"], user_message, item["target"]
                )
                status = await self._run_submit_turn(
                    item["conversation_id"],
                    user_message,
                    item["target"],
                    turn["turn_id"],
                    exec_context,
                )
                if status not in _TURN_TERMINAL_STATUSES:
                    # 协议违规：回合链只允许三终态。如实暴露，不允许未知
                    # 状态滞留队列冒充正常派发。
                    raise RuntimeError(
                        f"回合返回未知终态 {status!r}"
                        f"（conversation={conversation_id}，"
                        f"queue_item={queue_item_id}）"
                    )
                self.store.delete_queue_item(queue_item_id)
                self._emit_queue_changed(conversation_id)
            except BaseException:
                items = self.store.list_queue_items(conversation_id)
                if any(
                    candidate["queue_item_id"] == queue_item_id
                    and candidate["status"] == "processing"
                    for candidate in items
                ):
                    self.store.set_queue_item_status(queue_item_id, "queued")
                    self._emit_queue_changed(conversation_id)
                raise

    def _emit_queue_changed(self, conversation_id: str) -> None:
        """V0.2 M2：队列变化推送全量快照（按 position 有序）。"""
        self.emitter.emit(
            "queue.changed",
            {
                "conversation_id": conversation_id,
                "items": self.store.list_queue_items(conversation_id),
            },
        )

    async def _run_submit_turn(
        self,
        conversation_id: str,
        user_message: Any,
        target: str,
        turn_id: str,
        exec_context: ExecutionContext | None = None,
    ) -> str:
        """V0.2 M2：Turn 生命周期——started(running) → completed/failed/cancelled。

        失败仍把用户消息标记 failed（文字保留可重试），与消息状态对账；
        返回终态供派发链决定是否继续。
        """
        self._emit_turn_status(turn_id, "running")
        # V0.3.9 §5：登记本会话当前运行的回合，供首个真实引擎/流式事件
        # 回调把时间戳记到正确回合上。
        self._active_turn_ids[conversation_id] = turn_id
        result = "completed"
        terminal_status = "completed"
        failure_reason: str | None = None
        try:
            if target == "assistant":
                outcome = await self.orchestrator.process_direct_input(
                    conversation_id=conversation_id,
                    user_message=user_message,
                    context=exec_context,
                )
            else:
                outcome = await self.orchestrator.process_character_turn(
                    conversation_id=conversation_id,
                    user_message=user_message,
                    context=exec_context,
                )
                # V039-S4-003：角色本轮声明的长期记忆由服务侧按会话作用域落库。
                self._persist_memory_drafts(
                    conversation_id, tuple(outcome.memory_drafts)
                )
            if outcome.receipt is not None and outcome.receipt.status != "completed":
                result = outcome.receipt.status
                terminal_status = outcome.receipt.status
        except asyncio.CancelledError:
            result = "cancelled"
            terminal_status = "cancelled"
            # M2.2：Sidecar 关闭（stdout 断开/进程退出）触发的任务取消属于传输
            # 关闭路径，不应反向把已经持久化的业务消息改成 cancelled/failed。
            if not self._shutdown:
                self.orchestrator.mark_message_cancelled(
                    conversation_id, user_message.message_id
                )
                self.orchestrator.mark_processing_delegations_cancelled(conversation_id)
            raise
        except Exception as exc:  # noqa: BLE001 - 回合失败转为可见消息状态
            logger.exception("后台回合失败：%s", conversation_id)
            result = "failed"
            terminal_status = "failed"
            # V039-S4-015：可见提示、消息失败原因与日志必须携带同一份真实
            # 原因，异常自述为空时回落到类型名，不产出空壳提示。
            reason = _failure_reason(exc)
            failure_reason = reason
            self.orchestrator.mark_message_failed(
                conversation_id, user_message.message_id, reason
            )
            self.orchestrator.mark_processing_delegations_failed(
                conversation_id, reason
            )
            self.orchestrator.report_system_status(
                conversation_id, f"本次回复失败：{reason}"
            )
        finally:
            # 成功、失败、取消都补发收尾事件。正常消息已经落库时这是
            # 幂等的；若模型在 character.final 前退出，则可解除前端流式占位。
            self._finalize_streaming_for_conversation(
                conversation_id, user_message.message_id
            )
            # 让 turn 终态成为本回合最后一个事件，前端可以把它作为
            # 回合收尾信号，而不会在其后再次看到流式占位。
            self._emit_turn_status(turn_id, terminal_status)
            # V0.3.9 §5：turn 终态落一次指标；usage/tool_rounds 取事件流真实值，
            # 缺失字段为 null（真实零值用 0，绝不估算 token）。
            self._record_turn_metric(
                conversation_id,
                turn_id,
                target,
                terminal_status,
                outcome=outcome if "outcome" in locals() else None,
                failure_reason=failure_reason,
            )
            self._active_turn_ids.pop(conversation_id, None)
        return result

    def _record_turn_metric(
        self,
        conversation_id: str,
        turn_id: str,
        target: str,
        status: str,
        *,
        outcome: Any = None,
        failure_reason: str | None = None,
    ) -> None:
        """把回合终态写为 TurnMetric（幂等：同 turn 重复终态以首次写入为准）。

        契约 §5：未观测或供应商不提供的字段为 null 且键仍存在，真实零值
        用 0；token 只接受服务端真实 usage，绝不估算。``failure_reason``
        是回合链捕获的真实失败原因——调用方持有的消息对象是 frozen 的不
        可变原对象，失败原因只能由这里显式接收，不能从消息反查。
        """
        try:
            turn = self._turns.get(turn_id)
            if turn is None:
                return
            try:
                conversation = self.store.get_conversation(conversation_id)
            except KeyError:
                return
            account_id = self.current_account_id
            project_id = turn.get("project_id") or conversation.project_id or ""
            config = self._load_account_config()
            provider = self.dialogue_provider_name(config)
            model = config.get("dialogue.model") or ""
            engine_type = config.get("engine") or ""
            reasoning_effort = config.get("dialogue.reasoning_effort") or "auto"

            input_tokens: int | None = None
            output_tokens: int | None = None
            total_tokens: int | None = None
            tool_rounds = 0
            engine_turn_id: str | None = None
            task_id: str | None = None
            if outcome is not None:
                for event in outcome.engine_events:
                    if event.type == EngineEventType.USAGE:
                        payload = event.payload
                        input_tokens = _nullable_int(payload.get("input_tokens"))
                        output_tokens = _nullable_int(payload.get("output_tokens"))
                        total_tokens = _nullable_int(payload.get("total_tokens"))
                    elif event.type == EngineEventType.TOOL_STARTED:
                        tool_rounds += 1
                active_turn = self.orchestrator.state.get_for_conversation(conversation_id)
                if active_turn is not None:
                    task_id = active_turn.task_id
                    engine_turn_id = active_turn.engine_turn_id
                elif outcome.task is not None:
                    task_id = outcome.task.task_id
                # 引擎事件里的 engine_turn_id 是逐事件一致的；取最后一条。
                last_engine_events = getattr(outcome, "engine_events", ()) or ()
                if last_engine_events:
                    candidate = last_engine_events[-1].engine_turn_id
                    if candidate:
                        engine_turn_id = candidate

            started_at = turn.get("created_at") or utc_now().isoformat()
            completed_at = utc_now().isoformat()
            duration_ms = _duration_ms(started_at, completed_at)
            # V0.3.9 §5：first_event_at 只取回合链记录的首个真实引擎/流式
            # 事件时间；没有事件（例如立即抛错的失败回合）保持 null，不回落
            # 到被终态刷新过的 updated_at。
            first_event_raw = turn.get("first_event_at")
            first_event_at = (
                datetime.fromisoformat(first_event_raw)
                if isinstance(first_event_raw, str) and first_event_raw
                else None
            )
            first_event_latency_ms = (
                _duration_ms(started_at, first_event_raw)
                if first_event_at is not None
                else None
            )
            failure_type = None
            failure_message = None
            if status == "failed":
                failure_type = "turn_failed"
                failure_message = failure_reason

            metric = TurnMetric(
                account_id=account_id,
                project_id=project_id,
                conversation_id=conversation_id,
                pair_id=conversation.pair_id,
                character_ref=None,
                assistant_identity=None,
                turn_kind="assistant_task" if target == "assistant" else "character_turn",
                turn_id=turn_id,
                task_id=task_id,
                engine_turn_id=engine_turn_id,
                source_message_id=turn.get("source_message_id"),
                provider=provider or None,
                model=model or None,
                engine_type=engine_type or None,
                reasoning_effort=reasoning_effort or None,
                status=status,
                started_at=started_at,
                first_event_at=first_event_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                first_event_latency_ms=first_event_latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                tool_rounds=tool_rounds,
                compression_count=0,
                approval_count=0,
                failure_type=failure_type,
                failure_message=failure_message,
                # 来源身份取 Turn payload 的运行态记录（提交时由传输层注入）。
                origin=turn.get("origin") or "desktop",
                remote_device_key=turn.get("remote_device_key"),
                remote_device_name=turn.get("remote_device_name"),
            )
            self.store.upsert_turn_metric(metric)
        except Exception:  # noqa: BLE001 - 指标记录失败不得影响回合主链路
            logger.exception("回合指标记录失败（turn=%s）", turn_id)

    def _set_conversation_mode(
        self, conversation_id: str, mode: str
    ) -> None:
        """V0.2：模式是后端按会话持久化的独立字段，与推理档位/审批方式/
        发送对象互不覆盖。设置类命令不得回推覆盖它。"""
        self.store.update_conversation_mode(conversation_id, mode)
        self.orchestrator.set_conversation_mode(conversation_id, mode)  # type: ignore[arg-type]

    async def _conversation_set_mode(
        self, params: Mapping[str, Any]
    ) -> dict[str, Any]:
        """V0.2：独立模式命令——只改模式，返回定向响应，不回推整份快照。"""
        conversation_id = str(params.get("conversation_id") or self.current_conversation_id)
        if not conversation_id:
            raise ServiceError("没有当前聊天", code="no_active_conversation")
        mode = self._required_string(params, "mode")
        if mode not in {"chat", "collaboration"}:
            raise ServiceError("mode 必须是 chat 或 collaboration", code="invalid_mode")
        conversation = self._current_account_conversation(conversation_id)
        self._set_conversation_mode(conversation.conversation_id, mode)
        self.emitter.emit(
            "conversation.changed",
            {
                "conversation": self._conversation_payload(
                    self.store.get_conversation(conversation_id)
                )
            },
        )
        return {"conversation_id": conversation_id, "mode": mode}

    async def _task_cancel(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """V0.3.2 M4：定向取消——必须同时校验聊天与任务 id。

        用户切换聊天后，旧界面的取消按钮不得取消新聊天的任务；缺省参数
        保持旧行为（取消首个活动任务，兼容旧前端）。
        """
        conversation_id = str(params.get("conversation_id") or "") or None
        task_id = str(params.get("task_id") or "") or None
        if conversation_id is not None:
            active = self.orchestrator.state.get_for_conversation(conversation_id)
            if active is not None and (task_id is None or active.task_id == task_id):
                # M1.5：先结清该 Turn 的未决审批，让等待中的本地 future 以
                # DENY 完成并回复引擎；随后编排器发送 interrupt/cancel。
                self.approval_broker.cancel_for_conversation(conversation_id)
        return {
            "cancelled": await self.orchestrator.cancel_active_task(
                conversation_id, task_id
            )
        }

    async def _approval_resolve(
        self, params: Mapping[str, Any], *, origin: str = "desktop"
    ) -> dict[str, Any]:
        approval_id = self._required_string(params, "approval_id")
        decision = self._required_string(params, "decision")
        # V0.3.5：origin 由传输层注入（stdin=desktop、WS=remote），前端
        # 参数不可伪造；响应携带 resolved_by 供双端收敛展示。
        outcome = self.approval_broker.resolve(
            approval_id, decision, resolved_by=origin
        )
        return {
            "approval_id": approval_id,
            "accepted": True,
            "resolved_by": outcome["resolved_by"],
            "decision": outcome["decision"],
        }

    async def _voice_vad_set(self, params: Mapping[str, Any]) -> dict[str, Any]:
        enabled = bool(params.get("enabled", False))
        self._voice_state["vad_enabled"] = enabled
        if self.voice_runtime is None:
            self._voice_state["error"] = "语音运行时未启用"
        elif enabled:
            await self.voice_runtime.set_vad_enabled(True)
            self.voice_runtime.start_playback()
        else:
            if self._voice_state["enabled"]:
                # 关闭 VAD 仍要保留采集，PTT 依赖同一条麦克风通道。
                await self.voice_runtime.start_listening(vad_enabled=False)
                self.voice_runtime.start_playback()
            else:
                await self.voice_runtime.stop_listening()
        self._emit_voice_changed()
        return {"voice": self._voice_snapshot()}

    async def _voice_ptt_start(self, params: Mapping[str, Any]) -> dict[str, Any]:
        target = str(params.get("target", "character"))
        if target not in {"character", "assistant"}:
            raise ServiceError(
                "target 必须是 character 或 assistant",
                code="invalid_target",
            )
        if self.voice_runtime is None:
            raise ServiceError("语音运行时未启用", code="voice_unavailable")
        conversation_id = str(
            params.get("conversation_id") or self.current_conversation_id
        )
        conversation = self._current_account_conversation(conversation_id)
        await self._focus_voice_context(conversation_id, conversation.pair_id)
        async with self._voice_ptt_lock:
            # M4.3：开始录音时捕获不可变上下文，ASR 提交不再读切换后的
            # current_conversation_id。
            self._ptt_voice_context = {
                "conversation_id": conversation_id,
                "target": target,
                "pair_id": conversation.pair_id,
            }
            try:
                await self.voice_runtime.push_to_talk_start(target=target)
            except Exception as exc:  # noqa: BLE001 - 保留真实启动失败
                self._ptt_voice_context = None
                self._voice_state["ptt"] = False
                self._on_voice_error(f"按键说话启动失败：{exc}")
                raise
            self._voice_state["error"] = None
            self._voice_state["ptt"] = True
            self._emit_voice_changed()
            return {"voice": self._voice_snapshot()}

    async def _voice_ptt_stop(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        if self.voice_runtime is None:
            raise ServiceError("语音运行时未启用", code="voice_unavailable")
        async with self._voice_ptt_lock:
            try:
                await self.voice_runtime.push_to_talk_stop()
            except Exception as exc:  # noqa: BLE001 - ASR 收尾/后台调度失败继续上抛
                self._ptt_voice_context = None
                self._on_voice_error(f"语音提交失败：{exc}")
                raise
            finally:
                # ASR 收尾或角色提交失败都不能留下“聆听中”假状态。
                self._voice_state["ptt"] = False
                self._emit_voice_changed()
            return {"voice": self._voice_snapshot()}

    async def _voice_tts_stop(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        if self.voice_runtime is not None:
            # 停止可能需要等待播放器线程完成当前 PortAudio 写入；把同步
            # 原生清理移出事件循环，避免按钮请求卡住 Sidecar 协议处理。
            await self.voice_runtime.stop_speaking_async()
        self._voice_state["tts"] = "idle"
        self._emit_voice_changed()
        return {"voice": self._voice_snapshot()}

    # ------------------------------------------------------------------ M3 占位
    # 下列处理器在设置/账号阶段实现；此处先注册保证路由可用，
    # 未实现时返回明确的 ServiceError，不静默吞掉。

    async def _app_reconnect(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        raise ServiceError("应用重连由桌面进程负责，Sidecar 侧无需重建", code="not_implemented")

    async def _queue_edit(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """编辑队列项文本（仅尚未派发的 queued 项）。"""
        queue_item_id = self._required_string(params, "queue_item_id")
        text = self._required_string(params, "text")
        if not text.strip():
            raise ServiceError("队列项文本不能为空", code="invalid_text")
        try:
            self._current_account_queue_item(queue_item_id)
            item = self.store.edit_queue_item(queue_item_id, text)
        except KeyError as exc:
            raise ServiceError("队列项不存在或已派发", code="queue_item_not_found") from exc
        self._emit_queue_changed(item["conversation_id"])
        return {"queue_item": item}

    async def _queue_withdraw(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """撤回队列项（不再自动派发，状态置 withdrawn）。"""
        queue_item_id = self._required_string(params, "queue_item_id")
        try:
            self._current_account_queue_item(queue_item_id)
            item = self.store.withdraw_queue_item(queue_item_id)
        except KeyError as exc:
            raise ServiceError("队列项不存在", code="queue_item_not_found") from exc
        self._emit_queue_changed(item["conversation_id"])
        return {"queue_item": item}

    async def _queue_prioritize(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """把队列项置队首（steer）。"""
        queue_item_id = self._required_string(params, "queue_item_id")
        try:
            self._current_account_queue_item(queue_item_id)
            self.store.prioritize_queue_item(queue_item_id)
        except KeyError as exc:
            raise ServiceError("队列项不存在或已派发", code="queue_item_not_found") from exc
        item = self.store.get_queue_item(queue_item_id)
        self._emit_queue_changed(item["conversation_id"])
        return {"queue_item": item}

    def _current_account_queue_item(self, queue_item_id: str) -> dict[str, Any]:
        item = self.store.get_queue_item(queue_item_id)
        if item["account_id"] != self.current_account_id:
            raise ServiceError("队列项不属于当前账号", code="queue_account_mismatch")
        return item

    async def _voice_tts_play(
        self,
        params: Mapping[str, Any],
        *,
        origin: str = "desktop",
        device_key: str | None = None,
    ) -> dict[str, Any]:
        """逐条朗读：按 message_id 从会话取消息文本，重新合成入队（可重播）。"""
        self._require_playback_control(origin=origin, device_key=device_key)
        if self.voice_runtime is None:
            raise ServiceError("语音运行时未启用", code="voice_unavailable")
        conversation_id = str(
            params.get("conversation_id") or self.current_conversation_id
        )
        conversation = self._current_account_conversation(conversation_id)
        await self._focus_voice_context(conversation_id, conversation.pair_id)
        message_id = self._required_string(params, "message_id")
        snapshot = self.store.load_conversation(conversation_id)
        message = next(
            (m for m in snapshot["messages"] if m.message_id == message_id),
            None,
        )
        if message is None:
            raise ServiceError("消息不存在", code="message_not_found")
        if message.source == MessageSource.ASSISTANT:
            # V0.3.3：助手永不使用 TTS——手动重播助手消息在语音入口被拒。
            raise ServiceError(
                "助手语音已禁用，不可朗读助手消息",
                code="assistant_tts_disabled",
            )
        self._require_playback_control(origin=origin, device_key=device_key)
        self.voice_runtime.replay_message(message)
        return {"voice": self._voice_snapshot()}

    async def _voice_tts_skip(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        if self.voice_runtime is None:
            raise ServiceError("语音运行时未启用", code="voice_unavailable")
        await self.voice_runtime.skip_playing_async()
        return {"voice": self._voice_snapshot()}

    async def _voice_preview(
        self,
        params: Mapping[str, Any],
        *,
        origin: str = "desktop",
        device_key: str | None = None,
    ) -> dict[str, Any]:
        """语音试听：按指定文本合成入队；voice_id 缺省取当前有效角色音色。

        V0.3.2 M6：账号 BYOK 模式允许试听当前账号已生成的全部 manifest
        音色；开发机作者音色仍只允许当前搭档。显式传入未知 ID 时如实
        报错，不能静默替换成角色音色。voice_id 缺省时使用当前角色音色。
        """
        self._require_playback_control(origin=origin, device_key=device_key)
        if self.voice_runtime is None:
            raise ServiceError("语音运行时未启用", code="voice_unavailable")
        text = self._required_string(params, "text")
        if not is_readable_text(text):
            raise ServiceError("试听文本为空或只有标点", code="invalid_text")
        config = self._load_account_config()
        voices = resolve_effective_voice_profile(
            account_config=config,
            settings=Settings.overlay(Settings.from_environment(), config),
            pair_config=self.pair_config,
        )
        if voices.state == "account":
            try:
                manifest = load_reference_voice_manifest()
            except VoiceManifestError as exc:
                raise ServiceError(str(exc), code="voice_manifest_error") from exc
            allowed_voice_ids = {
                config.get(entry.profile_key)
                for entry in manifest
                if config.get(entry.profile_key)
            }
        else:
            allowed_voice_ids = {
                voice_id
                for voice_id in (
                    voices.character_voice_id,
                    voices.assistant_voice_id,
                )
                if voice_id
            }

        requested_voice_id = params.get("voice_id")
        if requested_voice_id is not None:
            if (
                not isinstance(requested_voice_id, str)
                or not requested_voice_id.strip()
                or requested_voice_id not in allowed_voice_ids
            ):
                raise ServiceError(
                    "该音色 ID 不属于当前账号已生成的专属音色",
                    code="voice_preview_not_allowed",
                )
            voice_id = requested_voice_id
        else:
            voice_id = voices.character_voice_id
        if voice_id is None and not voices.character_voice_id:
            raise ServiceError(
                "当前搭档的角色音色尚未生成，请先在语音页生成专属音色",
                code="voice_not_provisioned",
            )
        assistant_ids = assistant_speaker_ids()
        if voices.state == "account":
            assistant_preview_ids = {
                config[entry.profile_key]
                for entry in manifest
                if entry.speaker_id in assistant_ids and config.get(entry.profile_key)
            }
        else:
            assistant_preview_ids = (
                {voices.assistant_voice_id} if voices.assistant_voice_id else set()
            )
        if voice_id in assistant_preview_ids:
            raise ServiceError(
                "助手语音已禁用，不可作为试听音色",
                code="assistant_tts_disabled",
            )
        self.voice_runtime.enqueue_text(text, voice_id=voice_id)
        return {"voice": self._voice_snapshot()}

    # ------------------------------------------------------------------ V0.3.3 角色卡

    _BUILTIN_PREFIX = "builtin:"

    def _builtin_card_summaries(self) -> list[dict[str, Any]]:
        """内置角色只读摘要：来自 pair 目录，不入库、不可编辑。"""
        config = self._load_account_config()
        active_id = self.card_repository.get_active_card_id()
        summaries: list[dict[str, Any]] = []
        for pair in self.pair_catalog:
            speaker = pair.character.id
            voice_state = (
                "voice_ready"
                if (config.get(f"voice.profile.{speaker}.voice_id") or "").strip()
                else "voice_unconfigured"
            )
            summaries.append(
                {
                    "card_id": f"{self._BUILTIN_PREFIX}{speaker}",
                    "name": pair.character.name,
                    "state": "saved",
                    "source": "builtin",
                    "updated_at": "",
                    "has_avatar": False,
                    "voice_state": voice_state,
                    "active": active_id == f"{self._BUILTIN_PREFIX}{speaker}",
                    "read_only": True,
                }
            )
        return summaries

    def _card_avatar_payload(self, card: CharacterCard) -> dict[str, Any] | None:
        """card.get 的 avatar 字段：有资产时随响应整体下发（契约 §2.5）。"""
        hsr = card.hsr
        if hsr is None or hsr.avatar_asset is None or not hsr.avatar_asset.asset_id:
            return None
        try:
            import base64

            data, mime = self.asset_service.get_asset(hsr.avatar_asset.asset_id)
        except CharacterAssetError as exc:
            # 卡 JSON 明确引用了头像但文件/记录损坏：如实失败（Let It Fail），
            # 不能合成 avatar: null 让界面误以为角色没有头像。
            raise ServiceError(
                f"头像资产读取失败：{exc}", code="card_avatar_missing"
            ) from exc
        return {
            "mime_type": mime,
            "data_base64": base64.b64encode(data).decode("ascii"),
        }

    def _require_writable_card(self, card_id: str) -> None:
        if card_id.startswith(self._BUILTIN_PREFIX):
            raise ServiceError(
                "内置角色为只读，不能修改、归档或删除", code="card_read_only"
            )

    async def _card_list(self, params: Mapping[str, Any]) -> dict[str, Any]:
        include_archived = bool(params.get("include_archived", False))
        cards = [
            {
                "card_id": s.card_id,
                "name": s.name,
                "state": s.state,
                "source": s.source,
                "updated_at": s.updated_at,
                "has_avatar": s.has_avatar,
                "voice_state": s.voice_state,
                "active": s.active,
                "read_only": False,
            }
            for s in self.card_repository.list_cards(
                include_archived=include_archived
            )
        ]
        return {"cards": cards + self._builtin_card_summaries()}

    async def _card_get(self, params: Mapping[str, Any]) -> dict[str, Any]:
        card_id = str(params.get("card_id") or "")
        if not card_id:
            raise ServiceError("card.get 需要 card_id", code="invalid_params")
        if card_id.startswith(self._BUILTIN_PREFIX):
            speaker = card_id[len(self._BUILTIN_PREFIX):]
            pair = next(
                (p for p in self.pair_catalog if p.character.id == speaker), None
            )
            if pair is None:
                raise ServiceError("内置角色不存在", code="card_not_found")
            card = CharacterCard(
                name=pair.character.name,
                creator="HSR Partner Harness",
                tags=["builtin"],
                creator_notes=f"内置角色，提示词来源：{pair.character.prompt}",
            )
            return {
                "card_id": card_id,
                "state": "saved",
                "source": "builtin",
                "created_at": "",
                "updated_at": "",
                "card": json.loads(dump_card_v3(card)),
                "read_only": True,
            }
        try:
            record = self.card_repository.get_card(card_id)
        except KeyError as exc:
            raise ServiceError("角色卡不存在", code="card_not_found") from exc
        return {
            "card_id": record.card_id,
            "state": record.state,
            "source": record.source,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "card": json.loads(dump_card_v3(record.card)),
            "read_only": False,
            # V0.3.5：头像随 get 整体下发（契约 §2.5）；列表摘要仍只有布尔。
            "avatar": self._card_avatar_payload(record.card),
        }

    async def _card_create_draft(self, params: Mapping[str, Any]) -> dict[str, Any]:
        name = str(params.get("name") or "").strip()
        if not name:
            raise ServiceError("card.create_draft 需要 name", code="invalid_params")
        record = self.card_repository.create_draft(name)
        return {"card_id": record.card_id, "state": record.state}

    async def _card_update(self, params: Mapping[str, Any]) -> dict[str, Any]:
        card_id = str(params.get("card_id") or "")
        self._require_writable_card(card_id)
        raw_card = params.get("card")
        if not isinstance(raw_card, Mapping):
            raise ServiceError(
                "card.update 需要 card（角色卡 JSON 对象）", code="invalid_params"
            )
        try:
            parsed = load_card_payload(dict(raw_card))
        except Exception as exc:  # 解析失败如实上抛，不做兜底
            raise ServiceError(
                f"角色卡数据非法：{exc}", code="card_invalid_payload"
            ) from exc
        try:
            record = self.card_repository.update_card(card_id, parsed.card)
        except KeyError as exc:
            raise ServiceError("角色卡不存在", code="card_not_found") from exc
        return {"card_id": record.card_id, "updated_at": record.updated_at}

    async def _card_duplicate(self, params: Mapping[str, Any]) -> dict[str, Any]:
        card_id = str(params.get("card_id") or "")
        if card_id.startswith(self._BUILTIN_PREFIX):
            # V0.3.5 Codex 复核：导出流程建议「先复制再导出」，复制入口必须
            # 真实可用——内置卡从 pair 定义生成可编辑副本（无资产，无引用）。
            speaker = card_id[len(self._BUILTIN_PREFIX) :]
            pair = next(
                (p for p in self.pair_catalog if p.character.id == speaker), None
            )
            if pair is None:
                raise ServiceError("内置角色不存在", code="card_not_found")
            builtin_card = CharacterCard(
                name=pair.character.name,
                creator="HSR Partner Harness",
                tags=["builtin"],
                creator_notes=f"内置角色，提示词来源：{pair.character.prompt}",
            )
            record = self.card_repository.import_card(builtin_card, as_duplicate=True)
            return {"card_id": record.card_id, "name": record.card.name}
        try:
            record = self.card_repository.duplicate_card(card_id)
        except KeyError as exc:
            raise ServiceError("角色卡不存在", code="card_not_found") from exc
        # duplicate_card 只深拷贝 JSON：副本继续引用原卡资产 ID，删除原卡会
        # 连带毁掉副本（Codex P1 #5）。此处真实复制资产文件并把副本引用改向
        # 新资产 ID。
        mapping = self._copy_card_assets(card_id, record.card_id)
        card = record.card
        hsr = card.hsr
        if hsr is not None:
            if hsr.avatar_asset is not None and hsr.avatar_asset.asset_id in mapping:
                hsr.avatar_asset.asset_id = mapping[hsr.avatar_asset.asset_id]
            if (
                hsr.voice_profile is not None
                and hsr.voice_profile.reference_audio_asset in mapping
            ):
                hsr.voice_profile.reference_audio_asset = mapping[
                    hsr.voice_profile.reference_audio_asset
                ]
            self.card_repository.update_card(record.card_id, card)
        return {"card_id": record.card_id, "name": card.name}

    def _copy_card_assets(self, source_card_id: str, target_card_id: str) -> dict[str, str]:
        """把源卡的全部受管理资产真实复制归属到目标卡；返回旧→新 asset_id 映射。"""
        mapping: dict[str, str] = {}
        for record in self.asset_service.list_assets_for_card(source_card_id):
            data, mime = self.asset_service.get_asset(record.asset_id)
            new_id = self.asset_service.store_asset(
                card_id=target_card_id,
                data=data,
                kind=record.kind,
                mime_type=mime,
                source="duplicate",
                source_ref=record.asset_id,
                extension=Path(record.file_path).suffix.lstrip("."),
            )
            mapping[record.asset_id] = new_id
        return mapping

    async def _card_archive(self, params: Mapping[str, Any]) -> dict[str, Any]:
        card_id = str(params.get("card_id") or "")
        self._require_writable_card(card_id)
        try:
            self.card_repository.archive_card(card_id)
        except KeyError as exc:
            raise ServiceError("角色卡不存在", code="card_not_found") from exc
        except ValueError as exc:
            raise ServiceError(str(exc), code="card_invalid_state") from exc
        return {"card_id": card_id, "archived": True}

    async def _card_delete(self, params: Mapping[str, Any]) -> dict[str, Any]:
        card_id = str(params.get("card_id") or "")
        self._require_writable_card(card_id)
        confirm = params.get("confirm") is True
        try:
            self.card_repository.delete_card(card_id, confirm=confirm)
        except ValueError as exc:
            raise ServiceError(str(exc), code="card_confirm_required") from exc
        # V0.3.5：删除卡时同步清理头像与参考音频资产（契约 §2.5）。
        self.asset_service.delete_assets_for_card(card_id)
        return {"card_id": card_id, "deleted": True}

    async def _card_select_active(self, params: Mapping[str, Any]) -> dict[str, Any]:
        card_id = str(params.get("card_id") or "")
        self._require_writable_card(card_id)
        try:
            self.card_repository.select_active(card_id)
        except ValueError as exc:
            raise ServiceError(str(exc), code="card_invalid_state") from exc
        return {"card_id": card_id}

    # ------------------------------------------------------------------ V0.3.5 角色卡导入导出与发布

    @staticmethod
    def _compat_report_payload(report: Any) -> dict[str, Any]:
        return {
            "applied": list(report.applied),
            "preserved": list(report.preserved),
            "not_executed": list(report.not_executed),
            "normalized_from_root": list(report.normalized_from_root),
            "warnings": list(report.warnings),
            "errors": list(report.errors),
        }

    def _peek_card_from_path(self, params: Mapping[str, Any]):
        """读取并解析 JSON 角色卡文件（不落库）；失败保留原始错误。"""
        path_text = self._required_string(params, "path")
        path = Path(path_text).expanduser()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ServiceError(
                f"读取角色卡文件失败：{exc}", code="card_import_failed"
            ) from exc
        try:
            return load_card_json(text)
        except CardImportError as exc:
            raise ServiceError(
                f"角色卡解析失败：{exc}", code="card_import_failed"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - 非预期解析错误同样如实暴露
            raise ServiceError(
                f"角色卡解析失败：{exc}", code="card_import_failed"
            ) from exc

    def _import_preview_payload(
        self,
        card: CharacterCard,
        report: Any,
        *,
        format: str = "json",
        avatar_available: bool | None = None,
        avatar_width: int | None = None,
        avatar_height: int | None = None,
    ) -> dict[str, Any]:
        if avatar_available is None:
            # SillyTavern 惯例：根级 avatar 为 "none" 字符串表示无头像文件，
            # 不能按 truthy 字符串误判为有头像。
            avatar_available = (
                str(card.root_extras.get("avatar") or "").strip().lower()
                not in ("", "none")
            )
        return {
            "name": card.name,
            "spec_version": card.spec_version or "2.0",
            # V0.3.7 契约 §1.1：两分支统一 preview 形状，format 区分来源。
            "format": format,
            "avatar_available": avatar_available,
            "avatar_width": avatar_width,
            "avatar_height": avatar_height,
            "greeting_count": card.greeting_count(),
            "world_book_entries": (
                len(card.character_book.entries)
                if card.character_book is not None
                else 0
            ),
            "tags": list(card.tags),
            "report": self._compat_report_payload(report),
        }

    async def _card_peek_import(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """card.peek_import（card.peek_import_json 的规范名，同一 handler）。

        契约 §1.1：先读文件前 8 字节与 PNG 签名比对（文件签名优先，不信任
        扩展名）；PNG 签名命中 → PNG 分支，否则按 UTF-8 文本走 JSON 分支。
        失败一律包装为 ``card_import_failed``，message 携带原始错误文本。
        """
        path_text = self._required_string(params, "path")
        path = Path(path_text).expanduser()
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError as exc:
            raise ServiceError(
                f"读取角色卡文件失败：{exc}", code="card_import_failed"
            ) from exc
        if data.startswith(PNG_SIGNATURE):
            return self._peek_import_png(data)
        # JSON 分支：行为与现状一致（UTF-8 文本 → load_card_json）。
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ServiceError(
                f"角色卡解析失败：{exc}", code="card_import_failed"
            ) from exc
        try:
            result = load_card_json(text)
        except CardImportError as exc:
            raise ServiceError(
                f"角色卡解析失败：{exc}", code="card_import_failed"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - 非预期解析错误同样如实暴露
            raise ServiceError(
                f"角色卡解析失败：{exc}", code="card_import_failed"
            ) from exc
        return {
            "preview": self._import_preview_payload(
                result.card, result.report, format="json"
            )
        }

    def _peek_import_png(self, data: bytes) -> dict[str, Any]:
        """PNG 分支：字节 → read_png_card；头像尺寸经 png_image_dimensions。

        头像尺寸解析失败（None）如实返回 None 并追加 warnings「头像尺寸
        未能解析」；PngCardError/CardImportError 均包装为 card_import_failed。
        """
        try:
            result = read_png_card(data)
        except PngCardError as exc:
            raise ServiceError(
                f"角色卡解析失败：{exc}", code="card_import_failed"
            ) from exc
        except CardImportError as exc:
            raise ServiceError(
                f"角色卡解析失败：{exc}", code="card_import_failed"
            ) from exc
        dimensions = png_image_dimensions(data)
        if dimensions is None:
            result.report.warnings.append("头像尺寸未能解析")
        return {
            "preview": self._import_preview_payload(
                result.card,
                result.report,
                format="png",
                avatar_available=True,
                avatar_width=dimensions[0] if dimensions is not None else None,
                avatar_height=dimensions[1] if dimensions is not None else None,
            )
        }

    async def _card_import_json(self, params: Mapping[str, Any]) -> dict[str, Any]:
        result = self._peek_card_from_path(params)
        as_duplicate = params.get("as_duplicate") is True
        record = self.card_repository.import_card(
            result.card, as_duplicate=as_duplicate
        )
        return {
            "card_id": record.card_id,
            "name": record.card.name,
            "state": record.state,
            "report": self._compat_report_payload(result.report),
        }

    async def _card_export_json(self, params: Mapping[str, Any]) -> dict[str, Any]:
        card_id = self._required_string(params, "card_id")
        if card_id.startswith(self._BUILTIN_PREFIX):
            raise ServiceError(
                "内置角色为只读，请先复制为可编辑卡再导出", code="card_read_only"
            )
        path_text = self._required_string(params, "path")
        path = Path(path_text).expanduser()
        try:
            record = self.card_repository.get_card(card_id)
        except KeyError as exc:
            raise ServiceError("角色卡不存在", code="card_not_found") from exc
        payload = dump_card_v3(record.card)
        try:
            path.write_text(payload, encoding="utf-8")
        except OSError as exc:
            raise ServiceError(
                f"写出角色卡文件失败：{exc}", code="card_export_failed"
            ) from exc
        avatar_saved = False
        if params.get("save_avatar") is True:
            hsr = record.card.hsr
            asset_id = (
                hsr.avatar_asset.asset_id
                if hsr is not None and hsr.avatar_asset is not None
                else ""
            )
            if asset_id:
                data = b""
                mime = ""
                try:
                    data, mime = self.asset_service.get_asset(asset_id)
                except Exception:  # noqa: BLE001 - 头像缺失时如实不另存
                    data, mime = b"", ""
                if data:
                    extension = (
                        mime.split("/")[-1].split(";")[0] or "png"
                    )
                    avatar_path = path.with_suffix(f".avatar.{extension}")
                    try:
                        avatar_path.write_bytes(data)
                        avatar_saved = True
                    except OSError as exc:
                        raise ServiceError(
                            f"另存头像失败：{exc}", code="card_export_failed"
                        ) from exc
        return {"exported": True, "path": str(path), "avatar_saved": avatar_saved}

    async def _card_import_png(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """card.import_png：PNG 字节入库并登记头像资产（契约 §1.2）。

        定稿四步：字节 → read_png_card → import_card（as_duplicate 改名）→
        store_asset（PNG 原始字节即头像）→ 回写 card.hsr.avatar_asset。
        解析失败 → card_import_failed；资产写入失败 → card_import_failed
        携带 CharacterAssetError 原文（导入已落库时如实报告，不回滚不伪造）。
        """
        path_text = self._required_string(params, "path")
        path = Path(path_text).expanduser()
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ServiceError(
                f"读取角色卡文件失败：{exc}", code="card_import_failed"
            ) from exc
        try:
            result = read_png_card(data)
        except PngCardError as exc:
            raise ServiceError(
                f"角色卡解析失败：{exc}", code="card_import_failed"
            ) from exc
        except CardImportError as exc:
            raise ServiceError(
                f"角色卡解析失败：{exc}", code="card_import_failed"
            ) from exc
        as_duplicate = params.get("as_duplicate") is True
        record = self.card_repository.import_card(
            result.card, as_duplicate=as_duplicate
        )
        try:
            asset_id = self.asset_service.store_asset(
                card_id=record.card_id,
                data=data,
                kind="avatar",
                mime_type="image/png",
                source="png_import",
                source_ref=path.name,
            )
        except CharacterAssetError as exc:
            raise ServiceError(
                f"写入角色卡头像资产失败：{exc}", code="card_import_failed"
            ) from exc
        # 回写卡 JSON 的 hsr.avatar_asset（经 update_card，保持 updated_at 语义）。
        card = record.card
        if card.hsr is None:
            from pair_harness.character_cards.models import HsrExtension

            card.hsr = HsrExtension()
        card.hsr.avatar_asset = AvatarAsset(
            asset_id=asset_id,
            source="png_import",
            source_ref=path.name,
            mime_type="image/png",
            exported_in_png=True,
        )
        self.card_repository.update_card(record.card_id, card)
        return {
            "card_id": record.card_id,
            "name": record.card.name,
            "state": record.state,
            "report": self._compat_report_payload(result.report),
        }

    async def _card_export_png(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """card.export_png：把卡头像 + ccv3 元数据导出为单文件 PNG（契约 §1.3）。

        前置：卡存在且可写；卡当前头像必须可取回。无头像或 get_asset 失败
        → ``card_export_failed``（message 追加原始错误）；PNG 合成/写文件
        失败同样如实携带原文。不合成默认图。
        """
        card_id = self._required_string(params, "card_id")
        self._require_writable_card(card_id)
        path_text = self._required_string(params, "path")
        path = Path(path_text).expanduser()
        try:
            record = self.card_repository.get_card(card_id)
        except KeyError as exc:
            raise ServiceError("角色卡不存在", code="card_not_found") from exc
        hsr = record.card.hsr
        avatar_asset = hsr.avatar_asset if hsr is not None else None
        if avatar_asset is None or not avatar_asset.asset_id:
            raise ServiceError(
                "卡未设置头像，请先设置头像后再导出 PNG", code="card_export_failed"
            )
        try:
            avatar_bytes, _mime = self.asset_service.get_asset(avatar_asset.asset_id)
        except (CharacterAssetError, KeyError) as exc:
            raise ServiceError(
                f"卡未设置头像，请先设置头像后再导出 PNG（原始错误：{exc}）",
                code="card_export_failed",
            ) from exc
        try:
            png_bytes = write_png_card(record.card, avatar_bytes)
        except PngCardError as exc:
            raise ServiceError(
                f"合成 PNG 角色卡失败：{exc}", code="card_export_failed"
            ) from exc
        try:
            path.write_bytes(png_bytes)
        except OSError as exc:
            raise ServiceError(
                f"写出角色卡文件失败：{exc}", code="card_export_failed"
            ) from exc
        extensions = sorted(record.card.extensions.keys())
        if record.card.hsr is not None:
            extensions = sorted(set(extensions) | {"hsr"})
        return {
            "exported": True,
            "path": str(path),
            "name": record.card.name,
            "spec_version": record.card.spec_version or "2.0",
            "greeting_count": record.card.greeting_count(),
            "world_book_entries": (
                len(record.card.character_book.entries)
                if record.card.character_book is not None
                else 0
            ),
            "extensions": extensions,
        }

    async def _card_publish(self, params: Mapping[str, Any]) -> dict[str, Any]:
        card_id = self._required_string(params, "card_id")
        self._require_writable_card(card_id)
        try:
            record = self.card_repository.get_card(card_id)
        except KeyError as exc:
            raise ServiceError("角色卡不存在", code="card_not_found") from exc
        if record.state == "draft":
            labels = {"name": "角色名称", "first_mes": "第一条消息"}
            missing = [
                labels[key]
                for key, value in (
                    ("name", record.card.name.strip()),
                    ("first_mes", record.card.first_mes.strip()),
                )
                if not value
            ]
            if missing:
                raise ServiceError(
                    "完成创建前必填：" + "、".join(missing),
                    code="card_publish_invalid",
                )
        published = self.card_repository.publish_card(card_id)
        return {"card_id": card_id, "state": published.state}

    # ------------------------------------------------------------------ V0.3.5 头像资产

    @classmethod
    def _probe_image_mime(cls, data: bytes) -> str | None:
        if data[:12] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        return None

    def _delete_avatar_assets(self, card_id: str) -> None:
        for record in self.asset_service.list_assets_for_card(card_id):
            if record.kind == "avatar":
                self.asset_service.delete_asset(record.asset_id)

    async def _card_set_avatar(self, params: Mapping[str, Any]) -> dict[str, Any]:
        card_id = self._required_string(params, "card_id")
        self._require_writable_card(card_id)
        path_text = self._required_string(params, "path")
        path = Path(path_text).expanduser()
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ServiceError(
                f"读取头像文件失败：{exc}", code="card_avatar_invalid"
            ) from exc
        if len(data) > 5 * 1024 * 1024:
            raise ServiceError("头像文件超过 5MB 上限", code="card_avatar_too_large")
        mime = self._probe_image_mime(data)
        if mime is None:
            raise ServiceError(
                "头像仅支持 PNG / JPEG / WebP 图片", code="card_avatar_unsupported"
            )
        try:
            record = self.card_repository.get_card(card_id)
        except KeyError as exc:
            raise ServiceError("角色卡不存在", code="card_not_found") from exc
        self._delete_avatar_assets(card_id)
        extension = (
            "png" if mime == "image/png" else ("webp" if mime == "image/webp" else "jpg")
        )
        asset_id = self.asset_service.store_asset(
            card_id=card_id,
            data=data,
            kind="avatar",
            mime_type=mime,
            source="user_upload",
            source_ref=path.name,
            extension=extension,
        )
        card = record.card
        if card.hsr is None:
            from pair_harness.character_cards.models import HsrExtension

            card.hsr = HsrExtension()
        from pair_harness.character_cards.models import AvatarAsset

        card.hsr.avatar_asset = AvatarAsset(
            asset_id=asset_id,
            source="user_upload",
            source_ref=path.name,
            mime_type=mime,
        )
        self.card_repository.update_card(card_id, card)
        return {"card_id": card_id, "asset_id": asset_id, "mime_type": mime}

    async def _card_remove_avatar(self, params: Mapping[str, Any]) -> dict[str, Any]:
        card_id = self._required_string(params, "card_id")
        self._require_writable_card(card_id)
        try:
            record = self.card_repository.get_card(card_id)
        except KeyError as exc:
            raise ServiceError("角色卡不存在", code="card_not_found") from exc
        self._delete_avatar_assets(card_id)
        card = record.card
        if card.hsr is not None and card.hsr.avatar_asset is not None:
            card.hsr.avatar_asset = None
            self.card_repository.update_card(card_id, card)
        return {"card_id": card_id, "removed": True}

    # ------------------------------------------------------------------ V0.3.5 角色卡音色

    _REFERENCE_AUDIO_LIMIT = 10 * 1024 * 1024

    @staticmethod
    def _probe_wav_duration(data: bytes) -> float | None:
        """WAV 时长精确探测；非法 WAV 返回 None（不猜测）。"""
        import io as _io
        import wave

        try:
            with wave.open(_io.BytesIO(data)) as handle:
                return handle.getnframes() / float(handle.getframerate())
        except Exception:  # noqa: BLE001 - 探测失败如实返回 None
            return None

    async def _voice_card_bind_reference(
        self, params: Mapping[str, Any]
    ) -> dict[str, Any]:
        card_id = self._required_string(params, "card_id")
        self._require_writable_card(card_id)
        path_text = self._required_string(params, "path")
        path = Path(path_text).expanduser()
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ServiceError(
                f"读取参考音频失败：{exc}", code="voice_reference_invalid"
            ) from exc
        extension = path.suffix.lower().lstrip(".")
        mime_by_ext = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4"}
        mime = mime_by_ext.get(extension)
        if mime is None:
            raise ServiceError(
                "参考音频仅支持 WAV / MP3 / M4A", code="voice_reference_invalid"
            )
        if len(data) > self._REFERENCE_AUDIO_LIMIT:
            raise ServiceError(
                "参考音频超过 10MB 上限", code="voice_reference_invalid"
            )
        # WAV 本地精确校验 60 秒边界；MP3/M4A 不做不可靠的近似时长判断，
        # 大小之外交由 DashScope 真实裁决并如实回显错误（不猜测时长）。
        duration = self._probe_wav_duration(data) if extension == "wav" else None
        if duration is not None and duration > 60.0:
            raise ServiceError(
                f"参考音频 {duration:.0f} 秒，超过 60 秒上限",
                code="voice_reference_invalid",
            )
        try:
            record = self.card_repository.get_card(card_id)
        except KeyError as exc:
            raise ServiceError("角色卡不存在", code="card_not_found") from exc
        asset_id = self.asset_service.store_asset(
            card_id=card_id,
            data=data,
            kind="reference_audio",
            mime_type=mime,
            source="user_upload",
            source_ref=path.name,
            extension=extension,
        )
        card = record.card
        if card.hsr is None:
            from pair_harness.character_cards.models import HsrExtension

            card.hsr = HsrExtension()
        if card.hsr.voice_profile is None:
            from pair_harness.character_cards.models import VoiceProfile

            card.hsr.voice_profile = VoiceProfile()
        card.hsr.voice_profile.reference_audio_asset = asset_id
        self.card_repository.update_card(card_id, card)
        return {
            "card_id": card_id,
            "asset_id": asset_id,
            "duration_seconds": duration,
            "size_bytes": len(data),
            "mime_type": mime,
        }

    def _card_provision_emit(
        self,
        card_id: str,
        state: str,
        *,
        voice_id: str | None = None,
        error: str | None = None,
    ) -> None:
        self.emitter.emit(
            "voice.card_provision_changed",
            {
                "card_id": card_id,
                "state": state,
                "voice_id": voice_id,
                "error": error,
            },
        )

    @staticmethod
    def _default_prefix(card_name: str) -> str:
        cleaned = "".join(
            ch for ch in card_name.lower() if ch.isascii() and ch.isalnum()
        )[:10]
        return cleaned or "card"

    async def _voice_card_create(self, params: Mapping[str, Any]) -> dict[str, Any]:
        card_id = self._required_string(params, "card_id")
        self._require_writable_card(card_id)
        mode = self._required_string(params, "mode")
        if mode not in {"clone", "design"}:
            raise ServiceError("mode 必须是 clone 或 design", code="invalid_params")
        lock = self._card_provision_locks.setdefault(card_id, asyncio.Lock())
        if lock.locked():
            raise ServiceError(
                "该角色卡正在创建音色，请等待完成后再试",
                code="voice_card_provision_in_progress",
            )
        async with lock:
            config = self._load_account_config()
            api_key = (config.get("voice.api_key") or "").strip()
            base_url = (config.get("voice.base_url") or "").strip()
            if not api_key or not base_url:
                raise ServiceError(
                    "请先在语音页保存 DashScope API Key 与服务地址，再为角色创建音色",
                    code="voice_not_configured",
                )
            try:
                record = self.card_repository.get_card(card_id)
            except KeyError as exc:
                raise ServiceError("角色卡不存在", code="card_not_found") from exc
            card = record.card
            prefix = (
                str(params.get("prefix") or "").strip()
                or self._default_prefix(card.name)
            )
            if not (
                prefix.isascii()
                and prefix.isalnum()
                and prefix.islower()
                and len(prefix) <= 10
            ):
                raise ServiceError(
                    "prefix 必须是 ≤10 位小写字母/数字", code="voice_invalid_request"
                )
            if card.hsr is None:
                from pair_harness.character_cards.models import HsrExtension

                card.hsr = HsrExtension()
            if card.hsr.voice_profile is None:
                from pair_harness.character_cards.models import VoiceProfile

                card.hsr.voice_profile = VoiceProfile()
            profile = card.hsr.voice_profile

            from pair_harness.adapters.audio.qwen_voice_customization import (
                QwenVoiceCustomizationClient,
                VoiceCustomizationError,
                audio_file_to_data_uri,
            )

            client = QwenVoiceCustomizationClient(
                api_key=api_key, http_base_url=base_url
            )

            def persist(state: str, **updates: Any) -> None:
                profile.state = state
                for key, value in updates.items():
                    setattr(profile, key, value)
                profile.updated_at = utc_now().isoformat()
                self.card_repository.update_card(card_id, card)

            if mode == "clone":
                if not profile.reference_audio_asset:
                    raise ServiceError(
                        "请先绑定参考音频（voice.card_bind_reference）",
                        code="voice_reference_missing",
                    )
                asset = next(
                    (
                        item
                        for item in self.asset_service.list_assets_for_card(card_id)
                        if item.asset_id == profile.reference_audio_asset
                    ),
                    None,
                )
                if asset is None:
                    raise ServiceError(
                        "绑定的参考音频资产缺失，请重新绑定",
                        code="voice_reference_missing",
                    )
                audio_url = audio_file_to_data_uri(Path(asset.file_path))
                voice_prompt = ""
            else:
                voice_prompt = str(params.get("voice_prompt") or "").strip()
                if not voice_prompt:
                    raise ServiceError(
                        "声音设计需要非空 voice_prompt", code="voice_invalid_request"
                    )
                audio_url = ""

            self._card_provision_emit(card_id, CharacterVoiceState.CREATING.value)
            persist(CharacterVoiceState.CREATING.value)
            try:
                if mode == "clone":
                    result = await asyncio.to_thread(
                        client.create_cloned_voice,
                        prefix=prefix,
                        url=audio_url,
                    )
                else:
                    # 真实探针（2026-08-24）：preview_text 少于 15 字符会被
                    # DashScope 以 InvalidParameter 拒绝，默认文本须 ≥15 字符。
                    preview_text = (
                        str(params.get("preview_text") or "").strip()
                        or "你好，很高兴在这里遇见你，请多多关照。"
                    )
                    result = await asyncio.to_thread(
                        client.create_designed_voice,
                        prefix=prefix,
                        voice_prompt=voice_prompt,
                        preview_text=preview_text,
                    )
            except VoiceCustomizationError as exc:
                detail = (
                    f"HTTP {exc.http_status} "
                    if exc.http_status is not None
                    else ""
                ) + self._redact_voice_error(exc, api_key)
                # 失败保留旧 voice_id 与真实错误；不合成成功结果。
                persist(CharacterVoiceState.FAILED.value, last_error=detail)
                self._card_provision_emit(
                    card_id,
                    CharacterVoiceState.FAILED.value,
                    voice_id=profile.voice_id or None,
                    error=detail,
                )
                raise ServiceError(
                    detail, code="voice_card_create_failed"
                ) from exc
            except Exception as exc:  # noqa: BLE001 - 供应商/网络真实失败如实暴露
                detail = self._redact_voice_error(
                    str(exc) or type(exc).__name__, api_key
                )
                persist(CharacterVoiceState.FAILED.value, last_error=detail)
                self._card_provision_emit(
                    card_id,
                    CharacterVoiceState.FAILED.value,
                    voice_id=profile.voice_id or None,
                    error=detail,
                )
                raise ServiceError(
                    detail, code="voice_card_create_failed"
                ) from exc

            persist(
                CharacterVoiceState.READY.value,
                voice_id=result.voice_id,
                creation_mode=mode,
                prefix=prefix,
                last_error="",
            )
            self._card_provision_emit(
                card_id,
                CharacterVoiceState.READY.value,
                voice_id=result.voice_id,
            )
            return {
                "card_id": card_id,
                "state": CharacterVoiceState.READY.value,
                "voice_id": result.voice_id,
            }

    async def _voice_card_unbind(self, params: Mapping[str, Any]) -> dict[str, Any]:
        card_id = self._required_string(params, "card_id")
        self._require_writable_card(card_id)
        try:
            record = self.card_repository.get_card(card_id)
        except KeyError as exc:
            raise ServiceError("角色卡不存在", code="card_not_found") from exc
        card = record.card
        if card.hsr is not None and card.hsr.voice_profile is not None:
            profile = card.hsr.voice_profile
            # 旧 voice_id 不在用户供应商账号侧自动删除；本地解绑并保留参考音频。
            profile.voice_id = ""
            profile.state = CharacterVoiceState.UNCONFIGURED.value
            profile.creation_mode = ""
            profile.last_error = ""
            profile.updated_at = utc_now().isoformat()
            self.card_repository.update_card(card_id, card)
        return {
            "card_id": card_id,
            "state": CharacterVoiceState.UNCONFIGURED.value,
        }

    async def _voice_card_preview(
        self,
        params: Mapping[str, Any],
        *,
        origin: str = "desktop",
        device_key: str | None = None,
    ) -> dict[str, Any]:
        self._require_playback_control(origin=origin, device_key=device_key)
        card_id = self._required_string(params, "card_id")
        if self.voice_runtime is None:
            raise ServiceError("语音运行时未启用", code="voice_unavailable")
        text = str(params.get("text") or "").strip() or "你好，这是该角色的语音。"
        if not is_readable_text(text):
            raise ServiceError("试听文本为空或只有标点", code="invalid_text")
        try:
            record = self.card_repository.get_card(card_id)
        except KeyError as exc:
            raise ServiceError("角色卡不存在", code="card_not_found") from exc
        profile = (
            record.card.hsr.voice_profile if record.card.hsr is not None else None
        )
        if (
            profile is None
            or profile.state != CharacterVoiceState.READY.value
            or not profile.voice_id
        ):
            raise ServiceError("该角色卡尚未创建可用音色", code="voice_card_not_ready")
        # 卡音色属于角色侧；助手侧音色永不进入试听（voice_policy 边界）。
        self.voice_runtime.enqueue_text(text, voice_id=profile.voice_id)
        return {"voice": self._voice_snapshot()}

    # ------------------------------------------------------------------ V0.3.7 电源（契约 §1.5 / §2.1 / §8）

    async def _power_get_status(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """power.get_status：读取电源状态（只读，永不修改电源设置）。

        成功返回 ``PowerStatus`` 的 asdict（契约 §1.5 形状）；真实失败抛
        ``PowerStatusError`` 时转 ``power_status_unavailable`` 携带原文，
        不猜数值、不降级伪造。
        """
        del params
        try:
            status = read_power_status(
                remote_serve_enabled=self.remote_serve_enabled
            )
        except PowerStatusError as exc:
            raise ServiceError(
                f"读取电源状态失败：{exc}", code="power_status_unavailable"
            ) from exc
        return dataclasses.asdict(status)

    def start_power_monitor(
        self,
        *,
        runner: Callable[[list[str], Any], Any] | None = None,
        interval_seconds: float = 60.0,
    ) -> None:
        """启动电源监视守护线程（契约 §2.1；幂等，已在跑则跳过）。

        - 启动即读取并 emit 一次 ``power.status_changed``（payload 与
          ``power.get_status`` result 完全同形）；
        - 此后每 ``interval_seconds`` 秒轮询，仅当关键元组
          ``(supported, plan_name, ac, dc, remote_serve_enabled)`` 变化才
          emit（无变化不发事件，避免噪声）；
        - ``PowerStatusError`` 读取失败不合成事件：如实写入 stderr 日志并
          保留上次状态，下轮重试（Let It Fail，不伪造状态）。
        """
        if (
            self._power_monitor_thread is not None
            and self._power_monitor_thread.is_alive()
        ):
            return
        self._power_monitor_interval = interval_seconds
        self._power_monitor_stop = threading.Event()
        self._power_monitor_last = None
        thread = threading.Thread(
            target=self._power_monitor_loop,
            kwargs={
                "runner": runner,
                "interval_seconds": interval_seconds,
            },
            name="power-status-monitor",
            daemon=True,
        )
        self._power_monitor_thread = thread
        thread.start()

    def stop_power_monitor(self) -> None:
        """停止电源监视：置停止 Event 并 join（带超时）；未启动时 no-op。"""
        thread = self._power_monitor_thread
        if thread is None:
            return
        self._power_monitor_stop.set()
        thread.join(timeout=5.0)
        self._power_monitor_thread = None

    def _power_monitor_loop(
        self,
        *,
        runner: Callable[[list[str], Any], Any] | None,
        interval_seconds: float,
    ) -> None:
        while not self._power_monitor_stop.is_set():
            try:
                status = read_power_status(
                    remote_serve_enabled=self.remote_serve_enabled, runner=runner
                )
            except PowerStatusError as exc:
                # 读取失败不合成事件：如实记录原始错误，保留上次状态，下轮重试。
                logging.getLogger(__name__).error(
                    "电源状态读取失败（保留上次状态，下轮重试）：%s", exc
                )
            else:
                key = (
                    status.supported,
                    status.plan_name,
                    status.ac_sleep_timeout_seconds,
                    status.dc_sleep_timeout_seconds,
                    status.remote_serve_enabled,
                )
                if self._power_monitor_last is None or key != self._power_monitor_last:
                    self._power_monitor_last = key
                    self.emitter.emit(
                        "power.status_changed", dataclasses.asdict(status)
                    )
            if self._power_monitor_stop.wait(interval_seconds):
                break

    # ------------------------------------------------------------------ V0.3.5 对话绑定角色卡（装配）

    def _effective_active_card_id(self) -> str | None:
        """当前可作为新对话角色身份的 active 卡；draft 与归档卡不生效。"""
        card_id = self.card_repository.get_active_card_id()
        if not card_id:
            return None
        try:
            record = self.card_repository.get_card(card_id)
        except KeyError:
            return None
        if record.state not in {"saved", "imported"}:
            return None
        if self.card_repository.is_archived(card_id):
            return None
        return card_id

    def _recent_completed_summary(
        self, conversation_id: str
    ) -> ConversationSummary | None:
        """最近一条 completed 摘要（core ``ConversationSummary``）；无则 None。

        存储层 content 是 JSON 文本，这里解析回对象并按 core 契约构造：
        装配器读的是 ``.status``/``.content`` 属性，dict 会在装配时抛
        AttributeError（V0.3.9 §2 装配接缝）。
        """
        try:
            records = self.store.list_summaries(conversation_id, status="completed")
        except ValueError:
            return None
        if not records:
            return None
        latest = records[-1]
        content = _json_load(latest.content)
        if not isinstance(content, dict):
            content = None
        return ConversationSummary.model_validate(
            {
                "summary_id": latest.summary_id,
                "conversation_id": latest.conversation_id,
                "status": "completed",
                "covers_from_message_id": latest.covers_from_message_id,
                "covers_to_message_id": latest.covers_to_message_id,
                "covers_message_count": latest.covers_message_count,
                "content": content,
                "provider": latest.provider,
                "model": latest.model,
                "error_code": None,
                "error": None,
                "created_at": latest.created_at,
                "updated_at": latest.updated_at,
            }
        )

    def _builtin_character_card(self, conversation: Any) -> CharacterCard:
        """未绑定卡/卡已删除的会话：内置搭档角色提示词作为角色基座。

        只读取该聊天搭档配置的角色提示词原文作为 ``description``，不改写、
        不摘要；装配框架与模块标题与其他角色卡一致。
        """
        config = load_pair_config(conversation.pair_id)
        return CharacterCard(
            name=config.character.name,
            description=load_prompt(config.character.prompt),
        )

    def _conversation_active_memories(
        self, conversation_id: str
    ) -> tuple[PairMemory, ...]:
        """按会话作用域读取 active 长期记忆（core 形状）；无作用域返回空元组。

        无项目会话没有长期记忆作用域（契约 §1）：装配按无记忆继续，不让
        回合失败；记忆命令在同一会话上仍如实报错。其余作用域错误照常抛出。
        """
        try:
            scope = self._conversation_scope(conversation_id)
        except ServiceError as exc:
            if exc.code != MEMORY_INVALID:
                raise
            return ()
        return tuple(
            _core_memory(record)
            for record in self.store.list_memories(scope, status="active")
        )

    def _resolve_character_prompt(
        self,
        conversation_id: str,
        recent_messages: tuple = (),
        turn_index: int = 0,
    ) -> "AssembledPrompt | None":
        """按对话绑定的角色卡装配提示词；无角色基座返回 None。

        V0.3.7 契约 §4.5：resolver 三参 ``(conversation_id, recent_messages,
        turn_index)``。基座按 ``(card_id, updated_at)`` 缓存（世界书与
        depth_prompt 不进基座）；回合上下文（扫描文本与回合号）现算，
        叠加世界书激活、深度注入与确定性触发。``recent_messages`` /
        ``turn_index`` 带缺省值，兼容既有单参调用（等价空扫描的基座结果）。

        V0.3.9 §2：最近成功摘要与 active 长期记忆都在这条接缝注入。未绑定卡
        （或卡已删除）的会话只要确有摘要/记忆就用内置角色基座照常装配——
        投影已按摘要覆盖把原文窗口收窄到 12 条，摘要再不注入等于旧历史丢失；
        两者都没有时保持「未绑定 → None」的既有回退，交给内置 YAML 提示词。
        """
        try:
            conversation = self.store.get_conversation(conversation_id)
        except KeyError:
            return None
        summary = self._recent_completed_summary(conversation_id)
        memories = self._conversation_active_memories(conversation_id)
        card_id = conversation.character_card_id
        record = None
        if card_id:
            try:
                record = self.card_repository.get_card(card_id)
            except KeyError:
                # 卡已被删除：回退内置角色；降级提示由 conversation.open 发出。
                record = None
        if record is None and summary is None and not memories:
            return None
        if record is not None:
            cached = self._assembled_cache.get(card_id)
            if cached is not None and cached[0] == record.updated_at:
                base = cached[1]
            else:
                base = assemble_character_prompt(record.card)
                self._assembled_cache[card_id] = (record.updated_at, base)
            card = record.card
        else:
            card = self._builtin_character_card(conversation)
            base = None
        return assemble_turn_prompt(
            card,
            scan_texts=[m.text for m in recent_messages],
            turn_index=turn_index,
            base=base,
            summary=summary,
            memories=memories,
        )

    def _insert_character_greeting(
        self, conversation: Any, card: CharacterCard
    ) -> None:
        """绑定卡的对话创建后插入 first_mes 开场白（走既有消息路径）。"""
        text = card.first_mes.strip()
        if not text:
            return
        message = Message(
            conversation_id=conversation.conversation_id,
            pair_id=conversation.pair_id,
            source=MessageSource.CHARACTER,
            kind=MessageKind.CHARACTER_SPEECH,
            text=text,
            tts_eligible=True,
            origin=MessageOrigin.SYSTEM,
        )
        self.store.save_message(message)
        self.emitter.emit("message.created", {"message": message})

    # ------------------------------------------------------------------ V0.3.5 手机语音（契约 §5）

    def attach_event_fanout(self, fanout: Any) -> None:
        """--serve 模式由 __main__ 注入事件扇出；手机语音事件经它下发。"""
        self._event_fanout = fanout

    def _publish_remote_only(self, event: str, payload: dict[str, Any]) -> None:
        fanout = self._event_fanout
        if fanout is None:
            return
        envelope = {
            "kind": "event",
            "event": event,
            "stream_id": self.emitter.stream_id,
            # 必须经 allocate_sequence 消费序号；只读 next_sequence 会让
            # 全部 remote-only 事件与后续普通事件复用同一序号被客户端丢弃。
            "sequence": self.emitter.allocate_sequence(),
            "payload": payload,
        }
        # 音频分片只发远程连接，不写桌面 stdout 协议（契约 §5.2）。
        fanout.publish(envelope, remote_only=True)

    def _on_mobile_transcript(
        self, conversation_id: str, session_id: str, text: str, is_final: bool
    ) -> None:
        # 回调来自会话泵线程；线程安全转回主事件循环再发布。无运行
        # 循环（非事件循环上下文构造）时无处可发，如实跳过。
        if self._main_loop is None:
            return
        self._main_loop.call_soon_threadsafe(
            self._publish_remote_only,
            "voice.mobile_transcript",
            {
                "conversation_id": conversation_id,
                "session_id": session_id,
                "text": text,
                "is_final": is_final,
            },
        )

    def _mobile_asr_factory(self):
        from pair_harness.adapters.audio.qwen_asr import QwenStreamingRecognizer

        config = self._load_account_config()
        settings = Settings.overlay(Settings.from_environment(), config)
        api_key = (config.get("voice.api_key") or "").strip() or (
            settings.dashscope_api_key or ""
        )
        if not api_key:
            raise ServiceError(
                "请先在语音页保存 DashScope API Key，再使用手机语音",
                code="voice_not_configured",
            )

        def factory() -> QwenStreamingRecognizer:
            return QwenStreamingRecognizer(
                api_key=api_key, ws_url=settings.resolved_ws_url
            )

        return factory

    async def _voice_mobile_ptt_start(
        self, params: Mapping[str, Any], *, connection_key: str | None = None
    ) -> dict[str, Any]:
        conversation_id = self._required_string(params, "conversation_id")
        self._current_account_conversation(conversation_id)
        # 传输层注入的连接 key（WS 路径）优先；缺失时退回设备名——纯
        # service 级测试与 stdin 路径无连接概念，仍需可运行。
        key = connection_key or str(params.get("device_name") or "remote")
        factory = self._mobile_asr_factory()
        try:
            session_id = self._mobile_asr.start_session(
                conversation_id, key, factory
            )
        except MobileAudioError as exc:
            raise ServiceError(str(exc) or exc.code, code=exc.code) from exc
        self._mobile_asr_conversations[session_id] = conversation_id

        async def watchdog() -> None:
            # 连接断开未显式 stop 的兜底：超时静默取消，避免会话悬挂。
            await asyncio.sleep(120)
            self._mobile_asr.cancel_session(session_id)

        task = asyncio.create_task(watchdog())
        self._mobile_asr_watchdogs[session_id] = task
        return {"session_id": session_id, "conversation_id": conversation_id}

    async def _voice_mobile_audio_chunk(
        self, params: Mapping[str, Any]
    ) -> dict[str, Any]:
        session_id = self._required_string(params, "session_id")
        seq_raw = params.get("seq")
        if not isinstance(seq_raw, int) or isinstance(seq_raw, bool):
            raise ServiceError("seq 必须是整数", code="invalid_params")
        data = params.get("data")
        if not isinstance(data, str) or not data:
            raise ServiceError(
                "data 必须是非空 base64 字符串", code="invalid_params"
            )
        try:
            self._mobile_asr.feed_chunk(session_id, seq_raw, data)
        except MobileAudioError as exc:
            raise ServiceError(str(exc) or exc.code, code=exc.code) from exc
        return {"accepted": True}

    def handle_remote_disconnect(self, connection_key: str) -> None:
        """契约 §5.3：连接断开时取消该连接全部未完成语音会话（静默）。

        V0.3.9 契约 §6：断连不立即释放控制租约——给持有者 15s 重连宽限，
        宽限结束后由回收流程过期；锁屏、切后台和短暂断线都不恢复桌面播放。
        """
        self._mobile_asr.cancel_all_for_connection(connection_key)
        now = time.monotonic()
        for lease in self._control_leases.values():
            if lease.connection_key != connection_key:
                continue
            if lease.disconnected_at is None:
                lease.mark_disconnected(now)
                lease.reason = "disconnected"
                logger.info(
                    "remote-control: 连接断开，进入重连宽限 key=%s grace=%ss",
                    lease.device_key,
                    int(CONTROL_LEASE_GRACE_S),
                )
        self._ensure_control_sweeper()

    async def _voice_mobile_tts_stop(
        self, params: Mapping[str, Any]
    ) -> dict[str, Any]:
        message_id = self._required_string(params, "message_id")
        self._mobile_tts.stop(message_id)
        task = self._mobile_tts_tasks.pop(message_id, None)
        if task is not None and not task.done():
            task.cancel()
        # 控制期间联动停声；退出控制后迟到的手机停止请求不得打断新的桌面播放。
        if self.voice_runtime is not None and self.has_active_remote_controller():
            await self.voice_runtime.stop_speaking_async()
        return {"message_id": message_id, "stopped": True}

    async def _voice_mobile_ptt_stop(
        self,
        params: Mapping[str, Any],
        *,
        origin: str = "desktop",
        device_key: str | None = None,
        device_name: str | None = None,
    ) -> dict[str, Any]:
        session_id = self._required_string(params, "session_id")
        watchdog = self._mobile_asr_watchdogs.pop(session_id, None)
        if watchdog is not None:
            watchdog.cancel()
        try:
            # end_session 同步等待后台识别线程收尾（约 5 秒尾超时），
            # 必须移到工作线程，避免阻塞 Sidecar 事件循环。
            transcript = await asyncio.to_thread(
                self._mobile_asr.end_session, session_id
            )
        except MobileAudioError as exc:
            raise ServiceError(str(exc) or exc.code, code=exc.code) from exc
        text = transcript.strip()
        if not text:
            raise ServiceError("未识别到语音内容", code="voice_transcript_empty")
        # 转写文本以角色消息进入既有提交路径（模式校验/队列/归属全部复用）。
        conversation_id = self._mobile_asr_conversations.pop(session_id, "")
        if not conversation_id:
            raise ServiceError(
                "转写会话已结束", code="voice_session_not_found"
            )
        await self._chat_submit(
            {"conversation_id": conversation_id, "target": "character", "text": text},
            origin=origin,
            device_key=device_key,
            device_name=device_name,
        )
        return {"session_id": session_id, "transcript": text}

    def _maybe_relay_mobile_tts(
        self, message: Message, voice_id: str | None = None
    ) -> None:
        """角色自然语言回复 → 手机 TTS 下发；助手/工具/思考零下发。

        ``voice_id`` 由调用方（_on_message）预判注入：无可用音色时如实
        跳过，不空耗任务槽。None 时按自身解析兜底（兼容旧调用点）。
        """
        if self._event_fanout is None:
            logger.info("mobile-tts: fanout 未挂载，跳过 %s", message.message_id)
            return
        if not self._event_fanout.has_remote_subscribers():
            logger.info("mobile-tts: 无远程订阅者，跳过 %s", message.message_id)
            return
        if message.source != MessageSource.CHARACTER or not message.tts_eligible:
            logger.info(
                "mobile-tts: 非角色可朗读消息，跳过 source=%s kind=%s eligible=%s",
                message.source, message.kind, message.tts_eligible,
            )
            return
        if not message.text.strip():
            logger.info("mobile-tts: 空文本，跳过 %s", message.message_id)
            return
        if voice_id is None:
            # 调用方未预判（旧路径）：按权威解析再决定。
            try:
                conversation = self.store.get_conversation(message.conversation_id)
            except KeyError:
                conversation = None
            voice_id = (
                self._resolve_mobile_tts_voice_id(
                    message.conversation_id, conversation.character_card_id
                )
                if conversation is not None
                else None
            )
        if not voice_id:
            logger.info("mobile-tts: 无可用音色，跳过 %s", message.message_id)
            return
        logger.info("mobile-tts: 触发下发 %s（len=%s）", message.message_id, len(message.text))
        # V0.3.8 修复：下一条消息回答出现时抢占旧消息，中断前序未完成的 mobile-tts 任务
        for old_msg_id, old_task in tuple(self._mobile_tts_tasks.items()):
            if old_msg_id != message.message_id and not old_task.done():
                logger.info("mobile-tts: 新回复到达，抢占中断旧合成任务 %s", old_msg_id)
                old_task.cancel()
                self._mobile_tts.stop(old_msg_id)
        task = asyncio.create_task(
            self._relay_mobile_tts_task(message),
            name=f"mobile-tts:{message.message_id}",
        )
        self._mobile_tts_tasks[message.message_id] = task

        def _forget_task(finished: asyncio.Task[None]) -> None:
            # 按任务身份清理：同一 message_id 若已被更新的任务接管，不得把
            # 新任务从表里删掉（旧任务的回调晚于新任务注册时会发生）。
            if self._mobile_tts_tasks.get(message.message_id) is finished:
                self._mobile_tts_tasks.pop(message.message_id, None)

        task.add_done_callback(_forget_task)

    def _resolve_mobile_tts_voice_id(
        self, conversation_id: str, card_id: str | None
    ) -> str | None:
        """移动端朗读的可用音色解析（message.created 预判与 relay 共用）。

        与 _relay_mobile_tts_task 同规则：卡级 voice_ready 优先，否则账号
        级/作者级解析；解析不出可用音色返回 None——调用方按「如实不合成」
        处理（手机端据此不展示可朗读入口，杜绝点了没声音的假象）。
        """
        try:
            conversation = self.store.get_conversation(conversation_id)
        except KeyError:
            return None
        voice_id = ""
        if card_id:
            record = None
            try:
                record = self.card_repository.get_card(card_id)
            except KeyError:
                record = None
            if record is not None:
                profile = (
                    record.card.hsr.voice_profile
                    if record.card.hsr is not None
                    else None
                )
                if (
                    profile is not None
                    and profile.state == CharacterVoiceState.READY.value
                    and profile.voice_id
                ):
                    voice_id = profile.voice_id
        if not voice_id:
            pair = self._effective_voice_pair(
                conversation.pair_id, conversation_id
            )
            voice_id = pair.character.voice_id
        if not voice_id:
            return None
        config = self._load_account_config()
        settings = Settings.overlay(Settings.from_environment(), config)
        api_key = (config.get("voice.api_key") or "").strip() or (
            settings.dashscope_api_key or ""
        )
        if not api_key:
            return None
        return voice_id

    async def _relay_mobile_tts_task(self, message: Message) -> None:
        conversation = None
        try:
            conversation = self.store.get_conversation(message.conversation_id)
        except KeyError:
            logger.info("mobile-tts: 会话不存在 %s", message.conversation_id)
            return
        voice_id = self._resolve_mobile_tts_voice_id(
            message.conversation_id, conversation.character_card_id
        )
        if not voice_id:
            # 没有可用音色：如实不合成、不发事件（不空耗额度）。
            logger.info("mobile-tts: 无可用音色，跳过 %s", message.message_id)
            return
        config = self._load_account_config()
        settings = Settings.overlay(Settings.from_environment(), config)
        api_key = (config.get("voice.api_key") or "").strip() or (
            settings.dashscope_api_key or ""
        )
        if not api_key:
            logger.info("mobile-tts: 无 voice.api_key，跳过 %s", message.message_id)
            return
        logger.info(
            "mobile-tts: 开始合成 %s voice=%s ws=%s",
            message.message_id, voice_id, settings.resolved_ws_url,
        )
        from pair_harness.adapters.audio.qwen_tts import QwenSpeechSynthesizer
        from pair_harness.core.contracts import SpeechRequest

        synthesizer = QwenSpeechSynthesizer(
            api_key=api_key, ws_url=settings.resolved_ws_url
        )
        end_payload: dict[str, Any] | None = None
        chunk_count = 0
        try:
            # begin 放进 try：重复 message_id 等错误必须走同一收尾路径并如实
            # 上报（否则任务带着无人观察的异常结束，移动端只会一直等）。
            self._mobile_tts.begin(message.message_id, message.conversation_id)
            async for chunk in synthesizer.synthesize(
                SpeechRequest(
                    text=message.text,
                    voice_id=voice_id,
                    message_id=message.message_id,
                )
            ):
                # feed/end 的返回值就是事件 payload 本身（契约 §5.2）。
                payload = self._mobile_tts.feed(message.message_id, chunk.pcm)
                chunk_count += 1
                self._publish_remote_only("voice.mobile_tts_chunk", payload)
            end_payload = self._mobile_tts.end(message.message_id)
            logger.info(
                "mobile-tts: 合成完成 %s chunks=%s", message.message_id, chunk_count
            )
        except asyncio.CancelledError:
            # 手机端主动停止（voice.mobile_tts_stop）走 stop 清理，不是失败。
            raise
        except Exception as exc:  # noqa: BLE001 - 供应商真实失败必须让手机端退出播放状态
            logger.warning("手机 TTS 下发失败", exc_info=True)
            self._publish_remote_only(
                "voice.mobile_tts_failed",
                {
                    "conversation_id": message.conversation_id,
                    "message_id": message.message_id,
                    # 脱敏后供应商错误（不携带 Key/鉴权头）。
                    "error": self._redact_voice_error(
                        str(exc) or type(exc).__name__, ""
                    ),
                },
            )
            return
        finally:
            try:
                await synthesizer.aclose()
            except Exception as exc:  # noqa: BLE001 - 关闭失败不得覆盖原始结果
                # 关闭失败如实进日志：此处不重抛，避免把已经发生的真实失败
                # （或已完成的合成）替换成收尾异常，但绝不静默吞掉。
                logger.warning(
                    "mobile-tts: 关闭合成器失败 %s：%s: %s",
                    message.message_id,
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )
        if end_payload is not None:
            self._publish_remote_only("voice.mobile_tts_end", end_payload)

    # ------------------------------------------------------------------ V0.3.3 手机远程配对

    def _restore_pairing_state(self) -> None:

        raw = self.store.get_app_state("remote.pairing_state")
        if not raw:
            return
        try:
            state = json.loads(raw)
        except (TypeError, ValueError):
            # 状态损坏按空状态启动；真实错误留在日志，不阻断 Sidecar。
            logger.warning("远程配对状态损坏，按空状态启动", exc_info=True)
            return
        if isinstance(state, dict):
            self.pairing_service.load_state(state)
            if state.get("version", 1) < 2:
                self._persist_pairing_state()

    def _persist_pairing_state(self) -> None:
        self.store.set_app_state(
            "remote.pairing_state",
            json.dumps(self.pairing_service.export_state(), ensure_ascii=False),
        )

    async def _remote_issue_code(
        self, params: Mapping[str, Any], *, origin: str = "desktop"
    ) -> dict[str, Any]:
        """桌面端生成短期配对码（5 分钟有效、一次性）。

        仅桌面回环/stdin 路径可调用；远程连接无权生成。
        """
        del params
        if origin != "desktop":
            self.pairing_service.record_audit(
                "scope_denied", f"method=remote.issue_code origin={origin}"
            )
            raise ServiceError("远程连接无权调用控制面方法", code="forbidden_scope")
        code = self.pairing_service.issue_code()
        self._persist_pairing_state()
        # V039-S4-004：配对码与真实接入地址一起返回；未监听时为 None，
        # 调用方据此区分「尚未监听」与「已监听但无局域网地址」。
        return {
            "code": code,
            "ttl_seconds": 300,
            "serve_address": self.remote_serve_address,
        }

    async def _remote_pair(
        self, params: Mapping[str, Any], *, connection_key: str | None = None
    ) -> dict[str, Any]:
        code = str(params.get("code") or "")
        device_name = str(params.get("device_name") or "").strip()
        if not code or not device_name:
            raise ServiceError(
                "remote.pair 需要 code 与 device_name", code="invalid_params"
            )
        source = connection_key or "default"
        try:
            token = self.pairing_service.claim(code, device_name=device_name, source=source)
        except PairingError as exc:
            # 失败同样推进失败计数、封锁退避与审计（§4.4：封锁状态随配对状态
            # 持久化，重启不重置），必须在拒绝请求的当刻落盘，否则 Sidecar
            # 崩溃重启会重置攻击者的尝试预算。
            self._persist_pairing_state()
            details = (
                {"retry_after_s": int(round(exc.retry_after_s))}
                if exc.retry_after_s is not None
                else None
            )
            raise ServiceError(str(exc), code=f"pairing_{exc.code}", details=details) from exc
        self._persist_pairing_state()
        return {"token": token}

    async def _remote_list_devices(
        self, params: Mapping[str, Any], *, origin: str = "desktop"
    ) -> dict[str, Any]:
        del params
        if origin != "desktop":
            self.pairing_service.record_audit(
                "scope_denied", f"method=remote.list_devices origin={origin}"
            )
            raise ServiceError("远程连接无权调用控制面方法", code="forbidden_scope")
        return {"devices": self.pairing_service.list_devices()}

    async def _remote_revoke(
        self, params: Mapping[str, Any], *, origin: str = "desktop"
    ) -> dict[str, Any]:
        if origin != "desktop":
            self.pairing_service.record_audit(
                "scope_denied", f"method=remote.revoke origin={origin}"
            )
            raise ServiceError("远程连接无权调用控制面方法", code="forbidden_scope")
        device_name = str(params.get("device_name") or "").strip()
        if not device_name:
            raise ServiceError(
                "remote.revoke 需要 device_name", code="invalid_params"
            )
        # 桌面端按设备名撤销：撤销该设备名下全部 token。
        state = self.pairing_service.export_state()
        revoked = 0
        for entry in state.get("tokens", []):
            if entry.get("device_name") == device_name and not entry.get("revoked"):
                if self.pairing_service.revoke(entry["token"]):
                    revoked += 1
                    device_key = hashlib.sha256(
                        entry["token"].encode("utf-8")
                    ).hexdigest()
                    lease = self._control_leases.pop(device_key, None)
                    if lease is not None:
                        logger.info(
                            "remote-control: 设备撤销回收租约 key=%s", device_key
                        )
                        self._emit_control_changed(
                            lease, state="free", reason="revoked"
                        )
        if revoked == 0:
            raise ServiceError(
                f"没有可撤销的设备：{device_name}", code="device_not_found"
            )
        self._persist_pairing_state()
        return {"device_name": device_name, "revoked_tokens": revoked}

    async def _remote_tunnel_start(
        self, params: Mapping[str, Any], *, origin: str = "desktop"
    ) -> dict[str, Any]:
        if origin != "desktop":
            self.pairing_service.record_audit(
                "scope_denied", f"method=remote.tunnel_start origin={origin}"
            )
            raise ServiceError("远程连接无权调用控制面方法", code="forbidden_scope")
        port = params.get("port")
        if port is None and self.remote_serve_address:
            port = self.remote_serve_address.get("port")
        if port is None and self.remote_serve_port is not None:
            port = self.remote_serve_port
        if port is None:
            port = 8765
        return await self.tunnel_manager.start(int(port))

    async def _remote_tunnel_stop(
        self, params: Mapping[str, Any], *, origin: str = "desktop"
    ) -> dict[str, Any]:
        del params
        if origin != "desktop":
            self.pairing_service.record_audit(
                "scope_denied", f"method=remote.tunnel_stop origin={origin}"
            )
            raise ServiceError("远程连接无权调用控制面方法", code="forbidden_scope")
        return await self.tunnel_manager.stop()

    async def _remote_tunnel_status(
        self, params: Mapping[str, Any], *, origin: str = "desktop"
    ) -> dict[str, Any]:
        del params
        if origin != "desktop":
            self.pairing_service.record_audit(
                "scope_denied", f"method=remote.tunnel_status origin={origin}"
            )
            raise ServiceError("远程连接无权调用控制面方法", code="forbidden_scope")
        return self.tunnel_manager.status()

    @staticmethod
    def _remote_control_device_key(command: DesktopCommand) -> str:
        if command.origin != "remote" or not command.remote_device_key:
            raise ServiceError("远程控制需要已鉴权设备身份", code="remote_identity_required")
        return command.remote_device_key

    def _require_playback_control(
        self, *, origin: str = "desktop", device_key: str | None = None
    ) -> None:
        """起始播放/试听的调用方身份判定（V039-S4-016）。

        租约有效期内只有持有者可以起播：桌面调用方被拒（不得抢占远程），
        其他远程设备被拒并点名「另一台远程设备」，租约持有者自身放行——
        原实现只看租约是否存在，把「桌面不得抢占远程」实现成了「任何人
        不得播放」，持权端能停不能起。
        """
        self._sweep_control_leases()
        if not self._control_leases:
            return
        if origin == "remote" and device_key and device_key in self._control_leases:
            return
        if origin == "remote":
            raise ServiceError(
                "另一台远程设备正在控制语音，请先在该设备退出远程控制或撤销该设备",
                code="remote_playback_active",
            )
        raise ServiceError(
            "远程设备正在控制语音，请先在远程设备退出远程控制或撤销该设备",
            code="remote_playback_active",
        )

    async def _remote_claim_control(
        self,
        params: Mapping[str, Any],
        *,
        device_key: str,
        connection_key: str | None = None,
    ) -> dict[str, Any]:
        """手机端声明/续租远程控制权（V0.3.9 契约 §6）。

        按 device_key 独立记录：重复认领只续租不发事件；首次认领抢占桌面
        本地朗读（epoch 递增）并广播 remote.control_changed。
        """
        del params
        self._sweep_control_leases()
        now = time.monotonic()
        lease = self._control_leases.get(device_key)
        if lease is None:
            lease = _ControlLease(
                device_key=device_key,
                granted_at=now,
                last_refresh_at=now,
                expires_at_wall=datetime.now(timezone.utc)
                + timedelta(seconds=CONTROL_LEASE_TTL_S),
                connection_key=connection_key,
                reason="claimed",
            )
            self._control_leases[device_key] = lease
            # 抢占生效：epoch 递增并停止桌面端任何正在播放的本地声音。
            if self.voice_runtime is not None:
                await self.voice_runtime.stop_speaking_async("remote_claim")
            self._ensure_control_sweeper()
            logger.info(
                "remote-control: 控制器已认领 key=%s, total=%d",
                device_key,
                len(self._control_leases),
            )
            self._emit_control_changed(lease, state="held", reason="claimed")
        else:
            lease.renew(now)
            lease.connection_key = connection_key or lease.connection_key
            lease.reason = "renewed"
        return {"claimed": True, "active_controllers": len(self._control_leases)}

    async def _remote_release_control(
        self, params: Mapping[str, Any], *, device_key: str
    ) -> dict[str, Any]:
        """手机端释放自己的控制租约（恢复桌面播放资格）。

        V0.3.9 契约 §6：只回收该 device_key，不误释放其他设备。
        """
        del params
        lease = self._control_leases.pop(device_key, None)
        if lease is not None:
            logger.info(
                "remote-control: 控制器已释放 key=%s, remaining=%d",
                device_key,
                len(self._control_leases),
            )
            self._emit_control_changed(lease, state="free", reason="released")
        return {"released": True, "active_controllers": len(self._control_leases)}

    async def _remote_control_status(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """remote.control_status：只读租约状态（V0.3.9 契约 §6/§7）。"""
        del params
        return self._control_lease_payload()

    async def _metrics_query(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """metrics.query：显式只读查询回合指标（契约 §5）。

        过滤条件可空；limit 默认 50、上限 200（TurnMetricQuery 校验）。
        未观测字段早已由写入侧保持 null，此处只透传存储层结果。
        """
        try:
            query = TurnMetricQuery(
                account_id=_optional_text(params, "account_id"),
                project_id=_optional_text(params, "project_id"),
                conversation_id=_optional_text(params, "conversation_id"),
                pair_id=_optional_text(params, "pair_id"),
                character_ref=_optional_text(params, "character_ref"),
                assistant_identity=_optional_text(params, "assistant_identity"),
                turn_kind=_optional_text(params, "turn_kind"),
                status=_optional_text(params, "status"),
                origin=_optional_text(params, "origin"),
                since=_optional_datetime(params, "since"),
                until=_optional_datetime(params, "until"),
                limit=int(params.get("limit") or 50),
                cursor=_optional_text(params, "cursor"),
            )
        except ValueError as exc:
            raise ServiceError(str(exc), code="invalid_metrics_query") from exc
        page = self.store.query_turn_metrics(query)
        return {
            # V039-S4-001：记录层持有 datetime，协议层按 JSON 模式导出
            # （缺失保持 null、真实零保持 0），不做兜底改写。
            "metrics": [metric.model_dump(mode="json") for metric in page.items],
            "next_cursor": page.next_cursor,
        }

    async def _summary_regenerate(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """summary.regenerate：对真实失败记录或用户显式请求重新生成摘要。

        契约 §2：仍调用配置的真实模型；生成失败保留真实失败状态并广播
        summary.failed（原始 error_code/error），不伪造成功。生成在后台
        执行：先广播 summary.started，终态后广播 completed/failed。
        """
        summary_id = str(params.get("summary_id") or "").strip()
        conversation_id = str(params.get("conversation_id") or "").strip()
        if not summary_id:
            raise ServiceError("summary.regenerate 需要 summary_id", code="summary_invalid")
        if not conversation_id:
            raise ServiceError("summary.regenerate 需要 conversation_id", code="summary_invalid")
        try:
            conversation = self.store.get_conversation(conversation_id)
        except KeyError:
            raise ServiceError(
                f"会话不存在：{conversation_id}", code="conversation_not_found"
            ) from None
        try:
            summary = self.store.get_summary(summary_id)
        except KeyError:
            raise ServiceError(
                f"摘要不存在：{summary_id}", code="summary_invalid"
            ) from None
        require_summary_conversation(summary, conversation_id)
        if summary.status not in ("failed", "completed"):
            # 契约 §2：只有真实失败记录或用户显式请求允许重新生成；
            # running/idle 记录没有可恢复目标，按无效请求失败。
            raise ServiceError(
                f"摘要状态 {summary.status} 不支持重新生成（仅 failed/completed）",
                code="summary_invalid",
            )
        # 起点状态机：failed 保留旧覆盖区间；completed 由用户显式请求触发
        # （重新压缩全量未覆盖消息）。先广播 started 再异步执行。
        task = asyncio.create_task(
            self._run_summary_regeneration(conversation, summary),
            name=f"summary:{conversation_id}:{summary_id}",
        )
        self._summary_tasks.add(task)
        task.add_done_callback(self._summary_tasks.discard)
        self.emitter.emit(
            "summary.started",
            summary_event_payload(
                summary,
                account_id=self.current_account_id,
                project_id=conversation.project_id or "",
                pair_id=conversation.pair_id,
                character_ref=self._conversation_character_ref(conversation),
                assistant_identity=self._conversation_assistant_identity(conversation),
            ),
        )
        return {"summary_id": summary_id, "conversation_id": conversation_id, "status": "running"}

    async def _run_summary_regeneration(
        self, conversation: Any, previous: Any
    ) -> None:
        """后台摘要生成：调真实模型 → 校验 → 落库 → 广播终态。

        失败保留真实失败状态（error_code/error 原文），不生成空摘要。
        """
        conversation_id = conversation.conversation_id
        try:
            snapshot = self.store.load_conversation(conversation_id)
            messages = tuple(snapshot.get("messages", ()))
            # 区间：failed 记录保留了失败时意图覆盖的区间；重新生成压缩
            # 同一区间（failed 区间不存在/无效时按待摘要全部消息）。
            if previous.covers_from_message_id and previous.covers_to_message_id:
                start = _message_index(
                    messages, previous.covers_from_message_id
                )
                end = _message_index(messages, previous.covers_to_message_id)
                if start is None or end is None or start > end:
                    raise SummaryError(
                        "失败摘要区间引用了不存在的消息", code=SUMMARY_INVALID
                    )
                window = tuple(messages[start : end + 1])
                pending = role_messages(window)
                covers_from = messages[start].message_id
                covers_to = messages[end].message_id
                covers_count = len(pending)
            else:
                pending = role_messages(messages)
                if not pending:
                    raise SummaryError("没有可摘要的新消息", code=SUMMARY_INVALID)
                covers_from = pending[0].message_id
                covers_to = pending[-1].message_id
                covers_count = len(pending)
            if not pending:
                raise SummaryError("没有可摘要的新消息", code=SUMMARY_INVALID)
            pair_id = conversation.pair_id
            pair_config = load_pair_config(pair_id)
            assistant_prompt = load_prompt(pair_config.assistant.prompt)
            context_text = "\n".join(
                f"{_speaker_label(message)}：{message.text.strip()}"
                for message in pending
                if message.text.strip()
            )
            raw = await self.dialogue_model.generate_summary(
                pair_id=pair_id,
                assistant_prompt=assistant_prompt,
                context_text=context_text,
            )
            if not isinstance(raw, dict):
                raise SummaryError(
                    "摘要生成未返回 JSON 对象", code=SUMMARY_PROVIDER_ERROR
                )
            # V039-S4-013：标注实际生效的供应商与模型（与角色对话共用
            # _dialogue_runtime_settings 的解析口径），未配置时如实为 null。
            provider, model = self._effective_dialogue_identity()
            # 幂等语义（契约 §2）：regenerate 更新原 summary_id 行——
            # storage 的 upsert 以 (conversation_id, covers_from, covers_to)
            # 为键；失败记录的区间在落库时已保存，此处沿用不换区间。
            summary = StorageSummary(
                summary_id=previous.summary_id,
                conversation_id=conversation_id,
                covers_from_message_id=covers_from,
                covers_to_message_id=covers_to,
                covers_message_count=covers_count,
                content=_summary_content_text(raw),
                provider=provider,
                model=model,
                status="completed",
            )
            validate_summary_coverage(messages, summary)
            stored = self.store.upsert_summary(summary)
            # 投影侧摘要覆盖终点推进；角色上下文随后收窄（保留最近 12 条）。
            self.orchestrator.set_summary_coverage(
                conversation_id, stored.covers_to_message_id
            )
            self.emitter.emit(
                "summary.completed",
                summary_event_payload(
                    stored,
                    account_id=self.current_account_id,
                    project_id=conversation.project_id or "",
                    pair_id=conversation.pair_id,
                    character_ref=self._conversation_character_ref(conversation),
                    assistant_identity=self._conversation_assistant_identity(conversation),
                ),
            )
        except asyncio.CancelledError:
            raise
        except SummaryError as exc:
            await self._broadcast_summary_failed(
                conversation, previous, error_code=exc.code, error=str(exc)
            )
        except Exception as exc:  # noqa: BLE001 - 生成失败保留真实失败状态
            logger.exception("摘要重新生成失败（conversation=%s）", conversation_id)
            await self._broadcast_summary_failed(
                conversation,
                previous,
                error_code=SUMMARY_PROVIDER_ERROR,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _maybe_auto_summary(self, message: Any) -> None:
        """消息落库后的自动压缩触发判定（V0.3.9 §2）。

        只做纯函数判定（同会话未压缩 role 消息 ≥80 条或正文 ≥256KiB）：
        - 只有最终落库的角色消息才计数（summary_trigger 内 role_messages 过滤）；
        - 会话已有在途自动压缩/regenerate 任务时不重复触发；
        - 触发后异步跑 _run_auto_summary（后台调模型），不阻塞对话主链路；
        - 频繁消息下判定只读内存/DB，不做同步模型调用。
        """
        if not is_final_message(message):
            return
        conversation_id = message.conversation_id
        if conversation_id in self._auto_summary_in_flight:
            return
        try:
            self.store.get_conversation(conversation_id)
        except KeyError:
            return
        snapshot = self.store.load_conversation(conversation_id)
        messages = tuple(snapshot.get("messages", ()))
        covered_to = self.orchestrator.summary_coverage(conversation_id)
        trigger = summary_trigger(messages, covered_to_message_id=covered_to)
        if not trigger.should_start:
            return
        # 标记在途（防重入），广播 started 再异步生成。
        self._auto_summary_in_flight.add(conversation_id)
        try:
            conversation = self.store.get_conversation(conversation_id)
        except KeyError:
            self._auto_summary_in_flight.discard(conversation_id)
            return
        # 区间在触发时刻固定（生成期间新消息不改变本次 covers_*）。
        summary_id = f"auto-{conversation_id}-{message.message_id}"
        running_record = _running_summary_record(
            conversation_id=conversation_id,
            summary_id=summary_id,
            messages=messages,
            covered_to_message_id=covered_to,
            trigger=trigger,
        )
        self.emitter.emit(
            "summary.started",
            summary_event_payload(
                running_record,
                account_id=self.current_account_id,
                project_id=conversation.project_id or "",
                pair_id=conversation.pair_id,
                character_ref=self._conversation_character_ref(conversation),
                assistant_identity=self._conversation_assistant_identity(conversation),
            ),
        )
        task = asyncio.create_task(
            self._run_auto_summary(conversation, running_record, trigger),
            name=f"auto-summary:{conversation_id}",
        )
        self._summary_tasks.add(task)

        def _clear(completed: asyncio.Task[None]) -> None:
            self._summary_tasks.discard(completed)
            self._auto_summary_in_flight.discard(conversation_id)

        task.add_done_callback(_clear)

    async def _run_auto_summary(
        self, conversation: Any, running_record: Any, trigger: Any
    ) -> None:
        """自动压缩后台生成：区间=触发时刻固定（running 记录已定 covers_*）。

        生成期间新消息不改变本次区间；成功推进覆盖终点，失败保留真实
        失败状态（_broadcast_summary_failed 沿用 running 区间）。
        """
        conversation_id = conversation.conversation_id
        try:
            snapshot = self.store.load_conversation(conversation_id)
            messages = tuple(snapshot.get("messages", ()))
            # 窗口=触发时刻 running 记录固定的 covers 区间（生成期间新消息
            # 不改变本次压缩范围，留给下一次触发）。
            window_messages = _window_for_record(messages, running_record)
            if not window_messages:
                raise SummaryError("没有可摘要的新消息", code=SUMMARY_INVALID)
            content, provider, model = await self._generate_summary_content(
                conversation, window_messages
            )
            summary = StorageSummary(
                summary_id=running_record.summary_id,
                conversation_id=conversation_id,
                covers_from_message_id=running_record.covers_from_message_id,
                covers_to_message_id=running_record.covers_to_message_id,
                covers_message_count=running_record.covers_message_count,
                content=_summary_content_text(content),
                provider=provider,
                model=model,
                status="completed",
            )
            validate_summary_coverage(messages, summary)
            stored = self.store.upsert_summary(summary)
            self.orchestrator.set_summary_coverage(
                conversation_id, stored.covers_to_message_id
            )
            self.emitter.emit(
                "summary.completed",
                summary_event_payload(
                    stored,
                    account_id=self.current_account_id,
                    project_id=conversation.project_id or "",
                    pair_id=conversation.pair_id,
                    character_ref=self._conversation_character_ref(conversation),
                    assistant_identity=self._conversation_assistant_identity(conversation),
                ),
            )
        except asyncio.CancelledError:
            raise
        except SummaryError as exc:
            await self._broadcast_summary_failed(
                conversation, running_record, error_code=exc.code, error=str(exc)
            )
        except Exception as exc:  # noqa: BLE001 - 生成失败保留真实失败状态
            logger.exception("自动压缩失败（conversation=%s）", conversation_id)
            await self._broadcast_summary_failed(
                conversation,
                running_record,
                error_code=SUMMARY_PROVIDER_ERROR,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _generate_summary_content(
        self, conversation: Any, messages: tuple
    ) -> tuple[dict, str | None, str | None]:
        """调模型生成摘要内容；返回 (content, provider, model)。"""
        pair_id = conversation.pair_id
        pair_config = load_pair_config(pair_id)
        assistant_prompt = load_prompt(pair_config.assistant.prompt)
        context_text = "\n".join(
            f"{_speaker_label(message)}：{message.text.strip()}"
            for message in messages
            if message.text.strip()
        )
        raw = await self.dialogue_model.generate_summary(
            pair_id=pair_id,
            assistant_prompt=assistant_prompt,
            context_text=context_text,
        )
        if not isinstance(raw, dict):
            raise SummaryError(
                "摘要生成未返回 JSON 对象", code=SUMMARY_PROVIDER_ERROR
            )
        provider, model = self._effective_dialogue_identity()
        return raw, provider, model

    def _effective_dialogue_identity(self) -> tuple[str | None, str | None]:
        """实际生效的 (供应商, 模型)；摘要与记忆记录据此标注来源（V039-S4-013）。

        与角色对话共用 _dialogue_runtime_settings 的解析口径：配置缺省时
        取供应商默认模型，与环境变量口径一致，避免记录与实际调用分叉；
        确实解析不出时如实返回 null，不猜测。
        """
        config = self._load_account_config()
        provider, _base_url, _api_key, model = self._dialogue_runtime_settings(config)
        return provider or None, model or None

    async def _broadcast_summary_failed(
        self, conversation: Any, previous: Any, *, error_code: str, error: str
    ) -> None:
        """摘要失败：落库失败记录并广播 summary.failed（原始错误，不伪造成功）。"""
        failed = StorageSummary(
            summary_id=previous.summary_id,
            conversation_id=conversation.conversation_id,
            covers_from_message_id=previous.covers_from_message_id,
            covers_to_message_id=previous.covers_to_message_id,
            covers_message_count=previous.covers_message_count,
            content="",
            status="failed",
            error_code=error_code,
            error=error,
        )
        stored = self.store.upsert_summary(failed)
        self.emitter.emit(
            "summary.failed",
            summary_event_payload(
                stored,
                account_id=self.current_account_id,
                project_id=conversation.project_id or "",
                pair_id=conversation.pair_id,
                character_ref=self._conversation_character_ref(conversation),
                assistant_identity=self._conversation_assistant_identity(conversation),
            ),
        )

    def _conversation_character_ref(self, conversation: Any) -> str:
        """会话角色身份（card:<id> 或 builtin:<id>）。"""
        try:
            identity = self._conversation_identity(conversation)
        except MemoryError:
            return ""
        scope = resolve_memory_scope(identity)
        return scope.character_ref if scope is not None else ""

    def _conversation_assistant_identity(self, conversation: Any) -> str:
        try:
            return self._conversation_identity(conversation).assistant_identity
        except MemoryError:
            return ""

    def _conversation_identity(self, conversation: Any) -> ConversationIdentity:
        """解析会话身份（角色卡与权威搭档配置的 assistant.id，不接受客户端参数）。"""
        pair_config = load_pair_config(conversation.pair_id)
        return ConversationIdentity(
            account_id=self.current_account_id,
            project_id=conversation.project_id or None,
            conversation_id=conversation.conversation_id,
            pair_id=conversation.pair_id,
            character_card_id=conversation.character_card_id,
            pair_character_id=pair_config.character.id,
            assistant_identity=pair_config.assistant.id,
        )

    def _conversation_scope(self, conversation_id: str) -> StorageMemoryScope:
        """按会话解析记忆作用域；无项目/身份不完整按真实错误失败（契约 §1/§2）。"""
        try:
            conversation = self.store.get_conversation(conversation_id)
        except KeyError:
            raise ServiceError(
                f"会话不存在：{conversation_id}", code="conversation_not_found"
            ) from None
        scope = resolve_memory_scope(self._conversation_identity(conversation))
        if scope is None:
            raise ServiceError(
                "日常聊天（无项目）不读写长期记忆",
                code=MEMORY_INVALID,
            )
        # storage 作用域与 core 作用域同构（分量一致）；存储层查询用带
        # as_key/scope 的 storage 模型，此处显式转换，不依赖鸭子类型。
        try:
            return StorageMemoryScope(
                account_id=scope.account_id,
                project_id=scope.project_id,
                pair_id=scope.pair_id,
                character_ref=scope.character_ref,
                assistant_identity=scope.assistant_identity,
            )
        except ValueError as exc:
            raise ServiceError(str(exc), code=MEMORY_INVALID) from exc

    def _memory_scope_from_params(self, params: Mapping[str, Any]) -> StorageMemoryScope:
        """客户端显式作用域请求：只用于查询过滤，写入与更新一律以会话权威作用域为准。

        契约 §1：记忆作用域由服务端解析，不接受客户端拼接键。
        """
        try:
            return StorageMemoryScope(
                account_id=self.current_account_id,
                project_id=_optional_text(params, "project_id") or "",
                pair_id=_optional_text(params, "pair_id") or "",
                character_ref=_optional_text(params, "character_ref") or "",
                assistant_identity=_optional_text(params, "assistant_identity") or "",
            )
        except ValueError as exc:
            raise ServiceError(str(exc), code=MEMORY_INVALID) from exc

    async def _summary_get(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """summary.get：按会话读取摘要（显式只读；默认全部状态）。"""
        conversation_id = _optional_text(params, "conversation_id")
        if not conversation_id:
            raise ServiceError("summary.get 需要 conversation_id", code="summary_invalid")
        try:
            self.store.get_conversation(conversation_id)
        except KeyError:
            raise ServiceError(
                f"会话不存在：{conversation_id}", code="conversation_not_found"
            ) from None
        summaries = self.store.list_summaries(
            conversation_id, status=_optional_text(params, "status")
        )
        return {
            "summaries": [
                _summary_payload(summary)
                for summary in summaries
            ]
        }

    async def _memory_create(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """memory.create：显式新增一条长期记忆（V039-S4-003）。

        作用域以会话权威解析（五分量），不接受客户端拼接；日常聊天（无项目）
        没有记忆作用域，按真实错误拒绝。content 由调用方负责，代码不改写。
        """
        conversation_id = _optional_text(params, "conversation_id")
        if not conversation_id:
            raise ServiceError("memory.create 需要 conversation_id", code=MEMORY_INVALID)
        scope = self._conversation_scope(conversation_id)
        content = params.get("content")
        if not isinstance(content, Mapping):
            raise ServiceError("记忆内容必须是 JSON 对象", code=MEMORY_INVALID)
        if not content:
            # 与 MemoryDraft.content（min_length=1）同一契约：空对象不是可
            # 处理的记忆，不接受后再让调用方拿到一条空条目。
            raise ServiceError("记忆内容不得为空对象", code=MEMORY_INVALID)
        stored = self._store_memory(
            conversation_id=conversation_id,
            scope=scope,
            content=dict(content),
        )
        return {"memory": _memory_payload(stored, conversation_id=conversation_id)}

    def _store_memory(
        self,
        *,
        conversation_id: str,
        scope: StorageMemoryScope,
        content: Mapping[str, Any],
    ) -> Any:
        """写一条长期记忆并广播 memory.updated（显式创建与模型产出共用）。"""
        provider, model = self._effective_dialogue_identity()
        stored = self.store.upsert_memory(
            StorageMemory(
                account_id=scope.account_id,
                project_id=scope.project_id,
                pair_id=scope.pair_id,
                character_ref=scope.character_ref,
                assistant_identity=scope.assistant_identity,
                conversation_id=conversation_id,
                content=_json_text(dict(content)),
                provider=provider,
                model=model,
            )
        )
        self.emitter.emit(
            "memory.updated",
            _memory_payload(stored, conversation_id=conversation_id),
        )
        return stored

    def _report_memory_not_stored(
        self,
        conversation_id: str,
        drafts: tuple[Any, ...],
        reason: str,
        *,
        code: str,
    ) -> None:
        """本轮记忆未落库的如实暴露（日志 + diagnostic.warning，绝不只是丢弃）。"""
        logger.warning(
            "长期记忆未落库（conversation=%s，条数=%s）：%s",
            conversation_id,
            len(drafts),
            reason,
        )
        self._emit_diagnostic_warning(
            {
                "source": "memory",
                "conversation_id": conversation_id,
                "count": len(drafts),
                "message": f"本轮 {len(drafts)} 条长期记忆未落库：{reason}",
                "code": code,
            }
        )

    def _persist_memory_drafts(
        self, conversation_id: str, drafts: tuple[Any, ...]
    ) -> None:
        """落库角色本轮声明的长期记忆条目（V039-S4-003）。

        运行时协议只在有项目（有记忆作用域）时提供 memory 字段，因此无项目
        会话收到条目即协议越界：本轮消息与终态不受影响，但绝不静默丢弃——
        记日志并广播 diagnostic.warning，让「模型写了却没落库」可见。
        """
        if not drafts:
            return
        # 先整体校验再逐条写入：任何一条不可用时整批不落库，绝不部分写入。
        if any(not dict(draft.content) for draft in drafts):
            self._report_memory_not_stored(conversation_id, drafts, "记忆内容不得为空对象", code=MEMORY_INVALID)
            return
        try:
            scope = self._conversation_scope(conversation_id)
        except ServiceError as exc:
            self._report_memory_not_stored(conversation_id, drafts, str(exc), code=exc.code)
            return
        for draft in drafts:
            self._store_memory(
                conversation_id=conversation_id,
                scope=scope,
                content=draft.content,
            )

    async def _memory_list(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """memory.list：按作用域读取记忆（显式只读；默认 active）。"""
        conversation_id = _optional_text(params, "conversation_id")
        scope = (
            self._conversation_scope(conversation_id)
            if conversation_id
            else self._memory_scope_from_params(params)
        )
        status = _optional_text(params, "status")
        limit = params.get("limit")
        memories = self.store.list_memories(
            scope,
            status=status,
            limit=int(limit) if limit is not None else None,
        )
        return {
            "memories": [
                _memory_payload(memory, conversation_id=conversation_id)
                for memory in memories
            ]
        }

    async def _memory_update(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """memory.update：更新记忆内容/状态；作用域以会话权威解析，越作用域真实报错。"""
        conversation_id = _optional_text(params, "conversation_id")
        scope = (
            self._conversation_scope(conversation_id)
            if conversation_id
            else self._memory_scope_from_params(params)
        )
        memory_id = str(params.get("memory_id") or "").strip()
        if not memory_id:
            raise ServiceError("memory.update 需要 memory_id", code=MEMORY_INVALID)
        content = params.get("content")
        status = _optional_text(params, "status")
        fields: dict[str, Any] = {}
        if content is not None:
            if not isinstance(content, Mapping):
                raise ServiceError("记忆内容必须是 JSON 对象", code=MEMORY_INVALID)
            # 存储层 content 是 JSON 文本；协议侧由 memory_event_payload 解析回对象。
            fields["content"] = _json_text(dict(content))
        if status is not None:
            if status not in {"active", "deleted"}:
                raise ServiceError(
                    f"未知记忆状态：{status}", code=MEMORY_INVALID
                )
            fields["status"] = status
        if not fields:
            raise ServiceError("memory.update 无更新字段", code=MEMORY_INVALID)
        try:
            stored = self.store.update_memory(memory_id, scope=scope, **fields)
        except KeyError as exc:
            raise ServiceError(str(exc), code=MEMORY_NOT_FOUND) from exc
        except ValueError as exc:
            raise ServiceError(str(exc), code=MEMORY_INVALID) from exc
        self.emitter.emit(
            "memory.updated",
            _memory_payload(stored, conversation_id=conversation_id),
        )
        return {"memory": _memory_payload(stored, conversation_id=conversation_id)}

    async def _memory_delete(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """memory.delete：软删除记忆并持久化广播（契约 §2 真实状态）。"""
        conversation_id = _optional_text(params, "conversation_id")
        scope = (
            self._conversation_scope(conversation_id)
            if conversation_id
            else self._memory_scope_from_params(params)
        )
        memory_id = str(params.get("memory_id") or "").strip()
        if not memory_id:
            raise ServiceError("memory.delete 需要 memory_id", code=MEMORY_INVALID)
        try:
            stored = self.store.delete_memory(memory_id, scope=scope)
        except KeyError as exc:
            raise ServiceError(str(exc), code=MEMORY_NOT_FOUND) from exc
        self.emitter.emit(
            "memory.deleted",
            _memory_payload(stored, conversation_id=conversation_id),
        )
        return {"memory": _memory_payload(stored, conversation_id=conversation_id)}

    async def _diagnostics_prompt_assembly(
        self, params: Mapping[str, Any]
    ) -> dict[str, Any]:
        """diagnostics.prompt_assembly：显式只读查询装配诊断（契约 §5）。

        默认只返回模块名、字符范围、hash、摘要与记忆是否注入及既有
        diagnostics；只有 include_hidden=true 时返回隐藏原文（内容来自
        装配模块的原文，不属于对话流）。无绑定卡/卡已删除时返回空模块
        列表并附说明，不伪造装配结果。
        """
        conversation_id = _optional_text(params, "conversation_id")
        include_hidden = params.get("include_hidden") is True
        if not conversation_id:
            raise ServiceError("prompt_assembly 需要 conversation_id", code="missing_conversation")
        try:
            conversation = self.store.get_conversation(conversation_id)
        except KeyError:
            raise ServiceError(
                f"会话不存在：{conversation_id}", code="conversation_not_found"
            ) from None
        card_id = conversation.character_card_id
        modules: list[dict[str, Any]] = []
        diagnostics: list[str] = []
        generated_at = utc_now().isoformat()
        # V039-S4-011：空模块结果必须能自证原因，调用方与界面据此区分
        # 「未绑定卡」「卡已删除/归档」「绑定卡但装配为空」三种情况。
        reason: str | None = None
        if not card_id:
            reason = "character_card_unbound"
        elif self.card_repository.is_archived(card_id):
            reason = "character_card_archived"
        else:
            try:
                recent = self._recent_scan_messages(conversation_id)
                assembled = self._resolve_character_prompt(
                    conversation_id, recent_messages=recent
                )
            except KeyError:
                # 仓储里查不到卡：如实报缺失，不伪装成「装配为空」。
                assembled = None
                reason = "character_card_missing"
            if assembled is not None:
                for module in assembled.modules:
                    modules.append(
                        {
                            "name": module.title or module.kind,
                            "char_start": module.char_start,
                            "char_end": module.char_end,
                            "hash": None,
                            "summary": None,
                            "memory_injected": module.kind in ("chat_summary", "pair_memory"),
                            "hidden_content": module.content if include_hidden else None,
                        }
                    )
                for key, value in assembled.diagnostics.items():
                    diagnostics.append(f"{key}: {_diagnostics_label(value)}")
            # 绑定卡且未归档，却没产出任何模块：如实标为「装配为空」。
            if not modules and reason is None:
                reason = "assembly_empty"
        if not modules and reason is not None:
            diagnostics.append(_assembly_empty_label(reason, card_id))
        return {
            "conversation_id": conversation_id,
            "modules": modules,
            "reason": reason,
            "diagnostics": diagnostics,
            "generated_at": generated_at,
        }

    def _recent_scan_messages(self, conversation_id: str) -> tuple:
        """最近扫描窗口的消息（装配现算段；未绑定会话为空元组）。"""
        try:
            loaded = self.store.load_conversation(conversation_id)
        except KeyError:
            return ()
        messages = loaded.get("messages", ())
        # 契约 §4.4：扫描最近 12 条角色/用户消息。
        return tuple(messages[-12:])

    async def _account_list(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        return {
            "accounts": self._account_list_payload(),
            "current_account_id": self.current_account_id,
        }

    async def _account_register(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """注册并登录：新账号成为当前账号（账号级数据从此隔离）。"""
        username = self._required_string(params, "username")
        password = self._required_string(params, "password")
        display_name = str(params.get("display_name") or username)
        if len(password) < 6:
            raise ServiceError("密码至少 6 位", code="weak_password")
        try:
            account = self.store.create_account(
                username=username, display_name=display_name, password=password
            )
        except ValueError as exc:
            raise ServiceError(str(exc), code="username_taken") from exc
        await self._switch_account(account["account_id"])
        self.store.update_last_login(account["account_id"])
        return {
            "account": self._account_payload(account["account_id"]),
            "accounts": self._account_list_payload(),
        }

    async def _account_login(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """本地登录：密码校验通过后切换为当前账号。"""
        account_id = str(params.get("account_id") or "")
        username = str(params.get("username") or "")
        password = str(params.get("password") or "")
        if not account_id and username:
            account = self.store.get_account_by_username(username)
            if account is None:
                raise ServiceError("账号不存在", code="account_not_found")
            account_id = account["account_id"]
        if not account_id:
            raise ServiceError("缺少 account_id 或 username", code="invalid_params")
        if not self.store.verify_password(account_id, password):
            raise ServiceError("密码错误", code="wrong_password")
        await self._switch_account(account_id)
        self.store.update_last_login(account_id)
        return {
            "account": self._account_payload(account_id),
            "accounts": self._account_list_payload(),
        }

    async def _account_logout(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """退出当前账号：回到默认账号（登录页状态），数据不删除。"""
        del params
        await self._switch_account("default-local")
        return {
            "account": self._account_payload("default-local"),
            "accounts": self._account_list_payload(),
        }

    async def _account_switch(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """免密切换（本地信任的多账号切换；登录仍走 _account_login）。"""
        account_id = self._required_string(params, "account_id")
        if not self._account_exists(account_id):
            raise ServiceError("账号不存在", code="account_not_found")
        await self._switch_account(account_id)
        return {
            "account": self._account_payload(account_id),
            "accounts": self._account_list_payload(),
        }

    async def _account_update_profile(self, params: Mapping[str, Any]) -> dict[str, Any]:
        display_name = params.get("display_name")
        avatar = params.get("avatar")
        if display_name is None and avatar is None:
            raise ServiceError("没有需要更新的字段", code="invalid_params")
        account = self.store.update_account_profile(
            self.current_account_id,
            display_name=str(display_name) if display_name is not None else None,
            avatar=str(avatar) if avatar is not None else None,
        )
        self._emit_account_changed()
        return {"account": account}

    async def _account_change_password(self, params: Mapping[str, Any]) -> dict[str, Any]:
        old_password = self._required_string(params, "old_password")
        new_password = self._required_string(params, "new_password")
        if len(new_password) < 6:
            raise ServiceError("新密码至少 6 位", code="weak_password")
        if not self.store.change_password(
            self.current_account_id, old_password, new_password
        ):
            raise ServiceError("原密码错误", code="wrong_password")
        return {"changed": True}

    async def _account_onboarding_complete(
        self, params: Mapping[str, Any]
    ) -> dict[str, Any]:
        """V0.2 M4：首次引导完成标记——引导只在注册后由前端显式触发，
        登录/注册命令本身不自动置位。"""
        del params
        account_id = self.current_account_id
        self.store.set_onboarding_complete(account_id, True)
        self._emit_account_changed()
        return {"account": self._account_payload(account_id)}

    def _voice_settings(self, config: dict[str, str]) -> dict[str, Any]:
        """V0.3.2 M6：语音账号配置 + 6 说话方生成状态视图（不含明文 Key）。"""
        settings = Settings.overlay(Settings.from_environment(), config)
        voices = resolve_effective_voice_profile(
            account_config=config, settings=settings, pair_config=self.pair_config
        )
        try:
            manifest = load_reference_voice_manifest()
        except VoiceManifestError as exc:
            # manifest 缺失/损坏是真实错误：状态如实暴露，不合成空列表
            speakers: list[dict[str, Any]] = []
            manifest_error = str(exc)
        else:
            manifest_error = None
            account_states = self._voice_provision_states.get(
                self.current_account_id, {}
            )
            speakers = [
                {
                    "speaker_id": entry.speaker_id,
                    "name": entry.display_name,
                    "method": entry.method,
                    "voice_id": config.get(entry.profile_key) or "",
                    "state": (
                        account_states.get(entry.speaker_id, {}).get("state")
                        if account_states.get(entry.speaker_id, {}).get("state")
                        in {"creating", "failed"}
                        else (
                            "completed"
                            if config.get(entry.profile_key)
                            else account_states.get(entry.speaker_id, {}).get(
                                "state", "not_generated"
                            )
                        )
                    ),
                    "error": account_states.get(entry.speaker_id, {}).get("error"),
                }
                for entry in manifest
            ]
        return {
            "settings": settings,
            "voices": voices,
            "speakers": speakers,
            "manifest_error": manifest_error,
        }

    async def _config_get(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        config = self._load_account_config()
        codex = self.codex_auth.status()
        provider, dialogue_base, dialogue_key, dialogue_model_name = (
            self._dialogue_runtime_settings(config)
        )
        voice_info = self._voice_settings(config)
        voice_settings: Settings = voice_info["settings"]
        voices = voice_info["voices"]
        http_base = voice_settings.resolved_http_url
        account_voice_key = (config.get("voice.api_key") or "").strip()
        credential_source = (
            "account"
            if account_voice_key
            else (
                "development_env"
                if voice_settings.dashscope_api_key
                else "not_configured"
            )
        )
        unavailable = _provider_unavailable(provider)
        return {
            # B-03：引擎由 dialogue.provider 推导且只有 reasonix acp 一条路径，
            # 前端不需要（也不应）再发送 engine。
            "engine": self._engine_for_provider(provider),
            "dialogue": {
                # 存储值原样回显，不静默迁移用户已保存的供应商选择。
                "provider": provider,
                # 旧值（OpenAI OAuth）如实标注不受支持，调用点据此拒绝并引导重配。
                "provider_supported": unavailable is None,
                "provider_unavailable": unavailable,
                "model": dialogue_model_name,
                "base_url": dialogue_base,
                "api_key_masked": self._masked(dialogue_key),
                "reasoning_effort": config.get("dialogue.reasoning_effort") or "auto",
            },
            "voice": {
                # V0.3.2 M6：BYOK——账号保存自己的 voice.api_key/voice.base_url；
                # 模型固定为产品常量只读展示，用户侧没有模型修改入口。
                "enabled": (
                    config.get("voice.enabled")
                    or ("true" if self.voice_runtime is not None else "false")
                ),
                "base_url": http_base,
                # .env 只是开发运行时凭据，不得冒充当前账号已保存 BYOK。
                "api_key_masked": self._masked(account_voice_key),
                "credential_source": credential_source,
                "ws_url": voice_settings.resolved_ws_url,
                "customization_endpoint": (
                    http_base.rstrip("/")
                    + "/services/audio/tts/customization"
                ),
                "asr_model": VOICE_ASR_MODEL,
                "tts_model": VOICE_TTS_MODEL,
                # ASR 只依赖 Key+地址；TTS 按当前搭档说话方是否已生成
                "asr_available": bool(voice_settings.dashscope_api_key),
                "voices_source": voices.state,
                "speakers": voice_info["speakers"],
                "manifest_error": voice_info["manifest_error"],
                "character_voice": voices.character_voice_id or "",
                "character_voice_name": self.pair_config.character.name,
                "assistant_voice": voices.assistant_voice_id or "",
                "assistant_voice_name": self.pair_config.assistant.name,
                "assistant_voice_enabled": config.get("assistant_voice_enabled") or "false",
                "vad_enabled": config.get("vad_enabled") or "",
            },
            "codex": {
                "status": codex.get("status"),
                "account_label": codex.get("account_label"),
            },
        }

    async def _config_set(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """账号级配置：扁平键写入 provider_configs/secret_refs，立即生效。

        V0.3.2 M6（BYOK）：开放 ``voice.api_key``（写 secret_refs）与
        ``voice.base_url``（写 provider_configs）的账号级保存；ASR/TTS
        模型与音色 ID 仍由应用固定，客户端禁止写入。保存只落库，不触发
        音色生成（生成走 voice.provision）。
        """
        updates = params.get("updates")
        if not isinstance(updates, dict):
            raise ServiceError("updates 必须是对象", code="invalid_params")
        for key, value in updates.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ServiceError("配置键与值必须是字符串", code="invalid_params")
        locked_voice_keys = {
            "voice.asr_model",
            "voice.tts_model",
            "character_voice",
            "assistant_voice",
        }
        forbidden = sorted(locked_voice_keys & set(updates))
        if forbidden:
            raise ServiceError(
                f"语音模型与音色由应用固定，不可修改：{', '.join(forbidden)}",
                code="voice_config_locked",
            )
        if "voice.base_url" in updates:
            base_url = updates["voice.base_url"].strip()
            if base_url:
                # 缺 scheme 时按 https 规范化（协议层补全，不做语义猜测）
                if "://" not in base_url:
                    base_url = f"https://{base_url}"
                parsed = urlsplit(base_url)
                if parsed.scheme not in ("http", "https") or not parsed.hostname:
                    raise ServiceError(
                        "voice.base_url 必须是有效的 HTTP(S) 服务地址",
                        code="invalid_voice_base_url",
                    )
                updates = {**updates, "voice.base_url": base_url}
        # M3.1/M3.3：配置保存与账号切换互斥；先验证候选运行时，再单事务
        # 落库，提交成功后才替换运行时。
        async with self._account_switch_lock:
            await self._save_config_updates_locked(updates)
            voice_credentials_changed = bool(
                {"voice.api_key", "voice.base_url"}.intersection(updates)
            )
            if voice_credentials_changed:
                # 语音账号配置是运行时凭据：保存后立即按新 Key/地址/音色
                # 重建 VoiceRuntime（ASR 即刻可用；TTS 按生成状态解析）。
                await self._rebuild_voice_runtime_locked()
            # 开关类偏好立即同步到 voice 快照（前端 Composer 据此隐藏语音按钮）
            account_config = self._load_account_config()
            if "voice.enabled" in updates:
                self._voice_state["enabled"] = (
                    account_config.get("voice.enabled") not in ("false", "0")
                )
                # V039-S4-012：语音开关变化后，旧错误不再描述当前状态。
                self._clear_voice_error()
            if "assistant_voice_enabled" in updates:
                self._voice_state["assistant_voice_enabled"] = (
                    account_config.get("assistant_voice_enabled") in ("true", "1")
                )
                if self.voice_runtime is not None:
                    self.voice_runtime.set_assistant_voice_enabled(
                        self._voice_state["assistant_voice_enabled"]
                    )
            if "vad_enabled" in updates:
                self._voice_state["vad_enabled"] = (
                    account_config.get("vad_enabled") in ("true", "1")
                )
            if self.voice_runtime is not None and (
                "voice.enabled" in updates or "vad_enabled" in updates
            ):
                if self._voice_state["enabled"]:
                    await self.voice_runtime.start_listening(
                        vad_enabled=self._voice_state["vad_enabled"]
                    )
                    self.voice_runtime.start_playback()
                else:
                    # 关闭总开关：停止聆听并清空待播队列，避免后台继续出声。
                    await self.voice_runtime.stop_listening()
                    await self.voice_runtime.stop_speaking_async()
            self._emit_voice_changed()
            return {"config": await self._config_get({})}

    async def _config_test_connection(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """探测对话服务连接：短请求验证 base_url/model/api_key。

        V039-S4-014：结论必须可归属到具体目标——一律回传实际探测的
        provider/base_url/model（来自当前生效配置）。被拒绝的候选写入从未
        生效，此处的「连接正常」因此不能被读成对该端点的认可。
        """
        del params
        # V039-S4-002：显式 --demo 运行时没有真实对话后端，任何「连接正常」
        # 结论都是误导。此处如实失败，不让首次引导把演示模式读成配置可用。
        if self._demo:
            return {
                "ok": False,
                "provider": "demo",
                "base_url": "",
                "model": "",
                "message": (
                    "当前是演示模式（--demo）：不进行真实连接测试，"
                    "账号配置在此模式下不生效。请以真实模式重启后再测试。"
                ),
            }
        config = self._load_account_config()
        provider, base_url, api_key, model = self._dialogue_runtime_settings(config)
        target = {
            "provider": provider,
            "base_url": base_url,
            "model": model,
        }
        # B-03：OpenAI OAuth 登录已移除，这里不再按本地登录态给出「连接正常」。
        # 旧值直接按可定位原因拒绝，不做任何网络探测。
        unavailable = _provider_unavailable(provider)
        if unavailable is not None:
            return {
                **target,
                "provider_supported": False,
                "ok": False,
                "message": unavailable["message"],
            }
        if not (base_url and api_key and model):
            return {
                **target,
                "ok": False,
                "message": "缺少对话服务配置（Base URL / API Key / 模型）",
            }
        probe = await self._probe_dialogue_connection(base_url, api_key, model)
        return {**target, **probe}

    async def _codex_oauth_start(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """B-03：OpenAI OAuth（Codex/Responses 登录）已从产品移除。

        不写任何配置、不启动浏览器进程、不触碰 Codex 登录态——直接以可定位
        错误拒绝，不留「点了没结果」的入口。
        """
        del params
        raise ServiceError(
            CODEX_LOGIN_REMOVED_MESSAGE, code=CODEX_LOGIN_REMOVED_CODE
        )

    async def _codex_oauth_status(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """只读历史 Codex 登录态（产品不再据此决定任何行为）。

        B-03 后产品不使用 Codex 登录态：这里只把磁盘上的遗留状态如实读出，
        供界面/诊断识别旧数据，不启动登录、不声明可用。
        """
        del params
        status = self.codex_auth.status()
        status["account_id"] = self.current_account_id
        return status

    async def _codex_logout(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """清理历史 Codex 登录数据（本地文件，无网络、不涉及登录流程）。"""
        del params
        return self.codex_auth.logout()

    async def _codex_api_login(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """B-03：Codex API Key 登录入口已移除。

        该方法过去会写入 Codex 登录态并顺手覆盖 dialogue.base_url/model，
        会让用户自定义的兼容端点配置被改写成 OpenAI 官方端点。现在一律
        拒绝，OpenAI 兼容端点请经 config.set 保存。
        """
        del params
        raise ServiceError(
            CODEX_LOGIN_REMOVED_MESSAGE, code=CODEX_LOGIN_REMOVED_CODE
        )

    # ---- M3 辅助 ----

    def _account_list_payload(self) -> list[dict[str, Any]]:
        return [
            {**account, "is_last_login": account["account_id"] == self.current_account_id}
            for account in self.store.list_accounts()
        ]

    def _emit_account_changed(self) -> None:
        self.emitter.emit(
            "account.changed",
            {
                "account": self._account_payload(self.current_account_id),
                "accounts": self._account_list_payload(),
            },
        )

    async def _save_config_updates_locked(self, updates: dict[str, str]) -> None:
        """M3.3：配置保存先验证后提交（调用方必须已持有账号切换锁）。

        合并候选配置 → 构建候选运行时 → 单事务写全部配置/密钥 →
        提交成功后替换运行时；任何失败都关闭候选并保持数据库旧值。
        """
        updates = self._canonicalize_provider_updates(dict(updates))
        current = self._load_account_config()
        candidate_config = {**current, **updates}
        if self._demo:
            candidate = None
        else:
            try:
                candidate = self._build_runtime_candidate(candidate_config)
            except ServiceError:
                raise
            except Exception as exc:  # noqa: BLE001
                # V039-S4-014：候选运行时构建失败就是配置被拒绝（例如引擎
                # 与端点不兼容）。必须回结构化错误码并原样保留底层报文，
                # 不得落成 internal_error 让调用方无从判断写入是否生效。
                logger.error(
                    "配置候选被拒绝，未写入任何配置：%s", exc, exc_info=True
                )
                raise ServiceError(
                    f"{type(exc).__name__}: {exc}",
                    code="config_rejected",
                ) from exc
        secret_keys = {"dialogue.api_key", "voice.api_key"}
        config_updates = {
            key: value for key, value in updates.items() if key not in secret_keys
        }
        secret_updates = {
            key: value for key, value in updates.items() if key in secret_keys
        }
        provider_keys = {
            "engine",
            "dialogue.provider",
            "dialogue.base_url",
            "dialogue.model",
            "dialogue.api_key",
            "dialogue.reasoning_effort",
        }
        # 只有运行时相关键变化才使 EngineSessionRef 失效；纯语音开关等
        # 偏好保存不应丢掉可恢复的引擎会话。
        invalidate_sessions = bool(provider_keys.intersection(updates))
        try:
            self.store.set_configs_and_secrets(
                self.current_account_id, config_updates, secret_updates
            )
        except BaseException:
            if candidate is not None:
                await self._close_runtime(
                    candidate["dialogue_model"], candidate["coding_engine"]
                )
            raise
        self._account_config = None
        if candidate is not None:
            old_model, old_engine = self._install_runtime_candidate(
                candidate, invalidate_sessions=invalidate_sessions
            )
            self._schedule_close_runtime(old_model, old_engine)

    def _build_runtime_candidate(
        self, config: dict[str, str], *, account_id: str | None = None
    ) -> dict[str, Any]:
        """只读构建候选运行时，不触碰当前 dialogue/coding/reviewer 引用。

        demo 模式无外部状态，直接返回当前引用；真实模式为指定账号构建
        dialogue model、reviewer 和 coding engine。
        """
        if self._demo:
            return {
                "dialogue_model": self.dialogue_model,
                "coding_engine": self.coding_engine,
                "reviewer": self.orchestrator.reviewer,
            }
        account_id = account_id or self.current_account_id
        # B-03：CodexAuthService 在这里只提供账号目录（Reasonix 配置写入点）。
        auth = CodexAuthService(self.store.database.parent, account_id)
        provider, dialogue_base, dialogue_key, dialogue_model_name = (
            self._dialogue_runtime_settings(config)
        )
        self._validate_provider_endpoint(provider, dialogue_base)
        reasoning_effort = config.get("dialogue.reasoning_effort") or "auto"
        # B-03：角色与助手都只走 OpenAI Chat Completions 兼容路径。
        # 历史 openai_oauth 配置同样按它自己保存的端点构建（OpenAI OAuth
        # 凭据不是 API Key，因此没有可用凭据）——请求会在真实调用上如实失败，
        # 而不是启动期退出让用户进不了设置页；config.get / test_connection
        # 会明确标注该供应商不受支持。
        if dialogue_base and dialogue_model_name:
            preset = load_reasoning_preset(dialogue_base, dialogue_model_name)
            dialogue_model = OpenAICompatibleDialogueModel(
                base_url=dialogue_base,
                api_key=dialogue_key,
                model=dialogue_model_name,
                thinking=preset.default_thinking,
                reasoning_effort=reasoning_effort,
                temperature=1.0,
            )
            # V0.3.7 契约 §4.5：运行时候选重建（启动接管账号配置、运行期
            # config/account 切换共用本方法）产生的是新对话模型实例，
            # __init__ 里挂到初始实例的 resolver 不会自动跟随——必须在此
            # 重新挂载，否则角色卡装配静默回退内置角色。
            if isinstance(dialogue_model, OpenAICompatibleDialogueModel):
                dialogue_model.character_prompt_resolver = (
                    self._resolve_character_prompt
                )
        else:
            raise ServiceError(
                "缺少对话服务配置（Base URL / 模型）",
                code="missing_dialogue_config",
            )
        coding_engine = build_coding_engine(
            codex_auth=auth,
            model=dialogue_model_name,
            base_url=dialogue_base,
            api_key=dialogue_key,
            reasoning_effort=reasoning_effort,
            diagnostic_callback=self._emit_diagnostic_warning,
        )
        return {
            "dialogue_model": dialogue_model,
            "coding_engine": coding_engine,
            "reviewer": DialogueModelReviewer(dialogue_model),
        }

    def _validate_provider_endpoint(self, provider: str, base_url: str) -> None:
        """供应商与端点一致性校验（M3.3 先验证后提交）。"""
        if provider != "openai_oauth" and base_url:
            endpoint_provider = detect_provider(base_url).value
            if (provider == "deepseek") != (endpoint_provider == "deepseek"):
                raise ServiceError(
                    "dialogue.provider 与 Base URL 不一致；请同时选择同一供应商的配置",
                    code="provider_endpoint_mismatch",
                )

    def _install_runtime_candidate(
        self, candidate: dict[str, Any], *, invalidate_sessions: bool = True
    ) -> tuple[Any, Any]:
        """把候选运行时引用交换为当前运行时。

        ``invalidate_sessions=True`` 时使旧 session 失效（运行时替换）；
        启动阶段首次安装同一账号配置时传 False，保留可跨重启恢复的会话。
        返回旧 (dialogue_model, coding_engine)，供调用方异步关闭。
        """
        old_model = self.dialogue_model
        old_engine = self.coding_engine
        self.dialogue_model = candidate["dialogue_model"]
        self.orchestrator.dialogue_model = self.dialogue_model  # type: ignore[attr-defined]
        self.orchestrator.reviewer = candidate["reviewer"]  # type: ignore[attr-defined]
        self.coding_engine = candidate["coding_engine"]
        self.orchestrator.coding_engine = self.coding_engine  # type: ignore[attr-defined]
        # 引擎类型/供应商/项目根变化都会使旧 EngineSessionRef 失效。
        # 运行时替换路径统一清空当前账号持久化 session 与内存 session，
        # 下一次任务必然新开（不会在旧 transport 上 resume）。
        if invalidate_sessions:
            self._invalidate_engine_sessions()
        return old_model, old_engine

    def _invalidate_engine_sessions(self) -> None:
        """使当前账号的 EngineSessionRef 失效（内存 + SQLite）。"""
        self.orchestrator._sessions.clear()
        self.store.clear_engine_sessions(self.current_account_id)

    def _schedule_close_runtime(self, old_model: Any, old_engine: Any) -> None:
        """异步关闭旧运行时，避免阻塞切换/保存路径。"""
        if old_model is None or old_engine is None:
            return
        if old_model is self.dialogue_model and old_engine is self.coding_engine:
            return
        task = asyncio.create_task(
            self._close_runtime(old_model, old_engine),
            name=f"close-runtime:{type(old_model).__name__}:{type(old_engine).__name__}",
        )
        self._close_runtime_tasks.add(task)
        task.add_done_callback(self._close_runtime_tasks.discard)

    async def _close_runtime(self, dialogue_model: Any, coding_engine: Any) -> None:
        """关闭旧 dialogue model、HTTP client、Codex/Reasonix transport。"""
        errors: list[str] = []
        close_model = getattr(dialogue_model, "aclose", None)
        if callable(close_model):
            try:
                await close_model()
            except Exception as exc:  # noqa: BLE001 - 关闭失败保留真实错误
                errors.append(f"dialogue_model.aclose: {type(exc).__name__}: {exc}")
        transport = getattr(coding_engine, "transport", None)
        close_transport = getattr(transport, "close", None)
        if callable(close_transport):
            try:
                await close_transport()
            except Exception as exc:  # noqa: BLE001 - 关闭失败保留真实错误
                errors.append(f"coding_engine.transport.close: {type(exc).__name__}: {exc}")
        if errors:
            logger.error("关闭旧运行时失败：%s", " | ".join(errors))

    async def _rebuild_runtime_for_account(self, config: dict[str, str]) -> None:
        """M3.2：可等待的候选构建与替换流程。

        demo 模式（Scripted）无外部状态，跳过；真实模式构建候选运行时，
        安装后异步关闭旧运行时，并让旧 EngineSessionRef 失效。
        """
        if self._demo:
            return
        candidate = self._build_runtime_candidate(config)
        old_model, old_engine = self._install_runtime_candidate(candidate)
        self._schedule_close_runtime(old_model, old_engine)

    @staticmethod
    def _engine_for_provider(provider: str) -> str:
        """B-03：产品只有一条编程助手引擎路径（reasonix acp）。

        engine 始终由 dialogue.provider 推导，且任何受支持的 Chat
        Completions 兼容端点都装配同一个 ACP 引擎；端点差异体现在写入
        Reasonix 配置的 base_url/model/api_key，不体现在引擎类型上。
        """
        del provider
        return PROGRAM_ENGINE

    def _legacy_config_notices(self, config: dict[str, str]) -> list[dict[str, str]]:
        """历史账号配置的提示项（只读；不改写任何已保存的值）。

        覆盖两类继承配置：已移除的供应商（openai_oauth）与不再生效的
        engine 值（旧版本 config.set / PAIR_HARNESS_ENGINE 写入的 codex）。
        """
        notices: list[dict[str, str]] = []
        unavailable = _provider_unavailable(self.dialogue_provider_name(config))
        if unavailable is not None:
            notices.append(unavailable)
        engine_notice = _legacy_engine_notice((config.get("engine") or "").strip())
        if engine_notice is not None:
            notices.append(engine_notice)
        return notices

    def _emit_diagnostic_warning(self, payload: dict[str, Any]) -> None:
        """V0.3.8 T4（契约 §14.6）：引擎诊断告警转发到客户端事件通道。"""
        self.emitter.emit("diagnostic.warning", payload)

    @staticmethod
    def _provider_defaults(provider: str) -> tuple[str, str]:
        if provider == "deepseek":
            return "https://api.deepseek.com", "deepseek-v4-flash"
        return "https://api.openai.com/v1", "gpt-5.6-sol"

    def _dialogue_runtime_settings(
        self, config: dict[str, str]
    ) -> tuple[str, str, str, str]:
        """返回同一供应商要给角色和古代机械共用的端点、密钥和模型。"""
        provider = self.dialogue_provider_name(config)
        default_base, default_model = self._provider_defaults(provider)
        configured_provider = bool(config.get("dialogue.provider"))
        env_base = self._env_dialogue_base()
        env_provider = (
            detect_provider(env_base).value if env_base else "openai_compatible"
        )
        can_use_env = not configured_provider or (
            provider != "openai_oauth" and env_provider == provider
        )
        base_url = config.get("dialogue.base_url") or (
            env_base if can_use_env and env_base else default_base
        )
        saved_api_key = config.get("dialogue.api_key")
        if saved_api_key is None:
            api_key = (
                self._env_dialogue_key()
                if can_use_env and provider != "openai_oauth"
                else ""
            )
        else:
            # 即使保存的是空字符串，也代表用户显式清空过；不能用环境变量补回。
            api_key = saved_api_key
        model = config.get("dialogue.model") or (
            self._env_dialogue_model()
            if can_use_env and self._env_dialogue_model()
            else default_model
        )
        return provider, base_url, api_key, model

    @staticmethod
    def _normalize_dialogue_provider(value: str) -> str:
        normalized = " ".join(value.strip().casefold().replace("_", " ").split())
        aliases = {
            "deepseek": "deepseek",
            "openai oauth": "openai_oauth",
            "openai api": "openai_compatible",
            "openai": "openai_compatible",
            "openai compatible": "openai_compatible",
            "openai 兼容 api": "openai_compatible",
            "openai 兼容 api（包括 openai api）": "openai_compatible",
        }
        try:
            return aliases[normalized]
        except KeyError as exc:
            raise ServiceError(
                f"不支持的对话服务商：{value}", code="invalid_dialogue_provider"
            ) from exc

    def _canonicalize_provider_updates(self, updates: dict[str, str]) -> dict[str, str]:
        """把一次配置写入收敛为一个供应商。

        B-03：供应商由 dialogue.provider / dialogue.base_url 决定（两者必须
        一致），engine 不再承载任何选择信息——它由后端推导并恒为
        reasonix acp；客户端发来的旧 engine 值（codex/deepseek）按可定位的
        invalid_engine 拒绝，不静默改写用户配置。
        """
        provider_keys = {
            "engine",
            "dialogue.provider",
            "dialogue.base_url",
            "dialogue.model",
            "dialogue.api_key",
        }
        if not provider_keys.intersection(updates):
            return updates
        current = self._load_account_config()
        current_provider = self.dialogue_provider_name(current)
        explicit_provider = "dialogue.provider" in updates
        explicit_engine = "engine" in updates

        if explicit_provider:
            provider = self._normalize_dialogue_provider(updates["dialogue.provider"])
            # B-03：不受支持的供应商不能经配置写入被选中（历史值仍可读取）；
            # 拒绝要可定位，且不写入半个配置。
            unavailable = _provider_unavailable(provider)
            if unavailable is not None:
                raise ServiceError(
                    unavailable["message"], code=unavailable["code"]
                )
            updates["dialogue.provider"] = provider
        elif "dialogue.base_url" in updates:
            base_url = updates["dialogue.base_url"].strip()
            provider = detect_provider(base_url).value if base_url else "openai_compatible"
            updates["dialogue.provider"] = provider
        else:
            provider = current_provider

        if provider != current_provider and not explicit_provider:
            updates["dialogue.provider"] = provider
        if provider != current_provider:
            default_base, default_model = self._provider_defaults(provider)
            updates.setdefault("dialogue.base_url", default_base)
            updates.setdefault("dialogue.model", default_model)
            # 不把上一家供应商的密钥静默带到新供应商。只有该账号保存过
            # 密钥（包括显式清空过）时才写入空值；从未保存过则保留环境
            # 变量作为默认来源，而不是制造一条“已清空”记录。
            if "dialogue.api_key" in current:
                updates.setdefault("dialogue.api_key", "")

        if explicit_engine:
            requested_engine = updates["engine"].strip().casefold()
            if requested_engine != PROGRAM_ENGINE:
                raise ServiceError(
                    f"engine={updates['engine']} 已不受支持：产品只有 "
                    f"{PROGRAM_ENGINE}（reasonix acp）一条编程助手引擎路径；"
                    "供应商请用 dialogue.provider + dialogue.base_url 选择。",
                    code="invalid_engine",
                )
        # 后端推导：任何受支持的兼容端点都装配同一个引擎。
        updates["engine"] = self._engine_for_provider(provider)

        effective_base = updates.get("dialogue.base_url") or current.get(
            "dialogue.base_url"
        ) or self._env_dialogue_base()
        if effective_base:
            endpoint_provider = detect_provider(effective_base).value
            if (provider == "deepseek") != (endpoint_provider == "deepseek"):
                raise ServiceError(
                    "dialogue.provider 与 Base URL 不一致；请同时选择同一供应商的配置",
                    code="provider_endpoint_mismatch",
                )
        return updates

    def dialogue_provider_name(self, config: dict[str, str]) -> str:
        """按 base_url 识别服务商（复用供应商探测）。"""
        configured = config.get("dialogue.provider")
        if configured:
            return self._normalize_dialogue_provider(configured)
        base_url = config.get("dialogue.base_url") or self._env_dialogue_base()
        if not base_url:
            return "openai_compatible"
        return detect_provider(base_url).value

    @staticmethod
    def _env_dialogue_base() -> str:
        return os.getenv("PAIR_HARNESS_DIALOGUE_BASE_URL", "")

    @staticmethod
    def _env_dialogue_key() -> str:
        return os.getenv("PAIR_HARNESS_DIALOGUE_API_KEY", "")

    @staticmethod
    def _env_dialogue_model() -> str:
        return os.getenv("PAIR_HARNESS_DIALOGUE_MODEL", "")

    @staticmethod
    def _env_voice_key() -> str:
        return os.getenv("DASHSCOPE_API_KEY", "")

    async def _probe_dialogue_connection(
        self, base_url: str, api_key: str, model: str
    ) -> dict[str, Any]:
        """短请求探测对话服务（不产生对话历史）。"""
        import httpx
        import time

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                )
        except Exception as exc:  # noqa: BLE001 - 探测失败给用户可读信息
            # V039-R2-001：连接层失败的异常自述可能为空串（httpx.ConnectError
            # 在本机即如此），直接拼接会留下「连接失败：」空壳。复用回合路径
            # 的回落（自述优先、为空时给真实类型名），失败状态不改写，原始
            # 异常继续进日志。
            logger.warning(
                "对话服务探测失败（base_url=%s model=%s）：%s",
                base_url,
                model,
                exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            return {"ok": False, "message": f"连接失败：{_failure_reason(exc)}"}
        latency = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            return {
                "ok": False,
                "message": f"服务返回 {response.status_code}："
                f"{response.text[:120]}",
            }
        return {"ok": True, "message": f"连接正常（延迟 {latency} ms）"}

    def _snapshot_runtime_state(self) -> dict[str, Any]:
        """记录当前账号/运行时/上下文，供切换失败回滚。"""
        return {
            "account_id": self.current_account_id,
            "codex_auth": self.codex_auth,
            "account_config": self._account_config,
            "project_id": self.current_project_id,
            "conversation_id": self.current_conversation_id,
            "pair_config": self.pair_config,
            "dialogue_model": self.dialogue_model,
            "coding_engine": self.coding_engine,
            "reviewer": self.orchestrator.reviewer,
            "sessions": dict(self.orchestrator._sessions),
        }

    async def _rollback_runtime_state(self, snapshot: dict[str, Any]) -> None:
        """把账号、上下文和运行时引用恢复为切换前快照。"""
        self.current_account_id = snapshot["account_id"]
        self.store.set_app_state("current_account_id", snapshot["account_id"])
        self.codex_auth = snapshot["codex_auth"]
        self._account_config = snapshot["account_config"]
        self.current_project_id = snapshot["project_id"]
        self.current_conversation_id = snapshot["conversation_id"]
        self.pair_config = snapshot["pair_config"]
        self.dialogue_model = snapshot["dialogue_model"]
        self.orchestrator.dialogue_model = snapshot["dialogue_model"]  # type: ignore[attr-defined]
        self.orchestrator.reviewer = snapshot["reviewer"]  # type: ignore[attr-defined]
        self.coding_engine = snapshot["coding_engine"]
        self.orchestrator.coding_engine = snapshot["coding_engine"]  # type: ignore[attr-defined]
        self.orchestrator._sessions = dict(snapshot["sessions"])
        if (
            self.voice_runtime is not None
            and snapshot["conversation_id"]
            and snapshot["pair_config"] is not None
        ):
            await self.voice_runtime.set_context_async(
                snapshot["conversation_id"], snapshot["pair_config"]
            )

    async def _cancel_work_for_account_switch(self) -> None:
        """V0.3.2 M4：按当前账号枚举并结清全部活动任务，再切换。

        取消失败时中止切换并给出可见原因；每个任务定向取消（互不串线），
        全部进入终态后才进入账号交换。
        """
        active_tasks = self.orchestrator.state.active_tasks()
        if active_tasks:
            for active in active_tasks:
                turn_task = self._conversation_turn_tasks.get(active.conversation_id)
                try:
                    cancelled = await self.orchestrator.cancel_active_task(
                        active.conversation_id, active.task_id
                    )
                except Exception as exc:  # noqa: BLE001 - 取消失败是切换的可见原因
                    raise ServiceError(
                        f"切换账号失败：取消任务 {active.task_id} 失败（{exc}）",
                        code="account_switch_cancel_failed",
                    ) from exc
                if not cancelled:
                    # 返回 False 表示没有可取消的活动生命周期；任务仍在
                    # active 集合时等待它自然收尾。
                    turn_task = None
                if turn_task is not None and not turn_task.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(turn_task), timeout=30.0)
                    except asyncio.TimeoutError as exc:
                        raise ServiceError(
                            "切换账号失败：任务取消超时，任务未进入终态",
                            code="account_switch_cancel_failed",
                        ) from exc
            # 没有 tracked task 时，等待编排器 active 集合清空（自然结束）。
            if self.orchestrator.state.active_tasks():
                try:
                    await asyncio.wait_for(
                        self._wait_active_cleared(), timeout=30.0
                    )
                except asyncio.TimeoutError as exc:
                    raise ServiceError(
                        "切换账号失败：任务取消超时，任务未进入终态",
                        code="account_switch_cancel_failed",
                    ) from exc
        # 清理其余仍在跑的后台回合（角色流等），不让旧运行时被继续使用。
        remaining = [
            task
            for task in tuple(self._conversation_turn_tasks.values())
            if not task.done()
        ]
        for task in remaining:
            task.cancel()
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)

    async def _wait_active_cleared(self) -> None:
        while self.orchestrator.state.active_tasks():
            await asyncio.sleep(0.05)

    async def _switch_account(self, account_id: str) -> None:
        """M3.1：原子账号切换——候选构建成功后一次性交换账号/上下文/运行时。

        步骤：持有账号切换锁 → 取消并等待当前任务终态 → 只读构建目标账号
        候选运行时与上下文 → 全部成功后提交账号、项目/会话和运行时引用 →
        广播 account.changed 与新快照 → 异步关闭旧运行时。任一步失败关闭
        候选并回滚原账号状态。
        """
        if account_id == self.current_account_id:
            return
        async with self._account_switch_lock:
            snapshot = self._snapshot_runtime_state()
            candidate: dict[str, Any] | None = None
            installed = False
            old_model: Any = None
            old_engine: Any = None
            try:
                # 1. 取消当前任务并等待终态；失败直接中止。
                await self._cancel_work_for_account_switch()

                # 2. 只读构建目标账号候选运行时与上下文。
                config = self._load_account_config(account_id)
                if not self._demo:
                    candidate = self._build_runtime_candidate(
                        config, account_id=account_id
                    )
                projects = self.store.list_projects_for_account(account_id)
                target_project_id = projects[0].project_id if projects else ""
                target_conversation_id = ""
                if target_project_id:
                    conversations = self.store.list_conversations(
                        target_project_id, account_id=account_id
                    )
                    if conversations:
                        target_conversation_id = conversations[0].conversation_id
                        # 候选阶段预检 pair 配置，避免提交后才因坏搭档失败。
                        target_conversation = self.store.get_conversation(
                            target_conversation_id
                        )
                        load_pair_config(target_conversation.pair_id)

                # 3. 全部候选成功后，一次性提交账号身份。
                self.current_account_id = account_id
                self.store.set_app_state("current_account_id", account_id)
                self.codex_auth = CodexAuthService(self.store.database.parent, account_id)
                self._account_config = None
                if candidate is not None:
                    old_model, old_engine = self._install_runtime_candidate(candidate)
                    installed = True

                # 4. 使用与 _select_conversation_context 相同的完整上下文选择逻辑。
                if target_conversation_id:
                    await self._select_conversation_context(
                        target_conversation_id, emit=False
                    )
                else:
                    if self.current_conversation_id:
                        self.orchestrator.close_conversation(
                            self.current_conversation_id
                        )
                    self.current_project_id = ""
                    self.current_conversation_id = ""

                # 4.5 V0.3.2 M6：语音账号配置（Key/地址/音色映射）随账号隔离，
                # 切换后必须用目标账号自己的语音配置重建 VoiceRuntime。
                # 生成状态按 account_id 隔离；切换账号时不要抹掉其他账号
                # 的瞬时失败/进行中状态，切回后仍可继续显示并重试。
                await self._rebuild_voice_runtime_locked()

                # 5. 广播账号变更与新账号快照，随后异步关闭旧运行时。
                self._emit_account_changed()
                self._emit_state_snapshot()
                if candidate is not None:
                    self._schedule_close_runtime(old_model, old_engine)
            except BaseException:
                if installed:
                    await self._rollback_runtime_state(snapshot)
                    if candidate is not None:
                        await self._close_runtime(
                            candidate["dialogue_model"], candidate["coding_engine"]
                        )
                elif candidate is not None:
                    await self._close_runtime(
                        candidate["dialogue_model"], candidate["coding_engine"]
                    )
                raise

    # ------------------------------------------------------------------ 状态与事件

    def _on_message(self, message: Message) -> None:
        payload: dict[str, Any] = {"message": message}
        # 角色自然语言回复：预判移动端朗读可用性并随 message.created 下发。
        # tts_ready=false（账号音色未生成/无 Key）时手机端不得展示可朗读
        # 入口——服务端是合成能力的唯一权威，前端不做语义猜测。
        voice_id: str | None = None
        if (
            message.source == MessageSource.CHARACTER
            and message.tts_eligible
            and message.text.strip()
        ):
            try:
                conversation = self.store.get_conversation(message.conversation_id)
            except KeyError:
                conversation = None
            if conversation is not None:
                voice_id = self._resolve_mobile_tts_voice_id(
                    message.conversation_id, conversation.character_card_id
                )
            payload["tts_ready"] = voice_id is not None
            if not voice_id:
                logger.info(
                    "mobile-tts: message.created 标注 tts_ready=false %s",
                    message.message_id,
                )
        self.emitter.emit("message.created", payload)
        # V0.3.5：角色自然语言回复 → 在线手机端 TTS 下发（契约 §5.2）；
        # 助手/工具/思考/系统消息零音频下发。
        self._maybe_relay_mobile_tts(message, voice_id)
        # V0.3.9 §2：最终落库消息到达后判定自动压缩触发（纯函数，不调模型）。
        self._maybe_auto_summary(message)

    def _emit_state_snapshot(self) -> None:
        """发出与事件自身序号一致的完整快照。"""
        snapshot = self.bootstrap()
        # EventEmitter 会把下一条事件分配为 next_sequence；快照作为该事件
        # 的载荷时，内部序号必须与外层序号一致，前端才会继续接收后续事件。
        snapshot["sequence"] = self.emitter.next_sequence
        self.emitter.emit("state.snapshot", snapshot)

    def _on_message_status_changed(self, message: Message) -> None:
        """V0.2：消息状态推进（message.status_changed），前端按 id 对账。"""
        self.emitter.emit(
            "message.status_changed", {"message": message}
        )

    def _on_review_event(self, event: str, payload: dict) -> None:
        """V0.2：审查智能体生命周期事件（只在真正调用时触发，问题 14）。

        M4.3：conversation_id 由编排器在审查回调创建时捕获并放入 payload；
        这里不再读取切换后的 ``current_conversation_id``。旧回调没有该字段
        时保留原行为作为兼容兜底。
        """
        if event in {"review.started", "review.completed", "review.failed"}:
            conversation_id = payload.get("conversation_id") or self.current_conversation_id
            self.emitter.emit(event, {"conversation_id": conversation_id, **payload})

    def _note_turn_first_event(self, conversation_id: str) -> None:
        """记下本回合首个真实引擎/流式事件的时间（只写首个，不覆盖）。

        V0.3.9 §5：first_event_latency_ms 必须来自真实首事件；没有事件的
        回合保持 null，不回落到被终态刷新过的 updated_at。
        """
        turn_id = self._active_turn_ids.get(conversation_id)
        if turn_id is None:
            return
        turn = self._turns.get(turn_id)
        if turn is None or turn.get("first_event_at"):
            return
        self._turns[turn_id] = {**turn, "first_event_at": utc_now().isoformat()}

    def _on_dialogue_event(
        self, conversation_id: str, user_message: Any, event: Any
    ) -> None:
        """V0.2：把角色对话增量转发为 message.delta 的 reasoning/speech 通道。

        结构化 JSON 增量只推送干净字段；原始 JSON 进入技术详情（raw），
        绝不进入消息气泡。思考与正文共用一个消息 id，前端才能把它们
        合成一个气泡，正文完成后再由最终消息覆盖临时流。
        """
        self._note_turn_first_event(conversation_id)
        event_type = event.type
        message_id = f"speech:{conversation_id}:{user_message.message_id}"
        if event_type == "reasoning.started":
            self.emitter.emit(
                "message.delta",
                {
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                    "pair_id": user_message.pair_id,
                    "source": "character",
                    "kind": "character.speech",
                    "channel": "reasoning",
                    "delta": "",
                    "started": True,
                    "reasoning_streaming": True,
                },
            )
            return
        if event_type == "reasoning.delta":
            self.emitter.emit(
                "message.delta",
                {
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                    "pair_id": user_message.pair_id,
                    "source": "character",
                    "kind": "character.speech",
                    "channel": "reasoning",
                    "delta": event.delta or "",
                    "reasoning_streaming": True,
                },
            )
            return
        if event_type == "reasoning.completed":
            self.emitter.emit(
                "message.delta",
                {
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                    "pair_id": user_message.pair_id,
                    "source": "character",
                    "kind": "character.speech",
                    "channel": "reasoning",
                    "delta": "",
                    "completed": True,
                    "reasoning_streaming": False,
                },
            )
            return
        if event_type == "speech.started":
            self.emitter.emit(
                "message.delta",
                {
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                    "pair_id": user_message.pair_id,
                    "source": "character",
                    "kind": "character.speech",
                    "delta": "",
                    "started": True,
                },
            )
            return
        if event_type == "speech.delta":
            self.emitter.emit(
                "message.delta",
                {
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                    "pair_id": user_message.pair_id,
                    "source": "character",
                    "kind": "character.speech",
                    "delta": event.delta or "",
                },
            )
            return
        if event_type == "speech.completed":
            self.emitter.emit(
                "message.delta",
                {
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                    "pair_id": user_message.pair_id,
                    "source": "character",
                    "kind": "character.speech",
                    "delta": "",
                    "completed": True,
                    **({"raw": event.raw} if getattr(event, "raw", None) else {}),
                },
            )
            return

    def _on_engine_event(self, event: EngineEvent) -> None:
        self._note_turn_first_event(event.conversation_id)
        event_type = event.type
        if event_type == EngineEventType.ASSISTANT_DELTA:
            stream_key = (event.conversation_id, event.task_id)
            self._assistant_stream_text[stream_key] = (
                self._assistant_stream_text.get(stream_key, "")
                + str(event.payload.get("text", ""))
            )
            message_id = self._assistant_stream_message_id(event)
            self._streaming_message_ids.setdefault(
                (event.conversation_id, event.task_id), set()
            ).add(message_id)
            self.emitter.emit(
                "message.delta",
                {
                    "message_id": message_id,
                    "conversation_id": event.conversation_id,
                    "source": "assistant",
                    "kind": "assistant.natural_language",
                    "delta": str(event.payload.get("text", "")),
                    "task_id": event.task_id,
                    "segment_index": event.payload.get("segment_index"),
                    "timeline_order": event.payload.get("timeline_order"),
                    "reasoning_streaming": False,
                },
            )
        elif event_type == EngineEventType.ASSISTANT_REASONING_DELTA:
            # 思考与正文共用同一 segment 的消息 id，工作台沿用单气泡流式展示。
            message_id = self._assistant_stream_message_id(event)
            self._streaming_message_ids.setdefault(
                (event.conversation_id, event.task_id), set()
            ).add(message_id)
            self.emitter.emit(
                "message.delta",
                {
                    "message_id": message_id,
                    "conversation_id": event.conversation_id,
                    "source": "assistant",
                    "kind": "assistant.reasoning",
                    "channel": event.payload.get("channel", "summary"),
                    "delta": str(event.payload.get("text", "")),
                    "task_id": event.task_id,
                    "segment_index": event.payload.get("segment_index"),
                    "timeline_order": event.payload.get("timeline_order"),
                    "reasoning_streaming": True,
                },
            )
        elif event_type in (
            EngineEventType.TOOL_STARTED,
            EngineEventType.TOOL_PROGRESS,
            EngineEventType.TOOL_FINISHED,
        ):
            if event_type == EngineEventType.TOOL_STARTED:
                self._enqueue_assistant_progress(event)
                # V0.3.2 M1：工具边界定稿当前 segment——旧 segment 不再接收
                # delta，前端以 message.finalized 解除流式占位
                self._finalize_streaming_segments(
                    event.conversation_id, event.task_id
                )
            self._emit_tool_run(event)
        elif event_type == EngineEventType.APPROVAL_RESOLVED:
            self._emit_engine_approval_resolved(event)

    def _emit_engine_approval_resolved(self, event: EngineEvent) -> None:
        """统一 approval.resolved 载荷（V0.3.9 契约 §6）。

        引擎路径只在没有更早终态时广播：取消/超时已由 broker 广播过同一
        approval_id 时直接跳过（首个终态获胜）。resolved_by 只取真实来源
        （desktop/remote/system），缺失保持 null，不伪造。
        """
        payload = dict(event.payload)
        approval_id = str(payload.get("approval_id") or "")
        record = self.approval_broker.resolution(approval_id)
        if record is not None and record.get("emitted"):
            return
        if record is not None:
            resolved_at = record.get("resolved_at")
            resolved_by = record.get("resolved_by")
            error_code = record.get("error_code")
            self.approval_broker.mark_emitted(approval_id)
        else:
            resolved_at = datetime.now(timezone.utc).isoformat()
            resolved_by = None
            error_code = None
        self.emitter.emit(
            "approval.resolved",
            {
                "approval_id": approval_id,
                "conversation_id": event.conversation_id,
                "task_id": event.task_id,
                "decision": payload.get("decision"),
                "resolved_by": resolved_by,
                "actor": payload.get("actor"),
                "reason": payload.get("reason"),
                "resolved_at": resolved_at,
                "error_code": error_code,
                "suggestion": payload.get("suggestion"),
            },
        )

    def _assistant_stream_message_id(self, event: EngineEvent) -> str:
        """V0.3.2 M1：优先使用编排器分配的 segment 消息 id。

        没有段信息的事件（离线演示引擎等）回退旧版整轮单消息 id。
        """
        message_id = event.payload.get("message_id")
        if message_id:
            return str(message_id)
        return f"assistant:{event.conversation_id}:{event.task_id}"

    def _finalize_streaming_segments(
        self, conversation_id: str, task_id: str | None = None
    ) -> None:
        """定稿指定任务（省略 task 时为该聊天全部任务）的流式 segment。"""
        for (conv_id, event_task_id), message_ids in tuple(
            self._streaming_message_ids.items()
        ):
            if conv_id != conversation_id:
                continue
            if task_id is not None and event_task_id != task_id:
                continue
            for message_id in message_ids:
                self.emitter.emit(
                    "message.finalized",
                    {
                        "conversation_id": conversation_id,
                        "task_id": event_task_id,
                        "message_id": message_id,
                    },
                )
            self._streaming_message_ids.pop((conv_id, event_task_id), None)

    def _emit_tool_run(self, event: EngineEvent) -> None:
        if not event.tool_call_id:
            return
        key = (event.conversation_id, event.tool_call_id)
        payload = event.payload
        current = self._tool_runs.get(key)
        if event.type == EngineEventType.TOOL_STARTED or current is None:
            status = "running"
            if event.type == EngineEventType.TOOL_FINISHED:
                status = str(payload.get("status", "succeeded"))
            run = ToolRun(
                tool_call_id=event.tool_call_id,
                conversation_id=event.conversation_id,
                task_id=event.task_id,
                engine_turn_id=event.engine_turn_id,
                sequence=event.sequence,
                status=cast(Any, status),
                title=str(payload.get("command") or payload.get("title") or "工具"),
                summary=str(payload.get("summary", "")),
                details=str(payload.get("details") or payload.get("command") or ""),
                timeline_order=payload.get("timeline_order"),
            )
        else:
            status = current.status
            if event.type == EngineEventType.TOOL_FINISHED:
                status = cast(Any, str(payload.get("status", status)))
            run = current.model_copy(
                update={
                    "sequence": event.sequence,
                    "status": status,
                    # 后续完成事件可能只带“工具调用”标题，保留开始事件里的真实命令。
                    "title": str(payload.get("command") or current.title or payload.get("title") or "工具"),
                    "summary": str(payload.get("summary", current.summary)),
                    "details": str(payload.get("details", current.details)),
                    # 首个事件分配的序号沿用，更新不改位置（计划 5.6）
                    "timeline_order": current.timeline_order
                    if current.timeline_order is not None
                    else payload.get("timeline_order"),
                }
            )
        self._tool_runs[key] = run
        self.emitter.emit("tool_run.upserted", {"tool_run": run})

    def _enqueue_assistant_progress(self, event: EngineEvent) -> None:
        """工具开始前朗读助手已经输出的阶段性说明。"""
        text = self._assistant_stream_text.pop(
            (event.conversation_id, event.task_id), ""
        ).strip()
        runtime = self.voice_runtime
        if not text or runtime is None or self._voice_state.get("enabled") is False:
            return
        enqueue = getattr(runtime, "enqueue_assistant_progress", None)
        if not callable(enqueue):
            return
        try:
            enqueue(text, conversation_id=event.conversation_id)
        except Exception:  # noqa: BLE001 - 语音提示不影响工具执行
            logger.exception("编程助手阶段性语音入队失败")

    def _on_execution_started(self, active: Any) -> None:
        # V0.3.2 M4：事件携带事件发生后的完整权威集合，前端直接替换，
        # 避免增删事件丢失后形成幽灵忙碌状态。
        active_tasks = self.orchestrator.state.active_tasks()
        self.emitter.emit(
            "task.busy_changed",
            {
                "conversation_id": active.conversation_id,
                "busy": True,
                "active_task": to_jsonable(active),
                "active_tasks": to_jsonable(active_tasks),
            },
        )

    def _on_execution_finished(self, active: Any) -> None:
        # V0.3.2 M4：只收尾本任务自己的流式 segment；其他并发任务的
        # 占位不得被误清。
        self._finalize_streaming_segments(active.conversation_id, active.task_id)
        self._assistant_stream_text.pop((active.conversation_id, active.task_id), None)
        active_tasks = self.orchestrator.state.active_tasks()
        self.emitter.emit(
            "task.busy_changed",
            {
                "conversation_id": active.conversation_id,
                "busy": False,
                "active_task": None,
                "active_tasks": to_jsonable(active_tasks),
            },
        )

    def _finalize_streaming_for_conversation(
        self, conversation_id: str, source_message_id: str
    ) -> None:
        """回合失败时对仍在流的临时消息补发 message.finalized。

        角色思考/正文占位 id 是 ``speech:{conversation_id}:{source_message_id}``，
        只登记在 ``_streaming_message_ids`` 里的助手流式 id 一并收尾；
        正常路径由最终 ``message.created`` 覆盖或 ``_on_execution_finished``
        收尾，失败路径必须显式清掉，否则前端气泡永久停在“三个点”。
        """
        message_ids: set[str] = {f"speech:{conversation_id}:{source_message_id}"}
        for (conv_id, _task_id), ids in tuple(self._streaming_message_ids.items()):
            if conv_id == conversation_id:
                message_ids.update(ids)
        for message_id in message_ids:
            self.emitter.emit(
                "message.finalized",
                {"conversation_id": conversation_id, "message_id": message_id},
            )
        for key in tuple(self._assistant_stream_text):
            if key[0] == conversation_id:
                self._assistant_stream_text.pop(key, None)

    # ------------------------------------------------------------------ 上下文工具

    def _requested_pair_id(self, params: Mapping[str, Any]) -> str:
        """解析创建命令的搭档参数；省略时保持启动搭档的旧行为。"""
        if "pair_id" not in params:
            return self.pair_config.pair_id
        pair_id = str(params["pair_id"])
        if pair_id not in PAIR_CATALOG_IDS:
            raise ServiceError(
                f"搭档不存在：{pair_id}",
                code="PAIR_NOT_FOUND",
            )
        return pair_id

    def _restore_current_conversation(self) -> None:
        if not self.current_conversation_id:
            return
        try:
            conversation = self.store.get_conversation(self.current_conversation_id)
            if conversation.account_id and conversation.account_id != self.current_account_id:
                self.current_conversation_id = ""
                return
            if conversation.project_id is not None:
                self._current_account_project(conversation.project_id, conversation_mismatch=True)
        except (KeyError, ServiceError):
            self.current_conversation_id = ""
            return
        snapshot = self.store.load_conversation(self.current_conversation_id)
        self.orchestrator.restore_conversation(snapshot)
        for tool_run in snapshot["tool_runs"]:
            self._tool_runs[(tool_run.conversation_id, tool_run.tool_call_id)] = tool_run
        # Sidecar 可能在真实委派或队列派发中途退出；进程内任务已经不存在，
        # 遗留 processing 状态不能继续伪装成运行中。
        self.orchestrator.mark_processing_delegations_failed(
            self.current_conversation_id,
            "Sidecar 在委派完成前断开，任务已停止，请重新发送。",
        )
        for item in self.store.list_queue_items(self.current_conversation_id):
            if item["status"] == "processing":
                self.store.set_queue_item_status(item["queue_item_id"], "queued")

    def _resolve_execution_context(self, conversation_id: str) -> ExecutionContext:
        """V0.3.2 M4：提交被接受时一次性解析不可变执行上下文。

        只读取 SQLite 与搭档目录，不改写 ``current_*`` 视图状态；后台
        聊天的提交与运行中的 Turn 都使用这份快照，切换界面当前聊天
        不影响已经运行的 Turn。
        """
        conversation = self.store.get_conversation(conversation_id)
        if conversation.project_id is None:
            raise ServiceError("日常聊天尚未接入桌面迁移", code="daily_chat_unavailable")
        if conversation.account_id and conversation.account_id != self.current_account_id:
            raise ServiceError("聊天不属于当前账号", code="conversation_account_mismatch")
        project = self._current_account_project(
            conversation.project_id, conversation_mismatch=True
        )
        selected_pair = load_pair_config(conversation.pair_id)
        # V0.3.3 装配断言：助手上下文恰好注入一个助手 Markdown（单一来源）。
        assistant_md = load_prompt(selected_pair.assistant.prompt)
        context = ExecutionContext(
            account_id=self.current_account_id,
            project=ProjectRef(
                project_id=project.project_id,
                name=project.name,
                root_path=project.root_path,
            ),
            conversation_id=conversation.conversation_id,
            pair_id=conversation.pair_id,
            conversation_mode=conversation.last_mode,  # type: ignore[arg-type]
            approval_mode=ApprovalMode(project.approval_mode),
            reasoning_effort=project.reasoning_effort,
            assistant_instructions=assistant_md,
        )
        assert_single_assistant_markdown(context.assistant_instructions, assistant_md)
        return context

    def _effective_voice_pair(
        self, pair_id: str, conversation_id: str | None = None
    ) -> PairConfig:
        """按当前账号解析某个搭档的真实有效音色。

        V0.3.5：对话绑定卡且卡音色 voice_ready 时，角色侧 voice_id 覆盖为
        卡音色（契约 §3.4）；助手侧永不覆盖、永不可用。
        """
        pair_config = load_pair_config(pair_id)
        config = self._load_account_config()
        settings = Settings.overlay(Settings.from_environment(), config)
        voices = resolve_effective_voice_profile(
            account_config=config,
            settings=settings,
            pair_config=pair_config,
        )
        effective = effective_pair_config(pair_config, voices)
        if conversation_id is None:
            return effective
        card_voice_id = self._conversation_card_voice_id(conversation_id)
        if card_voice_id:
            return effective.model_copy(
                update={
                    "character": effective.character.model_copy(
                        update={"voice_id": card_voice_id}
                    )
                }
            )
        return effective

    def _conversation_card_voice_id(self, conversation_id: str) -> str:
        try:
            conversation = self.store.get_conversation(conversation_id)
        except KeyError:
            return ""
        card_id = conversation.character_card_id
        if not card_id:
            return ""
        try:
            record = self.card_repository.get_card(card_id)
        except KeyError:
            return ""
        profile = record.card.hsr.voice_profile if record.card.hsr else None
        if (
            profile is not None
            and profile.state == CharacterVoiceState.READY.value
            and profile.voice_id
        ):
            return profile.voice_id
        return ""

    async def _focus_voice_context(
        self, conversation_id: str, pair_id: str
    ) -> None:
        """只切换物理语音焦点，不改写 Sidecar 全局导航。"""
        if self.voice_runtime is None:
            return
        await self.voice_runtime.set_context_async(
            conversation_id,
            self._effective_voice_pair(pair_id, conversation_id),
        )

    async def _select_conversation_context(self, conversation_id: str, *, emit: bool) -> None:
        conversation = self.store.get_conversation(conversation_id)
        if conversation.project_id is None:
            raise ServiceError("日常聊天尚未接入桌面迁移", code="daily_chat_unavailable")
        if conversation.account_id and conversation.account_id != self.current_account_id:
            raise ServiceError("聊天不属于当前账号", code="conversation_account_mismatch")
        # 账号是完整隔离边界：先校验项目归属，再更新最近打开时间。
        project = self._current_account_project(
            conversation.project_id, conversation_mismatch=True
        )
        project = self.store.mark_project_opened(project.project_id)
        selected_pair = load_pair_config(conversation.pair_id)
        # V0.3.3 装配断言：切换上下文同样只注入一个助手 Markdown。
        assistant_md = load_prompt(selected_pair.assistant.prompt)
        assert_single_assistant_markdown(assistant_md, assistant_md)
        if conversation_id != self.current_conversation_id:
            self.orchestrator.close_conversation(self.current_conversation_id)
        self.current_project_id = project.project_id
        self.current_conversation_id = conversation_id
        self.pair_config = selected_pair
        self.orchestrator.select_context(
            project=ProjectRef(
                project_id=project.project_id,
                name=project.name,
                root_path=project.root_path,
            ),
            pair_id=conversation.pair_id,
            conversation_id=conversation_id,
            approval_mode=ApprovalMode(project.approval_mode),
            assistant_instructions=assistant_md,
            conversation_mode=conversation.last_mode,
        )
        if isinstance(self.dialogue_model, OpenAICompatibleDialogueModel):
            # M5.2：角色模型推理等级来自账号级 dialogue.reasoning_effort，
            # 与项目编程助手档位解耦；运行时构建时已读取，这里只防止旧项目
            # 档位在上下文切换时反向覆盖。
            account_config = self._load_account_config()
            self.dialogue_model.reasoning_effort = (
                account_config.get("dialogue.reasoning_effort") or "auto"
            )
        self._restore_current_conversation()
        if self.voice_runtime is not None:
            await self._focus_voice_context(conversation_id, conversation.pair_id)
        if emit:
            self.emitter.emit("project.changed", {"project": self._project_payload(project)})
            self.emitter.emit(
                "conversation.changed",
                {"conversation": self._conversation_payload(conversation)},
            )
            self._emit_state_snapshot()

    def _current_account_project(
        self, project_id: str, *, conversation_mismatch: bool = False
    ):
        """取当前账号的项目；外部账号 ID 在业务入口统一拒绝。"""
        project = self.store.get_project(project_id)
        if project.account_id != self.current_account_id:
            code = "conversation_account_mismatch" if conversation_mismatch else "project_account_mismatch"
            message = "聊天不属于当前账号" if conversation_mismatch else "项目不属于当前账号"
            raise ServiceError(message, code=code)
        return project

    def _current_account_conversation(self, conversation_id: str):
        """取当前账号的会话；会话归属沿项目链校验。"""
        conversation = self.store.get_conversation(conversation_id)
        if conversation.project_id is None:
            raise ServiceError("日常聊天尚未接入桌面迁移", code="daily_chat_unavailable")
        if conversation.account_id and conversation.account_id != self.current_account_id:
            raise ServiceError("聊天不属于当前账号", code="conversation_account_mismatch")
        self._current_account_project(conversation.project_id, conversation_mismatch=True)
        return conversation

    def _find_or_create_conversation(
        self, project_id: str, *, pair_id: str, character_card_id: str | None = None
    ):
        conversations = self.store.list_conversations(
            project_id, account_id=self.current_account_id
        )
        if conversations:
            return conversations[0]
        # V0.3.5：新对话快照当时的有效 active 卡（draft/归档不生效）；
        # 已开对话不受之后切换 active 卡影响（契约 §4.1/§4.3）。
        card_id = character_card_id
        if card_id is None:
            card_id = self._effective_active_card_id()
        conversation = self.store.create_conversation(
            project_id=project_id,
            pair_id=pair_id,
            title="新聊天",
            account_id=self.current_account_id,
            character_card_id=card_id,
        )
        if card_id:
            try:
                record = self.card_repository.get_card(card_id)
            except KeyError:
                record = None
            if record is not None:
                self._insert_character_greeting(conversation, record.card)
        return conversation

    def _schedule_title_generation(self, conversation_id: str, target: str) -> None:
        if conversation_id in self._title_generation_started:
            return
        if self.store.get_conversation(conversation_id).title != "新聊天":
            return
        context_sources = (
            {MessageSource.USER, MessageSource.CHARACTER}
            if target == "character"
            else {MessageSource.USER, MessageSource.ASSISTANT}
        )
        context = tuple(
            message
            for message in self.store.load_conversation(conversation_id)["messages"]
            if message.source in context_sources and message.text.strip()
        )
        if not context:
            return
        self._title_generation_started.add(conversation_id)
        pair_id = self.pair_config.pair_id
        task = asyncio.create_task(
            self._generate_title(conversation_id, pair_id=pair_id, context=context),
            name=f"title:{conversation_id}",
        )
        self._title_tasks.add(task)
        task.add_done_callback(self._title_tasks.discard)

    async def _generate_title(
        self,
        conversation_id: str,
        *,
        pair_id: str,
        context: tuple[Message, ...],
    ) -> None:
        try:
            try:
                title = await self.dialogue_model.generate_title(
                    pair_id=pair_id, context=context
                )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - 命名失败不影响聊天主链路
                logger.warning("自动生成聊天标题失败", exc_info=True)
                return
            title = self._normalize_title(title)
            if title is None:
                return
            conversation = self.store.get_conversation(conversation_id)
            if conversation.title != "新聊天":
                return
            self.store.rename_conversation(conversation_id, title)
            self.emitter.emit(
                "conversation.changed",
                {
                    "conversation": self._conversation_payload(
                        self.store.get_conversation(conversation_id)
                    )
                },
            )
        finally:
            # 只阻止同一时刻重复生成。失败或空标题后清理标记，下一轮完整
            # 回复可以重试；成功后标题已不再是“新聊天”，自然不会重复命名。
            self._title_generation_started.discard(conversation_id)

    @staticmethod
    def _normalize_title(value: object) -> str | None:
        title = " ".join(str(value or "").split()).strip("\"'“”‘’")
        if not title or title == "新聊天":
            return None
        return title[:24].strip("。！？!?：:，,") or None

    @staticmethod
    def _required_string(params: Mapping[str, Any], key: str) -> str:
        value = params.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ServiceError(f"缺少非空参数：{key}", code="invalid_params")
        return value.strip()

    @staticmethod
    def _conversation_payload(conversation: Any) -> dict[str, Any]:
        return dict(to_jsonable(conversation))

    @staticmethod
    def _empty_project_payload() -> dict[str, Any]:
        return {
            "project_id": "",
            "name": "",
            "root_path": "",
            "approval_mode": ApprovalMode.REQUEST_APPROVAL.value,
            "reasoning_effort": "low",
            "archived": False,
            "created_at": None,
            "last_opened_at": None,
            "path_available": False,
        }

    @staticmethod
    def _empty_conversation_payload() -> dict[str, Any]:
        return {
            "conversation_id": "",
            "account_id": "",
            "project_id": None,
            "pair_id": "",
            "title": "",
            "last_mode": "chat",
            "archived": False,
            "created_at": "",
            "updated_at": "",
        }

    @staticmethod
    def _project_payload(project: Any) -> dict[str, Any]:
        payload = dict(to_jsonable(project))
        payload["path_available"] = project.path_available
        return payload

    @staticmethod
    def _pair_payload(pair_config: PairConfig) -> dict[str, Any]:
        return {
            "pair_id": pair_config.pair_id,
            "character": {
                "id": pair_config.character.id,
                "name": pair_config.character.name,
                "voice_id": pair_config.character.voice_id,
            },
            "assistant": {
                "id": pair_config.assistant.id,
                "name": pair_config.assistant.name,
                "voice_id": pair_config.assistant.voice_id,
            },
            "theme": pair_config.theme.model_dump(mode="json"),
        }


def _get_or_create_project(
    store: SQLiteStore, root_path: Path, *, account_id: str = "default-local"
):
    root_path = root_path.resolve()
    recent = store.list_projects_for_account(account_id)
    if recent:
        return store.mark_project_opened(recent[0].project_id)
    existing = store.find_project_by_root_path(str(root_path))
    # M4.5：bootstrap 不自动恢复已归档项目；只有用户显式重新选择该目录时
    # 才由 project.create 恢复旧记录。
    if existing is not None and not existing.archived and existing.account_id == account_id:
        return store.mark_project_opened(existing.project_id)
    if store.list_projects(include_archived=True):
        # 用户已经把全部项目归档时，重启仍保持“暂无项目”，等待用户主动新建。
        return None
    return store.create_project(
        project_id=str(uuid4()),
        name=root_path.name or str(root_path),
        root_path=str(root_path),
        account_id=account_id,
    )


def _get_or_create_conversation(
    store: SQLiteStore, *, project_id: str, pair_id: str, account_id: str = ""
):
    conversations = store.list_conversations(project_id, account_id=account_id or None)
    if conversations:
        return conversations[0]
    return store.create_conversation(
        project_id=project_id,
        pair_id=pair_id,
        title="新聊天",
        account_id=account_id,
    )


def _build_service(
    *,
    database: Path,
    project_root: Path,
    pair_id: str,
    event_sink: EventSink,
    demo: bool,
    stream_id: str = "local",
) -> DesktopApplicationService:
    pair_catalog = list_pair_configs()
    store = SQLiteStore(database)
    account_id = store.get_app_state("current_account_id") or "default-local"
    try:
        store.get_account(account_id)
    except KeyError:
        account_id = "default-local"
        store.set_app_state("current_account_id", account_id)
    project = _get_or_create_project(store, project_root, account_id=account_id)
    conversation = (
        _get_or_create_conversation(
            store,
            project_id=project.project_id,
            pair_id=pair_id,
            account_id=account_id,
        )
        if project is not None
        else None
    )
    # Sidecar 重启时命令行只携带项目目录，不能用启动默认搭档覆盖已持久化
    # 的当前聊天。聊天的 pair_id 是业务状态，必须先恢复它再构造编排器。
    effective_pair_id = conversation.pair_id if conversation is not None else pair_id
    pair_config = load_pair_config(effective_pair_id)
    emitter = EventEmitter(event_sink, stream_id=stream_id)
    broker = ApprovalBroker(emitter)
    settings: Settings | None = None

    def emit_diagnostic_warning(payload: dict[str, Any]) -> None:
        """V0.3.8 T4（契约 §14.6）：引擎诊断告警转发到客户端事件通道。"""
        emitter.emit("diagnostic.warning", payload)

    if demo:
        dialogue_model: Any = ScriptedDialogueModel()
        coding_engine: Any = ScriptedCodingEngine()
    else:
        settings = Settings.from_environment()
        dialogue_base = settings.dialogue_base_url or ""
        dialogue_key = settings.dialogue_api_key or ""
        dialogue_model_name = settings.dialogue_model or "gpt-5.6-sol"
        preset = load_reasoning_preset(dialogue_base, dialogue_model_name)
        dialogue_model = OpenAICompatibleDialogueModel(
            base_url=dialogue_base,
            api_key=dialogue_key,
            model=dialogue_model_name,
            thinking=preset.default_thinking,
            reasoning_effort=(
                None
                if project is None or project.reasoning_effort == "auto"
                else project.reasoning_effort
            ),
            temperature=1.0,
        )
        initial_codex_auth = CodexAuthService(store.database.parent, account_id)
        coding_engine = build_coding_engine(
            codex_auth=initial_codex_auth,
            model=dialogue_model_name,
            base_url=dialogue_base,
            api_key=dialogue_key,
            diagnostic_callback=emit_diagnostic_warning,
        )

    orchestrator = ConversationOrchestrator(
        pair_id=effective_pair_id,
        project=ProjectRef(
            project_id=project.project_id if project is not None else "",
            name=project.name if project is not None else "",
            root_path=project.root_path if project is not None else str(project_root),
        ),
        dialogue_model=dialogue_model,
        coding_engine=coding_engine,
        store=store,
        approval_mode=ApprovalMode(
            project.approval_mode if project is not None else ApprovalMode.REQUEST_APPROVAL.value
        ),
        approval_callback=broker.request,
        reviewer=DialogueModelReviewer(dialogue_model) if not demo else None,
        # V0.3.3 装配断言：服务构建（含重启恢复路径）同样单一注入。
        assistant_instructions=load_prompt(pair_config.assistant.prompt),
    )
    service = DesktopApplicationService(
        store=store,
        orchestrator=orchestrator,
        pair_config=pair_config,
        pair_catalog=pair_catalog,
        emitter=emitter,
        approval_broker=broker,
        dialogue_model=dialogue_model,
        coding_engine=coding_engine,
        current_project_id=project.project_id if project is not None else "",
        current_conversation_id=conversation.conversation_id if conversation is not None else "",
    )
    if not demo:
        # 首次引导可从空配置启动；账号级配置存在时立即接管环境默认值。
        # 启动阶段使用同步候选安装（_rebuild_runtime_for_account 是异步版，
        # 供运行期 config/account 切换调用；这里尚无旧运行时需要等待）。
        old_model, old_engine = service._install_runtime_candidate(
            service._build_runtime_candidate(service._load_account_config()),
            invalidate_sessions=False,
        )
        service._schedule_close_runtime(old_model, old_engine)
        # B-03：历史账号配置（已移除的供应商 / engine 选择）在启动期如实提示，
        # 不静默改写用户已保存的值；提示后应用仍可进入设置页重新配置。
        for notice in service._legacy_config_notices(service._load_account_config()):
            service.emitter.emit(
                "error.reported",
                {
                    **notice,
                    "severity": "recoverable",
                    "fatal": False,
                    "source": "sidecar",
                },
            )
    if not demo and settings is not None and conversation is not None:
        # V0.3.2 M6：启动即用账号级语音配置覆盖环境默认（账号保存过
        # voice.api_key/voice.base_url 时账号优先，.env 只是开发机兼容）。
        # 有 Key 即可创建运行时——ASR 不依赖音色；TTS 有效音色按
        # 账号生成结果 → 开发机作者音色 → 不可用 解析。
        overlaid = Settings.overlay(
            settings, service._load_account_config(account_id)
        )
        if overlaid.dashscope_api_key:
            try:
                runtime = build_real_voice_runtime(
                    settings=overlaid,
                    orchestrator=orchestrator,
                    pair_config=pair_config,
                    conversation_id=conversation.conversation_id,
                    on_vad_state=service._on_voice_state,
                    on_asr_partial=service._on_asr_partial,
                    on_error=service._on_voice_error,
                    on_tts_state=service._on_tts_state,
                    on_text_input=service._submit_voice_input,
                    voices=resolve_effective_voice_profile(
                        account_config=service._load_account_config(account_id),
                        settings=overlaid,
                        pair_config=pair_config,
                    ),
                )
                service.attach_voice_runtime(runtime)
            except Exception as exc:  # noqa: BLE001 - 文本功能不因语音依赖失败而退出
                service._on_voice_error(f"语音运行时未启用：{exc}")
        else:
            service._on_voice_error(
                "真实语音未启用：未保存 DashScope API Key（语音页可保存账号 Key）"
            )
    return service


def build_demo_service(
    *,
    database: Path,
    project_root: Path,
    pair_id: str = "phainon_ancient_machine",
    event_sink: EventSink | None = None,
    stream_id: str = "local",
) -> DesktopApplicationService:
    """创建不需要外部凭据、不执行真实文件操作的 Sidecar 服务。"""
    return _build_service(
        database=database,
        project_root=project_root,
        pair_id=pair_id,
        event_sink=event_sink or (lambda _message: None),
        demo=True,
        stream_id=stream_id,
    )


def build_configured_service(
    *,
    database: Path | None = None,
    project_root: Path,
    pair_id: str = "phainon_ancient_machine",
    event_sink: EventSink | None = None,
    demo: bool = False,
    stream_id: str = "local",
) -> DesktopApplicationService:
    """按 Sidecar 启动配置创建 demo 或真实模型服务。"""
    if not demo:
        configured_env = os.getenv("PAIR_HARNESS_ENV_FILE")
        env_path = (
            Path(configured_env)
            if configured_env
            else Path(__file__).resolve().parents[3] / ".env"
        )
        load_dotenv(env_path)
    db = database or AppPaths.default().ensure().database
    return _build_service(
        database=db,
        project_root=project_root,
        pair_id=pair_id,
        event_sink=event_sink or (lambda _message: None),
        demo=demo,
        stream_id=stream_id,
    )
