# Message

> God node · 133 connections · `src/pair_harness/core/contracts.py`

**Community:** [对话上下文与消息模型](对话上下文与消息模型.md)

## Connections by Relation

### calls
- msg() `EXTRACTED`
- msg() `EXTRACTED`

### contains
- contracts.py `EXTRACTED`

### imports
- application_service.py `EXTRACTED`
- orchestrator.py `EXTRACTED`
- openai_compatible.py `EXTRACTED`
- ports.py `EXTRACTED`
- adapters/demo.py `EXTRACTED`
- sqlite_store.py `EXTRACTED`
- summary.py `EXTRACTED`
- voice_runtime.py `EXTRACTED`
- projection.py `EXTRACTED`
- reviewer.py `EXTRACTED`
- approval.py `EXTRACTED`
- context.py `EXTRACTED`

### inherits
- FrozenModel `EXTRACTED`

### method
- .normalize_unicode() `EXTRACTED`

### references
- ._message() `EXTRACTED`
- .process_character_turn() `EXTRACTED`
- .gate() `EXTRACTED`
- .adjudicate() `EXTRACTED`
- .process_direct_input() `EXTRACTED`
- ._dialogue_request() `EXTRACTED`
- ._retry_character_delegation() `EXTRACTED`
- ._relay_mobile_tts_task() `EXTRACTED`
- .generate_title() `EXTRACTED`
- .review() `EXTRACTED`
- ._enqueue_for_playback() `EXTRACTED`
- ._set_message_status() `EXTRACTED`
- .submit_user_message() `EXTRACTED`
- .__init__() `EXTRACTED`
- ._review_op() `EXTRACTED`
- ._maybe_relay_mobile_tts() `EXTRACTED`
- ._forward_dialogue_event() `EXTRACTED`
- .save_message() `EXTRACTED`
- ._write_message_row() `EXTRACTED`
- ._roleplay_context() `EXTRACTED`
- *…and 24 more `references` connection(s) not listed (lowest-degree first to go)*

### uses
- [DesktopApplicationService](DesktopApplicationService.md) `INFERRED`
- [SQLiteStore](SQLiteStore.md) `INFERRED`
- [ConversationOrchestrator](ConversationOrchestrator.md) `INFERRED`
- OpenAICompatibleDialogueModel `INFERRED`
- VoiceRuntime `INFERRED`
- ApprovalManager `INFERRED`
- DialogueModelReviewer `INFERRED`
- DialogueModel `INFERRED`
- ScriptedDialogueModel `INFERRED`
- build_projection() `INFERRED`
- StateStore `INFERRED`
- make_request() `INFERRED`
- ScriptedReviewer `INFERRED`
- _message() `INFERRED`
- _message() `INFERRED`
- _message() `INFERRED`
- _request() `INFERRED`
- validate_summary_coverage() `INFERRED`
- _message() `INFERRED`
- test_mobile_tts_begin_failure_is_reported_not_swallowed() `INFERRED`
- *…and 52 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*