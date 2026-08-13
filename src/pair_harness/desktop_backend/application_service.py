from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Mapping, cast
from uuid import uuid4

from pair_harness.adapters.codex.auth import CodexAuthService
from pair_harness.adapters.codex.engine import CodexAppServerEngine
from pair_harness.adapters.demo import ScriptedCodingEngine, ScriptedDialogueModel
from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.adapters.reviewer import DialogueModelReviewer
from pair_harness.app_paths import AppPaths
from pair_harness.cli import load_dotenv
from pair_harness.config.pairs import PairConfig, load_pair_config, load_prompt
from pair_harness.config.providers import detect_provider, load_reasoning_preset
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    EngineEvent,
    EngineEventType,
    Message,
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

from .commands import DesktopCommand
from .engine_factory import build_coding_engine
from .events import EventEmitter, EventSink, to_jsonable
from .voice_factory import build_real_voice_runtime


logger = logging.getLogger(__name__)


class ServiceError(RuntimeError):
    """可直接返回给前端的业务错误。"""

    def __init__(self, message: str, *, code: str = "service_error") -> None:
        super().__init__(message)
        self.code = code


class ApprovalBroker:
    """把 Orchestrator 的异步审批等待桥接成桌面事件与命令。"""

    def __init__(self, emitter: EventEmitter, active_context: callable) -> None:
        self._emitter = emitter
        self._active_context = active_context
        self._pending: dict[str, dict[str, Any]] = {}

    @property
    def pending(self) -> dict[str, dict[str, Any]]:
        return self._pending

    async def request(
        self, operation: PendingOperation, approval_id: str, reason: str
    ) -> ApprovalDecision:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ApprovalDecision] = loop.create_future()
        conversation_id = self._active_context()
        self._pending[approval_id] = {
            "future": future,
            "conversation_id": conversation_id,
            "operation": operation,
            "reason": reason,
        }
        self._emitter.emit(
            "approval.requested",
            {
                "approval_id": approval_id,
                "conversation_id": conversation_id,
                "operation": operation,
                "reason": reason,
            },
        )
        try:
            return await future
        finally:
            self._pending.pop(approval_id, None)

    def resolve(self, approval_id: str, decision: str) -> None:
        item = self._pending.get(approval_id)
        if item is None:
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

    def cancel_all(self) -> None:
        for item in tuple(self._pending.values()):
            future = cast(asyncio.Future[ApprovalDecision], item["future"])
            if not future.done():
                future.set_result(ApprovalDecision.DENY)

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "approval_id": approval_id,
                "conversation_id": item["conversation_id"],
                "operation": item["operation"],
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
        emitter: EventEmitter,
        approval_broker: ApprovalBroker,
        dialogue_model: Any,
        coding_engine: Any,
        current_project_id: str,
        current_conversation_id: str,
        voice_runtime: VoiceRuntime | None = None,
    ) -> None:
        self.store = store
        self.orchestrator = orchestrator
        self.pair_config = pair_config
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
        if self.voice_runtime is not None:
            await self.voice_runtime.shutdown()
        close_model = getattr(self.dialogue_model, "aclose", None)
        if close_model is not None:
            await close_model()
        transport = getattr(self.coding_engine, "transport", None)
        close_transport = getattr(transport, "close", None)
        if close_transport is not None:
            await close_transport()
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
            "voice.enabled",
            "vad_enabled",
        )
        config: dict[str, str] = {}
        for key in keys:
            value = self.store.get_config(account_id, key)
            if value is not None:
                config[key] = value
        for key in ("dialogue.api_key", "voice.api_key"):
            secret = self.store.get_secret(account_id, key)
            if secret:
                config[key] = secret
        return config

    def _masked(self, value: str | None) -> str:
        """密钥只回显掩码（方案：不回传明文）。"""
        if not value:
            return ""
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}…{value[-4:]}"

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
            except KeyError:
                self.current_conversation_id = ""
        active = self.orchestrator.state.active
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
            "messages": list(to_jsonable(snapshot["messages"])),
            "tool_runs": list(to_jsonable(snapshot["tool_runs"])),
            "turns": self._conversation_turns_payload(self.current_conversation_id),
            "queue_items": self.store.list_queue_items(self.current_conversation_id)
            if self.current_conversation_id
            else [],
            "active_task": to_jsonable(active),
            "busy": active is not None,
            "approvals": self.approval_broker.snapshot(),
            "voice": self._voice_snapshot(),
            "pair": self._pair_payload(self.pair_config),
            # 快照记录最近一条已经发出的事件；next_sequence 指向下一条待发事件。
            # 前端以该值作为 lastSequence，下一条事件必须从它递增一位。
            "sequence": self.emitter.next_sequence - 1,
        }

    def approval_conversation_id(self) -> str:
        """审批始终归属活动任务的原聊天，切换界面聊天不会改写它。"""
        active = self.orchestrator.state.active
        return active.conversation_id if active is not None else self.current_conversation_id

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
        vad_enabled = config.get("vad_enabled") in ("true", "1")
        self._voice_state["enabled"] = enabled
        self._voice_state["vad_enabled"] = vad_enabled
        if not enabled:
            return
        try:
            if vad_enabled:
                await self.voice_runtime.start_listening()
            self.voice_runtime.start_playback()
        except Exception as exc:  # noqa: BLE001 - 语音不可用不阻塞文本主线
            self._on_voice_error(f"语音启动失败：{exc}")

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
        }
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
        root_value = params.get("root_path")
        if not isinstance(root_value, str) or not root_value:
            raise ServiceError("project.create 需要 root_path", code="invalid_params")
        root_path = Path(root_value).expanduser().resolve()
        project = self.store.find_project_by_root_path(str(root_path))
        if project is None or project.account_id != self.current_account_id:
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
        conversation = self._find_or_create_conversation(
            project.project_id,
            pair_id=str(params.get("pair_id") or self.pair_config.pair_id),
        )
        self._select_conversation_context(conversation.conversation_id, emit=True)
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
        self._select_conversation_context(conversation.conversation_id, emit=True)
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
            if isinstance(self.dialogue_model, OpenAICompatibleDialogueModel):
                self.dialogue_model.reasoning_effort = effort
            if isinstance(self.orchestrator.coding_engine, CodexAppServerEngine):
                self.orchestrator.coding_engine.configure_reasoning(effort)
        if root_changed and project_id == self.current_project_id:
            # 重建运行时上下文（项目目录变化）但不回推整份快照
            self._select_conversation_context(self.current_conversation_id, emit=False)
        updated = self._project_payload(self.store.get_project(project_id))
        self.emitter.emit("project.changed", {"project": updated})
        # V0.2：设置类命令返回定向响应，不再用整份 bootstrap 覆盖未修改字段
        return {"project": updated}

    async def _project_archive(self, params: Mapping[str, Any]) -> dict[str, Any]:
        project_id = str(params.get("project_id") or self.current_project_id)
        if not project_id:
            raise ServiceError("没有可归档的项目", code="project_not_found")
        active = self.orchestrator.state.active
        if active is not None and getattr(active, "project_id", None) == project_id:
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
                self._select_conversation_context(conversation.conversation_id, emit=True)
            else:
                if previous_conversation_id:
                    self.orchestrator.close_conversation(previous_conversation_id)
                self.current_project_id = ""
                self.current_conversation_id = ""
        return self.bootstrap()

    async def _conversation_create(self, params: Mapping[str, Any]) -> dict[str, Any]:
        project_id = str(params.get("project_id") or self.current_project_id)
        project = self._current_account_project(project_id)
        title = str(params.get("title") or "新聊天")
        conversation = self.store.create_conversation(
            project_id=project.project_id,
            pair_id=str(params.get("pair_id") or self.pair_config.pair_id),
            title=title,
            account_id=self.current_account_id,
        )
        self._select_conversation_context(conversation.conversation_id, emit=True)
        return self.bootstrap()

    async def _conversation_select(self, params: Mapping[str, Any]) -> dict[str, Any]:
        conversation_id = self._required_string(params, "conversation_id")
        self._current_account_conversation(conversation_id)
        self._select_conversation_context(conversation_id, emit=True)
        return self.bootstrap()

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
            self._select_conversation_context(remaining[0].conversation_id, emit=True)
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
        had_user_messages = any(
            message.source == MessageSource.USER
            for message in self.store.load_conversation(conversation_id)["messages"]
        )
        if target not in {"character", "assistant"}:
            raise ServiceError("target 必须是 character 或 assistant", code="invalid_target")
        mode = params.get("mode")
        if mode is not None:
            if mode not in {"chat", "collaboration"}:
                raise ServiceError("mode 必须是 chat 或 collaboration", code="invalid_mode")
            self._set_conversation_mode(conversation_id, str(mode))
        if conversation_id != self.current_conversation_id:
            self._select_conversation_context(conversation_id, emit=False)

        # V0.2 M2（问题 9）：忙碌时提交先入队（followup 追加 / steer 置队首），
        # 先持久化再向前端确认；派发由回合完成后的自动派发链处理。
        active = self.orchestrator.state.active
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
            conversation_id=conversation_id, text=text, target=target
        )
        # V0.2 M2：同步创建 Turn（accepted），随提交返回 turn_id 供前端追踪；
        # 生命周期事件由后台任务按 started → completed/failed 推进。
        turn = self._register_turn(conversation_id, user_message, target)
        task = asyncio.create_task(
            self._run_submit_chain(
                conversation_id, user_message, target, turn["turn_id"]
            ),
            name=f"turn:{conversation_id}:{user_message.message_id}",
        )
        self._track_turn_task(conversation_id, task)
        if not had_user_messages:
            self._schedule_title_generation(conversation_id, target)
        return {
            "message_id": user_message.message_id,
            "conversation_id": conversation_id,
            "status": "received",
            "target": target,
            "turn_id": turn["turn_id"],
        }

    def _track_turn_task(
        self, conversation_id: str, task: asyncio.Task[None]
    ) -> None:
        """登记后台回合，并在结束时清除对应会话的忙碌标记。"""
        self._turn_tasks.add(task)
        self._conversation_turn_tasks[conversation_id] = task

        def _on_done(completed: asyncio.Task[None]) -> None:
            self._turn_tasks.discard(completed)
            if self._conversation_turn_tasks.get(conversation_id) is completed:
                self._conversation_turn_tasks.pop(conversation_id, None)

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
        self, conversation_id: str, user_message: Any, target: str, turn_id: str
    ) -> None:
        """V0.2 M2：回合 + 队列自动派发链（问题 9）。

        当前回合完成后自动派发队列下一条；失败停止派发（避免连发失败请求）。
        """
        status = await self._run_submit_turn(
            conversation_id, user_message, target, turn_id
        )
        if status == "completed":
            await self._dispatch_from_inbox(conversation_id)

    async def _dispatch_from_inbox(self, conversation_id: str) -> None:
        """V0.2 M2：持久化队列自动派发——processing → 回合 → 完成删除；
        回合失败退回 queued（可重试），不再自动派发后续。"""
        while True:
            item = self.store.peek_queue_item(conversation_id)
            if item is None:
                return
            self.store.set_queue_item_status(item["queue_item_id"], "processing")
            self._emit_queue_changed(conversation_id)
            user_message = await self.orchestrator.submit_user_message(
                conversation_id=item["conversation_id"],
                text=item["text"],
                target=item["target"],
            )
            turn = self._register_turn(
                item["conversation_id"], user_message, item["target"]
            )
            status = await self._run_submit_turn(
                item["conversation_id"], user_message, item["target"], turn["turn_id"]
            )
            if status != "completed":
                self.store.set_queue_item_status(item["queue_item_id"], "queued")
                self._emit_queue_changed(conversation_id)
                return
            self.store.delete_queue_item(item["queue_item_id"])
            self._emit_queue_changed(conversation_id)

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
        self, conversation_id: str, user_message: Any, target: str, turn_id: str
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
                await self.orchestrator.process_direct_input(
                    conversation_id=conversation_id, user_message=user_message
                )
            else:
                await self.orchestrator.process_character_turn(
                    conversation_id=conversation_id, user_message=user_message
                )
        except asyncio.CancelledError:
            result = "cancelled"
            terminal_status = "cancelled"
            self.orchestrator.mark_message_cancelled(
                conversation_id, user_message.message_id
            )
            raise
        except Exception as exc:  # noqa: BLE001 - 回合失败转为可见消息状态
            logger.exception("后台回合失败：%s", conversation_id)
            result = "failed"
            terminal_status = "failed"
            self.orchestrator.mark_message_failed(
                conversation_id, user_message.message_id, str(exc)
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
        del params
        return {"cancelled": await self.orchestrator.cancel_active_task()}

    async def _approval_resolve(self, params: Mapping[str, Any]) -> dict[str, Any]:
        approval_id = self._required_string(params, "approval_id")
        decision = self._required_string(params, "decision")
        self.approval_broker.resolve(approval_id, decision)
        return {"approval_id": approval_id, "accepted": True}

    async def _voice_vad_set(self, params: Mapping[str, Any]) -> dict[str, Any]:
        enabled = bool(params.get("enabled", False))
        self._voice_state["vad_enabled"] = enabled
        if self.voice_runtime is None:
            self._voice_state["error"] = "语音运行时未启用"
        elif enabled:
            await self.voice_runtime.start_listening()
            self.voice_runtime.start_playback()
        else:
            await self.voice_runtime.stop_listening()
        self._emit_voice_changed()
        return {"voice": self._voice_snapshot()}

    async def _voice_ptt_start(self, params: Mapping[str, Any]) -> dict[str, Any]:
        target = str(params.get("target", "character"))
        if self.voice_runtime is None:
            raise ServiceError("语音运行时未启用", code="voice_unavailable")
        await self.voice_runtime.push_to_talk_start(target=target)
        self._voice_state["ptt"] = True
        self._emit_voice_changed()
        return {"voice": self._voice_snapshot()}

    async def _voice_ptt_stop(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        if self.voice_runtime is None:
            raise ServiceError("语音运行时未启用", code="voice_unavailable")
        await self.voice_runtime.push_to_talk_stop()
        self._voice_state["ptt"] = False
        self._emit_voice_changed()
        return {"voice": self._voice_snapshot()}

    async def _voice_tts_stop(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        if self.voice_runtime is not None:
            self.voice_runtime.stop_speaking()
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
        message_id = self._required_string(params, "message_id")
        snapshot = self.store.load_conversation(self.current_conversation_id)
        message = next(
            (m for m in snapshot["messages"] if m.message_id == message_id),
            None,
        )
        if message is None:
            raise ServiceError("消息不存在", code="message_not_found")
        self.voice_runtime.replay_message(message)
        return {"voice": self._voice_snapshot()}

    async def _voice_tts_skip(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        if self.voice_runtime is None:
            raise ServiceError("语音运行时未启用", code="voice_unavailable")
        self.voice_runtime.skip_playing()
        return {"voice": self._voice_snapshot()}

    async def _voice_preview(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """语音试听：按指定文本合成入队；voice_id 缺省取角色音色。

        只允许当前 pair 内置的两个音色（角色/助手），其余一律回退角色音色，
        避免客户端绕过设置页指定任意音色。
        """
        if self.voice_runtime is None:
            raise ServiceError("语音运行时未启用", code="voice_unavailable")
        text = self._required_string(params, "text")
        if not is_readable_text(text):
            raise ServiceError("试听文本为空或只有标点", code="invalid_text")
        builtin = (self.pair_config.character.voice_id, self.pair_config.assistant.voice_id)
        voice_id = params.get("voice_id")
        if voice_id not in builtin:
            voice_id = None
        self.voice_runtime.enqueue_text(text, voice_id=voice_id)
        return {"voice": self._voice_snapshot()}

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

    async def _config_get(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        config = self._load_account_config()
        settings = Settings.from_environment()
        codex = self.codex_auth.status()
        provider, dialogue_base, dialogue_key, dialogue_model_name = (
            self._dialogue_runtime_settings(config)
        )
        return {
            # engine 由统一的 dialogue.provider 推导，不能与角色模型配置分叉。
            "engine": self._engine_for_provider(provider),
            "dialogue": {
                "provider": provider,
                "model": dialogue_model_name,
                "base_url": dialogue_base,
                "api_key_masked": self._masked(dialogue_key),
                "reasoning_effort": "auto",
            },
            "voice": {
                # 语音配置全部由应用内置：API Key / 模型 / 音色 / 服务地址
                # 来自环境变量与 pair 配置，账号配置只保留 enabled / vad_enabled
                "enabled": (
                    config.get("voice.enabled")
                    or ("true" if self.voice_runtime is not None else "false")
                ),
                "base_url": settings.resolved_http_url,
                "api_key_masked": self._masked(settings.dashscope_api_key),
                "asr_model": settings.qwen_asr_model,
                "tts_model": settings.qwen_tts_model,
                "character_voice": self.pair_config.character.voice_id,
                "character_voice_name": self.pair_config.character.name,
                "assistant_voice": self.pair_config.assistant.voice_id,
                "assistant_voice_name": self.pair_config.assistant.name,
                "vad_enabled": config.get("vad_enabled") or "",
            },
            "codex": {
                "status": codex.get("status"),
                "account_label": codex.get("account_label"),
            },
        }

    async def _config_set(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """账号级配置：扁平键写入 provider_configs/secret_refs，立即生效。

        语音的凭据/模型/音色/服务地址由应用内置（环境变量 + pair 配置），
        客户端一律禁止写入，只允许开关类偏好（voice.enabled / vad_enabled）。
        """
        updates = params.get("updates")
        if not isinstance(updates, dict):
            raise ServiceError("updates 必须是对象", code="invalid_params")
        for key, value in updates.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ServiceError("配置键与值必须是字符串", code="invalid_params")
        locked_voice_keys = {
            "voice.api_key",
            "voice.base_url",
            "voice.asr_model",
            "voice.tts_model",
            "character_voice",
            "assistant_voice",
        }
        forbidden = sorted(locked_voice_keys & set(updates))
        if forbidden:
            raise ServiceError(
                f"语音配置由应用内置，不可修改：{', '.join(forbidden)}",
                code="voice_config_locked",
            )
        updates = self._canonicalize_provider_updates(dict(updates))
        secret_keys = {"dialogue.api_key", "voice.api_key"}
        for key, value in updates.items():
            if key in secret_keys:
                self.store.set_secret(self.current_account_id, key, value)
            else:
                self.store.set_config(self.current_account_id, key, value)
        self._account_config = None
        self._rebuild_runtime_for_account(self._load_account_config())
        # 开关类偏好立即同步到 voice 快照（前端 Composer 据此隐藏语音按钮）
        account_config = self._load_account_config()
        if "voice.enabled" in updates:
            self._voice_state["enabled"] = (
                account_config.get("voice.enabled") not in ("false", "0")
            )
            # 关闭总开关：停止聆听并清空待播队列，避免后台继续出声
            if not self._voice_state["enabled"] and self.voice_runtime is not None:
                await self.voice_runtime.stop_listening()
                self.voice_runtime.stop_speaking()
        if "vad_enabled" in updates:
            self._voice_state["vad_enabled"] = (
                account_config.get("vad_enabled") in ("true", "1")
            )
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
        if self._demo:
            result = self.codex_auth.start_login()
        else:
            from .engine_factory import resolve_codex_executable

            result = self.codex_auth.start_login(
                resolve_codex_executable(os.getenv("PAIR_HARNESS_BUNDLED_CODEX_BIN"))
            )
        self.store.set_config(self.current_account_id, "engine", "codex")
        self.store.set_config(self.current_account_id, "dialogue.provider", "openai_oauth")
        self.store.set_config(
            self.current_account_id, "dialogue.base_url", "https://api.openai.com/v1"
        )
        self.store.set_config(self.current_account_id, "dialogue.model", "gpt-5.6-sol")
        self._account_config = None
        self._rebuild_runtime_for_account(self._load_account_config())
        return result

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
        self.store.set_config(self.current_account_id, "engine", "codex")
        self.store.set_config(
            self.current_account_id, "dialogue.provider", "openai_compatible"
        )
        self.store.set_config(
            self.current_account_id, "dialogue.base_url", "https://api.openai.com/v1"
        )
        self.store.set_config(self.current_account_id, "dialogue.model", "gpt-5.6-sol")
        self.store.set_secret(self.current_account_id, "dialogue.api_key", api_key)
        self._account_config = None
        self._rebuild_runtime_for_account(self._load_account_config())
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

    def _rebuild_runtime_for_account(self, config: dict[str, str]) -> None:
        """按账号配置重建对话与编程助手运行时（方案 §M3-2 第 5 步）。

        demo 模式（Scripted）无外部状态，跳过；真实模式替换
        dialogue_model/coding_engine 引用与编排器、审查智能体依赖。
        """
        if self._demo:
            return
        provider, dialogue_base, dialogue_key, dialogue_model_name = (
            self._dialogue_runtime_settings(config)
        )
        engine_choice = self._engine_for_provider(provider)
        if provider != "openai_oauth" and dialogue_base:
            endpoint_provider = detect_provider(dialogue_base).value
            if (provider == "deepseek") != (endpoint_provider == "deepseek"):
                raise ServiceError(
                    "dialogue.provider 与 Base URL 不一致；请同时选择同一供应商的配置",
                    code="provider_endpoint_mismatch",
                )
        if provider == "openai_oauth" and dialogue_model_name:
            from .engine_factory import build_codex_dialogue_model

            self.dialogue_model = build_codex_dialogue_model(
                codex_auth=self.codex_auth,
                model=dialogue_model_name,
                codex_bin=os.getenv("PAIR_HARNESS_BUNDLED_CODEX_BIN"),
            )
            self.orchestrator.dialogue_model = self.dialogue_model  # type: ignore[attr-defined]
            self.orchestrator.reviewer = DialogueModelReviewer(self.dialogue_model)  # type: ignore[attr-defined]
        elif dialogue_base and dialogue_model_name:
            preset = load_reasoning_preset(dialogue_base, dialogue_model_name)
            self.dialogue_model = OpenAICompatibleDialogueModel(
                base_url=dialogue_base,
                api_key=dialogue_key,
                model=dialogue_model_name,
                thinking=preset.default_thinking,
                reasoning_effort="auto",
                temperature=1.0,
            )
            self.orchestrator.dialogue_model = self.dialogue_model  # type: ignore[attr-defined]
            self.orchestrator.reviewer = DialogueModelReviewer(self.dialogue_model)  # type: ignore[attr-defined]
        self.coding_engine = build_coding_engine(
            engine_choice=engine_choice,
            codex_auth=self.codex_auth,
            codex_bin=os.getenv("PAIR_HARNESS_BUNDLED_CODEX_BIN"),
            model=dialogue_model_name or "gpt-5.6-sol",
            base_url=dialogue_base,
            api_key=dialogue_key,
        )
        self.orchestrator.coding_engine = self.coding_engine  # type: ignore[attr-defined]

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
        api_key = config.get("dialogue.api_key") or (
            self._env_dialogue_key() if can_use_env and provider != "openai_oauth" else ""
        )
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
            # 不把上一家供应商的密钥静默带到新供应商；若用户没有在本次
            # 选择中提供新 Key，真实连接会按缺少凭据失败并暴露出来。
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

    async def _switch_account(self, account_id: str) -> None:
        """V0.2 M3：切换账号——停止任务、重建认证与运行时、加载新账号数据。

        步骤（方案 §M3-2）：停止或明确处理当前任务 → 关闭当前模型运行时
        引用 → 按新账号重建 → 切到新账号项目/聊天 → 广播 account.changed
        与整份快照（前端清空旧账号快照）。
        """
        if account_id == self.current_account_id:
            return
        # 1. 停止当前任务（若有）
        try:
            await self.orchestrator.cancel_active_task()
        except Exception:  # noqa: BLE001 - 切换账号不因取消失败而中断
            logger.warning("切换账号时取消任务失败，忽略")
        # 2. 重建认证与运行时（真实模式按账号配置；demo 模式无状态）
        self._set_current_account(account_id)
        config = self._load_account_config()
        self._rebuild_runtime_for_account(config)
        # 3. 切到新账号的项目/聊天
        projects = self.store.list_projects_for_account(account_id)
        if projects:
            self.current_project_id = projects[0].project_id
            conversations = self.store.list_conversations(
                self.current_project_id, account_id=account_id
            )
            self.current_conversation_id = (
                conversations[0].conversation_id if conversations else ""
            )
        else:
            self.current_project_id = ""
            self.current_conversation_id = ""
        self._restore_current_conversation()
        # 4. 广播账号变更与整份快照
        self._emit_account_changed()
        self._emit_state_snapshot()

    # ------------------------------------------------------------------ 状态与事件

    def _on_message(self, message: Message) -> None:
        self.emitter.emit("message.created", {"message": message})

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

        未实际调用审查智能体时不显示审查状态；低风险直接放行、空闲状态
        与普通回复不产生任何 review.* 事件。
        """
        if event in {"review.started", "review.completed", "review.failed"}:
            self.emitter.emit(event, {"conversation_id": self.current_conversation_id, **payload})

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
            message_id = f"assistant:{event.conversation_id}:{event.task_id}"
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
                    "reasoning_streaming": False,
                },
            )
        elif event_type == EngineEventType.ASSISTANT_REASONING_DELTA:
            # 思考与正文共用一个消息 id，工作台沿用角色区的单气泡流式展示。
            message_id = f"assistant:{event.conversation_id}:{event.task_id}"
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
            enqueue(text)
        except Exception:  # noqa: BLE001 - 语音提示不影响工具执行
            logger.exception("编程助手阶段性语音入队失败")

    def _on_execution_started(self) -> None:
        self.emitter.emit(
            "task.busy_changed",
            {"busy": True, "active_task": self.orchestrator.state.active},
        )

    def _on_execution_finished(self) -> None:
        for (conversation_id, _task_id), message_ids in tuple(
            self._streaming_message_ids.items()
        ):
            for message_id in message_ids:
                self.emitter.emit(
                    "message.finalized",
                    {"conversation_id": conversation_id, "message_id": message_id},
                )
        self._streaming_message_ids.clear()
        self._assistant_stream_text.clear()
        self.emitter.emit("task.busy_changed", {"busy": False, "active_task": None})

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

    def _restore_current_conversation(self) -> None:
        if not self.current_conversation_id:
            return
        snapshot = self.store.load_conversation(self.current_conversation_id)
        self.orchestrator.restore_conversation(snapshot)
        for tool_run in snapshot["tool_runs"]:
            self._tool_runs[(tool_run.conversation_id, tool_run.tool_call_id)] = tool_run

    def _select_conversation_context(self, conversation_id: str, *, emit: bool) -> None:
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
            assistant_instructions=load_prompt(selected_pair.assistant.prompt),
            conversation_mode=conversation.last_mode,
        )
        if isinstance(self.dialogue_model, OpenAICompatibleDialogueModel):
            self.dialogue_model.reasoning_effort = (
                None if project.reasoning_effort == "auto" else project.reasoning_effort
            )
        if isinstance(self.orchestrator.coding_engine, CodexAppServerEngine):
            self.orchestrator.coding_engine.configure_reasoning(project.reasoning_effort)
        self._restore_current_conversation()
        if self.voice_runtime is not None:
            self.voice_runtime.set_context(conversation_id, selected_pair)
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

    def _find_or_create_conversation(self, project_id: str, *, pair_id: str):
        conversations = self.store.list_conversations(
            project_id, account_id=self.current_account_id
        )
        if conversations:
            return conversations[0]
        return self.store.create_conversation(
            project_id=project_id,
            pair_id=pair_id,
            title="新聊天",
            account_id=self.current_account_id,
        )

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
    if existing is not None and existing.account_id == account_id:
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
) -> DesktopApplicationService:
    pair_config = load_pair_config(pair_id)
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
    emitter = EventEmitter(event_sink)
    broker = ApprovalBroker(emitter, lambda: service.approval_conversation_id())
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
        pair_id=pair_id,
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
        assistant_instructions=load_prompt(pair_config.assistant.prompt),
    )
    service = DesktopApplicationService(
        store=store,
        orchestrator=orchestrator,
        pair_config=pair_config,
        emitter=emitter,
        approval_broker=broker,
        dialogue_model=dialogue_model,
        coding_engine=coding_engine,
        current_project_id=project.project_id if project is not None else "",
        current_conversation_id=conversation.conversation_id if conversation is not None else "",
    )
    if not demo:
        # 首次引导可从空配置启动；账号级配置存在时立即接管环境默认值。
        service._rebuild_runtime_for_account(service._load_account_config())
    if not demo and settings is not None and settings.dashscope_api_key and conversation is not None:
        try:
            runtime = build_real_voice_runtime(
                settings=settings,
                orchestrator=orchestrator,
                pair_config=pair_config,
                conversation_id=conversation.conversation_id,
                on_vad_state=service._on_voice_state,
                on_asr_partial=service._on_asr_partial,
                on_error=service._on_voice_error,
                on_tts_state=service._on_tts_state,
            )
            service.attach_voice_runtime(runtime)
        except Exception as exc:  # noqa: BLE001 - 文本功能不因语音依赖失败而退出
            service._on_voice_error(f"语音运行时未启用：{exc}")
    elif not demo and settings is not None and not settings.dashscope_api_key:
        service._on_voice_error("真实语音未启用：DASHSCOPE_API_KEY 未配置")
    return service


def build_demo_service(
    *,
    database: Path,
    project_root: Path,
    pair_id: str = "phainon_ancient_machine",
    event_sink: EventSink | None = None,
) -> DesktopApplicationService:
    """创建不需要外部凭据、不执行真实文件操作的 Sidecar 服务。"""
    return _build_service(
        database=database,
        project_root=project_root,
        pair_id=pair_id,
        event_sink=event_sink or (lambda _message: None),
        demo=True,
    )


def build_configured_service(
    *,
    database: Path | None = None,
    project_root: Path,
    pair_id: str = "phainon_ancient_machine",
    event_sink: EventSink | None = None,
    demo: bool = False,
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
    )
