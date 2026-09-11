# ConversationOrchestrator

> God node · 154 connections · `src/pair_harness/core/orchestrator.py`

**Community:** [会话编排器](会话编排器.md)

## Connections by Relation

### calls
- _build_service() `EXTRACTED`
- run_real() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- test_returned_reasoning_is_attached_to_final_messages() `EXTRACTED`
- run_demo() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- test_concurrent_chat_rounds_serialized_in_arrival_order() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- _live_orchestrator() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- make_orchestrator() `EXTRACTED`
- make_orchestrator() `EXTRACTED`
- make_orchestrator() `EXTRACTED`

### contains
- orchestrator.py `EXTRACTED`

### imports
- application_service.py `EXTRACTED`
- cli.py `EXTRACTED`
- voice_runtime.py `EXTRACTED`
- voice_factory.py `EXTRACTED`

### method
- ._execute_once() `EXTRACTED`
- ._message() `EXTRACTED`
- .process_character_turn() `EXTRACTED`
- ._execute() `EXTRACTED`
- .process_direct_input() `EXTRACTED`
- ._retry_character_delegation() `EXTRACTED`
- .__init__() `EXTRACTED`
- ._dialogue_request() `EXTRACTED`
- ._deny_tool_and_notify() `EXTRACTED`
- ._build_runtime_context() `EXTRACTED`
- ._context_or_current() `EXTRACTED`
- ._emit_gate_outcome() `EXTRACTED`
- ._set_message_status() `EXTRACTED`
- .submit_user_message() `EXTRACTED`
- .select_context() `EXTRACTED`
- .handle_direct_input() `EXTRACTED`
- ._emit_event() `EXTRACTED`
- ._turn_index_for() `EXTRACTED`
- ._finalize_segment() `EXTRACTED`
- ._forward_dialogue_event() `EXTRACTED`
- *…and 38 more `method` connection(s) not listed (lowest-degree first to go)*

### references
- .__init__() `EXTRACTED`

### uses
- [DesktopApplicationService](DesktopApplicationService.md) `INFERRED`
- [Message](Message.md) `INFERRED`
- [MessageSource](MessageSource.md) `INFERRED`
- [CharacterTurn](CharacterTurn.md) `INFERRED`
- [ApprovalMode](ApprovalMode.md) `INFERRED`
- ProjectRef `INFERRED`
- PendingOperation `INFERRED`
- MessageKind `INFERRED`
- EngineEvent `INFERRED`
- EngineSessionRef `INFERRED`
- ApprovalDecision `INFERRED`
- TaskRequestDraft `INFERRED`
- TaskRequest `INFERRED`
- EngineEventType `INFERRED`
- DialogueRequest `INFERRED`
- MessageOrigin `INFERRED`
- ApprovalManager `INFERRED`
- DialogueEvent `INFERRED`
- DialogueModel `INFERRED`
- ConversationSummary `INFERRED`
- *…and 50 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*