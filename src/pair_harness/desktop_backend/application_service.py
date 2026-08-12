from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Mapping, cast
from uuid import uuid4

from pair_harness.adapters.codex.engine import CodexAppServerEngine
from pair_harness.adapters.codex.transport import JsonlProcessTransport
from pair_harness.adapters.demo import ScriptedCodingEngine, ScriptedDialogueModel
from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.adapters.reviewer import DialogueModelReviewer
from pair_harness.app_paths import AppPaths
from pair_harness.cli import load_dotenv
from pair_harness.config.pairs import PairConfig, load_pair_config, load_prompt
from pair_harness.config.providers import load_reasoning_preset
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
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.core.voice_runtime import VoiceRuntime
from pair_harness.settings import Settings
from pair_harness.storage.sqlite_store import SQLiteStore

from .commands import DesktopCommand
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
        self.current_project_id = current_project_id
        self.current_conversation_id = current_conversation_id
        self.voice_runtime = voice_runtime
        self._shutdown = False
        self._tool_runs: dict[tuple[str, str], ToolRun] = {}
        self._streaming_message_ids: dict[tuple[str, str], set[str]] = {}
        self._title_tasks: set[asyncio.Task[None]] = set()
        self._title_generation_started: set[str] = set()
        self._voice_state: dict[str, Any] = {
            "supported": voice_runtime is not None,
            "vad": "idle",
            "vad_enabled": False,
            "ptt": False,
            "tts": "idle",
            "asr_partial": "",
            "error": None,
        }

        self.orchestrator.on_message = self._on_message
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

    # ------------------------------------------------------------------ 快照

    def bootstrap(self) -> dict[str, Any]:
        projects: list[dict[str, Any]] = []
        for project in self.store.list_projects():
            project_payload = dict(to_jsonable(project))
            project_payload["path_available"] = project.path_available
            project_payload["conversations"] = [
                self._conversation_payload(conversation)
                for conversation in self.store.list_conversations(project.project_id)
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
                snapshot = self.store.load_conversation(self.current_conversation_id)
            except KeyError:
                self.current_conversation_id = ""
        active = self.orchestrator.state.active
        return {
            "projects": projects,
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
            "active_task": to_jsonable(active),
            "busy": active is not None,
            "approvals": self.approval_broker.snapshot(),
            "voice": dict(self._voice_state),
            "pair": self._pair_payload(self.pair_config),
            "sequence": self.emitter.next_sequence,
        }

    def approval_conversation_id(self) -> str:
        """审批始终归属活动任务的原聊天，切换界面聊天不会改写它。"""
        active = self.orchestrator.state.active
        return active.conversation_id if active is not None else self.current_conversation_id

    def attach_voice_runtime(self, runtime: VoiceRuntime) -> None:
        self.voice_runtime = runtime
        self._voice_state["supported"] = True
        self.orchestrator.add_message_listener(runtime.on_message)
        self.emitter.emit("voice.state_changed", {"voice": dict(self._voice_state)})

    async def start_voice(self) -> None:
        if self.voice_runtime is None:
            return
        try:
            await self.voice_runtime.start_listening()
            self.voice_runtime.start_playback()
        except Exception as exc:  # noqa: BLE001 - 语音不可用不阻塞文本主线
            self._on_voice_error(f"语音启动失败：{exc}")

    def _on_voice_state(self, state: str) -> None:
        self._voice_state["vad"] = state
        self._voice_state["tts"] = "playing" if state == "playing" else "idle"
        self.emitter.emit("voice.state_changed", {"voice": dict(self._voice_state)})

    def _on_asr_partial(self, text: str) -> None:
        self._voice_state["asr_partial"] = text
        self.emitter.emit("voice.asr_partial", {"text": text})

    def _on_voice_error(self, message: str) -> None:
        self._voice_state["error"] = message
        self.emitter.emit("voice.state_changed", {"voice": dict(self._voice_state)})

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
            "chat.submit": self._chat_submit,
            "task.cancel": self._task_cancel,
            "approval.resolve": self._approval_resolve,
            "voice.vad_set": self._voice_vad_set,
            "voice.ptt_start": self._voice_ptt_start,
            "voice.ptt_stop": self._voice_ptt_stop,
            "voice.tts_stop": self._voice_tts_stop,
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
        if project is None:
            project = self.store.create_project(
                project_id=str(params.get("project_id") or uuid4()),
                name=str(params.get("name") or root_path.name or root_path),
                root_path=str(root_path),
                approval_mode=str(
                    params.get("approval_mode", ApprovalMode.REQUEST_APPROVAL.value)
                ),
                reasoning_effort=str(params.get("reasoning_effort", "low")),
            )
        conversation = self._find_or_create_conversation(
            project.project_id,
            pair_id=str(params.get("pair_id") or self.pair_config.pair_id),
        )
        self._select_conversation_context(conversation.conversation_id, emit=True)
        return self.bootstrap()

    async def _project_select(self, params: Mapping[str, Any]) -> dict[str, Any]:
        project_id = self._required_string(params, "project_id")
        project = self.store.get_project(project_id)
        conversation_id = params.get("conversation_id")
        if isinstance(conversation_id, str):
            conversation = self.store.get_conversation(conversation_id)
            if conversation.project_id != project.project_id:
                raise ServiceError("聊天不属于指定项目", code="conversation_project_mismatch")
        else:
            conversations = self.store.list_conversations(project.project_id)
            conversation = conversations[0] if conversations else self._find_or_create_conversation(
                project.project_id, pair_id=self.pair_config.pair_id
            )
        self._select_conversation_context(conversation.conversation_id, emit=True)
        return self.bootstrap()

    async def _project_update_settings(self, params: Mapping[str, Any]) -> dict[str, Any]:
        project_id = str(params.get("project_id") or self.current_project_id)
        project = self.store.get_project(project_id)
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
            self.store.update_project_reasoning_effort(project_id, effort)
            if isinstance(self.dialogue_model, OpenAICompatibleDialogueModel):
                self.dialogue_model.reasoning_effort = None if effort == "auto" else effort
        if root_changed and project_id == self.current_project_id:
            self._select_conversation_context(self.current_conversation_id, emit=True)
        else:
            self.emitter.emit(
                "project.changed",
                {"project": self._project_payload(self.store.get_project(project_id))},
            )
        return self.bootstrap()

    async def _project_archive(self, params: Mapping[str, Any]) -> dict[str, Any]:
        project_id = str(params.get("project_id") or self.current_project_id)
        if not project_id:
            raise ServiceError("没有可归档的项目", code="project_not_found")
        active = self.orchestrator.state.active
        if active is not None and getattr(active, "project_id", None) == project_id:
            raise ServiceError("项目正在执行任务，暂时不能归档", code="project_busy")

        self.store.get_project(project_id)
        was_current = project_id == self.current_project_id
        previous_conversation_id = self.current_conversation_id
        self.store.archive_project(project_id)

        if was_current:
            remaining = self.store.list_projects()
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
        project = self.store.get_project(project_id)
        title = str(params.get("title") or "新聊天")
        conversation = self.store.create_conversation(
            project_id=project.project_id,
            pair_id=str(params.get("pair_id") or self.pair_config.pair_id),
            title=title,
        )
        self._select_conversation_context(conversation.conversation_id, emit=True)
        return self.bootstrap()

    async def _conversation_select(self, params: Mapping[str, Any]) -> dict[str, Any]:
        conversation_id = self._required_string(params, "conversation_id")
        self.store.get_conversation(conversation_id)
        self._select_conversation_context(conversation_id, emit=True)
        return self.bootstrap()

    async def _conversation_rename(self, params: Mapping[str, Any]) -> dict[str, Any]:
        conversation_id = str(params.get("conversation_id") or self.current_conversation_id)
        title = self._required_string(params, "title")
        self.store.rename_conversation(conversation_id, title)
        self.emitter.emit(
            "conversation.changed",
            {"conversation": self._conversation_payload(self.store.get_conversation(conversation_id))},
        )
        return self.bootstrap()

    async def _conversation_archive(self, params: Mapping[str, Any]) -> dict[str, Any]:
        conversation_id = str(params.get("conversation_id") or self.current_conversation_id)
        self.store.archive_conversation(conversation_id)
        remaining = self.store.list_conversations(self.current_project_id)
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
        conversation_id = str(params.get("conversation_id") or self.current_conversation_id)
        if not conversation_id:
            raise ServiceError("请先创建或选择项目", code="no_active_conversation")
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
            self.store.update_conversation_mode(conversation_id, str(mode))
        if conversation_id != self.current_conversation_id:
            self._select_conversation_context(conversation_id, emit=False)
        if target == "assistant":
            outcome = await self.orchestrator.handle_direct_input(
                conversation_id=conversation_id, text=text
            )
        else:
            outcome = await self.orchestrator.handle_character_input(
                conversation_id=conversation_id, text=text
            )
        if not had_user_messages:
            self._schedule_title_generation(conversation_id, target)
        return {
            "conversation_id": conversation_id,
            "task_id": outcome.task.task_id if outcome.task is not None else None,
            "status": outcome.receipt.status if outcome.receipt is not None else None,
        }

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
        self.emitter.emit("voice.state_changed", {"voice": self._voice_state})
        return {"voice": dict(self._voice_state)}

    async def _voice_ptt_start(self, params: Mapping[str, Any]) -> dict[str, Any]:
        target = str(params.get("target", "character"))
        if self.voice_runtime is None:
            raise ServiceError("语音运行时未启用", code="voice_unavailable")
        await self.voice_runtime.push_to_talk_start(target=target)
        self._voice_state["ptt"] = True
        self.emitter.emit("voice.state_changed", {"voice": self._voice_state})
        return {"voice": dict(self._voice_state)}

    async def _voice_ptt_stop(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        if self.voice_runtime is None:
            raise ServiceError("语音运行时未启用", code="voice_unavailable")
        await self.voice_runtime.push_to_talk_stop()
        self._voice_state["ptt"] = False
        self.emitter.emit("voice.state_changed", {"voice": self._voice_state})
        return {"voice": dict(self._voice_state)}

    async def _voice_tts_stop(self, params: Mapping[str, Any]) -> dict[str, Any]:
        del params
        if self.voice_runtime is None:
            self._voice_state["tts"] = "idle"
        else:
            self.voice_runtime.stop_speaking()
            self._voice_state["tts"] = "idle"
        self.emitter.emit("voice.state_changed", {"voice": self._voice_state})
        return {"voice": dict(self._voice_state)}

    # ------------------------------------------------------------------ 状态与事件

    def _on_message(self, message: Message) -> None:
        self.emitter.emit("message.created", {"message": message})

    def _on_engine_event(self, event: EngineEvent) -> None:
        event_type = event.type
        if event_type == EngineEventType.ASSISTANT_DELTA:
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
                },
            )
        elif event_type == EngineEventType.ASSISTANT_REASONING_DELTA:
            message_id = f"assistant-reasoning:{event.conversation_id}:{event.task_id}"
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
                },
            )
        elif event_type in (
            EngineEventType.TOOL_STARTED,
            EngineEventType.TOOL_PROGRESS,
            EngineEventType.TOOL_FINISHED,
        ):
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
                title=str(payload.get("title", "工具")),
                summary=str(payload.get("summary", "")),
                details=str(payload.get("details", "")),
            )
        else:
            status = current.status
            if event.type == EngineEventType.TOOL_FINISHED:
                status = cast(Any, str(payload.get("status", status)))
            run = current.model_copy(
                update={
                    "sequence": event.sequence,
                    "status": status,
                    "title": str(payload.get("title", current.title)),
                    "summary": str(payload.get("summary", current.summary)),
                    "details": str(payload.get("details", current.details)),
                }
            )
        self._tool_runs[key] = run
        self.emitter.emit("tool_run.upserted", {"tool_run": run})

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
        self.emitter.emit("task.busy_changed", {"busy": False, "active_task": None})

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
        project = self.store.mark_project_opened(conversation.project_id)
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
        )
        if isinstance(self.dialogue_model, OpenAICompatibleDialogueModel):
            self.dialogue_model.reasoning_effort = (
                None if project.reasoning_effort == "auto" else project.reasoning_effort
            )
        self._restore_current_conversation()
        if self.voice_runtime is not None:
            self.voice_runtime.set_context(conversation_id, selected_pair)
        if emit:
            self.emitter.emit("project.changed", {"project": self._project_payload(project)})
            self.emitter.emit(
                "conversation.changed",
                {"conversation": self._conversation_payload(conversation)},
            )
            self.emitter.emit("state.snapshot", self.bootstrap())

    def _find_or_create_conversation(self, project_id: str, *, pair_id: str):
        conversations = self.store.list_conversations(project_id)
        if conversations:
            return conversations[0]
        return self.store.create_conversation(
            project_id=project_id,
            pair_id=pair_id,
            title="新聊天",
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


def _get_or_create_project(store: SQLiteStore, root_path: Path):
    root_path = root_path.resolve()
    recent = store.list_projects()
    if recent:
        return store.mark_project_opened(recent[0].project_id)
    existing = store.find_project_by_root_path(str(root_path))
    if existing is not None:
        return store.mark_project_opened(existing.project_id)
    if store.list_projects(include_archived=True):
        # 用户已经把全部项目归档时，重启仍保持“暂无项目”，等待用户主动新建。
        return None
    return store.create_project(
        project_id=str(uuid4()),
        name=root_path.name or str(root_path),
        root_path=str(root_path),
    )


def _get_or_create_conversation(store: SQLiteStore, *, project_id: str, pair_id: str):
    conversations = store.list_conversations(project_id)
    if conversations:
        return conversations[0]
    return store.create_conversation(
        project_id=project_id,
        pair_id=pair_id,
        title="新聊天",
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
    project = _get_or_create_project(store, project_root)
    conversation = (
        _get_or_create_conversation(
            store, project_id=project.project_id, pair_id=pair_id
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
        missing = [
            name
            for name, value in (
                ("PAIR_HARNESS_DIALOGUE_BASE_URL", settings.dialogue_base_url),
                ("PAIR_HARNESS_DIALOGUE_API_KEY", settings.dialogue_api_key),
                ("PAIR_HARNESS_DIALOGUE_MODEL", settings.dialogue_model),
            )
            if not value
        ]
        if missing:
            store.close()
            raise ServiceError(
                f"真实后端缺少环境变量：{', '.join(missing)}",
                code="missing_configuration",
            )
        assert settings.dialogue_base_url and settings.dialogue_api_key and settings.dialogue_model
        preset = load_reasoning_preset(settings.dialogue_base_url, settings.dialogue_model)
        dialogue_model = OpenAICompatibleDialogueModel(
            base_url=settings.dialogue_base_url,
            api_key=settings.dialogue_api_key,
            model=settings.dialogue_model,
            thinking=preset.default_thinking,
            reasoning_effort=(
                None
                if project is None or project.reasoning_effort == "auto"
                else project.reasoning_effort
            ),
            temperature=1.0,
        )
        coding_engine = CodexAppServerEngine(JsonlProcessTransport(settings.codex_bin))

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
