from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Mapping, cast
from urllib.parse import urlsplit
from uuid import uuid4

from pair_harness.adapters.codex.auth import CodexAuthService
from pair_harness.adapters.codex.engine import CodexAppServerEngine
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
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.core.voice_policy import is_readable_text
from pair_harness.core.voice_runtime import VoiceRuntime
from pair_harness.settings import Settings
from pair_harness.storage.sqlite_store import SQLiteStore
from .pairing import PairingError, PairingService
from .power import PowerStatus, PowerStatusError, read_power_status
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


logger = logging.getLogger(__name__)


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
    """

    def __init__(self, emitter: EventEmitter) -> None:
        self._emitter = emitter
        self._pending: dict[str, dict[str, Any]] = {}
        # V0.3.5：已决审批的短时结果记录——双端并发应答同一审批时，后到者
        # 收到 approval_already_resolved 与先到者的真实结果，双端状态收敛
        # （docs/plans/V0.3.5-契约冻结.md §6）。容量有界，防长会话累积。
        self._resolved: dict[str, dict[str, Any]] = {}

    @property
    def pending(self) -> dict[str, dict[str, Any]]:
        return self._pending

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
            return await future
        finally:
            self._pending.pop(approval_id, None)

    def resolve(
        self, approval_id: str, decision: str, *, resolved_by: str = "desktop"
    ) -> dict[str, Any]:
        item = self._pending.get(approval_id)
        if item is None:
            prior = self._resolved.get(approval_id)
            if prior is not None:
                # 契约 §6：后到者拿到先到者的真实结果（结构化字段），
                # 双端据此收敛展示，不必解析 message 文案。
                raise ServiceError(
                    f"审批已由 {prior['resolved_by']} 应答（{prior['decision']}），"
                    "不能重复应答",
                    code="approval_already_resolved",
                    details={
                        "decision": prior["decision"],
                        "resolved_by": prior["resolved_by"],
                    },
                )
            raise ServiceError(
                f"审批请求不存在或已经完成：{approval_id}",
                code="approval_not_found",
            )
        try:
            parsed = ApprovalDecision(decision)
        except ValueError as exc:
            raise ServiceError(f"未知审批决定：{decision}", code="invalid_decision") from exc
        future = cast(asyncio.Future[ApprovalDecision], item["future"])
        if not future.done():
            future.set_result(parsed)
        # 先到者立即占位：并发第二答在 pending 已移除后走 already_resolved，
        # 不会因 future 已 done 而静默成功（request 的 finally pop 幂等）。
        self._pending.pop(approval_id, None)
        outcome = {"decision": parsed.value, "resolved_by": resolved_by}
        self._resolved[approval_id] = outcome
        if len(self._resolved) > 256:
            self._resolved.pop(next(iter(self._resolved)))
        return outcome

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

    def _cancel_item(
        self, approval_id: str, item: dict[str, Any], reason: str
    ) -> None:
        future = cast(asyncio.Future[ApprovalDecision], item["future"])
        if not future.done():
            future.set_result(ApprovalDecision.DENY)
        self._pending.pop(approval_id, None)
        self._emitter.emit(
            "approval.resolved",
            {
                "approval_id": approval_id,
                "conversation_id": item.get("conversation_id"),
                "task_id": item.get("task_id"),
                "decision": ApprovalDecision.DENY.value,
                "reason": reason,
                "actor": "system",
            },
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

    def attach_voice_runtime(self, runtime: VoiceRuntime) -> None:
        self.voice_runtime = runtime
        self._voice_state["supported"] = True
        self.orchestrator.add_message_listener(runtime.on_message)
        self._emit_voice_changed()

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
            self.orchestrator.remove_message_listener(old_runtime.on_message)
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
        self._emit_voice_changed()

    def _on_asr_partial(self, text: str) -> None:
        self._voice_state["asr_partial"] = text
        self.emitter.emit("voice.asr_partial", {"text": text})

    def _on_voice_error(self, message: str) -> None:
        self._voice_state["error"] = message
        self._emit_voice_changed()

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
        }
        if command.method == "approval.resolve":
            # V0.3.5：审批应答需要命令来源做双端仲裁，其余 handler 只收 params。
            return await self._approval_resolve(
                command.params, origin=command.origin
            )
        if command.method == "voice.mobile_ptt_start":
            # V0.3.5：语音会话绑定传输层注入的连接 key，供断开清理。
            return await self._voice_mobile_ptt_start(
                command.params, connection_key=command.connection_key
            )
        handler = handlers[command.method]
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
            if isinstance(self.orchestrator.coding_engine, CodexAppServerEngine):
                self.orchestrator.coding_engine.configure_reasoning(effort)
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

    async def _conversation_create(self, params: Mapping[str, Any]) -> dict[str, Any]:
        pair_id = self._requested_pair_id(params)
        project_id = str(params.get("project_id") or self.current_project_id)
        project = self._current_account_project(project_id)
        title = str(params.get("title") or "新聊天")
        # V0.3.5：显式 character_card_id 优先；缺省快照当时有效的 active 卡。
        card_id = str(params.get("character_card_id") or "").strip() or None
        if card_id is None:
            card_id = self._effective_active_card_id()
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
        return self.bootstrap()

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
        self._current_account_conversation(conversation_id)
        self.store.archive_conversation(conversation_id)
        remaining = self.store.list_conversations(
            self.current_project_id, account_id=self.current_account_id
        )
        if not remaining:
            created = self._find_or_create_conversation(
                self.current_project_id, pair_id=self.pair_config.pair_id
            )
            remaining = [created]
        if conversation_id == self.current_conversation_id:
            await self._select_conversation_context(remaining[0].conversation_id, emit=True)
        else:
            self.emitter.emit("conversation.changed", {"conversation_id": conversation_id})
        return self.bootstrap()

    async def _chat_submit(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """V0.2 快速接受（问题 1）：同步落库用户消息，立即返回真实 id。

        回合处理移到后台任务（``_run_submit_turn``），前端按真实
        ``message_id`` 即时回显并推进状态；处理失败后文字仍在可重试。
        """
        conversation_id = str(params.get("conversation_id") or self.current_conversation_id)
        if not conversation_id:
            raise ServiceError("请先创建或选择项目", code="no_active_conversation")
        self._current_account_conversation(conversation_id)
        target = str(params.get("target", "character"))
        text = self._required_string(params, "text")
        if target not in {"character", "assistant"}:
            raise ServiceError("target 必须是 character 或 assistant", code="invalid_target")
        # M3.1：chat.submit 与账号切换/配置保存互斥。锁从模式/上下文切换
        # 开始持有，避免切换过程中提交落到半旧半新的状态。
        async with self._account_switch_lock:
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
                turn = self._register_turn(conversation_id, user_message, target)
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

    def _register_turn(self, conversation_id: str, user_message: Any, target: str) -> dict[str, Any]:
        """创建并登记 Turn（accepted 态），返回 payload。"""
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
        """V0.2 M2：持久化队列自动派发——processing → 回合 → 完成删除；
        回合失败退回 queued（可重试），不再自动派发后续。

        M1.2：记录当前 queue item，只有 completed 才删除；异常/取消在
        finally 中把仍为 processing 的项目退回 queued。
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
                if status != "completed":
                    self.store.set_queue_item_status(queue_item_id, "queued")
                    self._emit_queue_changed(conversation_id)
                    return
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
        result = "completed"
        terminal_status = "completed"
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
            self.orchestrator.mark_message_failed(
                conversation_id, user_message.message_id, str(exc)
            )
            self.orchestrator.mark_processing_delegations_failed(
                conversation_id, str(exc)
            )
            self.orchestrator.report_system_status(
                conversation_id, f"本次回复失败：{exc}"
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
        return result

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

    async def _voice_tts_play(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """逐条朗读：按 message_id 从会话取消息文本，重新合成入队（可重播）。"""
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
        self.voice_runtime.replay_message(message)
        return {"voice": self._voice_snapshot()}

    async def _voice_tts_skip(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        if self.voice_runtime is None:
            raise ServiceError("语音运行时未启用", code="voice_unavailable")
        await self.voice_runtime.skip_playing_async()
        return {"voice": self._voice_snapshot()}

    async def _voice_preview(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """语音试听：按指定文本合成入队；voice_id 缺省取当前有效角色音色。

        V0.3.2 M6：账号 BYOK 模式允许试听当前账号已生成的全部 manifest
        音色；开发机作者音色仍只允许当前搭档。显式传入未知 ID 时如实
        报错，不能静默替换成角色音色。voice_id 缺省时使用当前角色音色。
        """
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

    async def _voice_card_preview(self, params: Mapping[str, Any]) -> dict[str, Any]:
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

    def _resolve_character_prompt(
        self,
        conversation_id: str,
        recent_messages: tuple = (),
        turn_index: int = 0,
    ) -> "AssembledPrompt | None":
        """按对话绑定的角色卡装配提示词；未绑定或卡已删除返回 None。

        V0.3.7 契约 §4.5：resolver 三参 ``(conversation_id, recent_messages,
        turn_index)``。基座按 ``(card_id, updated_at)`` 缓存（世界书与
        depth_prompt 不进基座）；回合上下文（扫描文本与回合号）现算，
        叠加世界书激活、深度注入与确定性触发。``recent_messages`` /
        ``turn_index`` 带缺省值，兼容既有单参调用（等价空扫描的基座结果）。
        """
        try:
            conversation = self.store.get_conversation(conversation_id)
        except KeyError:
            return None
        card_id = conversation.character_card_id
        if not card_id:
            return None
        try:
            record = self.card_repository.get_card(card_id)
        except KeyError:
            # 卡已被删除：回退内置角色；降级提示由 conversation.open 发出。
            return None
        cached = self._assembled_cache.get(card_id)
        if cached is not None and cached[0] == record.updated_at:
            base = cached[1]
        else:
            base = assemble_character_prompt(record.card)
            self._assembled_cache[card_id] = (record.updated_at, base)
        return assemble_turn_prompt(
            record.card,
            scan_texts=[m.text for m in recent_messages],
            turn_index=turn_index,
            base=base,
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

        manager 端 cancel_all_for_connection 已关闭识别器并清理登记；
        对应 watchdog 到期后的 cancel 幂等，无副作用。
        """
        self._mobile_asr.cancel_all_for_connection(connection_key)
        for task in tuple(self._mobile_asr_watchdogs.values()):
            if not task.done():
                continue
        # watchdog 与 session 的对应关系由 manager 清理；此处只需确保
        # 已完成任务的表项最终被移除（done 回调与 stop 路径均会清理）。

    async def _voice_mobile_ptt_stop(
        self, params: Mapping[str, Any]
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
            {"conversation_id": conversation_id, "target": "character", "text": text}
        )
        return {"session_id": session_id, "transcript": text}

    async def _voice_mobile_tts_stop(
        self, params: Mapping[str, Any]
    ) -> dict[str, Any]:
        message_id = self._required_string(params, "message_id")
        self._mobile_tts.stop(message_id)
        task = self._mobile_tts_tasks.pop(message_id, None)
        if task is not None and not task.done():
            task.cancel()
        return {"message_id": message_id, "stopped": True}

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
        task = asyncio.create_task(
            self._relay_mobile_tts_task(message),
            name=f"mobile-tts:{message.message_id}",
        )
        self._mobile_tts_tasks[message.message_id] = task
        task.add_done_callback(
            lambda _t: self._mobile_tts_tasks.pop(message.message_id, None)
        )

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
        self._mobile_tts.begin(message.message_id, message.conversation_id)
        end_payload: dict[str, Any] | None = None
        chunk_count = 0
        try:
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
            except Exception:  # noqa: BLE001
                pass
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

    def _persist_pairing_state(self) -> None:
        self.store.set_app_state(
            "remote.pairing_state",
            json.dumps(self.pairing_service.export_state(), ensure_ascii=False),
        )

    async def _remote_issue_code(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """桌面端生成短期配对码（5 分钟有效、一次性）。

        仅桌面 stdin 路径与已鉴权远程连接可调用；未鉴权连接无权生成。
        """
        del params
        code = self.pairing_service.issue_code()
        self._persist_pairing_state()
        return {"code": code, "ttl_seconds": 300}

    async def _remote_pair(self, params: Mapping[str, Any]) -> dict[str, Any]:
        code = str(params.get("code") or "")
        device_name = str(params.get("device_name") or "").strip()
        if not code or not device_name:
            raise ServiceError(
                "remote.pair 需要 code 与 device_name", code="invalid_params"
            )
        try:
            token = self.pairing_service.claim(code, device_name=device_name)
        except PairingError as exc:
            raise ServiceError(str(exc), code=f"pairing_{exc.code}") from exc
        self._persist_pairing_state()
        return {"token": token}

    async def _remote_list_devices(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        return {"devices": self.pairing_service.list_devices()}

    async def _remote_revoke(self, params: Mapping[str, Any]) -> dict[str, Any]:
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
        if revoked == 0:
            raise ServiceError(
                f"没有可撤销的设备：{device_name}", code="device_not_found"
            )
        self._persist_pairing_state()
        return {"device_name": device_name, "revoked_tokens": revoked}

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
        return {
            # engine 由统一的 dialogue.provider 推导，不能与角色模型配置分叉。
            "engine": self._engine_for_provider(provider),
            "dialogue": {
                "provider": provider,
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
        """探测对话服务连接：短请求验证 base_url/model/api_key。"""
        del params
        config = self._load_account_config()
        provider, base_url, api_key, model = self._dialogue_runtime_settings(config)
        if provider == "openai_oauth":
            status = self.codex_auth.status().get("status")
            if status == "logged_in":
                return {"ok": True, "message": "连接正常（OpenAI OAuth）"}
            return {"ok": False, "message": "请先完成 OpenAI OAuth 登录"}
        if not (base_url and api_key and model):
            return {"ok": False, "message": "缺少对话服务配置（Base URL / API Key / 模型）"}
        return await self._probe_dialogue_connection(base_url, api_key, model)

    async def _codex_oauth_start(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        # OAuth 是统一供应商切换的一部分：先把角色和古代机械都切到
        # OpenAI/GPT，并清掉上一家供应商的 Key，再启动浏览器登录。
        updates = {
            "engine": "codex",
            "dialogue.provider": "openai_oauth",
            "dialogue.base_url": "https://api.openai.com/v1",
            "dialogue.model": "gpt-5.6-sol",
        }
        async with self._account_switch_lock:
            await self._save_config_updates_locked(updates)

            if self._demo:
                result = self.codex_auth.start_login()
            else:
                from .engine_factory import resolve_codex_executable

                result = self.codex_auth.start_login(
                    resolve_codex_executable(os.getenv("PAIR_HARNESS_BUNDLED_CODEX_BIN"))
                )
            return {**result, "config": await self._config_get({})}

    async def _codex_oauth_status(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        status = self.codex_auth.status()
        status["account_id"] = self.current_account_id
        return status

    async def _codex_logout(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        return self.codex_auth.logout()

    async def _codex_api_login(self, params: Mapping[str, Any]) -> dict[str, Any]:
        api_key = self._required_string(params, "api_key")
        try:
            result = self.codex_auth.api_login(api_key)
        except ValueError as exc:
            raise ServiceError(str(exc), code="invalid_api_key") from exc
        # OpenAI API Key 是统一供应商选择：角色和古代机械都切到
        # OpenAI-compatible + gpt-5.6-sol，不能只给 Codex 登录态。
        async with self._account_switch_lock:
            await self._save_config_updates_locked(
                {
                    "engine": "codex",
                    "dialogue.provider": "openai_compatible",
                    "dialogue.base_url": "https://api.openai.com/v1",
                    "dialogue.model": "gpt-5.6-sol",
                    "dialogue.api_key": api_key,
                }
            )
            return result

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
        candidate = (
            None
            if self._demo
            else self._build_runtime_candidate(candidate_config)
        )
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
        auth = CodexAuthService(self.store.database.parent, account_id)
        provider, dialogue_base, dialogue_key, dialogue_model_name = (
            self._dialogue_runtime_settings(config)
        )
        engine_choice = self._engine_for_provider(provider)
        self._validate_provider_endpoint(provider, dialogue_base)
        reasoning_effort = config.get("dialogue.reasoning_effort") or "auto"
        if provider == "openai_oauth" and dialogue_model_name:
            from .engine_factory import build_codex_dialogue_model

            dialogue_model = build_codex_dialogue_model(
                codex_auth=auth,
                model=dialogue_model_name,
                codex_bin=os.getenv("PAIR_HARNESS_BUNDLED_CODEX_BIN"),
                reasoning_effort=reasoning_effort,
            )
        elif dialogue_base and dialogue_model_name:
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
            engine_choice=engine_choice,
            codex_auth=auth,
            codex_bin=os.getenv("PAIR_HARNESS_BUNDLED_CODEX_BIN"),
            model=dialogue_model_name or "gpt-5.6-sol",
            base_url=dialogue_base,
            api_key=dialogue_key,
            reasoning_effort=reasoning_effort,
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
        return "deepseek" if provider == "deepseek" else "codex"

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
        """把一次配置写入收敛为一个供应商，拒绝孤立切换执行引擎。"""
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
            updates["dialogue.provider"] = provider
        elif explicit_engine:
            requested_engine = updates["engine"].strip().casefold()
            if requested_engine not in {"codex", "deepseek"}:
                raise ServiceError(
                    f"不支持的编程助手引擎：{updates['engine']}",
                    code="invalid_engine",
                )
            provider = (
                "deepseek"
                if requested_engine == "deepseek"
                else (
                    current_provider
                    if current_provider in {"openai_oauth", "openai_compatible"}
                    else "openai_compatible"
                )
            )
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
            if requested_engine not in {"codex", "deepseek"}:
                raise ServiceError(
                    f"不支持的编程助手引擎：{updates['engine']}",
                    code="invalid_engine",
                )
            if requested_engine != self._engine_for_provider(provider):
                raise ServiceError(
                    "engine 与 dialogue.provider 不一致；角色和古代机械必须使用同一供应商",
                    code="provider_engine_mismatch",
                )
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
            return {"ok": False, "message": f"连接失败：{exc}"}
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

    def _on_dialogue_event(
        self, conversation_id: str, user_message: Any, event: Any
    ) -> None:
        """V0.2：把角色对话增量转发为 message.delta 的 reasoning/speech 通道。

        结构化 JSON 增量只推送干净字段；原始 JSON 进入技术详情（raw），
        绝不进入消息气泡。思考与正文共用一个消息 id，前端才能把它们
        合成一个气泡，正文完成后再由最终消息覆盖临时流。
        """
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
            self.emitter.emit(
                "approval.resolved",
                {
                    "conversation_id": event.conversation_id,
                    "task_id": event.task_id,
                    **dict(event.payload),
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
        if isinstance(self.orchestrator.coding_engine, CodexAppServerEngine):
            self.orchestrator.coding_engine.configure_reasoning(project.reasoning_effort)
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
            engine_choice=(
                "deepseek"
                if detect_provider(dialogue_base).value == "deepseek"
                else "codex"
            ),
            codex_auth=initial_codex_auth,
            codex_bin=settings.codex_bin,
            model=dialogue_model_name,
            base_url=dialogue_base,
            api_key=dialogue_key,
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
