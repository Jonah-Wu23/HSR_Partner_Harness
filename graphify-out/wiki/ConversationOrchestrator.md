# ConversationOrchestrator

> God node · 126 connections · `src/pair_harness/core/orchestrator.py`

**Community:** [消息契约与会话编排](消息契约与会话编排.md)

## Connections by Relation

### calls
- run_real() `EXTRACTED`
- .__init__() `EXTRACTED`
- test_interleaved_output_forms_ordered_assistant_segments() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- run_demo() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- test_task_result_turn_shares_character_turn_context() `EXTRACTED`
- test_returned_reasoning_is_attached_to_final_messages() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- test_concurrent_chat_rounds_serialized_in_arrival_order() `EXTRACTED`
- _make_orchestrator() `EXTRACTED`
- _live_orchestrator() `EXTRACTED`
- make_orchestrator() `EXTRACTED`

### contains
- orchestrator.py `EXTRACTED`

### imports
- application_service.py `EXTRACTED`
- cli.py `EXTRACTED`

### method
- ._execute_once() `EXTRACTED`
- ._message() `EXTRACTED`
- .process_character_turn() `EXTRACTED`
- ._execute() `EXTRACTED`
- .process_direct_input() `EXTRACTED`
- ._dialogue_request() `EXTRACTED`
- .__init__() `EXTRACTED`
- ._deny_tool() `EXTRACTED`
- ._emit_gate_outcome() `EXTRACTED`
- ._set_message_status() `EXTRACTED`
- ._build_runtime_context() `EXTRACTED`
- .submit_user_message() `EXTRACTED`
- ._steer_turn() `EXTRACTED`
- ._finalize_segment() `EXTRACTED`
- ._forward_dialogue_event() `EXTRACTED`
- .handle_character_input() `EXTRACTED`
- ._emit_event() `EXTRACTED`
- ._operation_from_approval_event() `EXTRACTED`
- ._approval_notice() `EXTRACTED`
- ._roleplay_context() `EXTRACTED`
- *…and 30 more `method` connection(s) not listed (lowest-degree first to go)*

### uses
- [DesktopApplicationService](DesktopApplicationService.md) `INFERRED`
- [Message](Message.md) `INFERRED`
- EngineEvent `INFERRED`
- MessageSource `INFERRED`
- EngineSessionRef `INFERRED`
- ApprovalMode `INFERRED`
- ApprovalDecision `INFERRED`
- PendingOperation `INFERRED`
- MessageKind `INFERRED`
- TaskRequest `INFERRED`
- EngineEventType `INFERRED`
- TaskRequestDraft `INFERRED`
- ApprovalManager `INFERRED`
- MessageOrigin `INFERRED`
- CodingEngine `INFERRED`
- DialogueModel `INFERRED`
- DialogueEvent `INFERRED`
- DialogueRequest `INFERRED`
- ExecutionContext `INFERRED`
- direct_input() `INFERRED`
- *…and 37 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*