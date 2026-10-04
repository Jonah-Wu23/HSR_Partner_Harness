# Message

> God node · 113 connections · `src/pair_harness/core/contracts.py`

**Community:** [消息契约与会话编排](消息契约与会话编排.md)

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
- sqlite_store.py `EXTRACTED`
- demo.py `EXTRACTED`
- summary.py `EXTRACTED`
- voice_runtime.py `EXTRACTED`
- approval.py `EXTRACTED`
- core/repository.py `EXTRACTED`
- reviewer.py `EXTRACTED`
- projection.py `EXTRACTED`

### inherits
- FrozenModel `EXTRACTED`

### method
- .normalize_unicode() `EXTRACTED`

### references
- ._message() `EXTRACTED`
- .process_character_turn() `EXTRACTED`
- .adjudicate() `EXTRACTED`
- ._run_submit_turn() `EXTRACTED`
- .process_direct_input() `EXTRACTED`
- ._maybe_auto_summary() `EXTRACTED`
- ._dialogue_request() `EXTRACTED`
- ._relay_mobile_tts_task() `EXTRACTED`
- .generate_title() `EXTRACTED`
- ._enqueue_for_playback() `EXTRACTED`
- ._set_message_status() `EXTRACTED`
- ._run_submit_chain() `EXTRACTED`
- .submit_user_message() `EXTRACTED`
- ._review_op() `EXTRACTED`
- ._forward_dialogue_event() `EXTRACTED`
- ._maybe_relay_mobile_tts() `EXTRACTED`
- .review() `EXTRACTED`
- ._roleplay_context() `EXTRACTED`
- ._generate_title() `EXTRACTED`
- .on_message() `EXTRACTED`
- *…and 23 more `references` connection(s) not listed (lowest-degree first to go)*

### uses
- [DesktopApplicationService](DesktopApplicationService.md) `INFERRED`
- [SQLiteStore](SQLiteStore.md) `INFERRED`
- [ConversationOrchestrator](ConversationOrchestrator.md) `INFERRED`
- VoiceRuntime `INFERRED`
- OpenAICompatibleDialogueModel `INFERRED`
- ApprovalManager `INFERRED`
- _RecordingVoiceRuntime `INFERRED`
- DialogueModel `INFERRED`
- ScriptedDialogueModel `INFERRED`
- ConversationSnapshot `INFERRED`
- ConversationOutcome `INFERRED`
- DialogueModelReviewer `INFERRED`
- _message() `INFERRED`
- StateStore `INFERRED`
- ScriptedReviewer `INFERRED`
- test_assistant_messages_never_preempt() `INFERRED`
- Reviewer `INFERRED`
- messages_after_coverage() `INFERRED`
- summary_trigger() `INFERRED`
- validate_summary_coverage() `INFERRED`
- *…and 33 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*