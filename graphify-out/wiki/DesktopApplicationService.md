# DesktopApplicationService

> God node · 324 connections · `src/pair_harness/desktop_backend/application_service.py`

**Community:** [运行时装配与配置管理](运行时装配与配置管理.md)

## Connections by Relation

### calls
- _build_service() `EXTRACTED`

### contains
- application_service.py `EXTRACTED`

### imports
- desktop_backend/__main__.py `EXTRACTED`
- router.py `EXTRACTED`

### method
- ._required_string() `EXTRACTED`
- .bootstrap() `EXTRACTED`
- ._load_account_config() `EXTRACTED`
- .__init__() `EXTRACTED`
- ._run_summary() `EXTRACTED`
- ._switch_account() `EXTRACTED`
- ._chat_submit() `EXTRACTED`
- ._voice_preview() `EXTRACTED`
- ._voice_provision() `EXTRACTED`
- ._conversation_open() `EXTRACTED`
- ._require_writable_card() `EXTRACTED`
- ._voice_card_create() `EXTRACTED`
- ._current_account_conversation() `EXTRACTED`
- ._voice_snapshot() `EXTRACTED`
- ._emit_voice_changed() `EXTRACTED`
- ._conversation_scope() `EXTRACTED`
- ._run_submit_turn() `EXTRACTED`
- ._card_set_avatar() `EXTRACTED`
- ._build_runtime_candidate() `EXTRACTED`
- ._dialogue_runtime_settings() `EXTRACTED`
- *…and 220 more `method` connection(s) not listed (lowest-degree first to go)*

### rationale_for
- 无 Qt 的桌面应用服务。 Python 核心对象仍是唯一业务权威；此类只负责把现有能力映射到 Sidecar 命令、快照和增量事件，不让 JSONL… `EXTRACTED`

### references
- build_demo_service() `EXTRACTED`
- build_configured_service() `EXTRACTED`
- .__init__() `EXTRACTED`

### uses
- [SQLiteStore](SQLiteStore.md) `INFERRED`
- [ConversationOrchestrator](ConversationOrchestrator.md) `INFERRED`
- [Message](Message.md) `INFERRED`
- [CommandContext](CommandContext.md) `INFERRED`
- MessageSource `INFERRED`
- EngineEvent `INFERRED`
- ApprovalMode `INFERRED`
- PairingService `INFERRED`
- VoiceRuntime `INFERRED`
- ScriptedCodingEngine `INFERRED`
- CharacterCard `INFERRED`
- OpenAICompatibleDialogueModel `INFERRED`
- MessageKind `INFERRED`
- EngineEventType `INFERRED`
- SpeechRequest `INFERRED`
- ProjectRef `INFERRED`
- CharacterCardRepository `INFERRED`
- ConversationSummary `INFERRED`
- MessageOrigin `INFERRED`
- HsrExtension `INFERRED`
- *…and 56 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*