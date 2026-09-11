# DesktopApplicationService

> God node · 305 connections · `src/pair_harness/desktop_backend/application_service.py`

**Community:** [桌面后端应用服务](桌面后端应用服务.md)

## Connections by Relation

### calls
- _build_service() `EXTRACTED`

### contains
- application_service.py `EXTRACTED`

### imports
- router.py `EXTRACTED`
- desktop_backend/__init__.py `EXTRACTED`

### method
- ._required_string() `EXTRACTED`
- .bootstrap() `EXTRACTED`
- ._select_conversation_context() `EXTRACTED`
- ._load_account_config() `EXTRACTED`
- ._switch_account() `EXTRACTED`
- .__init__() `EXTRACTED`
- ._run_summary_regeneration() `EXTRACTED`
- ._chat_submit() `EXTRACTED`
- ._voice_card_create() `EXTRACTED`
- ._rebuild_voice_runtime_locked() `EXTRACTED`
- ._voice_snapshot() `EXTRACTED`
- ._voice_preview() `EXTRACTED`
- ._build_runtime_candidate() `EXTRACTED`
- ._voice_provision() `EXTRACTED`
- ._emit_voice_changed() `EXTRACTED`
- ._conversation_open() `EXTRACTED`
- ._require_writable_card() `EXTRACTED`
- ._run_auto_summary() `EXTRACTED`
- ._conversation_scope() `EXTRACTED`
- ._current_account_project() `EXTRACTED`
- *…and 219 more `method` connection(s) not listed (lowest-degree first to go)*

### rationale_for
- 无 Qt 的桌面应用服务。 Python 核心对象仍是唯一业务权威；此类只负责把现有能力映射到 Sidecar 命令、快照和增量事件，不让 JSONL… `EXTRACTED`

### references
- [build_demo_service()](build_demo_service.md) `EXTRACTED`
- build_configured_service() `EXTRACTED`
- .__init__() `EXTRACTED`

### uses
- [SQLiteStore](SQLiteStore.md) `INFERRED`
- [ConversationOrchestrator](ConversationOrchestrator.md) `INFERRED`
- [Message](Message.md) `INFERRED`
- [MessageSource](MessageSource.md) `INFERRED`
- [ApprovalMode](ApprovalMode.md) `INFERRED`
- ProjectRef `INFERRED`
- MessageKind `INFERRED`
- EngineEvent `INFERRED`
- OpenAICompatibleDialogueModel `INFERRED`
- PairingService `INFERRED`
- VoiceRuntime `INFERRED`
- EngineEventType `INFERRED`
- CharacterCard `INFERRED`
- DesktopCommand `INFERRED`
- MessageOrigin `INFERRED`
- SpeechRequest `INFERRED`
- CodexAuthService `INFERRED`
- QwenSpeechSynthesizer `INFERRED`
- MobileAudioError `INFERRED`
- DialogueModelReviewer `INFERRED`
- *…and 38 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*