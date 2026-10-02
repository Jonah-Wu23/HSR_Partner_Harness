from __future__ import annotations

import asyncio
import base64
import dataclasses
import io
import json
import logging
import mimetypes
import os
import time
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, cast
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from pair_harness.adapters.audio.qwen_voice_customization import (
    QwenVoiceCustomizationClient,
    VoiceCustomizationError,
    audio_file_to_data_uri,
)
from pair_harness.adapters.codex.auth import CodexAuthService
from pair_harness.adapters.demo import ScriptedCodingEngine, ScriptedDialogueModel
from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.adapters.reviewer import DialogueModelReviewer
from pair_harness.app_paths import AppPaths
from pair_harness.config.pairs import (
    PAIR_CATALOG_IDS,
    PairConfig,
    list_pair_configs,
    load_pair_config,
    load_prompt,
)
from pair_harness.config.providers import detect_provider
from pair_harness.config.voices import (
    ANCIENT_MACHINE_PREVIEW_TEXT,
    VoiceManifestError,
    assistant_speaker_ids,
    load_reference_voice_manifest,
)
from pair_harness.character_cards.codec import (
    CardImportError,
    CompatReport,
    ImportResult,
    dump_card_v3,
    load_card_json,
    load_card_payload,
)
from pair_harness.character_cards.models import (
    AvatarAsset,
    CharacterCard,
    HsrExtension,
    VoiceProfile,
)
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
from pair_harness.core.context import ExecutionContext
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    DialogueEvent,
    EngineEvent,
    EngineEventType,
    MemoryDraft,
    Message,
    MessageKind,
    MessageOrigin,
    MessageSource,
    ProjectRef,
    PendingOperation,
    SpeechRequest,
    ToolRun,
    Turn,
    TurnStatus,
    utc_now,
)
from pair_harness.storage.records import (
    ConversationSummary as StorageSummary,
    MemoryScope as StorageMemoryScope,
    MemoryStatus,
    PairMemory as StorageMemory,
    TurnMetric,
    TurnMetricQuery,
)
from pair_harness.core.orchestrator import (
    ConversationOrchestrator,
    ConversationOutcome,
    Runtime,
)
from pair_harness.core.ports import CodingEngine, DialogueModel
from pair_harness.core.repository import Conversation, ConversationSnapshot
from pair_harness.core.summary import (
    SUMMARY_INVALID,
    SUMMARY_PROVIDER_ERROR,
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
    ConversationIdentity,
    MemoryScope,
    PairMemory,
    PairMemoryError,
    resolve_memory_scope,
)
from pair_harness.core.voice_policy import is_readable_text
from pair_harness.core.voice_runtime import VoiceRuntime
from pair_harness.settings import Settings
from pair_harness.storage.sqlite_store import SQLiteStore
from .pairing import PairingError, PairingService
from .power import PowerStatusError, read_power_status
from .tunnel import TunnelManager
from .ws_server import RemoteServe
from pair_harness.voice_models import VOICE_ASR_MODEL, VOICE_TTS_MODEL

from .commands import CommandContext, DesktopCommand
from .engine_factory import build_coding_engine
from .events import EventEmitter, EventSink, to_jsonable
from .mobile_audio import (
    MobileAsrSessionManager,
    MobileAudioError,
    MobileTtsSequencer,
    RecognizerPort,
    TtsStream,
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
    """非负整数取值，否则 None（未观测保持 null，不用 0 顶替）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return None


def _duration_ms(started_at: str, completed_at: str) -> int | None:
    """两个 ISO 时间点之间的毫秒数；时钟回拨导致负值时为 None。"""
    duration = (
        datetime.fromisoformat(completed_at) - datetime.fromisoformat(started_at)
    ).total_seconds()
    return int(duration * 1000) if duration >= 0 else None


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
    """回合与连接探测的失败原因文本。

    异常自述优先；自述为空（无参异常、只带结构化字段的异常、自述为空串的
    httpx.ConnectError）时回落到类型名与结构化 code/category。
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


@dataclasses.dataclass(frozen=True)
class _CharacterAssembly:
    """角色提示词装配结果与角色基座来源（card / builtin / none）。"""

    source: str
    prompt: AssembledPrompt | None


def _assembly_empty_label(reason: str, card_id: str | None) -> str:
    """装配诊断为空的真实原因：区分未绑定、卡缺失与空装配。"""
    if reason == "character_card_unbound":
        return "未绑定角色卡：会话未选择角色卡，无装配模块"
    if reason == "character_card_missing":
        return f"角色卡不存在：{card_id}，无装配模块"
    return "已绑定角色卡但装配结果为空：无模块进入提示词"


def _summary_context_text(messages: tuple[Message, ...]) -> str:
    """摘要输入文本：按来源标注说话人，逐条拼接非空正文。"""
    return "\n".join(
        f"{'用户' if message.source == MessageSource.USER else '角色'}："
        f"{message.text.strip()}"
        for message in messages
        if message.text.strip()
    )


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
) -> StorageSummary:
    """自动压缩的 running 起点记录：区间为触发时刻的未压缩 role 消息。

    covers_* 指向真实已落库消息；没有可摘要消息时按 summary_invalid 失败。
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



def _summary_payload(summary: StorageSummary) -> dict[str, Any]:
    """storage 层摘要记录 → 协议载荷。

    completed 记录的 content 是 JSON 对象文本，解析回对象；running 与
    failed 记录的 content 为空串，载荷为 null。
    """
    return {
        "summary_id": summary.summary_id,
        "conversation_id": summary.conversation_id,
        "status": summary.status,
        "covers_from_message_id": summary.covers_from_message_id,
        "covers_to_message_id": summary.covers_to_message_id,
        "covers_message_count": summary.covers_message_count,
        "content": json.loads(summary.content) if summary.content else None,
        "provider": summary.provider,
        "model": summary.model,
        "error_code": summary.error_code,
        "error": summary.error,
        "created_at": summary.created_at.isoformat(),
        "updated_at": summary.updated_at.isoformat(),
    }


def _json_text(content: Mapping[str, Any]) -> str:
    """JSON 对象 → 紧凑文本（存储层 content 字段用，不改写内容）。"""
    return json.dumps(
        dict(content), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _memory_payload(
    memory: StorageMemory, *, conversation_id: str | None = None
) -> dict[str, Any]:
    """storage 层长期记忆 → 协议载荷：五分量作用域扁平下发，content 解析回对象。"""
    payload: dict[str, Any] = {
        "memory_id": memory.memory_id,
        "account_id": memory.account_id,
        "project_id": memory.project_id,
        "pair_id": memory.pair_id,
        "character_ref": memory.character_ref,
        "assistant_identity": memory.assistant_identity,
        "status": memory.status,
        "updated_at": memory.updated_at.isoformat(),
        "content": json.loads(memory.content),
    }
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    return payload


def _core_memory(memory: StorageMemory) -> PairMemory:
    """storage 层长期记忆 → core 装配用 ``PairMemory``；形状不符由 core 校验报错。"""
    return PairMemory(
        memory_id=memory.memory_id,
        scope=MemoryScope(
            account_id=memory.account_id,
            project_id=memory.project_id,
            pair_id=memory.pair_id,
            character_ref=memory.character_ref,
            assistant_identity=memory.assistant_identity,
        ),
        content=json.loads(memory.content),
        status=memory.status,
        updated_at=memory.updated_at,
    )


logger = logging.getLogger(__name__)

# 审批等待上限。审批发出后长时间无人裁决（如手机退后台）时如实失败并
# 释放 busy 与队列，任务不会无限期挂在等待上。
APPROVAL_TIMEOUT_S = 600.0

# timeout 是服务端专属终态，只由 broker 在等待超时后产生；它不是
# ApprovalDecision 成员，客户端提交时按未知裁决拒绝。
APPROVAL_TIMEOUT_DECISION = "timeout"

# 远程控制租约按 device_key 独立记录。TTL 45s（持有者每 15s 心跳续租，
# 3 次容错）；断连后额外宽限 15s（重连窗口），最晚 60s 回收。
CONTROL_LEASE_TTL_S = 45.0
CONTROL_LEASE_GRACE_S = 15.0
CONTROL_LEASE_SWEEP_INTERVAL_S = 5.0

CommandHandler = Callable[[Mapping[str, Any], CommandContext], Awaitable[Any]]

_JPEG_SIGNATURE = b"\xff\xd8\xff"

# 角色卡资产的扩展名与 MIME 对照。Python 3.12 内置表缺 webp 与 m4a，wav
# 只认 audio/x-wav；这里在独立实例上补登记，结果不随系统 MIME 配置变化。
_ASSET_MIME_TYPES = mimetypes.MimeTypes()
_ASSET_MIME_TYPES.add_type("image/webp", ".webp")
_ASSET_MIME_TYPES.add_type("audio/wav", ".wav")
_ASSET_MIME_TYPES.add_type("audio/mp4", ".m4a")
_REFERENCE_AUDIO_MIME_TYPES = frozenset({"audio/wav", "audio/mpeg", "audio/mp4"})


def _asset_extension(mime_type: str) -> str:
    """资产落盘扩展名（不带点），由 MIME 决定。"""
    extension = _ASSET_MIME_TYPES.guess_extension(mime_type)
    if extension is None:
        raise ValueError(f"没有登记扩展名的资产类型：{mime_type}")
    return extension.removeprefix(".")

# 产品只支持 OpenAI Chat Completions 兼容端点，编程助手引擎只有 reasonix
# acp 一条路径。历史账号里保存的旧选择如实报出并标注不受支持，不改写成
# 别的供应商，也不把请求发到不对应的端点。
PROGRAM_ENGINE = "reasonix"
SUPPORTED_DIALOGUE_PROVIDERS = frozenset({"deepseek", "openai_compatible"})
PROVIDER_UNAVAILABLE_CODE = "provider_unavailable"


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

    ``details`` 可选携带结构化附加字段，随错误响应体的 ``error.details``
    下发。
    """

    def __init__(
        self, message: str, *, code: str = "service_error", details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ApprovalBroker:
    """把编排器的异步审批等待桥接成桌面事件与命令。

    ``request`` 接收编排器从执行上下文捕获的 conversation_id 与 task_id。
    每个审批只有一个终态（allow/allow_for_conversation/deny/timeout），首个
    终态获胜，approval.resolved 只广播一次；来源缺失保持 null。
    """

    _RESOLVED_CAPACITY = 256

    def __init__(self, emitter: EventEmitter) -> None:
        self._emitter = emitter
        self._pending: dict[str, dict[str, Any]] = {}
        # 已决审批的短时终态记录：双端并发应答同一审批时，后到者收到
        # approval_already_resolved 与先到者的真实终态。容量有界。
        self._resolved: dict[str, dict[str, Any]] = {}

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
            # asyncio.wait 不取消 future：返回时未完成即是超时，裁决与超时
            # 不会互相覆盖。
            done, _ = await asyncio.wait((future,), timeout=APPROVAL_TIMEOUT_S)
            if done:
                return future.result()
            self._expire(approval_id)
            raise ServiceError(
                f"审批超时未裁决（{int(APPROVAL_TIMEOUT_S)}s）："
                "任务已按失败终止并释放，可重新发起",
                code="approval_timeout",
            )
        finally:
            self._pending.pop(approval_id, None)

    def resolve(
        self, approval_id: str, decision: str, *, resolved_by: str = "desktop"
    ) -> dict[str, Any]:
        item = self._pending.get(approval_id)
        if item is None:
            prior = self._resolved.get(approval_id)
            if prior is not None:
                # 后到者拿到先到者的真实终态（结构化字段），双端据此收敛展示。
                raise ServiceError(
                    f"审批已由 {prior['resolved_by'] or '系统'} 应答"
                    f"（{prior['decision']}），不能重复应答",
                    code="approval_already_resolved",
                    details=self._public_record(prior),
                )
            raise ServiceError(
                f"审批请求不存在或已经完成：{approval_id}",
                code="approval_not_found",
            )
        try:
            parsed = ApprovalDecision(decision)
        except ValueError as exc:
            raise ServiceError(f"未知审批决定：{decision}", code="invalid_decision") from exc
        # 用户裁决先记录终态；approval.resolved 由引擎路径带上完整结果后
        # 统一广播一次。
        record = self._settle(
            approval_id,
            parsed,
            resolved_by=resolved_by,
            actor="user",
            resolution_reason=None,
        )
        return {"decision": record["decision"], "resolved_by": record["resolved_by"]}

    def cancel_all(self) -> None:
        for approval_id in tuple(self._pending):
            self._cancel(approval_id, "Sidecar 关闭，审批已取消")

    def cancel_for_conversation(self, conversation_id: str) -> None:
        """任务取消时把该会话未决的审批按 DENY 结清并广播终态。

        编排器回调随即返回，把否决结果回复引擎；前端据事件移除待审批项。
        """
        for approval_id, item in tuple(self._pending.items()):
            if item["conversation_id"] == conversation_id:
                self._cancel(approval_id, "任务已取消，审批已否决")

    def publish_engine_resolution(self, event: EngineEvent) -> None:
        """引擎路径的 approval.resolved：同一审批已广播过终态时跳过。

        经 broker 的用户裁决此时补发记录里的真实来源；审查智能体等未经
        broker 的裁决按引擎载荷记录，resolved_by 保持 null。
        """
        payload = event.payload
        approval_id = str(payload["approval_id"])
        record = self._resolved.get(approval_id)
        if record is None:
            record = self._remember(
                approval_id,
                conversation_id=event.conversation_id,
                task_id=event.task_id,
                decision=str(payload["decision"]),
                resolved_by=None,
                actor=payload["actor"],
                request_reason=str(payload["request_reason"]),
                resolution_reason=payload["resolution_reason"],
                error_code=None,
            )
        elif record["emitted"]:
            return
        self._emit_resolved(record)

    def _settle(
        self,
        approval_id: str,
        decision: ApprovalDecision,
        *,
        resolved_by: str,
        actor: str,
        resolution_reason: str | None,
    ) -> dict[str, Any]:
        """把裁决交给等待方并记录终态。"""
        item = self._pending.pop(approval_id)
        cast(asyncio.Future[ApprovalDecision], item["future"]).set_result(decision)
        return self._remember(
            approval_id,
            conversation_id=item["conversation_id"],
            task_id=item["task_id"],
            decision=decision.value,
            resolved_by=resolved_by,
            actor=actor,
            request_reason=item["reason"],
            resolution_reason=resolution_reason,
            error_code=None,
        )

    def _cancel(self, approval_id: str, resolution_reason: str) -> None:
        record = self._settle(
            approval_id,
            ApprovalDecision.DENY,
            resolved_by="system",
            actor="system",
            resolution_reason=resolution_reason,
        )
        self._emit_resolved(record)

    def _expire(self, approval_id: str) -> None:
        """等待超时的终态：不向等待方回填裁决，由 request 抛出 approval_timeout。"""
        item = self._pending.pop(approval_id)
        record = self._remember(
            approval_id,
            conversation_id=item["conversation_id"],
            task_id=item["task_id"],
            decision=APPROVAL_TIMEOUT_DECISION,
            resolved_by="system",
            actor="system",
            request_reason=item["reason"],
            resolution_reason="等待审批超时",
            error_code="approval_timeout",
        )
        self._emit_resolved(record)

    def _remember(
        self,
        approval_id: str,
        *,
        conversation_id: str,
        task_id: str,
        decision: str,
        resolved_by: str | None,
        actor: str | None,
        request_reason: str,
        resolution_reason: str | None,
        error_code: str | None,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "approval_id": approval_id,
            "conversation_id": conversation_id,
            "task_id": task_id,
            "decision": decision,
            "resolved_by": resolved_by,
            "actor": actor,
            "request_reason": request_reason,
            "resolution_reason": resolution_reason,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "error_code": error_code,
            "emitted": False,
        }
        self._resolved[approval_id] = record
        while len(self._resolved) > self._RESOLVED_CAPACITY:
            self._resolved.pop(next(iter(self._resolved)))
        return record

    def _emit_resolved(self, record: dict[str, Any]) -> None:
        self._emitter.emit("approval.resolved", self._public_record(record))
        record["emitted"] = True

    @staticmethod
    def _public_record(record: dict[str, Any]) -> dict[str, Any]:
        """approval.resolved 载荷，也是 approval_already_resolved 的 details。"""
        return {key: value for key, value in record.items() if key != "emitted"}

    def snapshot(self) -> list[dict[str, Any]]:
        # operation 是 PendingOperation 模型，必须过 to_jsonable，否则有挂起
        # 审批时 bootstrap 响应编码失败。
        return [
            {
                "approval_id": approval_id,
                "conversation_id": item["conversation_id"],
                "task_id": item["task_id"],
                "operation": to_jsonable(item["operation"]),
                "reason": item["reason"],
            }
            for approval_id, item in self._pending.items()
        ]


@dataclasses.dataclass
class _ControlLease:
    """一条远程控制租约，按 device_key 独立记录。

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
        pair_config: PairConfig,
        pair_catalog: list[PairConfig],
        emitter: EventEmitter,
        demo: bool,
        current_account_id: str,
        current_project_id: str,
        current_conversation_id: str,
    ) -> None:
        self.store = store
        self.emitter = emitter
        # 当前登录账号是项目、聊天、配置与引擎数据的隔离边界。
        self.current_account_id = current_account_id
        # demo 模式使用离线脚本运行时，账号配置不参与装配。
        self._demo = demo
        self.card_repository = CharacterCardRepository(store)
        # 受管理资产（头像、参考音频）。
        self.asset_service = CharacterAssetService(
            store, store.database.parent / "character_assets"
        )
        self.pairing_service = PairingService()
        # 配对码、令牌与撤销状态变化时当刻落库。
        self.pairing_service.state_persist_hook = self._persist_pairing_state
        self._restore_pairing_state()
        self.tunnel_manager = TunnelManager(
            data_dir=store.database.parent, emitter=emitter
        )
        # --serve 监听成功后由 attach_remote_serve 登记；None 表示远程服务未开启。
        # 隧道只暴露这里登记的端口，电源状态的 remote_serve_enabled 也由它导出。
        self.remote_serve: RemoteServe | None = None
        self.pair_config = pair_config
        self.pair_catalog = tuple(pair_catalog)
        # 装配结果缓存（card_id → (updated_at, AssembledPrompt)）。
        self._assembled_cache: dict[str, tuple[str, AssembledPrompt]] = {}
        self.approval_broker = ApprovalBroker(emitter)
        runtime = self._initial_runtime()
        self.orchestrator = ConversationOrchestrator(
            dialogue_model=runtime.dialogue_model,
            coding_engine=runtime.coding_engine,
            reviewer=runtime.reviewer,
            store=store,
            approval_callback=self.approval_broker.request,
        )
        self.current_project_id = current_project_id
        self.current_conversation_id = current_conversation_id
        self.voice_runtime: VoiceRuntime | None = None
        self._shutdown = False
        # Router 会并发处理 JSONL 命令；PTT 的开始/结束必须按顺序执行，
        # 否则快速点击会让 stop 抢在 start 完成前进入 ASR 收尾。
        self._voice_ptt_lock = asyncio.Lock()
        # 音色生成互斥：同时只允许一个 voice.provision 任务，防止双击产生
        # 重复计费请求。
        self._voice_provision_lock = asyncio.Lock()
        # 生成中的瞬时状态按账号隔离；持久化成功状态以
        # voice.profile.<speaker>.voice_id 是否存在为准。
        self._voice_provision_states: dict[str, dict[str, dict[str, Any]]] = {}
        # PTT 开始时捕获的会话与目标；ASR 提交使用这份上下文，录音期间切换
        # 会话不会让文本落入错误会话。
        self._ptt_voice_context: dict[str, str] | None = None
        # 账号切换锁：切换过程与 chat.submit、配置保存互斥，新任务和新配置
        # 不会进入半切换状态的账号或运行时。
        self._account_switch_lock = asyncio.Lock()
        # 旧运行时的异步关闭任务（连续保存或切换时不泄漏子进程）。
        self._close_runtime_tasks: set[asyncio.Task[None]] = set()
        self._tool_runs: dict[tuple[str, str], ToolRun] = {}
        self._streaming_message_ids: dict[tuple[str, str], set[str]] = {}
        self._title_tasks: set[asyncio.Task[None]] = set()
        # 摘要生成后台任务（regenerate 与自动压缩）。
        self._summary_tasks: set[asyncio.Task[None]] = set()
        # 自动压缩防重入：会话级在途标记（任务完成后清除）。
        self._auto_summary_in_flight: set[str] = set()
        # 后台回合任务（快速接受后立即返回，回合在后台推进）。
        self._turn_tasks: set[asyncio.Task[None]] = set()
        # 角色对话不占用全局 coding busy 状态；用会话级任务记录阻止同一
        # 聊天在角色仍流式输出时再次并发启动，后续提交进入既有队列。
        self._conversation_turn_tasks: dict[str, asyncio.Task[None]] = {}
        self._title_generation_started: set[str] = set()
        # 一次提交对应一个 Turn。运行态记录随 bootstrap 水合，终态保留供
        # 前端历史展示。
        self._turns: dict[str, dict[str, Any]] = {}
        self._conversation_turn_ids: dict[str, list[str]] = {}
        # 会话当前运行中的 turn_id：首个真实引擎/流式事件回调据此把
        # first_event_at 记到正确的回合上（无事件的回合保持 null）。
        self._active_turn_ids: dict[str, str] = {}
        # 回合运行期间触发的自动压缩次数（turn_id → 次数），终态写入指标。
        self._turn_compression_counts: dict[str, int] = {}
        self._voice_state: dict[str, Any] = {
            "supported": False,
            # 语音总开关：随运行时启用，账号配置 voice.enabled=false 时关闭
            "enabled": False,
            # 古代机械语音必须由用户单独开启，默认关闭
            "assistant_voice_enabled": False,
            "vad": "idle",
            "vad_enabled": False,
            "ptt": False,
            "tts": "idle",
            "asr_partial": "",
            "error": None,
            # 待播队列条数（VoiceMiniPlayer 的 queuedCount 数据源）
            "speech_queue_len": 0,
        }
        # error 字段的来源（tts / voice）。状态恢复时只清除已不再成立的
        # 那一类错误，仍然成立的识别错误保持原样。
        self._voice_error_scope: str | None = None
        self._handlers = self._command_handlers()

        self.orchestrator.on_message = self._on_message
        self.orchestrator.on_message_status_changed = self._on_message_status_changed
        self.orchestrator.on_dialogue_event = self._on_dialogue_event
        self.orchestrator.on_review_event = self._on_review_event
        self.orchestrator.on_engine_event = self._on_engine_event
        self.orchestrator.on_execution_started = self._on_execution_started
        self.orchestrator.on_execution_finished = self._on_execution_finished
        # --serve 模式下由 __main__ 注入事件扇出；手机语音事件走 remote-only
        # 通道（只发远程连接，不写 stdout）。非 serve 模式保持 None。
        self._event_fanout: Any = None
        # 卡音色创建的每卡互斥锁（voice_card_provision_in_progress）。
        self._card_provision_locks: dict[str, asyncio.Lock] = {}
        # 手机上行转写会话。
        self._mobile_asr = MobileAsrSessionManager(
            on_transcript=self._on_mobile_transcript
        )
        # 每个转写会话的超时任务；手机端迟迟不发 stop 时取消会话并通知手机端。
        self._mobile_asr_watchdogs: dict[str, asyncio.Task[None]] = {}
        self._mobile_asr_timeout_s = 120.0
        # 手机下行 TTS 分片编目与在途下发任务。
        self._mobile_tts = MobileTtsSequencer()
        self._mobile_tts_tasks: dict[str, asyncio.Task[None]] = {}
        # 远程控制租约按 device_key 独立记录（TTL 45s，断连宽限 15s）；断连
        # 不立即释放，宽限结束后过期回收。
        self._control_leases: dict[str, _ControlLease] = {}
        self._control_sweeper: asyncio.Task[None] | None = None
        # 电源监视任务：在事件循环内轮询，由 shutdown 取消。
        self._power_monitor_task: asyncio.Task[None] | None = None
        self._recover_interrupted_work()
        if current_conversation_id:
            self._restore_conversation_state(current_conversation_id)
            if not demo:
                self._attach_account_voice_runtime()

    @property
    def dialogue_model(self) -> DialogueModel:
        return self.orchestrator.dialogue_model

    @property
    def coding_engine(self) -> CodingEngine:
        return self.orchestrator.coding_engine

    def _initial_runtime(self) -> Runtime:
        """启动运行时：demo 模式用离线脚本模型，真实模式按当前账号配置装配。"""
        if self._demo:
            return Runtime(
                dialogue_model=ScriptedDialogueModel(),
                coding_engine=ScriptedCodingEngine(),
                reviewer=None,
            )
        return self._build_runtime_candidate(self._load_account_config())

    # ------------------------------------------------------------------ 生命周期

    async def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        await self.stop_power_monitor()
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
        # 等待已排队的旧运行时关闭任务结束，进程退出前不泄漏子进程。
        if self._close_runtime_tasks:
            await asyncio.gather(*tuple(self._close_runtime_tasks), return_exceptions=True)
        if self.voice_runtime is not None:
            await self.voice_runtime.shutdown()
        await self.dialogue_model.aclose()
        await self.coding_engine.aclose()
        # Sidecar 退出时关闭隧道子进程，不留孤儿。
        await self.tunnel_manager.stop(reason="sidecar_exit")
        # 退出前持久化远程配对状态。
        self._persist_pairing_state()
        self.store.close()

    # ------------------------------------------------------------------ 账号

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

    def _voice_customization_error(self, exc: Exception, api_key: str) -> str:
        """音色定制失败的可见原因，Key 脱敏；客户端错误文本已带 HTTP 状态码。"""
        return self._redact_voice_error(str(exc) or type(exc).__name__, api_key)

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

        # current_* 只经账号校验后的入口写入（启动、选择聊天、切换账号、
        # 归档），这里只读。
        current_project = (
            self.store.get_project(self.current_project_id)
            if self.current_project_id
            else None
        )
        conversation = None
        messages: tuple[Message, ...] = ()
        tool_runs: tuple[ToolRun, ...] = ()
        if self.current_conversation_id:
            snapshot = self.store.load_conversation(self.current_conversation_id)
            conversation = snapshot.conversation
            messages = snapshot.messages
            tool_runs = snapshot.tool_runs
        # 快照携带全部活动任务集合；active_task 与 busy 只跟当前聊天。
        active_tasks = self.orchestrator.state.active_tasks()
        active = self.orchestrator.state.get_for_conversation(
            self.current_conversation_id
        )
        return {
            "projects": projects,
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
            "messages": list(to_jsonable(messages)),
            "tool_runs": list(to_jsonable(tool_runs)),
            "turns": self._conversation_turns_payload(self.current_conversation_id),
            "queue_items": self.store.list_queue_items(self.current_conversation_id)
            if self.current_conversation_id
            else [],
            "active_task": to_jsonable(active),
            "busy": active is not None,
            "active_tasks": to_jsonable(active_tasks),
            "approvals": self.approval_broker.snapshot(),
            "remote_control": self._control_lease_payload(),
            # 远程接入地址随快照下发，漏收 serve.started 事件也能恢复。
            "remote_serve": self.remote_serve.payload() if self.remote_serve else None,
            "voice": self._voice_snapshot(),
            "pair": self._pair_payload(self.pair_config),
            "pairs": [self._pair_payload(pair) for pair in self.pair_catalog],
            # 快照记录最近一条已经发出的事件；next_sequence 指向下一条待发事件。
            # 前端以该值作为 lastSequence，下一条事件必须从它递增一位。
            "sequence": self.emitter.next_sequence - 1,
            "stream_id": self.emitter.stream_id,
        }

    def has_active_remote_controller(self) -> bool:
        """是否存在未过期的远程控制租约。

        读取前先做一次惰性回收，过期租约不会继续阻断桌面播放。
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
        self._control_sweeper = asyncio.create_task(
            self._control_sweep_loop(), name="remote-control-sweeper"
        )

    async def _control_sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(CONTROL_LEASE_SWEEP_INTERVAL_S)
            self._sweep_control_leases()
            if not self._control_leases:
                # 无租约时退出；下次认领会重新创建回收任务。
                return

    def _control_lease_payload(self) -> dict[str, Any]:
        """remote_control 快照/状态：state/device_key/expires_at/
        grace_expires_at/reason，无值一律 null。"""
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
        """广播 remote.control_changed。"""
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
        if not enabled:
            return
        try:
            # 麦克风采集与 VAD 分开：VAD 默认关闭时仍需启动采集，PTT 才能把
            # 音频帧送进 ASR。
            await self.voice_runtime.start_listening(vad_enabled=vad_enabled)
            self.voice_runtime.start_playback()
        except Exception as exc:  # noqa: BLE001 - 语音不可用不阻塞文本主线
            self._on_voice_error(f"语音启动失败：{exc}")

    def _attach_account_voice_runtime(self) -> bool:
        """按当前账号语音配置创建并挂载 VoiceRuntime，返回是否成功。

        有 Key（账号级或开发机 .env）即创建运行时，ASR 不依赖音色；TTS
        有效音色按账号生成结果 → 开发机作者音色 → 不可用 的优先级解析。
        没有 Key 或构建失败时把原因写进语音错误状态。
        """
        config = self._load_account_config()
        settings = Settings.overlay(Settings.from_environment(), config)
        if not settings.dashscope_api_key:
            self._on_voice_error(
                "真实语音未启用：未保存 DashScope API Key（语音页可保存账号 Key）"
            )
            return False
        try:
            runtime = build_real_voice_runtime(
                settings=settings,
                pair_config=self.pair_config,
                conversation_id=self.current_conversation_id,
                on_vad_state=self._on_voice_state,
                on_asr_partial=self._on_asr_partial,
                on_error=self._on_voice_error,
                on_tts_state=self._on_tts_state,
                on_interrupted=self._on_voice_interrupted,
                on_text_input=self._submit_voice_input,
                voices=resolve_effective_voice_profile(
                    account_config=config,
                    settings=settings,
                    pair_config=self.pair_config,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 音频设备与依赖失败只关闭语音，文本功能照常
            logger.exception("语音运行时构建失败")
            self._on_voice_error(f"语音运行时未启用：{exc}")
            return False
        self.attach_voice_runtime(runtime)
        return True

    async def _rebuild_voice_runtime_locked(self) -> None:
        """按当前账号语音配置重建 VoiceRuntime。

        调用方必须已持有账号切换锁（config.set / _switch_account / 音色生成）。
        替换失败或没有 Key 时运行时保持为空并保留错误信息。
        """
        old_runtime = self.voice_runtime
        if old_runtime is not None:
            self.orchestrator.remove_message_listener(self._on_message_for_voice)
            self.voice_runtime = None
            try:
                await old_runtime.shutdown()
            except Exception as exc:  # noqa: BLE001 - 关闭失败写入语音错误状态
                logger.exception("旧语音运行时关闭失败")
                self._on_voice_error(f"旧语音运行时关闭失败：{exc}")
        if (
            not self._demo
            and self.current_conversation_id
            and self._attach_account_voice_runtime()
        ):
            await self.start_voice()
            return
        self._voice_state["supported"] = False
        self._voice_state["enabled"] = False
        self._emit_voice_changed()

    async def _voice_provision(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """按固定 manifest 在当前账号生成 6 个专属音色。

        命令不接受模型或 Key；``speaker_ids`` 只选择 manifest 中的固定项，
        ``replace_existing`` 只由显式的单项重新生成使用。默认调用只处理
        缺失/失败项，成功项不会重复计费。
        账号切换锁只包住读凭据与最后的运行时重建两段，DashScope 网络调用
        期间只持有音色生成锁，聊天提交不被阻塞。生成结果按开始时捕获的
        ``account_id`` 落库；重建前比对当前账号，账号已切走时不重建。
        """
        if self._voice_provision_lock.locked():
            raise ServiceError(
                "该账号正在生成专属音色，请等待完成后再试",
                code="voice_provision_in_progress",
            )

        async with self._voice_provision_lock:
            async with self._account_switch_lock:
                account_id = self.current_account_id
                config = self._load_account_config(account_id)
            # 生成命令只使用当前账号已保存的凭据；.env 里的开发机 Key 不参与
            # 一键生成。
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

            client = QwenVoiceCustomizationClient(
                api_key=api_key, http_base_url=base_url
            )
            total = len(manifest)
            completed = sum(
                1 for entry in manifest if config.get(entry.profile_key)
            )
            raw_speaker_ids = params.get("speaker_ids")
            if raw_speaker_ids is None:
                # 一键生成默认只含角色侧说话方；显式指定助手侧仍会被拒绝。
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
            # 助手不使用 TTS，助手侧说话方一律拒绝生成专属音色。
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
                        # qwen-audio-3.0-tts-flash 接受 input.url=data:audio/*;base64,...，
                        # 直接上传安装包内的参考音频，不依赖 DashScope 拉取外链。
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
                except Exception as exc:  # noqa: BLE001 - 单项失败记为 failed 并继续后续项
                    logger.warning(
                        "生成专属音色失败（speaker=%s）", entry.speaker_id, exc_info=True
                    )
                    failed += 1
                    detail = self._voice_customization_error(exc, api_key)
                    emit_progress(
                        entry.speaker_id, "failed", detail, saved or None
                    )
                    results.append(
                        {
                            "speaker_id": entry.speaker_id,
                            "state": "failed",
                            # 重新生成失败时保留旧 ID，可用音色不会被一次
                            # 失败请求清空。
                            "voice_id": saved or None,
                            "error": detail,
                        }
                    )
                    continue

                # 成功一项立即写入发起生成的账号；不合成、不猜测 voice_id。
                self.store.set_config(account_id, entry.profile_key, result.voice_id)
                config[entry.profile_key] = result.voice_id
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

            # 部分成功结果已经写入 SQLite，不因其他项失败而丢失。账号仍是
            # 发起生成的账号时按最新音色重建语音运行时；已切走则由切换流程
            # 按目标账号配置重建，这里不动。
            async with self._account_switch_lock:
                if self.current_account_id == account_id:
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
            self._voice_state["speech_queue_len"] = self.voice_runtime.speech_queue_len
        return dict(self._voice_state)

    def _emit_voice_changed(self) -> None:
        """广播 voice 快照（事件与命令响应共用）。"""
        self.emitter.emit("voice.state_changed", {"voice": self._voice_snapshot()})

    def _on_voice_state(self, state: str) -> None:
        # vad 通道保持既有语义（playing=播放期间暂停监听）
        self._voice_state["vad"] = state
        self._emit_voice_changed()

    def _on_tts_state(self, state: str) -> None:
        # tts 状态机独立于 vad：idle/synthesizing/playing/skipping/failed
        self._voice_state["tts"] = state
        if state in ("playing", "idle"):
            # 合成与播放恢复后清除旧的合成错误，界面不再展示与当前状态
            # 矛盾的旧报文。
            self._clear_voice_error(scope="tts")
        self._emit_voice_changed()

    def _on_voice_interrupted(
        self, conversation_id: str, message_id: str | None, reason: str
    ) -> None:
        """桌面朗读被抢占时广播 voice.playback_interrupted。"""
        self.emitter.emit(
            "voice.playback_interrupted",
            {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "reason": reason,
            },
        )

    async def _interrupt_desktop_speech(self, reason: str) -> None:
        """抢占桌面本地朗读；没有语音运行时则无事可做。"""
        if self.voice_runtime is not None:
            await self.voice_runtime.interrupt_async(reason)

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
        """清除已不再成立的语音错误。

        ``scope`` 限定来源：合成恢复只清除合成错误，识别错误保持原样。
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
        handler = self._handlers[command.method]
        return await handler(command.params, command.context)

    def _command_handlers(self) -> dict[str, CommandHandler]:
        return {
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
            "card.list": self._card_list,
            "card.get": self._card_get,
            "card.create_draft": self._card_create_draft,
            "card.update": self._card_update,
            "card.duplicate": self._card_duplicate,
            "card.archive": self._card_archive,
            "card.unarchive": self._card_unarchive,
            "card.delete": self._card_delete,
            "card.select_active": self._card_select_active,
            "card.peek_import": self._card_peek_import,
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
            "metrics.query": self._metrics_query,
            "diagnostics.prompt_assembly": self._diagnostics_prompt_assembly,
            "summary.regenerate": self._summary_regenerate,
            "summary.get": self._summary_get,
            "memory.create": self._memory_create,
            "memory.list": self._memory_list,
            "memory.update": self._memory_update,
            "memory.delete": self._memory_delete,
        }

    async def _app_bootstrap(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        return self.bootstrap()

    async def _app_shutdown(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        await self.shutdown()
        return {"stopped": True}

    async def _project_create(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        pair_id = self._requested_pair_id(params)
        root_value = params.get("root_path")
        if not isinstance(root_value, str) or not root_value:
            raise ServiceError("project.create 需要 root_path", code="invalid_params")
        root_path = Path(root_value).expanduser().resolve()
        # 先查所有项目（含已归档），同一目录不创建第二条记录；属于其他账号的
        # 目录在任何写入之前拒绝。
        project = self.store.find_project_by_root_path(str(root_path))
        if project is not None and project.account_id != self.current_account_id:
            raise ServiceError(
                "该项目目录已属于其他账号，不能静默创建重复记录",
                code="project_account_conflict",
            )
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
        conversation = self._find_or_create_conversation(
            project.project_id,
            pair_id=pair_id,
            character_card_id=_params_card_id(params),
        )
        await self._enter_conversation_context(conversation.conversation_id)
        return self.bootstrap()

    async def _enter_conversation_context(self, conversation_id: str) -> None:
        """命令入口切换到聊天并广播；从无聊天上下文进入时补建语音运行时。

        语音运行时绑定当前聊天，没有聊天时不会创建。先保存语音 Key、后创建
        项目，或切到没有聊天的账号后再选项目时，进入第一个聊天才重建。
        """
        entering = not self.current_conversation_id
        await self._select_conversation_context(conversation_id, emit=True)
        if entering and self.voice_runtime is None and not self._demo:
            async with self._account_switch_lock:
                if self.voice_runtime is None:
                    await self._rebuild_voice_runtime_locked()

    async def _project_select(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        project_id = self._required_string(params, "project_id")
        project = self._current_account_project(project_id)
        conversation_id = params.get("conversation_id")
        if isinstance(conversation_id, str):
            conversation = self.store.get_conversation(conversation_id)
            if conversation.project_id != project.project_id:
                raise ServiceError("聊天不属于指定项目", code="conversation_project_mismatch")
        else:
            conversation = self._find_or_create_conversation(
                project.project_id, pair_id=self.pair_config.pair_id
            )
        await self._enter_conversation_context(conversation.conversation_id)
        return self.bootstrap()

    async def _project_update_settings(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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
            self.orchestrator.set_project_approval_mode(project_id, mode)
        if "reasoning_effort" in params:
            effort = str(params["reasoning_effort"])
            if effort not in {"low", "medium", "high", "xhigh", "max"}:
                raise ServiceError("未知推理档位", code="invalid_reasoning_effort")
            # 项目级档位只落库；编程助手的推理档位取账号级
            # dialogue.reasoning_effort，在运行时构建时写入。
            self.store.update_project_reasoning_effort(project_id, effort)
        if root_changed:
            # 该项目聊天的旧 session 绑定旧目录，下一次任务在新目录新开
            # session；其他项目的可恢复会话保持不变。
            self.orchestrator.forget_sessions(
                self.store.clear_project_engine_sessions(project_id)
            )
        updated = self._project_payload(self.store.get_project(project_id))
        self.emitter.emit("project.changed", {"project": updated})
        # 设置类命令返回定向响应，不回推整份快照。
        return {"project": updated}

    async def _project_archive(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        project_id = str(params.get("project_id") or self.current_project_id)
        if not project_id:
            raise ServiceError("没有可归档的项目", code="project_not_found")
        # 多个聊天可并发运行，按项目枚举全部活动任务。
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
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """WS 心跳：响应携带服务端时间作活性信号。

        客户端约 30s 收不到任何入站消息即判定半开连接，主动断开走既有重连。
        已鉴权持有者的 ping 刷新控制租约（TTL 45s），续租本身不发事件；
        非持有者的 ping 不续租、不夺权。
        """
        if ctx.device_key is not None:
            lease = self._control_leases.get(ctx.device_key)
            if lease is not None:
                lease.renew(time.monotonic())
                lease.reason = "renewed"
        return {"server_time": datetime.now(timezone.utc).isoformat()}

    async def _conversation_create(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        pair_id = self._requested_pair_id(params)
        project_id = str(params.get("project_id") or self.current_project_id)
        project = self._current_account_project(project_id)
        # 显式 character_card_id 优先；缺省时快照当时有效的 active 卡。
        card_id = _params_card_id(params) or self._effective_active_card_id()
        # reuse_active=true 时同项目、同角色卡、同搭档已有活跃会话则直接复用：
        # 不新建、不重复插入开场白、不改标题。无角色卡的普通会话不参与复用；
        # 搭档是会话身份的一部分，不跨搭档复用。
        if bool(params.get("reuse_active", False)) and card_id is not None:
            existing = self.store.find_active_conversation(
                project.project_id,
                character_card_id=card_id,
                pair_id=pair_id,
                account_id=self.current_account_id,
            )
            if existing is not None:
                await self._enter_conversation_context(existing.conversation_id)
                result = self.bootstrap()
                result["reused"] = True
                return result
        title = _optional_text(params, "title")
        conversation = self._create_conversation(
            project.project_id,
            pair_id=pair_id,
            character_card_id=card_id,
            title=title,
        )
        await self._enter_conversation_context(conversation.conversation_id)
        result = self.bootstrap()
        result["reused"] = False
        return result

    async def _conversation_select(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        conversation_id = self._required_string(params, "conversation_id")
        self._current_account_conversation(conversation_id)
        await self._enter_conversation_context(conversation_id)
        return self.bootstrap()

    async def _conversation_open(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """多窗口只读装载：返回目标聊天快照，不改变全局导航。

        ``view_id`` 由前端携带用于路由，Sidecar 不保存窗口导航状态。返回
        conversation/project/pair/messages/tool_runs/turns/queue_items/
        active task，不修改其他窗口正在查看的聊天，也不清理审批或引擎会话。
        """
        conversation_id = self._required_string(params, "conversation_id")
        conversation = self._current_account_conversation(conversation_id)
        project = self.store.get_project(conversation.project_id)
        # 绑定卡已被删除时提示回退内置角色。
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
        # 只读装载：恢复内存历史与工具缓存（幂等），不改写 current_*。
        # 返回体所有会话运行态都在 await 前物化；随后事件由调用端按游标重放。
        snapshot = self._restore_conversation_state(conversation_id)
        active = self.orchestrator.state.get_for_conversation(conversation_id)
        result = {
            "conversation": self._conversation_payload(conversation),
            "project": self._project_payload(project),
            "pair": self._pair_payload(load_pair_config(conversation.pair_id)),
            "messages": list(to_jsonable(snapshot.messages)),
            "tool_runs": list(to_jsonable(snapshot.tool_runs)),
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

    async def _conversation_rename(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        conversation_id = str(params.get("conversation_id") or self.current_conversation_id)
        title = self._required_string(params, "title")
        self._current_account_conversation(conversation_id)
        self.store.rename_conversation(conversation_id, title)
        self.emitter.emit(
            "conversation.changed",
            {"conversation": self._conversation_payload(self.store.get_conversation(conversation_id))},
        )
        return self.bootstrap()

    async def _conversation_archive(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        conversation_id = str(params.get("conversation_id") or self.current_conversation_id)
        conversation = self._current_account_conversation(conversation_id)
        # 补建判断用被归档会话自身的项目：归档非当前项目的最后一个聊天，
        # 新聊天补建在它自己的项目里。
        project_id = conversation.project_id
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
            self.emitter.emit(
                "conversation.changed",
                {
                    "conversation": self._conversation_payload(
                        self.store.get_conversation(conversation_id)
                    )
                },
            )
        return self.bootstrap()

    async def _chat_submit(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """同步落库用户消息并立即返回真实 id，回合在后台推进。

        前端按真实 ``message_id`` 即时回显并推进状态；处理失败后文字仍在
        可重试。``ctx`` 里的来源身份落进 Turn payload 与队列项，终态指标
        据此记录来源。
        """
        conversation_id = str(params.get("conversation_id") or self.current_conversation_id)
        if not conversation_id:
            raise ServiceError("请先创建或选择项目", code="no_active_conversation")
        self._current_account_conversation(conversation_id)
        target = str(params.get("target", "character"))
        text = self._required_string(params, "text")
        if target not in {"character", "assistant"}:
            raise ServiceError("target 必须是 character 或 assistant", code="invalid_target")
        # 用户发送立即停声：epoch 递增、清队列、停播放器，旧 epoch 的迟到
        # PCM 永不写入（排队提交同样先停声）。
        await self._interrupt_desktop_speech("user_send")
        # 提交与账号切换、配置保存互斥；这把锁同时让同一聊天的“检查忙碌、
        # 落库用户消息、登记 Turn 与后台任务”成为原子步骤，第二条提交只会入队。
        async with self._account_switch_lock:
            # mode 缺省时不改写会话 last_mode；显式携带 mode 的提交按请求持久化，
            # 单独切换走 conversation.set_mode。
            mode = params.get("mode")
            if mode is not None:
                if mode not in {"chat", "collaboration"}:
                    raise ServiceError("mode 必须是 chat 或 collaboration", code="invalid_mode")
                self._set_conversation_mode(conversation_id, str(mode))
            # 按会话持久化模式校验 assistant 目标：chat 模式不能创建助手任务。
            if target == "assistant":
                persisted_mode = self.store.get_conversation(conversation_id).last_mode
                if persisted_mode == "chat":
                    raise ServiceError(
                        "聊天模式不能直接交给助手，请先切换到协作模式",
                        code="assistant_not_allowed_in_chat_mode",
                    )
            # 只解析不可变执行上下文，后台聊天的提交不改写全局当前项目、搭档
            # 与审批模式。
            exec_context = self._resolve_execution_context(conversation_id)

            # 本聊天忙碌时提交先入队（followup 追加 / steer 置队首），先持久化
            # 再向前端确认，并记下提交来源；派发由回合完成后的自动派发链处理。
            # 忙碌判定只看本聊天，其他聊天运行不影响提交。
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
                    origin=ctx.origin,
                    remote_device_key=ctx.device_key,
                    remote_device_name=ctx.device_name,
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
            # 同步创建 accepted 态 Turn，随提交返回 turn_id；生命周期事件由
            # 后台任务按 started → completed/failed/cancelled 推进。
            turn = self._register_turn(
                conversation_id,
                user_message,
                target,
                origin=ctx.origin,
                device_key=ctx.device_key,
                device_name=ctx.device_name,
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
            self._track_turn_task(conversation_id, task, turn["turn_id"])
            return {
                "message_id": user_message.message_id,
                "conversation_id": conversation_id,
                "status": "received",
                "target": target,
                "turn_id": turn["turn_id"],
            }

    async def _submit_voice_input(self, text: str, target: str) -> None:
        """把已完成 ASR 的文本送入同一条后台 Turn 链。

        PTT 开始时捕获的会话与目标优先；用户录音期间切换会话，松键提交
        仍进入开始录音时的会话。
        """
        context = self._ptt_voice_context or {}
        conversation_id = context.get("conversation_id") or self.current_conversation_id
        actual_target = context.get("target") or target
        # 后台提交可能晚于 voice.ptt_stop 返回；这里消费并清除上下文，避免
        # 下一次 PTT 或后续提交误用旧会话。
        self._ptt_voice_context = None
        await self._chat_submit(
            {
                "conversation_id": conversation_id,
                "target": actual_target,
                "text": text,
            },
            CommandContext(),
        )

    def _track_turn_task(
        self,
        conversation_id: str,
        task: asyncio.Task[None],
        turn_id: str | None = None,
    ) -> None:
        """登记后台回合，并在结束时清除对应会话的忙碌标记。

        同一会话已有未完成任务时禁止覆盖旧引用。回合失败在
        ``_run_submit_turn`` 内落为 failed，队列派发前的失败在
        ``_dispatch_from_inbox`` 内落为 failed 队列项；done callback 只把
        漏出的异常写进日志。
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
            logger.error(
                "后台回合任务异常（conversation=%s turn=%s）：%s",
                conversation_id,
                turn_id,
                exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )

        task.add_done_callback(_on_done)

    def _register_turn(
        self,
        conversation_id: str,
        user_message: Any,
        target: str,
        *,
        origin: str,
        device_key: str | None,
        device_name: str | None,
    ) -> dict[str, Any]:
        """创建并登记 Turn（accepted 态），返回 payload。

        来源身份随 Turn payload 落到运行态记录，终态指标从同一份记录取值。
        回合只发生在项目聊天里（日常聊天在提交与派发入口即被拒绝），
        project_id 取会话的真实项目。
        """
        turn = Turn(
            project_id=self.store.get_conversation(conversation_id).project_id,
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
        user_message: Message,
        target: str,
        turn_id: str,
        exec_context: ExecutionContext,
    ) -> None:
        """回合 + 队列自动派发链。

        ``exec_context`` 是提交时解析的不可变上下文。回合到达 completed 或
        failed 后放行队列，failed 照常呈现真实终态与原因；取消向上抛出。
        """
        await self._run_submit_turn(
            conversation_id, user_message, target, turn_id, exec_context
        )
        await self._dispatch_from_inbox(conversation_id)

    async def _dispatch_from_inbox(self, conversation_id: str) -> None:
        """持久化队列自动派发：processing → 回合 → 终态删除。

        回合开始后到达任一终态（completed/failed/cancelled）即删除该项并
        派发下一条，真实终态与原因已在消息流与回合记录中呈现。回合开始前
        的失败（解析执行上下文、落库用户消息）把该项标为 failed 并保留
        原因，广播 queue.changed 并写一条系统消息，该项不再自动派发。
        回合开始前被取消时该项退回 queued。派发出的回合沿用入队时的来源。
        """
        while True:
            item = self.store.peek_queue_item(conversation_id)
            if item is None:
                return
            queue_item_id = item["queue_item_id"]
            self.store.set_queue_item_status(queue_item_id, "processing")
            self._emit_queue_changed(conversation_id)
            try:
                exec_context = self._resolve_execution_context(conversation_id)
                user_message = await self.orchestrator.submit_user_message(
                    conversation_id=conversation_id,
                    text=item["text"],
                    target=item["target"],
                    pair_id=exec_context.pair_id,
                )
            except asyncio.CancelledError:
                self.store.set_queue_item_status(queue_item_id, "queued")
                self._emit_queue_changed(conversation_id)
                raise
            except Exception as exc:  # noqa: BLE001 - 派发失败落为可见的 failed 队列项
                reason = _failure_reason(exc)
                logger.exception(
                    "队列项派发失败（conversation=%s queue_item=%s）",
                    conversation_id,
                    queue_item_id,
                )
                self.store.mark_queue_item_failed(queue_item_id, reason)
                self._emit_queue_changed(conversation_id)
                self.orchestrator.report_system_status(
                    conversation_id, f"排队消息未能发送：{reason}"
                )
                continue
            turn = self._register_turn(
                conversation_id,
                user_message,
                item["target"],
                origin=item["origin"],
                device_key=item["remote_device_key"],
                device_name=item["remote_device_name"],
            )
            try:
                await self._run_submit_turn(
                    conversation_id,
                    user_message,
                    item["target"],
                    turn["turn_id"],
                    exec_context,
                )
            finally:
                # 回合已开始，终态（含取消）已在回合记录与消息流中呈现。
                self.store.delete_queue_item(queue_item_id)
                self._emit_queue_changed(conversation_id)

    def _emit_queue_changed(self, conversation_id: str) -> None:
        """队列变化推送全量快照（按 position 有序）。"""
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
        user_message: Message,
        target: str,
        turn_id: str,
        exec_context: ExecutionContext,
    ) -> None:
        """Turn 生命周期：started(running) → completed/failed/cancelled。

        失败仍把用户消息标记 failed（文字保留可重试），与消息状态对账；
        回合完成后调度自动标题（直接提交与队列派发共用）；取消向上抛出。
        """
        self._emit_turn_status(turn_id, "running")
        # 登记本会话当前运行的回合，供首个真实引擎/流式事件回调与自动压缩
        # 计数记到正确回合上。
        self._active_turn_ids[conversation_id] = turn_id
        terminal_status = "completed"
        failure_reason: str | None = None
        outcome: ConversationOutcome | None = None
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
                # 角色本轮声明的长期记忆由服务侧按会话作用域落库。
                self._persist_memory_drafts(
                    conversation_id, tuple(outcome.memory_drafts)
                )
            if outcome.receipt is not None:
                terminal_status = outcome.receipt.status
                if terminal_status == "failed":
                    # 引擎上报失败时回合不抛异常，真实原因在回执的 errors 里。
                    failure_reason = "\n".join(outcome.receipt.errors) or None
        except asyncio.CancelledError:
            terminal_status = "cancelled"
            # Sidecar 关闭（stdout 断开、进程退出）触发的任务取消属于传输关闭
            # 路径，已经持久化的业务消息保持原状态。
            if not self._shutdown:
                self.orchestrator.mark_message_cancelled(
                    conversation_id, user_message.message_id
                )
                self.orchestrator.mark_processing_delegations_cancelled(conversation_id)
            raise
        except Exception as exc:  # noqa: BLE001 - 回合失败转为可见消息状态
            logger.exception("后台回合失败：%s", conversation_id)
            terminal_status = "failed"
            # 可见提示、消息失败原因与日志携带同一份真实原因。
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
            # turn 终态落一次指标；计数取事件流真实值，缺失字段为 null
            # （真实零值用 0，不估算 token）。
            self._active_turn_ids.pop(conversation_id, None)
            self._record_turn_metric(
                conversation_id,
                turn_id,
                target,
                terminal_status,
                outcome=outcome,
                failure_reason=failure_reason,
            )
        if terminal_status == "completed":
            # 完整回复已经落库后再生成标题，保证命名上下文至少包含一问一答。
            # 失败回合不命名，后续成功回合仍可再次尝试。
            self._schedule_title_generation(conversation_id, target)

    def _record_turn_metric(
        self,
        conversation_id: str,
        turn_id: str,
        target: str,
        status: str,
        *,
        outcome: ConversationOutcome | None,
        failure_reason: str | None,
    ) -> None:
        """把回合终态写为 TurnMetric（幂等：同 turn 重复终态以首次写入为准）。

        未观测或供应商不提供的字段为 null 且键仍存在，真实零值用 0；token
        只接受服务端真实 usage，不估算。``failure_reason`` 是回合链得到的
        真实失败原因：回合抛出的异常，或引擎失败回执里的 errors；回执没有
        错误明细时为 None。

        供应商与模型取实际生效的对话配置，engine_type 取当前编程助手引擎，
        reasoning_effort 只记账号保存的值（未配置为 null）。approval_count
        统计本回合事件流里的审批请求，compression_count 统计本回合期间触发
        的自动压缩。
        """
        turn = self._turns[turn_id]
        conversation = self.store.get_conversation(conversation_id)
        provider, model = self._effective_dialogue_identity()
        reasoning_effort = self._load_account_config().get("dialogue.reasoning_effort")
        compression_count = self._turn_compression_counts.pop(turn_id, 0)

        input_tokens: int | None = None
        output_tokens: int | None = None
        total_tokens: int | None = None
        tool_rounds = 0
        approval_count = 0
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
                elif event.type == EngineEventType.APPROVAL_REQUESTED:
                    approval_count += 1
            active_turn = self.orchestrator.state.get_for_conversation(conversation_id)
            if active_turn is not None:
                task_id = active_turn.task_id
                engine_turn_id = active_turn.engine_turn_id
            elif outcome.task is not None:
                task_id = outcome.task.task_id
            # 引擎事件里的 engine_turn_id 逐事件一致，取最后一条。
            if outcome.engine_events and outcome.engine_events[-1].engine_turn_id:
                engine_turn_id = outcome.engine_events[-1].engine_turn_id

        started_at = turn["created_at"]
        completed_at = utc_now().isoformat()
        duration_ms = _duration_ms(started_at, completed_at)
        # first_event_at 只取回合链记录的首个真实引擎/流式事件时间；没有事件
        # 的回合（例如立即抛错的失败回合）保持 null。
        first_event_raw: str | None = turn.get("first_event_at")
        first_event_at = (
            datetime.fromisoformat(first_event_raw) if first_event_raw else None
        )
        first_event_latency_ms = (
            _duration_ms(started_at, first_event_raw) if first_event_raw else None
        )
        failure_type = None
        failure_message = None
        if status == "failed":
            failure_type = "turn_failed"
            failure_message = failure_reason

        metric = TurnMetric(
            account_id=self.current_account_id,
            project_id=turn["project_id"],
            conversation_id=conversation_id,
            pair_id=conversation.pair_id,
            character_ref=None,
            assistant_identity=None,
            turn_kind="assistant_task" if target == "assistant" else "character_turn",
            turn_id=turn_id,
            task_id=task_id,
            engine_turn_id=engine_turn_id,
            source_message_id=turn["source_message_id"],
            provider=provider,
            model=model,
            engine_type=self.coding_engine.engine_type,
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
            compression_count=compression_count,
            approval_count=approval_count,
            failure_type=failure_type,
            failure_message=failure_message,
            # 来源身份取 Turn payload 的运行态记录（提交或入队时由传输层注入）。
            origin=turn["origin"],
            remote_device_key=turn["remote_device_key"],
            remote_device_name=turn["remote_device_name"],
        )
        self.store.upsert_turn_metric(metric)

    def _set_conversation_mode(self, conversation_id: str, mode: str) -> None:
        """模式是按会话持久化的独立字段，与推理档位、审批方式、发送对象互不
        覆盖；回合在提交时从执行上下文读取它。"""
        self.store.update_conversation_mode(conversation_id, mode)

    async def _conversation_set_mode(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """只改会话模式，返回定向响应，不回推整份快照。"""
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

    async def _task_cancel(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """定向取消：按聊天与任务 id 校验，旧界面的取消按钮不会取消新聊天的任务。"""
        conversation_id = self._required_string(params, "conversation_id")
        task_id = _optional_text(params, "task_id")
        active = self.orchestrator.state.get_for_conversation(conversation_id)
        if active is not None and (task_id is None or active.task_id == task_id):
            # 先结清该任务的未决审批，让等待中的 future 以 DENY 完成并回复
            # 引擎；随后编排器发送 interrupt/cancel。
            self.approval_broker.cancel_for_conversation(conversation_id)
        return {
            "cancelled": await self.orchestrator.cancel_active_task(
                conversation_id, task_id
            )
        }

    async def _approval_resolve(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        approval_id = self._required_string(params, "approval_id")
        decision = self._required_string(params, "decision")
        # 应答来源取传输层注入的 origin；响应携带 resolved_by 供双端收敛展示。
        outcome = self.approval_broker.resolve(
            approval_id, decision, resolved_by=ctx.origin
        )
        return {
            "approval_id": approval_id,
            "accepted": True,
            "resolved_by": outcome["resolved_by"],
            "decision": outcome["decision"],
        }

    async def _voice_vad_set(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        if self.voice_runtime is None:
            raise ServiceError("语音运行时未启用", code="voice_unavailable")
        enabled = bool(params.get("enabled", False))
        self._voice_state["vad_enabled"] = enabled
        if enabled:
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

    async def _voice_ptt_start(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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
            # 开始录音时捕获会话与目标，ASR 提交使用这份上下文，不读切换后的
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

    async def _voice_ptt_stop(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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

    async def _voice_tts_stop(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        if self.voice_runtime is not None:
            # 停止可能需要等待播放器线程完成当前 PortAudio 写入；把同步
            # 原生清理移出事件循环，避免按钮请求卡住 Sidecar 协议处理。
            await self.voice_runtime.stop_speaking_async()
        self._voice_state["tts"] = "idle"
        self._emit_voice_changed()
        return {"voice": self._voice_snapshot()}

    async def _queue_edit(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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

    async def _queue_withdraw(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """撤回队列项（不再自动派发，状态置 withdrawn）。"""
        queue_item_id = self._required_string(params, "queue_item_id")
        try:
            self._current_account_queue_item(queue_item_id)
            item = self.store.withdraw_queue_item(queue_item_id)
        except KeyError as exc:
            raise ServiceError("队列项不存在", code="queue_item_not_found") from exc
        self._emit_queue_changed(item["conversation_id"])
        return {"queue_item": item}

    async def _queue_prioritize(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """逐条朗读：按 message_id 从会话取消息文本，重新合成入队（可重播）。"""
        self._require_playback_control(ctx)
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
            (m for m in snapshot.messages if m.message_id == message_id),
            None,
        )
        if message is None:
            raise ServiceError("消息不存在", code="message_not_found")
        if message.source == MessageSource.ASSISTANT:
            # 助手不使用 TTS，手动重播助手消息在语音入口被拒。
            raise ServiceError(
                "助手语音已禁用，不可朗读助手消息",
                code="assistant_tts_disabled",
            )
        # 前面的 await 期间远程设备可能认领控制权，起播前再判定一次。
        self._require_playback_control(ctx)
        self.voice_runtime.replay_message(message)
        return {"voice": self._voice_snapshot()}

    async def _voice_tts_skip(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        if self.voice_runtime is None:
            raise ServiceError("语音运行时未启用", code="voice_unavailable")
        await self.voice_runtime.skip_playing_async()
        return {"voice": self._voice_snapshot()}

    async def _voice_preview(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """语音试听：按指定文本合成入队；voice_id 缺省取当前有效角色音色。

        账号 BYOK 模式允许试听当前账号已生成的全部 manifest 音色；开发机
        作者音色只允许当前搭档。显式传入未知 ID 时如实报错，不替换成角色音色。
        """
        self._require_playback_control(ctx)
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
            if not voice_id:
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

    # ------------------------------------------------------------------ 角色卡

    _BUILTIN_PREFIX = "builtin:"

    def _builtin_card(self, card_id: str) -> CharacterCard:
        """内置角色的只读卡视图：来自 pair 目录，不入库。"""
        speaker = card_id.removeprefix(self._BUILTIN_PREFIX)
        pair = next(
            (p for p in self.pair_catalog if p.character.id == speaker), None
        )
        if pair is None:
            raise ServiceError("内置角色不存在", code="card_not_found")
        return CharacterCard(
            name=pair.character.name,
            creator="HSR Partner Harness",
            tags=["builtin"],
            creator_notes=f"内置角色，提示词来源：{pair.character.prompt}",
        )

    def _compat_report_of(self, card: CharacterCard) -> dict[str, Any]:
        """已入库卡的兼容报告：按导出形状重新走一遍导入时的同一套静态扫描。"""
        result = load_card_payload(json.loads(dump_card_v3(card)))
        return self._compat_report_payload(result.report)

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
        """card.get 的 avatar 字段：有资产时随响应整体下发。"""
        hsr = card.hsr
        if hsr is None or hsr.avatar_asset is None or not hsr.avatar_asset.asset_id:
            return None
        try:
            data, mime = self.asset_service.get_asset(hsr.avatar_asset.asset_id)
        except CharacterAssetError as exc:
            # 卡 JSON 引用了头像但文件或记录损坏时如实失败，界面不会误以为
            # 角色没有头像。
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

    async def _card_list(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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
                "archived": self.card_repository.is_archived(s.card_id),
            }
            for s in self.card_repository.list_cards(
                include_archived=include_archived
            )
        ]
        # 内置角色不能归档。
        builtin = [
            {**summary, "archived": False}
            for summary in self._builtin_card_summaries()
        ]
        return {"cards": cards + builtin}

    async def _card_get(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        card_id = str(params.get("card_id") or "")
        if not card_id:
            raise ServiceError("card.get 需要 card_id", code="invalid_params")
        if card_id.startswith(self._BUILTIN_PREFIX):
            card = self._builtin_card(card_id)
            return {
                "card_id": card_id,
                "state": "saved",
                "source": "builtin",
                "created_at": "",
                "updated_at": "",
                "card": json.loads(dump_card_v3(card)),
                "read_only": True,
                "avatar": None,
                "compat_report": self._compat_report_of(card),
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
            # 头像随 get 整体下发；列表摘要只有 has_avatar。
            "avatar": self._card_avatar_payload(record.card),
            "compat_report": self._compat_report_of(record.card),
        }

    async def _card_create_draft(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        name = str(params.get("name") or "").strip()
        if not name:
            raise ServiceError("card.create_draft 需要 name", code="invalid_params")
        record = self.card_repository.create_draft(name)
        return {"card_id": record.card_id, "state": record.state}

    async def _card_update(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        card_id = str(params.get("card_id") or "")
        self._require_writable_card(card_id)
        raw_card = params.get("card")
        if not isinstance(raw_card, Mapping):
            raise ServiceError(
                "card.update 需要 card（角色卡 JSON 对象）", code="invalid_params"
            )
        try:
            parsed = load_card_payload(dict(raw_card))
        except CardImportError as exc:
            raise ServiceError(
                f"角色卡数据非法：{exc}", code="card_invalid_payload"
            ) from exc
        try:
            stored_hsr = self.card_repository.get_card(card_id).card.hsr
        except KeyError as exc:
            raise ServiceError("角色卡不存在", code="card_not_found") from exc
        # 头像引用与音色绑定只由 card.set_avatar / card.remove_avatar /
        # voice.card_* 修改；整卡保存沿用库中当前值，编辑页打开期间的旧快照
        # 不会把它们写回旧值。
        card = parsed.card
        avatar_asset = stored_hsr.avatar_asset if stored_hsr is not None else None
        voice_profile = stored_hsr.voice_profile if stored_hsr is not None else None
        if card.hsr is None and (avatar_asset is not None or voice_profile is not None):
            card.hsr = HsrExtension()
        if card.hsr is not None:
            card.hsr.avatar_asset = avatar_asset
            card.hsr.voice_profile = voice_profile
        record = self.card_repository.update_card(card_id, card)
        return {"card_id": record.card_id, "updated_at": record.updated_at}

    async def _card_duplicate(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        card_id = str(params.get("card_id") or "")
        if card_id.startswith(self._BUILTIN_PREFIX):
            # 内置卡从 pair 定义生成可编辑副本（无资产），供“先复制再导出”。
            record = self.card_repository.import_card(
                self._builtin_card(card_id), as_duplicate=True
            )
            return {"card_id": record.card_id, "name": record.card.name}
        try:
            record = self.card_repository.duplicate_card(card_id)
        except KeyError as exc:
            raise ServiceError("角色卡不存在", code="card_not_found") from exc
        # duplicate_card 只深拷贝 JSON，副本仍引用原卡资产 ID；这里复制资产
        # 文件并把副本引用改向新资产 ID，删除原卡不影响副本。
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
                source_ref=record.asset_id,
                extension=Path(record.file_path).suffix.lstrip("."),
            )
            mapping[record.asset_id] = new_id
        return mapping

    async def _card_archive(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        card_id = str(params.get("card_id") or "")
        self._require_writable_card(card_id)
        try:
            self.card_repository.archive_card(card_id)
        except KeyError as exc:
            raise ServiceError("角色卡不存在", code="card_not_found") from exc
        except ValueError as exc:
            raise ServiceError(str(exc), code="card_invalid_state") from exc
        return {"card_id": card_id, "archived": True}

    async def _card_unarchive(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        card_id = self._required_string(params, "card_id")
        self._require_writable_card(card_id)
        try:
            self.card_repository.unarchive_card(card_id)
        except KeyError as exc:
            raise ServiceError("角色卡不存在", code="card_not_found") from exc
        return {"card_id": card_id, "archived": False}

    async def _card_delete(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        card_id = str(params.get("card_id") or "")
        self._require_writable_card(card_id)
        confirm = params.get("confirm") is True
        try:
            self.card_repository.delete_card(card_id, confirm=confirm)
        except ValueError as exc:
            raise ServiceError(str(exc), code="card_confirm_required") from exc
        # 删除卡时同步清理头像与参考音频资产。
        self.asset_service.delete_assets_for_card(card_id)
        return {"card_id": card_id, "deleted": True}

    async def _card_select_active(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        card_id = str(params.get("card_id") or "")
        self._require_writable_card(card_id)
        try:
            self.card_repository.select_active(card_id)
        except ValueError as exc:
            raise ServiceError(str(exc), code="card_invalid_state") from exc
        return {"card_id": card_id}

    # ------------------------------------------------------------------ 角色卡导入导出与发布

    @staticmethod
    def _compat_report_payload(report: CompatReport) -> dict[str, Any]:
        return {
            "applied": list(report.applied),
            "preserved": list(report.preserved),
            "not_executed": [
                {"category": item.category, "text": item.text}
                for item in report.not_executed
            ],
            "normalized_from_root": list(report.normalized_from_root),
            "warnings": list(report.warnings),
            "errors": list(report.errors),
        }

    def _read_card_file(self, params: Mapping[str, Any]) -> tuple[Path, bytes]:
        """读取 params.path 指向的角色卡文件；读取失败按 card_import_failed 报出。"""
        path = Path(self._required_string(params, "path")).expanduser()
        try:
            return path, path.read_bytes()
        except OSError as exc:
            raise ServiceError(
                f"读取角色卡文件失败：{exc}", code="card_import_failed"
            ) from exc

    @staticmethod
    def _parse_json_card(data: bytes) -> ImportResult:
        """UTF-8 JSON 角色卡解析（不落库）；失败携带原始错误。"""
        try:
            return load_card_json(data.decode("utf-8"))
        except (UnicodeDecodeError, CardImportError) as exc:
            raise ServiceError(
                f"角色卡解析失败：{exc}", code="card_import_failed"
            ) from exc

    @staticmethod
    def _parse_png_card(data: bytes) -> ImportResult:
        """PNG 角色卡解析（不落库）；失败携带原始错误。"""
        try:
            return read_png_card(data)
        except (PngCardError, CardImportError) as exc:
            raise ServiceError(
                f"角色卡解析失败：{exc}", code="card_import_failed"
            ) from exc

    def _import_preview_payload(
        self,
        card: CharacterCard,
        report: CompatReport,
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
            # JSON 与 PNG 两个分支共用 preview 形状，format 区分来源。
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

    async def _card_peek_import(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """card.peek_import：预检角色卡文件，不写库。

        按文件签名分派（不信任扩展名）：PNG 签名命中走 PNG 分支，否则按
        UTF-8 文本走 JSON 分支。失败一律为 ``card_import_failed``，message
        携带原始错误文本。
        """
        _path, data = self._read_card_file(params)
        if data.startswith(PNG_SIGNATURE):
            return self._peek_import_png(data)
        result = self._parse_json_card(data)
        return {
            "preview": self._import_preview_payload(
                result.card, result.report, format="json"
            )
        }

    def _peek_import_png(self, data: bytes) -> dict[str, Any]:
        """PNG 分支：头像尺寸解析不出时为 None，并在 warnings 里注明。"""
        result = self._parse_png_card(data)
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

    async def _card_import_json(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        _path, data = self._read_card_file(params)
        result = self._parse_json_card(data)
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

    async def _card_export_json(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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
        payload = dump_card_v3(record.card, for_export=True)
        # 另存头像时先取回头像资产，读取失败与 PNG 导出一致按 card_export_failed
        # 报出，不写出半套文件。扩展名沿用资产入库时的文件扩展名。
        avatar: tuple[bytes, Path] | None = None
        hsr = record.card.hsr
        if (
            params.get("save_avatar") is True
            and hsr is not None
            and hsr.avatar_asset is not None
            and hsr.avatar_asset.asset_id
        ):
            asset_id = hsr.avatar_asset.asset_id
            try:
                data, _mime = self.asset_service.get_asset(asset_id)
                stored = next(
                    item
                    for item in self.asset_service.list_assets_for_card(card_id)
                    if item.asset_id == asset_id
                )
            except (CharacterAssetError, KeyError, StopIteration) as exc:
                raise ServiceError(
                    f"读取头像资产失败（原始错误：{exc!r}）",
                    code="card_export_failed",
                ) from exc
            avatar = (
                data,
                path.with_suffix(f".avatar{Path(stored.file_path).suffix}"),
            )
        try:
            path.write_text(payload, encoding="utf-8")
        except OSError as exc:
            raise ServiceError(
                f"写出角色卡文件失败：{exc}", code="card_export_failed"
            ) from exc
        if avatar is not None:
            data, avatar_path = avatar
            try:
                avatar_path.write_bytes(data)
            except OSError as exc:
                raise ServiceError(
                    f"另存头像失败：{exc}", code="card_export_failed"
                ) from exc
        return {
            "exported": True,
            "path": str(path),
            "avatar_saved": avatar is not None,
        }

    async def _card_import_png(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """card.import_png：PNG 字节入库并登记头像资产。

        字节 → read_png_card → import_card（as_duplicate 改名）→ store_asset
        （PNG 原始字节即头像）→ 回写 card.hsr.avatar_asset。解析或资产写入
        失败都按 card_import_failed 报出原文；导入已落库时不回滚。
        """
        path, data = self._read_card_file(params)
        result = self._parse_png_card(data)
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
                source_ref=path.name,
            )
        except CharacterAssetError as exc:
            raise ServiceError(
                f"写入角色卡头像资产失败：{exc}", code="card_import_failed"
            ) from exc
        # 经 update_card 回写卡 JSON 的 hsr.avatar_asset，updated_at 随之更新。
        card = record.card
        if card.hsr is None:
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

    async def _card_export_png(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """card.export_png：把卡头像 + ccv3 元数据导出为单文件 PNG。

        卡必须存在、可写且头像可取回。没有头像、取回头像、合成 PNG 或写文件
        失败都按 ``card_export_failed`` 报出原始错误。
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

    async def _card_publish(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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

    # ------------------------------------------------------------------ 头像资产

    @staticmethod
    def _probe_image_mime(data: bytes) -> str | None:
        """按文件签名识别头像格式（PNG / JPEG / WebP），不信任扩展名。"""
        if data.startswith(PNG_SIGNATURE):
            return "image/png"
        if data.startswith(_JPEG_SIGNATURE):
            return "image/jpeg"
        # WebP 容器：RIFF<4 字节长度>WEBP。
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        return None

    def _delete_avatar_assets(self, card_id: str) -> None:
        for record in self.asset_service.list_assets_for_card(card_id):
            if record.kind == "avatar":
                self.asset_service.delete_asset(record.asset_id)

    async def _card_set_avatar(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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
        asset_id = self.asset_service.store_asset(
            card_id=card_id,
            data=data,
            kind="avatar",
            mime_type=mime,
            source_ref=path.name,
            extension=_asset_extension(mime),
        )
        card = record.card
        if card.hsr is None:
            card.hsr = HsrExtension()
        card.hsr.avatar_asset = AvatarAsset(
            asset_id=asset_id,
            source="user_upload",
            source_ref=path.name,
            mime_type=mime,
        )
        self.card_repository.update_card(card_id, card)
        return {"card_id": card_id, "asset_id": asset_id, "mime_type": mime}

    async def _card_remove_avatar(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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

    # ------------------------------------------------------------------ 角色卡音色

    _REFERENCE_AUDIO_LIMIT = 10 * 1024 * 1024

    @staticmethod
    def _wav_duration(data: bytes) -> float:
        """WAV 时长（秒）；不是合法 WAV 时按 voice_reference_invalid 拒绝。"""
        try:
            with wave.open(io.BytesIO(data)) as handle:
                return handle.getnframes() / float(handle.getframerate())
        except (wave.Error, EOFError) as exc:
            raise ServiceError(
                f"参考音频不是有效的 WAV 文件：{exc}", code="voice_reference_invalid"
            ) from exc

    async def _voice_card_bind_reference(
        self, params: Mapping[str, Any], ctx: CommandContext
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
        mime = _ASSET_MIME_TYPES.guess_type(path.name)[0]
        if mime not in _REFERENCE_AUDIO_MIME_TYPES:
            raise ServiceError(
                "参考音频仅支持 WAV / MP3 / M4A", code="voice_reference_invalid"
            )
        if len(data) > self._REFERENCE_AUDIO_LIMIT:
            raise ServiceError(
                "参考音频超过 10MB 上限", code="voice_reference_invalid"
            )
        # WAV 本地精确校验 60 秒边界；MP3/M4A 不做近似时长判断，大小之外
        # 由 DashScope 裁决并回显错误。
        duration = self._wav_duration(data) if mime == "audio/wav" else None
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
            source_ref=path.name,
            extension=_asset_extension(mime),
        )
        card = record.card
        if card.hsr is None:
            card.hsr = HsrExtension()
        if card.hsr.voice_profile is None:
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

    def _mark_card_voice_failed(self, card_id: str, detail: str) -> None:
        """音色创建失败或取消：落 voice_failed 与原因，保留旧 voice_id。"""
        record = self.card_repository.update_voice_profile(
            card_id, state=CharacterVoiceState.FAILED.value, last_error=detail
        )
        self._card_provision_emit(
            card_id,
            CharacterVoiceState.FAILED.value,
            voice_id=record.card.hsr.voice_profile.voice_id or None,
            error=detail,
        )

    async def _voice_card_create(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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
            reference_audio_asset = (
                card.hsr.voice_profile.reference_audio_asset
                if card.hsr is not None and card.hsr.voice_profile is not None
                else ""
            )
            client = QwenVoiceCustomizationClient(
                api_key=api_key, http_base_url=base_url
            )

            if mode == "clone":
                if not reference_audio_asset:
                    raise ServiceError(
                        "请先绑定参考音频（voice.card_bind_reference）",
                        code="voice_reference_missing",
                    )
                asset = next(
                    (
                        item
                        for item in self.asset_service.list_assets_for_card(card_id)
                        if item.asset_id == reference_audio_asset
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

            # 等待供应商期间卡可能被编辑：每次落库只改音色字段，并重读最新卡。
            self._card_provision_emit(card_id, CharacterVoiceState.CREATING.value)
            self.card_repository.update_voice_profile(
                card_id, state=CharacterVoiceState.CREATING.value
            )
            try:
                if mode == "clone":
                    result = await asyncio.to_thread(
                        client.create_cloned_voice,
                        prefix=prefix,
                        url=audio_url,
                    )
                else:
                    # DashScope 以 InvalidParameter 拒绝少于 15 字符的
                    # preview_text，默认文本不少于 15 字符。
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
            except asyncio.CancelledError:
                self._mark_card_voice_failed(card_id, "音色创建已取消")
                raise
            except Exception as exc:  # noqa: BLE001 - 失败落 voice_failed 后带原因上抛
                detail = self._voice_customization_error(exc, api_key)
                self._mark_card_voice_failed(card_id, detail)
                raise ServiceError(
                    detail, code="voice_card_create_failed"
                ) from exc

            self.card_repository.update_voice_profile(
                card_id,
                state=CharacterVoiceState.READY.value,
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

    async def _voice_card_unbind(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        self._require_playback_control(ctx)
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

    # ------------------------------------------------------------------ 远程服务与电源

    def attach_remote_serve(self, serve: RemoteServe) -> None:
        """登记 --serve 监听成功后的接入信息，广播 serve.started 并启动电源监视。"""
        self.remote_serve = serve
        self.emitter.emit("serve.started", serve.payload())
        self.start_power_monitor()

    async def _power_get_status(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """power.get_status：只读电源状态；读取失败转 power_status_unavailable 并携带原文。"""
        del params
        try:
            status = read_power_status(remote_serve_enabled=self.remote_serve is not None)
        except PowerStatusError as exc:
            raise ServiceError(
                f"读取电源状态失败：{exc}", code="power_status_unavailable"
            ) from exc
        return dataclasses.asdict(status)

    def start_power_monitor(self, *, interval_seconds: float = 60.0) -> None:
        """在事件循环内启动电源监视任务；已在运行时直接返回。

        启动即发出一次 ``power.status_changed``（载荷与 power.get_status 结果
        同形），此后每 ``interval_seconds`` 秒轮询，方案名称、AC/DC 超时或
        远程服务状态变化时才再发。读取失败只写日志，保留上次状态，下轮重试。
        """
        if self._power_monitor_task is not None and not self._power_monitor_task.done():
            return
        self._power_monitor_task = asyncio.create_task(
            self._power_monitor_loop(interval_seconds=interval_seconds),
            name="power-status-monitor",
        )

    async def stop_power_monitor(self) -> None:
        """取消电源监视任务并等待其结束；未启动时直接返回。"""
        task = self._power_monitor_task
        if task is None:
            return
        self._power_monitor_task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise

    async def _power_monitor_loop(self, *, interval_seconds: float) -> None:
        last_key: tuple | None = None
        while True:
            try:
                status = read_power_status(
                    remote_serve_enabled=self.remote_serve is not None
                )
            except PowerStatusError as exc:
                logger.error("电源状态读取失败（保留上次状态，下轮重试）：%s", exc)
            else:
                key = (
                    status.supported,
                    status.plan_name,
                    status.ac_sleep_timeout_seconds,
                    status.dc_sleep_timeout_seconds,
                    status.remote_serve_enabled,
                )
                if key != last_key:
                    last_key = key
                    self.emitter.emit(
                        "power.status_changed", dataclasses.asdict(status)
                    )
            await asyncio.sleep(interval_seconds)

    # ------------------------------------------------------------------ 聊天绑定角色卡（装配）

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
        """按时间最新的一条 completed 摘要（core ``ConversationSummary``）；无则 None。

        存储层 content 是 JSON 对象文本，解析回对象后按 core 模型校验构造。
        """
        latest = self.store.latest_completed_summary(conversation_id)
        if latest is None:
            return None
        return ConversationSummary.model_validate(
            {
                "summary_id": latest.summary_id,
                "conversation_id": latest.conversation_id,
                "status": "completed",
                "covers_from_message_id": latest.covers_from_message_id,
                "covers_to_message_id": latest.covers_to_message_id,
                "covers_message_count": latest.covers_message_count,
                "content": json.loads(latest.content),
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

        无项目会话没有长期记忆作用域：装配按无记忆继续，记忆命令在同一
        会话上照常报错。其余作用域错误照常抛出。
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
        """对话模型的 resolver：按对话绑定的角色卡装配提示词，无内容时返回 None。

        三参 ``(conversation_id, recent_messages, turn_index)``。基座按
        ``(card_id, updated_at)`` 缓存（世界书与 depth_prompt 不进基座）；
        回合上下文（扫描文本与回合号）现算，叠加世界书激活、深度注入与确定性
        触发。``recent_messages`` / ``turn_index`` 缺省时等价空扫描的基座结果。

        最近成功摘要与 active 长期记忆都在这里注入。未绑定卡（或卡已删除）
        的会话只要确有摘要或记忆就用内置角色基座装配：投影已按摘要覆盖把
        原文窗口收窄到 12 条，摘要不注入等于旧历史丢失。两者都没有时返回
        None，交给内置 YAML 提示词。
        """
        return self._resolve_character_assembly(
            self.store.get_conversation(conversation_id), recent_messages, turn_index
        ).prompt

    def _resolve_character_assembly(
        self,
        conversation: Any,
        recent_messages: tuple = (),
        turn_index: int = 0,
    ) -> _CharacterAssembly:
        """装配角色提示词并标明角色基座来源（对话与装配诊断共用）。

        ``card``：绑定卡存在，用卡装配；``builtin``：未绑定或绑定卡已删除，
        但有摘要或记忆，用内置角色基座装配；``none``：没有可装配内容。
        """
        conversation_id = conversation.conversation_id
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
            return _CharacterAssembly(source="none", prompt=None)
        if record is not None:
            cached = self._assembled_cache.get(card_id)
            if cached is not None and cached[0] == record.updated_at:
                base = cached[1]
            else:
                base = assemble_character_prompt(record.card)
                self._assembled_cache[card_id] = (record.updated_at, base)
            card = record.card
            source = "card"
        else:
            card = self._builtin_character_card(conversation)
            base = None
            source = "builtin"
        return _CharacterAssembly(
            source=source,
            prompt=assemble_turn_prompt(
                card,
                scan_texts=[m.text for m in recent_messages],
                turn_index=turn_index,
                base=base,
                summary=summary,
                memories=memories,
            ),
        )

    def _insert_character_greeting(
        self, conversation: Conversation, card: CharacterCard
    ) -> None:
        """绑定卡的聊天创建后插入 first_mes 开场白。

        开场白是新聊天的第一条时间线记录，序号为 1；编排器恢复该聊天时
        从已有最大序号继续计数。
        """
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
            timeline_order=1,
        )
        self.store.save_message(message)
        self.emitter.emit("message.created", {"message": message})

    # ------------------------------------------------------------------ 手机语音

    def attach_event_fanout(self, fanout: Any) -> None:
        """--serve 模式由 __main__ 注入事件扇出；手机语音事件经它下发。"""
        self._event_fanout = fanout

    def _publish_remote_only(self, event: str, payload: dict[str, Any]) -> None:
        fanout = self._event_fanout
        if fanout is None:
            return
        # remote-only 事件只发远程连接，不写桌面 stdout，因此不占用全局序号：
        # 占用序号会在桌面事件流里留下缺口。手机端按无 sequence 即时应用。
        envelope = {
            "kind": "event",
            "event": event,
            "stream_id": self.emitter.stream_id,
            "payload": payload,
        }
        fanout.publish(envelope, remote_only=True)

    def _on_mobile_transcript(
        self, conversation_id: str, session_id: str, text: str, is_final: bool
    ) -> None:
        self._publish_remote_only(
            "voice.mobile_transcript",
            {
                "conversation_id": conversation_id,
                "session_id": session_id,
                "text": text,
                "is_final": is_final,
            },
        )

    def _mobile_asr_factory(self) -> Callable[[], RecognizerPort]:
        # qwen_asr 在模块级导入 dashscope（可选的 voice 依赖组），按需在此导入。
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
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        conversation_id = self._required_string(params, "conversation_id")
        self._current_account_conversation(conversation_id)
        # 转写会话绑定发起连接，连接断开时据此取消。
        if ctx.connection_key is None:
            raise ServiceError(
                "手机语音只能从远程连接发起", code="remote_connection_required"
            )
        factory = self._mobile_asr_factory()
        try:
            session_id = self._mobile_asr.start_session(
                conversation_id, ctx.connection_key, factory
            )
        except MobileAudioError as exc:
            raise ServiceError(str(exc) or exc.code, code=exc.code) from exc

        async def watchdog() -> None:
            # 手机端始终没有发 stop：取消会话，丢弃录音，并把失败告诉手机端。
            await asyncio.sleep(self._mobile_asr_timeout_s)
            self._mobile_asr_watchdogs.pop(session_id, None)
            if self._mobile_asr.cancel_session(session_id) is None:
                return
            self._publish_remote_only(
                "voice.mobile_asr_failed",
                {
                    "conversation_id": conversation_id,
                    "session_id": session_id,
                    "code": "voice_session_timeout",
                    "error": (
                        f"录音超过 {int(self._mobile_asr_timeout_s)} 秒未结束，"
                        "本次转写已取消"
                    ),
                },
            )

        task = asyncio.create_task(watchdog())
        self._mobile_asr_watchdogs[session_id] = task
        return {"session_id": session_id, "conversation_id": conversation_id}

    async def _voice_mobile_audio_chunk(
        self, params: Mapping[str, Any], ctx: CommandContext
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
        """连接断开时静默取消该连接全部未完成的语音会话。

        控制租约不立即释放：持有者有 15 秒重连宽限，宽限结束后由回收流程
        过期；锁屏、切后台和短暂断线都不恢复桌面播放。
        """
        for session_id in self._mobile_asr.cancel_all_for_connection(connection_key):
            self._mobile_asr_watchdogs.pop(session_id).cancel()
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
        self, params: Mapping[str, Any], ctx: CommandContext
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
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        session_id = self._required_string(params, "session_id")
        watchdog = self._mobile_asr_watchdogs.pop(session_id, None)
        if watchdog is not None:
            watchdog.cancel()
        try:
            conversation_id, transcript = await self._mobile_asr.end_session(
                session_id
            )
        except MobileAudioError as exc:
            raise ServiceError(str(exc) or exc.code, code=exc.code) from exc
        text = transcript.strip()
        if not text:
            raise ServiceError("未识别到语音内容", code="voice_transcript_empty")
        # 转写文本以角色消息进入既有提交路径（模式校验/队列/归属全部复用）。
        await self._chat_submit(
            {"conversation_id": conversation_id, "target": "character", "text": text},
            ctx,
        )
        return {
            "session_id": session_id,
            "conversation_id": conversation_id,
            "transcript": text,
        }

    def _maybe_relay_mobile_tts(self, message: Message, voice_id: str | None) -> None:
        """把角色自然语言回复合成后下发到手机；助手、工具与思考不下发。

        ``voice_id`` 由 _on_message 预先解析，None 表示没有可用音色。
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
        if not voice_id:
            logger.info("mobile-tts: 无可用音色，跳过 %s", message.message_id)
            return
        logger.info("mobile-tts: 触发下发 %s（len=%s）", message.message_id, len(message.text))
        # 新回复到达时中断前一条仍在合成的回复。
        for old_msg_id, old_task in tuple(self._mobile_tts_tasks.items()):
            if old_msg_id != message.message_id and not old_task.done():
                logger.info("mobile-tts: 新回复到达，抢占中断旧合成任务 %s", old_msg_id)
                old_task.cancel()
                self._mobile_tts.stop(old_msg_id)
        task = asyncio.create_task(
            self._relay_mobile_tts_task(message, voice_id),
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
        """解析手机朗读可用的音色，随 message.created 的 tts_ready 下发。

        卡级已就绪音色优先，否则按账号级与作者级解析；没有音色或没有
        DashScope Key 时返回 None，手机端据此不展示朗读入口。
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

    async def _relay_mobile_tts_task(self, message: Message, voice_id: str) -> None:
        # qwen_tts 在模块级导入 dashscope（可选的 voice 依赖组），按需在此导入。
        from pair_harness.adapters.audio.qwen_tts import QwenSpeechSynthesizer

        config = self._load_account_config()
        settings = Settings.overlay(Settings.from_environment(), config)
        api_key = (config.get("voice.api_key") or "").strip() or (
            settings.dashscope_api_key or ""
        )
        logger.info(
            "mobile-tts: 开始合成 %s voice=%s ws=%s",
            message.message_id, voice_id, settings.resolved_ws_url,
        )
        synthesizer = QwenSpeechSynthesizer(
            api_key=api_key, ws_url=settings.resolved_ws_url
        )
        stream: TtsStream | None = None
        chunk_count = 0
        try:
            # begin 失败（同一 message_id 仍在下发）同样作为失败上报给手机端。
            stream = self._mobile_tts.begin(message.message_id, message.conversation_id)
            async for chunk in synthesizer.synthesize(
                SpeechRequest(
                    text=message.text,
                    voice_id=voice_id,
                    message_id=message.message_id,
                )
            ):
                # 手机端停止或新回复抢占后不再下发；已下发的分片不撤回。
                if stream.stopped:
                    return
                # 适配器以 final 空块标记合成结束，手机端的结束信号是
                # voice.mobile_tts_end。
                if chunk.final:
                    continue
                chunk_count += 1
                self._publish_remote_only("voice.mobile_tts_chunk", stream.chunk(chunk.pcm))
            if stream.stopped:
                return
            self._publish_remote_only("voice.mobile_tts_end", stream.end_payload())
            logger.info(
                "mobile-tts: 合成完成 %s chunks=%s", message.message_id, chunk_count
            )
        except Exception as exc:  # noqa: BLE001 - 供应商失败必须让手机端退出播放状态
            logger.warning("手机 TTS 下发失败", exc_info=True)
            self._publish_remote_only(
                "voice.mobile_tts_failed",
                {
                    "conversation_id": message.conversation_id,
                    "message_id": message.message_id,
                    # 脱敏后供应商错误（不携带 Key/鉴权头）。
                    "error": self._redact_voice_error(
                        str(exc) or type(exc).__name__, api_key
                    ),
                },
            )
            return
        finally:
            if stream is not None:
                self._mobile_tts.finish(stream)
            try:
                await synthesizer.aclose()
            except Exception as exc:  # noqa: BLE001 - 关闭失败只进日志，不覆盖合成本身的结果
                logger.warning(
                    "mobile-tts: 关闭合成器失败 %s：%s: %s",
                    message.message_id,
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )

    # ------------------------------------------------------------------ 手机远程配对

    def _restore_pairing_state(self) -> None:
        raw = self.store.get_app_state("remote.pairing_state")
        if not raw:
            return
        try:
            state = json.loads(raw)
        except ValueError:
            # 状态损坏按空状态启动；真实错误留在日志，不阻断 Sidecar。
            logger.warning("远程配对状态损坏，按空状态启动", exc_info=True)
            return
        self.pairing_service.load_state(state)
        if state["version"] != 3:
            # 旧版本保存的令牌原文在载入时已转成哈希，立即按版本 3 覆盖落库。
            self._persist_pairing_state()

    def _persist_pairing_state(self) -> None:
        self.store.set_app_state(
            "remote.pairing_state",
            json.dumps(self.pairing_service.export_state(), ensure_ascii=False),
        )

    async def _remote_issue_code(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """生成一次性配对码（5 分钟有效），连同真实接入地址返回。

        控制面命令只由桌面 stdin 调用，远程连接在 WS 鉴权门被拒。
        ``serve_address`` 为 None 表示远程服务尚未监听。
        """
        del params, ctx
        code = self.pairing_service.issue_code()
        return {
            "code": code,
            "ttl_seconds": 300,
            "serve_address": self.remote_serve.payload() if self.remote_serve else None,
        }

    async def _remote_pair(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        code = str(params.get("code") or "")
        device_name = str(params.get("device_name") or "").strip()
        if not code or not device_name:
            raise ServiceError(
                "remote.pair 需要 code 与 device_name", code="invalid_params"
            )
        # 配对码的累计错误次数由 PairingService 在变化当刻经持久化钩子落盘，
        # Sidecar 重启不会重置当前配对码的尝试预算。
        try:
            token = self.pairing_service.claim(code, device_name=device_name)
        except PairingError as exc:
            raise ServiceError(str(exc), code=f"pairing_{exc.code}") from exc
        # 配对成功即时广播，桌面端据此重拉设备列表。
        self.emitter.emit("remote.paired", {"device_name": device_name})
        return {"token": token}

    async def _remote_list_devices(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        del params, ctx
        return {"devices": self.pairing_service.list_devices()}

    async def _remote_revoke(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """撤销该设备名下全部令牌，并回收这些设备持有的控制租约。"""
        del ctx
        device_name = str(params.get("device_name") or "").strip()
        if not device_name:
            raise ServiceError(
                "remote.revoke 需要 device_name", code="invalid_params"
            )
        revoked = self.pairing_service.revoke_device(device_name)
        if not revoked:
            raise ServiceError(
                f"没有可撤销的设备：{device_name}", code="device_not_found"
            )
        for device_key in revoked:
            lease = self._control_leases.pop(device_key, None)
            if lease is not None:
                logger.info("remote-control: 设备撤销回收租约 key=%s", device_key)
                self._emit_control_changed(lease, state="free", reason="revoked")
        return {"device_name": device_name, "revoked_tokens": len(revoked)}

    async def _remote_tunnel_start(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        del params, ctx
        # 隧道只暴露 --serve 监听成功后登记的端口；未监听（未开启或端口被占）
        # 时如实拒绝，避免把占用该端口的无关本地服务交给 cloudflared。
        if self.remote_serve is None:
            raise ServiceError(
                "远程服务未启动（--serve 未监听或端口被占用），无法开启公网接入",
                code="serve_not_started",
            )
        return await self.tunnel_manager.start(self.remote_serve.port)

    async def _remote_tunnel_stop(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        del params, ctx
        return await self.tunnel_manager.stop()

    async def _remote_tunnel_status(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        del params, ctx
        return self.tunnel_manager.status()

    @staticmethod
    def _remote_control_device_key(ctx: CommandContext) -> str:
        if ctx.origin != "remote" or not ctx.device_key:
            raise ServiceError("远程控制需要已鉴权设备身份", code="remote_identity_required")
        return ctx.device_key

    def _require_playback_control(self, ctx: CommandContext) -> None:
        """起始播放与试听按调用方身份判定。

        租约有效期内只有持有者可以起播：桌面调用方被拒（不得抢占远程），
        其他远程设备被拒并点名「另一台远程设备」，租约持有者自身放行。
        """
        self._sweep_control_leases()
        if not self._control_leases:
            return
        if (
            ctx.origin == "remote"
            and ctx.device_key
            and ctx.device_key in self._control_leases
        ):
            return
        if ctx.origin == "remote":
            raise ServiceError(
                "另一台远程设备正在控制语音，请先在该设备退出远程控制或撤销该设备",
                code="remote_playback_active",
            )
        raise ServiceError(
            "远程设备正在控制语音，请先在远程设备退出远程控制或撤销该设备",
            code="remote_playback_active",
        )

    async def _remote_claim_control(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """手机端声明或续租远程控制权。

        按 device_key 独立记录：重复认领只续租不发事件；首次认领抢占桌面
        本地朗读（epoch 递增）并广播 remote.control_changed。
        """
        device_key = self._remote_control_device_key(ctx)
        connection_key = ctx.connection_key
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
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """手机端释放自己的控制租约（恢复桌面播放资格）。

        只回收该 device_key 的租约，其他设备不受影响。
        """
        device_key = self._remote_control_device_key(ctx)
        lease = self._control_leases.pop(device_key, None)
        if lease is not None:
            logger.info(
                "remote-control: 控制器已释放 key=%s, remaining=%d",
                device_key,
                len(self._control_leases),
            )
            self._emit_control_changed(lease, state="free", reason="released")
        return {"released": True, "active_controllers": len(self._control_leases)}

    async def _remote_control_status(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """remote.control_status：只读租约状态。"""
        del params
        return self._control_lease_payload()

    async def _metrics_query(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """metrics.query：只读查询回合指标。

        过滤条件可空；limit 默认 50、上限 200（TurnMetricQuery 校验）。
        未观测字段由写入侧保持 null，这里只透传存储层结果。
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
            # 记录层持有 datetime，协议层按 JSON 模式导出。
            "metrics": [metric.model_dump(mode="json") for metric in page.items],
            "next_cursor": page.next_cursor,
        }

    async def _summary_regenerate(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """summary.regenerate：按原记录的覆盖区间重新生成摘要。

        调用配置的真实模型，在后台执行：先广播 summary.started，终态后广播
        completed 或 failed（failed 携带原始 error_code/error）。
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
            # running 记录仍在生成，没有可重新生成的终态。
            raise ServiceError(
                f"摘要状态 {summary.status} 不支持重新生成（仅 failed/completed）",
                code="summary_invalid",
            )
        task = asyncio.create_task(
            self._run_summary(conversation, summary),
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

    async def _run_summary(
        self, conversation: Conversation, record: StorageSummary
    ) -> None:
        """后台摘要生成：按记录固定的覆盖区间调真实模型 → 校验 → 落库 → 广播终态。

        自动压缩用触发时刻的 running 记录，重新生成沿用原记录的区间与
        summary_id；生成期间的新消息留给下一次触发。失败落 failed 记录并
        广播原始 error_code/error。
        """
        conversation_id = conversation.conversation_id
        try:
            messages = self.store.load_conversation(conversation_id).messages
            window = role_messages(_window_for_record(messages, record))
            if not window:
                raise SummaryError("摘要区间内没有可摘要的消息", code=SUMMARY_INVALID)
            pair_config = load_pair_config(conversation.pair_id)
            content = await self.dialogue_model.generate_summary(
                pair_id=conversation.pair_id,
                assistant_prompt=load_prompt(pair_config.assistant.prompt),
                context_text=_summary_context_text(window),
            )
            provider, model = self._effective_dialogue_identity()
            summary = StorageSummary(
                summary_id=record.summary_id,
                conversation_id=conversation_id,
                covers_from_message_id=record.covers_from_message_id,
                covers_to_message_id=record.covers_to_message_id,
                covers_message_count=len(window),
                content=_json_text(content),
                provider=provider,
                model=model,
                status="completed",
            )
            validate_summary_coverage(messages, summary)
            stored = self.store.upsert_summary(summary)
            # 摘要覆盖终点推进后，角色上下文收窄为最近 12 条原文。
            self.orchestrator.set_summary_coverage(
                conversation_id, stored.covers_to_message_id
            )
            self._emit_summary_event("summary.completed", conversation, stored)
        except SummaryError as exc:
            self._record_summary_failure(
                conversation, record, error_code=exc.code, error=str(exc)
            )
        except Exception as exc:  # noqa: BLE001 - 供应商失败落 failed 记录并广播原文
            logger.exception("摘要生成失败（conversation=%s）", conversation_id)
            self._record_summary_failure(
                conversation,
                record,
                error_code=SUMMARY_PROVIDER_ERROR,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _maybe_auto_summary(self, message: Message) -> None:
        """消息落库后的自动压缩触发判定。

        同会话未压缩 role 消息 ≥80 条或正文 ≥256KiB 时触发；只有最终落库的
        角色消息计数。会话已有在途自动压缩时不重复触发；触发后在后台调模型，
        不阻塞对话主链路。
        """
        if not is_final_message(message):
            return
        conversation_id = message.conversation_id
        if conversation_id in self._auto_summary_in_flight:
            return
        if self._has_unhandled_failed_summary(conversation_id):
            # 上次压缩失败后由用户经 summary.regenerate 重试，不在每条消息上
            # 重复调用模型。
            return
        snapshot = self.store.load_conversation(conversation_id)
        covered_to = self.orchestrator.summary_coverage(conversation_id)
        trigger = summary_trigger(snapshot.messages, covered_to_message_id=covered_to)
        if not trigger.should_start:
            return
        conversation = snapshot.conversation
        # 区间在触发时刻固定，生成期间新消息不改变本次 covers_*。
        running_record = _running_summary_record(
            conversation_id=conversation_id,
            summary_id=f"auto-{conversation_id}-{message.message_id}",
            messages=snapshot.messages,
            covered_to_message_id=covered_to,
        )
        self._auto_summary_in_flight.add(conversation_id)
        self._emit_summary_event("summary.started", conversation, running_record)
        task = asyncio.create_task(
            self._run_summary(conversation, running_record),
            name=f"auto-summary:{conversation_id}",
        )
        self._summary_tasks.add(task)
        # 本回合触发的自动压缩计入回合指标。
        turn_id = self._active_turn_ids.get(conversation_id)
        if turn_id is not None:
            self._turn_compression_counts[turn_id] = (
                self._turn_compression_counts.get(turn_id, 0) + 1
            )

        def _clear(completed: asyncio.Task[None]) -> None:
            self._summary_tasks.discard(completed)
            self._auto_summary_in_flight.discard(conversation_id)

        task.add_done_callback(_clear)

    def _has_unhandled_failed_summary(self, conversation_id: str) -> bool:
        """是否有晚于最近一次成功摘要、尚未重新生成的失败摘要。"""
        latest = self.store.latest_completed_summary(conversation_id)
        return any(
            latest is None or failed.updated_at > latest.updated_at
            for failed in self.store.list_summaries(conversation_id, status="failed")
        )

    def _effective_dialogue_identity(self) -> tuple[str, str]:
        """实际生效的 (供应商, 模型)，摘要、记忆与回合指标据此标注来源。

        与角色对话共用 _dialogue_runtime_settings 的解析口径，记录与实际
        调用不分叉。
        """
        config = self._load_account_config()
        provider, _base_url, _api_key, model = self._dialogue_runtime_settings(config)
        return provider, model

    def _emit_summary_event(
        self, event: str, conversation: Conversation, summary: StorageSummary
    ) -> None:
        self.emitter.emit(
            event,
            summary_event_payload(
                summary,
                account_id=self.current_account_id,
                project_id=conversation.project_id or "",
                pair_id=conversation.pair_id,
                character_ref=self._conversation_character_ref(conversation),
                assistant_identity=self._conversation_assistant_identity(conversation),
            ),
        )

    def _record_summary_failure(
        self,
        conversation: Conversation,
        previous: StorageSummary,
        *,
        error_code: str,
        error: str,
    ) -> None:
        """摘要失败：落库 failed 记录（沿用原区间）并广播原始错误。"""
        stored = self.store.upsert_summary(
            StorageSummary(
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
        )
        self._emit_summary_event("summary.failed", conversation, stored)

    def _conversation_character_ref(self, conversation: Conversation) -> str:
        """会话角色身份（card:<id> 或 builtin:<id>）；身份不完整时为空串。"""
        try:
            scope = resolve_memory_scope(self._conversation_identity(conversation))
        except PairMemoryError:
            return ""
        return scope.character_ref if scope is not None else ""

    def _conversation_assistant_identity(self, conversation: Conversation) -> str:
        return self._conversation_identity(conversation).assistant_identity

    def _conversation_identity(self, conversation: Conversation) -> ConversationIdentity:
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
        """按会话解析记忆作用域；无项目或身份不完整时按真实错误失败。"""
        try:
            conversation = self.store.get_conversation(conversation_id)
        except KeyError:
            raise ServiceError(
                f"会话不存在：{conversation_id}", code="conversation_not_found"
            ) from None
        try:
            scope = resolve_memory_scope(self._conversation_identity(conversation))
        except PairMemoryError as exc:
            raise ServiceError(str(exc), code=exc.code) from exc
        if scope is None:
            raise ServiceError(
                "日常聊天（无项目）不读写长期记忆",
                code=MEMORY_INVALID,
            )
        # core 已校验五分量，存储层查询使用 storage 模型。
        return StorageMemoryScope(
            account_id=scope.account_id,
            project_id=scope.project_id,
            pair_id=scope.pair_id,
            character_ref=scope.character_ref,
            assistant_identity=scope.assistant_identity,
        )

    def _memory_scope_from_params(self, params: Mapping[str, Any]) -> StorageMemoryScope:
        """客户端显式作用域：只用于查询过滤，写入与更新以会话权威作用域为准。"""
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

    async def _summary_get(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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

    async def _memory_create(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """memory.create：显式新增一条长期记忆。

        作用域按会话权威解析（五分量），不接受客户端拼接；日常聊天（无项目）
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
            # 与 MemoryDraft.content 同一约束：空对象不是可处理的记忆。
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
    ) -> StorageMemory:
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

    def _persist_memory_drafts(
        self, conversation_id: str, drafts: tuple[MemoryDraft, ...]
    ) -> None:
        """按会话作用域落库角色本轮声明的长期记忆条目。

        回合只在有项目的会话里运行（chat.submit 对无项目会话报
        daily_chat_unavailable），作用域解析失败即回合失败。
        """
        if not drafts:
            return
        scope = self._conversation_scope(conversation_id)
        for draft in drafts:
            self._store_memory(
                conversation_id=conversation_id,
                scope=scope,
                content=draft.content,
            )

    async def _memory_list(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """memory.list：按作用域读取记忆（显式只读；默认 active）。"""
        conversation_id = _optional_text(params, "conversation_id")
        scope = (
            self._conversation_scope(conversation_id)
            if conversation_id
            else self._memory_scope_from_params(params)
        )
        limit = params.get("limit")
        memories = self.store.list_memories(
            scope,
            status=_optional_text(params, "status") or MemoryStatus.ACTIVE.value,
            limit=int(limit) if limit is not None else None,
        )
        return {
            "memories": [
                _memory_payload(memory, conversation_id=conversation_id)
                for memory in memories
            ]
        }

    async def _memory_update(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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
            # 存储层 content 是 JSON 文本，协议载荷由 _memory_payload 解析回对象。
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

    async def _memory_delete(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """memory.delete：软删除记忆（status=deleted 持久化）并广播。"""
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
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """diagnostics.prompt_assembly：显式只读查询装配诊断。

        默认只返回模块名、字符范围、hash、摘要与记忆是否注入及既有
        diagnostics；只有 include_hidden=true 时返回隐藏原文（内容来自
        装配模块的原文，不属于对话流）。诊断与对话走同一个装配入口，
        ``source`` 标明角色基座来源；没有模块时 ``reason`` 说明原因。
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
        assembly = self._resolve_character_assembly(
            conversation, self._recent_scan_messages(conversation_id)
        )
        if assembly.prompt is not None:
            for module in assembly.prompt.modules:
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
            for key, value in assembly.prompt.diagnostics.items():
                diagnostics.append(f"{key}: {_diagnostics_label(value)}")
        # 角色基座的真实来源：绑定卡装配出空结果、绑定卡已删除、未绑定卡
        # 三种情况各自给出原因，界面据此区分。
        if assembly.source == "card":
            reason = None if modules else "assembly_empty"
        elif card_id:
            reason = "character_card_missing"
        else:
            reason = "character_card_unbound"
        if not modules and reason is not None:
            diagnostics.append(_assembly_empty_label(reason, card_id))
        return {
            "conversation_id": conversation_id,
            "source": assembly.source,
            "modules": modules,
            "reason": reason,
            "diagnostics": diagnostics,
            "generated_at": generated_at,
        }

    def _recent_scan_messages(self, conversation_id: str) -> tuple[Message, ...]:
        """装配诊断的世界书扫描窗口：该聊天最近 12 条消息。"""
        return self.store.load_conversation(conversation_id).messages[-12:]

    async def _account_list(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        return {
            "accounts": self._account_list_payload(),
            "current_account_id": self.current_account_id,
        }

    async def _account_register(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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

    async def _account_login(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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

    async def _account_logout(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """退出当前账号：回到默认账号（登录页状态），数据不删除。"""
        await self._switch_account("default-local")
        return {
            "account": self._account_payload("default-local"),
            "accounts": self._account_list_payload(),
        }

    async def _account_switch(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """免密切换（本地信任的多账号切换；登录仍走 _account_login）。"""
        account_id = self._required_string(params, "account_id")
        if not self._account_exists(account_id):
            raise ServiceError("账号不存在", code="account_not_found")
        await self._switch_account(account_id)
        return {
            "account": self._account_payload(account_id),
            "accounts": self._account_list_payload(),
        }

    async def _account_update_profile(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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

    async def _account_change_password(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
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
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """首次引导完成标记：由前端在注册后显式触发，登录/注册命令不自动置位。"""
        account_id = self.current_account_id
        self.store.set_onboarding_complete(account_id, True)
        self._emit_account_changed()
        return {"account": self._account_payload(account_id)}

    def _voice_settings(self, config: dict[str, str]) -> dict[str, Any]:
        """语音账号配置与 6 个说话方的生成状态视图（不含明文 Key）。"""
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

    async def _config_get(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        return self._config_payload()

    def _config_payload(self) -> dict[str, Any]:
        config = self._load_account_config()
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
            # 编程助手只有 reasonix acp 一条路径，前端不发送 engine。
            "engine": PROGRAM_ENGINE,
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
                # 账号保存自己的 voice.api_key/voice.base_url；模型是产品常量，
                # 只读展示。
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
        }

    async def _config_set(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """账号级配置：扁平键写入 provider_configs/secret_refs，立即生效。

        ``voice.api_key`` 写 secret_refs，``voice.base_url`` 写
        provider_configs；ASR/TTS 模型与音色 ID 由应用固定，客户端禁止写入。
        保存只落库，不触发音色生成（生成走 voice.provision）。
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
        # 配置保存与账号切换互斥；先验证候选运行时，再单事务落库，提交成功
        # 后才替换运行时。
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
                # 语音开关变化后，旧错误不再描述当前状态。
                self._clear_voice_error()
            if "assistant_voice_enabled" in updates:
                self._voice_state["assistant_voice_enabled"] = (
                    account_config.get("assistant_voice_enabled") in ("true", "1")
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
            return {"config": self._config_payload()}

    async def _config_test_connection(
        self, params: Mapping[str, Any], ctx: CommandContext
    ) -> dict[str, Any]:
        """探测对话服务连接：短请求验证 base_url/model/api_key。

        结论一律回传实际探测的 provider/base_url/model（来自当前生效配置），
        被拒绝的候选写入从未生效，不会被这里的结论覆盖。
        """
        # --demo 运行时没有真实对话后端，如实返回失败，不让首次引导把演示
        # 模式读成配置可用。
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
        # 不受支持的历史供应商直接按可定位原因拒绝，不做网络探测。
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
        """配置保存先验证后提交（调用方必须已持有账号切换锁）。

        合并候选配置 → 构建候选运行时 → 单事务写全部配置/密钥 →
        提交成功后替换运行时；任何失败都关闭候选并保持数据库旧值。
        """
        updates = self._canonicalize_provider_updates(dict(updates))
        current = self._load_account_config()
        candidate_config = {**current, **updates}
        candidate: Runtime | None = None
        if not self._demo:
            try:
                candidate = self._build_runtime_candidate(candidate_config)
            except ServiceError:
                raise
            except Exception as exc:  # noqa: BLE001 - 构建失败即配置被拒绝，原文随错误码返回
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
        # 偏好保存不丢掉可恢复的引擎会话。
        invalidate_sessions = bool(provider_keys.intersection(updates))
        try:
            self.store.set_configs_and_secrets(
                self.current_account_id, config_updates, secret_updates
            )
        except BaseException:
            if candidate is not None:
                await self._close_runtime(candidate)
            raise
        if candidate is not None:
            self._install_runtime(candidate, invalidate_sessions=invalidate_sessions)

    def _build_runtime_candidate(
        self, config: dict[str, str], *, account_id: str | None = None
    ) -> Runtime:
        """为指定账号构建候选运行时，不触碰当前运行时。

        角色与助手都走 OpenAI Chat Completions 兼容路径。历史 openai_oauth
        配置同样按它保存的端点构建，请求会在真实调用上如实失败；
        config.get 与 test_connection 会标注该供应商不受支持。
        """
        account_id = account_id or self.current_account_id
        provider, dialogue_base, dialogue_key, dialogue_model_name = (
            self._dialogue_runtime_settings(config)
        )
        self._validate_provider_endpoint(provider, dialogue_base)
        dialogue_model = OpenAICompatibleDialogueModel(
            base_url=dialogue_base,
            api_key=dialogue_key,
            model=dialogue_model_name,
            temperature=1.0,
            character_prompt_resolver=self._resolve_character_prompt,
        )
        coding_engine = build_coding_engine(
            # CodexAuthService 只提供账号目录（Reasonix 配置写入点）。
            codex_auth=CodexAuthService(self.store.database.parent, account_id),
            model=dialogue_model_name,
            base_url=dialogue_base,
            api_key=dialogue_key,
            reasoning_effort=config.get("dialogue.reasoning_effort") or "auto",
            diagnostic_callback=self._emit_diagnostic_warning,
        )
        return Runtime(
            dialogue_model=dialogue_model,
            coding_engine=coding_engine,
            reviewer=DialogueModelReviewer(dialogue_model),
        )

    @staticmethod
    def _validate_provider_endpoint(provider: str, base_url: str) -> None:
        """供应商与端点一致性校验。"""
        if provider != "openai_oauth" and base_url:
            endpoint_provider = detect_provider(base_url).value
            if (provider == "deepseek") != (endpoint_provider == "deepseek"):
                raise ServiceError(
                    "dialogue.provider 与 Base URL 不一致；请同时选择同一供应商的配置",
                    code="provider_endpoint_mismatch",
                )

    def _install_runtime(self, runtime: Runtime, *, invalidate_sessions: bool) -> None:
        """换入新运行时并异步关闭旧运行时。

        ``invalidate_sessions`` 为 True 时清空当前账号的引擎会话（内存与
        SQLite），下一次任务在新 transport 上新开 session；切换账号时目标
        账号的会话由它自己的配置创建，保留可恢复。
        """
        previous = self.orchestrator.install_runtime(runtime)
        if invalidate_sessions:
            self.orchestrator.forget_sessions()
            self.store.clear_engine_sessions(self.current_account_id)
        self._close_runtime_later(previous)

    def _close_runtime_later(self, runtime: Runtime) -> None:
        """异步关闭被换下的运行时，不阻塞切换与保存路径。"""
        task = asyncio.create_task(self._close_runtime(runtime), name="close-runtime")
        self._close_runtime_tasks.add(task)
        task.add_done_callback(self._close_runtime_tasks.discard)

    async def _close_runtime(self, runtime: Runtime) -> None:
        """关闭对话模型的 HTTP client 与编程助手 transport；失败写日志。"""
        errors: list[str] = []
        try:
            await runtime.dialogue_model.aclose()
        except Exception as exc:  # noqa: BLE001 - 关闭失败记入日志，不打断切换
            errors.append(f"dialogue_model.aclose: {type(exc).__name__}: {exc}")
        try:
            await runtime.coding_engine.aclose()
        except Exception as exc:  # noqa: BLE001 - 关闭失败记入日志，不打断切换
            errors.append(f"coding_engine.aclose: {type(exc).__name__}: {exc}")
        if errors:
            logger.error("关闭旧运行时失败：%s", " | ".join(errors))

    def _legacy_config_notices(self, config: dict[str, str]) -> list[dict[str, str]]:
        """历史账号配置的提示项（只读，不改写已保存的值）。

        覆盖两类继承配置：已移除的供应商（openai_oauth）与不再生效的
        engine 值（旧版本写入的 codex）。
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
        """引擎诊断告警转发到客户端事件通道。"""
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

        供应商由 dialogue.provider / dialogue.base_url 决定（两者必须一致）；
        engine 由后端写为 reasonix，客户端发来的其他 engine 值按
        invalid_engine 拒绝。
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
            # 不受支持的供应商不能经配置写入被选中（历史值仍可读取），整次
            # 写入按可定位原因拒绝。
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
        # 任何受支持的兼容端点都装配同一个引擎。
        updates["engine"] = PROGRAM_ENGINE
        self._validate_provider_endpoint(
            provider,
            updates.get("dialogue.base_url")
            or current.get("dialogue.base_url")
            or self._env_dialogue_base(),
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

    async def _probe_dialogue_connection(
        self, base_url: str, api_key: str, model: str
    ) -> dict[str, Any]:
        """短请求探测对话服务（不产生对话历史）。"""
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
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            # 连接层异常的自述可能为空串（如 httpx.ConnectError），提示里
            # 回落到真实类型名；原始异常照常进日志。
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

    async def _cancel_work_for_account_switch(self) -> None:
        """按当前账号枚举并结清全部活动任务，再切换。

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
        """原子账号切换：候选构建成功后一次性交换账号、上下文与运行时。

        步骤：持有账号切换锁 → 取消并等待当前任务终态 → 只读构建目标账号
        候选运行时与上下文 → 全部成功后提交账号、项目/会话和运行时 →
        广播 account.changed 与新快照 → 异步关闭旧运行时。任一步失败关闭
        候选并回滚原账号状态。
        """
        if account_id == self.current_account_id:
            return
        async with self._account_switch_lock:
            previous_account_id = self.current_account_id
            previous_project_id = self.current_project_id
            previous_conversation_id = self.current_conversation_id
            previous_pair_config = self.pair_config
            candidate: Runtime | None = None
            previous_runtime: Runtime | None = None
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

                # 3. 全部候选成功后，一次性提交账号身份与运行时。目标账号的
                # 引擎会话由它自己的配置创建，切换后仍可恢复。
                self.current_account_id = account_id
                self.store.set_app_state("current_account_id", account_id)
                if candidate is not None:
                    previous_runtime = self.orchestrator.install_runtime(candidate)

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

                # 5. 语音配置（Key、地址、音色映射）随账号隔离，用目标账号的
                # 配置重建 VoiceRuntime。音色生成状态按 account_id 保存，切回
                # 原账号后仍可显示并重试。
                await self._rebuild_voice_runtime_locked()

                # 6. 广播账号变更与新账号快照。
                self._emit_account_changed()
                self._emit_state_snapshot()
            except BaseException:
                self.current_account_id = previous_account_id
                self.store.set_app_state("current_account_id", previous_account_id)
                self.current_project_id = previous_project_id
                self.current_conversation_id = previous_conversation_id
                self.pair_config = previous_pair_config
                if previous_runtime is not None:
                    self.orchestrator.install_runtime(previous_runtime)
                if previous_conversation_id:
                    self._restore_conversation_state(previous_conversation_id)
                    await self._focus_voice_context(
                        previous_conversation_id, previous_pair_config.pair_id
                    )
                if candidate is not None:
                    await self._close_runtime(candidate)
                raise
            if previous_runtime is not None:
                self._close_runtime_later(previous_runtime)

    # ------------------------------------------------------------------ 状态与事件

    def _on_message(self, message: Message) -> None:
        payload: dict[str, Any] = {"message": message}
        # 角色自然语言回复：预判手机端朗读可用性并随 message.created 下发。
        # 服务端是合成能力的唯一权威；tts_ready=false（账号音色未生成或无
        # Key）时手机端不展示朗读入口。
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
        # 角色自然语言回复下发到在线手机端合成；助手、工具、思考与系统消息
        # 不下发音频。
        self._maybe_relay_mobile_tts(message, voice_id)
        # 最终落库消息到达后判定是否触发自动压缩（只读判定，不调模型）。
        self._maybe_auto_summary(message)

    def _emit_state_snapshot(self) -> None:
        """发出与事件自身序号一致的完整快照。"""
        snapshot = self.bootstrap()
        # EventEmitter 会把下一条事件分配为 next_sequence；快照作为该事件
        # 的载荷时，内部序号必须与外层序号一致，前端才会继续接收后续事件。
        snapshot["sequence"] = self.emitter.next_sequence
        self.emitter.emit("state.snapshot", snapshot)

    def _on_message_status_changed(self, message: Message) -> None:
        """消息状态推进（message.status_changed），前端按 id 对账。"""
        self.emitter.emit(
            "message.status_changed", {"message": message}
        )

    def _on_review_event(self, event: str, payload: dict) -> None:
        """审查智能体生命周期事件，只在真正调用审查时触发。

        payload 带编排器在审查开始时捕获的 conversation_id。
        """
        if event in {"review.started", "review.completed", "review.failed"}:
            self.emitter.emit(event, payload)

    def _note_turn_first_event(self, conversation_id: str) -> None:
        """记下本回合首个真实引擎/流式事件的时间（只写首个，不覆盖）。

        first_event_latency_ms 来自真实首事件；没有事件的回合保持 null。
        """
        turn_id = self._active_turn_ids.get(conversation_id)
        if turn_id is None:
            return
        turn = self._turns.get(turn_id)
        if turn is None or turn.get("first_event_at"):
            return
        self._turns[turn_id] = {**turn, "first_event_at": utc_now().isoformat()}

    def _on_dialogue_event(
        self,
        conversation_id: str,
        user_message: Message,
        event: DialogueEvent,
        timeline_order: int,
    ) -> None:
        """把角色对话增量转发为 message.delta 的 reasoning/speech 通道。

        结构化 JSON 增量只推送干净字段；原始 JSON 进入技术详情（raw），
        不进入消息气泡。思考与正文共用一个消息 id 与时间线序号，前端把它们
        合成一个气泡，正文完成后由最终消息覆盖临时流。
        """
        self._note_turn_first_event(conversation_id)
        if event.type == "character.final":
            return
        payload: dict[str, Any] = {
            "message_id": f"speech:{conversation_id}:{user_message.message_id}",
            "conversation_id": conversation_id,
            "pair_id": user_message.pair_id,
            "source": "character",
            "kind": "character.speech",
            "delta": event.delta or "",
            "timeline_order": timeline_order,
        }
        channel, _, phase = event.type.partition(".")
        if channel == "reasoning":
            payload["channel"] = "reasoning"
            payload["reasoning_streaming"] = phase != "completed"
        if phase == "started":
            payload["started"] = True
        elif phase == "completed":
            payload["completed"] = True
            if channel == "speech" and event.raw:
                payload["raw"] = event.raw
        self.emitter.emit("message.delta", payload)

    def _on_engine_event(self, event: EngineEvent) -> None:
        self._note_turn_first_event(event.conversation_id)
        event_type = event.type
        if event_type in (
            EngineEventType.ASSISTANT_DELTA,
            EngineEventType.ASSISTANT_REASONING_DELTA,
        ):
            # 思考与正文共用编排器分配的 segment 消息 id 与时间线序号，工作台
            # 沿用单气泡流式展示。
            payload = event.payload
            message_id = str(payload["message_id"])
            self._streaming_message_ids.setdefault(
                (event.conversation_id, event.task_id), set()
            ).add(message_id)
            delta: dict[str, Any] = {
                "message_id": message_id,
                "conversation_id": event.conversation_id,
                "source": "assistant",
                "kind": "assistant.natural_language",
                "delta": str(payload.get("text", "")),
                "task_id": event.task_id,
                "segment_index": payload["segment_index"],
                "timeline_order": payload["timeline_order"],
                "reasoning_streaming": False,
            }
            if event_type == EngineEventType.ASSISTANT_REASONING_DELTA:
                delta["kind"] = "assistant.reasoning"
                delta["channel"] = payload.get("channel", "summary")
                delta["reasoning_streaming"] = True
            self.emitter.emit("message.delta", delta)
        elif event_type in (
            EngineEventType.TOOL_STARTED,
            EngineEventType.TOOL_PROGRESS,
            EngineEventType.TOOL_FINISHED,
        ):
            if event_type == EngineEventType.TOOL_STARTED:
                # 工具边界定稿当前 segment：旧 segment 不再接收 delta，前端以
                # message.finalized 解除流式占位。
                self._finalize_streaming_segments(
                    event.conversation_id, event.task_id
                )
            self._emit_tool_run(event)
        elif event_type == EngineEventType.APPROVAL_RESOLVED:
            self.approval_broker.publish_engine_resolution(event)

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
                status = str(payload["status"])
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
                timeline_order=payload["timeline_order"],
            )
        else:
            status = current.status
            if event.type == EngineEventType.TOOL_FINISHED:
                status = cast(Any, str(payload["status"]))
            run = current.model_copy(
                update={
                    "sequence": event.sequence,
                    "status": status,
                    # 后续完成事件可能只带“工具调用”标题，保留开始事件里的真实命令。
                    "title": str(payload.get("command") or current.title or payload.get("title") or "工具"),
                    "summary": str(payload.get("summary", current.summary)),
                    "details": str(payload.get("details", current.details)),
                }
            )
        self._tool_runs[key] = run
        self.emitter.emit("tool_run.upserted", {"tool_run": run})

    def _on_execution_started(self, active: Any) -> None:
        # 事件携带事件发生后的完整活动任务集合，前端直接替换，增删事件
        # 丢失也不会形成幽灵忙碌状态。
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
        # 只收尾本任务自己的流式 segment，其他并发任务的占位保持不变。
        self._finalize_streaming_segments(active.conversation_id, active.task_id)
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

    # ------------------------------------------------------------------ 上下文工具

    def _requested_pair_id(self, params: Mapping[str, Any]) -> str:
        """解析创建命令的搭档参数；省略时使用当前搭档。"""
        if "pair_id" not in params:
            return self.pair_config.pair_id
        pair_id = str(params["pair_id"])
        if pair_id not in PAIR_CATALOG_IDS:
            raise ServiceError(
                f"搭档不存在：{pair_id}",
                code="PAIR_NOT_FOUND",
            )
        return pair_id

    def _restore_conversation_state(self, conversation_id: str) -> ConversationSnapshot:
        """把聊天快照回填进编排器历史与工具记录缓存（幂等），返回快照。"""
        snapshot = self.store.load_conversation(conversation_id)
        self.orchestrator.restore_conversation(snapshot)
        for tool_run in snapshot.tool_runs:
            self._tool_runs[(tool_run.conversation_id, tool_run.tool_call_id)] = tool_run
        return snapshot

    def _recover_interrupted_work(self) -> None:
        """服务启动时对全部聊天做一次崩溃恢复。

        上一个 Sidecar 进程在委派、队列派发或音色创建中途退出后，进程内
        任务已经不存在：遗留的 processing 委派卡标为失败，processing 队列项
        退回 queued，voice_creating 的角色卡标为 voice_failed。只在启动时执行，
        运行中的任务不受影响。
        """
        self.store.requeue_processing_queue_items()
        for conversation_id in self.store.conversations_with_processing_delegations():
            self.orchestrator.restore_conversation(
                self.store.load_conversation(conversation_id)
            )
            self.orchestrator.mark_processing_delegations_failed(
                conversation_id,
                "Sidecar 在委派完成前断开，任务已停止，请重新发送。",
            )
        for record in self.card_repository.list_cards(include_archived=True):
            if record.voice_state == CharacterVoiceState.CREATING.value:
                self.card_repository.update_voice_profile(
                    record.card_id,
                    state=CharacterVoiceState.FAILED.value,
                    last_error="Sidecar 在音色创建完成前断开，请重新创建。",
                )

    def _resolve_execution_context(self, conversation_id: str) -> ExecutionContext:
        """提交被接受时一次性解析不可变执行上下文。

        只读取 SQLite 与搭档目录，不改写 ``current_*`` 视图状态；后台
        聊天的提交与运行中的 Turn 都使用这份快照，切换界面当前聊天
        不影响已经运行的 Turn。
        """
        conversation = self._current_account_conversation(conversation_id)
        project = self.store.get_project(conversation.project_id)
        selected_pair = load_pair_config(conversation.pair_id)
        assistant_md = load_prompt(selected_pair.assistant.prompt)
        return ExecutionContext(
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
            assistant_instructions=assistant_md,
        )

    def _effective_voice_pair(
        self, pair_id: str, conversation_id: str | None = None
    ) -> PairConfig:
        """按当前账号解析某个搭档的真实有效音色。

        聊天绑定卡且卡音色 voice_ready 时，角色侧 voice_id 覆盖为卡音色；
        助手侧不覆盖，也不可用。
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
        """聊天绑定卡的可用音色；未绑定、卡已删除或音色未就绪时为空串。"""
        card_id = self.store.get_conversation(conversation_id).character_card_id
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
        # 账号是完整隔离边界：先校验会话与项目归属，再更新最近打开时间。
        conversation = self._current_account_conversation(conversation_id)
        project = self.store.mark_project_opened(conversation.project_id)
        if conversation_id != self.current_conversation_id:
            self.orchestrator.close_conversation(self.current_conversation_id)
        self.current_project_id = project.project_id
        self.current_conversation_id = conversation_id
        self.pair_config = load_pair_config(conversation.pair_id)
        self._restore_conversation_state(conversation_id)
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
        return self._create_conversation(
            project_id,
            pair_id=pair_id,
            character_card_id=character_card_id or self._effective_active_card_id(),
        )

    def _create_conversation(
        self,
        project_id: str,
        *,
        pair_id: str,
        character_card_id: str | None,
        title: str | None = None,
    ) -> Conversation:
        """新建聊天并插入绑定卡的开场白。

        聊天快照创建时的角色卡；之后切换 active 卡不影响已开的聊天。
        """
        conversation = self.store.create_conversation(
            project_id=project_id,
            pair_id=pair_id,
            title=title or "新聊天",
            title_source="user" if title else "default",
            account_id=self.current_account_id,
            character_card_id=character_card_id,
        )
        if character_card_id:
            try:
                record = self.card_repository.get_card(character_card_id)
            except KeyError:
                record = None
            if record is not None:
                self._insert_character_greeting(conversation, record.card)
        return conversation

    def _schedule_title_generation(self, conversation_id: str, target: str) -> None:
        """首次完整回复后按会话自己的搭档生成标题；只处理仍是初始名的聊天。"""
        if conversation_id in self._title_generation_started:
            return
        conversation = self.store.get_conversation(conversation_id)
        if conversation.title_source != "default":
            return
        context_sources = (
            {MessageSource.USER, MessageSource.CHARACTER}
            if target == "character"
            else {MessageSource.USER, MessageSource.ASSISTANT}
        )
        context = tuple(
            message
            for message in self.store.load_conversation(conversation_id).messages
            if message.source in context_sources and message.text.strip()
        )
        if not context:
            return
        self._title_generation_started.add(conversation_id)
        task = asyncio.create_task(
            self._generate_title(
                conversation_id, pair_id=conversation.pair_id, context=context
            ),
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
        """生成并保存模型给出的标题；只去掉首尾空白，超长标题由界面省略显示。"""
        try:
            try:
                title = await self.dialogue_model.generate_title(
                    pair_id=pair_id, context=context
                )
            except Exception:  # noqa: BLE001 - 命名失败写日志，聊天主链路不受影响
                logger.warning(
                    "自动生成聊天标题失败（conversation=%s）",
                    conversation_id,
                    exc_info=True,
                )
                return
            title = title.strip()
            if not title:
                logger.warning(
                    "自动生成聊天标题失败（conversation=%s）：模型返回空标题",
                    conversation_id,
                )
                return
            # 生成期间用户可能已手动改名：只在标题来源仍为 default 时写入。
            if not self.store.set_auto_title(conversation_id, title):
                return
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
            # 回复可以重试；成功后标题来源变为 auto，不会重复命名。
            self._title_generation_started.discard(conversation_id)

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
    # 启动不自动恢复已归档项目；只有用户显式重新选择该目录时才由
    # project.create 恢复旧记录。
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
    store: SQLiteStore, *, project_id: str, pair_id: str, account_id: str
):
    conversations = store.list_conversations(project_id, account_id=account_id)
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
    # 当前聊天的 pair_id 是业务状态，重启时以它为准；命令行搭档只用于新建聊天。
    pair_config = load_pair_config(
        conversation.pair_id if conversation is not None else pair_id
    )
    service = DesktopApplicationService(
        store=store,
        pair_config=pair_config,
        pair_catalog=list_pair_configs(),
        emitter=EventEmitter(event_sink, stream_id=stream_id),
        demo=demo,
        current_account_id=account_id,
        current_project_id=project.project_id if project is not None else "",
        current_conversation_id=(
            conversation.conversation_id if conversation is not None else ""
        ),
    )
    if not demo:
        # 历史账号配置（已移除的供应商或 engine 选择）在启动期如实提示，
        # 已保存的值不改写，用户可进入设置页重新配置。
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
    db = database or AppPaths.default().ensure().database
    return _build_service(
        database=db,
        project_root=project_root,
        pair_id=pair_id,
        event_sink=event_sink or (lambda _message: None),
        demo=demo,
        stream_id=stream_id,
    )
